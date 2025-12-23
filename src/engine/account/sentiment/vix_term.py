"""VIX term structure analysis.

Account-level module for VIX term structure (contango/backwardation) analysis.
Uses VIX3M/VIX ratio to assess market expectations.

For HK market, uses 2800.HK option IV at different expiries as proxy.
"""

from src.engine.models.enums import TermStructure, TrendSignal
from src.engine.models.sentiment import VixTermStructure


# Term structure thresholds
CONTANGO_THRESHOLD = 1.05  # VIX3M/VIX > 1.05 = contango
BACKWARDATION_THRESHOLD = 0.95  # VIX3M/VIX < 0.95 = backwardation


def calc_vix_term_ratio(vix: float | None, vix_3m: float | None) -> float | None:
    """Calculate VIX3M/VIX ratio.

    The ratio indicates term structure:
    - > 1: Contango (normal), VIX3M > VIX
    - < 1: Backwardation (inverted), VIX3M < VIX
    - = 1: Flat

    Args:
        vix: Current VIX (or short-term volatility) value.
        vix_3m: 3-month VIX (or longer-term volatility) value.

    Returns:
        Ratio value, or None if inputs invalid.

    Example:
        >>> calc_vix_term_ratio(15.0, 17.0)
        1.133...
        >>> calc_vix_term_ratio(25.0, 22.0)
        0.88
    """
    if vix is None or vix_3m is None:
        return None
    if vix <= 0:
        return None
    return vix_3m / vix


def get_term_structure(ratio: float | None) -> TermStructure:
    """Classify term structure from ratio.

    Args:
        ratio: VIX3M/VIX ratio.

    Returns:
        TermStructure classification.
        - CONTANGO: ratio > 1.05 (normal, complacent market)
        - BACKWARDATION: ratio < 0.95 (inverted, fear/panic)
        - FLAT: ratio between 0.95 and 1.05

    Example:
        >>> get_term_structure(1.10)
        <TermStructure.CONTANGO: 'contango'>
        >>> get_term_structure(0.90)
        <TermStructure.BACKWARDATION: 'backwardation'>
    """
    if ratio is None:
        return TermStructure.FLAT

    if ratio > CONTANGO_THRESHOLD:
        return TermStructure.CONTANGO
    elif ratio < BACKWARDATION_THRESHOLD:
        return TermStructure.BACKWARDATION
    else:
        return TermStructure.FLAT


def interpret_term_structure(structure: TermStructure) -> TrendSignal:
    """Interpret term structure as trading signal.

    Contrarian interpretation:
    - CONTANGO (complacent): Near-term calm, can indicate complacency.
      May be a warning sign - BEARISH signal.
    - BACKWARDATION (fear): Near-term volatility spike, extreme fear.
      Often a contrarian buying opportunity - BULLISH signal.
    - FLAT: Neutral market conditions - NEUTRAL signal.

    Args:
        structure: Term structure classification.

    Returns:
        Trading signal based on contrarian interpretation.

    Example:
        >>> interpret_term_structure(TermStructure.BACKWARDATION)
        <TrendSignal.BULLISH: 'bullish'>
        >>> interpret_term_structure(TermStructure.CONTANGO)
        <TrendSignal.BEARISH: 'bearish'>
    """
    if structure == TermStructure.BACKWARDATION:
        return TrendSignal.BULLISH  # Fear = buying opportunity
    elif structure == TermStructure.CONTANGO:
        return TrendSignal.BEARISH  # Complacency = warning
    else:
        return TrendSignal.NEUTRAL


def analyze_term_structure(
    vix: float | None,
    vix_3m: float | None,
) -> VixTermStructure | None:
    """Complete term structure analysis.

    Combines ratio calculation, structure classification, and signal
    interpretation into a single result.

    Args:
        vix: Current VIX value (or VHSI proxy for HK).
        vix_3m: 3-month VIX value (or longer-dated IV for HK).

    Returns:
        VixTermStructure result with all analysis components.
        Returns None if either input is missing (cannot calculate term structure).

    Example:
        >>> result = analyze_term_structure(vix=20.0, vix_3m=18.0)
        >>> result.structure
        <TermStructure.BACKWARDATION: 'backwardation'>
        >>> result.signal
        <TrendSignal.BULLISH: 'bullish'>
        >>> analyze_term_structure(vix=20.0, vix_3m=None)  # Missing data
        None
    """
    # Cannot calculate term structure without both values
    if vix is None or vix_3m is None:
        return None

    ratio = calc_vix_term_ratio(vix, vix_3m)
    structure = get_term_structure(ratio)
    signal = interpret_term_structure(structure)

    return VixTermStructure(
        vix=vix,
        vix_3m=vix_3m,
        ratio=ratio,
        structure=structure,
        signal=signal,
    )


def is_term_structure_favorable(structure: TermStructure) -> bool:
    """Check if term structure is favorable for option selling.

    Backwardation (high near-term volatility) provides better premiums
    for option sellers, especially for short-dated options.

    Args:
        structure: Term structure classification.

    Returns:
        True if conditions favor option selling.
    """
    # Backwardation or flat are favorable for selling
    # Contango is less favorable (lower near-term vol)
    return structure != TermStructure.CONTANGO
