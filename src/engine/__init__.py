"""Calculation Engine Layer.

This module provides quantitative indicators and calculations for options trading.
It processes raw market data from the data layer and outputs signals and metrics
for use by the business layer.

Architecture:
- position/: Position-level calculations (single contract/stock)
    - greeks: Option Greeks extraction
    - volatility: HV, IV, IV Rank calculations
    - technical: Technical indicators (RSI, Support/Resistance)
    - fundamental: Fundamental analysis metrics
    - risk_return: Single-trade risk/return metrics
    - option_metrics: Option strategy metrics

- portfolio/: Portfolio-level calculations (list[Position])
    - greeks_agg: Greeks aggregation (delta dollars, gamma dollars)
    - risk_metrics: Portfolio risk (VaR, beta, concentration)
    - returns: Return analysis (Sharpe, Sortino, drawdown)
    - composite: Composite scores (PREI, SAS)

- account/: Account-level calculations (capital/margin/sentiment)
    - margin: Margin utilization
    - position_sizing: Kelly criterion
    - capital: ROC calculations
    - sentiment: Market sentiment (VIX, Trend, PCR)

- bs/: Black-Scholes model calculations
- strategy/: Option strategy definitions
"""

# Base types (from models)
from src.engine.models.enums import RatingSignal, TrendSignal, VixZone
from src.engine.models.position import Position
from src.engine.models.result import FundamentalScore, SupportResistance, TrendResult

# ===== Position Level =====
# Greeks
from src.engine.position import (
    get_delta,
    get_gamma,
    get_greeks,
    get_rho,
    get_theta,
    get_vega,
)

# Volatility
from src.engine.position.volatility import (
    calc_hv,
    calc_hv_from_returns,
    calc_iv_hv_ratio,
    calc_iv_percentile,
    calc_iv_rank,
    calc_realized_volatility,
    get_iv,
    interpret_iv_rank,
    is_iv_cheap,
    is_iv_elevated,
)

# Technical
from src.engine.position.technical import (
    calc_resistance_level,
    calc_rsi,
    calc_rsi_series,
    calc_support_level,
    find_pivot_points,
    get_rsi_zone,
    interpret_rsi,
)

# Fundamental
from src.engine.position.fundamental import (
    evaluate_fundamentals,
    get_analyst_rating,
    get_pe,
    get_profit_margin,
    get_revenue_growth,
    is_fundamentally_strong,
)

# Position Risk/Return & Option Metrics
from src.engine.position import (
    calc_prei,
    calc_risk_reward_ratio,
    calc_roc_from_dte,
    calc_sas,
    calc_tgr,
)

# ===== Portfolio Level =====
from src.engine.portfolio import (
    # Greeks aggregation
    calc_beta_weighted_delta,
    calc_delta_dollars,
    calc_portfolio_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_vega,
    # Risk metrics
    calc_concentration_risk,
    calc_portfolio_beta,
    calc_portfolio_tgr,
    calc_portfolio_var,
    # Return analysis
    calc_annualized_return,
    calc_average_loss,
    calc_average_win,
    calc_calmar_ratio,
    calc_cvar,
    calc_drawdown_series,
    calc_expected_return,
    calc_expected_std,
    calc_max_drawdown,
    calc_profit_factor,
    calc_sharpe_ratio,
    calc_sortino_ratio,
    calc_total_return,
    calc_var,
    calc_win_rate,
    # Composite scores
    calc_portfolio_prei,
    calc_portfolio_sas,
)

# ===== Account Level =====
from src.engine.account import (
    # Margin
    calc_margin_utilization,
    # Position sizing
    calc_fractional_kelly,
    calc_half_kelly,
    calc_kelly,
    calc_kelly_from_trades,
    interpret_kelly,
    # Capital
    calc_roc,
    # Sentiment - VIX
    calc_vix_percentile,
    get_vix_regime,
    get_vix_zone,
    interpret_vix,
    is_vix_favorable_for_selling,
    # Sentiment - Trend
    calc_ema,
    calc_sma,
    calc_spy_trend,
    calc_trend_detailed,
    calc_trend_strength,
    is_above_moving_average,
    # Sentiment - PCR
    calc_pcr,
    calc_pcr_percentile,
    get_pcr_zone,
    interpret_pcr,
    is_pcr_favorable_for_puts,
)

# ===== B-S Model =====
from src.engine.bs import (
    calc_bs_call_price,
    calc_bs_delta,
    calc_bs_gamma,
    calc_bs_greeks,
    calc_bs_put_price,
    calc_bs_rho,
    calc_bs_theta,
    calc_bs_vega,
    calc_call_exercise_prob,
    calc_call_itm_prob,
    calc_d1,
    calc_d2,
    calc_d3,
    calc_n,
    calc_put_exercise_prob,
    calc_put_itm_prob,
)

# ===== Strategy Definitions =====
from src.engine.strategy import (
    CoveredCallStrategy,
    OptionLeg,
    OptionStrategy,
    OptionType,
    PositionSide,
    ShortPutStrategy,
    ShortStrangleStrategy,
    StrategyMetrics,
    StrategyParams,
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
    # Position Level - Greeks
    "get_greeks",
    "get_delta",
    "get_gamma",
    "get_theta",
    "get_vega",
    "get_rho",
    # Position Level - Volatility
    "calc_hv",
    "calc_hv_from_returns",
    "calc_realized_volatility",
    "get_iv",
    "calc_iv_hv_ratio",
    "is_iv_elevated",
    "is_iv_cheap",
    "calc_iv_rank",
    "calc_iv_percentile",
    "interpret_iv_rank",
    # Position Level - Technical
    "calc_rsi",
    "interpret_rsi",
    "get_rsi_zone",
    "calc_rsi_series",
    "calc_support_level",
    "calc_resistance_level",
    "find_pivot_points",
    # Position Level - Fundamental
    "get_pe",
    "get_revenue_growth",
    "get_profit_margin",
    "get_analyst_rating",
    "evaluate_fundamentals",
    "is_fundamentally_strong",
    # Position Level - Risk/Return & Option Metrics
    "calc_sas",
    "calc_prei",
    "calc_risk_reward_ratio",
    "calc_roc_from_dte",
    "calc_tgr",
    # Portfolio Level - Greeks Aggregation
    "calc_beta_weighted_delta",
    "calc_delta_dollars",
    "calc_portfolio_delta",
    "calc_portfolio_gamma",
    "calc_portfolio_theta",
    "calc_portfolio_vega",
    # Portfolio Level - Risk Metrics
    "calc_portfolio_tgr",
    "calc_portfolio_var",
    "calc_portfolio_beta",
    "calc_concentration_risk",
    # Portfolio Level - Return Analysis
    "calc_annualized_return",
    "calc_total_return",
    "calc_win_rate",
    "calc_expected_return",
    "calc_expected_std",
    "calc_average_win",
    "calc_average_loss",
    "calc_profit_factor",
    "calc_sharpe_ratio",
    "calc_sortino_ratio",
    "calc_max_drawdown",
    "calc_calmar_ratio",
    "calc_drawdown_series",
    "calc_var",
    "calc_cvar",
    # Portfolio Level - Composite
    "calc_portfolio_sas",
    "calc_portfolio_prei",
    # Account Level - Margin
    "calc_margin_utilization",
    # Account Level - Position Sizing
    "calc_kelly",
    "calc_kelly_from_trades",
    "calc_half_kelly",
    "calc_fractional_kelly",
    "interpret_kelly",
    # Account Level - Capital
    "calc_roc",
    # Account Level - Sentiment (VIX)
    "interpret_vix",
    "get_vix_zone",
    "is_vix_favorable_for_selling",
    "calc_vix_percentile",
    "get_vix_regime",
    # Account Level - Sentiment (Trend)
    "calc_sma",
    "calc_ema",
    "calc_spy_trend",
    "calc_trend_strength",
    "calc_trend_detailed",
    "is_above_moving_average",
    # Account Level - Sentiment (PCR)
    "calc_pcr",
    "interpret_pcr",
    "get_pcr_zone",
    "is_pcr_favorable_for_puts",
    "calc_pcr_percentile",
    # B-S Model
    "calc_d1",
    "calc_d2",
    "calc_d3",
    "calc_n",
    "calc_bs_call_price",
    "calc_bs_put_price",
    "calc_bs_delta",
    "calc_bs_gamma",
    "calc_bs_theta",
    "calc_bs_vega",
    "calc_bs_rho",
    "calc_bs_greeks",
    "calc_put_exercise_prob",
    "calc_call_exercise_prob",
    "calc_put_itm_prob",
    "calc_call_itm_prob",
    # Option Strategies
    "OptionType",
    "PositionSide",
    "OptionLeg",
    "StrategyParams",
    "StrategyMetrics",
    "OptionStrategy",
    "ShortPutStrategy",
    "CoveredCallStrategy",
    "ShortStrangleStrategy",
]
