"""Black-Scholes Greeks calculations.

Provides analytical formulas for computing option Greeks based on the
Black-Scholes model.

Greeks formulas:
- Delta (Δ): ∂V/∂S
  - Call: N(d1)
  - Put: N(d1) - 1 = -N(-d1)

- Gamma (Γ): ∂²V/∂S² (same for call and put)
  - n(d1) / (S × σ × √T)

- Theta (Θ): ∂V/∂t
  - Call: -S×n(d1)×σ/(2√T) - r×K×e^(-rT)×N(d2)
  - Put: -S×n(d1)×σ/(2√T) + r×K×e^(-rT)×N(-d2)

- Vega (ν): ∂V/∂σ (same for call and put)
  - S × n(d1) × √T

- Rho (ρ): ∂V/∂r
  - Call: K × T × e^(-rT) × N(d2)
  - Put: -K × T × e^(-rT) × N(-d2)

Where:
- n(d) is the standard normal PDF
- N(d) is the standard normal CDF

All functions use BSParams for input parameters.
"""

from __future__ import annotations

import math

from scipy.stats import norm

from src.engine.bs.core import calc_d1, calc_d2, calc_n
from src.engine.models import BSParams


def _calc_n_pdf(d: float) -> float:
    """Calculate standard normal probability density function n(d).

    n(d) = (1/√(2π)) × e^(-d²/2)

    Args:
        d: Input value.

    Returns:
        PDF value at d.
    """
    return float(norm.pdf(d))


def calc_bs_delta(params: BSParams) -> float | None:
    """Calculate option delta using Black-Scholes formula.

    Delta measures the rate of change of option price with respect to
    changes in the underlying asset's price.

    Formula:
        Call Delta = N(d1)
        Put Delta = N(d1) - 1 = -N(-d1)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Delta value. Call delta in [0, 1], put delta in [-1, 0].
        Returns None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    if params.is_call:
        return calc_n(d1)
    else:
        return calc_n(d1) - 1


def calc_bs_gamma(params: BSParams) -> float | None:
    """Calculate option gamma using Black-Scholes formula.

    Gamma measures the rate of change of delta with respect to changes
    in the underlying asset's price. Same for both calls and puts.

    Formula:
        Gamma = n(d1) / (S × σ × √T)

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Gamma value (always positive).
        Returns None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    if params.spot_price <= 0 or params.volatility <= 0 or params.time_to_expiry <= 0:
        return None

    sqrt_t = math.sqrt(params.time_to_expiry)
    n_d1_pdf = _calc_n_pdf(d1)

    return n_d1_pdf / (params.spot_price * params.volatility * sqrt_t)


def calc_bs_theta(params: BSParams) -> float | None:
    """Calculate option theta using Black-Scholes formula.

    Theta measures the rate of change of option price with respect to time.
    Returns theta per day (daily time decay), consistent with broker APIs.

    Formula:
        Call Theta = [-S×n(d1)×σ/(2√T) - r×K×e^(-rT)×N(d2)] / 365
        Put Theta = [-S×n(d1)×σ/(2√T) + r×K×e^(-rT)×N(-d2)] / 365

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Theta value per day (typically negative for long positions).
        Returns None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    sqrt_t = math.sqrt(params.time_to_expiry)
    n_d1_pdf = _calc_n_pdf(d1)
    discount = math.exp(-params.risk_free_rate * params.time_to_expiry)

    # First term is common to both call and put
    term1 = -(params.spot_price * n_d1_pdf * params.volatility) / (2 * sqrt_t)

    if params.is_call:
        term2 = -params.risk_free_rate * params.strike_price * discount * calc_n(d2)
    else:
        term2 = params.risk_free_rate * params.strike_price * discount * calc_n(-d2)

    annual_theta = term1 + term2
    return annual_theta / 365  # Convert to daily theta


def calc_bs_vega(params: BSParams) -> float | None:
    """Calculate option vega using Black-Scholes formula.

    Vega measures the sensitivity of option price to changes in volatility.
    Same for both calls and puts. Returns vega per 1% change in volatility,
    consistent with broker APIs.

    Formula:
        Vega = S × n(d1) × √T / 100

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Vega value per 1% IV change (always positive).
        Returns None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    sqrt_t = math.sqrt(params.time_to_expiry)
    n_d1_pdf = _calc_n_pdf(d1)

    return (params.spot_price * n_d1_pdf * sqrt_t) / 100  # Per 1% IV change


def calc_bs_rho(params: BSParams) -> float | None:
    """Calculate option rho using Black-Scholes formula.

    Rho measures the sensitivity of option price to changes in the
    risk-free interest rate. Returns rho per 1% change in rate,
    consistent with broker APIs.

    Formula:
        Call Rho = K × T × e^(-rT) × N(d2) / 100
        Put Rho = -K × T × e^(-rT) × N(-d2) / 100

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Rho value per 1% rate change.
        Returns None if inputs are invalid.
    """
    d1 = calc_d1(params)
    if d1 is None:
        return None

    d2 = calc_d2(params, d1)
    if d2 is None:
        return None

    discount = math.exp(-params.risk_free_rate * params.time_to_expiry)

    if params.is_call:
        rho = params.strike_price * params.time_to_expiry * discount * calc_n(d2)
    else:
        rho = -params.strike_price * params.time_to_expiry * discount * calc_n(-d2)

    return rho / 100  # Per 1% rate change


def calc_bs_greeks(params: BSParams) -> dict[str, float | None]:
    """Calculate all Greeks at once using Black-Scholes formulas.

    Reuses individual Greek calculation functions to ensure consistent
    units across all callers:
    - Delta: standard (0 to 1 for calls, -1 to 0 for puts)
    - Gamma: per $1 move in underlying
    - Theta: per day (daily time decay)
    - Vega: per 1% change in IV
    - Rho: per 1% change in interest rate

    Args:
        params: Black-Scholes calculation parameters.

    Returns:
        Dictionary with delta, gamma, theta, vega, rho.
        Individual values may be None if calculation fails.

    Example:
        >>> params = BSParams(
        ...     spot_price=100, strike_price=100, risk_free_rate=0.05,
        ...     volatility=0.2, time_to_expiry=1.0, is_call=True
        ... )
        >>> greeks = calc_bs_greeks(params)
        >>> print(greeks["delta"])
    """
    return {
        "delta": calc_bs_delta(params),
        "gamma": calc_bs_gamma(params),
        "theta": calc_bs_theta(params),  # Daily theta
        "vega": calc_bs_vega(params),    # Per 1% IV change
        "rho": calc_bs_rho(params),      # Per 1% rate change
    }
