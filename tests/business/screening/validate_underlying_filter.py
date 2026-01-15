#!/usr/bin/env python3
"""Validation script for UnderlyingFilter - US and HK markets.

This script validates:
1. IV Rank and IV/HV ratio
2. Technical indicators (RSI, ADX, SMA alignment)
3. Fundamental data (optional)
4. Event calendar (earnings, ex-dividend)

Usage:
    python tests/business/screening/validate_underlying_filter.py

    # US market only
    python tests/business/screening/validate_underlying_filter.py --market us

    # HK market only
    python tests/business/screening/validate_underlying_filter.py --market hk

    # Single symbol
    python tests/business/screening/validate_underlying_filter.py --symbol NVDA
"""

import argparse
import os
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from pathlib import Path

import yaml

from src.business.config.screening_config import ScreeningConfig
from src.business.screening.filters.underlying_filter import UnderlyingFilter
from src.business.screening.models import (
    FundamentalScore,
    MarketType,
    TechnicalScore,
    UnderlyingScore,
)
from src.data.providers.unified_provider import UnifiedDataProvider


def print_header(title: str, char: str = "=") -> None:
    """Print section header."""
    width = 70
    print()
    print(char * width)
    print(f"  {title}")
    print(char * width)


def print_subheader(title: str) -> None:
    """Print subsection header."""
    print()
    print(f"--- {title} ---")


def status_icon(passed: bool) -> str:
    """Return icon for pass/fail status."""
    return "[PASS]" if passed else "[FAIL]"


def format_value(value, fmt: str = ".2f", suffix: str = "") -> str:
    """Format a value or return N/A if None."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:{fmt}}{suffix}"
    return str(value)


def load_stock_pools() -> dict:
    """Load stock pools from YAML config."""
    config_path = Path(__file__).parent.parent.parent.parent / "config" / "screening" / "stock_pools.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_symbols_for_market(market: str) -> list[str]:
    """Get symbol list for a market."""
    pools = load_stock_pools()

    if market == "us":
        us_pools = pools.get("us_pools", {})
        default_pool = pools.get("defaults", {}).get("us", "us_default")
        return us_pools.get(default_pool, {}).get("symbols", [])
    elif market == "hk":
        hk_pools = pools.get("hk_pools", {})
        default_pool = pools.get("defaults", {}).get("hk", "hk_default")
        return hk_pools.get(default_pool, {}).get("symbols", [])

    return []


def format_percent(value: float | None) -> str:
    """Format a decimal value as percentage (0.21 -> '21.0%')."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def print_volatility_data(score: UnderlyingScore, config: ScreeningConfig) -> None:
    """Print volatility data details."""
    uf_config = config.underlying_filter

    print(f"  Current Price:    {format_value(score.current_price, '.2f')}")
    print()
    print(f"  IV Rank:          {format_value(score.iv_rank, '.1f', '%')}")
    print(f"  Min IV Rank:      {uf_config.min_iv_rank:.1f}%")

    iv_rank_pass = score.iv_rank is not None and score.iv_rank >= uf_config.min_iv_rank
    print(f"  IV Rank Status:   {status_icon(iv_rank_pass)}")

    print()
    # IV 和 HV 是小数形式 (0.21 = 21%)，需要乘以 100 显示
    print(f"  Current IV:       {format_percent(score.current_iv)}")
    print(f"  HV (20-day):      {format_percent(score.hv_20)}")
    print(f"  IV/HV Ratio:      {format_value(score.iv_hv_ratio, '.2f')}")
    print(f"  IV/HV Range:      [{uf_config.min_iv_hv_ratio}, {uf_config.max_iv_hv_ratio}]")

    iv_hv_pass = (
        score.iv_hv_ratio is not None
        and uf_config.min_iv_hv_ratio <= score.iv_hv_ratio <= uf_config.max_iv_hv_ratio
    )
    print(f"  IV/HV Status:     {status_icon(iv_hv_pass)}")


def rsi_zone_icon(zone: str) -> str:
    """Return icon for RSI zone."""
    icons = {
        "oversold": "[<<]",
        "stabilizing": "[< ]",
        "neutral": "[==]",
        "exhausting": "[ >]",
        "overbought": "[>>]",
    }
    return icons.get(zone, "[??]")


def sma_alignment_icon(alignment: str) -> str:
    """Return icon for SMA alignment."""
    icons = {
        "strong_bullish": "[++]",
        "bullish": "[+ ]",
        "neutral": "[= ]",
        "bearish": "[- ]",
        "strong_bearish": "[--]",
        "mixed": "[~~]",
    }
    return icons.get(alignment, "[??]")


def print_technical_data(technical: TechnicalScore | None, config: ScreeningConfig) -> None:
    """Print technical indicator details."""
    tech_config = config.underlying_filter.technical

    if technical is None:
        print("  Status:           N/A (data unavailable)")
        return

    # RSI
    print(f"  RSI:              {format_value(technical.rsi, '.1f')}")
    print(f"  RSI Zone:         {rsi_zone_icon(technical.rsi_zone)} {technical.rsi_zone}")
    print(f"  RSI Range:        [{tech_config.min_rsi}, {tech_config.max_rsi}]")

    rsi_pass = (
        technical.rsi is None
        or (tech_config.min_rsi <= technical.rsi <= tech_config.max_rsi)
    )
    print(f"  RSI Status:       {status_icon(rsi_pass)}")

    print()

    # ADX
    print(f"  ADX:              {format_value(technical.adx, '.1f')}")
    print(f"  Max ADX:          {tech_config.max_adx}")

    adx_pass = technical.adx is None or technical.adx <= tech_config.max_adx
    print(f"  ADX Status:       {status_icon(adx_pass)}")

    print()

    # Bollinger Bands
    print(f"  BB %B:            {format_value(technical.bb_percent_b, '.2f')}")
    print(f"  BB %B Range:      {tech_config.bb_percent_b_range}")

    print()

    # SMA Alignment
    print(f"  SMA Alignment:    {sma_alignment_icon(technical.sma_alignment or 'neutral')} {technical.sma_alignment}")
    print(f"  Min Alignment:    {tech_config.min_sma_alignment}")

    print()

    # Support Distance
    if technical.support_distance is not None:
        print(f"  Support Distance: {technical.support_distance:.1f}%")


def print_fundamental_data(fundamental: FundamentalScore | None, config: ScreeningConfig) -> None:
    """Print fundamental data details."""
    fund_config = config.underlying_filter.fundamental

    if not fund_config.enabled:
        print("  Status:           Disabled (fundamental.enabled=False)")
        return

    if fundamental is None:
        print("  Status:           N/A (data unavailable)")
        return

    print(f"  PE Ratio:         {format_value(fundamental.pe_ratio, '.1f')}")
    print(f"  PE Percentile:    {format_value(fundamental.pe_percentile, '.1%')}")
    print(f"  Max PE Pct:       {fund_config.max_pe_percentile:.0%}")

    pe_pass = (
        fundamental.pe_percentile is None
        or fundamental.pe_percentile <= fund_config.max_pe_percentile
    )
    print(f"  PE Status:        {status_icon(pe_pass)}")

    print()

    print(f"  Revenue Growth:   {format_value(fundamental.revenue_growth, '.1%')}")
    print(f"  Recommendation:   {fundamental.recommendation or 'N/A'}")
    print(f"  Min Recommendation: {fund_config.min_recommendation}")

    print()

    print(f"  Fund Score:       {fundamental.score:.1f}/100")


def print_event_calendar(score: UnderlyingScore, config: ScreeningConfig) -> None:
    """Print event calendar details."""
    event_config = config.underlying_filter.event_calendar

    if not event_config.enabled:
        print("  Status:           Disabled (event_calendar.enabled=False)")
        return

    today = date.today()

    # Earnings
    if score.earnings_date:
        days = score.days_to_earnings
        if days is not None:
            icon = "[WARN]" if days < event_config.min_days_to_earnings else "[OK  ]"
            print(f"  Earnings Date:    {score.earnings_date} ({icon} {days} days)")
        else:
            print(f"  Earnings Date:    {score.earnings_date} (past)")
    else:
        print(f"  Earnings Date:    N/A")

    print(f"  Min Days (Earn):  {event_config.min_days_to_earnings}")

    print()

    # Ex-dividend
    if score.ex_dividend_date:
        days = score.days_to_ex_dividend
        if days is not None:
            icon = "[WARN]" if days < event_config.min_days_to_ex_dividend else "[OK  ]"
            print(f"  Ex-Div Date:      {score.ex_dividend_date} ({icon} {days} days)")
        else:
            print(f"  Ex-Div Date:      {score.ex_dividend_date} (past)")
    else:
        print(f"  Ex-Div Date:      N/A")

    print(f"  Min Days (ExDiv): {event_config.min_days_to_ex_dividend}")


def print_underlying_summary(score: UnderlyingScore) -> None:
    """Print underlying summary."""
    print()
    print("-" * 50)

    if score.passed:
        print(f"  Result:           {status_icon(True)} PASSED - Ready for contract screening")
    else:
        print(f"  Result:           {status_icon(False)} FAILED - Disqualified")

    if score.disqualify_reasons:
        print()
        print("  Disqualify Reasons (P0/P1 - Blocking):")
        for reason in score.disqualify_reasons:
            print(f"    - {reason}")

    if score.warnings:
        print()
        print("  Warnings (P2/P3 - Non-blocking):")
        for warning in score.warnings:
            print(f"    - {warning}")

    print()
    print(f"  Composite Score:  {score.composite_score:.1f}/100")
    print(f"  Timestamp:        {score.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")


def validate_underlying(
    symbol: str,
    market_type: MarketType,
    config: ScreeningConfig,
    underlying_filter: UnderlyingFilter,
) -> UnderlyingScore:
    """Validate a single underlying and print details."""
    print_header(f"UNDERLYING VALIDATION - {symbol}")

    # Evaluate
    score = underlying_filter.evaluate_single(symbol, market_type)

    # 1. Volatility Data
    print_subheader("1. Volatility Data")
    print_volatility_data(score, config)

    # 2. Technical Indicators
    print_subheader("2. Technical Indicators")
    print_technical_data(score.technical, config)

    # 3. Fundamental Data
    print_subheader("3. Fundamental Data")
    print_fundamental_data(score.fundamental, config)

    # 4. Event Calendar
    print_subheader("4. Event Calendar")
    print_event_calendar(score, config)

    # Summary
    print_underlying_summary(score)

    return score


def main():
    """Run underlying filter validation."""
    parser = argparse.ArgumentParser(description="Validate UnderlyingFilter for US and HK markets")
    parser.add_argument(
        "--market",
        choices=["us", "hk", "both"],
        default="both",
        help="Market to validate (default: both)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Validate specific symbol only"
    )
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  UNDERLYING FILTER VALIDATION")
    print(f"  Date: {date.today()}")
    print("=" * 70)

    # Load config
    config = ScreeningConfig()
    provider = UnifiedDataProvider()
    underlying_filter = UnderlyingFilter(config, provider)

    results: dict[str, list[UnderlyingScore]] = {"US": [], "HK": []}

    # Single symbol mode
    if args.symbol:
        symbol = args.symbol.upper()
        # Detect market type
        if symbol.endswith(".HK"):
            market_type = MarketType.HK
            market_key = "HK"
        else:
            market_type = MarketType.US
            market_key = "US"

        score = validate_underlying(symbol, market_type, config, underlying_filter)
        results[market_key].append(score)
    else:
        # Validate US market
        if args.market in ["us", "both"]:
            us_symbols = get_symbols_for_market("us")
            print_header(f"US MARKET - {len(us_symbols)} symbols")

            for symbol in us_symbols:
                try:
                    score = validate_underlying(symbol, MarketType.US, config, underlying_filter)
                    results["US"].append(score)
                except Exception as e:
                    print(f"\n[ERROR] Validation failed for {symbol}: {e}")
                    import traceback
                    traceback.print_exc()

        # Validate HK market
        if args.market in ["hk", "both"]:
            hk_symbols = get_symbols_for_market("hk")
            print_header(f"HK MARKET - {len(hk_symbols)} symbols")

            for symbol in hk_symbols:
                try:
                    score = validate_underlying(symbol, MarketType.HK, config, underlying_filter)
                    results["HK"].append(score)
                except Exception as e:
                    print(f"\n[ERROR] Validation failed for {symbol}: {e}")
                    import traceback
                    traceback.print_exc()

    # Final summary
    print_header("FINAL SUMMARY")

    for market, scores in results.items():
        if not scores:
            continue

        passed = sum(1 for s in scores if s.passed)
        total = len(scores)

        print(f"\n  {market} Market:")
        print(f"    Total:   {total}")
        print(f"    Passed:  {passed}")
        print(f"    Failed:  {total - passed}")

        if passed > 0:
            print(f"    Passed Symbols: {', '.join(s.symbol for s in scores if s.passed)}")

        if total - passed > 0:
            failed_reasons: dict[str, list[str]] = {}
            for s in scores:
                if not s.passed:
                    failed_reasons[s.symbol] = s.disqualify_reasons

            print(f"    Failed Details (P0/P1):")
            for symbol, reasons in failed_reasons.items():
                print(f"      {symbol}:")
                for reason in reasons:
                    print(f"        - {reason}")

        # Show warnings for passed symbols
        passed_with_warnings = [(s.symbol, s.warnings) for s in scores if s.passed and s.warnings]
        if passed_with_warnings:
            print(f"    Passed with Warnings (P2/P3):")
            for symbol, warnings_list in passed_with_warnings:
                print(f"      {symbol}:")
                for warning in warnings_list:
                    print(f"        - {warning}")

    print()
    print("=" * 70)
    print("  Validation Complete")
    print("=" * 70)

    # Return exit code
    all_passed = all(s.passed for scores in results.values() for s in scores)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
