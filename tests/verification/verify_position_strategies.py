#!/usr/bin/env python3
"""Position-Level Strategy Verification Script.

Verifies strategy metrics for each option position in the account.
Uses data models to drive all calculations:
  AccountPosition → StockVolatility → OptionLeg + StrategyParams → Strategy → StrategyMetrics

This script:
1. Classifies each option position into strategy types (short_put, covered_call, strangle, etc.)
2. Builds complete data pipeline with StockVolatility for HV/IV data
3. Creates Strategy objects and calculates comprehensive metrics
4. Verifies Position-level indicators: SAS, PREI, TGR, ROC, Sharpe Ratio, Kelly Fraction

Usage:
    python tests/verification/verify_position_strategies.py
    python tests/verification/verify_position_strategies.py --account-type paper
    python tests/verification/verify_position_strategies.py --ibkr-only
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
from src.data.models.option import Greeks, OptionType
from src.data.models.stock import StockVolatility
from src.data.providers import IBKRProvider, FutuProvider
from src.data.providers.account_aggregator import AccountAggregator
from src.engine.models.enums import PositionSide
from src.engine.models.strategy import OptionLeg, StrategyMetrics, StrategyParams
from src.engine.strategy import (
    StrategyInstance,
    create_strategies_from_position,
)
from src.engine.strategy.factory import calc_dte_from_expiry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Output Formatting
# ============================================================================


def print_section_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_strategy_debug_info(strategy, position: AccountPosition) -> None:
    """Print detailed strategy information for debugging.

    Args:
        strategy: OptionStrategy instance.
        position: Original AccountPosition.
    """
    print(f"\n{'='*70}")
    print(f"DEBUG: Strategy Details for {position.symbol}")
    print(f"{'='*70}")

    # OptionLeg Info
    if strategy.leg:
        print(f"\nOptionLeg:")
        print(f"  Type: {strategy.leg.option_type}")
        print(f"  Side: {strategy.leg.side}")
        print(f"  Strike: ${strategy.leg.strike:.2f}")
        print(f"  Premium: ${strategy.leg.premium:.4f}")
        print(f"  Quantity: {strategy.leg.quantity}")
        print(f"  Greeks:")
        if strategy.leg.delta is not None:
            print(f"    Delta: {strategy.leg.delta:.4f}")
        else:
            print("    Delta: None")
        if strategy.leg.gamma is not None:
            print(f"    Gamma: {strategy.leg.gamma:.6f}")
        else:
            print("    Gamma: None")
        if strategy.leg.theta is not None:
            print(f"    Theta: {strategy.leg.theta:.4f}")
        else:
            print("    Theta: None")
        if strategy.leg.vega is not None:
            print(f"    Vega: {strategy.leg.vega:.4f}")
        else:
            print("    Vega: None")

    # StrategyParams Info
    params = strategy.params
    print(f"\nStrategyParams:")
    print(f"  Spot Price: ${params.spot_price:.2f}")
    print(f"  Volatility (IV): {params.volatility:.4f} ({params.volatility*100:.2f}%)")
    print(f"  Time to Expiry: {params.time_to_expiry:.4f} years")
    print(f"  Risk-Free Rate: {params.risk_free_rate:.4f}")
    if params.hv is not None:
        print(f"  HV: {params.hv:.4f} ({params.hv*100:.2f}%)")
    else:
        print("  HV: None")
    if params.dte is not None:
        print(f"  DTE: {params.dte} days")
    else:
        print("  DTE: None")

    # Calculated values
    print(f"\nCalculated Metrics:")
    try:
        margin_req = strategy.calc_margin_requirement()
        print(f"  Margin Requirement: ${margin_req:.2f}")
    except Exception as e:
        print(f"  Margin Requirement: Error - {e}")

    capital = strategy._calc_capital_at_risk()
    print(f"  Capital at Risk: ${capital:.2f}")
    print(f"  Expected Return: ${strategy.calc_expected_return():.4f}")
    print(f"  Max Profit: ${strategy.calc_max_profit():.2f}")
    print(f"  Max Loss: ${strategy.calc_max_loss():.2f}")

    print(f"{'='*70}\n")


def print_strategy_metrics(
    position: AccountPosition, strategy_type: str, metrics: StrategyMetrics
) -> None:
    """Print strategy metrics in formatted output.

    Args:
        position: Original AccountPosition.
        strategy_type: Strategy classification.
        metrics: Calculated StrategyMetrics.
    """
    # Header
    dte = calc_dte_from_expiry(position.expiry)
    dte_str = f"{dte} DTE" if dte is not None else "N/A"

    # Calculate premium per share and total
    premium_per_share = abs(position.market_value / (position.quantity * position.contract_multiplier))
    premium_total = abs(position.market_value / position.quantity)

    print(f"\n[Position: {position.symbol} {position.option_type.upper()} "
          f"{position.strike:.1f} {position.expiry}]")
    print(f"Strategy Type: {strategy_type}")
    print(f"Symbol: {position.symbol}")
    print(f"Strike: ${position.strike:.2f}")
    print(f"Expiry: {position.expiry} ({dte_str})")
    print(f"Premium: ${premium_per_share:.2f}/share (${premium_total:.2f} total)")
    print(f"IV: {position.iv:.1%}" if position.iv else "IV: N/A")
    print(f"Underlying Price: ${position.underlying_price:.2f}")

    # Core Metrics
    print("\nCore Metrics:")
    print(f"  Expected Return: ${metrics.expected_return:,.2f}")
    print(f"  Max Profit: ${metrics.max_profit:,.2f}")
    print(f"  Max Loss: ${metrics.max_loss:,.2f}")

    if isinstance(metrics.breakeven, list):
        breakeven_str = ", ".join([f"${be:.2f}" for be in metrics.breakeven])
        print(f"  Breakeven: {breakeven_str}")
    else:
        print(f"  Breakeven: ${metrics.breakeven:.2f}")

    print(f"  Win Probability: {metrics.win_probability:.1%}")

    # Risk-Adjusted Metrics
    print("\nRisk-Adjusted Metrics:")
    print(f"  Return Std: ${metrics.return_std:,.2f}")

    if metrics.sharpe_ratio is not None:
        print(f"  Sharpe Ratio: {metrics.sharpe_ratio:.3f}")
    else:
        print("  Sharpe Ratio: N/A")

    if metrics.kelly_fraction is not None:
        kelly_pct = metrics.kelly_fraction * 100
        if kelly_pct > 20:
            interpretation = "(strong edge)"
        elif kelly_pct > 10:
            interpretation = "(moderate edge)"
        elif kelly_pct > 0:
            interpretation = "(small edge)"
        else:
            interpretation = "(no edge)"
        print(f"  Kelly Fraction: {metrics.kelly_fraction:.3f} ({kelly_pct:.1f}%) {interpretation}")
    else:
        print("  Kelly Fraction: N/A")

    # Extended Metrics
    print("\nExtended Metrics:")

    if metrics.prei is not None:
        if metrics.prei < 20:
            risk_level = "(low risk)"
        elif metrics.prei < 40:
            risk_level = "(moderate risk)"
        elif metrics.prei < 60:
            risk_level = "(elevated risk)"
        else:
            risk_level = "(high risk)"
        print(f"  PREI: {metrics.prei:.1f} {risk_level}")
    else:
        print("  PREI: N/A (missing Greeks/DTE)")

    if metrics.sas is not None:
        if metrics.sas >= 70:
            attractiveness = "(very attractive)"
        elif metrics.sas >= 50:
            attractiveness = "(attractive)"
        elif metrics.sas >= 30:
            attractiveness = "(moderate)"
        else:
            attractiveness = "(unattractive)"
        print(f"  SAS: {metrics.sas:.1f} {attractiveness}")
    else:
        print("  SAS: N/A (missing HV data)")

    if metrics.tgr is not None:
        if metrics.tgr > 0.8:
            tgr_quality = "(excellent theta income)"
        elif metrics.tgr > 0.5:
            tgr_quality = "(good theta income)"
        elif metrics.tgr > 0.3:
            tgr_quality = "(moderate theta income)"
        else:
            tgr_quality = "(low theta income)"
        print(f"  TGR: {metrics.tgr:.3f} {tgr_quality}")
    else:
        print("  TGR: N/A (missing Greeks)")

    if metrics.roc is not None:
        print(f"  ROC: {metrics.roc:.1%} (annualized)")
    else:
        print("  ROC: N/A (missing margin data)")

    if metrics.expected_roc is not None:
        print(f"  Expected ROC: {metrics.expected_roc:.1%} (annualized)")
    else:
        print("  Expected ROC: N/A (missing data)")

    print("-" * 70)


# ============================================================================
# Main Verification Function
# ============================================================================


def verify_position_strategies(
    portfolio: ConsolidatedPortfolio, ibkr_provider: IBKRProvider | None
) -> None:
    """Verify Position-level strategy metrics for all option positions.

    Args:
        portfolio: Consolidated portfolio with all positions.
        ibkr_provider: IBKR provider for volatility data.
    """
    print_section_header("Position-Level Strategy Metrics")

    option_positions = [
        p for p in portfolio.positions if p.asset_type == AssetType.OPTION
    ]

    if not option_positions:
        print("No option positions found.")
        return

    print(f"\nFound {len(option_positions)} option position(s) to verify.\n")

    # Statistics
    total_positions = 0
    verified_positions = 0
    skipped_positions = 0
    strategy_counts = {}

    for pos in option_positions:
        total_positions += 1

        # Step 1: Create strategy instance(s) using factory
        # Factory handles classification, splitting, and all complex logic
        strategy_instances = create_strategies_from_position(
            position=pos,
            all_positions=portfolio.positions,
            ibkr_provider=ibkr_provider,
        )

        if not strategy_instances:
            logger.info(f"Skipping {pos.symbol}: no strategies created")
            skipped_positions += 1
            continue

        # Step 2: Process each strategy instance
        # (Most positions return 1 strategy, but partial coverage returns 2)
        for idx, instance in enumerate(strategy_instances, 1):
            strategy = instance.strategy
            ratio = instance.quantity_ratio
            desc = instance.description

            # Extract strategy type from description
            strategy_type = desc.split("(")[0].strip()

            # Track strategy types
            strategy_counts[strategy_type] = strategy_counts.get(strategy_type, 0) + 1

            # Log coverage info
            if len(strategy_instances) > 1:
                logger.info(f"{pos.symbol} [{idx}/{len(strategy_instances)}]: {desc}")
                print(f"\n>>> Strategy {idx}/{len(strategy_instances)}: {desc}")
            else:
                logger.info(f"{pos.symbol}: {desc}")

            # Print debug info for strategy
            print_strategy_debug_info(strategy, pos)

            # Step 3: Calculate margin for logging
            try:
                margin_per_contract = strategy.calc_margin_requirement()
                capital_at_risk = strategy._calc_capital_at_risk()

                # Apply quantity ratio
                margin = margin_per_contract * ratio

                margin_ratio = margin / capital_at_risk if capital_at_risk > 0 else 1.0

                logger.info(
                    f"{pos.symbol}: Margin=${margin:.2f} "
                    f"(${margin_per_contract:.2f}×{ratio:.0%}), "
                    f"Capital@Risk=${capital_at_risk:.2f}, "
                    f"Ratio={margin_ratio:.1%}"
                )
            except Exception as e:
                logger.warning(f"{pos.symbol}: Could not calculate margin: {e}")

            # Step 4: Calculate metrics (now uses calc_margin_requirement internally)
            try:
                metrics = strategy.calc_metrics()
                verified_positions += 1
            except Exception as e:
                print(f"\n{pos.symbol}: Error calculating metrics: {e}")
                logger.exception(f"Error calculating metrics for {pos.symbol}")
                skipped_positions += 1
                continue

            # Step 5: Print results with ratio annotation
            if len(strategy_instances) > 1:
                print(f"\n{pos.symbol} [{idx}/{len(strategy_instances)}] - {desc}:")
            print_strategy_metrics(pos, strategy_type, metrics)

    # Summary
    print_section_header("Verification Summary")
    print(f"\nTotal Option Positions: {total_positions}")
    print(f"Successfully Verified: {verified_positions}")
    print(f"Skipped: {skipped_positions}")
    print("\nStrategy Type Distribution:")
    for stype, count in strategy_counts.items():
        print(f"  {stype}: {count}")


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Verify position-level strategy metrics with real data"
    )
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
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug output",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    account_type = AccountType.PAPER if args.account_type == "paper" else AccountType.REAL

    print("\n" + "=" * 70)
    print("  Position-Level Strategy Verification")
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
        portfolio = aggregator.get_consolidated_portfolio(
            account_type, base_currency="USD"
        )

        # Verify position strategies
        verify_position_strategies(portfolio, ibkr)

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
