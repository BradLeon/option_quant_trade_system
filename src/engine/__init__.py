"""Calculation Engine Layer.

This module provides quantitative indicators and calculations for options trading.
It processes raw market data from the data layer and outputs signals and metrics
for use by the business layer.

Modules:
- greeks: Option Greeks extraction
- volatility: HV, IV, IV Rank calculations
- returns: Return and risk metrics (Sharpe, Max DD, Kelly)
- sentiment: Market sentiment indicators (VIX, PCR, Trend)
- fundamental: Fundamental analysis metrics
- technical: Technical indicators (RSI, Support/Resistance)
- portfolio: Portfolio-level risk metrics
"""

# Base types
from src.engine.base import (
    FundamentalScore,
    Position,
    RatingSignal,
    SupportResistance,
    TrendResult,
    TrendSignal,
    VixZone,
)

# Greeks
from src.engine.greeks import get_greeks

# Volatility
from src.engine.volatility import (
    calc_hv,
    calc_iv_hv_ratio,
    calc_iv_percentile,
    calc_iv_rank,
    get_iv,
)

# Returns and Risk
from src.engine.returns import (
    calc_annualized_return,
    calc_calmar_ratio,
    calc_expected_return,
    calc_expected_std,
    calc_kelly,
    calc_kelly_from_trades,
    calc_max_drawdown,
    calc_sharpe_ratio,
    calc_win_rate,
)

# Sentiment
from src.engine.sentiment import (
    calc_pcr,
    calc_spy_trend,
    calc_trend_strength,
    get_vix_zone,
    interpret_pcr,
    interpret_vix,
)

# Fundamental
from src.engine.fundamental import (
    evaluate_fundamentals,
    get_analyst_rating,
    get_pe,
    get_profit_margin,
    get_revenue_growth,
)

# Technical
from src.engine.technical import (
    calc_rsi,
    calc_support_distance,
    calc_support_level,
    find_support_resistance,
    interpret_rsi,
)

# Portfolio
from src.engine.portfolio import (
    calc_beta_weighted_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_var,
    calc_portfolio_vega,
    calc_prei,
    calc_roc,
    calc_sas,
    calc_tgr,
)

__all__ = [
    # Base types
    "TrendSignal",
    "RatingSignal",
    "VixZone",
    "Position",
    "FundamentalScore",
    "TrendResult",
    "SupportResistance",
    # Greeks
    "get_greeks",
    # Volatility
    "calc_hv",
    "get_iv",
    "calc_iv_hv_ratio",
    "calc_iv_rank",
    "calc_iv_percentile",
    # Returns
    "calc_annualized_return",
    "calc_win_rate",
    "calc_expected_return",
    "calc_expected_std",
    "calc_sharpe_ratio",
    "calc_max_drawdown",
    "calc_calmar_ratio",
    "calc_kelly",
    "calc_kelly_from_trades",
    # Sentiment
    "interpret_vix",
    "get_vix_zone",
    "calc_spy_trend",
    "calc_trend_strength",
    "calc_pcr",
    "interpret_pcr",
    # Fundamental
    "get_pe",
    "get_revenue_growth",
    "get_profit_margin",
    "get_analyst_rating",
    "evaluate_fundamentals",
    # Technical
    "calc_rsi",
    "interpret_rsi",
    "calc_support_level",
    "calc_support_distance",
    "find_support_resistance",
    # Portfolio
    "calc_beta_weighted_delta",
    "calc_portfolio_theta",
    "calc_portfolio_vega",
    "calc_portfolio_gamma",
    "calc_tgr",
    "calc_roc",
    "calc_portfolio_var",
    "calc_sas",
    "calc_prei",
]
