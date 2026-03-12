"""Concrete backtest strategy implementations."""

from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig
from src.backtest.strategy.versions.sma_leaps import SmaLeapsStrategy, SmaLeapsConfig
from src.backtest.strategy.versions.momentum_mixed import MomentumMixedStrategy, MomentumMixedConfig
from src.backtest.strategy.versions.short_options import ShortPutStrategy, ShortPutConfig, ShortOptionsStrategy
from src.backtest.strategy.versions.spread import BullPutSpreadStrategy, BullPutSpreadConfig

__all__ = [
    "SmaStockStrategy",
    "SmaStockConfig",
    "SmaLeapsStrategy",
    "SmaLeapsConfig",
    "MomentumMixedStrategy",
    "MomentumMixedConfig",
    "ShortPutStrategy",
    "ShortPutConfig",
    "ShortOptionsStrategy",  # backward compat alias
    "BullPutSpreadStrategy",
    "BullPutSpreadConfig",
]
