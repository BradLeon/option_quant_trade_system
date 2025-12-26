"""Composite portfolio metrics (Portfolio-level SAS and PREI).

This module provides portfolio-level aggregation of:
- Strategy Attractiveness Score (SAS): Margin-weighted average of position SAS scores
- Position Risk Exposure Index (PREI): Aggregated tail risk exposure
"""

import math

from src.engine.models.position import Position
from src.engine.portfolio.greeks_agg import calc_portfolio_gamma, calc_portfolio_vega


def calc_portfolio_sas(
    positions_with_sas: list[tuple[Position, float]],
) -> float | None:
    """Calculate Portfolio-level Strategy Attractiveness Score.

    Aggregates individual position SAS scores weighted by margin requirement.
    This represents the overall attractiveness of the portfolio's option positions,
    with larger positions (by margin) having more weight.

    Formula:
        Portfolio_SAS = Σ(SAS_i × margin_i) / Σ(margin_i)

    Args:
        positions_with_sas: List of (Position, sas_score) tuples.
            - Position.margin: Margin requirement for weighting
            - sas_score: Pre-calculated SAS score (0-100) from calc_sas()

    Returns:
        Portfolio SAS score (0-100). Higher = more attractive portfolio.
        Returns None if no valid positions with both sas and margin.

    Example:
        >>> from src.engine.position.option_metrics import calc_sas
        >>> positions = [
        ...     Position(symbol="AAPL", quantity=1, margin=5000.0),
        ...     Position(symbol="MSFT", quantity=1, margin=3000.0),
        ... ]
        >>> sas_scores = [80.0, 60.0]  # Pre-calculated SAS for each position
        >>> calc_portfolio_sas(list(zip(positions, sas_scores)))
        72.5  # (80*5000 + 60*3000) / (5000+3000) = 580000/8000
    """
    if not positions_with_sas:
        return None

    total_weighted_sas = 0.0
    total_margin = 0.0

    for pos, sas in positions_with_sas:
        margin = pos.margin

        # Skip positions without valid SAS or margin
        if sas is None or margin is None or margin <= 0:
            continue

        total_weighted_sas += sas * margin
        total_margin += margin

    if total_margin == 0:
        return None

    return total_weighted_sas / total_margin


def calc_portfolio_prei(
    positions: list[Position],
    weights: tuple[float, float, float] = (0.40, 0.30, 0.30),
) -> float | None:
    """Calculate Portfolio-level Position Risk Exposure Index.

    Aggregates position-level risk into a portfolio-level tail risk metric.
    Each risk component (gamma, vega, DTE) is independently normalized to 0-1,
    then combined with weights.

    Formula:
        Portfolio_PREI = (w1 × Gamma_Risk + w2 × Vega_Risk + w3 × DTE_Risk) × 100

        Where each component is normalized to 0-1:
        - Gamma_Risk = |calc_portfolio_gamma()| normalized to 0-1
        - Vega_Risk = |calc_portfolio_vega()| normalized to 0-1
        - DTE_Risk = Σ(DTE_Risk_i × |Γ$_i|) / Σ|Γ$_i| normalized to 0-1
          DTE_Risk_i = sqrt(1 / max(1, DTE_i))

    Args:
        positions: List of Position objects with gamma, vega, underlying_price,
            quantity, and dte fields.
        weights: Tuple of (w1, w2, w3) weights for gamma, vega, and DTE risk.
            Default: (0.40, 0.30, 0.30).

    Returns:
        Portfolio PREI score (0-100). Higher = more risk exposure.
        Returns None if positions are empty or invalid.

    Example:
        >>> positions = [
        ...     Position(symbol="AAPL", quantity=2, gamma=0.03, vega=15,
        ...              underlying_price=150, dte=30),
        ...     Position(symbol="MSFT", quantity=-1, gamma=-0.02, vega=-10,
        ...              underlying_price=400, dte=20),
        ... ]
        >>> calc_portfolio_prei(positions)
        35.0  # Moderate due to partial hedging
    """
    if not positions:
        return None

    w1, w2, w3 = weights

    # Gamma Risk: Use calc_portfolio_gamma for net gamma (allows hedging offset)
    total_gamma = calc_portfolio_gamma(positions)

    # Vega Risk: Use calc_portfolio_vega for net vega (allows hedging offset)
    total_vega = calc_portfolio_vega(positions)

    # DTE Risk: Gamma-weighted average of position DTE risks
    # DTE_Risk = Σ(DTE_Risk_i × |Γ$_i|) / Σ|Γ$_i|
    weighted_dte_risk = 0.0
    abs_gamma_dollars_sum = 0.0

    for pos in positions:
        gamma = pos.gamma
        price = pos.underlying_price
        dte = pos.dte
        quantity = pos.quantity if pos.quantity is not None else 1
        multiplier = pos.contract_multiplier if pos.contract_multiplier else 100

        # Skip positions with missing gamma/price data
        if gamma is None or price is None or price <= 0:
            continue

        # Calculate |Γ$| for this position (for weighting)
        pos_gamma_dollars = abs(gamma * (price ** 2) * multiplier * quantity / 100)
        abs_gamma_dollars_sum += pos_gamma_dollars

        # DTE risk for this position: sqrt(1/DTE), range (0, 1] for DTE >= 1
        if dte is not None and dte > 0:
            dte_risk_i = math.sqrt(1.0 / max(1, dte))
            weighted_dte_risk += dte_risk_i * pos_gamma_dollars

    # If no valid positions with gamma data, return None
    if abs_gamma_dollars_sum == 0:
        return None

    # Calculate average DTE risk (gamma-weighted), already in 0-1 range
    avg_dte_risk = weighted_dte_risk / abs_gamma_dollars_sum if weighted_dte_risk > 0 else 0.0

    # If no DTE data available, use a default moderate DTE risk
    if avg_dte_risk == 0:
        # Default: assume 30 DTE -> sqrt(1/30) ≈ 0.183
        avg_dte_risk = math.sqrt(1.0 / 30)

    # Normalize gamma and vega to 0-1 range
    # Use sigmoid-like normalization: risk = |value| / (|value| + k)
    # This maps any value to (0, 1), with k controlling the "sensitivity"
    # k = 1 means: value of 1 gives risk of 0.5
    gamma_risk = _normalize_to_01(abs(total_gamma), k=1.0)
    vega_risk = _normalize_to_01(abs(total_vega), k=100.0)

    # Weighted combination, scale to 0-100
    portfolio_prei = (w1 * gamma_risk + w2 * vega_risk + w3 * avg_dte_risk) * 100

    return portfolio_prei


def _normalize_to_01(value: float, k: float = 1.0) -> float:
    """Normalize a non-negative value to 0-1 range using sigmoid-like function.

    Formula: normalized = value / (value + k)

    Properties:
    - value=0 -> 0
    - value=k -> 0.5
    - value->inf -> 1

    Args:
        value: Non-negative value to normalize.
        k: Scaling constant. When value=k, output is 0.5.

    Returns:
        Normalized value in range [0, 1).
    """
    if value <= 0:
        return 0.0
    return value / (value + k)
