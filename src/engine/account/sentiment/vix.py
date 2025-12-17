"""VIX interpretation and analysis.

Account-level module for VIX-based market sentiment analysis.
"""

from src.engine.models.enums import TrendSignal, VixZone


def interpret_vix(vix_value: float) -> TrendSignal:
    """Interpret VIX value as a market signal.

    Higher VIX generally indicates fear, which can be contrarian bullish.
    Lower VIX indicates complacency, which can be contrarian bearish.

    Args:
        vix_value: Current VIX index value.

    Returns:
        TrendSignal indicating market sentiment.
        - BULLISH: VIX > 25 (fear, potential buying opportunity)
        - BEARISH: VIX < 15 (complacency, potential warning)
        - NEUTRAL: VIX 15-25 (normal conditions)

    Example:
        >>> interpret_vix(30)
        <TrendSignal.BULLISH: 'bullish'>
        >>> interpret_vix(12)
        <TrendSignal.BEARISH: 'bearish'>
    """
    if vix_value is None:
        return TrendSignal.NEUTRAL

    if vix_value > 25:
        return TrendSignal.BULLISH  # High fear = potential buy
    elif vix_value < 15:
        return TrendSignal.BEARISH  # Low fear/complacency = potential warning
    else:
        return TrendSignal.NEUTRAL


def get_vix_zone(vix_value: float) -> VixZone:
    """Categorize VIX into volatility zones.

    Args:
        vix_value: Current VIX index value.

    Returns:
        VixZone enum indicating the volatility regime.

    Example:
        >>> get_vix_zone(12)
        <VixZone.LOW: 'low'>
        >>> get_vix_zone(22)
        <VixZone.ELEVATED: 'elevated'>
    """
    if vix_value is None:
        return VixZone.NORMAL

    if vix_value < 15:
        return VixZone.LOW
    elif vix_value < 20:
        return VixZone.NORMAL
    elif vix_value < 25:
        return VixZone.ELEVATED
    elif vix_value < 35:
        return VixZone.HIGH
    else:
        return VixZone.EXTREME


def is_vix_favorable_for_selling(vix_value: float, min_vix: float = 15.0) -> bool:
    """Check if VIX is favorable for option selling strategies.

    Higher VIX means higher premiums for option sellers.

    Args:
        vix_value: Current VIX value.
        min_vix: Minimum VIX for favorable conditions.

    Returns:
        True if VIX is above minimum threshold.
    """
    if vix_value is None:
        return False
    return vix_value >= min_vix


def calc_vix_percentile(
    current_vix: float,
    historical_vix: list[float],
) -> float | None:
    """Calculate VIX percentile rank in historical context.

    Args:
        current_vix: Current VIX value.
        historical_vix: List of historical VIX values.

    Returns:
        Percentile (0-100) indicating where current VIX ranks historically.
    """
    if current_vix is None or historical_vix is None or len(historical_vix) == 0:
        return None

    count_lower = sum(1 for v in historical_vix if v < current_vix)
    return count_lower / len(historical_vix) * 100


def get_vix_regime(vix_value: float) -> str:
    """Get a descriptive regime name for current VIX level.

    Args:
        vix_value: Current VIX value.

    Returns:
        String description of market regime.
    """
    zone = get_vix_zone(vix_value)

    regime_names = {
        VixZone.LOW: "complacent_market",
        VixZone.NORMAL: "normal_market",
        VixZone.ELEVATED: "uncertain_market",
        VixZone.HIGH: "fearful_market",
        VixZone.EXTREME: "panic_market",
    }

    return regime_names.get(zone, "unknown")
