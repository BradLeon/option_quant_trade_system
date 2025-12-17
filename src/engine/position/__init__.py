"""Position-level calculations for individual contracts/stocks.

This module provides calculations at the single position level:
- Greeks extraction from option quotes
- Volatility calculations (HV, IV, IV Rank)
- Technical indicators (RSI, Support/Resistance)
- Fundamental analysis
- Single-trade risk/return metrics
- Strategy Attractiveness Score (SAS)

Note: For strategy metrics (expected return, Sharpe ratio, etc.),
use Strategy classes directly from src.engine.strategy.
"""

from src.engine.position.greeks import (
    get_delta,
    get_gamma,
    get_greeks,
    get_rho,
    get_theta,
    get_vega,
)
from src.engine.position.option_metrics import calc_sas
from src.engine.position.risk_return import (
    calc_prei,
    calc_risk_reward_ratio,
    calc_roc_from_dte,
    calc_tgr,
)

__all__ = [
    # Greeks
    "get_greeks",
    "get_delta",
    "get_gamma",
    "get_theta",
    "get_vega",
    "get_rho",
    # Option metrics
    "calc_sas",
    # Risk/Return
    "calc_prei",
    "calc_roc_from_dte",
    "calc_risk_reward_ratio",
    "calc_tgr",
]
