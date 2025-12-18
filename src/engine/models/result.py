"""Result models for analysis outputs."""

from dataclasses import dataclass
from typing import Any

from src.engine.models.enums import RatingSignal, TrendSignal


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
class VolatilityScore:
    """Volatility analysis score result.

    Evaluates volatility conditions for option trading strategies.
    Higher scores indicate more favorable conditions for option selling.

    Attributes:
        score: Overall score (0-100).
        rating: Overall rating signal for option selling favorability.
        iv_rank: IV Rank (0-100).
        iv_hv_ratio: IV/HV ratio.
        iv_percentile: IV Percentile as decimal (0-1).
        pcr: Put/Call Ratio (excluded from scoring, for reference only).
        details: Additional details including interpretations.
    """

    score: float
    rating: RatingSignal
    iv_rank: float | None = None
    iv_hv_ratio: float | None = None
    iv_percentile: float | None = None
    pcr: float | None = None
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
