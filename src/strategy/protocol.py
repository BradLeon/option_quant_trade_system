"""Shared Strategy Protocol & Base Class

Defines the minimal contract for strategies and a convenience
base class with template-method splitting. Used by both backtest
and live trading executors.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from src.strategy.execution_log import ExecutionLog
from src.strategy.models import (
    MarketSnapshot,
    PortfolioState,
    PositionView,
    Signal,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class StrategyProtocol(Protocol):
    """Minimal contract: any object with generate_signals() can be a strategy.

    Replaces the old 3-method lifecycle (evaluate_positions + find_opportunities
    + generate_entry_signals) with a single entry point.

    Used by both BacktestExecutor and LiveStrategyExecutor.
    """

    @property
    def name(self) -> str: ...

    def generate_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]: ...


class Strategy:
    """Convenience base class for strategies (backtest & live).

    Provides a template-method skeleton that splits generate_signals into:
    - on_day_start()          — optional initialization hook
    - compute_exit_signals()  — EXIT / ROLL signals for existing positions
    - compute_entry_signals() — ENTRY signals for new positions
    - on_day_end()            — optional cleanup hook (called by executor)

    Subclasses can override any subset. For complete control, override
    generate_signals() directly (like StrategyProtocol).

    Structured logging:
        All strategies get self.log(step, status, **detail) for recording
        pipeline decisions. The executor reads self.execution_log after
        generate_signals() and renders the trace to CLI.
    """

    def __init__(self) -> None:
        self._trading_day_count: int = 0
        self._last_signal_detail: dict = {}
        self._last_logged_detail_id: int = 0
        self._execution_log: ExecutionLog = ExecutionLog()

    @property
    def name(self) -> str:
        raise NotImplementedError("Subclass must define name property")

    @property
    def execution_log(self) -> ExecutionLog:
        """Structured execution log from the last generate_signals() call."""
        return self._execution_log

    def log(self, step: str, status: str, **detail: Any) -> None:
        """Record a diagnostic entry. Shorthand for self._execution_log.record()."""
        self._execution_log.record(step, status, **detail)

    def generate_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        """Template method: portfolio_log → day_start → exits → entries."""
        self._execution_log.clear()
        self._trading_day_count += 1
        self._last_logged_detail_id = 0

        # ① Auto-log portfolio state
        self._auto_log_portfolio(market, portfolio)

        self.on_day_start(market, portfolio)

        signals: list[Signal] = []

        # ② Exit signals
        exit_signals = self.compute_exit_signals(market, portfolio, data_provider)

        # ③ Auto-log signal context after exit computation
        self._auto_log_signal_context("exit_context")

        self.log(
            "exit_signals", "ok",
            count=len(exit_signals),
            signals=[f"{s.type.value} {s.instrument.symbol} qty={s.target_quantity} | {s.reason}" for s in exit_signals],
        )
        signals.extend(exit_signals)

        # ④ Entry signals
        entry_signals = self.compute_entry_signals(market, portfolio, data_provider)

        # ⑤ Auto-log signal context after entry computation
        self._auto_log_signal_context("entry_context")

        self.log(
            "entry_signals", "ok",
            count=len(entry_signals),
            signals=[f"{s.type.value} {s.instrument.symbol} qty={s.target_quantity} | {s.reason}" for s in entry_signals],
        )
        signals.extend(entry_signals)

        return signals

    # -- Hooks for subclasses --------------------------------------------------

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        """Called at the start of each day before signal computation."""
        pass

    def compute_exit_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        """Generate EXIT / ROLL signals for existing positions."""
        return []

    def compute_entry_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        """Generate ENTRY signals for new positions."""
        return []

    def on_day_end(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> dict:
        """Called by executor after all trades are settled.

        Returns a dict of metrics to store in snapshot.
        Default: returns signal detail from last computation.
        """
        return dict(self._last_signal_detail)

    # -- Auto-logging methods --------------------------------------------------

    def _auto_log_portfolio(
        self, market: MarketSnapshot, portfolio: PortfolioState
    ) -> None:
        """Auto-log portfolio state with formatted position list."""
        positions_desc: list[str] = []

        # Group: options first, then stocks, then cash equivalents
        option_pos = portfolio.get_option_positions()
        stock_pos = [p for p in portfolio.get_stock_positions() if not p.is_cash_equivalent]
        cash_equiv = portfolio.get_cash_equivalent_positions()

        for pos in option_pos:
            positions_desc.append(self._format_position(pos, market))
        for pos in stock_pos:
            positions_desc.append(self._format_position(pos, market))
        for pos in cash_equiv:
            positions_desc.append(self._format_position(pos, market))

        self.log(
            "portfolio", "ok",
            nlv=portfolio.nlv,
            cash=portfolio.cash,
            margin_used=portfolio.margin_used,
            positions=positions_desc,
        )

    def _auto_log_signal_context(self, phase: str) -> None:
        """Auto-log signal detail dict if set by strategy.

        Strategies set self._last_signal_detail in compute_exit_signals()
        or compute_entry_signals(). This method renders it as a log entry.
        Uses _last_logged_detail_id to avoid double-logging the same dict.
        Does NOT clear _last_signal_detail — on_day_end() still needs it.
        """
        detail = self._last_signal_detail
        if not detail:
            return

        detail_id = id(detail)
        if detail_id == self._last_logged_detail_id:
            return  # Already logged this exact dict
        self._last_logged_detail_id = detail_id

        self.log(phase, "info", context=dict(detail))

    @staticmethod
    def _format_position(pos: PositionView, market: MarketSnapshot) -> str:
        """Format a single position for display."""
        parts = [f"{pos.instrument.symbol} qty={pos.quantity}"]
        if pos.dte is not None:
            parts.append(f"DTE={pos.dte}")
        if pos.delta is not None:
            parts.append(f"delta={pos.delta:.2f}")
        if pos.unrealized_pnl != 0:
            parts.append(f"pnl=${pos.unrealized_pnl:,.0f}")
        return " ".join(parts)

    # -- Utilities for subclasses ----------------------------------------------

    def _is_decision_day(self, frequency: int) -> bool:
        """Check if current day is a decision day (every N trading days)."""
        return self._trading_day_count % frequency == 0

    @property
    def requires_synthetic_data(self) -> bool:
        """Whether this strategy needs SyntheticLeapsProvider for historical LEAPS data.

        Override to return True in strategies that use get_option_chain()
        for LEAPS options (DTE > 180 days). Without synthetic data,
        backtests before ThetaData coverage (2023-06) will have no option data.
        """
        return False

    def _rebalance_cooldown_ok(
        self, last_rebalance_day: int, min_interval: int
    ) -> bool:
        """Check if enough trading days have passed since last rebalance."""
        return (self._trading_day_count - last_rebalance_day) >= min_interval


# Backward-compat alias — BacktestStrategy was merged into Strategy
BacktestStrategy = Strategy
