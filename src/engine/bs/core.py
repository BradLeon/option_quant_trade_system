"""Black-Scholes model core calculations.

Provides the fundamental mathematical functions for option pricing
based on the Black-Scholes model.

Reference: B-S期权定价模型.md
"""

import math

from scipy.stats import norm


def calc_d1(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate d1 in Black-Scholes formula.

    d1 = [ln(S/K) + (r + σ²/2)×T] / (σ×√T)

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        d1 value, or None if inputs are invalid.
    """
    if spot_price <= 0 or strike_price <= 0 or volatility <= 0 or time_to_expiry <= 0:
        return None

    sqrt_t = math.sqrt(time_to_expiry)
    sigma_sqrt_t = volatility * sqrt_t

    d1 = (
        math.log(spot_price / strike_price)
        + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry
    ) / sigma_sqrt_t

    return d1


def calc_d2(d1: float, volatility: float, time_to_expiry: float) -> float | None:
    """Calculate d2 from d1.

    d2 = d1 - σ×√T

    Args:
        d1: Previously calculated d1 value
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        d2 value, or None if inputs are invalid.
    """
    if d1 is None or volatility <= 0 or time_to_expiry <= 0:
        return None

    return d1 - volatility * math.sqrt(time_to_expiry)


def calc_d3(d2: float, volatility: float, time_to_expiry: float) -> float | None:
    """Calculate d3 from d2 (used in variance calculation).

    d3 = d2 + 2×σ×√T = d1 + σ×√T

    Args:
        d2: Previously calculated d2 value
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        d3 value, or None if inputs are invalid.
    """
    if d2 is None or volatility <= 0 or time_to_expiry <= 0:
        return None

    return d2 + 2 * volatility * math.sqrt(time_to_expiry)


def calc_n(d: float) -> float:
    """Calculate cumulative standard normal distribution N(d).

    Args:
        d: Input value

    Returns:
        Cumulative probability N(d)
    """
    return float(norm.cdf(d))


def calc_bs_call_price(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate theoretical call option price using Black-Scholes formula.

    C = S×N(d1) - K×e^(-r×T)×N(d2)

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Theoretical call price, or None if inputs are invalid.
    """
    d1 = calc_d1(spot_price, strike_price, risk_free_rate, volatility, time_to_expiry)
    if d1 is None:
        return None

    d2 = calc_d2(d1, volatility, time_to_expiry)
    if d2 is None:
        return None

    n_d1 = calc_n(d1)
    n_d2 = calc_n(d2)

    discount_factor = math.exp(-risk_free_rate * time_to_expiry)
    call_price = spot_price * n_d1 - strike_price * discount_factor * n_d2

    return call_price


def calc_bs_put_price(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> float | None:
    """Calculate theoretical put option price using Black-Scholes formula.

    P = K×e^(-r×T)×N(-d2) - S×N(-d1)

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Theoretical put price, or None if inputs are invalid.
    """
    d1 = calc_d1(spot_price, strike_price, risk_free_rate, volatility, time_to_expiry)
    if d1 is None:
        return None

    d2 = calc_d2(d1, volatility, time_to_expiry)
    if d2 is None:
        return None

    n_minus_d1 = calc_n(-d1)
    n_minus_d2 = calc_n(-d2)

    discount_factor = math.exp(-risk_free_rate * time_to_expiry)
    put_price = strike_price * discount_factor * n_minus_d2 - spot_price * n_minus_d1

    return put_price


def calc_bs_params(
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    volatility: float,
    time_to_expiry: float,
) -> dict | None:
    """Calculate all B-S parameters at once.

    Convenience function to get d1, d2, d3, and related N values.

    Args:
        spot_price: Current stock price (S)
        strike_price: Option strike price (K)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Implied volatility (σ)
        time_to_expiry: Time to expiration in years (T)

    Returns:
        Dictionary with d1, d2, d3, n_d1, n_d2, n_minus_d1, n_minus_d2, n_minus_d3
        or None if inputs are invalid.
    """
    d1 = calc_d1(spot_price, strike_price, risk_free_rate, volatility, time_to_expiry)
    if d1 is None:
        return None

    d2 = calc_d2(d1, volatility, time_to_expiry)
    d3 = calc_d3(d2, volatility, time_to_expiry)

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
