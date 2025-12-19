"""Average Directional Index (ADX) calculations.

Position-level module for trend strength analysis using ADX.
ADX measures the strength of a trend (not direction).
"""

from dataclasses import dataclass

from src.engine.models.enums import TrendSignal


@dataclass
class ADXResult:
    """ADX calculation result."""

    adx: float
    plus_di: float  # +DI (Positive Directional Indicator)
    minus_di: float  # -DI (Negative Directional Indicator)


def calc_true_range(high: float, low: float, prev_close: float) -> float:
    """Calculate True Range (TR).

    TR = max(High - Low, |High - PrevClose|, |Low - PrevClose|)

    Args:
        high: Current period high price.
        low: Current period low price.
        prev_close: Previous period close price.

    Returns:
        True Range value.

    Example:
        >>> calc_true_range(50, 45, 47)
        5
    """
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def calc_tr_series(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> list[float]:
    """Calculate True Range series.

    Args:
        highs: List of high prices.
        lows: List of low prices.
        closes: List of close prices.

    Returns:
        List of True Range values (starts from index 1).

    Example:
        >>> highs = [50, 52, 51, 53]
        >>> lows = [48, 49, 48, 50]
        >>> closes = [49, 51, 49, 52]
        >>> tr = calc_tr_series(highs, lows, closes)
        >>> len(tr) == 3
        True
    """
    if len(highs) != len(lows) or len(highs) != len(closes):
        return []

    if len(highs) < 2:
        return []

    tr_list = []
    for i in range(1, len(highs)):
        tr = calc_true_range(highs[i], lows[i], closes[i - 1])
        tr_list.append(tr)

    return tr_list


def _calc_wilder_smoothed(values: list[float], period: int) -> list[float]:
    """Calculate Wilder's Smoothed values.

    Wilder's smoothing uses:
    - First value: SUM of first N values
    - Subsequent: Previous - (Previous / N) + Current

    This is equivalent to an EMA with alpha = 1/N.

    Args:
        values: List of values to smooth.
        period: Smoothing period.

    Returns:
        List of smoothed values (same length as input minus period + 1).
    """
    if len(values) < period:
        return []

    result = []

    # First smoothed value is SUM of first N values
    first_sum = sum(values[:period])
    result.append(first_sum)

    # Subsequent values use Wilder smoothing
    for i in range(period, len(values)):
        smoothed = result[-1] - (result[-1] / period) + values[i]
        result.append(smoothed)

    return result


def calc_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> ADXResult | None:
    """Calculate Average Directional Index (ADX) with +DI and -DI.

    ADX measures trend strength (not direction):
    - ADX > 25: Strong trend
    - ADX 20-25: Emerging/weak trend
    - ADX < 20: Ranging/no trend

    Args:
        highs: List of high prices (oldest to newest).
        lows: List of low prices.
        closes: List of close prices.
        period: ADX period (default 14).

    Returns:
        ADXResult with adx, plus_di, minus_di.
        Returns None if insufficient data.

    Example:
        >>> # Minimum 2 * period + 1 data points needed
        >>> highs = [50 + i * 0.5 for i in range(30)]  # Uptrend
        >>> lows = [48 + i * 0.5 for i in range(30)]
        >>> closes = [49 + i * 0.5 for i in range(30)]
        >>> result = calc_adx(highs, lows, closes, period=14)
        >>> result.adx > 20  # Should show trend
        True
    """
    n = len(highs)
    if n != len(lows) or n != len(closes):
        return None

    # Need at least 2 * period data points for meaningful ADX
    if n < 2 * period:
        return None

    # Calculate True Range series
    tr_list = []
    plus_dm_list = []  # +DM (Directional Movement)
    minus_dm_list = []  # -DM

    for i in range(1, n):
        # True Range
        tr = calc_true_range(highs[i], lows[i], closes[i - 1])
        tr_list.append(tr)

        # Directional Movement
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        # +DM: Up move is greater and positive
        if up_move > down_move and up_move > 0:
            plus_dm_list.append(up_move)
        else:
            plus_dm_list.append(0)

        # -DM: Down move is greater and positive
        if down_move > up_move and down_move > 0:
            minus_dm_list.append(down_move)
        else:
            minus_dm_list.append(0)

    # Smooth TR, +DM, -DM using Wilder's method
    smoothed_tr = _calc_wilder_smoothed(tr_list, period)
    smoothed_plus_dm = _calc_wilder_smoothed(plus_dm_list, period)
    smoothed_minus_dm = _calc_wilder_smoothed(minus_dm_list, period)

    if not smoothed_tr or not smoothed_plus_dm or not smoothed_minus_dm:
        return None

    # Calculate +DI and -DI series
    plus_di_list = []
    minus_di_list = []
    dx_list = []

    for i in range(len(smoothed_tr)):
        if smoothed_tr[i] == 0:
            plus_di_list.append(0)
            minus_di_list.append(0)
            dx_list.append(0)
            continue

        plus_di = 100 * smoothed_plus_dm[i] / smoothed_tr[i]
        minus_di = 100 * smoothed_minus_dm[i] / smoothed_tr[i]
        plus_di_list.append(plus_di)
        minus_di_list.append(minus_di)

        # DX = |+DI - -DI| / (+DI + -DI) * 100
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_list.append(0)
        else:
            dx = abs(plus_di - minus_di) / di_sum * 100
            dx_list.append(dx)

    # Calculate ADX as smoothed average of DX
    # First ADX = average of first N DX values
    # Subsequent: ADX = ((Prior ADX × (N-1)) + Current DX) / N
    if len(dx_list) < period:
        return None

    adx_list = []

    # First ADX is simple average of first N DX values
    first_adx = sum(dx_list[:period]) / period
    adx_list.append(first_adx)

    # Subsequent ADX values use Wilder smoothing
    for i in range(period, len(dx_list)):
        adx = (adx_list[-1] * (period - 1) + dx_list[i]) / period
        adx_list.append(adx)

    if not adx_list:
        return None

    return ADXResult(
        adx=adx_list[-1],
        plus_di=plus_di_list[-1],
        minus_di=minus_di_list[-1],
    )


def interpret_adx(adx: float) -> str:
    """Interpret ADX value.

    Args:
        adx: ADX value (0-100).

    Returns:
        Trend strength description:
        - 'strong_trend': ADX > 25
        - 'emerging_trend': ADX 20-25
        - 'weak_trend': ADX 15-20
        - 'ranging': ADX < 15

    Example:
        >>> interpret_adx(30)
        'strong_trend'
        >>> interpret_adx(10)
        'ranging'
    """
    if adx is None:
        return "unknown"

    if adx > 25:
        return "strong_trend"
    elif adx >= 20:
        return "emerging_trend"
    elif adx >= 15:
        return "weak_trend"
    else:
        return "ranging"


def get_adx_trend_direction(plus_di: float, minus_di: float) -> TrendSignal:
    """Get trend direction from DI crossover.

    Args:
        plus_di: +DI value.
        minus_di: -DI value.

    Returns:
        TrendSignal based on DI relationship:
        - BULLISH: +DI > -DI (uptrend)
        - BEARISH: -DI > +DI (downtrend)
        - NEUTRAL: values are approximately equal

    Example:
        >>> get_adx_trend_direction(25, 15)
        <TrendSignal.BULLISH: 'bullish'>
        >>> get_adx_trend_direction(15, 30)
        <TrendSignal.BEARISH: 'bearish'>
    """
    if plus_di is None or minus_di is None:
        return TrendSignal.NEUTRAL

    # Use 2-point threshold to avoid noise
    threshold = 2.0

    if plus_di > minus_di + threshold:
        return TrendSignal.BULLISH
    elif minus_di > plus_di + threshold:
        return TrendSignal.BEARISH
    else:
        return TrendSignal.NEUTRAL


def is_trending(adx: float, threshold: float = 25) -> bool:
    """Check if market is trending.

    Args:
        adx: ADX value.
        threshold: ADX threshold for trending market (default 25).

    Returns:
        True if ADX > threshold (market is trending).

    Example:
        >>> is_trending(30)
        True
        >>> is_trending(15)
        False
    """
    if adx is None:
        return False
    return adx > threshold


def is_ranging(adx: float, threshold: float = 20) -> bool:
    """Check if market is ranging (sideways).

    Args:
        adx: ADX value.
        threshold: ADX threshold for ranging market (default 20).

    Returns:
        True if ADX < threshold (market is ranging).

    Example:
        >>> is_ranging(15)
        True
        >>> is_ranging(30)
        False
    """
    if adx is None:
        return False
    return adx < threshold


def is_adx_favorable_for_strangle(
    adx: float,
    max_adx: float = 25,
) -> bool:
    """Check if ADX is favorable for selling strangles.

    Strangles profit when price stays in a range.
    Favorable conditions: Low ADX (market is ranging).

    Args:
        adx: Current ADX value.
        max_adx: Maximum ADX for strangle (default 25).

    Returns:
        True if ADX indicates ranging market.
    """
    if adx is None:
        return False
    return adx < max_adx


def is_adx_favorable_for_directional(
    adx: float,
    plus_di: float,
    minus_di: float,
    min_adx: float = 20,
) -> tuple[bool, TrendSignal]:
    """Check if ADX is favorable for directional strategies.

    Directional strategies (e.g., short put in uptrend) work best
    with strong trends.

    Args:
        adx: Current ADX value.
        plus_di: +DI value.
        minus_di: -DI value.
        min_adx: Minimum ADX for trend (default 20).

    Returns:
        Tuple of (is_favorable, direction).
    """
    if adx is None or plus_di is None or minus_di is None:
        return (False, TrendSignal.NEUTRAL)

    if adx < min_adx:
        return (False, TrendSignal.NEUTRAL)

    direction = get_adx_trend_direction(plus_di, minus_di)
    return (True, direction)
