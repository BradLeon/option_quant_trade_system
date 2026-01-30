"""Black-Scholes model calculations module.

All functions use BSParams for input parameters:

    >>> from src.engine.models import BSParams
    >>> from src.engine.bs import calc_bs_delta
    >>>
    >>> params = BSParams(
    ...     spot_price=100, strike_price=100, risk_free_rate=0.05,
    ...     volatility=0.2, time_to_expiry=1.0, is_call=True
    ... )
    >>> delta = calc_bs_delta(params)
"""

from src.engine.bs.core import (
    calc_bs_call_price,
    calc_bs_params,
    calc_bs_price,
    calc_bs_put_price,
    calc_d1,
    calc_d2,
    calc_d3,
    calc_n,
)
from src.engine.bs.greeks import (
    calc_bs_delta,
    calc_bs_gamma,
    calc_bs_greeks,
    calc_bs_rho,
    calc_bs_theta,
    calc_bs_vega,
)
from src.engine.bs.greeks_cache import (
    CachedGreeksCalculator,
    GreeksResult,
    calc_bs_greeks_cached,
    clear_greeks_cache,
    get_cached_calculator,
    get_greeks_cache_info,
)
from src.engine.bs.probability import (
    calc_call_exercise_prob,
    calc_call_itm_prob,
    calc_call_win_prob,
    calc_exercise_prob,
    calc_itm_prob,
    calc_put_exercise_prob,
    calc_put_itm_prob,
    calc_put_win_prob,
    calc_win_prob,
)

__all__ = [
    # Core calculations
    "calc_d1",
    "calc_d2",
    "calc_d3",
    "calc_n",
    "calc_bs_call_price",
    "calc_bs_put_price",
    "calc_bs_price",
    "calc_bs_params",
    # Greeks calculations
    "calc_bs_delta",
    "calc_bs_gamma",
    "calc_bs_theta",
    "calc_bs_vega",
    "calc_bs_rho",
    "calc_bs_greeks",
    # Cached Greeks calculations
    "CachedGreeksCalculator",
    "GreeksResult",
    "calc_bs_greeks_cached",
    "clear_greeks_cache",
    "get_cached_calculator",
    "get_greeks_cache_info",
    # Probability calculations
    "calc_exercise_prob",
    "calc_itm_prob",
    "calc_win_prob",
    "calc_put_exercise_prob",
    "calc_call_exercise_prob",
    "calc_put_itm_prob",
    "calc_call_itm_prob",
    "calc_put_win_prob",
    "calc_call_win_prob",
]
