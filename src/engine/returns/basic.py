"""Basic return calculations."""

import math

import numpy as np


def calc_annualized_return(
    returns: list[float],
    periods_per_year: int = 252,
) -> float | None:
    """Calculate annualized return from a series of periodic returns.

    Uses geometric mean for compounding.

    Args:
        returns: List of periodic returns (as decimals, e.g., 0.01 for 1%).
        periods_per_year: Number of periods in a year (252 for daily, 12 for monthly).

    Returns:
        Annualized return as a decimal.
        Returns None if insufficient data.

    Example:
        >>> daily_returns = [0.001] * 252  # 0.1% daily for a year
        >>> ann_return = calc_annualized_return(daily_returns)
        >>> 0.25 < ann_return < 0.30  # ~28.6% annualized
        True
    """
    if returns is None or len(returns) == 0:
        return None

    # Calculate cumulative return using geometric method
    cumulative = 1.0
    for r in returns:
        cumulative *= (1 + r)

    # Annualize based on number of periods
    n_periods = len(returns)
    if n_periods == 0:
        return None

    # Geometric mean annualized return
    annualized = cumulative ** (periods_per_year / n_periods) - 1

    return annualized


def calc_total_return(returns: list[float]) -> float | None:
    """Calculate total cumulative return.

    Args:
        returns: List of periodic returns (as decimals).

    Returns:
        Total return as a decimal (e.g., 0.5 for 50% total return).
        Returns None if insufficient data.
    """
    if returns is None or len(returns) == 0:
        return None

    cumulative = 1.0
    for r in returns:
        cumulative *= (1 + r)

    return cumulative - 1


def calc_win_rate(trades: list[float]) -> float | None:
    """Calculate win rate from a list of trade P&L.

    Args:
        trades: List of trade profits/losses (positive = win, negative = loss).

    Returns:
        Win rate as a decimal (0-1). E.g., 0.6 means 60% win rate.
        Returns None if no trades.

    Example:
        >>> trades = [100, -50, 200, -30, 150]  # 3 wins, 2 losses
        >>> calc_win_rate(trades)
        0.6
    """
    if trades is None or len(trades) == 0:
        return None

    wins = sum(1 for t in trades if t > 0)
    return wins / len(trades)


def calc_expected_return(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> float | None:
    """Calculate expected return per trade.

    Formula: E[R] = win_rate * avg_win - (1 - win_rate) * avg_loss

    Args:
        win_rate: Probability of winning (0-1).
        avg_win: Average profit when winning (positive number).
        avg_loss: Average loss when losing (positive number, will be treated as loss).

    Returns:
        Expected return per trade.
        Returns None if any input is None.

    Example:
        >>> calc_expected_return(0.6, 100, 50)  # 60% win rate, $100 avg win, $50 avg loss
        40.0
    """
    if win_rate is None or avg_win is None or avg_loss is None:
        return None

    return win_rate * avg_win - (1 - win_rate) * abs(avg_loss)


def calc_expected_std(returns: list[float]) -> float | None:
    """Calculate standard deviation of returns.

    Args:
        returns: List of periodic returns (as decimals).

    Returns:
        Standard deviation of returns.
        Returns None if insufficient data.
    """
    if returns is None or len(returns) < 2:
        return None

    return float(np.std(returns, ddof=1))


def calc_average_win(trades: list[float]) -> float | None:
    """Calculate average winning trade.

    Args:
        trades: List of trade profits/losses.

    Returns:
        Average profit of winning trades.
        Returns None if no winning trades.
    """
    if trades is None:
        return None

    wins = [t for t in trades if t > 0]
    if len(wins) == 0:
        return None

    return sum(wins) / len(wins)


def calc_average_loss(trades: list[float]) -> float | None:
    """Calculate average losing trade.

    Args:
        trades: List of trade profits/losses.

    Returns:
        Average loss of losing trades (as positive number).
        Returns None if no losing trades.
    """
    if trades is None:
        return None

    losses = [abs(t) for t in trades if t < 0]
    if len(losses) == 0:
        return None

    return sum(losses) / len(losses)


def calc_profit_factor(trades: list[float]) -> float | None:
    """Calculate profit factor.

    Profit Factor = Gross Profit / Gross Loss

    Args:
        trades: List of trade profits/losses.

    Returns:
        Profit factor. > 1 indicates profitable strategy.
        Returns None if no losses (infinite profit factor).
    """
    if trades is None or len(trades) == 0:
        return None

    gross_profit = sum(t for t in trades if t > 0)
    gross_loss = sum(abs(t) for t in trades if t < 0)

    if gross_loss == 0:
        return None  # Infinite profit factor

    return gross_profit / gross_loss
