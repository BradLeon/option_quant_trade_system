"""Base types and interfaces for the calculation engine."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


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


@dataclass
class Position:
    """Position information for portfolio calculations.

    Attributes:
        symbol: The ticker symbol of the position.
        quantity: Number of contracts or shares (positive for long, negative for short).
        delta: Position delta (sensitivity to underlying price).
        gamma: Position gamma (rate of change of delta).
        theta: Position theta (time decay per day).
        vega: Position vega (sensitivity to volatility).
        beta: Beta relative to SPY/market.
        market_value: Current market value of the position.
    """

    symbol: str
    quantity: float
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    beta: float | None = None
    market_value: float | None = None


@dataclass
class FundamentalScore:
    """Fundamental analysis score result.

    Attributes:
        score: Overall score (0-100).
        rating: Overall rating signal.
        pe_score: P/E ratio score component.
        growth_score: Revenue growth score component.
        margin_score: Profit margin score component.
        analyst_score: Analyst rating score component.
        details: Additional details or breakdown.
    """

    score: float
    rating: RatingSignal
    pe_score: float | None = None
    growth_score: float | None = None
    margin_score: float | None = None
    analyst_score: float | None = None
    details: dict[str, Any] | None = None


@dataclass
class TrendResult:
    """Trend analysis result.

    Attributes:
        signal: The trend signal (bullish/bearish/neutral).
        strength: Trend strength (-1 to 1, where -1 is strong bearish, 1 is strong bullish).
        short_ma: Short-term moving average value.
        long_ma: Long-term moving average value.
    """

    signal: TrendSignal
    strength: float
    short_ma: float | None = None
    long_ma: float | None = None


@dataclass
class SupportResistance:
    """Support and resistance levels.

    Attributes:
        support: Support price level.
        resistance: Resistance price level.
        support_strength: Strength of support (number of touches or confidence).
        resistance_strength: Strength of resistance.
    """

    support: float
    resistance: float
    support_strength: float | None = None
    resistance_strength: float | None = None
