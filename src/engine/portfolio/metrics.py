"""Portfolio metrics calculation - unified entry point.

This module provides a single entry point for calculating all portfolio-level
metrics, following the principle that all calculation logic belongs in engine
layer while monitoring layer only performs threshold checks.

Example:
    >>> from src.engine.portfolio.metrics import calc_portfolio_metrics
    >>> metrics = calc_portfolio_metrics(positions)
    >>> print(f"BWD: {metrics.beta_weighted_delta}")
"""

from __future__ import annotations

from datetime import datetime

from src.engine.models.position import Position
from src.engine.portfolio.greeks_agg import (
    calc_beta_weighted_delta,
    calc_portfolio_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_vega,
)
from src.engine.models.portfolio import PortfolioMetrics
from src.engine.portfolio.risk_metrics import (
    calc_concentration_risk,
    calc_portfolio_tgr,
)


def calc_portfolio_metrics(positions: list[Position]) -> PortfolioMetrics:
    """Calculate all portfolio-level metrics.

    This is the unified entry point for portfolio metrics calculation.
    It aggregates results from specialized calculation functions in the
    engine layer.

    Args:
        positions: List of Position objects with Greeks and market data.

    Returns:
        PortfolioMetrics with all calculated values.

    Example:
        >>> positions = [Position(...), Position(...)]
        >>> metrics = calc_portfolio_metrics(positions)
        >>> if metrics.portfolio_tgr and metrics.portfolio_tgr < 0.5:
        ...     print("TGR is low, consider adjusting positions")
    """
    if not positions:
        return PortfolioMetrics(timestamp=datetime.now())

    return PortfolioMetrics(
        # Greeks aggregation
        total_delta=calc_portfolio_delta(positions),
        total_gamma=calc_portfolio_gamma(positions),
        total_theta=calc_portfolio_theta(positions),
        total_vega=calc_portfolio_vega(positions),
        # Beta weighted delta
        beta_weighted_delta=calc_beta_weighted_delta(positions),
        # Risk metrics
        portfolio_tgr=calc_portfolio_tgr(positions),
        concentration_hhi=calc_concentration_risk(positions),
        # Timestamp
        timestamp=datetime.now(),
    )
