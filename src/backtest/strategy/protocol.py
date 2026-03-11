"""Backtest Strategy Protocol & Base Class

Defines the minimal contract for backtest strategies and a convenience
base class with template-method splitting.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from src.backtest.strategy.models import (
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
    """

    @property
    def name(self) -> str: ...

    def generate_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]: ...


class BacktestStrategy:
    """Convenience base class for backtest strategies.

    Provides a template-method skeleton that splits generate_signals into:
    - on_day_start()          — optional initialization hook
    - compute_exit_signals()  — EXIT / ROLL signals for existing positions
    - compute_entry_signals() — ENTRY signals for new positions
    - on_day_end()            — optional cleanup hook (called by executor, not generate_signals)

    Subclasses can override any subset. For complete control, override
    generate_signals() directly (like StrategyProtocol).
    """

    def __init__(self) -> None:
        self._trading_day_count: int = 0
        self._last_signal_detail: dict = {}

    @property
    def name(self) -> str:
        raise NotImplementedError("Subclass must define name property")

    def generate_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        """Template method: day_start → exits → entries."""
        self._trading_day_count += 1
        self.on_day_start(market, portfolio)

        signals: list[Signal] = []
        signals.extend(self.compute_exit_signals(market, portfolio, data_provider))
        signals.extend(self.compute_entry_signals(market, portfolio, data_provider))
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

        Returns a dict of metrics to store in DailySnapshot.strategy_metrics.
        Default: returns signal detail from last computation.
        """
        return dict(self._last_signal_detail)

    @property
    def requires_synthetic_data(self) -> bool:
        """Whether this strategy needs SyntheticLeapsProvider for historical LEAPS data.

        Override to return True in strategies that use get_option_chain()
        for LEAPS options (DTE > 180 days). Without synthetic data,
        backtests before ThetaData coverage (2023-06) will have no option data.
        """
        return False

    # -- Utilities for subclasses ----------------------------------------------

    def _is_decision_day(self, frequency: int) -> bool:
        """Check if current day is a decision day (every N trading days)."""
        return self._trading_day_count % frequency == 0

    def _rebalance_cooldown_ok(
        self, last_rebalance_day: int, min_interval: int
    ) -> bool:
        """Check if enough trading days have passed since last rebalance."""
        return (self._trading_day_count - last_rebalance_day) >= min_interval
