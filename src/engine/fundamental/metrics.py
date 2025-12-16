"""Fundamental metrics extraction and analysis."""

from src.data.models.fundamental import Fundamental
from src.engine.base import FundamentalScore, RatingSignal


def get_pe(fundamental: Fundamental) -> float | None:
    """Get P/E ratio from fundamental data.

    Args:
        fundamental: Fundamental data object.

    Returns:
        P/E ratio, or None if not available.
    """
    if fundamental is None:
        return None
    return fundamental.pe_ratio


def get_revenue_growth(fundamental: Fundamental) -> float | None:
    """Get revenue growth rate from fundamental data.

    Args:
        fundamental: Fundamental data object.

    Returns:
        Revenue growth as decimal (e.g., 0.15 for 15%), or None if not available.
    """
    if fundamental is None:
        return None
    return fundamental.revenue_growth


def get_profit_margin(fundamental: Fundamental) -> float | None:
    """Get profit margin from fundamental data.

    Args:
        fundamental: Fundamental data object.

    Returns:
        Profit margin as decimal, or None if not available.
    """
    if fundamental is None:
        return None
    return fundamental.profit_margin


def get_analyst_rating(fundamental: Fundamental) -> RatingSignal:
    """Get analyst rating signal from fundamental data.

    Converts numeric recommendation mean to RatingSignal.

    Args:
        fundamental: Fundamental data object.

    Returns:
        RatingSignal based on analyst consensus.
    """
    if fundamental is None:
        return RatingSignal.HOLD

    # Use recommendation_mean if available (1=Strong Buy, 5=Strong Sell)
    mean = fundamental.recommendation_mean
    if mean is not None:
        if mean <= 1.5:
            return RatingSignal.STRONG_BUY
        elif mean <= 2.5:
            return RatingSignal.BUY
        elif mean <= 3.5:
            return RatingSignal.HOLD
        elif mean <= 4.5:
            return RatingSignal.SELL
        else:
            return RatingSignal.STRONG_SELL

    # Fallback to text recommendation
    rec = fundamental.recommendation
    if rec is None:
        return RatingSignal.HOLD

    rec_lower = rec.lower()
    if "strong" in rec_lower and "buy" in rec_lower:
        return RatingSignal.STRONG_BUY
    elif "buy" in rec_lower:
        return RatingSignal.BUY
    elif "strong" in rec_lower and "sell" in rec_lower:
        return RatingSignal.STRONG_SELL
    elif "sell" in rec_lower:
        return RatingSignal.SELL
    else:
        return RatingSignal.HOLD


def evaluate_fundamentals(fundamental: Fundamental) -> FundamentalScore:
    """Evaluate overall fundamental quality.

    Scores each fundamental metric and combines into an overall score.

    Args:
        fundamental: Fundamental data object.

    Returns:
        FundamentalScore with overall and component scores.
    """
    if fundamental is None:
        return FundamentalScore(score=50.0, rating=RatingSignal.HOLD)

    scores = {}
    weights = {}

    # P/E Score (lower is better, but not negative)
    pe = get_pe(fundamental)
    if pe is not None and pe > 0:
        if pe < 15:
            pe_score = 100
        elif pe < 25:
            pe_score = 80
        elif pe < 35:
            pe_score = 60
        elif pe < 50:
            pe_score = 40
        else:
            pe_score = 20
        scores["pe"] = pe_score
        weights["pe"] = 0.25

    # Revenue Growth Score
    growth = get_revenue_growth(fundamental)
    if growth is not None:
        if growth > 0.30:
            growth_score = 100
        elif growth > 0.15:
            growth_score = 80
        elif growth > 0.05:
            growth_score = 60
        elif growth > 0:
            growth_score = 40
        else:
            growth_score = 20
        scores["growth"] = growth_score
        weights["growth"] = 0.25

    # Profit Margin Score
    margin = get_profit_margin(fundamental)
    if margin is not None:
        if margin > 0.20:
            margin_score = 100
        elif margin > 0.10:
            margin_score = 80
        elif margin > 0.05:
            margin_score = 60
        elif margin > 0:
            margin_score = 40
        else:
            margin_score = 20
        scores["margin"] = margin_score
        weights["margin"] = 0.25

    # Analyst Rating Score
    rating = get_analyst_rating(fundamental)
    rating_scores = {
        RatingSignal.STRONG_BUY: 100,
        RatingSignal.BUY: 80,
        RatingSignal.HOLD: 60,
        RatingSignal.SELL: 40,
        RatingSignal.STRONG_SELL: 20,
    }
    scores["analyst"] = rating_scores[rating]
    weights["analyst"] = 0.25

    # Calculate weighted average
    total_weight = sum(weights.values())
    if total_weight == 0:
        overall_score = 50.0
    else:
        overall_score = sum(scores[k] * weights[k] for k in scores) / total_weight

    # Determine overall rating
    if overall_score >= 80:
        overall_rating = RatingSignal.STRONG_BUY
    elif overall_score >= 65:
        overall_rating = RatingSignal.BUY
    elif overall_score >= 45:
        overall_rating = RatingSignal.HOLD
    elif overall_score >= 30:
        overall_rating = RatingSignal.SELL
    else:
        overall_rating = RatingSignal.STRONG_SELL

    return FundamentalScore(
        score=overall_score,
        rating=overall_rating,
        pe_score=scores.get("pe"),
        growth_score=scores.get("growth"),
        margin_score=scores.get("margin"),
        analyst_score=scores.get("analyst"),
        details={
            "pe": pe,
            "revenue_growth": growth,
            "profit_margin": margin,
            "analyst_rating": rating.value,
        },
    )


def is_fundamentally_strong(
    fundamental: Fundamental,
    min_score: float = 65.0,
) -> bool:
    """Check if stock has strong fundamentals.

    Args:
        fundamental: Fundamental data object.
        min_score: Minimum score to be considered strong.

    Returns:
        True if fundamental score is at or above threshold.
    """
    score = evaluate_fundamentals(fundamental)
    return score.score >= min_score
