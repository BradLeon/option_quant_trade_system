"""Greeks extraction from option quotes.

Position-level module for extracting Greeks from individual option quotes.
When Greeks are not available from the data source, they are calculated
using Black-Scholes formulas as a fallback.
"""

from src.data.models.option import Greeks, OptionQuote, OptionType
from src.engine.bs.greeks import (
    calc_bs_delta,
    calc_bs_gamma,
    calc_bs_greeks,
    calc_bs_rho,
    calc_bs_theta,
    calc_bs_vega,
)
from src.engine.models import BSParams


def get_greeks(
    option_quote: OptionQuote,
    spot_price: float | None = None,
    risk_free_rate: float = 0.05,
) -> Greeks | None:
    """Extract or calculate Greeks from an option quote.

    If the option quote has Greeks data, returns it directly.
    Otherwise, calculates Greeks using Black-Scholes model if sufficient
    data is available (spot_price and IV).

    Args:
        option_quote: The option quote containing Greeks data.
        spot_price: Current underlying price. Required for fallback calculation.
        risk_free_rate: Annual risk-free rate for B-S calculation. Default 5%.

    Returns:
        Greeks object if available or calculable, None otherwise.

    Example:
        >>> quote = OptionQuote(contract=..., greeks=Greeks(delta=0.5, gamma=0.02))
        >>> greeks = get_greeks(quote)
        >>> greeks.delta
        0.5

        >>> # If greeks missing but IV available, will calculate using B-S
        >>> quote = OptionQuote(contract=..., iv=0.30, greeks=Greeks())
        >>> greeks = get_greeks(quote, spot_price=150.0)
        >>> greeks.delta  # Calculated via B-S
        0.55
    """
    if option_quote is None:
        return None

    # If Greeks data exists and has at least delta, return it
    if option_quote.greeks is not None and option_quote.greeks.delta is not None:
        return option_quote.greeks

    # Try to calculate Greeks using B-S as fallback
    calculated = _calc_greeks_fallback(option_quote, spot_price, risk_free_rate)
    if calculated is not None:
        return calculated

    # Return original greeks (may be empty/partial)
    return option_quote.greeks


def get_delta(
    option_quote: OptionQuote,
    spot_price: float | None = None,
    risk_free_rate: float = 0.05,
) -> float | None:
    """Extract or calculate delta from an option quote.

    Args:
        option_quote: The option quote.
        spot_price: Current underlying price for fallback calculation.
        risk_free_rate: Annual risk-free rate for B-S calculation.

    Returns:
        Delta value if available or calculable, None otherwise.
    """
    if option_quote is None:
        return None

    # Try to get from existing Greeks
    if option_quote.greeks is not None and option_quote.greeks.delta is not None:
        return option_quote.greeks.delta

    # Fallback: calculate using B-S
    return _calc_single_greek_fallback(option_quote, spot_price, risk_free_rate, "delta")


def get_gamma(
    option_quote: OptionQuote,
    spot_price: float | None = None,
    risk_free_rate: float = 0.05,
) -> float | None:
    """Extract or calculate gamma from an option quote.

    Args:
        option_quote: The option quote.
        spot_price: Current underlying price for fallback calculation.
        risk_free_rate: Annual risk-free rate for B-S calculation.

    Returns:
        Gamma value if available or calculable, None otherwise.
    """
    if option_quote is None:
        return None

    # Try to get from existing Greeks
    if option_quote.greeks is not None and option_quote.greeks.gamma is not None:
        return option_quote.greeks.gamma

    # Fallback: calculate using B-S
    return _calc_single_greek_fallback(option_quote, spot_price, risk_free_rate, "gamma")


def get_theta(
    option_quote: OptionQuote,
    spot_price: float | None = None,
    risk_free_rate: float = 0.05,
) -> float | None:
    """Extract or calculate theta from an option quote.

    Args:
        option_quote: The option quote.
        spot_price: Current underlying price for fallback calculation.
        risk_free_rate: Annual risk-free rate for B-S calculation.

    Returns:
        Theta value if available or calculable, None otherwise.
    """
    if option_quote is None:
        return None

    # Try to get from existing Greeks
    if option_quote.greeks is not None and option_quote.greeks.theta is not None:
        return option_quote.greeks.theta

    # Fallback: calculate using B-S
    return _calc_single_greek_fallback(option_quote, spot_price, risk_free_rate, "theta")


def get_vega(
    option_quote: OptionQuote,
    spot_price: float | None = None,
    risk_free_rate: float = 0.05,
) -> float | None:
    """Extract or calculate vega from an option quote.

    Args:
        option_quote: The option quote.
        spot_price: Current underlying price for fallback calculation.
        risk_free_rate: Annual risk-free rate for B-S calculation.

    Returns:
        Vega value if available or calculable, None otherwise.
    """
    if option_quote is None:
        return None

    # Try to get from existing Greeks
    if option_quote.greeks is not None and option_quote.greeks.vega is not None:
        return option_quote.greeks.vega

    # Fallback: calculate using B-S
    return _calc_single_greek_fallback(option_quote, spot_price, risk_free_rate, "vega")


def get_rho(
    option_quote: OptionQuote,
    spot_price: float | None = None,
    risk_free_rate: float = 0.05,
) -> float | None:
    """Extract or calculate rho from an option quote.

    Args:
        option_quote: The option quote.
        spot_price: Current underlying price for fallback calculation.
        risk_free_rate: Annual risk-free rate for B-S calculation.

    Returns:
        Rho value if available or calculable, None otherwise.
    """
    if option_quote is None:
        return None

    # Try to get from existing Greeks
    if option_quote.greeks is not None and option_quote.greeks.rho is not None:
        return option_quote.greeks.rho

    # Fallback: calculate using B-S
    return _calc_single_greek_fallback(option_quote, spot_price, risk_free_rate, "rho")


def _calc_greeks_fallback(
    option_quote: OptionQuote,
    spot_price: float | None,
    risk_free_rate: float,
) -> Greeks | None:
    """Calculate all Greeks using B-S model as fallback.

    Requires:
    - spot_price (passed in)
    - strike_price (from contract)
    - time_to_expiry (from contract.days_to_expiry)
    - volatility (from option_quote.iv)

    Args:
        option_quote: The option quote with contract and IV data.
        spot_price: Current underlying price.
        risk_free_rate: Annual risk-free rate.

    Returns:
        Greeks object with calculated values, or None if insufficient data.
    """
    # Validate required data
    if spot_price is None or spot_price <= 0:
        return None

    if option_quote.iv is None or option_quote.iv <= 0:
        return None

    contract = option_quote.contract
    if contract is None:
        return None

    strike_price = contract.strike_price
    if strike_price is None or strike_price <= 0:
        return None

    dte = contract.days_to_expiry
    if dte is None or dte <= 0:
        return None

    # Convert DTE to years
    time_to_expiry = dte / 365.0

    # Create BSParams for calculation
    params = BSParams(
        spot_price=spot_price,
        strike_price=strike_price,
        risk_free_rate=risk_free_rate,
        volatility=option_quote.iv,
        time_to_expiry=time_to_expiry,
        is_call=contract.option_type == OptionType.CALL,
    )

    # Calculate all Greeks using B-S
    # Note: calc_bs_greeks already returns correct units:
    # - theta: per day
    # - vega: per 1% IV change
    # - rho: per 1% rate change
    greeks_dict = calc_bs_greeks(params)

    return Greeks(
        delta=greeks_dict["delta"],
        gamma=greeks_dict["gamma"],
        theta=greeks_dict["theta"],
        vega=greeks_dict["vega"],
        rho=greeks_dict["rho"],
    )


def _calc_single_greek_fallback(
    option_quote: OptionQuote,
    spot_price: float | None,
    risk_free_rate: float,
    greek_name: str,
) -> float | None:
    """Calculate a single Greek using B-S model as fallback.

    Args:
        option_quote: The option quote with contract and IV data.
        spot_price: Current underlying price.
        risk_free_rate: Annual risk-free rate.
        greek_name: Name of the Greek to calculate ("delta", "gamma", etc.)

    Returns:
        Calculated Greek value, or None if insufficient data.
    """
    # Validate required data
    if spot_price is None or spot_price <= 0:
        return None

    if option_quote.iv is None or option_quote.iv <= 0:
        return None

    contract = option_quote.contract
    if contract is None:
        return None

    strike_price = contract.strike_price
    if strike_price is None or strike_price <= 0:
        return None

    dte = contract.days_to_expiry
    if dte is None or dte <= 0:
        return None

    # Convert DTE to years
    time_to_expiry = dte / 365.0

    # Determine option type
    is_call = contract.option_type == OptionType.CALL

    # Create BSParams for calculation
    params = BSParams(
        spot_price=spot_price,
        strike_price=strike_price,
        risk_free_rate=risk_free_rate,
        volatility=option_quote.iv,
        time_to_expiry=time_to_expiry,
        is_call=is_call,
    )

    # Calculate the specific Greek
    # Note: All calc_bs_* functions now return correct units:
    # - theta: per day
    # - vega: per 1% IV change
    # - rho: per 1% rate change
    if greek_name == "delta":
        return calc_bs_delta(params)
    elif greek_name == "gamma":
        return calc_bs_gamma(params)
    elif greek_name == "theta":
        return calc_bs_theta(params)
    elif greek_name == "vega":
        return calc_bs_vega(params)
    elif greek_name == "rho":
        return calc_bs_rho(params)

    return None
