"""Portfolio risk metrics calculations."""

import math

import numpy as np

from src.engine.base import Position


def calc_tgr(theta: float, gamma: float) -> float | None:
    """Calculate Theta/Gamma Ratio (TGR).

    TGR measures the ratio of daily time decay income to gamma risk.
    Higher TGR indicates more favorable risk/reward for theta strategies.

    Args:
        theta: Total portfolio theta (daily time decay).
        gamma: Total portfolio gamma.

    Returns:
        TGR value. Higher is better for theta strategies.
        Returns None if gamma is zero.

    Example:
        >>> calc_tgr(-50, 10)  # $50/day theta income, 10 gamma
        5.0
    """
    if gamma is None or gamma == 0:
        return None

    if theta is None:
        return None

    # Use absolute values as theta is typically negative (decay)
    return abs(theta) / abs(gamma)


def calc_roc(profit: float, capital: float) -> float | None:
    """Calculate Return on Capital (ROC).

    Args:
        profit: Realized or unrealized profit.
        capital: Capital employed/at risk.

    Returns:
        ROC as decimal (e.g., 0.15 for 15% return).
        Returns None if capital is zero.

    Example:
        >>> calc_roc(150, 1000)
        0.15
    """
    if capital is None or capital == 0:
        return None

    if profit is None:
        return None

    return profit / capital


def calc_portfolio_var(
    positions: list[Position],
    confidence: float = 0.95,
    daily_vol: float = 0.01,
) -> float | None:
    """Calculate portfolio Value at Risk (VaR).

    Simple parametric VaR based on delta exposure.

    Args:
        positions: List of Position objects.
        confidence: Confidence level (default 95%).
        daily_vol: Assumed daily volatility of underlying (default 1%).

    Returns:
        VaR as positive dollar amount.
        Returns None if insufficient data.
    """
    if not positions:
        return None

    # Calculate total dollar delta
    total_delta_dollars = 0.0
    for pos in positions:
        if pos.delta is not None and pos.market_value is not None:
            total_delta_dollars += abs(pos.delta * pos.quantity * pos.market_value)

    if total_delta_dollars == 0:
        return None

    # Z-score for confidence level
    from scipy import stats

    z_score = stats.norm.ppf(confidence)

    # VaR = delta_dollars * volatility * z_score
    var = total_delta_dollars * daily_vol * z_score

    return abs(var)


def calc_risk_reward_ratio(
    max_profit: float,
    max_loss: float,
) -> float | None:
    """Calculate risk/reward ratio.

    Args:
        max_profit: Maximum potential profit.
        max_loss: Maximum potential loss (as positive number).

    Returns:
        Risk/reward ratio. < 1 means reward exceeds risk.
        Returns None if max_profit is zero.
    """
    if max_profit is None or max_profit == 0:
        return None

    if max_loss is None:
        return None

    return abs(max_loss) / max_profit


def calc_margin_utilization(
    margin_used: float,
    total_margin: float,
) -> float | None:
    """Calculate margin utilization percentage.

    Args:
        margin_used: Current margin used.
        total_margin: Total available margin.

    Returns:
        Utilization as decimal (e.g., 0.50 for 50%).
        Returns None if total_margin is zero.
    """
    if total_margin is None or total_margin == 0:
        return None

    if margin_used is None:
        return None

    return margin_used / total_margin


def calc_portfolio_beta(positions: list[Position]) -> float | None:
    """Calculate portfolio weighted-average beta.

    Args:
        positions: List of Position objects with beta and market_value.

    Returns:
        Portfolio beta.
        Returns None if insufficient data.
    """
    if not positions:
        return None

    total_value = 0.0
    weighted_beta = 0.0

    for pos in positions:
        if pos.beta is not None and pos.market_value is not None:
            value = abs(pos.market_value * pos.quantity)
            weighted_beta += pos.beta * value
            total_value += value

    if total_value == 0:
        return None

    return weighted_beta / total_value


def calc_concentration_risk(positions: list[Position]) -> float | None:
    """Calculate position concentration risk using Herfindahl Index.

    HHI ranges from 0 (highly diversified) to 1 (single position).

    Args:
        positions: List of Position objects with market_value.

    Returns:
        Herfindahl-Hirschman Index (0-1).
        Returns None if insufficient data.
    """
    if not positions:
        return None

    values = []
    for pos in positions:
        if pos.market_value is not None:
            values.append(abs(pos.market_value * pos.quantity))

    if not values or sum(values) == 0:
        return None

    total = sum(values)
    weights = [v / total for v in values]

    # HHI = sum of squared weights
    hhi = sum(w ** 2 for w in weights)

    return hhi
