#!/usr/bin/env python3
"""Portfolio Calculation Verification Script.

Verifies the accuracy of portfolio and account calculation functions
using real broker position data.

This script tests engine layer calculations:
1. Portfolio Greeks aggregation (delta, gamma, theta, vega, delta_dollars, gamma_dollars)
2. Portfolio risk metrics (TGR, concentration risk)
3. Account metrics (margin utilization, ROC)

Usage:
    python tests/verification/verify_portfolio_calculations.py
    python tests/verification/verify_portfolio_calculations.py --account-type paper
    python tests/verification/verify_portfolio_calculations.py --ibkr-only
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data.models.account import (
    AccountPosition,
    AccountType,
    AssetType,
    ConsolidatedPortfolio,
)
from src.data.models.option import Greeks
from src.data.providers import IBKRProvider, FutuProvider
from src.data.providers.account_aggregator import AccountAggregator
from src.engine.models.position import Position

# Portfolio calculations
from src.engine.portfolio.greeks_agg import (
    calc_portfolio_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_vega,
    calc_delta_dollars,
    calc_gamma_dollars,
    summarize_portfolio_greeks,
)
from src.engine.portfolio.risk_metrics import (
    calc_portfolio_tgr,
    calc_concentration_risk,
)

# Account calculations
from src.engine.account.margin import calc_margin_utilization

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def account_position_to_engine_position(ap: AccountPosition) -> Position:
    """Convert AccountPosition to engine Position.

    Args:
        ap: AccountPosition from broker data.

    Returns:
        Position object for engine calculations.
    """
    greeks = Greeks(
        delta=ap.delta,
        gamma=ap.gamma,
        theta=ap.theta,
        vega=ap.vega,
    )

    # Calculate DTE from expiry if available
    dte = None
    if ap.expiry:
        try:
            expiry_date = datetime.strptime(ap.expiry, "%Y%m%d")
            dte = (expiry_date - datetime.now()).days
            if dte < 0:
                dte = 0
        except ValueError:
            pass

    # Ensure contract_multiplier is int (IBKR may return string)
    multiplier = ap.contract_multiplier
    if isinstance(multiplier, str):
        multiplier = int(multiplier) if multiplier else 1
    elif multiplier is None:
        multiplier = 1

    return Position(
        symbol=ap.symbol,
        quantity=ap.quantity,
        greeks=greeks,
        market_value=ap.market_value,
        underlying_price=ap.underlying_price,
        contract_multiplier=multiplier,
        dte=dte,
        currency=ap.currency,
    )


def print_section_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_positions(positions: list[AccountPosition]) -> None:
    """Print position details in a table format."""
    print_section_header("Position Details")

    if not positions:
        print("No positions found.")
        return

    # Separate stocks and options
    stocks = [p for p in positions if p.asset_type == AssetType.STOCK]
    options = [p for p in positions if p.asset_type == AssetType.OPTION]

    # Print stocks
    if stocks:
        print("\n[Stocks]")
        print(f"{'Symbol':<15} {'Qty':>8} {'MktVal':>12} {'P&L':>10} {'Delta':>8}")
        print("-" * 55)
        for p in stocks:
            delta = f"{p.delta:.4f}" if p.delta else "N/A"
            print(f"{p.symbol:<15} {p.quantity:>8.0f} {p.market_value:>12,.2f} "
                  f"{p.unrealized_pnl:>10,.2f} {delta:>8}")

    # Print options
    if options:
        print("\n[Options]")
        print(f"{'Symbol':<25} {'Qty':>6} {'Strike':>8} {'Expiry':>10} "
              f"{'Delta':>7} {'Gamma':>7} {'Theta':>7} {'Vega':>7} {'IV':>7}")
        print("-" * 95)
        for p in options:
            delta = f"{p.delta:.3f}" if p.delta else "N/A"
            gamma = f"{p.gamma:.4f}" if p.gamma else "N/A"
            theta = f"{p.theta:.3f}" if p.theta else "N/A"
            vega = f"{p.vega:.3f}" if p.vega else "N/A"
            iv = f"{p.iv:.1%}" if p.iv else "N/A"
            strike = f"{p.strike:.1f}" if p.strike else "N/A"
            expiry = p.expiry if p.expiry else "N/A"
            print(f"{p.symbol:<25} {p.quantity:>6.0f} {strike:>8} {expiry:>10} "
                  f"{delta:>7} {gamma:>7} {theta:>7} {vega:>7} {iv:>7}")

    print(f"\nTotal positions: {len(positions)} ({len(stocks)} stocks, {len(options)} options)")


def print_portfolio_greeks(positions: list[Position]) -> None:
    """Calculate and print portfolio Greeks."""
    print_section_header("Portfolio Greeks Aggregation")

    if not positions:
        print("No positions to calculate.")
        return

    # Calculate individual Greeks
    total_delta = calc_portfolio_delta(positions)
    total_gamma = calc_portfolio_gamma(positions)
    total_theta = calc_portfolio_theta(positions)
    total_vega = calc_portfolio_vega(positions)

    print(f"\n{'Metric':<25} {'Value':>15} {'Description'}")
    print("-" * 70)
    print(f"{'Portfolio Delta':<25} {total_delta:>15.4f} {'Sum of all position deltas'}")
    print(f"{'Portfolio Gamma':<25} {total_gamma:>15.4f} {'Sum of all position gammas'}")
    print(f"{'Portfolio Theta':<25} {total_theta:>15.4f} {'Daily time decay ($)'}")
    print(f"{'Portfolio Vega':<25} {total_vega:>15.4f} {'Sensitivity to IV change'}")

    # Calculate dollar-based metrics (need underlying prices)
    delta_dollars = calc_delta_dollars(positions)
    gamma_dollars = calc_gamma_dollars(positions)

    print(f"\n{'Dollar Metrics':<25} {'Value':>15} {'Description'}")
    print("-" * 70)
    print(f"{'Delta Dollars':<25} ${delta_dollars:>14,.2f} {'$ change per $1 underlying move'}")
    print(f"{'Gamma Dollars':<25} ${gamma_dollars:>14,.2f} {'Delta$ change per 1% move'}")
    print(f"{'Theta (USD)':<25} ${total_theta:>14,.2f} {'Daily time decay (USD)'}")
    print(f"{'Vega (USD)':<25} ${total_vega:>14,.2f} {'$ change per 1% IV move'}")

    # Summary using summarize function
    print("\n[Greeks Summary via summarize_portfolio_greeks()]")
    summary = summarize_portfolio_greeks(positions)
    for key, value in summary.items():
        if value is not None:
            print(f"  {key}: {value:.4f}")


def print_risk_metrics(positions: list[Position]) -> None:
    """Calculate and print portfolio risk metrics."""
    print_section_header("Portfolio Risk Metrics")

    if not positions:
        print("No positions to calculate.")
        return

    print(f"\n{'Metric':<30} {'Value':>15} {'Interpretation'}")
    print("-" * 75)

    # Theta/Gamma Ratio
    tgr = calc_portfolio_tgr(positions)
    if tgr is not None:
        interpretation = "Good income/risk" if tgr > 0.5 else "Low income/risk"
        print(f"{'Theta/Gamma Ratio (TGR)':<30} {tgr:>15.4f} {interpretation}")
    else:
        print(f"{'Theta/Gamma Ratio (TGR)':<30} {'N/A':>15} {'Insufficient data'}")

    # Concentration Risk (HHI)
    hhi = calc_concentration_risk(positions)
    if hhi is not None:
        if hhi < 0.15:
            interpretation = "Well diversified"
        elif hhi < 0.25:
            interpretation = "Moderately concentrated"
        else:
            interpretation = "Highly concentrated"
        print(f"{'Concentration Risk (HHI)':<30} {hhi:>15.4f} {interpretation}")
    else:
        print(f"{'Concentration Risk (HHI)':<30} {'N/A':>15} {'Insufficient data'}")


def print_account_metrics(portfolio: ConsolidatedPortfolio) -> None:
    """Calculate and print account-level metrics."""
    print_section_header("Account Metrics")

    print(f"\n{'Broker':<10} {'Total Assets':>15} {'Cash':>15} {'Margin Used':>15} {'Margin Avail':>15}")
    print("-" * 75)

    for broker_name, summary in portfolio.by_broker.items():
        margin_used = f"${summary.margin_used:,.2f}" if summary.margin_used else "N/A"
        margin_avail = f"${summary.margin_available:,.2f}" if summary.margin_available else "N/A"
        print(f"{broker_name:<10} ${summary.total_assets:>14,.2f} ${summary.cash:>14,.2f} "
              f"{margin_used:>15} {margin_avail:>15}")

    # Calculate margin utilization for each broker
    print("\n[Margin Utilization]")
    for broker_name, summary in portfolio.by_broker.items():
        if summary.margin_used is not None and summary.margin_available is not None:
            total_margin = summary.margin_used + summary.margin_available
            utilization = calc_margin_utilization(summary.margin_used, total_margin)
            if utilization is not None:
                print(f"  {broker_name}: {utilization:.1%} margin utilized")

    # Portfolio totals
    print("\n[Portfolio Totals]")
    print(f"  Total Value (USD): ${portfolio.total_value_usd:,.2f}")
    print(f"  Total Unrealized P&L (USD): ${portfolio.total_unrealized_pnl_usd:,.2f}")

    # Exchange rates used
    if portfolio.exchange_rates:
        print("\n[Exchange Rates]")
        for currency, rate in portfolio.exchange_rates.items():
            print(f"  {currency}/USD: {rate:.4f}")


def print_calculation_validation(positions: list[Position]) -> None:
    """Print validation of individual calculations for debugging."""
    print_section_header("Calculation Validation (Debug)")

    # Print position details including multiplier and underlying_price
    print("\n[Position Details - Multiplier & Underlying Price]")
    print(f"{'Symbol':<25} {'Qty':>6} {'Mult':>6} {'UndPrice':>12} {'Delta':>8} {'Gamma':>8}")
    print("-" * 75)
    for pos in positions:
        und_price = f"{pos.underlying_price:.2f}" if pos.underlying_price else "N/A"
        delta = f"{pos.delta:.4f}" if pos.delta is not None else "N/A"
        gamma = f"{pos.gamma:.4f}" if pos.gamma is not None else "N/A"
        print(f"{pos.symbol:<25} {pos.quantity:>6.0f} {pos.contract_multiplier:>6} {und_price:>12} {delta:>8} {gamma:>8}")

    print("\n[Per-Position Delta Contribution (with multiplier)]")
    print(f"{'Symbol':<25} {'Qty':>8} {'Delta':>10} {'Mult':>6} {'Contribution':>15}")
    print("-" * 70)

    total = 0.0
    for pos in positions:
        if pos.delta is not None:
            contribution = pos.delta * pos.quantity * pos.contract_multiplier
            total += contribution
            print(f"{pos.symbol:<25} {pos.quantity:>8.0f} {pos.delta:>10.4f} {pos.contract_multiplier:>6} {contribution:>15.4f}")

    print("-" * 60)
    print(f"{'Total Portfolio Delta':<45} {total:>15.4f}")


def main():
    parser = argparse.ArgumentParser(description="Verify portfolio calculations with real data")
    parser.add_argument(
        "--account-type",
        choices=["paper", "real"],
        default="paper",
        help="Account type to use (default: paper)",
    )
    parser.add_argument(
        "--ibkr-only",
        action="store_true",
        help="Only use IBKR (skip Futu)",
    )
    parser.add_argument(
        "--futu-only",
        action="store_true",
        help="Only use Futu (skip IBKR)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug output",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    account_type = AccountType.PAPER if args.account_type == "paper" else AccountType.REAL

    print("\n" + "=" * 70)
    print("  Portfolio Calculation Verification")
    print(f"  Account Type: {account_type.value.upper()}")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Initialize providers
    ibkr = None
    futu = None

    try:
        if not args.futu_only:
            logger.info("Connecting to IBKR...")
            ibkr = IBKRProvider(account_type=account_type)
            ibkr.__enter__()
            if ibkr.is_available:
                logger.info("IBKR connected successfully")
            else:
                logger.warning("IBKR not available")
                ibkr = None
    except Exception as e:
        logger.warning(f"Failed to connect to IBKR: {e}")
        ibkr = None

    try:
        if not args.ibkr_only:
            logger.info("Connecting to Futu...")
            futu = FutuProvider(account_type=account_type)
            futu.__enter__()
            if futu.is_available:
                logger.info("Futu connected successfully")
            else:
                logger.warning("Futu not available")
                futu = None
    except Exception as e:
        logger.warning(f"Failed to connect to Futu: {e}")
        futu = None

    if not ibkr and not futu:
        print("\nError: No broker connections available. Exiting.")
        sys.exit(1)

    try:
        # Get consolidated portfolio
        logger.info("Fetching portfolio data...")
        aggregator = AccountAggregator(ibkr, futu)
        portfolio = aggregator.get_consolidated_portfolio(account_type, base_currency="USD")

        # 1. Print raw position data
        print_positions(portfolio.positions)

        # 2. Convert to engine positions (both stocks and options)
        all_positions = [
            account_position_to_engine_position(p)
            for p in portfolio.positions
        ]

        # 3. Calculate and print Portfolio Greeks
        print_portfolio_greeks(all_positions)

        # 4. Calculate and print risk metrics
        print_risk_metrics(all_positions)

        # 5. Print account metrics
        print_account_metrics(portfolio)

        # 6. Print validation details (for debugging)
        if args.verbose:
            print_calculation_validation(all_positions)

        print("\n" + "=" * 70)
        print("  Verification Complete")
        print("=" * 70 + "\n")

    finally:
        # Clean up connections
        if ibkr:
            try:
                ibkr.__exit__(None, None, None)
            except Exception:
                pass
        if futu:
            try:
                futu.__exit__(None, None, None)
            except Exception:
                pass


if __name__ == "__main__":
    main()
