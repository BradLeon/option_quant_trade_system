"""VIX term structure analysis.

Account-level module for VIX term structure (VIX vs VIX3M) analysis.
Term structure provides insight into market stress levels:
- Contango (VIX < VIX3M): Normal market, short-term calm
- Backwardation (VIX > VIX3M): Stressed market, near-term fear
"""

from dataclasses import dataclass

from src.engine.models.enums import TermStructure


@dataclass
class TermStructureResult:
    """Result of term structure calculation.

    Attributes:
        vix: Current VIX value.
        vix3m: Current VIX3M value.
        ratio: VIX / VIX3M ratio.
        state: Term structure state (contango/flat/backwardation).
        is_favorable: Whether conditions favor option selling.
    """

    vix: float
    vix3m: float
    ratio: float
    state: TermStructure
    is_favorable: bool


def calc_term_structure(
    vix: float | None,
    vix3m: float | None,
    flat_threshold: float = 0.02,
) -> TermStructureResult | None:
    """Calculate VIX term structure metrics.

    The term structure ratio (VIX/VIX3M) indicates market stress:
    - ratio < 1: Contango (normal) - short-term vol below long-term
    - ratio > 1: Backwardation (stressed) - short-term vol above long-term

    Args:
        vix: Current VIX index value.
        vix3m: Current VIX3M index value (3-month VIX).
        flat_threshold: Threshold for considering ratio as flat (default 2%).

    Returns:
        TermStructureResult with ratio, state, and favorability.
        Returns None if inputs are invalid.

    Example:
        >>> result = calc_term_structure(18.5, 20.0)
        >>> result.ratio
        0.925
        >>> result.state
        <TermStructure.CONTANGO: 'contango'>
    """
    if vix is None or vix3m is None:
        return None
    if vix3m <= 0:
        return None

    ratio = vix / vix3m
    state = get_term_structure_state(ratio, flat_threshold)
    is_favorable = is_term_structure_favorable(ratio)

    return TermStructureResult(
        vix=vix,
        vix3m=vix3m,
        ratio=ratio,
        state=state,
        is_favorable=is_favorable,
    )


def get_term_structure_state(
    ratio: float | None,
    flat_threshold: float = 0.02,
) -> TermStructure:
    """Categorize term structure ratio into states.

    Args:
        ratio: VIX / VIX3M ratio.
        flat_threshold: Threshold around 1.0 for flat classification.

    Returns:
        TermStructure enum.

    Example:
        >>> get_term_structure_state(0.9)
        <TermStructure.CONTANGO: 'contango'>
        >>> get_term_structure_state(1.15)
        <TermStructure.BACKWARDATION: 'backwardation'>
    """
    if ratio is None:
        return TermStructure.FLAT

    if ratio < (1.0 - flat_threshold):
        return TermStructure.CONTANGO
    elif ratio > (1.0 + flat_threshold):
        return TermStructure.BACKWARDATION
    else:
        return TermStructure.FLAT


def is_term_structure_favorable(
    ratio: float | None,
    max_ratio: float = 1.0,
) -> bool:
    """Check if term structure is favorable for option selling.

    Contango (ratio < 1) is favorable because:
    - Short-term vol is lower than long-term (normal market)
    - Premium sellers benefit from time decay in calm conditions
    - Backwardation often precedes further volatility spikes

    Args:
        ratio: VIX / VIX3M ratio.
        max_ratio: Maximum ratio for favorable conditions (default 1.0).

    Returns:
        True if term structure favors option selling.

    Example:
        >>> is_term_structure_favorable(0.92)
        True
        >>> is_term_structure_favorable(1.15)
        False
    """
    if ratio is None:
        return False
    return ratio <= max_ratio


def get_term_structure_regime(ratio: float | None) -> str:
    """Get a descriptive regime name for current term structure.

    Args:
        ratio: VIX / VIX3M ratio.

    Returns:
        String description of term structure regime.

    Example:
        >>> get_term_structure_regime(0.85)
        'normal_contango'
        >>> get_term_structure_regime(1.20)
        'stressed_backwardation'
    """
    if ratio is None:
        return "unknown"

    if ratio < 0.90:
        return "strong_contango"
    elif ratio < 0.98:
        return "normal_contango"
    elif ratio < 1.02:
        return "flat"
    elif ratio < 1.10:
        return "mild_backwardation"
    else:
        return "stressed_backwardation"


def interpret_term_structure(ratio: float | None) -> str:
    """Provide interpretation of term structure for trading decisions.

    Args:
        ratio: VIX / VIX3M ratio.

    Returns:
        Human-readable interpretation string.
    """
    if ratio is None:
        return "Unable to calculate term structure"

    regime = get_term_structure_regime(ratio)

    interpretations = {
        "strong_contango": "Strong contango - calm market, favorable for premium selling",
        "normal_contango": "Normal contango - market conditions are stable",
        "flat": "Flat term structure - transitional period, monitor closely",
        "mild_backwardation": "Mild backwardation - elevated near-term stress",
        "stressed_backwardation": "Stressed backwardation - high near-term fear, caution advised",
    }

    return interpretations.get(regime, f"Term structure ratio: {ratio:.2f}")
