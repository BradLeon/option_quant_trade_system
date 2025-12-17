"""Black-Scholes model core calculations.

Provides the fundamental mathematical functions for option pricing
based on the Black-Scholes model.

All functions use BSParams for input parameters.

Reference: B-S期权定价模型.md
"""

from __future__ import annotations

import math

from scipy.stats import norm

from src.engine.models import BSParams


def calc_d1(params: BSParams) -> float | None:
    """Calculate d1 in Black-Scholes formula.

    d1 = [ln(S/K) + (r + σ²/2)×T] / (σ×√T)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        d1 value, or None if inputs are invalid.
    """
    if (
        params.spot_price <= 0
        or params.strike_price <= 0
        or params.volatility <= 0
        or params.time_to_expiry <= 0
    ):
        return None

    sqrt_t = math.sqrt(params.time_to_expiry)
    sigma_sqrt_t = params.volatility * sqrt_t

    d1 = (
        math.log(params.spot_price / params.strike_price)
        + (params.risk_free_rate + 0.5 * params.volatility**2) * params.time_to_expiry
    ) / sigma_sqrt_t

    return d1


def calc_d2(params: BSParams, d1: float | None = None) -> float | None:
    """Calculate d2 from BSParams (or from provided d1).

    d2 = d1 - σ×√T

    Args:
        params: Black-Scholes calculation parameters.
        d1: Pre-calculated d1 value (optional, will calculate if not provided).

    Returns:
        d2 value, or None if inputs are invalid.
    """
    if params.volatility <= 0 or params.time_to_expiry <= 0:
        return None

    if d1 is None:
        d1 = calc_d1(params)
    if d1 is None:
        return None

    return d1 - params.volatility * math.sqrt(params.time_to_expiry)


def calc_d3(params: BSParams, d2: float | None = None) -> float | None:
    """Calculate d3 from BSParams (or from provided d2).

    d3 = d2 + 2×σ×√T = d1 + σ×√T

    Args:
        params: Black-Scholes calculation parameters.
        d2: Pre-calculated d2 value (optional, will calculate if not provided).

    Returns:
        d3 value, or None if inputs are invalid.
    """
    if params.volatility <= 0 or params.time_to_expiry <= 0:
        return None

    if d2 is None:
        d2 = calc_d2(params)
    if d2 is None:
        return None

    return d2 + 2 * params.volatility * math.sqrt(params.time_to_expiry)


def calc_n(d: float) -> float:
    """Calculate cumulative standard normal distribution N(d).

    Args:
        d: Input value

    Returns:
        Cumulative probability N(d)
    """
    return float(norm.cdf(d))


def calc_bs_call_price(params: BSParams) -> float | None:
    """Calculate theoretical call option price using Black-Scholes formula.

    C = S×N(d1) - K×e^(-r×T)×N(d2)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Theoretical call price, or None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    n_d1 = calc_n(d1)
    n_d2 = calc_n(d2)

    discount_factor = math.exp(-params.risk_free_rate * params.time_to_expiry)
    call_price = params.spot_price * n_d1 - params.strike_price * discount_factor * n_d2

    return call_price


def calc_bs_put_price(params: BSParams) -> float | None:
    """Calculate theoretical put option price using Black-Scholes formula.

    P = K×e^(-r×T)×N(-d2) - S×N(-d1)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Theoretical put price, or None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    n_minus_d1 = calc_n(-d1)
    n_minus_d2 = calc_n(-d2)

    discount_factor = math.exp(-params.risk_free_rate * params.time_to_expiry)
    put_price = params.strike_price * discount_factor * n_minus_d2 - params.spot_price * n_minus_d1

    return put_price


def calc_bs_price(params: BSParams) -> float | None:
    """Calculate option price using BSParams.

    Automatically selects call or put formula based on params.is_call.

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Theoretical option price, or None if inputs are invalid.

    Example:
        >>> params = BSParams(
        ...     spot_price=100, strike_price=100, risk_free_rate=0.05,
        ...     volatility=0.2, time_to_expiry=1.0, is_call=True
        ... )
        >>> price = calc_bs_price(params)
    """
    if params.is_call:
        return calc_bs_call_price(params)
    else:
        return calc_bs_put_price(params)


def calc_bs_params(params: BSParams) -> dict | None:
    """Calculate all B-S parameters at once.

    Convenience function to get d1, d2, d3, and related N values.

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Dictionary with d1, d2, d3, n_d1, n_d2, n_minus_d1, n_minus_d2, n_minus_d3
        or None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    d3 = calc_d3(params, d2)

    if d2 is None or d3 is None:
        return None

    return {
        "d1": d1,
        "d2": d2,
        "d3": d3,
        "n_d1": calc_n(d1),
        "n_d2": calc_n(d2),
        "n_d3": calc_n(d3),
        "n_minus_d1": calc_n(-d1),
        "n_minus_d2": calc_n(-d2),
        "n_minus_d3": calc_n(-d3),
    }
