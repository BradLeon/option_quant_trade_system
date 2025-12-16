"""IV Rank and IV Percentile calculations."""


def calc_iv_rank(current_iv: float, historical_ivs: list[float]) -> float | None:
    """Calculate IV Rank.

    IV Rank measures where the current IV falls within the historical
    high-low range over a period (typically 252 trading days / 1 year).

    Formula: IV Rank = (Current IV - Min IV) / (Max IV - Min IV) * 100

    Args:
        current_iv: Current implied volatility (decimal form).
        historical_ivs: List of historical IV values (decimal form).

    Returns:
        IV Rank as a percentage (0-100).
        Returns 50 if all historical IVs are equal.
        Returns None if insufficient data.

    Example:
        >>> hist_ivs = [0.15, 0.20, 0.25, 0.30, 0.35]
        >>> calc_iv_rank(0.25, hist_ivs)
        50.0
        >>> calc_iv_rank(0.15, hist_ivs)
        0.0
        >>> calc_iv_rank(0.35, hist_ivs)
        100.0
    """
    if current_iv is None or historical_ivs is None:
        return None

    if len(historical_ivs) < 1:
        return None

    min_iv = min(historical_ivs)
    max_iv = max(historical_ivs)

    # Handle case where all IVs are equal
    if max_iv == min_iv:
        return 50.0

    rank = (current_iv - min_iv) / (max_iv - min_iv) * 100
    return max(0.0, min(100.0, rank))  # Clamp to 0-100


def calc_iv_percentile(current_iv: float, historical_ivs: list[float]) -> float | None:
    """Calculate IV Percentile.

    IV Percentile measures the percentage of days where IV was lower
    than the current IV.

    Formula: IV Percentile = (Count of days with IV < current IV) / Total days * 100

    Args:
        current_iv: Current implied volatility (decimal form).
        historical_ivs: List of historical IV values (decimal form).

    Returns:
        IV Percentile as a percentage (0-100).
        Returns None if insufficient data.

    Example:
        >>> hist_ivs = [0.15, 0.20, 0.25, 0.30, 0.35]
        >>> calc_iv_percentile(0.25, hist_ivs)  # 2 out of 5 are lower
        40.0
    """
    if current_iv is None or historical_ivs is None:
        return None

    if len(historical_ivs) < 1:
        return None

    count_lower = sum(1 for iv in historical_ivs if iv < current_iv)
    percentile = count_lower / len(historical_ivs) * 100

    return percentile


def interpret_iv_rank(iv_rank: float) -> str:
    """Interpret IV Rank value.

    Args:
        iv_rank: IV Rank value (0-100).

    Returns:
        Interpretation string: "low", "normal", "elevated", or "high".
    """
    if iv_rank < 20:
        return "low"
    elif iv_rank < 50:
        return "normal"
    elif iv_rank < 80:
        return "elevated"
    else:
        return "high"


def is_iv_rank_favorable_for_selling(iv_rank: float, threshold: float = 50.0) -> bool:
    """Check if IV Rank is favorable for option selling strategies.

    Higher IV Rank generally indicates better premium collection opportunities.

    Args:
        iv_rank: IV Rank value (0-100).
        threshold: Minimum IV Rank for favorable conditions.

    Returns:
        True if IV Rank is at or above threshold.
    """
    if iv_rank is None:
        return False
    return iv_rank >= threshold
