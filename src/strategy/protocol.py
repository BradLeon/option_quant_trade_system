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
        """Template method: day_start → exits → entries."""
        self._execution_log.clear()
        self._trading_day_count += 1
        self.on_day_start(market, portfolio)

        signals: list[Signal] = []

        exit_signals = self.compute_exit_signals(market, portfolio, data_provider)
        self.log(
            "exit_signals", "ok",
            count=len(exit_signals),
            signals=[f"{s.type.value} {s.instrument.symbol} qty={s.target_quantity} | {s.reason}" for s in exit_signals],
        )
        signals.extend(exit_signals)

        entry_signals = self.compute_entry_signals(market, portfolio, data_provider)
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

    # -- Utilities for subclasses ----------------------------------------------

    def _is_decision_day(self, frequency: int) -> bool:
        """Check if current day is a decision day (every N trading days)."""
        return self._trading_day_count % frequency == 0

    def _rebalance_cooldown_ok(
        self, last_rebalance_day: int, min_interval: int
    ) -> bool:
        """Check if enough trading days have passed since last rebalance."""
        return (self._trading_day_count - last_rebalance_day) >= min_interval
