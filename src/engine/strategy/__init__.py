"""Option strategy module."""

# Models (re-exported for convenience)
from src.data.models.option import OptionType
from src.engine.models.enums import PositionSide
from src.engine.models.strategy import OptionLeg, StrategyMetrics, StrategyParams

# Base class
from src.engine.strategy.base import OptionStrategy

# Strategy implementations
from src.engine.strategy.covered_call import CoveredCallStrategy
from src.engine.strategy.short_put import ShortPutStrategy
from src.engine.strategy.strangle import ShortStrangleStrategy

__all__ = [
    # Models (re-exported for convenience)
    "OptionType",
    "PositionSide",
    "OptionLeg",
    "StrategyParams",
    "StrategyMetrics",
    # Base class
    "OptionStrategy",
    # Strategies
    "ShortPutStrategy",
    "CoveredCallStrategy",
    "ShortStrangleStrategy",
]
