#!/usr/bin/env python3
"""Stock Position Verification Script.

Verifies and displays comprehensive data for stock positions in the account.
Displays 5 tables:
1. Market Data (Qty, Price, Cost, Value, PnL)
2. Fundamental Analysis (FundamentalScore)
3. Volatility Analysis (VolatilityScore)
4. Technical Analysis (TechnicalScore)
5. Technical Signals (TechnicalSignal)

Usage:
    python tests/verification/verify_position_stocks.py
    python tests/verification/verify_position_stocks.py --account-type paper
    python tests/verification/verify_position_stocks.py --ibkr-only
    python tests/verification/verify_position_stocks.py -v  # verbose mode
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
from src.data.models.technical import TechnicalData
from src.data.providers import IBKRProvider, FutuProvider
from src.data.providers.account_aggregator import AccountAggregator
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.models.enums import RatingSignal, TrendSignal
from src.engine.models.result import (
    FundamentalScore,
    VolatilityScore,
    TechnicalScore,
    TechnicalSignal,
)
from src.engine.position.fundamental.metrics import evaluate_fundamentals
from src.engine.position.volatility.metrics import evaluate_volatility
from src.engine.position.technical.metrics import calc_technical_score, calc_technical_signal

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
class StockRow:
    """Container for all stock data to be displayed in tables."""

    # Position Info
    symbol: str
    quantity: float
    current_price: float
    cost_price: float
    market_value_usd: float  # Converted to USD

    # PnL
    daily_pnl_pct: Optional[float]
    daily_pnl_usd: Optional[float]
    unrealized_pnl_pct: Optional[float]
    unrealized_pnl_usd: Optional[float]
    realized_pnl_pct: Optional[float]
    realized_pnl_usd: Optional[float]

    # Fundamental Score
    fund_score: Optional[float]
    fund_rating: Optional[RatingSignal]
    pe_score: Optional[float]
    growth_score: Optional[float]
    margin_score: Optional[float]

    # Volatility Score
    vol_score: Optional[float]
    vol_rating: Optional[RatingSignal]
    iv_rank: Optional[float]
    iv_hv_ratio: Optional[float]
    iv_percentile: Optional[float]

    # Technical Score
    trend_signal: Optional[TrendSignal]
    ma_alignment: Optional[str]
    rsi: Optional[float]
    rsi_zone: Optional[str]
    adx: Optional[float]
    support: Optional[float]
    resistance: Optional[float]

    # Technical Signal
    market_regime: Optional[str]
    trend_strength: Optional[str]
    sell_put_signal: Optional[str]
    sell_call_signal: Optional[str]
    is_dangerous_period: Optional[bool]


# ============================================================================
# Output Formatting
# ============================================================================


def print_section_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 120)
    print(f"  {title}")
    print("=" * 120)


def format_value(val, fmt: str = ".2f", suffix: str = "") -> str:
    """Format a value for table display."""
    if val is None:
        return "-"
    if fmt == ".0%":
        return f"{val:.0%}"
    if fmt == ".1%":
        return f"{val:.1%}"
    if fmt == ".2%":
        return f"{val:.2%}"
    if fmt == ".1f":
        return f"{val:.1f}{suffix}"
    if fmt == ".2f":
        return f"{val:.2f}{suffix}"
    return str(val)


def format_rating(rating: Optional[RatingSignal]) -> str:
    """Format rating signal for display."""
    if rating is None:
        return "-"
    rating_map = {
        RatingSignal.STRONG_BUY: "S.BUY",
        RatingSignal.BUY: "BUY",
        RatingSignal.HOLD: "HOLD",
        RatingSignal.SELL: "SELL",
        RatingSignal.STRONG_SELL: "S.SELL",
    }
    return rating_map.get(rating, str(rating.value))


def format_trend(trend: Optional[TrendSignal]) -> str:
    """Format trend signal for display."""
    if trend is None:
        return "-"
    trend_map = {
        TrendSignal.BULLISH: "Bull",
        TrendSignal.BEARISH: "Bear",
        TrendSignal.NEUTRAL: "Neut",
    }
    return trend_map.get(trend, str(trend.value))


def print_summary_tables(rows: list[StockRow]) -> None:
    """Print all stock data in formatted summary tables.

    Args:
        rows: List of StockRow data containers.
    """
    if not rows:
        print("\nNo stock positions to display.")
        return

    # ========== Table 1: Market Data ==========
    print_section_header("Table 1: 持仓行情 (Market Data)")

    print(f"\n{'Symbol':<10} {'Qty':>6} {'现价':>8} {'成本':>8} {'市值(USD)':>10} "
          f"{'今日PnL%':>9} {'今日PnL$':>10} {'未实现PnL%':>9} {'未实现PnL$':>10} {'已实现PnL%':>9} {'已实现PnL$':>10}")
    print("-" * 130)

    for r in rows:
        daily_pnl_pct_str = format_value(r.daily_pnl_pct, ".2%") if r.daily_pnl_pct else "-"
        daily_pnl_usd_str = format_value(r.daily_pnl_usd, ".2f") if r.daily_pnl_usd else "-"
        unrealized_pnl_pct_str = format_value(r.unrealized_pnl_pct, ".2%") if r.unrealized_pnl_pct else "-"
        unrealized_pnl_usd_str = format_value(r.unrealized_pnl_usd, ".2f") if r.unrealized_pnl_usd else "-"
        realized_pnl_pct_str = format_value(r.realized_pnl_pct, ".2%") if r.realized_pnl_pct else "-"
        realized_pnl_usd_str = format_value(r.realized_pnl_usd, ".2f") if r.realized_pnl_usd else "-"

        print(f"{r.symbol:<10} {r.quantity:>6.0f} {r.current_price:>8.2f} {r.cost_price:>8.2f} "
              f"{r.market_value_usd:>10.2f} {daily_pnl_pct_str:>9} {daily_pnl_usd_str:>10} "
              f"{unrealized_pnl_pct_str:>9} {unrealized_pnl_usd_str:>10} {realized_pnl_pct_str:>9} {realized_pnl_usd_str:>10}")

    # ========== Table 2: Fundamental Analysis ==========
    print_section_header("Table 2: 基本面分析 (Fundamental Score)")

    print(f"\n{'Symbol':<8} {'Score':>8} {'Rating':>8} {'PE评分':>8} {'增长评分':>8} {'利润率评分':>10}")
    print("-" * 120)

    for r in rows:
        score_str = format_value(r.fund_score, ".1f")
        rating_str = format_rating(r.fund_rating)
        pe_str = format_value(r.pe_score, ".1f")
        growth_str = format_value(r.growth_score, ".1f")
        margin_str = format_value(r.margin_score, ".1f")

        print(f"{r.symbol:<8} {score_str:>8} {rating_str:>8} {pe_str:>8} {growth_str:>8} {margin_str:>10}")

    # ========== Table 3: Volatility Analysis ==========
    print_section_header("Table 3: 波动率分析 (Volatility Score)")

    print(f"\n{'Symbol':<8} {'Score':>8} {'Rating':>8} {'IV Rank':>8} {'IV/HV':>8} {'IV Pctl':>8}")
    print("-" * 120)

    for r in rows:
        score_str = format_value(r.vol_score, ".1f")
        rating_str = format_rating(r.vol_rating)
        iv_rank_str = format_value(r.iv_rank, ".1f")
        iv_hv_str = format_value(r.iv_hv_ratio, ".2f")
        iv_pctl_str = format_value(r.iv_percentile, ".1%") if r.iv_percentile else "-"

        print(f"{r.symbol:<8} {score_str:>8} {rating_str:>8} {iv_rank_str:>8} {iv_hv_str:>8} {iv_pctl_str:>8}")

    # ========== Table 4: Technical Analysis ==========
    print_section_header("Table 4: 技术面分析 (Technical Score)")

    print(f"\n{'Symbol':<8} {'趋势':>6} {'MA对齐':>12} {'RSI':>6} {'RSI区':>8} "
          f"{'ADX':>6} {'支撑':>10} {'阻力':>10}")
    print("-" * 120)

    for r in rows:
        trend_str = format_trend(r.trend_signal)
        ma_str = r.ma_alignment[:10] if r.ma_alignment else "-"
        rsi_str = format_value(r.rsi, ".1f")
        rsi_zone_str = r.rsi_zone[:8] if r.rsi_zone else "-"
        adx_str = format_value(r.adx, ".1f")
        support_str = format_value(r.support, ".2f")
        resistance_str = format_value(r.resistance, ".2f")

        print(f"{r.symbol:<8} {trend_str:>6} {ma_str:>12} {rsi_str:>6} {rsi_zone_str:>8} "
              f"{adx_str:>6} {support_str:>10} {resistance_str:>10}")

    # ========== Table 5: Technical Signals ==========
    print_section_header("Table 5: 技术信号 (Technical Signal)")

    print(f"\n{'Symbol':<8} {'市场状态':>12} {'趋势强度':>10} {'卖Put信号':>10} "
          f"{'卖Call信号':>10} {'危险期':>6}")
    print("-" * 120)

    for r in rows:
        regime_str = r.market_regime[:10] if r.market_regime else "-"
        strength_str = r.trend_strength[:8] if r.trend_strength else "-"
        put_str = r.sell_put_signal[:8] if r.sell_put_signal else "-"
        call_str = r.sell_call_signal[:8] if r.sell_call_signal else "-"
        danger_str = "Yes" if r.is_dangerous_period else "No"

        print(f"{r.symbol:<8} {regime_str:>12} {strength_str:>10} {put_str:>10} "
              f"{call_str:>10} {danger_str:>6}")


# ============================================================================
# Main Verification Function
# ============================================================================


def verify_position_stocks(
    portfolio: ConsolidatedPortfolio,
    unified_provider: UnifiedDataProvider,
    verbose: bool = False,
) -> None:
    """Verify stock position data for all stock holdings.

    Args:
        portfolio: Consolidated portfolio with all positions.
        unified_provider: Unified data provider for fetching additional data.
        verbose: If True, print detailed debug info.
    """
    print_section_header("Stock Position Verification")

    stock_positions = [
        p for p in portfolio.positions if p.asset_type == AssetType.STOCK
    ]

    if not stock_positions:
        print("No stock positions found.")
        return

    print(f"\nFound {len(stock_positions)} stock position(s) to verify.\n")

    # Collect all stock data for table output
    stock_rows: list[StockRow] = []

    for pos in stock_positions:
        symbol = pos.symbol
        logger.info(f"Processing {symbol}...")

        # === 1. Market Data (from AccountPosition) ===
        quantity = pos.quantity
        current_price = pos.market_value / pos.quantity if pos.quantity else 0
        cost_price = pos.avg_cost or 0
        market_value_usd = pos.market_value  # Assume already in USD or convert

        # PnL calculations
        unrealized_pnl_usd = pos.unrealized_pnl
        realized_pnl_usd = pos.realized_pnl
        unrealized_pnl_pct = None
        realized_pnl_pct = None
        if cost_price and quantity:
            cost_basis = cost_price * quantity
            if cost_basis > 0:
                unrealized_pnl_pct = unrealized_pnl_usd / cost_basis if unrealized_pnl_usd else 0
                realized_pnl_pct = realized_pnl_usd / cost_basis if realized_pnl_usd else 0

        # Daily PnL (requires previous close)
        daily_pnl_pct = None
        daily_pnl_usd = None
        # Try to get from quote
        try:
            quote = unified_provider.get_stock_quote(symbol)
            if quote and quote.prev_close and quote.prev_close > 0:
                # Use quote.close (current price in original currency) for consistent comparison
                # Both quote.close and quote.prev_close are in the same currency (HKD for HK, USD for US)
                quote_current = quote.close or 0
                if quote_current > 0:
                    daily_pnl_pct = (quote_current - quote.prev_close) / quote.prev_close
                    daily_pnl_usd = daily_pnl_pct * market_value_usd
        except Exception as e:
            logger.debug(f"Could not get quote for {symbol}: {e}")

        # === 2. Fundamental Data ===
        fund_score_obj: Optional[FundamentalScore] = None
        try:
            fundamental = unified_provider.get_fundamental(symbol)
            if fundamental:
                fund_score_obj = evaluate_fundamentals(fundamental)
                if verbose:
                    print(f"  {symbol} Fundamental: score={fund_score_obj.score:.1f}, "
                          f"rating={fund_score_obj.rating.value}")
        except Exception as e:
            logger.warning(f"Could not get fundamental for {symbol}: {e}")

        # === 3. Volatility Data ===
        vol_score_obj: Optional[VolatilityScore] = None
        try:
            volatility = unified_provider.get_stock_volatility(symbol)
            if volatility:
                vol_score_obj = evaluate_volatility(volatility)
                if verbose:
                    print(f"  {symbol} Volatility: score={vol_score_obj.score:.1f}, "
                          f"iv_rank={vol_score_obj.iv_rank}")
        except Exception as e:
            logger.warning(f"Could not get volatility for {symbol}: {e}")

        # === 4. Technical Data ===
        tech_score_obj: Optional[TechnicalScore] = None
        tech_signal_obj: Optional[TechnicalSignal] = None
        try:
            # Get historical kline data
            klines = unified_provider.get_history_kline(symbol)
            if klines and len(klines) >= 20:
                tech_data = TechnicalData.from_klines(klines)
                tech_score_obj = calc_technical_score(tech_data)
                tech_signal_obj = calc_technical_signal(tech_data)
                if verbose:
                    print(f"  {symbol} Technical: trend={tech_score_obj.trend_signal.value}, "
                          f"rsi={tech_score_obj.rsi:.1f}" if tech_score_obj.rsi else "rsi=N/A")
        except Exception as e:
            logger.warning(f"Could not get technical data for {symbol}: {e}")

        # === Build StockRow ===
        row = StockRow(
            # Position Info
            symbol=symbol,
            quantity=quantity,
            current_price=current_price,
            cost_price=cost_price,
            market_value_usd=market_value_usd,
            # PnL
            daily_pnl_pct=daily_pnl_pct,
            daily_pnl_usd=daily_pnl_usd,
            unrealized_pnl_pct=unrealized_pnl_pct,
            unrealized_pnl_usd=unrealized_pnl_usd,
            realized_pnl_pct=realized_pnl_pct,
            realized_pnl_usd=realized_pnl_usd,
            # Fundamental
            fund_score=fund_score_obj.score if fund_score_obj else None,
            fund_rating=fund_score_obj.rating if fund_score_obj else None,
            pe_score=fund_score_obj.pe_score if fund_score_obj else None,
            growth_score=fund_score_obj.growth_score if fund_score_obj else None,
            margin_score=fund_score_obj.margin_score if fund_score_obj else None,
            # Volatility
            vol_score=vol_score_obj.score if vol_score_obj else None,
            vol_rating=vol_score_obj.rating if vol_score_obj else None,
            iv_rank=vol_score_obj.iv_rank if vol_score_obj else None,
            iv_hv_ratio=vol_score_obj.iv_hv_ratio if vol_score_obj else None,
            iv_percentile=vol_score_obj.iv_percentile if vol_score_obj else None,
            # Technical Score
            trend_signal=tech_score_obj.trend_signal if tech_score_obj else None,
            ma_alignment=tech_score_obj.ma_alignment if tech_score_obj else None,
            rsi=tech_score_obj.rsi if tech_score_obj else None,
            rsi_zone=tech_score_obj.rsi_zone if tech_score_obj else None,
            adx=tech_score_obj.adx if tech_score_obj else None,
            support=tech_score_obj.support if tech_score_obj else None,
            resistance=tech_score_obj.resistance if tech_score_obj else None,
            # Technical Signal
            market_regime=tech_signal_obj.market_regime if tech_signal_obj else None,
            trend_strength=tech_signal_obj.trend_strength if tech_signal_obj else None,
            sell_put_signal=tech_signal_obj.sell_put_signal if tech_signal_obj else None,
            sell_call_signal=tech_signal_obj.sell_call_signal if tech_signal_obj else None,
            is_dangerous_period=tech_signal_obj.is_dangerous_period if tech_signal_obj else None,
        )
        stock_rows.append(row)

    # Print summary tables
    print_summary_tables(stock_rows)

    # Summary Statistics
    print_section_header("Verification Summary")
    print(f"\nTotal Stock Positions: {len(stock_positions)}")
    print(f"Successfully Processed: {len(stock_rows)}")

    # Portfolio totals
    total_value = sum(r.market_value_usd for r in stock_rows)
    total_unrealized_pnl = sum(r.unrealized_pnl_usd or 0 for r in stock_rows)
    total_realized_pnl = sum(r.realized_pnl_usd or 0 for r in stock_rows)
    total_daily_pnl = sum(r.daily_pnl_usd or 0 for r in stock_rows)

    print(f"\nPortfolio Summary:")
    print(f"  Total Market Value: ${total_value:,.2f}")
    print(f"  Unrealized PnL: ${total_unrealized_pnl:,.2f}")
    print(f"  Realized PnL: ${total_realized_pnl:,.2f}")
    print(f"  Total PnL: ${total_unrealized_pnl + total_realized_pnl:,.2f}")
    print(f"  Today's PnL: ${total_daily_pnl:,.2f}")

    # Rating Legend
    print("\n" + "-" * 60)
    print("Rating Legend:")
    print("  Fundamental: S.BUY(>80) | BUY(65-80) | HOLD(45-65) | SELL(30-45) | S.SELL(<30)")
    print("  Volatility: S.BUY(>70) | BUY(55-70) | HOLD(40-55) | SELL(25-40) | S.SELL(<25)")
    print("  Trend: Bull(bullish) | Bear(bearish) | Neut(neutral)")
    print("  Signal: strong | moderate | weak | none")


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Verify stock position data with comprehensive analysis"
    )
    parser.add_argument(
        "--account-type",
        choices=["paper", "real"],
        default="real",
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

    account_type = AccountType.PAPER if args.account_type == "paper" else AccountType.LIVE

    print("\n" + "=" * 120)
    print("  Stock Position Verification")
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

        # Create unified provider for additional data
        unified_provider = UnifiedDataProvider(
            ibkr_provider=ibkr,
            futu_provider=futu,
        )

        # Verify stock positions
        verify_position_stocks(portfolio, unified_provider, verbose=args.verbose)

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
