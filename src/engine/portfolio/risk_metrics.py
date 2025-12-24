"""Portfolio risk metrics calculations.

Portfolio-level module for risk metrics that operate on list[Position].
"""

from src.engine.models.position import Position
from src.engine.portfolio.greeks_agg import (
    calc_delta_dollars,
    calc_gamma_dollars,
    calc_portfolio_theta,
)


def calc_portfolio_tgr(positions: list[Position]) -> float | None:
    """Calculate Portfolio Theta/Gamma Ratio (TGR) in dollar terms.

    TGR measures the ratio of daily theta income to gamma risk, both in dollars.
    Higher TGR indicates more favorable risk/reward for theta strategies.

    Formula: TGR = |theta_dollars| / |gamma_dollars|

    Physical meaning:
    - Theta$ is daily income from time decay in dollars
    - Gamma$ is the dollar gamma risk (delta change per 1% move)
    - High TGR = more theta income per dollar of gamma risk
    - Using dollars normalizes across different underlyings and multipliers
    - Typical target: TGR > 0.5-1.0 for income strategies

    Args:
        positions: List of Position objects with theta, gamma, and underlying_price.

    Returns:
        TGR value. Higher is better for theta strategies.
        Returns None if gamma_dollars is zero or no valid positions.

    Example:
        # Short put: theta=$50/day, gamma risk=$100
        # TGR = 50/100 = 0.5 (earn $0.50 theta per $1 gamma risk)
    """
    if not positions:
        return None

    # portfolio_theta is already in USD (converted by AccountAggregator)
    theta_usd = calc_portfolio_theta(positions)
    gamma_dollars = calc_gamma_dollars(positions)

    if gamma_dollars == 0:
        return None

    # Use absolute values as theta is typically negative for short options
    return abs(theta_usd) / abs(gamma_dollars)


def calc_portfolio_var(
    positions: list[Position],
    confidence: float = 0.95,
    daily_vol: float = 0.01,
) -> float | None:
    """Calculate portfolio Value at Risk (VaR).

    Simple parametric VaR based on delta exposure.

    Formula: VaR = |Delta$| × daily_vol × z_score

    Physical meaning:
    - Estimates maximum loss at given confidence level over one day
    - Based on delta exposure (first-order approximation)
    - VaR of $5,000 at 95% means 95% chance daily loss won't exceed $5,000

    Args:
        positions: List of Position objects with delta and underlying_price.
        confidence: Confidence level (default 95%).
        daily_vol: Assumed daily volatility of underlying (default 1%).

    Returns:
        VaR as positive dollar amount.
        Returns None if insufficient data.

    Example:
        # Portfolio with $100,000 delta exposure, 1% daily vol, 95% confidence
        # VaR = 100,000 × 0.01 × 1.645 = $1,645
    """
    if not positions:
        return None

    # Use calc_delta_dollars from greeks_agg for correct calculation
    total_delta_dollars = calc_delta_dollars(positions)

    if total_delta_dollars == 0:
        return None

    # Z-score for confidence level
    from scipy import stats

    z_score = stats.norm.ppf(confidence)

    # VaR = |delta_dollars| × volatility × z_score
    var = abs(total_delta_dollars) * daily_vol * z_score

    return var


def calc_portfolio_beta(positions: list[Position]) -> float | None:
    """Calculate portfolio weighted-average beta.

    Weights by delta dollars (actual directional exposure) not option market value.

    Formula: Portfolio Beta = Σ(beta × |delta_dollars|) / Σ(|delta_dollars|)

    Physical meaning:
    - How the portfolio moves relative to the market
    - Beta of 1.5 means portfolio moves 1.5x the market
    - Weighted by actual risk exposure (delta dollars)

    Args:
        positions: List of Position objects with beta, delta, and underlying_price.

    Returns:
        Portfolio beta.
        Returns None if insufficient data.

    Example:
        # NVDA (beta=1.8) with $50,000 delta exposure
        # AAPL (beta=1.2) with $30,000 delta exposure
        # Portfolio beta = (1.8×50000 + 1.2×30000) / (50000+30000) = 1.575
    """
    if not positions:
        return None

    total_exposure = 0.0
    weighted_beta = 0.0

    for pos in positions:
        if pos.beta is None or pos.delta is None or pos.underlying_price is None:
            continue

        # Weight by delta dollars (actual directional exposure)
        delta_dollars = abs(
            pos.delta * pos.underlying_price * pos.contract_multiplier * pos.quantity
        )
        weighted_beta += pos.beta * delta_dollars
        total_exposure += delta_dollars

    if total_exposure == 0:
        return None

    return weighted_beta / total_exposure


def calc_concentration_risk(positions: list[Position]) -> float | None:
    """Calculate position concentration risk using Herfindahl Index.

    HHI ranges from 1/n (perfectly diversified) to 1 (single position).

    Uses delta dollars as the weight measure, since that represents
    actual directional risk exposure rather than option premium paid.

    Formula: HHI = Σ(weight²) where weight = |delta_dollars| / total

    Physical meaning:
    - HHI = 1.0: All exposure in single position (maximum concentration)
    - HHI = 0.5: Two equal positions
    - HHI = 0.25: Four equal positions
    - Lower HHI = better diversification

    Args:
        positions: List of Position objects with delta and underlying_price.

    Returns:
        Herfindahl-Hirschman Index (0-1).
        Returns None if insufficient data.

    Example:
        # Two positions with equal delta dollars exposure
        # HHI = 0.5² + 0.5² = 0.5
    """
    if not positions:
        return None

    exposures = []
    for pos in positions:
        if pos.delta is not None and pos.underlying_price is not None:
            delta_dollars = abs(
                pos.delta * pos.underlying_price * pos.contract_multiplier * pos.quantity
            )
            if delta_dollars > 0:
                exposures.append(delta_dollars)

    if not exposures or sum(exposures) == 0:
        return None

    total = sum(exposures)
    weights = [e / total for e in exposures]

    # HHI = sum of squared weights
    hhi = sum(w ** 2 for w in weights)

    return hhi
