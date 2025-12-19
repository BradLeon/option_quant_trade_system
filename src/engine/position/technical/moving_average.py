"""Moving Average (MA/EMA) calculations.

Position-level module for trend analysis using moving averages.
Supports Simple Moving Average (SMA) and Exponential Moving Average (EMA).
"""

from dataclasses import dataclass

from src.engine.models.enums import TrendSignal


@dataclass
class MovingAverageResult:
    """Moving average calculation result."""

    period: int
    sma: float | None
    ema: float | None


def calc_sma(prices: list[float], period: int = 20) -> float | None:
    """Calculate Simple Moving Average (SMA).

    SMA = Sum of last N prices / N

    Args:
        prices: List of closing prices (oldest to newest).
        period: MA period (default 20).

    Returns:
        SMA value.
        Returns None if insufficient data.

    Example:
        >>> prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        >>> calc_sma(prices, period=5)
        18.0
    """
    if prices is None or len(prices) < period:
        return None

    return sum(prices[-period:]) / period


def calc_ema(prices: list[float], period: int = 20) -> float | None:
    """Calculate Exponential Moving Average (EMA).

    EMA = Price × k + EMA_prev × (1-k)
    where k = 2 / (period + 1)

    Args:
        prices: List of closing prices (oldest to newest).
        period: EMA period (default 20).

    Returns:
        EMA value.
        Returns None if insufficient data.

    Example:
        >>> prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        >>> ema = calc_ema(prices, period=5)
        >>> 17 < ema < 20
        True
    """
    if prices is None or len(prices) < period:
        return None

    # Multiplier (smoothing factor)
    k = 2 / (period + 1)

    # Start with SMA for initial EMA value
    ema = sum(prices[:period]) / period

    # Calculate EMA for remaining prices
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)

    return ema


def calc_sma_series(prices: list[float], period: int = 20) -> list[float | None]:
    """Calculate SMA series for all data points.

    Args:
        prices: List of closing prices.
        period: SMA period.

    Returns:
        List of SMA values (None for initial periods without enough data).

    Example:
        >>> prices = [1, 2, 3, 4, 5]
        >>> calc_sma_series(prices, period=3)
        [None, None, 2.0, 3.0, 4.0]
    """
    if prices is None or len(prices) < period:
        return []

    result: list[float | None] = [None] * (period - 1)

    for i in range(period - 1, len(prices)):
        sma = sum(prices[i - period + 1 : i + 1]) / period
        result.append(sma)

    return result


def calc_ema_series(prices: list[float], period: int = 20) -> list[float | None]:
    """Calculate EMA series for all data points.

    Args:
        prices: List of closing prices.
        period: EMA period.

    Returns:
        List of EMA values (None for initial periods without enough data).

    Example:
        >>> prices = [1, 2, 3, 4, 5]
        >>> ema_series = calc_ema_series(prices, period=3)
        >>> len(ema_series) == 5
        True
    """
    if prices is None or len(prices) < period:
        return []

    k = 2 / (period + 1)

    result: list[float | None] = [None] * (period - 1)

    # First EMA is SMA
    ema = sum(prices[:period]) / period
    result.append(ema)

    # Calculate EMA for remaining prices
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
        result.append(ema)

    return result


def interpret_ma_crossover(short_ma: float, long_ma: float) -> TrendSignal:
    """Interpret MA crossover signal.

    Args:
        short_ma: Short-term moving average value.
        long_ma: Long-term moving average value.

    Returns:
        TrendSignal based on MA relationship:
        - BULLISH: short > long (golden cross / uptrend)
        - BEARISH: short < long (death cross / downtrend)
        - NEUTRAL: values are approximately equal

    Example:
        >>> interpret_ma_crossover(50.5, 48.0)
        <TrendSignal.BULLISH: 'bullish'>
        >>> interpret_ma_crossover(45.0, 50.0)
        <TrendSignal.BEARISH: 'bearish'>
    """
    if short_ma is None or long_ma is None:
        return TrendSignal.NEUTRAL

    # Use 0.5% threshold to avoid noise
    threshold = long_ma * 0.005

    if short_ma > long_ma + threshold:
        return TrendSignal.BULLISH
    elif short_ma < long_ma - threshold:
        return TrendSignal.BEARISH
    else:
        return TrendSignal.NEUTRAL


def get_ma_trend(
    prices: list[float],
    short_period: int = 20,
    long_period: int = 50,
    use_ema: bool = False,
) -> TrendSignal:
    """Get trend signal from MA crossover.

    Args:
        prices: List of closing prices.
        short_period: Short MA period (default 20).
        long_period: Long MA period (default 50).
        use_ema: If True, use EMA; otherwise use SMA.

    Returns:
        TrendSignal based on MA crossover.

    Example:
        >>> # Uptrend prices
        >>> prices = list(range(1, 101))  # 1 to 100
        >>> get_ma_trend(prices, 20, 50)
        <TrendSignal.BULLISH: 'bullish'>
    """
    if prices is None or len(prices) < long_period:
        return TrendSignal.NEUTRAL

    calc_func = calc_ema if use_ema else calc_sma
    short_ma = calc_func(prices, short_period)
    long_ma = calc_func(prices, long_period)

    if short_ma is None or long_ma is None:
        return TrendSignal.NEUTRAL

    return interpret_ma_crossover(short_ma, long_ma)


def is_above_ma(price: float, ma: float) -> bool:
    """Check if price is above moving average.

    Args:
        price: Current price.
        ma: Moving average value.

    Returns:
        True if price is above MA.

    Example:
        >>> is_above_ma(105, 100)
        True
        >>> is_above_ma(95, 100)
        False
    """
    if price is None or ma is None:
        return False
    return price > ma


def calc_ma_distance(price: float, ma: float) -> float | None:
    """Calculate percentage distance from moving average.

    Args:
        price: Current price.
        ma: Moving average value.

    Returns:
        Percentage distance from MA.
        Positive if price > MA, negative if price < MA.
        Returns None if inputs are invalid.

    Example:
        >>> calc_ma_distance(110, 100)
        10.0
        >>> calc_ma_distance(90, 100)
        -10.0
    """
    if price is None or ma is None or ma == 0:
        return None

    return ((price - ma) / ma) * 100


def get_ma_alignment(
    prices: list[float],
    periods: list[int] | None = None,
    use_ema: bool = False,
) -> str:
    """Check MA alignment for trend strength.

    Strong uptrend: price > MA20 > MA50 > MA200
    Strong downtrend: price < MA20 < MA50 < MA200

    Args:
        prices: List of closing prices.
        periods: List of MA periods (default [20, 50, 200]).
        use_ema: If True, use EMA; otherwise use SMA.

    Returns:
        Alignment status:
        - 'strong_bullish': All MAs aligned upward
        - 'bullish': Short-term MAs bullish
        - 'bearish': Short-term MAs bearish
        - 'strong_bearish': All MAs aligned downward
        - 'mixed': No clear alignment
    """
    if periods is None:
        periods = [20, 50, 200]

    if prices is None or len(prices) < max(periods):
        return "mixed"

    calc_func = calc_ema if use_ema else calc_sma
    current_price = prices[-1]

    mas = []
    for period in sorted(periods):
        ma = calc_func(prices, period)
        if ma is None:
            return "mixed"
        mas.append(ma)

    # Check alignment
    # Strong bullish: price > MA20 > MA50 > MA200
    if current_price > mas[0] > mas[1] > mas[2]:
        return "strong_bullish"
    # Strong bearish: price < MA20 < MA50 < MA200
    elif current_price < mas[0] < mas[1] < mas[2]:
        return "strong_bearish"
    # Bullish: price above short-term MAs
    elif current_price > mas[0] and current_price > mas[1]:
        return "bullish"
    # Bearish: price below short-term MAs
    elif current_price < mas[0] and current_price < mas[1]:
        return "bearish"
    else:
        return "mixed"


def is_ma_favorable_for_short_put(
    prices: list[float],
    periods: list[int] | None = None,
    use_ema: bool = False,
) -> bool:
    """Check if MA alignment is favorable for selling put options.

    Favorable conditions:
    - Price above key moving averages (uptrend or neutral)
    - Avoid strong downtrends

    Args:
        prices: List of closing prices.
        periods: List of MA periods to check.
        use_ema: If True, use EMA; otherwise use SMA.

    Returns:
        True if conditions are favorable for short put.
    """
    alignment = get_ma_alignment(prices, periods, use_ema)
    # Favorable: strong_bullish, bullish, or mixed (not bearish)
    return alignment in ("strong_bullish", "bullish", "mixed")
