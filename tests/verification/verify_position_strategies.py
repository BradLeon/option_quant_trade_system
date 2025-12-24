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
from src.engine.strategy.covered_call import CoveredCallStrategy
from src.engine.strategy.short_put import ShortPutStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Strategy Classification
# ============================================================================


def classify_option_strategy(
    position: AccountPosition, all_positions: list[AccountPosition]
) -> str:
    """Classify option strategy type based on position characteristics.

    Args:
        position: Option position to classify.
        all_positions: All positions in the portfolio (for checking stock holdings).

    Returns:
        Strategy type: "short_put", "covered_call", "naked_call", "long_call",
        "long_put", "not_option", or "unknown".
    """
    if position.asset_type != AssetType.OPTION:
        return "not_option"

    # Short Put: PUT + quantity < 0 (sold)
    if position.option_type == "put" and position.quantity < 0:
        return "short_put"

    # Covered Call / Naked Call: CALL + quantity < 0 (sold)
    if position.option_type == "call" and position.quantity < 0:
        # Check if we have the underlying stock
        underlying_symbol = position.underlying or position.symbol
        # Normalize symbol for matching (e.g., "9988" from "HK.09988")
        underlying_symbol = normalize_symbol(underlying_symbol)

        has_stock = any(
            p.asset_type == AssetType.STOCK
            and normalize_symbol(p.symbol) == underlying_symbol
            and p.quantity > 0
            for p in all_positions
        )

        if has_stock:
            return "covered_call"
        else:
            return "naked_call"

    # Long Call: CALL + quantity > 0 (bought)
    if position.option_type == "call" and position.quantity > 0:
        return "long_call"

    # Long Put: PUT + quantity > 0 (bought)
    if position.option_type == "put" and position.quantity > 0:
        return "long_put"

    return "unknown"


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol for matching across brokers.

    Examples:
        "HK.09988" -> "9988"
        "9988.HK" -> "9988"
        "AAPL" -> "AAPL"
    """
    # Remove HK prefix/suffix
    symbol = symbol.replace("HK.", "").replace(".HK", "")
    # Remove leading zeros for HK stocks
    if symbol.isdigit():
        symbol = str(int(symbol))
    return symbol


# ============================================================================
# Data Model Builders
# ============================================================================


def calc_dte_from_expiry(expiry_str: str) -> int | None:
    """Calculate days to expiry from YYYYMMDD format.

    Args:
        expiry_str: Expiry date in YYYYMMDD format (e.g., "20250117").

    Returns:
        Days to expiry (non-negative), or None if parsing fails.
    """
    if not expiry_str:
        return None
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
        dte = (expiry_date - datetime.now()).days
        return max(0, dte)  # Cannot be negative
    except ValueError:
        return None


def build_option_leg(ap: AccountPosition) -> OptionLeg:
    """Build OptionLeg data model from AccountPosition.

    Args:
        ap: AccountPosition with option data.

    Returns:
        OptionLeg with option_type, side, strike, premium, greeks.
    """
    # Determine side: quantity < 0 = SHORT (sold), > 0 = LONG (bought)
    side = PositionSide.SHORT if ap.quantity < 0 else PositionSide.LONG

    # Calculate premium per share
    # market_value is total value, need to divide by (quantity * multiplier)
    premium = abs(ap.market_value / (ap.quantity * ap.contract_multiplier))

    # Build Greeks
    greeks = Greeks(
        delta=ap.delta,
        gamma=ap.gamma,
        theta=ap.theta,
        vega=ap.vega,
    )

    return OptionLeg(
        option_type=OptionType.CALL if ap.option_type == "call" else OptionType.PUT,
        side=side,
        strike=ap.strike,
        premium=premium,
        greeks=greeks,
    )


def build_strategy_params(
    ap: AccountPosition, hv: float | None = None
) -> StrategyParams:
    """Build StrategyParams data model from AccountPosition.

    Args:
        ap: AccountPosition with option data.
        hv: Historical volatility (from StockVolatility), optional.

    Returns:
        StrategyParams with spot_price, volatility, time_to_expiry, hv, dte.
    """
    dte_days = calc_dte_from_expiry(ap.expiry)
    time_to_expiry = dte_days / 365.0 if dte_days else 0.01  # Minimum 0.01 years

    return StrategyParams(
        spot_price=ap.underlying_price,
        volatility=ap.iv,
        time_to_expiry=time_to_expiry,
        risk_free_rate=0.03,
        hv=hv,
        dte=dte_days,
    )


def get_volatility_data(
    symbol: str, provider: IBKRProvider | None
) -> StockVolatility | None:
    """Get stock volatility data (IV + HV) from provider.

    Args:
        symbol: Stock symbol (normalized).
        provider: IBKR provider instance (has get_stock_volatility method).

    Returns:
        StockVolatility model with iv, hv, iv_rank, iv_percentile, pcr.
        Returns None if provider unavailable or data fetch fails.
    """
    if provider is None:
        return None

    try:
        volatility = provider.get_stock_volatility(symbol)
        return volatility
    except Exception as e:
        logger.warning(f"Failed to get volatility for {symbol}: {e}")
        return None


# ============================================================================
# Strategy Creation
# ============================================================================


def create_strategy_from_position(
    position: AccountPosition,
    strategy_type: str,
    all_positions: list[AccountPosition],
    ibkr_provider: IBKRProvider | None,
) -> ShortPutStrategy | CoveredCallStrategy | None:
    """Create Strategy object from AccountPosition.

    Builds complete data pipeline:
      AccountPosition → StockVolatility → OptionLeg + StrategyParams → Strategy

    Args:
        position: Option position.
        strategy_type: Strategy classification ("short_put", "covered_call", etc.).
        all_positions: All positions (for covered call stock lookup).
        ibkr_provider: IBKR provider for volatility data.

    Returns:
        Strategy instance, or None if required data is missing.
    """
    # Validate required fields - but try to fetch underlying_price if missing
    if not position.strike or not position.iv:
        logger.warning(
            f"{position.symbol}: Missing required data "
            f"(strike={position.strike}, iv={position.iv})"
        )
        return None

    # If underlying_price is missing, try to fetch it
    if not position.underlying_price:
        underlying_symbol = position.underlying or position.symbol

        # Convert HK stocks to .HK format if needed
        if underlying_symbol.startswith("HK."):
            code = underlying_symbol[3:].lstrip("0") or "0"
            underlying_symbol = f"{int(code):04d}.HK"
        elif underlying_symbol.isdigit():
            underlying_symbol = f"{int(underlying_symbol):04d}.HK"

        try:
            if ibkr_provider:
                stock_quote = ibkr_provider.get_stock_quote(underlying_symbol)
                if stock_quote and stock_quote.close:
                    position.underlying_price = stock_quote.close
                    logger.info(f"Fetched missing underlying_price for {position.symbol}: {position.underlying_price}")
        except Exception as e:
            logger.warning(f"Could not fetch underlying price for {position.symbol}: {e}")

        if not position.underlying_price:
            logger.warning(
                f"{position.symbol}: Missing underlying_price and could not fetch it"
            )
            return None

    # Step 1: Get volatility data (StockVolatility model)
    # Don't normalize - keep original format with .HK suffix for IBKR provider
    underlying_symbol = position.underlying or position.symbol

    # Convert HK stocks to .HK format if needed
    if underlying_symbol.startswith("HK."):
        # Futu format: HK.00700 -> 0700.HK
        code = underlying_symbol[3:].lstrip("0") or "0"
        underlying_symbol = f"{int(code):04d}.HK"
    elif underlying_symbol.isdigit():
        # IBKR format: "700" -> 0700.HK
        underlying_symbol = f"{int(underlying_symbol):04d}.HK"

    volatility_data = get_volatility_data(underlying_symbol, ibkr_provider)
    hv = volatility_data.hv if volatility_data else None

    # Step 2: Build OptionLeg
    try:
        leg = build_option_leg(position)
    except Exception as e:
        logger.warning(f"{position.symbol}: Failed to build OptionLeg: {e}")
        return None

    # Step 3: Build StrategyParams
    try:
        params = build_strategy_params(position, hv=hv)
    except Exception as e:
        logger.warning(f"{position.symbol}: Failed to build StrategyParams: {e}")
        return None

    # Step 4: Create Strategy instance
    if strategy_type == "short_put":
        return ShortPutStrategy(
            spot_price=params.spot_price,
            strike_price=leg.strike,
            premium=leg.premium,
            volatility=params.volatility,
            time_to_expiry=params.time_to_expiry,
            risk_free_rate=params.risk_free_rate,
            hv=params.hv,
            dte=params.dte,
            delta=leg.delta,
            gamma=leg.gamma,
            theta=leg.theta,
            vega=leg.vega,
        )
    elif strategy_type == "covered_call":
        # Find stock position for cost basis
        underlying_symbol = normalize_symbol(position.underlying or position.symbol)
        stock_position = next(
            (
                p
                for p in all_positions
                if p.asset_type == AssetType.STOCK
                and normalize_symbol(p.symbol) == underlying_symbol
            ),
            None,
        )

        if stock_position is None:
            logger.warning(
                f"{position.symbol}: Covered call without stock position (should not happen)"
            )
            return None

        stock_cost_basis = stock_position.avg_cost

        return CoveredCallStrategy(
            spot_price=params.spot_price,
            strike_price=leg.strike,
            premium=leg.premium,
            stock_cost_basis=stock_cost_basis,
            volatility=params.volatility,
            time_to_expiry=params.time_to_expiry,
            risk_free_rate=params.risk_free_rate,
            hv=params.hv,
            dte=params.dte,
            delta=leg.delta,
            gamma=leg.gamma,
            theta=leg.theta,
            vega=leg.vega,
        )

    # Other strategy types not yet implemented
    return None


# ============================================================================
# Output Formatting
# ============================================================================


def print_section_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


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

    print(f"\n[Position: {position.symbol} {position.option_type.upper()} "
          f"{position.strike:.1f} {position.expiry}]")
    print(f"Strategy Type: {strategy_type}")
    print(f"Symbol: {position.symbol}")
    print(f"Strike: ${position.strike:.2f}")
    print(f"Expiry: {position.expiry} ({dte_str})")
    print(f"Premium: ${abs(position.market_value / position.quantity):.2f}")
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

        # Step 1: Classify strategy
        strategy_type = classify_option_strategy(pos, portfolio.positions)

        if strategy_type in ("not_option", "unknown", "naked_call", "long_call", "long_put"):
            logger.info(f"Skipping {pos.symbol}: strategy_type={strategy_type}")
            skipped_positions += 1
            continue

        # Track strategy types
        strategy_counts[strategy_type] = strategy_counts.get(strategy_type, 0) + 1

        # Step 2: Create strategy and calculate metrics
        strategy = create_strategy_from_position(
            pos, strategy_type, portfolio.positions, ibkr_provider
        )

        if strategy is None:
            print(f"\n{pos.symbol}: Unable to create strategy (missing data)")
            skipped_positions += 1
            continue

        # Step 3: Calculate metrics
        try:
            metrics = strategy.calc_metrics()
            verified_positions += 1
        except Exception as e:
            print(f"\n{pos.symbol}: Error calculating metrics: {e}")
            logger.exception(f"Error calculating metrics for {pos.symbol}")
            skipped_positions += 1
            continue

        # Step 4: Print results
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
