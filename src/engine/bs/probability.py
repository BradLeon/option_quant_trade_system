"""Option exercise probability calculations based on Black-Scholes model.

Provides functions to calculate the probability of option exercise
and ITM (in-the-money) probabilities at expiration.

All functions use BSParams for input parameters.
"""

from src.engine.bs.core import calc_d1, calc_d2, calc_n
from src.engine.models import BSParams


def calc_exercise_prob(params: BSParams) -> float | None:
    """Calculate option exercise probability using BSParams.

    For call option: exercise probability = N(d2)
    For put option: exercise probability = N(-d2)

    This is the risk-neutral probability that the option will be exercised.

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Exercise probability (0-1), or None if inputs are invalid.

    Example:
        >>> params = BSParams(
        ...     spot_price=100, strike_price=100, risk_free_rate=0.05,
        ...     volatility=0.2, time_to_expiry=1.0, is_call=True
        ... )
        >>> prob = calc_exercise_prob(params)
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    if params.is_call:
        return calc_n(d2)  # P(S_T > K)
    else:
        return calc_n(-d2)  # P(S_T < K)


def calc_itm_prob(params: BSParams) -> float | None:
    """Calculate probability of option being ITM at expiry.

    Same as exercise probability for European options.

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        ITM probability (0-1), or None if inputs are invalid.
    """
    return calc_exercise_prob(params)


def calc_win_prob(params: BSParams) -> float | None:
    """Calculate win probability for option seller (short position).

    Win probability = 1 - exercise probability

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Win probability for option seller (0-1), or None if inputs are invalid.
    """
    exercise_prob = calc_exercise_prob(params)
    if exercise_prob is None:
        return None

    return 1.0 - exercise_prob


def calc_put_exercise_prob(params: BSParams) -> float | None:
    """Calculate put option exercise probability.

    For a put option, exercise probability = N(-d2)
    This is the risk-neutral probability that S_T < K at expiry.

    Args:
        params: Black-Scholes calculation parameters (is_call is ignored).

    Returns:
        Exercise probability (0-1), or None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    return calc_n(-d2)  # P(S_T < K)


def calc_call_exercise_prob(params: BSParams) -> float | None:
    """Calculate call option exercise probability.

    For a call option, exercise probability = N(d2)
    This is the risk-neutral probability that S_T > K at expiry.

    Args:
        params: Black-Scholes calculation parameters (is_call is ignored).

    Returns:
        Exercise probability (0-1), or None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    return calc_n(d2)  # P(S_T > K)


def calc_put_itm_prob(params: BSParams) -> float | None:
    """Calculate probability of put being ITM at expiry.

    Same as exercise probability for European options.

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        ITM probability (0-1), or None if inputs are invalid.
    """
    return calc_put_exercise_prob(params)


def calc_call_itm_prob(params: BSParams) -> float | None:
    """Calculate probability of call being ITM at expiry.

    Same as exercise probability for European options.

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        ITM probability (0-1), or None if inputs are invalid.
    """
    return calc_call_exercise_prob(params)


def calc_put_win_prob(params: BSParams) -> float | None:
    """Calculate win probability for short put (seller).

    Win probability = 1 - exercise probability = 1 - N(-d2) = N(d2)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Win probability for put seller (0-1), or None if inputs are invalid.
    """
    exercise_prob = calc_put_exercise_prob(params)
    if exercise_prob is None:
        return None

    return 1.0 - exercise_prob


def calc_call_win_prob(params: BSParams) -> float | None:
    """Calculate win probability for short call (seller).

    Win probability = 1 - exercise probability = 1 - N(d2) = N(-d2)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Win probability for call seller (0-1), or None if inputs are invalid.
    """
    exercise_prob = calc_call_exercise_prob(params)
    if exercise_prob is None:
        return None

    return 1.0 - exercise_prob
