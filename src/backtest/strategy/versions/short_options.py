"""Short Options Strategy — bridges the old pipeline-based strategies.

Wraps existing ShortOptionsWithExpire / ShortOptionsWithoutExpire as a
LegacyStrategyAdapter, translating the 3-method lifecycle to generate_signals().

This is a Phase 2 bridge: the old pipeline logic is preserved exactly,
wrapped in the new StrategyProtocol interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backtest.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)
from src.backtest.strategy.protocol import BacktestStrategy

logger = logging.getLogger(__name__)


class ShortOptionsStrategy(BacktestStrategy):
    """Bridge strategy wrapping old pipeline-based short option strategies.

    Args:
        allow_assignment: True → uses ShortOptionsWithExpireItmStockTrade
                         False → uses ShortOptionsWithoutExpireItmStockTrade
    """

    def __init__(self, allow_assignment: bool = True) -> None:
        super().__init__()
        self._allow_assignment = allow_assignment
        self._legacy_strategy = None
        self._legacy_initialized = False

    @property
    def name(self) -> str:
        suffix = "with_assignment" if self._allow_assignment else "without_assignment"
        return f"short_options_{suffix}"

    def _ensure_legacy(self) -> Any:
        """Lazily initialize the old strategy."""
        if not self._legacy_initialized:
            from src.business.strategy.factory import StrategyFactory

            name = (
                "short_options_with_expire_itm_stock_trade"
                if self._allow_assignment
                else "short_options_without_expire_itm_stock_trade"
            )
            self._legacy_strategy = StrategyFactory.create(name)
            self._legacy_initialized = True
        return self._legacy_strategy

    def generate_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        """Delegate to old strategy via the legacy 3-method lifecycle.

        This method converts new-style MarketSnapshot/PortfolioState to
        old-style MarketContext + PositionData, calls the old methods,
        and converts old TradeSignals back to new Signals.

        NOTE: For short options, the strategy returns empty Signals here.
        The actual trading is done through the executor's legacy path
        which calls the old evaluate_positions/find_opportunities/generate_entry_signals
        directly. This bridge exists primarily for registration and future migration.
        """
        self._trading_day_count += 1
        # Short options strategy delegates to legacy executor path
        # The new executor will detect this and use the legacy code path
        return []

    @property
    def uses_legacy_executor(self) -> bool:
        """Flag indicating this strategy needs the legacy executor path."""
        return True

    def get_legacy_strategy(self) -> Any:
        """Returns the underlying old-style BaseTradeStrategy instance.

        Called by BacktestExecutor to use the old 3-method execution path.
        """
        return self._ensure_legacy()
