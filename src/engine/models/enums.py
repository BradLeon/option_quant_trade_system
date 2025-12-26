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


class TermStructureState(Enum):
    """VIX term structure state.

    Term structure = VIX / VIX3M ratio
    - Contango (ratio < 1): Normal, short-term vol lower than long-term
    - Backwardation (ratio > 1): Stressed, short-term vol higher than long-term
    """

    CONTANGO = "contango"  # VIX < VIX3M, normal market
    FLAT = "flat"  # VIX ≈ VIX3M, transitional
    BACKWARDATION = "backwardation"  # VIX > VIX3M, stressed market


class TermStructure(Enum):
    """VIX term structure state (alias for vix_term module).

    Describes the relationship between short-term and longer-term VIX.
    - CONTANGO: VIX3M > VIX (normal market, complacency)
    - FLAT: VIX3M ≈ VIX (transition state)
    - BACKWARDATION: VIX3M < VIX (fear/panic, elevated short-term volatility)
    """

    CONTANGO = "contango"
    FLAT = "flat"
    BACKWARDATION = "backwardation"


class MarketType(Enum):
    """Market type for sentiment analysis."""

    US = "us"
    HK = "hk"
