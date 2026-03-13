"""Backtest Strategy Registry — maps strategy names to factory functions.

All strategies are native V2 implementations using the generate_signals()
single entry point.
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


def _create_leaps_baseline(**kwargs) -> StrategyProtocol:
    """Baseline LEAPS (identical to leaps_only, for A/B comparison)."""
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedStrategy, MomentumMixedConfig
    config = MomentumMixedConfig(
        name="leaps_baseline",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return MomentumMixedStrategy(config)


def _create_leaps_theta_guard(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.leaps_variants import LeapsThetaGuardStrategy
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedConfig
    config = MomentumMixedConfig(
        name="leaps_theta_guard",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return LeapsThetaGuardStrategy(config)


def _create_leaps_vega_guard(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.leaps_variants import LeapsVegaGuardStrategy
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedConfig
    config = MomentumMixedConfig(
        name="leaps_vega_guard",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return LeapsVegaGuardStrategy(config)


def _create_leaps_rebal_down_only(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.leaps_variants import LeapsRebalDownOnlyStrategy
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedConfig
    config = MomentumMixedConfig(
        name="leaps_rebal_down_only",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return LeapsRebalDownOnlyStrategy(config)


def _create_leaps_stop_loss(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.leaps_variants import LeapsStopLossStrategy
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedConfig
    config = MomentumMixedConfig(
        name="leaps_stop_loss",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return LeapsStopLossStrategy(config)


def _create_leaps_dd_deleverage(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.leaps_variants import LeapsDrawdownDeleverageStrategy
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedConfig
    config = MomentumMixedConfig(
        name="leaps_dd_deleverage",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return LeapsDrawdownDeleverageStrategy(config)


def _create_momentum_mixed_v2(**kwargs) -> StrategyProtocol:
    """LEAPS V2: Theta Guard (roll_dte=90) + Vega Guard (VIX spike reduce)."""
    from src.backtest.strategy.versions.momentum_mixed_v2 import (
        MomentumMixedV2Strategy,
        MomentumMixedV2Config,
    )
    config = MomentumMixedV2Config(
        name="momentum_mixed_v2",
        use_stock_component=False,
        cash_interest_enabled=True,
        **kwargs,
    )
    return MomentumMixedV2Strategy(config)


def _create_leaps_only_cash_sweep(**kwargs) -> StrategyProtocol:
    """LEAPS-only with active SHV cash sweep (replaces passive interest)."""
    from src.backtest.strategy.versions.momentum_mixed import MomentumMixedStrategy, MomentumMixedConfig
    from src.strategy.cash_sweep import CashSweepConfig
    config = MomentumMixedConfig(
        name="spy_leaps_only_cash_sweep",
        use_stock_component=False,
        cash_interest_enabled=False,
        cash_sweep_config=CashSweepConfig(enabled=True, instrument_symbol="SHV"),
        **kwargs,
    )
    return MomentumMixedStrategy(config)


def _create_leaps_v2_cash_sweep(**kwargs) -> StrategyProtocol:
    """LEAPS V2 with active SHV cash sweep."""
    from src.backtest.strategy.versions.momentum_mixed_v2 import (
        MomentumMixedV2Strategy,
        MomentumMixedV2Config,
    )
    from src.strategy.cash_sweep import CashSweepConfig
    config = MomentumMixedV2Config(
        name="leaps_v2_cash_sweep",
        use_stock_component=False,
        cash_interest_enabled=False,
        cash_sweep_config=CashSweepConfig(enabled=True, instrument_symbol="SHV"),
        **kwargs,
    )
    return MomentumMixedV2Strategy(config)


def _create_bull_put_spread(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig
    config = BullPutSpreadConfig(**kwargs)
    return BullPutSpreadStrategy(config)


def _create_bull_put_spread_more(**kwargs) -> StrategyProtocol:
    """More spreads variant: 8 spreads instead of 10 default."""
    from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig
    overrides = dict(name="bull_put_spread_more", max_spreads=8, spread_width=10.0)
    overrides.update(kwargs)
    return BullPutSpreadStrategy(BullPutSpreadConfig(**overrides))


def _create_bull_put_spread_tight(**kwargs) -> StrategyProtocol:
    """Tighter profit target: 65% instead of 50%."""
    from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig
    overrides = dict(name="bull_put_spread_tight", profit_target_pct=0.65, spread_width=10.0)
    overrides.update(kwargs)
    return BullPutSpreadStrategy(BullPutSpreadConfig(**overrides))


def _create_bull_put_spread_wide(**kwargs) -> StrategyProtocol:
    """Wider spread: $15 width instead of $5."""
    from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig
    overrides = dict(name="bull_put_spread_wide", spread_width=15.0)
    overrides.update(kwargs)
    return BullPutSpreadStrategy(BullPutSpreadConfig(**overrides))


def _create_bull_put_spread_conservative(**kwargs) -> StrategyProtocol:
    """Conservative: fewer spreads, tighter DTE, lower delta."""
    from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig
    overrides = dict(
        name="bull_put_spread_conservative",
        max_spreads=3,
        spread_width=5.0,
        short_put_delta=0.20,
        target_dte_min=30,
        target_dte_max=45,
    )
    overrides.update(kwargs)
    return BullPutSpreadStrategy(BullPutSpreadConfig(**overrides))


def _create_short_put_with(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.short_options import ShortPutStrategy, ShortPutConfig
    return ShortPutStrategy(ShortPutConfig(
        name="short_put_with_assignment",
        allow_assignment=True,
        technical_enabled=True,
        win_probability_enabled=False,
    ))


def _create_short_put_without(**kwargs) -> StrategyProtocol:
    from src.backtest.strategy.versions.short_options import ShortPutStrategy, ShortPutConfig
    return ShortPutStrategy(ShortPutConfig(
        name="short_put_without_assignment",
        allow_assignment=False,
        technical_enabled=False,
        win_probability_enabled=True,
    ))


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

    # LEAPS risk improvement variants (A/B testing)
    "leaps_baseline": _create_leaps_baseline,
    "leaps_theta_guard": _create_leaps_theta_guard,
    "leaps_vega_guard": _create_leaps_vega_guard,
    "leaps_rebal_down_only": _create_leaps_rebal_down_only,
    "leaps_stop_loss": _create_leaps_stop_loss,
    "leaps_dd_deleverage": _create_leaps_dd_deleverage,

    # LEAPS V2 (combined V1+V2 improvements)
    "momentum_mixed_v2": _create_momentum_mixed_v2,
    "leaps_v2": _create_momentum_mixed_v2,

    # LEAPS with active cash sweep (SHV ETF)
    "leaps_cash_sweep": _create_leaps_only_cash_sweep,
    "leaps_v2_cash_sweep": _create_leaps_v2_cash_sweep,

    # Multi-leg combo strategies
    "bull_put_spread": _create_bull_put_spread,
    "bull_put_spread_more": _create_bull_put_spread_more,
    "bull_put_spread_tight": _create_bull_put_spread_tight,
    "bull_put_spread_wide": _create_bull_put_spread_wide,
    "bull_put_spread_conservative": _create_bull_put_spread_conservative,

    # Short put (native V2)
    "short_put_with_assignment": _create_short_put_with,
    "short_put_without_assignment": _create_short_put_without,
    "short_options_with_expire_itm_stock_trade": _create_short_put_with,
    "short_options_without_expire_itm_stock_trade": _create_short_put_without,
    "short_options_with_assignment": _create_short_put_with,
    "short_options_without_assignment": _create_short_put_without,
}


class BacktestStrategyRegistry:
    """Registry for backtest strategies.

    Usage:
        strategy = BacktestStrategyRegistry.create("sma_stock")
        strategy = BacktestStrategyRegistry.create("short_options_with_assignment")
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
