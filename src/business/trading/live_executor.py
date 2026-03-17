"""Live Strategy Executor — Run V2 strategies against live market data.

V2 architecture: Signal → RiskGuard chain → SignalOrderBuilder → OrderRequest
                 → OrderValidator → TradingProvider → OrderRecord

Split into two phases for IBKR single-connection constraint:
- plan()    → data acquisition + signal generation + order building → ExecutionPlan
- execute() → connect trading channel + submit orders → list[OrderRecord]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.strategy.execution_log import ExecutionLog
from src.strategy.models import MarketSnapshot, PortfolioState, Signal
from src.strategy.protocol import StrategyProtocol
from src.strategy.risk import RiskGuard
from src.business.trading.live_snapshot_builder import LiveSnapshotBuilder
from src.business.trading.models.order import OrderRecord, OrderRequest
from src.business.trading.pipeline import TradingPipeline
from src.business.trading.signal_order_builder import SignalOrderBuilder

logger = logging.getLogger(__name__)


@dataclass
class ExecutionPlan:
    """Output of plan() — everything needed for execute()."""

    orders: list[OrderRequest] = field(default_factory=list)
    roll_pairs: list[tuple[OrderRequest, OrderRequest]] = field(
        default_factory=list
    )
    portfolio: PortfolioState | None = None
    signals: list[Signal] = field(default_factory=list)


@dataclass
class LiveExecutionResult:
    """Result of a single live execution cycle."""

    timestamp: datetime
    signals_generated: int
    signals_after_risk: int
    orders_planned: int
    orders: list[OrderRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    market_snapshot: MarketSnapshot | None = None
    portfolio_state: PortfolioState | None = None
    trace: ExecutionLog = field(default_factory=ExecutionLog)


class LiveStrategyExecutor:
    """Run V2 strategies in live trading mode.

    Two-phase execution for IBKR single-connection constraint:
    - plan():    uses IBKRProvider for data → produces ExecutionPlan
    - execute(): uses TradingPipeline for orders → produces list[OrderRecord]
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
        self._risk_guards = risk_guards or []

        # Auto-add cash sweep ETF symbol
        all_symbols = list(symbols)
        if hasattr(strategy, "_cash_sweep_config"):
            cs_cfg = strategy._cash_sweep_config
            if cs_cfg.enabled and cs_cfg.instrument_symbol not in all_symbols:
                all_symbols.append(cs_cfg.instrument_symbol)
        self._symbols = all_symbols
        self._snapshot_builder = LiveSnapshotBuilder(data_provider, all_symbols)
        self._order_builder = SignalOrderBuilder()

        # Exposed after plan() for deferred execution
        self.last_plan: ExecutionPlan | None = None

    def plan(self) -> tuple[LiveExecutionResult, ExecutionPlan]:
        """Phase A: data acquisition + signal generation + order building.

        Uses IBKRProvider for market data. Call this before disconnecting
        the data provider.

        Returns:
            (result, plan) — result has trace/signals info, plan has orders
        """
        trace = ExecutionLog()
        errors: list[str] = []

        # ── Step 1: Get account portfolio ──
        try:
            portfolio = self._aggregator.get_consolidated_portfolio()
        except Exception as e:
            trace.record("portfolio_state", "error", reason=str(e))
            return (
                self._make_result(0, 0, 0, errors=[str(e)], trace=trace),
                ExecutionPlan(),
            )

        # ── Step 2: Build market snapshot ──
        try:
            market = self._snapshot_builder.build_market_snapshot()
            trace.record(
                "market_snapshot",
                "ok",
                **{sym: f"${p:.2f}" for sym, p in market.prices.items()},
                vix=market.vix,
                risk_free_rate=market.risk_free_rate,
            )
        except Exception as e:
            trace.record("market_snapshot", "error", reason=str(e))
            return (
                self._make_result(0, 0, 0, errors=[str(e)], trace=trace),
                ExecutionPlan(),
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
                "portfolio_state",
                "ok",
                nlv=port_state.nlv,
                cash=port_state.cash,
                margin_used=port_state.margin_used,
                positions=pos_details,
            )
        except Exception as e:
            trace.record("portfolio_state", "error", reason=str(e))
            return (
                self._make_result(
                    0, 0, 0, errors=[str(e)],
                    market_snapshot=market, trace=trace,
                ),
                ExecutionPlan(),
            )

        # ── Step 4: Call strategy ──
        try:
            signals = self._strategy.generate_signals(
                market, port_state, self._dp
            )
            if hasattr(self._strategy, "execution_log"):
                trace.record(
                    "strategy_call", "info", strategy=self._strategy.name
                )
                trace.extend(self._strategy.execution_log)
        except Exception as e:
            trace.record(
                "strategy_call", "error",
                strategy=self._strategy.name, reason=str(e),
            )
            return (
                self._make_result(
                    0, 0, 0, errors=[str(e)],
                    market_snapshot=market, portfolio_state=port_state,
                    trace=trace,
                ),
                ExecutionPlan(),
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
                before=before,
                after=after,
                filtered=before - after,
            )

        filtered_count = len(signals)

        # Sort by priority (EXIT > ROLL > REBALANCE > ENTRY)
        signals.sort(key=lambda s: s.priority, reverse=True)

        # ── Step 6: Build orders (Signal → OrderRequest) ──
        orders = self._order_builder.build(signals, port_state)

        # Separate roll pairs from regular orders
        regular_orders: list[OrderRequest] = []
        roll_pairs: list[tuple[OrderRequest, OrderRequest]] = []

        i = 0
        while i < len(orders):
            if orders[i].context.get("roll_pair") == "close" and i + 1 < len(orders):
                if orders[i + 1].context.get("roll_pair") == "open":
                    roll_pairs.append((orders[i], orders[i + 1]))
                    i += 2
                    continue
            regular_orders.append(orders[i])
            i += 1

        signal_descs = [
            f"{s.type.value} {s.instrument.symbol} qty={s.target_quantity} | {s.reason}"
            for s in signals
        ]
        trace.record(
            "signal_convert",
            "ok",
            signals=signal_descs,
            orders=len(orders),
        )

        plan = ExecutionPlan(
            orders=regular_orders,
            roll_pairs=roll_pairs,
            portfolio=port_state,
            signals=signals,
        )
        self.last_plan = plan

        result = self._make_result(
            signals_generated=signals_count,
            signals_after_risk=filtered_count,
            orders_planned=len(orders),
            market_snapshot=market,
            portfolio_state=port_state,
            trace=trace,
        )

        trace.record(
            "execution", "info",
            mode="PLANNED",
            regular_orders=len(regular_orders),
            roll_pairs=len(roll_pairs),
        )

        return result, plan

    def execute(self, plan: ExecutionPlan) -> list[OrderRecord]:
        """Phase B: submit orders via TradingPipeline.

        Call this after disconnecting the data provider and connecting
        the trading pipeline.

        Args:
            plan: ExecutionPlan from plan()

        Returns:
            List of OrderRecords from submitted orders.
        """
        if plan.portfolio is None:
            logger.error("ExecutionPlan has no portfolio state")
            return []

        all_records: list[OrderRecord] = []

        # Execute regular orders
        if plan.orders:
            records = self._pipeline.execute_orders(
                plan.orders, plan.portfolio, dry_run=False
            )
            all_records.extend(records)

        # Execute roll pairs
        for close_order, open_order in plan.roll_pairs:
            records = self._pipeline.execute_roll_orders(
                close_order, open_order, plan.portfolio, dry_run=False
            )
            all_records.extend(records)

        return all_records

    def run_once(self, dry_run: bool = True) -> LiveExecutionResult:
        """Convenience method: plan + optional execute in one call.

        For backward compat and simple dry-run usage.
        """
        result, plan = self.plan()

        if not dry_run and plan.orders or plan.roll_pairs:
            # Note: caller must handle IBKR connection switching
            # This method assumes pipeline is already connected
            try:
                orders = self.execute(plan)
                result.orders = orders
                order_descs = [
                    f"{o.order.side.value} {o.order.quantity} "
                    f"{o.order.symbol} → {o.order.status.value}"
                    for o in orders
                ]
                result.trace.record(
                    "execution", "ok", mode="LIVE", orders=order_descs
                )
            except Exception as e:
                result.trace.record("execution", "error", reason=str(e))
                result.errors.append(str(e))

        return result

    def _make_result(
        self,
        signals_generated: int,
        signals_after_risk: int,
        orders_planned: int,
        errors: list[str] | None = None,
        market_snapshot: MarketSnapshot | None = None,
        portfolio_state: PortfolioState | None = None,
        trace: ExecutionLog | None = None,
    ) -> LiveExecutionResult:
        return LiveExecutionResult(
            timestamp=datetime.now(),
            signals_generated=signals_generated,
            signals_after_risk=signals_after_risk,
            orders_planned=orders_planned,
            errors=errors or [],
            market_snapshot=market_snapshot,
            portfolio_state=portfolio_state,
            trace=trace or ExecutionLog(),
        )
