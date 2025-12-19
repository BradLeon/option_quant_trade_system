"""Engine layer data models.

This module provides data models for the calculation engine layer,
designed to work with data layer models (src.data.models) while
providing clean interfaces for engine functions.

Models:
    BSParams: Black-Scholes calculation parameters
    Position: Portfolio position information
    OptionLeg: Single option leg in a strategy
    StrategyParams: Common parameters for strategy calculations
    StrategyMetrics: Calculated metrics for a strategy
    FundamentalScore: Fundamental analysis score result
    VolatilityScore: Volatility analysis score result
    TechnicalScore: Technical analysis score result
    TrendResult: Trend analysis result
    SupportResistance: Support and resistance levels

Enums:
    TrendSignal: Market trend signal
    RatingSignal: Analyst rating signal
    VixZone: VIX volatility zones
    OptionType: Call or Put (from data layer)
    PositionSide: Long or Short
"""

from src.data.models.option import Greeks, OptionType  # 统一使用 data 层定义
from src.engine.models.bs_params import BSParams
from src.engine.models.enums import (
    PositionSide,
    RatingSignal,
    TrendSignal,
    VixZone,
)
from src.engine.models.position import Position
from src.engine.models.result import (
    FundamentalScore,
    SupportResistance,
    TechnicalScore,
    TechnicalSignal,
    TrendResult,
    VolatilityScore,
)
from src.engine.models.strategy import OptionLeg, StrategyMetrics, StrategyParams

__all__ = [
    # B-S params
    "BSParams",
    # Enums
    "TrendSignal",
    "RatingSignal",
    "VixZone",
    "OptionType",
    "PositionSide",
    # Greeks (from data layer)
    "Greeks",
    # Position
    "Position",
    # Results
    "FundamentalScore",
    "VolatilityScore",
    "TechnicalScore",
    "TechnicalSignal",
    "TrendResult",
    "SupportResistance",
    # Strategy
    "OptionLeg",
    "StrategyParams",
    "StrategyMetrics",
]
