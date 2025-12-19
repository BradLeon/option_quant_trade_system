"""Support and resistance level calculations.

Position-level module for support/resistance technical analysis.
"""

from src.engine.models.result import SupportResistance


def calc_support_level(
    prices: list[float],
    window: int = 20,
) -> float | None:
    """Calculate support level as recent period low.

    Simple support calculation using the minimum price over a window.

    Args:
        prices: List of closing prices (oldest to newest).
        window: Lookback period for support calculation.

    Returns:
        Support price level.
        Returns None if insufficient data.

    Example:
        >>> prices = [100, 102, 98, 103, 99, 105, 101]
        >>> calc_support_level(prices, window=5)
        99
    """
    if prices is None or len(prices) < window:
        return None

    return min(prices[-window:])


def calc_resistance_level(
    prices: list[float],
    window: int = 20,
) -> float | None:
    """Calculate resistance level as recent period high.

    Simple resistance calculation using the maximum price over a window.

    Args:
        prices: List of closing prices (oldest to newest).
        window: Lookback period for resistance calculation.

    Returns:
        Resistance price level.
        Returns None if insufficient data.
    """
    if prices is None or len(prices) < window:
        return None

    return max(prices[-window:])


def calc_support_distance(
    current_price: float,
    support: float,
) -> float | None:
    """Calculate distance from current price to support level.

    Args:
        current_price: Current stock price.
        support: Support price level.

    Returns:
        Distance as percentage (e.g., 0.05 means 5% above support).
        Returns None if support is zero or either is None.

    Example:
        >>> calc_support_distance(105, 100)
        0.05
    """
    if current_price is None or support is None:
        return None

    if support == 0:
        return None

    return (current_price - support) / support


def calc_resistance_distance(
    current_price: float,
    resistance: float,
) -> float | None:
    """Calculate distance from current price to resistance level.

    Args:
        current_price: Current stock price.
        resistance: Resistance price level.

    Returns:
        Distance as percentage (negative if below resistance).
        Returns None if current_price is zero or either is None.
    """
    if current_price is None or resistance is None:
        return None

    if current_price == 0:
        return None

    return (resistance - current_price) / current_price


def find_support_resistance(
    prices: list[float],
    window: int = 20,
) -> SupportResistance:
    """Find both support and resistance levels.

    Args:
        prices: List of closing prices (oldest to newest).
        window: Lookback period.

    Returns:
        SupportResistance dataclass with support and resistance levels.
    """
    support = calc_support_level(prices, window)
    resistance = calc_resistance_level(prices, window)

    return SupportResistance(
        support=support or 0.0,
        resistance=resistance or 0.0,
    )


def find_pivot_points(
    high: float,
    low: float,
    close: float,
) -> dict[str, float]:
    """Calculate classic pivot points.

    Args:
        high: Previous period high.
        low: Previous period low.
        close: Previous period close.

    Returns:
        Dictionary with pivot point levels (P, R1, R2, R3, S1, S2, S3).
    """
    pivot = (high + low + close) / 3

    return {
        "pivot": pivot,
        "r1": 2 * pivot - low,
        "r2": pivot + (high - low),
        "r3": high + 2 * (pivot - low),
        "s1": 2 * pivot - high,
        "s2": pivot - (high - low),
        "s3": low - 2 * (high - pivot),
    }


def is_near_support(
    current_price: float,
    support: float,
    threshold: float = 0.02,
) -> bool:
    """Check if price is near support level.

    Args:
        current_price: Current price.
        support: Support level.
        threshold: Distance threshold as decimal (default 2%).

    Returns:
        True if price is within threshold of support.
    """
    distance = calc_support_distance(current_price, support)
    if distance is None:
        return False
    return 0 <= distance <= threshold


def is_near_resistance(
    current_price: float,
    resistance: float,
    threshold: float = 0.02,
) -> bool:
    """Check if price is near resistance level.

    Args:
        current_price: Current price.
        resistance: Resistance level.
        threshold: Distance threshold as decimal (default 2%).

    Returns:
        True if price is within threshold of resistance.
    """
    distance = calc_resistance_distance(current_price, resistance)
    if distance is None:
        return False
    return 0 <= distance <= threshold
