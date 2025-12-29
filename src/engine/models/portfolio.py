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

    Attributes:
        beta_weighted_delta: Portfolio delta normalized to SPY-equivalent shares.
            A BWD of 100 means the portfolio moves like 100 shares of SPY.
        total_delta: Sum of all position deltas (share-equivalent terms).
        total_gamma: Sum of all position gammas in gamma_dollars.
        total_theta: Sum of all position thetas (daily time decay in dollars).
        total_vega: Sum of all position vegas.
        portfolio_tgr: Theta/Gamma ratio - measures daily theta income
            per unit of gamma risk. Higher is better for theta strategies.
        concentration_hhi: Herfindahl-Hirschman Index for concentration risk.
            Range 0-1, where 1 = single position, 0.25 = 4 equal positions.
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

    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)
