"""Portfolio Greeks aggregation."""

from src.engine.base import Position


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

    This converts all position deltas to SPY-equivalent units,
    allowing comparison across different underlyings.

    Formula: BWD = Sum(position_delta * position_price / spy_price * beta)

    Args:
        positions: List of Position objects with delta and beta values.
        spy_price: Current SPY price for normalization.

    Returns:
        Beta-weighted delta in SPY-equivalent shares.

    Example:
        A portfolio with BWD of 100 behaves like being long 100 shares of SPY.
    """
    if not positions or spy_price is None or spy_price <= 0:
        return 0.0

    total_bwd = 0.0
    for pos in positions:
        if pos.delta is None or pos.beta is None:
            continue

        # Get position value (use market_value if available)
        if pos.market_value is not None:
            pos_value = pos.market_value
        else:
            continue  # Can't calculate without position value

        # Beta-weighted delta = delta * (position_value / spy_price) * beta
        bwd = pos.delta * pos.quantity * pos_value / spy_price * pos.beta
        total_bwd += bwd

    return total_bwd


def calc_delta_dollars(positions: list[Position]) -> float:
    """Calculate delta exposure in dollar terms.

    Args:
        positions: List of Position objects with delta and market_value.

    Returns:
        Total dollar delta exposure.
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.delta is not None and pos.market_value is not None:
            # Delta dollars = delta * quantity * position value
            total += pos.delta * pos.quantity * abs(pos.market_value)
    return total


def calc_gamma_dollars(positions: list[Position]) -> float:
    """Calculate gamma exposure in dollar terms.

    Represents how much delta changes for a 1% move in underlying.

    Args:
        positions: List of Position objects with gamma and market_value.

    Returns:
        Total dollar gamma exposure.
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.gamma is not None and pos.market_value is not None:
            # Gamma dollars = gamma * quantity * position value * price / 100
            total += pos.gamma * pos.quantity * abs(pos.market_value) / 100
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
