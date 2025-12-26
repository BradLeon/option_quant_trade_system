"""Market sentiment aggregation.

Provides unified sentiment analysis for US and HK markets.
Combines VIX, term structure, trends, and PCR into composite scores.
"""

from datetime import datetime

from src.engine.models.enums import MarketType, TrendSignal, VixZone
from src.engine.models.sentiment import (
    MarketSentiment,
    MarketTrend,
    PcrResult,
)

from src.engine.account.sentiment.vix import (
    get_vix_zone,
    interpret_vix,
    is_vix_favorable_for_selling,
)
from src.engine.account.sentiment.vix_term import analyze_term_structure
from src.engine.account.sentiment.market_trend import analyze_market_trend
from src.engine.account.sentiment.pcr import get_pcr_zone, interpret_pcr


# Market-specific configurations
HK_CONFIG = {
    # VHSI data source (Futu: 800125.HK, IBKR: use 2800.HK IV as proxy)
    "vhsi_symbol": "800125.HK",  # VHSI index (Futu only)
    "vix_proxy": "2800.HK",  # IV from 2800.HK options as VHSI proxy (IBKR fallback)
    # HSI data sources
    "primary_index": "800000.HK",  # Hang Seng Index (Futu)
    "primary_index_yahoo": "^HSI",  # Hang Seng Index (Yahoo fallback)
    "primary_index_etf": "2800.HK",  # Tracker Fund ETF (for option data)
    # HSTECH data sources
    "secondary_index": "HSTECH.HK",  # Hang Seng TECH Index (Yahoo)
    "secondary_index_etf": "3032.HK",  # HSTECH ETF (for option data)
    "pcr_symbol": "2800.HK",
    # Adjusted thresholds for HK market (generally higher volatility)
    "vix_thresholds": {"low": 18, "normal": 23, "elevated": 28, "high": 35},
    "pcr_thresholds": {"bullish": 1.2, "bearish": 0.6},
}

US_CONFIG = {
    "vix_symbol": "^VIX",
    "vix_3m_symbol": "^VIX3M",
    "primary_index": "SPY",
    "secondary_index": "QQQ",
    "pcr_symbol": "SPY",
    # Standard US thresholds
    "vix_thresholds": {"low": 15, "normal": 20, "elevated": 25, "high": 35},
    "pcr_thresholds": {"bullish": 1.0, "bearish": 0.7},
}

# Default composite score weights
DEFAULT_WEIGHTS = {
    "vix": 0.25,
    "term_structure": 0.15,
    "primary_trend": 0.25,
    "secondary_trend": 0.15,
    "pcr": 0.20,
}


def _signal_to_score(signal: TrendSignal | None) -> float:
    """Convert TrendSignal to numeric score.

    Args:
        signal: TrendSignal enum.

    Returns:
        1.0 for BULLISH, -1.0 for BEARISH, 0.0 for NEUTRAL/None.
    """
    if signal == TrendSignal.BULLISH:
        return 1.0
    elif signal == TrendSignal.BEARISH:
        return -1.0
    else:
        return 0.0


def calc_composite_score(
    vix_signal: TrendSignal,
    term_signal: TrendSignal | None,
    primary_trend: MarketTrend | None,
    secondary_trend: MarketTrend | None,
    pcr_signal: TrendSignal | None,
    weights: dict[str, float] | None = None,
) -> float:
    """Calculate composite sentiment score.

    Combines multiple sentiment indicators into a single score.
    Score ranges from -100 (extreme bearish) to +100 (extreme bullish).

    Args:
        vix_signal: VIX-based signal.
        term_signal: Term structure signal.
        primary_trend: Primary index trend result.
        secondary_trend: Secondary index trend result.
        pcr_signal: PCR signal.
        weights: Custom weights for each component.

    Returns:
        Composite score (-100 to 100).

    Example:
        >>> calc_composite_score(
        ...     vix_signal=TrendSignal.BULLISH,
        ...     term_signal=TrendSignal.BULLISH,
        ...     primary_trend=MarketTrend("SPY", TrendSignal.BULLISH, 0.5),
        ...     secondary_trend=None,
        ...     pcr_signal=TrendSignal.BULLISH,
        ... )
        60.0  # Strong bullish score
    """
    weights = weights or DEFAULT_WEIGHTS

    score = 0.0
    total_weight = 0.0

    # VIX signal contribution
    score += _signal_to_score(vix_signal) * weights["vix"]
    total_weight += weights["vix"]

    # Term structure contribution
    if term_signal is not None:
        score += _signal_to_score(term_signal) * weights["term_structure"]
        total_weight += weights["term_structure"]

    # Primary trend contribution (modulated by strength)
    if primary_trend is not None:
        trend_score = _signal_to_score(primary_trend.signal)
        # Modulate by trend strength
        trend_score *= abs(primary_trend.strength)
        score += trend_score * weights["primary_trend"]
        total_weight += weights["primary_trend"]

    # Secondary trend contribution (modulated by strength)
    if secondary_trend is not None:
        trend_score = _signal_to_score(secondary_trend.signal)
        trend_score *= abs(secondary_trend.strength)
        score += trend_score * weights["secondary_trend"]
        total_weight += weights["secondary_trend"]

    # PCR contribution
    if pcr_signal is not None:
        score += _signal_to_score(pcr_signal) * weights["pcr"]
        total_weight += weights["pcr"]

    # Normalize to -100 to 100 scale
    if total_weight > 0:
        return (score / total_weight) * 100
    return 0.0


def score_to_signal(score: float) -> TrendSignal:
    """Convert composite score to trend signal.

    Args:
        score: Composite score (-100 to 100).

    Returns:
        TrendSignal based on score thresholds.
        - BULLISH if score > 20
        - BEARISH if score < -20
        - NEUTRAL otherwise
    """
    if score > 20:
        return TrendSignal.BULLISH
    elif score < -20:
        return TrendSignal.BEARISH
    else:
        return TrendSignal.NEUTRAL


def analyze_us_sentiment(
    vix: float | None,
    vix_3m: float | None,
    spy_prices: list[float] | None,
    qqq_prices: list[float] | None,
    spy_current: float | None = None,
    qqq_current: float | None = None,
    pcr: float | None = None,
) -> MarketSentiment:
    """Analyze US market sentiment.

    Combines VIX, VIX term structure, SPY trend, QQQ trend,
    and Put/Call Ratio into a comprehensive sentiment view.

    Args:
        vix: Current VIX value.
        vix_3m: VIX3M value.
        spy_prices: SPY price history (oldest to newest).
        qqq_prices: QQQ price history (oldest to newest).
        spy_current: Current SPY price (for 200MA check).
        qqq_current: Current QQQ price (for 200MA check).
        pcr: Put/Call ratio.

    Returns:
        MarketSentiment for US market.

    Example:
        >>> result = analyze_us_sentiment(
        ...     vix=28.0,
        ...     vix_3m=24.0,
        ...     spy_prices=list(range(100, 160)),
        ...     qqq_prices=list(range(200, 260)),
        ...     pcr=1.2,
        ... )
        >>> result.composite_signal
        <TrendSignal.BULLISH: 'bullish'>
    """
    # VIX analysis
    vix_zone = get_vix_zone(vix) if vix else VixZone.NORMAL
    vix_signal = interpret_vix(vix) if vix else TrendSignal.NEUTRAL

    # Term structure
    term_struct = analyze_term_structure(vix, vix_3m)

    # Trends
    spy_trend = analyze_market_trend("SPY", spy_prices, spy_current) if spy_prices else None
    qqq_trend = analyze_market_trend("QQQ", qqq_prices, qqq_current) if qqq_prices else None

    # PCR
    pcr_result = None
    if pcr is not None:
        pcr_result = PcrResult(
            value=pcr,
            zone=get_pcr_zone(pcr),
            signal=interpret_pcr(pcr),
        )

    # Composite score (term_struct may be None if vix_3m is missing)
    composite = calc_composite_score(
        vix_signal,
        term_struct.signal if term_struct else None,
        spy_trend,
        qqq_trend,
        pcr_result.signal if pcr_result else None,
    )

    return MarketSentiment(
        market=MarketType.US,
        timestamp=datetime.now(),
        vix_value=vix,
        vix_zone=vix_zone,
        vix_signal=vix_signal,
        term_structure=term_struct,
        primary_trend=spy_trend,
        secondary_trend=qqq_trend,
        pcr=pcr_result,
        composite_score=composite,
        composite_signal=score_to_signal(composite),
        favorable_for_selling=is_vix_favorable_for_selling(vix) if vix else False,
    )


def _get_hk_vix_zone(vhsi: float | None) -> VixZone:
    """Get VIX zone for HK market with adjusted thresholds.

    HK market typically has higher volatility than US market.

    Args:
        vhsi: VHSI or VHSI proxy value.

    Returns:
        VixZone classification.
    """
    thresholds = HK_CONFIG["vix_thresholds"]

    if vhsi is None:
        return VixZone.NORMAL

    if vhsi < thresholds["low"]:
        return VixZone.LOW
    elif vhsi < thresholds["normal"]:
        return VixZone.NORMAL
    elif vhsi < thresholds["elevated"]:
        return VixZone.ELEVATED
    elif vhsi < thresholds["high"]:
        return VixZone.HIGH
    else:
        return VixZone.EXTREME


def _interpret_hk_vix(vhsi: float | None) -> TrendSignal:
    """Interpret VHSI proxy as trading signal.

    Uses HK-specific thresholds for interpretation.

    Args:
        vhsi: VHSI or VHSI proxy value.

    Returns:
        Trading signal (contrarian interpretation).
    """
    thresholds = HK_CONFIG["vix_thresholds"]

    if vhsi is None:
        return TrendSignal.NEUTRAL

    if vhsi > thresholds["elevated"]:
        return TrendSignal.BULLISH  # High fear = contrarian bullish
    elif vhsi < thresholds["low"]:
        return TrendSignal.BEARISH  # Complacency warning
    else:
        return TrendSignal.NEUTRAL


def _analyze_hk_pcr(pcr: float) -> PcrResult:
    """Analyze PCR with HK-specific thresholds.

    HK market PCR may have different normal ranges.

    Args:
        pcr: Put/Call ratio value.

    Returns:
        PcrResult with signal and zone.
    """
    thresholds = HK_CONFIG["pcr_thresholds"]

    if pcr > thresholds["bullish"]:
        signal = TrendSignal.BULLISH  # High PCR = contrarian bullish
        zone = "extreme_fear" if pcr > 1.5 else "elevated_fear"
    elif pcr < thresholds["bearish"]:
        signal = TrendSignal.BEARISH  # Low PCR = contrarian bearish
        zone = "extreme_greed" if pcr < 0.4 else "elevated_greed"
    else:
        signal = TrendSignal.NEUTRAL
        zone = "neutral"

    return PcrResult(value=pcr, zone=zone, signal=signal)


def analyze_hk_sentiment(
    vhsi_proxy: float | None,
    vhsi_3m_proxy: float | None,
    hsi_prices: list[float] | None,
    hstech_prices: list[float] | None,
    hsi_current: float | None = None,
    hstech_current: float | None = None,
    pcr: float | None = None,
) -> MarketSentiment:
    """Analyze HK market sentiment.

    Uses 2800.HK (Tracker Fund) as VHSI proxy since direct VHSI
    data API may not be available.

    Args:
        vhsi_proxy: 2800.HK IV as VHSI proxy.
        vhsi_3m_proxy: Longer-dated 2800.HK option IV.
        hsi_prices: 2800.HK price history (HSI proxy).
        hstech_prices: 3032.HK price history (HSTECH proxy).
        hsi_current: Current 2800.HK price.
        hstech_current: Current 3032.HK price.
        pcr: Put/Call ratio from 2800.HK options.

    Returns:
        MarketSentiment for HK market.

    Example:
        >>> result = analyze_hk_sentiment(
        ...     vhsi_proxy=25.0,
        ...     vhsi_3m_proxy=22.0,
        ...     hsi_prices=list(range(20, 26)),
        ...     hstech_prices=list(range(10, 16)),
        ... )
        >>> result.market
        <MarketType.HK: 'hk'>
    """
    # VIX proxy analysis (adjusted for HK)
    vix_zone = _get_hk_vix_zone(vhsi_proxy)
    vix_signal = _interpret_hk_vix(vhsi_proxy)

    # Term structure
    term_struct = analyze_term_structure(vhsi_proxy, vhsi_3m_proxy)

    # Trends (use Futu index symbols for clearer reporting)
    hsi_trend = analyze_market_trend("800000.HK", hsi_prices, hsi_current) if hsi_prices else None
    hstech_trend = (
        analyze_market_trend("3032.HK", hstech_prices, hstech_current)
        if hstech_prices
        else None
    )

    # PCR (adjusted thresholds for HK)
    pcr_result = None
    if pcr is not None:
        pcr_result = _analyze_hk_pcr(pcr)

    # Composite score (term_struct may be None if vhsi_3m_proxy is missing)
    composite = calc_composite_score(
        vix_signal,
        term_struct.signal if term_struct else None,
        hsi_trend,
        hstech_trend,
        pcr_result.signal if pcr_result else None,
    )

    # Favorable for selling check (use HK threshold)
    thresholds = HK_CONFIG["vix_thresholds"]
    favorable = vhsi_proxy is not None and vhsi_proxy >= thresholds["low"]

    return MarketSentiment(
        market=MarketType.HK,
        timestamp=datetime.now(),
        vix_value=vhsi_proxy,
        vix_zone=vix_zone,
        vix_signal=vix_signal,
        term_structure=term_struct,
        primary_trend=hsi_trend,
        secondary_trend=hstech_trend,
        pcr=pcr_result,
        composite_score=composite,
        composite_signal=score_to_signal(composite),
        favorable_for_selling=favorable,
    )


def get_sentiment_summary(sentiment: MarketSentiment) -> str:
    """Get a human-readable summary of market sentiment.

    Args:
        sentiment: MarketSentiment analysis result.

    Returns:
        String summary of the sentiment.
    """
    market_name = "US Market" if sentiment.market == MarketType.US else "HK Market"

    signal_desc = {
        TrendSignal.BULLISH: "bullish",
        TrendSignal.BEARISH: "bearish",
        TrendSignal.NEUTRAL: "neutral",
    }

    score_desc = ""
    if sentiment.composite_score > 50:
        score_desc = "strongly bullish"
    elif sentiment.composite_score > 20:
        score_desc = "moderately bullish"
    elif sentiment.composite_score > -20:
        score_desc = "neutral"
    elif sentiment.composite_score > -50:
        score_desc = "moderately bearish"
    else:
        score_desc = "strongly bearish"

    vix_str = f"{sentiment.vix_value:.1f}" if sentiment.vix_value else "N/A"
    zone_str = sentiment.vix_zone.value

    favorable_str = "Yes" if sentiment.favorable_for_selling else "No"

    return (
        f"{market_name} Sentiment: {score_desc} (score: {sentiment.composite_score:.1f})\n"
        f"VIX: {vix_str} ({zone_str}), Signal: {signal_desc[sentiment.vix_signal]}\n"
        f"Favorable for option selling: {favorable_str}"
    )
