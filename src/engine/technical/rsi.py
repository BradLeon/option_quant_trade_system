"""RSI (Relative Strength Index) calculation."""

from src.engine.base import TrendSignal


def calc_rsi(prices: list[float], period: int = 14) -> float | None:
    """Calculate Relative Strength Index (RSI).

    RSI = 100 - (100 / (1 + RS))
    where RS = Average Gain / Average Loss

    Args:
        prices: List of closing prices (oldest to newest).
        period: RSI period (default 14).

    Returns:
        RSI value (0-100).
        Returns None if insufficient data.

    Example:
        >>> prices = [44, 44.5, 44, 43.5, 44, 44.5, 44, 43.5, 44, 44.5,
        ...           44, 43.5, 44, 44.5, 44]
        >>> rsi = calc_rsi(prices, period=14)
        >>> 30 < rsi < 70
        True
    """
    if prices is None or len(prices) < period + 1:
        return None

    # Calculate price changes
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Separate gains and losses
    gains = [max(0, c) for c in changes]
    losses = [abs(min(0, c)) for c in changes]

    # Calculate initial average gain/loss using SMA
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Use Wilder's smoothing method for remaining periods
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    # Calculate RS and RSI
    if avg_loss == 0:
        return 100.0  # No losses means RSI = 100

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def interpret_rsi(rsi: float) -> TrendSignal:
    """Interpret RSI value as a signal.

    Args:
        rsi: RSI value (0-100).

    Returns:
        TrendSignal based on RSI level.
        - BEARISH: RSI > 70 (overbought, potential reversal down)
        - BULLISH: RSI < 30 (oversold, potential reversal up)
        - NEUTRAL: RSI 30-70

    Example:
        >>> interpret_rsi(75)
        <TrendSignal.BEARISH: 'bearish'>
        >>> interpret_rsi(25)
        <TrendSignal.BULLISH: 'bullish'>
    """
    if rsi is None:
        return TrendSignal.NEUTRAL

    if rsi > 70:
        return TrendSignal.BEARISH  # Overbought
    elif rsi < 30:
        return TrendSignal.BULLISH  # Oversold
    else:
        return TrendSignal.NEUTRAL


def get_rsi_zone(rsi: float) -> str:
    """Categorize RSI into zones.

    Args:
        rsi: RSI value (0-100).

    Returns:
        Zone description string.
    """
    if rsi is None:
        return "unknown"

    if rsi > 80:
        return "extreme_overbought"
    elif rsi > 70:
        return "overbought"
    elif rsi > 60:
        return "bullish"
    elif rsi > 40:
        return "neutral"
    elif rsi > 30:
        return "bearish"
    elif rsi > 20:
        return "oversold"
    else:
        return "extreme_oversold"


def calc_rsi_series(
    prices: list[float],
    period: int = 14,
) -> list[float | None]:
    """Calculate RSI series for all data points.

    Args:
        prices: List of closing prices.
        period: RSI period.

    Returns:
        List of RSI values (None for initial periods without enough data).
    """
    if prices is None or len(prices) < period + 1:
        return []

    result = [None] * period  # First 'period' values are None

    # Calculate for each subsequent point
    for i in range(period, len(prices)):
        rsi = calc_rsi(prices[: i + 1], period)
        result.append(rsi)

    return result


def is_rsi_favorable_for_selling(
    rsi: float,
    min_rsi: float = 40,
    max_rsi: float = 70,
) -> bool:
    """Check if RSI is in a favorable zone for option selling.

    Avoid selling options when RSI is at extremes (potential reversal).

    Args:
        rsi: Current RSI value.
        min_rsi: Minimum RSI (avoid oversold).
        max_rsi: Maximum RSI (avoid overbought).

    Returns:
        True if RSI is in favorable range.
    """
    if rsi is None:
        return False
    return min_rsi <= rsi <= max_rsi
