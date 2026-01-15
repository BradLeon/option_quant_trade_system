"""Portfolio risk metrics calculations.

Portfolio-level module for risk metrics that operate on list[Position].
"""

from src.engine.models.position import Position
from src.engine.portfolio.greeks_agg import (
    calc_delta_dollars,
    calc_portfolio_gamma,
    calc_portfolio_theta,
)


def calc_portfolio_tgr(positions: list[Position]) -> float | None:
    """Calculate standardized Portfolio Theta/Gamma Ratio (TGR).

    Standardized TGR normalizes for stock price and volatility:
        TGR = |Theta$| / Σ(|Gamma| × S² × σ_daily × qty × multiplier) × 100

    Where:
        - Theta$ = Σ(|theta| × qty × multiplier) (theta dollars)
        - S = underlying_price (spot price)
        - σ_daily = IV / √252 (daily volatility from each position's IV)
        - Gamma × S² = "Gamma Dollar" (normalizes gamma across different stock prices)

    Physical meaning:
    - Theta$ is daily income from time decay in dollars
    - Gamma$ (volatility-adjusted) is the dollar gamma risk considering actual IV
    - High TGR = more theta income per unit of volatility-adjusted gamma risk
    - Target: TGR > 1.0 for good theta strategies

    Args:
        positions: List of Position objects with theta, gamma, underlying_price, and iv.

    Returns:
        Standardized TGR value. Higher is better for theta strategies.
        Returns None if gamma_dollars is zero or no valid positions.

    Example:
        # Short put: theta=$50/day, gamma_dollar_vol=$40
        # TGR = (50/40) * 100 = 125 (earn $1.25 theta per $1 gamma risk)
    """
    import math

    if not positions:
        return None

    # Calculate theta dollars
    theta_usd = calc_portfolio_theta(positions)

    # Calculate standardized gamma dollars using each position's IV
    gamma_dollar_sum = 0.0
    for pos in positions:
        if pos.gamma is None or pos.underlying_price is None:
            continue

        # Use position's IV if available, otherwise fall back to 1% (0.01) for legacy behavior
        iv = pos.iv if pos.iv and pos.iv > 0 else 0.01
        sigma_daily = iv / math.sqrt(252)

        # Gamma Dollar = |Gamma| × S² × σ_daily
        gamma_dollar = (
            abs(pos.gamma)
            * (pos.underlying_price**2)
            * sigma_daily
            * pos.contract_multiplier
            * abs(pos.quantity)
        )
        gamma_dollar_sum += gamma_dollar

    if gamma_dollar_sum == 0:
        return None

    # Standardized TGR = |Theta$| / Gamma$ × 100
    return (abs(theta_usd) / gamma_dollar_sum) * 100


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


def calc_vega_weighted_iv_hv(
    positions: list[Position],
    position_iv_hv_ratios: dict[str, float] | None = None,
) -> float | None:
    """Calculate vega-weighted IV/HV ratio for portfolio quality assessment.

    Formula: Σ(|Pos_Vega_i| × IV_HV_i) / Σ(|Pos_Vega_i|)

    Physical meaning:
    - Measures whether the portfolio is selling "expensive" options
    - IV/HV ratio indicates option pricing relative to realized volatility
    - Vega-weighting because a position's contribution to portfolio vol risk
      is proportional to its vega (not premium or delta)
    - > 1.0: Good quality - selling overpriced IV relative to HV
    - 0.8 ~ 1.2: Neutral - fair pricing
    - < 0.8: Poor quality - "underselling" options, insufficient vol premium

    Args:
        positions: List of Position objects with vega values.
        position_iv_hv_ratios: Dict mapping symbol to its IV/HV ratio.
            Must be provided externally as Position model lacks IV/HV data.

    Returns:
        Vega-weighted IV/HV ratio, or None if insufficient data.

    Example:
        # Position A: vega=$500, IV/HV=1.3 (selling overpriced)
        # Position B: vega=$300, IV/HV=0.9 (slightly underpriced)
        # Weighted IV/HV = (500*1.3 + 300*0.9) / (500+300) = 1.15
    """
    if not positions or not position_iv_hv_ratios:
        return None

    total_vega = 0.0
    weighted_sum = 0.0

    for pos in positions:
        if pos.vega is None:
            continue

        # Calculate absolute vega dollars for this position
        pos_vega = abs(pos.vega * pos.quantity * pos.contract_multiplier)
        if pos_vega == 0:
            continue

        # Get IV/HV ratio for this position's underlying
        # Try both the position symbol and underlying (for options)
        iv_hv = position_iv_hv_ratios.get(pos.symbol)
        if iv_hv is None:
            continue

        weighted_sum += pos_vega * iv_hv
        total_vega += pos_vega

    if total_vega == 0:
        return None

    return weighted_sum / total_vega
