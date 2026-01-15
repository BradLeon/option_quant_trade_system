"""Option contract metrics for screening.

Contract-level module for calculating option-specific metrics.
"""


def calc_otm_percent(
    spot: float,
    strike: float,
    option_type: str,
) -> float | None:
    """Calculate out-of-the-money percentage as decimal.

    For puts: how far below spot is the strike (positive = OTM)
    For calls: how far above spot is the strike (positive = OTM)

    OTM% = |spot - strike| / spot (when option is OTM)

    Args:
        spot: Current underlying price.
        strike: Option strike price.
        option_type: "put" or "call".

    Returns:
        OTM percentage as decimal (e.g., 0.05 for 5% OTM).
        Returns 0 if option is ITM.
        Returns None if inputs are invalid.

    Example:
        >>> calc_otm_percent(100, 95, "put")
        0.05  # Put is 5% OTM
        >>> calc_otm_percent(100, 105, "call")
        0.05  # Call is 5% OTM
        >>> calc_otm_percent(100, 105, "put")
        0.0  # Put is ITM
    """
    if spot is None or strike is None or spot <= 0:
        return None

    option_type = option_type.lower()
    if option_type not in ("put", "call"):
        return None

    if option_type == "put":
        # Put is OTM when strike < spot
        if strike >= spot:
            return 0.0  # ITM or ATM
        return (spot - strike) / spot
    else:
        # Call is OTM when strike > spot
        if strike <= spot:
            return 0.0  # ITM or ATM
        return (strike - spot) / spot


def calc_moneyness(
    spot: float,
    strike: float,
) -> float | None:
    """Calculate moneyness ratio.

    Moneyness = (spot - strike) / strike

    Interpretation:
    - Positive: In-the-money for puts
    - Negative: Out-of-the-money for puts
    - Zero: At-the-money

    Args:
        spot: Current underlying price.
        strike: Option strike price.

    Returns:
        Moneyness ratio (decimal).
        Returns None if strike is zero or None.

    Example:
        >>> calc_moneyness(105, 100)
        0.05  # 5% above strike
        >>> calc_moneyness(95, 100)
        -0.05  # 5% below strike
    """
    if spot is None or strike is None or strike == 0:
        return None

    return (spot - strike) / strike


def calc_theta_premium_ratio(
    theta: float | None,
    premium: float | None,
) -> float | None:
    """Calculate theta to premium ratio.

    This ratio shows what percentage of premium decays per day.
    Higher ratio = faster decay, good for option sellers.

    Formula: ratio = |theta| / premium

    Rule of thumb for short options:
    - > 0.05: Excellent theta decay
    - 0.03-0.05: Good
    - < 0.03: Slow decay (far from expiry)

    Args:
        theta: Daily theta (negative value for long options).
        premium: Option premium (mid-price or last price).

    Returns:
        Theta/premium ratio as decimal.
        Returns None if inputs are invalid.

    Example:
        >>> calc_theta_premium_ratio(-0.05, 1.00)
        0.05  # 5% of premium decays daily
    """
    if theta is None or premium is None:
        return None

    if premium <= 0:
        return None

    # Theta is typically negative, take absolute value
    return abs(theta) / premium


def calc_theta_gamma_ratio(
    theta: float | None,
    gamma: float | None,
    spot_price: float | None = None,
    iv: float | None = None,
) -> float | None:
    """Calculate standardized Theta/Gamma Ratio (TGR).

    Standardized TGR normalizes for stock price and volatility:
        TGR = |Theta| / (|Gamma| × S² × σ_daily) × 100

    Where:
        - S = spot_price (underlying price)
        - σ_daily = IV / √252 (daily volatility)
        - Gamma × S² = "Gamma Dollar" (normalizes gamma across different stock prices)

    For option sellers:
    - Higher TGR is better (more decay per gamma risk)
    - Target: TGR > 1.0 for good theta strategies

    Args:
        theta: Daily theta (negative for long options).
        gamma: Option gamma.
        spot_price: Underlying stock price (optional, for standardization).
        iv: Implied volatility as decimal (optional, for standardization).

    Returns:
        Standardized TGR ratio.
        Returns None if inputs are invalid or gamma is zero.
        Falls back to simple TGR if spot_price or iv unavailable.

    Example:
        >>> calc_theta_gamma_ratio(-0.03, 0.05, spot_price=150, iv=0.30)
        1.5  # Good theta strategy
    """
    import math

    if theta is None or gamma is None:
        return None

    if gamma <= 0:
        return None

    # Fall back to simple TGR if spot_price or iv unavailable
    if spot_price is None or iv is None or spot_price <= 0 or iv <= 0:
        return abs(theta) / gamma

    # Standardized TGR
    sigma_daily = iv / math.sqrt(252)
    gamma_dollar_vol = abs(gamma) * (spot_price**2) * sigma_daily

    if gamma_dollar_vol == 0:
        return None

    return (abs(theta) / gamma_dollar_vol) * 100


def calc_annual_return(
    premium: float,
    margin: float,
    dte: int,
) -> float | None:
    """Calculate annualized return for an option selling strategy.

    Assumes the premium is earned over the DTE period and annualizes it.

    Formula: annual_return = (premium / margin) * (365 / dte)

    Args:
        premium: Option premium received.
        margin: Required margin/capital.
        dte: Days to expiration.

    Returns:
        Annualized return as decimal (e.g., 0.12 for 12%).
        Returns None if inputs are invalid.

    Example:
        >>> calc_annual_return(1.00, 20.00, 30)
        0.608  # ~61% annualized return
    """
    if premium is None or margin is None or dte is None:
        return None

    if margin <= 0 or dte <= 0:
        return None

    period_return = premium / margin
    annual_return = period_return * (365 / dte)

    return annual_return


def calc_break_even(
    strike: float,
    premium: float,
    option_type: str,
) -> float | None:
    """Calculate break-even price for option selling.

    For put sellers: break_even = strike - premium
    For call sellers: break_even = strike + premium

    Args:
        strike: Option strike price.
        premium: Premium received.
        option_type: "put" or "call".

    Returns:
        Break-even price.
        Returns None if inputs are invalid.

    Example:
        >>> calc_break_even(100, 2, "put")
        98.0  # Break even at $98 for short put
    """
    if strike is None or premium is None:
        return None

    option_type = option_type.lower()

    if option_type == "put":
        return strike - premium
    elif option_type == "call":
        return strike + premium
    else:
        return None


def calc_max_loss(
    strike: float,
    premium: float,
    option_type: str,
    underlying_price: float | None = None,
) -> float | None:
    """Calculate maximum loss for option selling.

    For put sellers: max_loss = strike - premium (stock goes to 0)
    For call sellers: max_loss = unlimited (but can estimate based on 2x move)

    Args:
        strike: Option strike price.
        premium: Premium received.
        option_type: "put" or "call".
        underlying_price: Current underlying price (for call max loss estimate).

    Returns:
        Maximum loss estimate.
        Returns None if inputs are invalid.

    Example:
        >>> calc_max_loss(100, 2, "put")
        98.0  # Max loss is $98 per share
    """
    if strike is None or premium is None:
        return None

    option_type = option_type.lower()

    if option_type == "put":
        # Max loss: stock goes to $0
        return strike - premium
    elif option_type == "call":
        # For calls, estimate max loss as 2x underlying price move
        if underlying_price is not None:
            return underlying_price - premium  # Rough estimate
        return None
    else:
        return None


def calc_expected_move(
    spot: float,
    iv: float,
    dte: int,
) -> float | None:
    """Calculate expected move based on implied volatility.

    Uses the formula: expected_move = spot * iv * sqrt(dte/365)

    This represents approximately a 1 standard deviation move.

    Args:
        spot: Current underlying price.
        iv: Implied volatility (decimal, e.g., 0.30 for 30%).
        dte: Days to expiration.

    Returns:
        Expected move in price terms.
        Returns None if inputs are invalid.

    Example:
        >>> calc_expected_move(100, 0.30, 30)
        8.59  # Expected ~$8.59 move over 30 days
    """
    if spot is None or iv is None or dte is None:
        return None

    if spot <= 0 or iv <= 0 or dte <= 0:
        return None

    import math
    return spot * iv * math.sqrt(dte / 365)
