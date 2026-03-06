"""Option pricing module."""

# Models (re-exported for convenience)
from src.data.models.option import OptionType
from src.engine.models.enums import PositionSide
from src.engine.models.pricing import OptionLeg, PricingMetrics, PricingParams

# Base class
from src.engine.pricing.base import OptionPricer

# Pricer implementations
from src.engine.pricing.covered_call import CoveredCallPricer
from src.engine.pricing.long_call import LongCallPricer
from src.engine.pricing.long_put import LongPutPricer
from src.engine.pricing.short_call import ShortCallPricer
from src.engine.pricing.short_put import ShortPutPricer
from src.engine.pricing.strangle import ShortStranglePricer

# Factory pattern
from src.engine.pricing.factory import (
    PricerInstance,
    create_pricers_from_position,
)

__all__ = [
    # Models (re-exported for convenience)
    "OptionType",
    "PositionSide",
    "OptionLeg",
    "PricingParams",
    "PricingMetrics",
    # Base class
    "OptionPricer",
    # Pricers
    "ShortPutPricer",
    "ShortCallPricer",
    "CoveredCallPricer",
    "ShortStranglePricer",
    "LongPutPricer",
    "LongCallPricer",
    # Factory
    "PricerInstance",
    "create_pricers_from_position",
]
