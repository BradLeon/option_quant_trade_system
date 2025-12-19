"""Portfolio Greeks aggregation."""

from src.engine.models.position import Position


def calc_portfolio_delta(positions: list[Position]) -> float:
    """Calculate total portfolio delta.

    Args:
        positions: List of Position objects with delta values.

    Returns:
        Sum of all position deltas.
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.delta is not None:
            total += pos.delta * pos.quantity
    return total


def calc_portfolio_gamma(positions: list[Position]) -> float:
    """Calculate total portfolio gamma.

    Args:
        positions: List of Position objects with gamma values.

    Returns:
        Sum of all position gammas.
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.gamma is not None:
            total += pos.gamma * pos.quantity
    return total


def calc_portfolio_theta(positions: list[Position]) -> float:
    """Calculate total portfolio theta.

    Represents daily time decay of the portfolio.

    Args:
        positions: List of Position objects with theta values.

    Returns:
        Sum of all position thetas (typically negative for long options).
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.theta is not None:
            total += pos.theta * pos.quantity
    return total


def calc_portfolio_vega(positions: list[Position]) -> float:
    """Calculate total portfolio vega.

    Represents sensitivity to changes in implied volatility.

    Args:
        positions: List of Position objects with vega values.

    Returns:
        Sum of all position vegas.
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.vega is not None:
            total += pos.vega * pos.quantity
    return total


def calc_beta_weighted_delta(
    positions: list[Position],
    spy_price: float,
) -> float:
    """Calculate beta-weighted delta normalized to SPY.

    This converts all position deltas to SPY-equivalent shares,
    allowing comparison of directional exposure across different underlyings.

    Formula: BWD = Σ(delta × underlying_price × multiplier × quantity × beta / spy_price)

    Physical meaning:
    - Converts dollar delta exposure to SPY-equivalent shares
    - A BWD of 100 means the portfolio behaves like being long 100 shares of SPY
    - Useful for hedging: to neutralize, short BWD shares of SPY

    Args:
        positions: List of Position objects with delta, beta, and underlying_price.
        spy_price: Current SPY price for normalization.

    Returns:
        Beta-weighted delta in SPY-equivalent shares.

    Example:
        # NVDA Call: delta=0.5, NVDA=$500, beta=1.8, 2 contracts, SPY=$450
        # BWD = 0.5 × 500 × 100 × 2 × 1.8 / 450 = 200 SPY shares
        # This NVDA position moves like 200 shares of SPY
    """
    if not positions or spy_price is None or spy_price <= 0:
        return 0.0

    total_bwd = 0.0
    for pos in positions:
        if pos.delta is None or pos.beta is None or pos.underlying_price is None:
            continue

        # Beta-weighted delta = delta × underlying_price × multiplier × quantity × beta / spy_price
        delta_dollars = pos.delta * pos.underlying_price * pos.contract_multiplier * pos.quantity
        bwd = delta_dollars * pos.beta / spy_price
        total_bwd += bwd

    return total_bwd


def calc_delta_dollars(positions: list[Position]) -> float:
    """Calculate delta exposure in dollar terms.

    Formula: Delta$ = Σ(delta × underlying_price × multiplier × quantity)

    Physical meaning:
    - How much the portfolio value changes when the underlying moves $1
    - Delta$ of $10,000 means a $1 move in underlying changes portfolio by $10,000

    Args:
        positions: List of Position objects with delta and underlying_price.

    Returns:
        Total dollar delta exposure.

    Example:
        # AAPL Call: delta=0.5, AAPL=$150, 3 contracts
        # Delta$ = 0.5 × 150 × 100 × 3 = $22,500
        # If AAPL moves $1, position value changes by $150 (0.5 × 100 × 3)
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.delta is not None and pos.underlying_price is not None:
            # Delta dollars = delta × underlying_price × multiplier × quantity
            total += pos.delta * pos.underlying_price * pos.contract_multiplier * pos.quantity
    return total


def calc_gamma_dollars(positions: list[Position]) -> float:
    """Calculate gamma exposure in dollar terms.

    Formula: Gamma$ = Σ(gamma × underlying_price² × multiplier × quantity / 100)

    Physical meaning:
    - How much Delta$ changes when the underlying moves 1%
    - Gamma$ of $5,000 means a 1% move changes Delta$ by $5,000
    - High Gamma$ means the portfolio's directional exposure changes rapidly

    Args:
        positions: List of Position objects with gamma and underlying_price.

    Returns:
        Total dollar gamma exposure.

    Example:
        # AAPL Call: gamma=0.02, AAPL=$150, 3 contracts
        # Gamma$ = 0.02 × 150² × 100 × 3 / 100 = $1,350
        # A 1% move in AAPL changes Delta$ by $1,350
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.gamma is not None and pos.underlying_price is not None:
            # Gamma dollars = gamma × underlying_price² × multiplier × quantity / 100
            total += (
                pos.gamma
                * pos.underlying_price ** 2
                * pos.contract_multiplier
                * pos.quantity
                / 100
            )
    return total


def summarize_portfolio_greeks(
    positions: list[Position],
    spy_price: float | None = None,
) -> dict[str, float]:
    """Get summary of all portfolio Greeks.

    Args:
        positions: List of Position objects.
        spy_price: Current SPY price (optional, for beta-weighted delta).

    Returns:
        Dictionary with all aggregated Greek values.
    """
    summary = {
        "total_delta": calc_portfolio_delta(positions),
        "total_gamma": calc_portfolio_gamma(positions),
        "total_theta": calc_portfolio_theta(positions),
        "total_vega": calc_portfolio_vega(positions),
        "delta_dollars": calc_delta_dollars(positions),
        "gamma_dollars": calc_gamma_dollars(positions),
    }

    if spy_price is not None and spy_price > 0:
        summary["beta_weighted_delta"] = calc_beta_weighted_delta(positions, spy_price)

    return summary
