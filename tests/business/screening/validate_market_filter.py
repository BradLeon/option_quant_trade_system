#!/usr/bin/env python3
"""Validation script for MarketFilter - US and HK markets.

This script validates:
1. VIX status (US) / IV status (HK)
2. Trend indices status (SPY/QQQ for US, 2800.HK/3033.HK for HK)
3. Term structure (US only)
4. Put/Call ratio (US only)
5. Macro events blackout (US only)

Usage:
    python tests/business/screening/validate_market_filter.py

    # US market only
    python tests/business/screening/validate_market_filter.py --market us

    # HK market only
    python tests/business/screening/validate_market_filter.py --market hk
"""

import argparse
import os
import sys
from datetime import date, datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from src.business.config.screening_config import ScreeningConfig
from src.business.screening.filters.market_filter import MarketFilter
from src.business.screening.models import (
    FilterStatus,
    IndexStatus,
    MacroEventStatus,
    MarketStatus,
    MarketType,
    PCRStatus,
    TermStructureStatus,
    TrendStatus,
    VolatilityIndexStatus,
    VolatilityStatus,
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


def status_icon(status: FilterStatus | None) -> str:
    """Return icon for filter status."""
    if status == FilterStatus.FAVORABLE:
        return "[PASS]"
    elif status == FilterStatus.UNFAVORABLE:
        return "[FAIL]"
    elif status == FilterStatus.OPPORTUNITY:
        return "[OPPT]"
    elif status == FilterStatus.NEUTRAL:
        return "[NEUT]"
    else:
        return "[----]"


def trend_icon(trend: TrendStatus) -> str:
    """Return icon for trend status."""
    icons = {
        TrendStatus.STRONG_BULLISH: "[++]",
        TrendStatus.BULLISH: "[+ ]",
        TrendStatus.NEUTRAL: "[= ]",
        TrendStatus.BEARISH: "[- ]",
        TrendStatus.STRONG_BEARISH: "[--]",
    }
    return icons.get(trend, "[??]")


def volatility_icon(status: VolatilityStatus) -> str:
    """Return icon for volatility status."""
    icons = {
        VolatilityStatus.LOW: "[LOW]",
        VolatilityStatus.NORMAL: "[NRM]",
        VolatilityStatus.HIGH: "[HI ]",
        VolatilityStatus.EXTREME: "[EXT]",
    }
    return icons.get(status, "[---]")


def print_volatility_index(vol: VolatilityIndexStatus | None, config_range: tuple, pct_range: tuple) -> None:
    """Print volatility index details."""
    if vol is None:
        print("  Status:           N/A (数据获取失败)")
        return

    print(f"  Symbol:           {vol.symbol}")
    print(f"  Current Value:    {vol.value:.2f}")
    if vol.percentile is not None:
        print(f"  Percentile:       {vol.percentile * 100:.1f}% (365天历史)")
    else:
        print(f"  Percentile:       N/A")
    print(f"  Zone:             {volatility_icon(vol.status)} {vol.status.value.upper()}")
    print(f"  Config Range:     [{config_range[0]}, {config_range[1]}]")
    print(f"  Percentile Range: [{pct_range[0] * 100:.0f}%, {pct_range[1] * 100:.0f}%]")
    print(f"  Filter Status:    {status_icon(vol.filter_status)} {vol.filter_status.value.upper()}")


def print_trend_indices(indices: list[IndexStatus], overall: TrendStatus, required: str) -> None:
    """Print trend indices details."""
    if not indices:
        print("  Status:           N/A (数据获取失败)")
        return

    for idx in indices:
        print(f"  {idx.symbol} (weight={idx.weight}):")
        print(f"    Price:          ${idx.price:,.2f}" if not idx.symbol.endswith(".HK") else f"    Price:          HK${idx.price:,.2f}")
        if idx.sma20:
            print(f"    SMA20:          ${idx.sma20:,.2f}" if not idx.symbol.endswith(".HK") else f"    SMA20:          HK${idx.sma20:,.2f}")
        if idx.sma50:
            print(f"    SMA50:          ${idx.sma50:,.2f}" if not idx.symbol.endswith(".HK") else f"    SMA50:          HK${idx.sma50:,.2f}")
        if idx.sma200:
            print(f"    SMA200:         ${idx.sma200:,.2f}" if not idx.symbol.endswith(".HK") else f"    SMA200:         HK${idx.sma200:,.2f}")
        print(f"    Trend:          {trend_icon(idx.trend)} {idx.trend.value}")

    print()
    print(f"  Overall Trend:    {trend_icon(overall)} {overall.value}")
    print(f"  Required:         {required}")

    # Check pass/fail
    if required == "bullish_or_neutral":
        is_pass = overall not in [TrendStatus.BEARISH, TrendStatus.STRONG_BEARISH]
    elif required == "bullish":
        is_pass = overall in [TrendStatus.BULLISH, TrendStatus.STRONG_BULLISH]
    else:
        is_pass = True

    status = FilterStatus.FAVORABLE if is_pass else FilterStatus.UNFAVORABLE
    print(f"  Filter Status:    {status_icon(status)} {status.value.upper()}")


def print_term_structure(ts: TermStructureStatus | None, threshold: float) -> None:
    """Print term structure details."""
    if ts is None:
        print("  Status:           N/A (数据获取失败)")
        return

    print(f"  VIX:              {ts.vix_value:.2f}")
    print(f"  VIX3M:            {ts.vix3m_value:.2f}")
    print(f"  Ratio:            {ts.ratio:.3f}")
    state = "CONTANGO" if ts.is_contango else "BACKWARDATION"
    print(f"  State:            {state}")
    print(f"  Threshold:        >= {threshold}")
    print(f"  Filter Status:    {status_icon(ts.filter_status)} {ts.filter_status.value.upper()}")


def print_pcr(pcr: PCRStatus | None, config_range: tuple) -> None:
    """Print PCR details."""
    if pcr is None:
        print("  Status:           N/A (数据获取失败)")
        return

    print(f"  Symbol:           {pcr.symbol}")
    print(f"  Current PCR:      {pcr.value:.2f}")
    print(f"  Config Range:     [{config_range[0]}, {config_range[1]}]")
    print(f"  Filter Status:    {status_icon(pcr.filter_status)} {pcr.filter_status.value.upper()} (warning only)")


def print_macro_events(macro: MacroEventStatus | None) -> None:
    """Print macro events details."""
    if macro is None:
        print("  Status:           N/A (检查被禁用或失败)")
        return

    today = date.today()
    print(f"  Blackout Days:    {macro.blackout_days}")
    print(f"  Events Checked:   FOMC, CPI, NFP")

    if macro.is_in_blackout:
        print(f"  Is Blackout:      [WARN] YES")
        print(f"  Upcoming Events:")
        for event in macro.upcoming_events[:5]:
            days = (event.event_date - today).days
            print(f"    - {event.name}: {event.event_date} (+{days} days)")
        status = FilterStatus.UNFAVORABLE
    else:
        print(f"  Is Blackout:      NO")
        # Show next FOMC
        from src.data.providers.economic_calendar_provider import EconomicCalendarProvider
        provider = EconomicCalendarProvider()
        next_fomc = provider.get_next_fomc()
        if next_fomc:
            days = (next_fomc.event_date - today).days
            print(f"  Next FOMC:        {next_fomc.event_date} (+{days} days)")
        status = FilterStatus.FAVORABLE

    print(f"  Filter Status:    {status_icon(status)} {status.value.upper()}")


def print_summary(status: MarketStatus) -> None:
    """Print market status summary."""
    print_header(f"SUMMARY - {status.market_type.value} Market", "-")

    if status.is_favorable:
        print("  Is Favorable:     [PASS] YES - Safe to open positions")
    else:
        print("  Is Favorable:     [FAIL] NO - Avoid new positions")

    if status.unfavorable_reasons:
        print()
        print("  Unfavorable Reasons:")
        for reason in status.unfavorable_reasons:
            print(f"    - {reason}")
    else:
        print("  Unfavorable Reasons: (none)")

    print()
    print(f"  Timestamp:        {status.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")


def validate_us_market(config: ScreeningConfig, provider: UnifiedDataProvider) -> MarketStatus:
    """Validate US market and print details."""
    print_header("MARKET FILTER VALIDATION - US Market")

    us_config = config.market_filter.us_market
    market_filter = MarketFilter(config, provider)

    # Get full status
    status = market_filter.evaluate(MarketType.US)

    # 1. Volatility Index (VIX)
    print_subheader("1. Volatility Index (VIX)")
    print_volatility_index(
        status.volatility_index,
        us_config.vix_range,
        us_config.vix_percentile_range
    )

    # 2. Trend Indices
    print_subheader("2. Trend Indices (SPY/QQQ)")
    print_trend_indices(
        status.trend_indices,
        status.overall_trend,
        us_config.trend_required
    )

    # 3. Term Structure
    print_subheader("3. Term Structure (VIX/VIX3M)")
    print_term_structure(
        status.term_structure,
        us_config.term_structure_threshold
    )

    # 4. Put/Call Ratio
    print_subheader("4. Put/Call Ratio (SPY)")
    print_pcr(status.pcr, us_config.pcr_range)

    # 5. Macro Events
    print_subheader("5. Macro Events")
    print_macro_events(status.macro_events)

    # Summary
    print_summary(status)

    return status


def validate_hk_market(config: ScreeningConfig, provider: UnifiedDataProvider) -> MarketStatus:
    """Validate HK market and print details."""
    print_header("MARKET FILTER VALIDATION - HK Market")

    hk_config = config.market_filter.hk_market
    market_filter = MarketFilter(config, provider)

    # Get full status
    status = market_filter.evaluate(MarketType.HK)

    # 1. Volatility (VHSI - 恒生波动率指数)
    print_subheader("1. Volatility Index (VHSI)")
    print_volatility_index(
        status.volatility_index,
        hk_config.vhsi_range,
        hk_config.vhsi_percentile_range
    )

    # 2. Trend Indices
    print_subheader("2. Trend Indices (2800.HK/3033.HK)")
    print_trend_indices(
        status.trend_indices,
        status.overall_trend,
        hk_config.trend_required
    )

    # 3. Term Structure - not applicable for HK
    print_subheader("3. Term Structure")
    print("  Status:           N/A (HK market)")

    # 4. Put/Call Ratio - not applicable for HK
    print_subheader("4. Put/Call Ratio")
    print("  Status:           N/A (HK market)")

    # 5. Macro Events (FOMC 对全球市场有影响)
    print_subheader("5. Macro Events (US events)")
    if hk_config.check_us_macro_events:
        print_macro_events(status.macro_events)
    else:
        print("  Status:           Disabled (check_us_macro_events=False)")

    # Summary
    print_summary(status)

    return status


def main():
    """Run market filter validation."""
    parser = argparse.ArgumentParser(description="Validate MarketFilter for US and HK markets")
    parser.add_argument(
        "--market",
        choices=["us", "hk", "both"],
        default="both",
        help="Market to validate (default: both)"
    )
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  MARKET FILTER VALIDATION")
    print(f"  Date: {date.today()}")
    print("=" * 70)

    # Load config
    config = ScreeningConfig()
    provider = UnifiedDataProvider()

    results = {}

    # Validate markets
    if args.market in ["us", "both"]:
        try:
            results["US"] = validate_us_market(config, provider)
        except Exception as e:
            print(f"\n[ERROR] US market validation failed: {e}")
            import traceback
            traceback.print_exc()

    if args.market in ["hk", "both"]:
        try:
            results["HK"] = validate_hk_market(config, provider)
        except Exception as e:
            print(f"\n[ERROR] HK market validation failed: {e}")
            import traceback
            traceback.print_exc()

    # Final summary
    print_header("FINAL SUMMARY")
    for market, status in results.items():
        icon = "[PASS]" if status.is_favorable else "[FAIL]"
        print(f"  {market} Market: {icon} {'Favorable' if status.is_favorable else 'Unfavorable'}")

    print()
    print("=" * 70)
    print("  Validation Complete")
    print("=" * 70)

    return 0 if all(s.is_favorable for s in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
