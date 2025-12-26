"""Market sentiment result models.

Dataclasses for market sentiment analysis results, supporting both US and HK markets.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.engine.models.enums import MarketType, TermStructure, TrendSignal, VixZone


@dataclass
class VixTermStructure:
    """VIX term structure analysis result.

    Analyzes the relationship between short-term VIX and longer-term VIX (VIX3M).
    For HK market, uses 2800.HK option IV at different expiries as proxy.

    Interpretation:
    - Contango (ratio > 1.05): Normal market, complacency - bearish warning
    - Backwardation (ratio < 0.95): Fear/panic - bullish opportunity (contrarian)
    - Flat: Neutral market conditions

    Attributes:
        vix: Current VIX value (or VHSI proxy for HK).
        vix_3m: 3-month VIX value (or longer-dated IV for HK).
        ratio: VIX3M / VIX ratio.
        structure: Term structure classification.
        signal: Trading signal interpretation (contrarian).
    """

    vix: float | None
    vix_3m: float | None
    ratio: float | None
    structure: TermStructure
    signal: TrendSignal


@dataclass
class MarketTrend:
    """Market trend analysis result.

    Generalized trend analysis for any market index or ETF.
    Supports SPY, QQQ (US) and 2800.HK, 3032.HK (HK).

    Attributes:
        symbol: Underlying symbol analyzed.
        signal: Trend signal (BULLISH/BEARISH/NEUTRAL).
        strength: Trend strength (-1 to 1, negative=bearish, positive=bullish).
        short_ma: Short-term moving average value.
        long_ma: Long-term moving average value.
        above_200ma: Whether current price is above 200-day MA.
    """

    symbol: str
    signal: TrendSignal
    strength: float
    short_ma: float | None = None
    long_ma: float | None = None
    above_200ma: bool | None = None


@dataclass
class PcrResult:
    """Put/Call Ratio analysis result.

    Contrarian interpretation of Put/Call Ratio.

    Attributes:
        value: PCR value (puts/calls).
        zone: Sentiment zone (extreme_fear/elevated_fear/neutral/elevated_greed/extreme_greed).
        signal: Contrarian trading signal.
        percentile: Historical percentile (0-100) if available.
    """

    value: float | None
    zone: str
    signal: TrendSignal
    percentile: float | None = None


@dataclass
class MarketSentiment:
    """Aggregated market sentiment for a specific market.

    Combines VIX, term structure, trends, and PCR into a composite sentiment view.
    Supports both US and HK markets with market-specific thresholds.

    Composite Score Weights (default):
    - VIX: 25%
    - Term Structure: 15%
    - Primary Trend: 25%
    - Secondary Trend: 15%
    - PCR: 20%

    Attributes:
        market: Market type (US or HK).
        timestamp: Analysis timestamp.

        vix_value: VIX or VHSI proxy value.
        vix_zone: VIX zone classification (LOW/NORMAL/ELEVATED/HIGH/EXTREME).
        vix_signal: VIX-based trading signal (contrarian).
        term_structure: VIX term structure analysis result.

        primary_trend: Primary index trend (SPY for US, 2800.HK for HK).
        secondary_trend: Secondary index trend (QQQ for US, 3032.HK for HK).

        pcr: Put/Call Ratio analysis result.

        composite_score: Overall sentiment score (-100 to 100).
        composite_signal: Overall trading signal.
        favorable_for_selling: Whether conditions favor option selling.

        details: Additional details or breakdown.
    """

    market: MarketType
    timestamp: datetime

    # Volatility indicators
    vix_value: float | None
    vix_zone: VixZone
    vix_signal: TrendSignal
    term_structure: VixTermStructure | None

    # Trend indicators
    primary_trend: MarketTrend | None
    secondary_trend: MarketTrend | None

    # Sentiment indicators
    pcr: PcrResult | None

    # Composite analysis
    composite_score: float
    composite_signal: TrendSignal
    favorable_for_selling: bool

    details: dict[str, Any] | None = None
