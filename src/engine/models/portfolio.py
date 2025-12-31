"""Portfolio-level data models.

This module defines data structures for portfolio-level calculations,
following the principle that all calculation logic belongs in engine layer
while monitoring layer only performs threshold checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PortfolioMetrics:
    """Portfolio-level metrics calculated by engine layer.

    This model is a pure data container with no calculation logic.
    All values are computed by calc_portfolio_metrics() in metrics.py.

    Absolute value fields (for display and other uses):
        beta_weighted_delta: Portfolio delta normalized to SPY-equivalent shares.
            A BWD of 100 means the portfolio moves like 100 shares of SPY.
        total_delta: Sum of all position deltas (share-equivalent terms).
        total_gamma: Sum of all position gammas in gamma_dollars.
        total_theta: Sum of all position thetas (daily time decay in dollars).
        total_vega: Sum of all position vegas.

    NLV-normalized percentage fields (for threshold checks):
        beta_weighted_delta_pct: BWD / NLV, directional leverage relative to account.
        delta_pct: total_delta / NLV.
        gamma_pct: total_gamma / NLV, convexity risk per 1% underlying move.
        theta_pct: total_theta / NLV, daily time value accrual rate.
        vega_pct: total_vega / NLV, volatility risk per 1% IV change.

    Risk metrics:
        portfolio_tgr: Theta/Gamma ratio - measures daily theta income
            per unit of gamma risk. Higher is better for theta strategies.
        concentration_hhi: Herfindahl-Hirschman Index for concentration risk.
            Range 0-1, where 1 = single position, 0.25 = 4 equal positions.
        vega_weighted_iv_hv: Vega-weighted IV/HV ratio. Measures option pricing
            quality. > 1.0 means selling overpriced options, < 0.8 is "underselling".

    Other:
        timestamp: When the metrics were calculated.
    """

    # Beta weighted delta (normalized to SPY)
    beta_weighted_delta: float | None = None

    # Portfolio Greeks
    total_delta: float = 0.0
    total_gamma: float = 0.0
    total_theta: float = 0.0
    total_vega: float = 0.0

    # Theta/Gamma ratio
    portfolio_tgr: float | None = None

    # Concentration risk (Herfindahl-Hirschman Index)
    concentration_hhi: float | None = None

    # NLV-normalized percentage fields (Greeks / NLV)
    # These are more useful for threshold checks as they're account-size independent
    beta_weighted_delta_pct: float | None = None  # BWD / NLV, directional leverage
    delta_pct: float | None = None  # total_delta / NLV
    gamma_pct: float | None = None  # total_gamma / NLV, convexity risk per 1% move
    theta_pct: float | None = None  # total_theta / NLV, daily time value accrual rate
    vega_pct: float | None = None  # total_vega / NLV, volatility risk per 1% IV change

    # Portfolio quality metric
    vega_weighted_iv_hv: float | None = None  # sum(Vega_i * IV_i/HV_i) / sum(Vega_i)

    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)
