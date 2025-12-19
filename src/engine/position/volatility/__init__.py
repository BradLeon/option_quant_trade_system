"""Volatility calculation module.

Position-level volatility calculations for individual securities.
"""

from src.engine.position.volatility.historical import (
    calc_hv,
    calc_hv_from_returns,
    calc_realized_volatility,
)
from src.engine.position.volatility.implied import (
    calc_iv_hv_ratio,
    get_iv,
    is_iv_cheap,
    is_iv_elevated,
)
from src.engine.position.volatility.iv_rank import (
    calc_iv_percentile,
    calc_iv_rank,
    interpret_iv_rank,
    is_iv_rank_favorable_for_selling,
)
from src.engine.position.volatility.metrics import (
    evaluate_volatility,
    get_hv,
    get_iv_hv_ratio,
    get_iv_percentile,
    get_iv_rank,
    get_pcr,
    interpret_pcr,
    is_favorable_for_selling,
)
from src.engine.position.volatility.metrics import get_iv as get_iv_from_volatility

__all__ = [
    # Historical volatility (calculation functions)
    "calc_hv",
    "calc_hv_from_returns",
    "calc_realized_volatility",
    # Implied volatility (from OptionQuote)
    "get_iv",
    "calc_iv_hv_ratio",
    "is_iv_elevated",
    "is_iv_cheap",
    # IV Rank (calculation functions)
    "calc_iv_rank",
    "calc_iv_percentile",
    "interpret_iv_rank",
    "is_iv_rank_favorable_for_selling",
    # Metrics (from StockVolatility data model)
    "get_iv_from_volatility",
    "get_hv",
    "get_iv_rank",
    "get_iv_percentile",
    "get_pcr",
    "get_iv_hv_ratio",
    "interpret_pcr",
    "is_favorable_for_selling",
    "evaluate_volatility",
]
