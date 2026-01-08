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
    python tests/verification/verify_position_strategies.py -v  # verbose mode with debug info
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

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
# Data Container for Table Output
# ============================================================================


@dataclass
class StrategyRow:
    """Container for all strategy data to be displayed in table."""

    # Position Info
    symbol: str
    underlying: str
    option_type: str  # CALL/PUT
    side: str  # SHORT/LONG
    strike: float
    expiry: str
    dte: Optional[int]
    quantity: float  # May be fractional due to partial coverage
    premium: float  # per share
    iv: Optional[float]
    underlying_price: float
    strategy_type: str

    # Greeks
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]

    # Strategy Params
    hv: Optional[float]
    spot_price: float

    # Calculated Values
    margin: Optional[float]
    capital_at_risk: Optional[float]

    # Core Metrics
    expected_return: float
    max_profit: float
    max_loss: float
    breakeven: float | list[float]
    win_probability: float

    # Risk-Adjusted Metrics
    return_std: float
    sharpe_ratio: Optional[float]
    kelly_fraction: Optional[float]

    # Extended Metrics
    prei: Optional[float]
    sas: Optional[float]
    tgr: Optional[float]
    roc: Optional[float]
    expected_roc: Optional[float]


# ============================================================================
# Output Formatting
# ============================================================================


def print_section_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 120)
    print(f"  {title}")
    print("=" * 120)


def print_strategy_debug_info(strategy, position: AccountPosition) -> None:
    """Print detailed strategy information for debugging (verbose mode).

    Args:
        strategy: OptionStrategy instance.
        position: Original AccountPosition.
    """
    print(f"\n{'='*80}")
    print(f"DEBUG: Strategy Details for {position.symbol}")
    print(f"{'='*80}")

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

    print(f"{'='*80}\n")


def format_value(val, fmt: str = ".2f", suffix: str = "") -> str:
    """Format a value for table display."""
    if val is None:
        return "-"
    if fmt == ".0%":
        return f"{val:.0%}"
    if fmt == ".1%":
        return f"{val:.1%}"
    if fmt == ".1f":
        return f"{val:.1f}{suffix}"
    if fmt == ".2f":
        return f"{val:.2f}{suffix}"
    if fmt == ".3f":
        return f"{val:.3f}{suffix}"
    return str(val)


def get_prei_rating(prei: Optional[float]) -> str:
    """Get PREI risk rating."""
    if prei is None:
        return ""
    if prei < 20:
        return "Low"
    if prei < 40:
        return "Med"
    if prei < 60:
        return "High"
    return "VHigh"


def get_sas_rating(sas: Optional[float]) -> str:
    """Get SAS attractiveness rating."""
    if sas is None:
        return ""
    if sas >= 70:
        return "VGood"
    if sas >= 50:
        return "Good"
    if sas >= 30:
        return "Med"
    return "Low"


def get_tgr_rating(tgr: Optional[float]) -> str:
    """Get TGR quality rating."""
    if tgr is None:
        return ""
    if tgr > 0.8:
        return "Exc"
    if tgr > 0.5:
        return "Good"
    if tgr > 0.3:
        return "Med"
    return "Low"


def get_kelly_rating(kelly: Optional[float]) -> str:
    """Get Kelly fraction rating."""
    if kelly is None:
        return ""
    kelly_pct = kelly * 100
    if kelly_pct > 20:
        return "Strong"
    if kelly_pct > 10:
        return "Med"
    if kelly_pct > 0:
        return "Small"
    return "None"


def print_summary_tables(rows: list[StrategyRow]) -> None:
    """Print all strategies in formatted summary tables.

    Args:
        rows: List of StrategyRow data containers.
    """
    if not rows:
        print("\nNo strategies to display.")
        return

    # ========== Table 1: Position Information ==========
    print_section_header("Table 1: Option Position Information")

    # Header
    print(f"\n{'Symbol':<8} {'Type':<5} {'Side':<6} {'Strike':>8} {'Expiry':<10} {'DTE':>4} "
          f"{'Qty':>5} {'Prem':>6} {'IV':>6} {'Und$':>8} {'Strategy':<14}")
    print("-" * 120)

    for r in rows:
        iv_str = f"{r.iv*100:.1f}%" if r.iv else "-"
        qty_str = f"{r.quantity:.1f}" if r.quantity != int(r.quantity) else f"{int(r.quantity)}"
        print(f"{r.underlying:<8} {r.option_type:<5} {r.side:<6} {r.strike:>8.1f} {r.expiry:<10} "
              f"{r.dte if r.dte else '-':>4} {qty_str:>5} {r.premium:>6.2f} {iv_str:>6} "
              f"{r.underlying_price:>8.2f} {r.strategy_type:<14}")

    # ========== Table 2: Greeks ==========
    print_section_header("Table 2: Greeks")

    print(f"\n{'Symbol':<8} {'Type':<5} {'Strike':>8} {'Delta':>8} {'Gamma':>10} {'Theta':>8} {'Vega':>8} "
          f"{'HV':>6} {'IV':>6} {'IV/HV':>6}")
    print("-" * 120)

    for r in rows:
        delta_str = format_value(r.delta, ".2f") if r.delta else "-"
        gamma_str = format_value(r.gamma, ".2f") if r.gamma else "-"
        theta_str = format_value(r.theta, ".2f") if r.theta else "-"
        vega_str = format_value(r.vega, ".2f") if r.vega else "-"
        hv_str = f"{r.hv*100:.1f}%" if r.hv else "-"
        iv_str = f"{r.iv*100:.1f}%" if r.iv else "-"
        iv_hv = f"{r.iv/r.hv:.2f}" if r.iv and r.hv and r.hv > 0 else "-"

        print(f"{r.underlying:<8} {r.option_type:<5} {r.strike:>8.1f} {delta_str:>8} {gamma_str:>10} "
              f"{theta_str:>8} {vega_str:>8} {hv_str:>6} {iv_str:>6} {iv_hv:>6}")

    # ========== Table 3: Core Metrics ==========
    print_section_header("Table 3: Core Metrics")

    print(f"\n{'Symbol':<8} {'Strike':>8} {'Strategy':<14} {'E[Return]':>10} {'MaxProfit':>10} "
          f"{'MaxLoss':>10} {'Breakeven':>10} {'WinProb':>8}")
    print("-" * 120)

    for r in rows:
        be_str = f"{r.breakeven:.2f}" if isinstance(r.breakeven, float) else ",".join([f"{b:.1f}" for b in r.breakeven])
        print(f"{r.underlying:<8} {r.strike:>8.1f} {r.strategy_type:<14} {r.expected_return:>10.2f} "
              f"{r.max_profit:>10.2f} {r.max_loss:>10.2f} {be_str:>10} {r.win_probability:>7.1%}")

    # ========== Table 4: Risk-Adjusted Metrics ==========
    print_section_header("Table 4: Risk-Adjusted & Extended Metrics")

    print(f"\n{'Symbol':<8} {'Strike':>8} {'PREI':>6} {'Risk':>5} {'SAS':>5} {'Attr':>5} "
          f"{'TGR':>6} {'Qual':>4} {'ROC':>7} {'E[ROC]':>7} {'Sharpe':>7} {'Kelly':>7} {'Edge':>6}")
    print("-" * 120)

    for r in rows:
        prei_str = format_value(r.prei, ".1f")
        prei_rating = get_prei_rating(r.prei)
        sas_str = format_value(r.sas, ".1f")
        sas_rating = get_sas_rating(r.sas)
        tgr_str = format_value(r.tgr, ".3f")
        tgr_rating = get_tgr_rating(r.tgr)
        roc_str = f"{r.roc:.1%}" if r.roc is not None else "-"
        eroc_str = f"{r.expected_roc:.1%}" if r.expected_roc is not None else "-"
        sharpe_str = format_value(r.sharpe_ratio, ".3f")
        kelly_str = f"{r.kelly_fraction:.1%}" if r.kelly_fraction is not None else "-"
        kelly_rating = get_kelly_rating(r.kelly_fraction)

        print(f"{r.underlying:<8} {r.strike:>8.1f} {prei_str:>6} {prei_rating:>5} {sas_str:>5} {sas_rating:>5} "
              f"{tgr_str:>6} {tgr_rating:>4} {roc_str:>7} {eroc_str:>7} {sharpe_str:>7} {kelly_str:>7} {kelly_rating:>6}")

    # ========== Table 5: Capital & Margin ==========
    print_section_header("Table 5: Capital & Margin")

    print(f"\n{'Symbol':<8} {'Strike':>8} {'Strategy':<14} {'Margin':>10} {'Capital@Risk':>12} "
          f"{'ReturnStd':>10} {'Margin/Cap':>10}")
    print("-" * 120)

    for r in rows:
        margin_str = f"${r.margin:.2f}" if r.margin else "-"
        car_str = f"${r.capital_at_risk:.2f}" if r.capital_at_risk else "-"
        margin_ratio = f"{r.margin/r.capital_at_risk:.1%}" if r.margin and r.capital_at_risk and r.capital_at_risk > 0 else "-"

        print(f"{r.underlying:<8} {r.strike:>8.1f} {r.strategy_type:<14} {margin_str:>10} {car_str:>12} "
              f"${r.return_std:>9.2f} {margin_ratio:>10}")


def print_strategy_metrics_detail(
    position: AccountPosition, strategy_type: str, metrics: StrategyMetrics
) -> None:
    """Print strategy metrics in detailed format (legacy, for verbose mode).

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
    portfolio: ConsolidatedPortfolio,
    ibkr_provider: IBKRProvider | None,
    futu_provider: FutuProvider | None = None,
    verbose: bool = False,
) -> None:
    """Verify Position-level strategy metrics for all option positions.

    Args:
        portfolio: Consolidated portfolio with all positions.
        ibkr_provider: IBKR provider for volatility data.
        futu_provider: Futu provider for fallback HK stock quotes.
        verbose: If True, print detailed debug info for each strategy.
    """
    print_section_header("Position-Level Strategy Metrics Verification")

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

    # Collect all strategy data for table output
    strategy_rows: list[StrategyRow] = []

    for pos in option_positions:
        total_positions += 1

        # Step 1: Create strategy instance(s) using factory
        strategy_instances = create_strategies_from_position(
            position=pos,
            all_positions=portfolio.positions,
            ibkr_provider=ibkr_provider,
            futu_provider=futu_provider,
        )

        if not strategy_instances:
            logger.info(f"Skipping {pos.symbol}: no strategies created")
            skipped_positions += 1
            continue

        # Step 2: Process each strategy instance
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
            else:
                logger.info(f"{pos.symbol}: {desc}")

            # Verbose: Print debug info
            if verbose:
                print_strategy_debug_info(strategy, pos)

            # Step 3: Calculate margin
            margin = None
            capital_at_risk = None
            try:
                margin_per_contract = strategy.calc_margin_requirement()
                capital_at_risk = strategy._calc_capital_at_risk()
                margin = margin_per_contract * ratio
            except Exception as e:
                logger.warning(f"{pos.symbol}: Could not calculate margin: {e}")

            # Step 4: Calculate metrics
            try:
                metrics = strategy.calc_metrics()
                verified_positions += 1
            except Exception as e:
                print(f"\n{pos.symbol}: Error calculating metrics: {e}")
                logger.exception(f"Error calculating metrics for {pos.symbol}")
                skipped_positions += 1
                continue

            # Verbose: Print detailed metrics
            if verbose:
                print_strategy_metrics_detail(pos, strategy_type, metrics)

            # Step 5: Collect data for table
            dte = calc_dte_from_expiry(pos.expiry)
            premium_per_share = abs(pos.market_value / (pos.quantity * pos.contract_multiplier))

            # Determine side from strategy leg
            side = "SHORT" if strategy.leg and strategy.leg.side == PositionSide.SHORT else "LONG"

            row = StrategyRow(
                symbol=pos.symbol,
                underlying=pos.underlying or pos.symbol,
                option_type=pos.option_type.upper() if pos.option_type else "-",
                side=side,
                strike=pos.strike,
                expiry=pos.expiry,
                dte=dte,
                quantity=ratio * abs(pos.quantity),  # Use ratio for partial coverage
                premium=premium_per_share,
                iv=pos.iv,
                underlying_price=pos.underlying_price,
                strategy_type=strategy_type,
                delta=strategy.leg.delta if strategy.leg else None,
                gamma=strategy.leg.gamma if strategy.leg else None,
                theta=strategy.leg.theta if strategy.leg else None,
                vega=strategy.leg.vega if strategy.leg else None,
                hv=strategy.params.hv,
                spot_price=strategy.params.spot_price,
                margin=margin,
                capital_at_risk=capital_at_risk,
                expected_return=metrics.expected_return,
                max_profit=metrics.max_profit,
                max_loss=metrics.max_loss,
                breakeven=metrics.breakeven,
                win_probability=metrics.win_probability,
                return_std=metrics.return_std,
                sharpe_ratio=metrics.sharpe_ratio,
                kelly_fraction=metrics.kelly_fraction,
                prei=metrics.prei,
                sas=metrics.sas,
                tgr=metrics.tgr,
                roc=metrics.roc,
                expected_roc=metrics.expected_roc,
            )
            strategy_rows.append(row)

    # Print summary tables
    print_summary_tables(strategy_rows)

    # Summary Statistics
    print_section_header("Verification Summary")
    print(f"\nTotal Option Positions: {total_positions}")
    print(f"Successfully Verified: {verified_positions}")
    print(f"Skipped: {skipped_positions}")
    print("\nStrategy Type Distribution:")
    for stype, count in sorted(strategy_counts.items()):
        print(f"  {stype}: {count}")

    # Quick Reference Legend
    print("\n" + "-" * 60)
    print("Rating Legend:")
    print("  PREI Risk: Low(<20) | Med(20-40) | High(40-60) | VHigh(>60)")
    print("  SAS Attr:  Low(<30) | Med(30-50) | Good(50-70) | VGood(>70)")
    print("  TGR Qual:  Low(<0.3) | Med(0.3-0.5) | Good(0.5-0.8) | Exc(>0.8)")
    print("  Kelly:     None(≤0) | Small(0-10%) | Med(10-20%) | Strong(>20%)")


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
        help="Enable verbose/debug output with detailed info per strategy",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    account_type = AccountType.PAPER if args.account_type == "paper" else AccountType.REAL

    print("\n" + "=" * 120)
    print("  Position-Level Strategy Verification")
    print(f"  Account Type: {account_type.value.upper()}")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Verbose Mode: {'ON' if args.verbose else 'OFF'}")
    print("=" * 120)

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
        verify_position_strategies(portfolio, ibkr, futu_provider=futu, verbose=args.verbose)

        print("\n" + "=" * 120)
        print("  Verification Complete")
        print("=" * 120 + "\n")

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
