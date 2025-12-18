"""Volatility metrics extraction and analysis.

Position-level module for volatility analysis of individual securities.
Uses StockVolatility data model from data layer, similar to how
fundamental/metrics.py uses Fundamental data model.
"""

from src.data.models.stock import StockVolatility
from src.engine.models.enums import RatingSignal
from src.engine.models.result import VolatilityScore


def get_iv(volatility: StockVolatility) -> float | None:
    """Get implied volatility from volatility data.

    Args:
        volatility: StockVolatility data object.

    Returns:
        IV as decimal (e.g., 0.25 for 25%), or None if not available.
    """
    if volatility is None:
        return None
    return volatility.iv


def get_hv(volatility: StockVolatility) -> float | None:
    """Get historical volatility from volatility data.

    Args:
        volatility: StockVolatility data object.

    Returns:
        HV as decimal (e.g., 0.25 for 25%), or None if not available.
    """
    if volatility is None:
        return None
    return volatility.hv


def get_iv_rank(volatility: StockVolatility) -> float | None:
    """Get IV Rank from volatility data.

    Args:
        volatility: StockVolatility data object.

    Returns:
        IV Rank (0-100), or None if not available.
    """
    if volatility is None:
        return None
    return volatility.iv_rank


def get_iv_percentile(volatility: StockVolatility) -> float | None:
    """Get IV Percentile from volatility data.

    Args:
        volatility: StockVolatility data object.

    Returns:
        IV Percentile as decimal (e.g., 0.18 for 18%), or None if not available.
    """
    if volatility is None:
        return None
    return volatility.iv_percentile


def get_pcr(volatility: StockVolatility) -> float | None:
    """Get Put/Call Ratio from volatility data.

    Args:
        volatility: StockVolatility data object.

    Returns:
        Put/Call Ratio, or None if not available.
    """
    if volatility is None:
        return None
    return volatility.pcr


def get_iv_hv_ratio(volatility: StockVolatility) -> float | None:
    """Get IV/HV ratio from volatility data.

    Args:
        volatility: StockVolatility data object.

    Returns:
        IV/HV ratio. > 1 means IV is higher than HV (options are "expensive").
        Returns None if either IV or HV is not available.
    """
    if volatility is None:
        return None
    return volatility.iv_hv_ratio


def interpret_iv_rank(iv_rank: float | None) -> str:
    """Interpret IV Rank value.

    Args:
        iv_rank: IV Rank value (0-100).

    Returns:
        Interpretation string: "unknown", "low", "normal", "elevated", or "high".
    """
    if iv_rank is None:
        return "unknown"
    if iv_rank < 20:
        return "low"
    elif iv_rank < 50:
        return "normal"
    elif iv_rank < 80:
        return "elevated"
    else:
        return "high"


def interpret_pcr(pcr: float | None) -> str:
    """Interpret Put/Call Ratio value.

    Args:
        pcr: Put/Call Ratio value.

    Returns:
        Interpretation string indicating market sentiment.
    """
    if pcr is None:
        return "unknown"
    if pcr < 0.5:
        return "bullish"  # More calls than puts
    elif pcr < 0.7:
        return "slightly_bullish"
    elif pcr < 1.0:
        return "neutral"
    elif pcr < 1.5:
        return "slightly_bearish"
    else:
        return "bearish"  # More puts than calls


def is_iv_elevated(volatility: StockVolatility, threshold: float = 1.2) -> bool:
    """Check if IV is elevated relative to HV.

    Args:
        volatility: StockVolatility data object.
        threshold: IV/HV ratio threshold above which IV is considered elevated.

    Returns:
        True if IV/HV ratio exceeds threshold.
    """
    ratio = get_iv_hv_ratio(volatility)
    if ratio is None:
        return False
    return ratio > threshold


def is_iv_cheap(volatility: StockVolatility, threshold: float = 0.8) -> bool:
    """Check if IV is cheap relative to HV.

    Args:
        volatility: StockVolatility data object.
        threshold: IV/HV ratio threshold below which IV is considered cheap.

    Returns:
        True if IV/HV ratio is below threshold.
    """
    ratio = get_iv_hv_ratio(volatility)
    if ratio is None:
        return False
    return ratio < threshold


def is_favorable_for_selling(
    volatility: StockVolatility,
    min_iv_rank: float = 50.0,
) -> bool:
    """Check if volatility conditions are favorable for option selling strategies.

    Higher IV Rank generally indicates better premium collection opportunities.

    Args:
        volatility: StockVolatility data object.
        min_iv_rank: Minimum IV Rank for favorable conditions.

    Returns:
        True if IV Rank is at or above threshold.
    """
    iv_rank = get_iv_rank(volatility)
    if iv_rank is None:
        return False
    return iv_rank >= min_iv_rank


def evaluate_volatility(volatility: StockVolatility) -> VolatilityScore:
    """Evaluate overall volatility conditions for option trading.

    Scores each volatility metric and combines into an overall score.
    Higher scores indicate more favorable conditions for option selling.

    Args:
        volatility: StockVolatility data object.

    Returns:
        VolatilityScore with overall and component scores.
    """
    if volatility is None:
        return VolatilityScore(score=50.0, rating=RatingSignal.HOLD)

    scores = {}
    weights = {}

    # IV Rank Score (higher is better for selling)
    # Range: 0-100, directly maps to score
    iv_rank = get_iv_rank(volatility)
    if iv_rank is not None:
        scores["iv_rank"] = iv_rank
        weights["iv_rank"] = 0.40

    # IV/HV Ratio Score (higher ratio = options are more expensive = better for selling)
    # Range: mapped to 0-100
    iv_hv_ratio = get_iv_hv_ratio(volatility)
    if iv_hv_ratio is not None:
        if iv_hv_ratio >= 1.5:
            ratio_score = 100
        elif iv_hv_ratio >= 1.2:
            ratio_score = 80
        elif iv_hv_ratio >= 1.0:
            ratio_score = 60
        elif iv_hv_ratio >= 0.8:
            ratio_score = 40
        else:
            ratio_score = 20
        scores["iv_hv_ratio"] = ratio_score
        weights["iv_hv_ratio"] = 0.30

    # IV Percentile Score (higher is better for selling)
    # Range: 0-100 (stored as decimal, multiplied by 100)
    iv_percentile = get_iv_percentile(volatility)
    if iv_percentile is not None:
        scores["iv_percentile"] = iv_percentile * 100
        weights["iv_percentile"] = 0.30

    # PCR is excluded from scoring due to non-monotonic relationship
    # (neutral is best, extremes are worse - doesn't fit "higher is better" pattern)
    # Still available in details for reference
    pcr = get_pcr(volatility)

    # Calculate weighted average
    total_weight = sum(weights.values())
    if total_weight == 0:
        overall_score = 50.0
    else:
        overall_score = sum(scores[k] * weights[k] for k in scores) / total_weight

    # Determine overall rating for option selling
    if overall_score >= 70:
        overall_rating = RatingSignal.STRONG_BUY  # Strong sell premium opportunity
    elif overall_score >= 55:
        overall_rating = RatingSignal.BUY  # Good sell premium opportunity
    elif overall_score >= 40:
        overall_rating = RatingSignal.HOLD  # Neutral
    elif overall_score >= 25:
        overall_rating = RatingSignal.SELL  # Unfavorable for selling
    else:
        overall_rating = RatingSignal.STRONG_SELL  # Very unfavorable

    return VolatilityScore(
        score=overall_score,
        rating=overall_rating,
        iv_rank=iv_rank,
        iv_hv_ratio=iv_hv_ratio,
        iv_percentile=iv_percentile,
        pcr=pcr,  # Excluded from scoring, for reference only
        details={
            "iv": get_iv(volatility),
            "hv": get_hv(volatility),
            "iv_rank_interpretation": interpret_iv_rank(iv_rank),
            "pcr_interpretation": interpret_pcr(pcr),
        },
    )
