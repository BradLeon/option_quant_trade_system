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

from datetime import date, datetime
from typing import TYPE_CHECKING

from src.engine.models.position import Position
from src.engine.portfolio.greeks_agg import (
    _get_spy_price,
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
    calc_vega_weighted_iv_hv,
)

if TYPE_CHECKING:
    from src.data.providers.base import DataProvider


def calc_portfolio_metrics(
    positions: list[Position],
    nlv: float | None = None,
    position_iv_hv_ratios: dict[str, float] | None = None,
    data_provider: "DataProvider | None" = None,
    as_of_date: date | None = None,
) -> PortfolioMetrics:
    """Calculate all portfolio-level metrics.

    This is the unified entry point for portfolio metrics calculation.
    It aggregates results from specialized calculation functions in the
    engine layer.

    Args:
        positions: List of Position objects with Greeks and market data.
        nlv: Net Liquidation Value (account equity) for percentage calculations.
            If provided, percentage fields (delta_pct, gamma_pct, etc.) will be
            calculated. If None, these fields remain None for backward compatibility.
        position_iv_hv_ratios: Dict mapping symbol to its IV/HV ratio.
            Used to calculate vega_weighted_iv_hv quality metric.
        data_provider: Optional data provider for backtest mode (reads from DuckDB).
        as_of_date: Query date for rolling beta lookup (backtest mode).

    Returns:
        PortfolioMetrics with all calculated values.

    Example:
        >>> positions = [Position(...), Position(...)]
        >>> metrics = calc_portfolio_metrics(positions, nlv=100000)
        >>> print(f"BWD%: {metrics.beta_weighted_delta_pct:.1%}")
    """
    if not positions:
        return PortfolioMetrics(timestamp=datetime.now())

    # Calculate absolute Greeks
    total_delta = calc_portfolio_delta(positions)
    total_gamma = calc_portfolio_gamma(positions)
    total_theta = calc_portfolio_theta(positions)
    total_vega = calc_portfolio_vega(positions)
    beta_weighted_delta = calc_beta_weighted_delta(
        positions, data_provider=data_provider, as_of_date=as_of_date
    )

    # Calculate NLV-normalized percentages (only if NLV provided and positive)
    beta_weighted_delta_pct = None
    delta_pct = None
    gamma_pct = None
    theta_pct = None
    vega_pct = None

    if nlv and nlv > 0:
        # BWD% = (BWD_shares * SPY_price) / NLV
        # This converts SPY-equivalent shares to dollar exposure, then normalizes
        if beta_weighted_delta is not None:
            spy_price = _get_spy_price(data_provider=data_provider)
            if spy_price and spy_price > 0:
                beta_weighted_delta_pct = (beta_weighted_delta * spy_price) / nlv
        # delta_pct is less meaningful (raw shares / NLV), keep for reference
        delta_pct = total_delta / nlv
        # Gamma, Theta, Vega are already in dollar terms
        gamma_pct = total_gamma / nlv
        theta_pct = total_theta / nlv
        vega_pct = total_vega / nlv

    # Calculate vega-weighted IV/HV
    vega_weighted_iv_hv = calc_vega_weighted_iv_hv(positions, position_iv_hv_ratios)

    return PortfolioMetrics(
        # Absolute Greeks
        total_delta=total_delta,
        total_gamma=total_gamma,
        total_theta=total_theta,
        total_vega=total_vega,
        beta_weighted_delta=beta_weighted_delta,
        # NLV-normalized percentages
        beta_weighted_delta_pct=beta_weighted_delta_pct,
        delta_pct=delta_pct,
        gamma_pct=gamma_pct,
        theta_pct=theta_pct,
        vega_pct=vega_pct,
        # Risk metrics
        portfolio_tgr=calc_portfolio_tgr(positions),
        concentration_hhi=calc_concentration_risk(positions),
        vega_weighted_iv_hv=vega_weighted_iv_hv,
        # Timestamp
        timestamp=datetime.now(),
    )
