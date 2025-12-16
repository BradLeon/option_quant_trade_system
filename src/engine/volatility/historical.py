"""Historical volatility calculation."""

import math

import numpy as np


def calc_hv(
    prices: list[float],
    window: int = 20,
    annualize: bool = True,
    trading_days_per_year: int = 252,
) -> float | None:
    """Calculate historical volatility from a price series.

    Uses the standard deviation of log returns method.

    Args:
        prices: List of closing prices (oldest to newest).
        window: Number of periods to calculate volatility over.
        annualize: Whether to annualize the volatility. Default True.
        trading_days_per_year: Number of trading days for annualization. Default 252.

    Returns:
        Historical volatility as a decimal (e.g., 0.25 for 25%).
        Returns None if insufficient data.

    Example:
        >>> prices = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109,
        ...           110, 112, 111, 113, 115, 114, 116, 118, 117, 119, 120]
        >>> hv = calc_hv(prices, window=20)
        >>> 0.05 < hv < 0.30  # Reasonable HV range
        True
    """
    if prices is None or len(prices) < window + 1:
        return None

    # Use the most recent 'window + 1' prices to get 'window' returns
    recent_prices = prices[-(window + 1) :]

    # Calculate log returns
    log_returns = []
    for i in range(1, len(recent_prices)):
        if recent_prices[i - 1] <= 0 or recent_prices[i] <= 0:
            return None
        log_returns.append(math.log(recent_prices[i] / recent_prices[i - 1]))

    if len(log_returns) < 2:
        return None

    # Calculate standard deviation of log returns
    returns_array = np.array(log_returns)
    std_dev = np.std(returns_array, ddof=1)  # Sample standard deviation

    if annualize:
        return float(std_dev * math.sqrt(trading_days_per_year))
    return float(std_dev)


def calc_hv_from_returns(
    returns: list[float],
    annualize: bool = True,
    trading_days_per_year: int = 252,
) -> float | None:
    """Calculate historical volatility directly from returns.

    Args:
        returns: List of daily returns (as decimals, e.g., 0.01 for 1%).
        annualize: Whether to annualize the volatility.
        trading_days_per_year: Number of trading days for annualization.

    Returns:
        Historical volatility as a decimal.
        Returns None if insufficient data.
    """
    if returns is None or len(returns) < 2:
        return None

    returns_array = np.array(returns)
    std_dev = np.std(returns_array, ddof=1)

    if annualize:
        return float(std_dev * math.sqrt(trading_days_per_year))
    return float(std_dev)


def calc_realized_volatility(
    prices: list[float],
    window: int = 20,
    trading_days_per_year: int = 252,
) -> list[float]:
    """Calculate rolling realized volatility.

    Args:
        prices: List of closing prices (oldest to newest).
        window: Rolling window size.
        trading_days_per_year: Number of trading days for annualization.

    Returns:
        List of rolling HV values (same length as prices, with NaN for initial periods).
    """
    if prices is None or len(prices) < window + 1:
        return []

    # Calculate log returns
    log_returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] <= 0 or prices[i] <= 0:
            log_returns.append(float("nan"))
        else:
            log_returns.append(math.log(prices[i] / prices[i - 1]))

    # Calculate rolling standard deviation
    result = [float("nan")] * window  # First 'window' values are NaN
    for i in range(window, len(log_returns)):
        window_returns = log_returns[i - window + 1 : i + 1]
        if any(math.isnan(r) for r in window_returns):
            result.append(float("nan"))
        else:
            std_dev = np.std(window_returns, ddof=1)
            result.append(float(std_dev * math.sqrt(trading_days_per_year)))

    return result
