"""Composite portfolio metrics (SAS, PREI, etc.)."""

import math


def calc_sas(allocations: list[float]) -> float | None:
    """Calculate Strategy Allocation Score (SAS).

    SAS measures diversification across different strategies.
    Uses normalized entropy: higher score = more diversified.

    Args:
        allocations: List of allocation percentages per strategy (should sum to ~1.0).

    Returns:
        SAS score (0-100). Higher indicates better diversification.
        Returns None if allocations are empty or invalid.

    Example:
        >>> calc_sas([0.5, 0.5])  # Equal allocation to 2 strategies
        100.0
        >>> calc_sas([1.0])  # Single strategy
        0.0
        >>> calc_sas([0.33, 0.33, 0.34])  # Equal 3-way split
        100.0
    """
    if not allocations:
        return None

    # Filter out zero/negative allocations
    valid_allocs = [a for a in allocations if a is not None and a > 0]

    if len(valid_allocs) == 0:
        return None

    if len(valid_allocs) == 1:
        return 0.0  # Single strategy = no diversification

    # Normalize allocations
    total = sum(valid_allocs)
    if total == 0:
        return None

    weights = [a / total for a in valid_allocs]

    # Calculate entropy
    entropy = -sum(w * math.log(w) for w in weights if w > 0)

    # Maximum entropy for n strategies
    max_entropy = math.log(len(weights))

    if max_entropy == 0:
        return 0.0

    # Normalize to 0-100 scale
    normalized_entropy = (entropy / max_entropy) * 100

    return normalized_entropy


def calc_prei(exposures: dict[str, float]) -> float | None:
    """Calculate Portfolio Risk Exposure Index (PREI).

    PREI combines multiple risk exposures into a single metric.
    Higher PREI indicates higher overall risk exposure.

    Expected exposures dict keys:
    - "delta": Direction exposure (-1 to 1 normalized)
    - "gamma": Convexity exposure (-1 to 1 normalized)
    - "theta": Time decay exposure (-1 to 1 normalized)
    - "vega": Volatility exposure (-1 to 1 normalized)
    - "concentration": Position concentration (0 to 1)

    Args:
        exposures: Dictionary of exposure names to normalized values.

    Returns:
        PREI score (0-100). Higher = more risk exposure.
        Returns None if exposures dict is empty.

    Example:
        >>> exposures = {
        ...     "delta": 0.5,  # Moderate direction exposure
        ...     "gamma": -0.2,  # Short gamma
        ...     "theta": 0.3,  # Positive theta
        ...     "vega": -0.4,  # Short vega
        ...     "concentration": 0.3,  # Moderate concentration
        ... }
        >>> prei = calc_prei(exposures)
        >>> 0 <= prei <= 100
        True
    """
    if not exposures:
        return None

    # Default weights for each exposure type
    weights = {
        "delta": 0.25,
        "gamma": 0.20,
        "theta": 0.15,
        "vega": 0.20,
        "concentration": 0.20,
    }

    total_weight = 0.0
    weighted_exposure = 0.0

    for exp_name, exp_value in exposures.items():
        if exp_value is None:
            continue

        weight = weights.get(exp_name, 0.1)  # Default weight for unknown exposures

        # Take absolute value and clamp to [0, 1]
        abs_exposure = min(1.0, abs(exp_value))

        weighted_exposure += abs_exposure * weight
        total_weight += weight

    if total_weight == 0:
        return None

    # Normalize and scale to 0-100
    prei = (weighted_exposure / total_weight) * 100

    return prei


def calc_portfolio_health_score(
    sas: float | None,
    prei: float | None,
    sharpe: float | None,
    max_dd: float | None,
) -> float | None:
    """Calculate overall portfolio health score.

    Combines diversification, risk exposure, risk-adjusted return, and drawdown.

    Args:
        sas: Strategy Allocation Score (0-100, higher = better).
        prei: Portfolio Risk Exposure Index (0-100, lower = better).
        sharpe: Sharpe ratio (higher = better, typically 0-3).
        max_dd: Maximum drawdown as decimal (lower = better, typically 0-0.5).

    Returns:
        Health score (0-100). Higher = healthier portfolio.
    """
    scores = []
    weights = []

    # SAS component (higher is better)
    if sas is not None:
        scores.append(sas)
        weights.append(0.25)

    # PREI component (lower is better, so invert)
    if prei is not None:
        scores.append(100 - prei)
        weights.append(0.25)

    # Sharpe component (scale to 0-100, cap at 3)
    if sharpe is not None:
        sharpe_score = min(100, max(0, sharpe / 3 * 100))
        scores.append(sharpe_score)
        weights.append(0.25)

    # Max DD component (lower is better, scale 0-50% to 100-0)
    if max_dd is not None:
        dd_score = max(0, 100 - (max_dd * 200))  # 0% DD = 100, 50% DD = 0
        scores.append(dd_score)
        weights.append(0.25)

    if not scores:
        return None

    total_weight = sum(weights)
    weighted_score = sum(s * w for s, w in zip(scores, weights))

    return weighted_score / total_weight


def calc_position_sizing_score(
    kelly: float | None,
    margin_util: float | None,
    concentration: float | None,
) -> float | None:
    """Calculate position sizing appropriateness score.

    Args:
        kelly: Kelly fraction (0-1).
        margin_util: Margin utilization (0-1).
        concentration: Position concentration HHI (0-1).

    Returns:
        Score (0-100). Higher = better position sizing.
    """
    scores = []

    # Kelly score (optimal around 0.1-0.3, penalize extremes)
    if kelly is not None:
        if 0.1 <= kelly <= 0.3:
            kelly_score = 100
        elif kelly < 0.1:
            kelly_score = 50 + (kelly / 0.1) * 50
        elif kelly <= 0.5:
            kelly_score = 100 - ((kelly - 0.3) / 0.2) * 30
        else:
            kelly_score = max(0, 70 - (kelly - 0.5) * 100)
        scores.append(kelly_score)

    # Margin utilization score (optimal around 0.3-0.5)
    if margin_util is not None:
        if 0.3 <= margin_util <= 0.5:
            margin_score = 100
        elif margin_util < 0.3:
            margin_score = 60 + (margin_util / 0.3) * 40
        elif margin_util <= 0.7:
            margin_score = 100 - ((margin_util - 0.5) / 0.2) * 30
        else:
            margin_score = max(0, 70 - (margin_util - 0.7) * 200)
        scores.append(margin_score)

    # Concentration score (lower is better)
    if concentration is not None:
        conc_score = max(0, 100 - concentration * 100)
        scores.append(conc_score)

    if not scores:
        return None

    return sum(scores) / len(scores)
