"""Greeks extraction from option quotes."""

from src.data.models.option import Greeks, OptionQuote


def get_greeks(option_quote: OptionQuote) -> Greeks | None:
    """Extract Greeks from an option quote.

    Args:
        option_quote: The option quote containing Greeks data.

    Returns:
        Greeks object if available, None if option_quote has no Greeks.

    Example:
        >>> quote = OptionQuote(contract=..., greeks=Greeks(delta=0.5, gamma=0.02))
        >>> greeks = get_greeks(quote)
        >>> greeks.delta
        0.5
    """
    if option_quote is None:
        return None

    return option_quote.greeks


def get_delta(option_quote: OptionQuote) -> float | None:
    """Extract delta from an option quote.

    Args:
        option_quote: The option quote.

    Returns:
        Delta value if available, None otherwise.
    """
    if option_quote is None or option_quote.greeks is None:
        return None
    return option_quote.greeks.delta


def get_gamma(option_quote: OptionQuote) -> float | None:
    """Extract gamma from an option quote.

    Args:
        option_quote: The option quote.

    Returns:
        Gamma value if available, None otherwise.
    """
    if option_quote is None or option_quote.greeks is None:
        return None
    return option_quote.greeks.gamma


def get_theta(option_quote: OptionQuote) -> float | None:
    """Extract theta from an option quote.

    Args:
        option_quote: The option quote.

    Returns:
        Theta value if available, None otherwise.
    """
    if option_quote is None or option_quote.greeks is None:
        return None
    return option_quote.greeks.theta


def get_vega(option_quote: OptionQuote) -> float | None:
    """Extract vega from an option quote.

    Args:
        option_quote: The option quote.

    Returns:
        Vega value if available, None otherwise.
    """
    if option_quote is None or option_quote.greeks is None:
        return None
    return option_quote.greeks.vega


def get_rho(option_quote: OptionQuote) -> float | None:
    """Extract rho from an option quote.

    Args:
        option_quote: The option quote.

    Returns:
        Rho value if available, None otherwise.
    """
    if option_quote is None or option_quote.greeks is None:
        return None
    return option_quote.greeks.rho
