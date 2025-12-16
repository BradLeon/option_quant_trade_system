"""Market trend analysis."""

import numpy as np

from src.engine.base import TrendResult, TrendSignal


def calc_sma(prices: list[float], window: int) -> float | None:
    """Calculate Simple Moving Average.

    Args:
        prices: List of prices (oldest to newest).
        window: Number of periods for the moving average.

    Returns:
        SMA value, or None if insufficient data.
    """
    if prices is None or len(prices) < window:
        return None

    return sum(prices[-window:]) / window


def calc_ema(prices: list[float], window: int) -> float | None:
    """Calculate Exponential Moving Average.

    Args:
        prices: List of prices (oldest to newest).
        window: Number of periods for the EMA.

    Returns:
        EMA value, or None if insufficient data.
    """
    if prices is None or len(prices) < window:
        return None

    multiplier = 2 / (window + 1)
    ema = sum(prices[:window]) / window  # Start with SMA

    for price in prices[window:]:
        ema = (price - ema) * multiplier + ema

    return ema


def calc_spy_trend(
    prices: list[float],
    short_window: int = 20,
    long_window: int = 50,
) -> TrendSignal:
    """Calculate SPY/market trend using moving average crossover.

    Uses short and long-term SMA crossover to determine trend.

    Args:
        prices: List of closing prices (oldest to newest).
        short_window: Short-term moving average period.
        long_window: Long-term moving average period.

    Returns:
        TrendSignal: BULLISH if short > long, BEARISH if short < long, NEUTRAL otherwise.

    Example:
        >>> prices = list(range(100, 160))  # Uptrend
        >>> calc_spy_trend(prices)
        <TrendSignal.BULLISH: 'bullish'>
    """
    if prices is None or len(prices) < long_window:
        return TrendSignal.NEUTRAL

    short_ma = calc_sma(prices, short_window)
    long_ma = calc_sma(prices, long_window)

    if short_ma is None or long_ma is None:
        return TrendSignal.NEUTRAL

    # Calculate percentage difference
    diff_pct = (short_ma - long_ma) / long_ma

    # Use a small threshold to avoid noise
    threshold = 0.005  # 0.5%

    if diff_pct > threshold:
        return TrendSignal.BULLISH
    elif diff_pct < -threshold:
        return TrendSignal.BEARISH
    else:
        return TrendSignal.NEUTRAL


def calc_trend_strength(
    prices: list[float],
    window: int = 20,
) -> float | None:
    """Calculate trend strength.

    Uses the slope of a linear regression normalized by volatility.

    Args:
        prices: List of closing prices (oldest to newest).
        window: Number of periods to analyze.

    Returns:
        Trend strength from -1 (strong bearish) to 1 (strong bullish).
        Returns None if insufficient data.
    """
    if prices is None or len(prices) < window:
        return None

    recent_prices = prices[-window:]

    # Linear regression slope
    x = np.arange(window)
    y = np.array(recent_prices)

    # Calculate slope using least squares
    x_mean = np.mean(x)
    y_mean = np.mean(y)

    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)

    if denominator == 0:
        return 0.0

    slope = numerator / denominator

    # Normalize by average price and window
    normalized_slope = slope / y_mean * window

    # Clamp to [-1, 1]
    return max(-1.0, min(1.0, normalized_slope))


def calc_trend_detailed(
    prices: list[float],
    short_window: int = 20,
    long_window: int = 50,
) -> TrendResult:
    """Calculate detailed trend analysis.

    Args:
        prices: List of closing prices (oldest to newest).
        short_window: Short-term moving average period.
        long_window: Long-term moving average period.

    Returns:
        TrendResult with signal, strength, and MA values.
    """
    signal = calc_spy_trend(prices, short_window, long_window)
    strength = calc_trend_strength(prices, short_window) or 0.0

    short_ma = calc_sma(prices, short_window) if prices and len(prices) >= short_window else None
    long_ma = calc_sma(prices, long_window) if prices and len(prices) >= long_window else None

    return TrendResult(
        signal=signal,
        strength=strength,
        short_ma=short_ma,
        long_ma=long_ma,
    )


def is_above_moving_average(
    price: float,
    prices: list[float],
    window: int = 200,
) -> bool | None:
    """Check if current price is above a moving average.

    Commonly used with 200-day MA as a long-term trend indicator.

    Args:
        price: Current price.
        prices: Historical prices for MA calculation.
        window: Moving average period.

    Returns:
        True if price is above MA, False if below, None if insufficient data.
    """
    ma = calc_sma(prices, window)
    if ma is None:
        return None
    return price > ma
