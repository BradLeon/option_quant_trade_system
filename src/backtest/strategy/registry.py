"""Backtest Strategy Registry — maps strategy names to classes.

Replaces business/strategy/factory.py for backtest-specific strategies.
Supports both new V2 strategies and legacy (pipeline-based) strategies.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backtest.strategy.protocol import StrategyProtocol
from src.backtest.strategy.signals.sma import SmaComparison
from src.backtest.strategy.signals.momentum import MomentumConfig

logger = logging.getLogger(__name__)


def _create_sma_stock_buy_and_hold(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig
    config = SmaStockConfig(
        name="spy_buy_and_hold_sma_timing",
        sma_period=200,
        comparison=SmaComparison.PRICE_VS_SMA,
        decision_frequency=1,
        **kwargs,
    )
    return SmaStockStrategy(config)


def _create_sma_stock_freq5(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig
    config = SmaStockConfig(
        name="spy_sma200_freq5_timing",
        sma_period=200,
        short_period=50,
        comparison=SmaComparison.SMA_CROSS,
        decision_frequency=5,
        **kwargs,
    )
    return SmaStockStrategy(config)


def _create_sma_leaps(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.sma_leaps import SmaLeapsStrategy, SmaLeapsConfig
    config = SmaLeapsConfig(name="long_leaps_call_sma_timing", **kwargs)
    return SmaLeapsStrategy(config)


def _create_momentum_lev(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedStrategy, MomentumMixedConfig
    config = MomentumMixedConfig(
        name="spy_momentum_lev_vol_target",
        use_stock_component=True,
        cash_interest_enabled=False,
        **kwargs,
    )
    return MomentumMixedStrategy(config)


def _create_leaps_only(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedStrategy, MomentumMixedConfig
    config = MomentumMixedConfig(
        name="spy_leaps_only_vol_target",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return MomentumMixedStrategy(config)


def _create_bull_put_spread(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig
    config = BullPutSpreadConfig(**kwargs)
    return BullPutSpreadStrategy(config)


def _create_short_options_with(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.short_options import ShortOptionsStrategy
    return ShortOptionsStrategy(allow_assignment=True)


def _create_short_options_without(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.short_options import ShortOptionsStrategy
    return ShortOptionsStrategy(allow_assignment=False)


# Registry: name → factory function
_REGISTRY: dict[str, Any] = {
    # New V2 strategies (parameterized)
    "sma_stock": _create_sma_stock_buy_and_hold,
    "sma_leaps": _create_sma_leaps,
    "momentum_mixed": _create_momentum_lev,
    "momentum_leaps_only": _create_leaps_only,

    # Legacy name compatibility (map to V2)
    "spy_buy_and_hold_sma_timing": _create_sma_stock_buy_and_hold,
    "spy_sma200_freq5_timing": _create_sma_stock_freq5,
    "long_leaps_call_sma_timing": _create_sma_leaps,
    "spy_momentum_lev_vol_target": _create_momentum_lev,
    "spy_leaps_only_vol_target": _create_leaps_only,

    # Multi-leg combo strategies
    "bull_put_spread": _create_bull_put_spread,

    # Short options (bridge to legacy pipelines)
    "short_options_with_expire_itm_stock_trade": _create_short_options_with,
    "short_options_without_expire_itm_stock_trade": _create_short_options_without,
    "short_options_with_assignment": _create_short_options_with,
    "short_options_without_assignment": _create_short_options_without,
}


class BacktestStrategyRegistry:
    """Registry for backtest strategies.

    Usage:
        strategy = BacktestStrategyRegistry.create("sma_stock")
        strategy = BacktestStrategyRegistry.create("spy_momentum_lev_vol_target")
    """

    @classmethod
    def create(cls, name: str, **kwargs) -> StrategyProtocol:
        """Create a strategy by name.

        Args:
            name: Strategy name (see get_available_strategies())
            **kwargs: Additional config overrides passed to factory

        Returns:
            Strategy instance implementing StrategyProtocol

        Raises:
            ValueError: If strategy name is unknown
        """
        factory = _REGISTRY.get(name.lower())
        if factory is None:
            available = cls.get_available_strategies()
            raise ValueError(
                f"Unknown strategy: '{name}'. Available: {available}"
            )
        return factory(**kwargs)

    @classmethod
    def get_available_strategies(cls) -> list[str]:
        """Return list of registered strategy names."""
        return sorted(_REGISTRY.keys())

    @classmethod
    def register(cls, name: str, factory) -> None:
        """Register a new strategy factory."""
        _REGISTRY[name.lower()] = factory

    @classmethod
    def is_v2_strategy(cls, name: str) -> bool:
        """Check if a strategy name maps to a V2 (new-style) strategy.

        V2 strategies use generate_signals() single entry point.
        Non-V2 strategies use the legacy 3-method lifecycle.
        """
        strategy = cls.create(name)
        return not getattr(strategy, "uses_legacy_executor", False)
