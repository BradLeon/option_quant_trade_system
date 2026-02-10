"""Portfolio return calculations.

Portfolio-level module for return time-series analysis.
"""

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


def calc_sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float | None:
    """Calculate annualized Sharpe ratio.

    Formula: Sharpe = (Mean Return - Risk Free Rate) / Std Dev * sqrt(periods_per_year)

    Args:
        returns: List of periodic returns (as decimals).
        risk_free_rate: Risk-free rate per period (as decimal).
        periods_per_year: Number of periods in a year (252 for daily).

    Returns:
        Annualized Sharpe ratio.
        Returns None or 0 if insufficient data or zero volatility.

    Example:
        >>> returns = [0.001, 0.002, -0.001, 0.003, 0.001]
        >>> sharpe = calc_sharpe_ratio(returns)
        >>> sharpe is not None
        True
    """
    if returns is None or len(returns) < 2:
        return None

    returns_array = np.array(returns)
    excess_returns = returns_array - risk_free_rate

    mean_excess = np.mean(excess_returns)
    std_dev = np.std(excess_returns, ddof=1)

    if std_dev == 0:
        return 0.0

    # Annualize Sharpe ratio
    sharpe = (mean_excess / std_dev) * math.sqrt(periods_per_year)

    return float(sharpe)


def calc_sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float | None:
    """Calculate annualized Sortino ratio.

    Like Sharpe but only considers downside volatility.

    Args:
        returns: List of periodic returns (as decimals).
        risk_free_rate: Risk-free rate per period (as decimal).
        periods_per_year: Number of periods in a year.

    Returns:
        Annualized Sortino ratio.
        Returns None if insufficient data.
    """
    if returns is None or len(returns) < 2:
        return None

    returns_array = np.array(returns)
    excess_returns = returns_array - risk_free_rate

    mean_excess = np.mean(excess_returns)

    # Calculate downside deviation (only negative returns)
    negative_returns = excess_returns[excess_returns < 0]
    if len(negative_returns) == 0:
        return None  # No downside risk

    downside_dev = np.std(negative_returns, ddof=1)

    if downside_dev == 0:
        return None

    sortino = (mean_excess / downside_dev) * math.sqrt(periods_per_year)

    return float(sortino)


def calc_max_drawdown(equity_curve: list[float]) -> float | None:
    """Calculate maximum drawdown from an equity curve.

    Max Drawdown = (Peak - Trough) / Peak

    Args:
        equity_curve: List of portfolio values or cumulative returns (oldest to newest).

    Returns:
        Maximum drawdown as a positive decimal (e.g., 0.20 for 20% drawdown).
        Returns 0 if equity is monotonically increasing.
        Returns None if insufficient data.

    Example:
        >>> equity = [100, 110, 105, 120, 100, 130]
        >>> mdd = calc_max_drawdown(equity)
        >>> abs(mdd - 0.1667) < 0.01  # ~16.67% drawdown from 120 to 100
        True
    """
    if equity_curve is None or len(equity_curve) < 2:
        return None

    max_drawdown = 0.0
    peak = equity_curve[0]

    for value in equity_curve:
        if value > peak:
            peak = value
        elif peak > 0:
            drawdown = (peak - value) / peak
            max_drawdown = max(max_drawdown, drawdown)

    return max_drawdown


def calc_calmar_ratio(
    annualized_return: float,
    max_drawdown: float,
) -> float | None:
    """Calculate Calmar ratio.

    Calmar Ratio = Annualized Return / Max Drawdown

    Args:
        annualized_return: Annualized return as decimal.
        max_drawdown: Maximum drawdown as positive decimal.

    Returns:
        Calmar ratio. Higher is better.
        Returns None if max_drawdown is zero.
    """
    if annualized_return is None or max_drawdown is None:
        return None

    if max_drawdown == 0:
        return None

    return annualized_return / max_drawdown


def calc_drawdown_series(equity_curve: list[float]) -> list[float]:
    """Calculate drawdown series from an equity curve.

    Args:
        equity_curve: List of portfolio values.

    Returns:
        List of drawdowns at each point (as positive decimals).
    """
    if equity_curve is None or len(equity_curve) == 0:
        return []

    drawdowns = []
    peak = equity_curve[0]

    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            drawdowns.append((peak - value) / peak)
        else:
            drawdowns.append(0.0)

    return drawdowns


def calc_var(
    returns: list[float],
    confidence: float = 0.95,
) -> float | None:
    """Calculate Value at Risk (VaR) using historical method.

    Args:
        returns: List of periodic returns (as decimals).
        confidence: Confidence level (e.g., 0.95 for 95% VaR).

    Returns:
        VaR as a positive decimal (potential loss at given confidence).
        Returns None if insufficient data.
    """
    if returns is None or len(returns) < 5:
        return None

    returns_array = np.array(returns)
    var_percentile = np.percentile(returns_array, (1 - confidence) * 100)

    return abs(float(var_percentile))


def calc_cvar(
    returns: list[float],
    confidence: float = 0.95,
) -> float | None:
    """Calculate Conditional Value at Risk (CVaR / Expected Shortfall).

    CVaR is the expected loss given that the loss exceeds VaR.

    Args:
        returns: List of periodic returns (as decimals).
        confidence: Confidence level.

    Returns:
        CVaR as a positive decimal.
        Returns None if insufficient data.
    """
    if returns is None or len(returns) < 5:
        return None

    returns_array = np.array(returns)
    var_percentile = np.percentile(returns_array, (1 - confidence) * 100)

    # Expected shortfall: mean of returns below VaR
    tail_returns = returns_array[returns_array <= var_percentile]

    if len(tail_returns) == 0:
        return None

    return abs(float(np.mean(tail_returns)))
