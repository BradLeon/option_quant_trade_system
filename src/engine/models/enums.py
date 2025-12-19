"""Engine layer enumerations.

Centralized location for all enums used in the engine layer.
"""

from enum import Enum


class TrendSignal(Enum):
    """Market trend signal."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class RatingSignal(Enum):
    """Analyst rating signal."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class VixZone(Enum):
    """VIX volatility zones."""

    LOW = "low"  # VIX < 15: Market complacency
    NORMAL = "normal"  # VIX 15-20: Normal conditions
    ELEVATED = "elevated"  # VIX 20-25: Increased uncertainty
    HIGH = "high"  # VIX 25-35: Fear/panic
    EXTREME = "extreme"  # VIX > 35: Extreme fear


class PositionSide(Enum):
    """Position side enumeration."""

    LONG = "long"  # Buy
    SHORT = "short"  # Sell
