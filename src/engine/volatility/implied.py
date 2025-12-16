"""Implied volatility operations."""

from src.data.models.option import OptionQuote


def get_iv(option_quote: OptionQuote) -> float | None:
    """Get implied volatility from an option quote.

    Args:
        option_quote: The option quote containing IV data.

    Returns:
        Implied volatility as a decimal (e.g., 0.25 for 25%).
        Returns None if IV is not available.

    Example:
        >>> quote = OptionQuote(contract=..., iv=0.35)
        >>> get_iv(quote)
        0.35
    """
    if option_quote is None:
        return None
    return option_quote.iv


def calc_iv_hv_ratio(iv: float, hv: float) -> float | None:
    """Calculate the IV/HV ratio.

    This ratio indicates whether options are relatively expensive (IV > HV)
    or cheap (IV < HV) compared to historical volatility.

    Args:
        iv: Implied volatility (decimal form).
        hv: Historical volatility (decimal form).

    Returns:
        IV/HV ratio. > 1 means IV is higher than HV (options are "expensive").
        Returns None if HV is zero or either value is None.

    Example:
        >>> calc_iv_hv_ratio(0.30, 0.20)
        1.5
        >>> calc_iv_hv_ratio(0.20, 0.30)
        0.6666666666666666
    """
    if iv is None or hv is None:
        return None
    if hv == 0:
        return None
    return iv / hv


def is_iv_elevated(iv: float, hv: float, threshold: float = 1.2) -> bool:
    """Check if IV is elevated relative to HV.

    Args:
        iv: Implied volatility.
        hv: Historical volatility.
        threshold: Ratio threshold above which IV is considered elevated.

    Returns:
        True if IV/HV ratio exceeds threshold.
    """
    ratio = calc_iv_hv_ratio(iv, hv)
    if ratio is None:
        return False
    return ratio > threshold


def is_iv_cheap(iv: float, hv: float, threshold: float = 0.8) -> bool:
    """Check if IV is cheap relative to HV.

    Args:
        iv: Implied volatility.
        hv: Historical volatility.
        threshold: Ratio threshold below which IV is considered cheap.

    Returns:
        True if IV/HV ratio is below threshold.
    """
    ratio = calc_iv_hv_ratio(iv, hv)
    if ratio is None:
        return False
    return ratio < threshold
