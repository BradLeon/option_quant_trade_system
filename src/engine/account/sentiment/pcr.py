"""Put/Call Ratio analysis.

Account-level module for PCR-based market sentiment analysis.
"""

from src.engine.models.enums import TrendSignal


def calc_pcr(put_volume: int, call_volume: int) -> float | None:
    """Calculate Put/Call Ratio.

    PCR = Put Volume / Call Volume

    Args:
        put_volume: Total put option volume.
        call_volume: Total call option volume.

    Returns:
        Put/Call ratio. > 1 means more puts than calls.
        Returns None if call_volume is zero.

    Example:
        >>> calc_pcr(1000, 800)
        1.25
        >>> calc_pcr(600, 1000)
        0.6
    """
    if call_volume is None or call_volume == 0:
        return None

    if put_volume is None:
        return None

    return put_volume / call_volume


def interpret_pcr(pcr: float) -> TrendSignal:
    """Interpret Put/Call Ratio as a contrarian indicator.

    High PCR (> 1.0) suggests excessive bearish sentiment,
    which can be contrarian bullish.

    Low PCR (< 0.7) suggests excessive bullish sentiment,
    which can be contrarian bearish.

    Args:
        pcr: Put/Call ratio value.

    Returns:
        TrendSignal as contrarian interpretation.

    Example:
        >>> interpret_pcr(1.2)  # High put buying = contrarian bullish
        <TrendSignal.BULLISH: 'bullish'>
        >>> interpret_pcr(0.5)  # High call buying = contrarian bearish
        <TrendSignal.BEARISH: 'bearish'>
    """
    if pcr is None:
        return TrendSignal.NEUTRAL

    if pcr > 1.0:
        return TrendSignal.BULLISH  # Excessive puts = contrarian bullish
    elif pcr < 0.7:
        return TrendSignal.BEARISH  # Excessive calls = contrarian bearish
    else:
        return TrendSignal.NEUTRAL


def get_pcr_zone(pcr: float) -> str:
    """Categorize PCR into sentiment zones.

    Args:
        pcr: Put/Call ratio value.

    Returns:
        Zone description string.
    """
    if pcr is None:
        return "unknown"

    if pcr > 1.3:
        return "extreme_fear"
    elif pcr > 1.0:
        return "elevated_fear"
    elif pcr > 0.7:
        return "neutral"
    elif pcr > 0.5:
        return "elevated_greed"
    else:
        return "extreme_greed"


def is_pcr_favorable_for_puts(
    pcr: float,
    threshold: float = 0.7,
) -> bool:
    """Check if PCR suggests it's favorable to sell puts.

    Low PCR (bullish sentiment) with potential contrarian reversal
    makes selling puts attractive.

    Args:
        pcr: Put/Call ratio value.
        threshold: PCR below this is considered favorable.

    Returns:
        True if PCR is below threshold.
    """
    if pcr is None:
        return False
    return pcr < threshold


def calc_pcr_percentile(
    current_pcr: float,
    historical_pcr: list[float],
) -> float | None:
    """Calculate PCR percentile rank in historical context.

    Args:
        current_pcr: Current PCR value.
        historical_pcr: List of historical PCR values.

    Returns:
        Percentile (0-100) indicating where current PCR ranks historically.
    """
    if current_pcr is None or historical_pcr is None or len(historical_pcr) == 0:
        return None

    count_lower = sum(1 for p in historical_pcr if p < current_pcr)
    return count_lower / len(historical_pcr) * 100
