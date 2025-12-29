"""Portfolio-level calculations for risk and return analysis.

This module provides calculations at the portfolio level:
- Greeks aggregation (delta dollars, gamma dollars, etc.)
- Risk metrics (VaR, beta, concentration)
- Return analysis (Sharpe, Sortino, drawdown, etc.)
- Composite scores (PREI, SAS)
- Unified metrics entry point (calc_portfolio_metrics)
"""

from src.engine.portfolio.composite import calc_portfolio_prei, calc_portfolio_sas
from src.engine.portfolio.greeks_agg import (
    calc_beta_weighted_delta,
    calc_delta_dollars,
    calc_portfolio_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_vega,
)
from src.engine.portfolio.returns import (
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
)
from src.engine.portfolio.metrics import calc_portfolio_metrics
from src.engine.models.portfolio import PortfolioMetrics
from src.engine.portfolio.risk_metrics import (
    calc_concentration_risk,
    calc_portfolio_beta,
    calc_portfolio_tgr,
    calc_portfolio_var,
)

__all__ = [
    # Models
    "PortfolioMetrics",
    # Unified entry point
    "calc_portfolio_metrics",
    # Greeks aggregation
    "calc_beta_weighted_delta",
    "calc_delta_dollars",
    "calc_portfolio_delta",
    "calc_portfolio_gamma",
    "calc_portfolio_theta",
    "calc_portfolio_vega",
    # Risk metrics
    "calc_portfolio_tgr",
    "calc_portfolio_var",
    "calc_portfolio_beta",
    "calc_concentration_risk",
    # Return analysis
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
    # Composite
    "calc_portfolio_sas",
    "calc_portfolio_prei",
]
