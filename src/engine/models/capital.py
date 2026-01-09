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

    Core Risk Control Metrics (4 Pillars):
        1. margin_utilization: Distance from margin call (survival)
           Formula: Maint Margin / NLV
           Green: < 40%, Yellow: 40%~70%, Red: > 70%

        2. cash_ratio: Liquidity buffer (operational flexibility)
           Formula: Net Cash Balance / NLV
           Green: > 30%, Yellow: 10%~30%, Red: < 10%

        3. gross_leverage: Total exposure control (prevent "empty fat")
           Formula: (Σ|Stock Value| + Σ|Option Notional|) / NLV
           Option Notional = Strike × Multiplier × |Qty|
           Green: < 2.0x, Yellow: 2.0x~4.0x, Red: > 4.0x

        4. stress_test_loss: Tail risk (Black Swan protection)
           Formula: (Current_NLV - Stressed_NLV) / Current_NLV
           Scenario: Spot -15% & IV +40%
           Green: < 10%, Yellow: 10%~20%, Red: > 20%

    Attributes:
        total_equity: Total account equity (NLV).
        cash_balance: Net cash balance.
        maintenance_margin: Current maintenance margin requirement.
        realized_pnl: Realized profit/loss for the period.
        unrealized_pnl: Unrealized profit/loss on open positions.
        total_position_value: Total market value of all positions.
        margin_utilization: Maint Margin / NLV (survival metric).
        cash_ratio: Cash Balance / NLV (liquidity metric).
        gross_leverage: Total Notional / NLV (exposure metric).
        stress_test_loss: Simulated loss under stress scenario.
        timestamp: When the metrics were calculated.
    """

    # Account equity
    total_equity: float | None = None
    cash_balance: float | None = None

    # Margin
    maintenance_margin: float | None = None

    # P&L
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None

    # Position value (for leverage calculation)
    total_position_value: float | None = None

    # === Core Risk Control Metrics (4 Pillars) ===

    # 1. Margin Utilization: Maint Margin / NLV
    # Measures distance from margin call - survival metric
    margin_utilization: float | None = None

    # 2. Cash Ratio: Net Cash Balance / NLV
    # Measures liquidity buffer - operational flexibility
    cash_ratio: float | None = None

    # 3. Gross Leverage: Total Notional / NLV
    # Measures total exposure - prevents "empty fat"
    gross_leverage: float | None = None

    # 4. Stress Test Loss: (Current_NLV - Stressed_NLV) / Current_NLV
    # Measures tail risk under extreme scenario (Spot -15%, IV +40%)
    stress_test_loss: float | None = None

    # Timestamp
    timestamp: datetime = field(default_factory=datetime.now)
