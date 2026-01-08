"""Capital metrics calculation - unified entry point.

This module provides a single entry point for calculating all capital-level
metrics, following the principle that all calculation logic belongs in engine
layer while monitoring layer only performs threshold checks.

Core Risk Control Metrics (4 Pillars):
    1. Margin Utilization - Distance from margin call (survival)
    2. Cash Ratio - Liquidity buffer (operational flexibility)
    3. Gross Leverage - Total exposure control (prevent "empty fat")
    4. Stress Test Loss - Tail risk (Black Swan protection)

Example:
    >>> from src.engine.account.metrics import calc_capital_metrics
    >>> metrics = calc_capital_metrics(portfolio)
    >>> print(f"Margin Utilization: {metrics.margin_utilization:.1%}")
    >>> print(f"Stress Test Loss: {metrics.stress_test_loss:.1%}")
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from src.data.models.account import AssetType, ConsolidatedPortfolio
from src.engine.models.capital import CapitalMetrics

logger = logging.getLogger(__name__)


def _is_valid_number(value) -> bool:
    """Check if value is a valid number (not None, not nan, not inf)."""
    if value is None:
        return False
    try:
        return not (math.isnan(value) or math.isinf(value))
    except (TypeError, ValueError):
        return False


def calc_margin_utilization(
    maintenance_margin: float,
    nlv: float,
) -> float | None:
    """Calculate margin utilization (survival metric).

    Margin Utilization = Current Maintenance Margin / NLV

    Physical meaning:
        - Measures distance from margin call
        - < 40% is safe, > 70% is dangerous

    Args:
        maintenance_margin: Current maintenance margin requirement.
        nlv: Net Liquidation Value.

    Returns:
        Utilization as decimal (e.g., 0.40 for 40%), or None if invalid.
    """
    if nlv is None or nlv <= 0:
        return None
    if maintenance_margin is None:
        return None
    return maintenance_margin / nlv


def calc_cash_ratio(
    cash_balance: float,
    nlv: float,
) -> float | None:
    """Calculate cash retention ratio (liquidity metric).

    Cash Ratio = Net Cash Balance / NLV

    Physical meaning:
        - Measures operational flexibility and assignment buffer
        - Higher ratio means more "dry powder" for emergencies
        - > 30% is safe, < 10% is dangerous

    Args:
        cash_balance: Net cash balance in USD.
        nlv: Net Liquidation Value.

    Returns:
        Cash ratio as decimal (e.g., 0.30 for 30%), or None if invalid.
    """
    if nlv is None or nlv <= 0:
        return None
    if cash_balance is None:
        return None
    return cash_balance / nlv


def calc_gross_leverage(
    portfolio: ConsolidatedPortfolio,
    nlv: float,
) -> float | None:
    """Calculate gross notional leverage (exposure metric).

    Gross Leverage = (Σ|Stock Value| + Σ|Option Notional|) / NLV

    Stock Value = |Qty × Price|
    Option Notional = Strike × Multiplier × |Qty|

    Physical meaning:
        - Measures total exposure relative to account size
        - Prevents "empty fat" - low margin but high notional exposure
        - < 2.0x is safe, > 4.0x is dangerous

    Args:
        portfolio: Consolidated portfolio with positions.
        nlv: Net Liquidation Value.

    Returns:
        Gross leverage as multiple (e.g., 2.5 for 2.5x), or None if invalid.
    """
    if nlv is None or nlv <= 0:
        return None

    total_stock_notional = 0.0
    total_option_notional = 0.0

    for pos in portfolio.positions:
        # Get FX rate for currency conversion
        fx_rate = 1.0
        if pos.currency != "USD" and pos.currency in portfolio.exchange_rates:
            fx_rate = portfolio.exchange_rates[pos.currency]

        if pos.asset_type == AssetType.STOCK:
            # Stock notional = |Qty × Price|
            # Use underlying_price if available, otherwise derive from market_value
            price = pos.underlying_price
            if price is None and pos.quantity != 0:
                price = abs(pos.market_value / pos.quantity)
            if price is not None:
                stock_value = abs(pos.quantity * price)
                total_stock_notional += stock_value * fx_rate

        elif pos.asset_type == AssetType.OPTION:
            # Option notional = Strike × Multiplier × |Qty|
            if pos.strike is not None and pos.contract_multiplier:
                option_notional = pos.strike * pos.contract_multiplier * abs(pos.quantity)
                total_option_notional += option_notional * fx_rate

    gross_notional = total_stock_notional + total_option_notional
    return gross_notional / nlv


def calc_stress_test_loss(
    portfolio: ConsolidatedPortfolio,
    current_nlv: float,
    cash_balance: float,
    spot_shock: float = -0.15,
    iv_shock: float = 0.40,
    risk_free_rate: float = 0.05,
) -> float | None:
    """Calculate stress test loss under extreme scenario (tail risk metric).

    Stress Test Loss = (Current_NLV - Stressed_NLV) / Current_NLV

    Default scenario: "Stock crash + panic"
        - Spot price drops by 15%
        - IV increases by 40%

    Uses Black-Scholes full revaluation for options.

    Physical meaning:
        - Predicts drawdown under Black Swan events
        - < 10% is safe, > 20% is dangerous

    Args:
        portfolio: Consolidated portfolio with positions.
        current_nlv: Current Net Liquidation Value.
        cash_balance: Current cash balance.
        spot_shock: Spot price change (default -0.15 for -15%).
        iv_shock: IV relative increase (default 0.40 for +40%).
        risk_free_rate: Risk-free rate for B-S pricing.

    Returns:
        Stress loss as decimal (e.g., 0.15 for 15% loss), or None if invalid.
    """
    if current_nlv is None or current_nlv <= 0:
        return None

    # Import B-S functions here to avoid circular imports
    from src.engine.bs.core import calc_bs_price
    from src.engine.models.bs_params import BSParams

    stressed_portfolio_value = 0.0

    for pos in portfolio.positions:
        # Get FX rate for currency conversion
        fx_rate = 1.0
        if pos.currency != "USD" and pos.currency in portfolio.exchange_rates:
            fx_rate = portfolio.exchange_rates[pos.currency]

        if pos.asset_type == AssetType.STOCK:
            # Stock revaluation: simply apply spot shock
            price = pos.underlying_price
            if not _is_valid_number(price) and pos.quantity != 0:
                # Fallback: derive price from market_value
                price = abs(pos.market_value / pos.quantity)
            if _is_valid_number(price):
                stressed_price = price * (1 + spot_shock)
                stressed_value = pos.quantity * stressed_price * fx_rate
                stressed_portfolio_value += stressed_value
            else:
                # Fallback: use current market value with spot shock
                logger.debug(
                    f"Stock {pos.symbol}: missing price, using market_value fallback"
                )
                stressed_portfolio_value += pos.market_value * (1 + spot_shock) * fx_rate

        elif pos.asset_type == AssetType.OPTION:
            # Option revaluation using B-S model
            # Check all required fields are valid numbers (not None, not nan)
            has_valid_data = all([
                _is_valid_number(pos.strike),
                _is_valid_number(pos.iv),
                _is_valid_number(pos.underlying_price),
                pos.expiry is not None,
            ])

            if not has_valid_data:
                # Missing data for B-S, use delta approximation for stress
                # Short put/call: approximate loss using delta × spot_shock × notional
                # Conservative fallback: assume delta ≈ 0.3 for OTM options
                delta = pos.delta if _is_valid_number(pos.delta) else 0.3
                notional = (pos.strike or 0) * (pos.contract_multiplier or 100) * abs(pos.quantity)

                # For short options (qty < 0): spot drop hurts short puts, helps short calls
                # Simplified: apply delta-based approximation
                if pos.option_type and pos.option_type.lower() == "put":
                    # Short put loses when spot drops: loss ≈ |delta| × spot_drop × notional
                    delta_loss = abs(delta) * abs(spot_shock) * notional
                    stressed_value = pos.market_value - delta_loss * (1 if pos.quantity < 0 else -1)
                else:
                    # Short call gains when spot drops (usually)
                    delta_loss = abs(delta) * abs(spot_shock) * notional
                    stressed_value = pos.market_value + delta_loss * (1 if pos.quantity < 0 else -1)

                stressed_portfolio_value += stressed_value * fx_rate
                logger.warning(
                    f"Option {pos.symbol}: missing data for B-S, using delta approximation "
                    f"(delta={delta:.2f}, notional={notional:.0f})"
                )
                continue

            # Calculate stressed parameters
            stressed_spot = pos.underlying_price * (1 + spot_shock)
            stressed_iv = pos.iv * (1 + iv_shock)

            # Calculate time to expiry in years
            dte_years = _calc_dte_years(pos.expiry)
            if dte_years <= 0:
                dte_years = 1 / 365  # Minimum 1 day

            # Determine option type
            is_call = pos.option_type is not None and pos.option_type.lower() == "call"

            # Create B-S params for stressed scenario
            try:
                bs_params = BSParams(
                    spot_price=stressed_spot,
                    strike_price=pos.strike,
                    risk_free_rate=risk_free_rate,
                    volatility=stressed_iv,
                    time_to_expiry=dte_years,
                    is_call=is_call,
                )

                # Calculate stressed option price (per share)
                stressed_option_price = calc_bs_price(bs_params)
                if stressed_option_price is None:
                    # B-S calculation failed, use current value
                    stressed_portfolio_value += pos.market_value * fx_rate
                    continue

                # Option value = Price × Multiplier × Qty
                # Note: qty can be negative for short positions
                stressed_option_value = (
                    stressed_option_price * pos.contract_multiplier * pos.quantity
                )
                stressed_portfolio_value += stressed_option_value * fx_rate

            except Exception as e:
                logger.warning(
                    f"B-S revaluation failed for {pos.symbol}: {e}, using current value"
                )
                stressed_portfolio_value += pos.market_value * fx_rate

    # Stressed NLV = Cash + Stressed Portfolio Value
    stressed_nlv = cash_balance + stressed_portfolio_value

    # Handle potential nan values
    if not _is_valid_number(stressed_nlv):
        logger.warning(
            f"Stress test produced invalid result: stressed_nlv={stressed_nlv}, "
            f"cash={cash_balance}, portfolio={stressed_portfolio_value}"
        )
        return None

    # Stress Test Loss = (Current - Stressed) / Current
    stress_loss = (current_nlv - stressed_nlv) / current_nlv

    # Return positive value for loss (ensure non-negative)
    # Return None if result is invalid (nan/inf)
    if not _is_valid_number(stress_loss):
        logger.warning(f"Stress test loss is invalid: {stress_loss}")
        return None

    return max(0.0, stress_loss)


def _calc_dte_years(expiry: str) -> float:
    """Convert expiry string to years remaining.

    Args:
        expiry: Expiry date string (various formats supported).

    Returns:
        Time to expiry in years.
    """
    try:
        # Try different date formats
        for fmt in ["%Y-%m-%d", "%Y%m%d", "%y%m%d"]:
            try:
                expiry_date = datetime.strptime(expiry, fmt)
                break
            except ValueError:
                continue
        else:
            return 30 / 365  # Default 30 days if parsing fails

        days = (expiry_date - datetime.now()).days
        return max(days, 1) / 365

    except Exception:
        return 30 / 365


def _calc_cash_balance_usd(portfolio: ConsolidatedPortfolio) -> float:
    """Calculate total cash balance in USD.

    Args:
        portfolio: Consolidated portfolio.

    Returns:
        Total cash balance converted to USD.
    """
    cash_balance = 0.0
    for cash in portfolio.cash_balances:
        if cash.currency == "USD":
            cash_balance += cash.balance
        elif cash.currency in portfolio.exchange_rates:
            cash_balance += cash.balance * portfolio.exchange_rates[cash.currency]
    return cash_balance


def _calc_maintenance_margin(portfolio: ConsolidatedPortfolio) -> float:
    """Calculate total maintenance margin from all brokers.

    Args:
        portfolio: Consolidated portfolio.

    Returns:
        Total maintenance margin.
    """
    maintenance_margin = 0.0
    for broker_summary in portfolio.by_broker.values():
        if broker_summary.margin_used is not None:
            maintenance_margin += broker_summary.margin_used
    return maintenance_margin


def _calc_total_position_value(portfolio: ConsolidatedPortfolio) -> float:
    """Calculate total position value in USD.

    Args:
        portfolio: Consolidated portfolio.

    Returns:
        Total absolute market value of all positions.
    """
    total_position_value = 0.0
    for pos in portfolio.positions:
        if pos.currency == "USD":
            total_position_value += abs(pos.market_value)
        elif pos.currency in portfolio.exchange_rates:
            total_position_value += abs(pos.market_value) * portfolio.exchange_rates[pos.currency]
    return total_position_value


def calc_capital_metrics(
    portfolio: ConsolidatedPortfolio,
    risk_free_rate: float = 0.05,
) -> CapitalMetrics:
    """Calculate all capital-level metrics from consolidated portfolio.

    This is the unified entry point for capital metrics calculation.
    It extracts values from ConsolidatedPortfolio and calculates the
    4 core risk control metrics.

    Args:
        portfolio: Consolidated portfolio from all brokers.
        risk_free_rate: Risk-free rate for B-S stress test (default 5%).

    Returns:
        CapitalMetrics with all calculated values.

    Example:
        >>> from src.data.providers import get_portfolio
        >>> portfolio = get_portfolio()
        >>> metrics = calc_capital_metrics(portfolio)
        >>> print(f"Margin Utilization: {metrics.margin_utilization:.1%}")
        >>> print(f"Cash Ratio: {metrics.cash_ratio:.1%}")
        >>> print(f"Gross Leverage: {metrics.gross_leverage:.1f}x")
        >>> print(f"Stress Test Loss: {metrics.stress_test_loss:.1%}")
    """
    # Extract NLV (total equity)
    nlv = portfolio.total_value_usd

    # Calculate base values
    cash_balance = _calc_cash_balance_usd(portfolio)
    maintenance_margin = _calc_maintenance_margin(portfolio)
    total_position_value = _calc_total_position_value(portfolio)
    unrealized_pnl = portfolio.total_unrealized_pnl_usd

    # === Calculate 4 Core Risk Control Metrics ===

    # 1. Margin Utilization = Maint Margin / NLV
    margin_utilization = calc_margin_utilization(maintenance_margin, nlv)

    # 2. Cash Ratio = Cash Balance / NLV
    cash_ratio = calc_cash_ratio(cash_balance, nlv)

    # 3. Gross Leverage = Total Notional / NLV
    gross_leverage = calc_gross_leverage(portfolio, nlv)

    # 4. Stress Test Loss (B-S revaluation)
    stress_test_loss = calc_stress_test_loss(
        portfolio,
        nlv,
        cash_balance,
        spot_shock=-0.15,  # -15%
        iv_shock=0.40,     # +40%
        risk_free_rate=risk_free_rate,
    )

    return CapitalMetrics(
        total_equity=nlv,
        cash_balance=cash_balance,
        maintenance_margin=maintenance_margin,
        realized_pnl=None,  # Not available in ConsolidatedPortfolio
        unrealized_pnl=unrealized_pnl,
        total_position_value=total_position_value,
        margin_utilization=margin_utilization,
        cash_ratio=cash_ratio,
        gross_leverage=gross_leverage,
        stress_test_loss=stress_test_loss,
        timestamp=datetime.now(),
    )
