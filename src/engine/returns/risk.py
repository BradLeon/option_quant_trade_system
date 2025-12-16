"""Risk metrics calculations."""

import math

import numpy as np


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
    if returns is None or len(returns) < 10:
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
    if returns is None or len(returns) < 10:
        return None

    returns_array = np.array(returns)
    var_percentile = np.percentile(returns_array, (1 - confidence) * 100)

    # Expected shortfall: mean of returns below VaR
    tail_returns = returns_array[returns_array <= var_percentile]

    if len(tail_returns) == 0:
        return None

    return abs(float(np.mean(tail_returns)))
