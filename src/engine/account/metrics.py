"""Capital metrics calculation - unified entry point.

This module provides a single entry point for calculating all capital-level
metrics, following the principle that all calculation logic belongs in engine
layer while monitoring layer only performs threshold checks.

Example:
    >>> from src.engine.account.metrics import calc_capital_metrics
    >>> metrics = calc_capital_metrics(portfolio)
    >>> print(f"Margin usage: {metrics.margin_usage:.1%}")
"""

from __future__ import annotations

from datetime import datetime

from src.data.models.account import ConsolidatedPortfolio
from src.engine.account.margin import calc_margin_utilization
from src.engine.models.capital import CapitalMetrics


def calc_capital_metrics(
    portfolio: ConsolidatedPortfolio,
    sharpe_ratio: float | None = None,
    kelly_capacity: float | None = None,
    peak_equity: float | None = None,
) -> CapitalMetrics:
    """Calculate all capital-level metrics from consolidated portfolio.

    This is the unified entry point for capital metrics calculation.
    It extracts values from ConsolidatedPortfolio and uses specialized
    calculation functions from the engine layer.

    Args:
        portfolio: Consolidated portfolio from all brokers.
        sharpe_ratio: Pre-calculated Sharpe ratio (optional).
        kelly_capacity: Maximum position value based on Kelly (optional).
        peak_equity: Historical peak equity for drawdown (optional).

    Returns:
        CapitalMetrics with all calculated values.

    Example:
        >>> from src.data.providers import get_portfolio
        >>> portfolio = get_portfolio()
        >>> metrics = calc_capital_metrics(portfolio, peak_equity=110000)
        >>> print(f"Drawdown: {metrics.current_drawdown:.1%}")
    """
    # Extract total equity
    total_equity = portfolio.total_value_usd

    # Calculate total cash balance in USD
    cash_balance = 0.0
    for cash in portfolio.cash_balances:
        if cash.currency == "USD":
            cash_balance += cash.balance
        elif cash.currency in portfolio.exchange_rates:
            cash_balance += cash.balance * portfolio.exchange_rates[cash.currency]
        # If no exchange rate, skip (or could use a fallback)

    # Calculate total maintenance margin from all brokers
    maintenance_margin = 0.0
    for broker_summary in portfolio.by_broker.values():
        if broker_summary.margin_used is not None:
            maintenance_margin += broker_summary.margin_used

    # Calculate total position value in USD
    total_position_value = 0.0
    for pos in portfolio.positions:
        if pos.currency == "USD":
            total_position_value += abs(pos.market_value)
        elif pos.currency in portfolio.exchange_rates:
            total_position_value += abs(pos.market_value) * portfolio.exchange_rates[pos.currency]

    # Unrealized P&L is already in USD
    unrealized_pnl = portfolio.total_unrealized_pnl_usd

    # Calculate margin usage using existing engine function
    margin_usage = None
    if total_equity and total_equity > 0:
        margin_usage = calc_margin_utilization(maintenance_margin, total_equity)

    # Calculate Kelly usage
    kelly_usage = None
    if kelly_capacity and kelly_capacity > 0 and total_position_value > 0:
        kelly_usage = total_position_value / kelly_capacity

    # Calculate current drawdown
    current_drawdown = None
    if peak_equity and peak_equity > 0 and total_equity is not None:
        current_drawdown = (peak_equity - total_equity) / peak_equity
        current_drawdown = max(0.0, current_drawdown)  # Ensure non-negative

    return CapitalMetrics(
        total_equity=total_equity,
        cash_balance=cash_balance,
        maintenance_margin=maintenance_margin,
        margin_usage=margin_usage,
        realized_pnl=None,  # Not available in ConsolidatedPortfolio
        unrealized_pnl=unrealized_pnl,
        sharpe_ratio=sharpe_ratio,
        total_position_value=total_position_value,
        kelly_capacity=kelly_capacity,
        kelly_usage=kelly_usage,
        peak_equity=peak_equity,
        current_drawdown=current_drawdown,
        timestamp=datetime.now(),
    )
