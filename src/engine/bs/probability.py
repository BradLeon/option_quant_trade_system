"""Option exercise probability calculations based on Black-Scholes model.

Provides functions to calculate the probability of option exercise
and ITM (in-the-money) probabilities at expiration.
"""

from src.engine.bs.core import calc_d1, calc_d2, calc_n


def calc_put_exercise_prob(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate put option exercise probability.

    For a put option, exercise probability = N(-d2)
    This is the risk-neutral probability that S_T < K at expiry.

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Exercise probability (0-1), or None if inputs are invalid.
    """
    d1 = calc_d1(spot_price, strike_price, risk_free_rate, volatility, time_to_expiry)
    if d1 is None:
        return None

    d2 = calc_d2(d1, volatility, time_to_expiry)
    if d2 is None:
        return None

    return calc_n(-d2)


def calc_call_exercise_prob(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate call option exercise probability.

    For a call option, exercise probability = N(d2)
    This is the risk-neutral probability that S_T > K at expiry.

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Exercise probability (0-1), or None if inputs are invalid.
    """
    d1 = calc_d1(spot_price, strike_price, risk_free_rate, volatility, time_to_expiry)
    if d1 is None:
        return None

    d2 = calc_d2(d1, volatility, time_to_expiry)
    if d2 is None:
        return None

    return calc_n(d2)


def calc_put_itm_prob(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate probability of put being ITM at expiry.

    Same as exercise probability for European options.

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        ITM probability (0-1), or None if inputs are invalid.
    """
    return calc_put_exercise_prob(
        spot_price, strike_price, risk_free_rate, volatility, time_to_expiry
    )


def calc_call_itm_prob(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate probability of call being ITM at expiry.

    Same as exercise probability for European options.

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        ITM probability (0-1), or None if inputs are invalid.
    """
    return calc_call_exercise_prob(
        spot_price, strike_price, risk_free_rate, volatility, time_to_expiry
    )


def calc_put_win_prob(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate win probability for short put (seller).

    Win probability = 1 - exercise probability = 1 - N(-d2) = N(d2)

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Win probability for put seller (0-1), or None if inputs are invalid.
    """
    exercise_prob = calc_put_exercise_prob(
        spot_price, strike_price, risk_free_rate, volatility, time_to_expiry
    )
    if exercise_prob is None:
        return None

    return 1.0 - exercise_prob


def calc_call_win_prob(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate win probability for short call (seller).

    Win probability = 1 - exercise probability = 1 - N(d2) = N(-d2)

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Win probability for call seller (0-1), or None if inputs are invalid.
    """
    exercise_prob = calc_call_exercise_prob(
        spot_price, strike_price, risk_free_rate, volatility, time_to_expiry
    )
    if exercise_prob is None:
        return None

    return 1.0 - exercise_prob
