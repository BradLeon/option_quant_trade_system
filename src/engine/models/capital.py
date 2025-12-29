"""Account-level data models.

This module defines data structures for account/capital-level calculations,
following the principle that all calculation logic belongs in engine layer
while monitoring layer only performs threshold checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CapitalMetrics:
    """Capital-level metrics calculated by engine layer.

    This model is a pure data container with no calculation logic.
    All values are computed by calc_capital_metrics() in metrics.py.

    Attributes:
        total_equity: Total account equity (cash + positions).
        cash_balance: Available cash balance.
        maintenance_margin: Current maintenance margin requirement.
        margin_usage: Ratio of maintenance_margin to total_equity.
            Values > 0.7 indicate high leverage risk.
        realized_pnl: Realized profit/loss for the period.
        unrealized_pnl: Unrealized profit/loss on open positions.
        sharpe_ratio: Risk-adjusted return measure.
            Values > 1.0 indicate good risk-adjusted performance.
        total_position_value: Total market value of all positions.
        kelly_capacity: Maximum position value based on Kelly criterion.
        kelly_usage: Ratio of total_position_value to kelly_capacity.
            Values > 1.0 indicate over-leveraged relative to Kelly.
        peak_equity: Historical peak equity for drawdown calculation.
        current_drawdown: Current drawdown from peak as a ratio (0-1).
        timestamp: When the metrics were calculated.
    """

    # Account equity
    total_equity: float | None = None
    cash_balance: float | None = None

    # Margin
    maintenance_margin: float | None = None
    margin_usage: float | None = None

    # P&L
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    sharpe_ratio: float | None = None

    # Kelly usage
    total_position_value: float | None = None
    kelly_capacity: float | None = None
    kelly_usage: float | None = None

    # Drawdown
    peak_equity: float | None = None
    current_drawdown: float | None = None

    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)
