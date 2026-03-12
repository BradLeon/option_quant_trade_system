"""Live Strategy Executor — Run V2 strategies against live market data.

Mirrors BacktestExecutor's daily loop but sources data from real-time
providers and executes via TradingPipeline → IBKR.

Produces a structured ExecutionLog that the CLI renders step-by-step,
regardless of whether signals or orders are generated.

Usage:
    from src.strategy import StrategyProtocol
    from src.backtest.strategy import BacktestStrategyRegistry

    strategy = BacktestStrategyRegistry.create("short_put_with_assignment")

    executor = LiveStrategyExecutor(
        strategy=strategy,
        data_provider=unified_provider,
        account_aggregator=aggregator,
        trading_pipeline=pipeline,
        symbols=["SPY", "AAPL"],
    )
    result = executor.run_once(dry_run=True)
    print(result.trace.format_text())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.data.models.account import (
    AssetType,
    ConsolidatedPortfolio,
)
from src.strategy.execution_log import ExecutionLog
from src.strategy.models import MarketSnapshot, PortfolioState, Signal
from src.strategy.protocol import StrategyProtocol
from src.strategy.risk import RiskGuard
from src.business.trading.account_bridge import portfolio_to_account_state
from src.business.trading.live_signal_converter import LiveSignalConverter
from src.business.trading.live_snapshot_builder import LiveSnapshotBuilder
from src.business.trading.models.decision import PositionContext
from src.business.trading.models.order import OrderRecord
from src.business.trading.pipeline import TradingPipeline

logger = logging.getLogger(__name__)


@dataclass
class LiveExecutionResult:
    """Result of a single live execution cycle."""

    timestamp: datetime
    signals_generated: int
    signals_after_risk: int
    decisions_count: int
    orders: list[OrderRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    market_snapshot: MarketSnapshot | None = None
    portfolio_state: PortfolioState | None = None
    trace: ExecutionLog = field(default_factory=ExecutionLog)


class LiveStrategyExecutor:
    """Run V2 strategies in live trading mode.

    Orchestrates the full cycle with structured logging at every step:
    1. Build MarketSnapshot from live data
    2. Build PortfolioState from IBKR account
    3. Call strategy.generate_signals() (same as backtest)
    4. Apply RiskGuard chain
    5. Convert Signal → TradingDecision
    6. Execute via TradingPipeline → IBKR

    The strategy instance is identical to what runs in backtest —
    zero modification required.
    """

    def __init__(
        self,
        strategy: StrategyProtocol,
        data_provider: Any,
        account_aggregator: Any,
        trading_pipeline: TradingPipeline,
        symbols: list[str],
        risk_guards: list[RiskGuard] | None = None,
    ) -> None:
        self._strategy = strategy
        self._dp = data_provider
        self._aggregator = account_aggregator
        self._pipeline = trading_pipeline
        self._symbols = symbols
        self._risk_guards = risk_guards or []
        self._snapshot_builder = LiveSnapshotBuilder(data_provider, symbols)
        self._signal_converter = LiveSignalConverter()

        # Exposed after run_once() for deferred execution
        self.last_decisions: list[Any] = []
        self.last_account_state: Any = None

    def run_once(self, dry_run: bool = True) -> LiveExecutionResult:
        """Execute one cycle of strategy evaluation + trading.

        Returns LiveExecutionResult with a structured trace of every step.
        """
        trace = ExecutionLog()
        errors: list[str] = []

        # ── Step 1: Get account portfolio ──
        try:
            portfolio = self._aggregator.get_consolidated_portfolio()
        except Exception as e:
            trace.record("portfolio_state", "error", reason=str(e))
            return LiveExecutionResult(
                timestamp=datetime.now(),
                signals_generated=0, signals_after_risk=0, decisions_count=0,
                errors=[str(e)], trace=trace,
            )

        # ── Step 2: Build market snapshot ──
        try:
            market = self._snapshot_builder.build_market_snapshot()
            trace.record(
                "market_snapshot", "ok",
                **{sym: f"${p:.2f}" for sym, p in market.prices.items()},
                vix=market.vix,
                risk_free_rate=market.risk_free_rate,
            )
        except Exception as e:
            trace.record("market_snapshot", "error", reason=str(e))
            return LiveExecutionResult(
                timestamp=datetime.now(),
                signals_generated=0, signals_after_risk=0, decisions_count=0,
                errors=[str(e)], trace=trace,
            )

        # ── Step 3: Build portfolio state ──
        try:
            port_state = self._snapshot_builder.build_portfolio_state(portfolio)
            pos_details = []
            for p in port_state.positions:
                desc = f"{p.instrument.symbol} qty={p.quantity}"
                if p.unrealized_pnl:
                    desc += f" pnl=${p.unrealized_pnl:,.0f}"
                pos_details.append(desc)
            trace.record(
                "portfolio_state", "ok",
                nlv=port_state.nlv, cash=port_state.cash,
                margin_used=port_state.margin_used,
                positions=pos_details,
            )
        except Exception as e:
            trace.record("portfolio_state", "error", reason=str(e))
            return LiveExecutionResult(
                timestamp=datetime.now(),
                signals_generated=0, signals_after_risk=0, decisions_count=0,
                errors=[str(e)], market_snapshot=market, trace=trace,
            )

        # ── Step 4: Call strategy ──
        try:
            signals = self._strategy.generate_signals(
                market, port_state, self._dp
            )
            # Merge strategy's execution log into our trace
            if hasattr(self._strategy, 'execution_log'):
                trace.record("strategy_call", "info", strategy=self._strategy.name)
                trace.extend(self._strategy.execution_log)
        except Exception as e:
            trace.record("strategy_call", "error",
                         strategy=self._strategy.name, reason=str(e))
            return LiveExecutionResult(
                timestamp=datetime.now(),
                signals_generated=0, signals_after_risk=0, decisions_count=0,
                errors=[str(e)], market_snapshot=market,
                portfolio_state=port_state, trace=trace,
            )

        signals_count = len(signals)

        # ── Step 5: Risk guard chain ──
        for guard in self._risk_guards:
            before = len(signals)
            signals = guard.check(signals, port_state, market)
            after = len(signals)
            guard_name = type(guard).__name__
            trace.record(
                f"risk_guards:{guard_name}",
                "pass" if after == before else "info",
                before=before, after=after,
                filtered=before - after,
            )

        filtered_count = len(signals)

        # Sort by priority (EXIT > ROLL > REBALANCE > ENTRY)
        signals.sort(key=lambda s: s.priority, reverse=True)

        # ── Step 6: Convert Signal → TradingDecision ──
        account_state = portfolio_to_account_state(portfolio)
        self.last_account_state = account_state
        position_map = self._build_position_map(portfolio)
        decisions = self._signal_converter.convert(
            signals, account_state, position_map
        )
        self.last_decisions = decisions

        signal_descs = [
            f"{s.type.value} {s.instrument.symbol} qty={s.target_quantity} | {s.reason}"
            for s in signals
        ]
        trace.record(
            "signal_convert", "ok",
            signals=signal_descs,
            decisions=len(decisions),
        )

        # ── Step 7: Execute ──
        orders: list[OrderRecord] = []
        if decisions and not dry_run:
            try:
                orders = self._pipeline.execute_decisions(
                    decisions, account_state, dry_run=False
                )
                order_descs = [
                    f"{o.order.side.value} {o.order.quantity} {o.order.symbol} → {o.order.status.value}"
                    for o in orders
                ]
                trace.record("execution", "ok", mode="LIVE", orders=order_descs)
            except Exception as e:
                trace.record("execution", "error", reason=str(e))
                errors.append(str(e))
        else:
            trace.record("execution", "info",
                         mode="DRY-RUN", decisions=len(decisions))

        return LiveExecutionResult(
            timestamp=datetime.now(),
            signals_generated=signals_count,
            signals_after_risk=filtered_count,
            decisions_count=len(decisions),
            orders=orders,
            errors=errors,
            market_snapshot=market,
            portfolio_state=port_state,
            trace=trace,
        )

    def _build_position_map(
        self, portfolio: ConsolidatedPortfolio
    ) -> dict[str, PositionContext]:
        """Build position_id → PositionContext map for EXIT/ROLL signal resolution."""
        position_map: dict[str, PositionContext] = {}

        for ap in portfolio.positions:
            if ap.asset_type == AssetType.CASH:
                continue

            instrument = self._snapshot_builder._make_instrument(ap)
            position_id = instrument.symbol

            position_map[position_id] = PositionContext(
                position_id=position_id,
                symbol=ap.symbol,
                underlying=ap.underlying or ap.symbol,
                option_type=ap.option_type,
                strike=ap.strike,
                expiry=ap.expiry,
                trading_class=ap.trading_class,
                con_id=ap.con_id,
                quantity=ap.quantity,
                avg_cost=ap.avg_cost,
                current_price=self._snapshot_builder._calc_per_unit_price(ap),
                market_value=ap.market_value,
                unrealized_pnl=ap.unrealized_pnl,
                delta=ap.delta,
                gamma=ap.gamma,
                theta=ap.theta,
                vega=ap.vega,
            )

        return position_map
