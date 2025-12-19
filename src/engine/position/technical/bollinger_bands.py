"""Bollinger Bands calculations.

Position-level module for volatility analysis and mean reversion using Bollinger Bands.
"""

import math
from dataclasses import dataclass


@dataclass
class BollingerBands:
    """Bollinger Bands result."""

    upper: float  # Upper band = SMA + (num_std * std)
    middle: float  # Middle band = SMA
    lower: float  # Lower band = SMA - (num_std * std)
    bandwidth: float  # Bandwidth = (upper - lower) / middle
    percent_b: float  # %B = (price - lower) / (upper - lower)


def _calc_std(values: list[float]) -> float:
    """Calculate population standard deviation.

    Args:
        values: List of values.

    Returns:
        Standard deviation.
    """
    if not values:
        return 0.0

    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    return math.sqrt(variance)


def calc_bollinger_bands(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerBands | None:
    """Calculate Bollinger Bands.

    - Upper Band = SMA + (num_std * std)
    - Middle Band = SMA
    - Lower Band = SMA - (num_std * std)

    Args:
        prices: List of closing prices (oldest to newest).
        period: BB period (default 20).
        num_std: Number of standard deviations (default 2.0).

    Returns:
        BollingerBands with upper, middle, lower, bandwidth, percent_b.
        Returns None if insufficient data.

    Example:
        >>> prices = [20, 21, 22, 21, 20, 21, 22, 23, 22, 21,
        ...           22, 23, 24, 23, 22, 23, 24, 25, 24, 23]
        >>> bb = calc_bollinger_bands(prices, period=20, num_std=2.0)
        >>> bb.lower < bb.middle < bb.upper
        True
    """
    if prices is None or len(prices) < period:
        return None

    # Get last N prices
    recent_prices = prices[-period:]

    # Calculate SMA (middle band)
    middle = sum(recent_prices) / period

    # Calculate standard deviation
    std = _calc_std(recent_prices)

    # Calculate bands
    upper = middle + (num_std * std)
    lower = middle - (num_std * std)

    # Calculate bandwidth
    bandwidth = (upper - lower) / middle if middle != 0 else 0

    # Calculate %B using current price
    current_price = prices[-1]
    band_width = upper - lower
    if band_width != 0:
        percent_b = (current_price - lower) / band_width
    else:
        percent_b = 0.5  # At middle if bands are flat

    return BollingerBands(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        percent_b=percent_b,
    )


def calc_bollinger_series(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> list[BollingerBands | None]:
    """Calculate Bollinger Bands series for all data points.

    Args:
        prices: List of closing prices.
        period: BB period.
        num_std: Number of standard deviations.

    Returns:
        List of BollingerBands (None for initial periods without enough data).

    Example:
        >>> prices = list(range(1, 25))  # 24 prices
        >>> bb_series = calc_bollinger_series(prices, period=20)
        >>> len(bb_series) == 24
        True
    """
    if prices is None or len(prices) < period:
        return []

    result: list[BollingerBands | None] = [None] * (period - 1)

    for i in range(period - 1, len(prices)):
        bb = calc_bollinger_bands(prices[: i + 1], period, num_std)
        result.append(bb)

    return result


def calc_percent_b(price: float, bb: BollingerBands) -> float:
    """Calculate %B indicator.

    %B shows where price is relative to the bands:
    - %B > 1: Price above upper band (overbought)
    - %B = 1: Price at upper band
    - %B = 0.5: Price at middle band
    - %B = 0: Price at lower band
    - %B < 0: Price below lower band (oversold)

    Args:
        price: Current price.
        bb: BollingerBands object.

    Returns:
        %B value.

    Example:
        >>> bb = BollingerBands(upper=110, middle=100, lower=90,
        ...                     bandwidth=0.2, percent_b=0.5)
        >>> calc_percent_b(105, bb)
        0.75
    """
    if bb is None:
        return 0.5

    band_width = bb.upper - bb.lower
    if band_width == 0:
        return 0.5

    return (price - bb.lower) / band_width


def calc_bandwidth(bb: BollingerBands) -> float:
    """Calculate Bollinger Bandwidth.

    Bandwidth = (Upper - Lower) / Middle
    Measures the width of the bands relative to the middle band.
    Used to identify periods of low/high volatility.

    Args:
        bb: BollingerBands object.

    Returns:
        Bandwidth value.

    Example:
        >>> bb = BollingerBands(upper=110, middle=100, lower=90,
        ...                     bandwidth=0.2, percent_b=0.5)
        >>> calc_bandwidth(bb)
        0.2
    """
    if bb is None or bb.middle == 0:
        return 0.0

    return (bb.upper - bb.lower) / bb.middle


def is_squeeze(bandwidth: float, threshold: float = 0.1) -> bool:
    """Check if Bollinger Bands are in squeeze (low volatility).

    A squeeze indicates the bands are narrowing, which often
    precedes a significant price move (breakout).

    Args:
        bandwidth: Bollinger Bandwidth value.
        threshold: Squeeze threshold (default 0.1 = 10%).

    Returns:
        True if bandwidth is below threshold.

    Example:
        >>> is_squeeze(0.05)
        True
        >>> is_squeeze(0.15)
        False
    """
    if bandwidth is None:
        return False
    return bandwidth < threshold


def interpret_bb_position(percent_b: float) -> str:
    """Interpret price position in Bollinger Bands.

    Args:
        percent_b: %B value.

    Returns:
        Position description:
        - 'overbought': %B > 1 (above upper band)
        - 'upper_zone': %B 0.8-1.0 (near upper band)
        - 'middle': %B 0.2-0.8 (middle zone)
        - 'lower_zone': %B 0-0.2 (near lower band)
        - 'oversold': %B < 0 (below lower band)

    Example:
        >>> interpret_bb_position(1.2)
        'overbought'
        >>> interpret_bb_position(0.5)
        'middle'
        >>> interpret_bb_position(-0.1)
        'oversold'
    """
    if percent_b is None:
        return "unknown"

    if percent_b > 1.0:
        return "overbought"
    elif percent_b >= 0.8:
        return "upper_zone"
    elif percent_b >= 0.2:
        return "middle"
    elif percent_b >= 0:
        return "lower_zone"
    else:
        return "oversold"


def get_bb_zone(percent_b: float) -> str:
    """Get detailed Bollinger Band zone.

    Args:
        percent_b: %B value.

    Returns:
        Detailed zone description.
    """
    if percent_b is None:
        return "unknown"

    if percent_b > 1.2:
        return "extreme_overbought"
    elif percent_b > 1.0:
        return "overbought"
    elif percent_b >= 0.8:
        return "upper_band"
    elif percent_b >= 0.6:
        return "upper_middle"
    elif percent_b >= 0.4:
        return "middle"
    elif percent_b >= 0.2:
        return "lower_middle"
    elif percent_b >= 0:
        return "lower_band"
    elif percent_b >= -0.2:
        return "oversold"
    else:
        return "extreme_oversold"


def is_favorable_for_selling(
    percent_b: float,
    min_b: float = 0.2,
    max_b: float = 0.8,
) -> bool:
    """Check if BB position is favorable for option selling.

    Option selling (e.g., short put, covered call, strangle)
    works best when price is in the middle zone of Bollinger Bands,
    avoiding extreme positions that may lead to breakouts.

    Args:
        percent_b: %B value.
        min_b: Minimum %B for favorable zone (default 0.2).
        max_b: Maximum %B for favorable zone (default 0.8).

    Returns:
        True if %B is in favorable range.

    Example:
        >>> is_favorable_for_selling(0.5)
        True
        >>> is_favorable_for_selling(1.1)
        False
    """
    if percent_b is None:
        return False
    return min_b <= percent_b <= max_b


def is_favorable_for_short_put(
    percent_b: float,
    bb: BollingerBands | None = None,
) -> bool:
    """Check if conditions are favorable for short put.

    Favorable conditions:
    - Price in middle to upper zone (%B >= 0.3)
    - Not extremely overbought (risk of pullback)

    Args:
        percent_b: %B value.
        bb: Optional BollingerBands for additional analysis.

    Returns:
        True if favorable for short put.
    """
    if percent_b is None:
        return False

    # Want price above lower band but not extremely overbought
    return 0.3 <= percent_b <= 1.0


def is_favorable_for_covered_call(
    percent_b: float,
    bb: BollingerBands | None = None,
) -> bool:
    """Check if conditions are favorable for covered call.

    Favorable conditions:
    - Price in middle to lower zone (room to move up)
    - Not oversold (underlying might drop further)

    Args:
        percent_b: %B value.
        bb: Optional BollingerBands for additional analysis.

    Returns:
        True if favorable for covered call.
    """
    if percent_b is None:
        return False

    # Want price with room to appreciate but not overbought
    return 0.2 <= percent_b <= 0.7


def get_volatility_signal(bandwidth: float, squeeze_threshold: float = 0.1) -> str:
    """Get volatility signal from Bollinger Bandwidth.

    Args:
        bandwidth: Bollinger Bandwidth value.
        squeeze_threshold: Threshold for squeeze detection.

    Returns:
        Volatility signal:
        - 'squeeze': Very low volatility, potential breakout coming
        - 'low': Low volatility
        - 'normal': Normal volatility
        - 'high': High volatility
        - 'extreme': Extremely high volatility

    Example:
        >>> get_volatility_signal(0.05)
        'squeeze'
        >>> get_volatility_signal(0.15)
        'normal'
    """
    if bandwidth is None:
        return "unknown"

    if bandwidth < squeeze_threshold:
        return "squeeze"
    elif bandwidth < 0.15:
        return "low"
    elif bandwidth < 0.25:
        return "normal"
    elif bandwidth < 0.4:
        return "high"
    else:
        return "extreme"
