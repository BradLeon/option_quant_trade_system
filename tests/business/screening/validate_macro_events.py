#!/usr/bin/env python3
"""Validation script for FRED API + Static FOMC and MarketFilter macro events.

This script validates:
1. FRED API connectivity and data retrieval
2. Static FOMC calendar loading
3. EconomicCalendarProvider integration
4. MarketFilter._check_macro_events() functionality
5. Blackout period logic correctness

Usage:
    # Set API key first (optional for FRED, static FOMC works without)
    export FRED_API_KEY=your_api_key

    # Run validation
    python tests/business/screening/validate_macro_events.py

    # Or run via pytest for live tests
    pytest tests/business/screening/test_macro_events_validation.py -v -k "live"
"""

import os
import sys
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))


def print_header(title: str) -> None:
    """Print section header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_ok(message: str) -> None:
    """Print success message."""
    print(f"  [OK] {message}")


def print_fail(message: str) -> None:
    """Print failure message."""
    print(f"  [FAIL] {message}")


def print_warn(message: str) -> None:
    """Print warning message."""
    print(f"  [WARN] {message}")


def print_info(message: str) -> None:
    """Print info message."""
    print(f"  [INFO] {message}")


def validate_api_key() -> bool:
    """Validate FRED API key is configured."""
    print_header("1. FRED API Key Configuration")

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print_warn("FRED_API_KEY environment variable not set")
        print_info("FRED API features will be skipped, but static FOMC works without it")
        print_info("Get free API key at: https://fred.stlouisfed.org/docs/api/api_key.html")
        return False

    print_ok(f"API key configured (length: {len(api_key)} chars)")
    return True


def validate_static_fomc_calendar() -> bool:
    """Validate static FOMC calendar loading."""
    print_header("2. Static FOMC Calendar")

    from src.data.providers.economic_calendar_provider import EconomicCalendarProvider

    provider = EconomicCalendarProvider()

    # Check if FOMC dates loaded
    if not provider._fomc_dates:
        print_fail("Failed to load FOMC calendar from YAML")
        return False

    total_dates = sum(len(dates) for dates in provider._fomc_dates.values())
    years = list(provider._fomc_dates.keys())
    print_ok(f"Loaded {total_dates} FOMC meetings for years: {years}")

    today = date.today()
    current_year = today.year

    # Show current year's FOMC meetings
    if current_year in provider._fomc_dates:
        fomc_current = provider._fomc_dates[current_year]
        print_ok(f"{current_year} FOMC meetings: {len(fomc_current)} scheduled")
        for d in fomc_current:
            days_diff = (d - today).days
            marker = " <-- NEXT" if days_diff > 0 and all((d2 - today).days < 0 or d2 >= d for d2 in fomc_current) else ""
            if days_diff >= 0:
                print_info(f"  - {d} (+{days_diff} days){marker}")
            else:
                print_info(f"  - {d} (passed)")
    else:
        print_warn(f"No {current_year} FOMC dates found")

    return True


def validate_fred_connectivity() -> bool:
    """Validate FRED provider can connect to API."""
    print_header("3. FRED API Connectivity Test")

    from src.data.providers.fred_calendar_provider import FredCalendarProvider

    provider = FredCalendarProvider()

    if not provider.is_available:
        print_warn("FRED provider not available (API key missing)")
        return False

    print_ok("Provider initialized successfully")

    today = date.today()
    look_ahead_days = 180

    # Define all release types to fetch
    release_types = [
        (FredCalendarProvider.RELEASE_CPI, "CPI", "Consumer Price Index"),
        (FredCalendarProvider.RELEASE_NFP, "NFP", "Non-Farm Payrolls"),
        (FredCalendarProvider.RELEASE_GDP, "GDP", "Gross Domestic Product"),
        (FredCalendarProvider.RELEASE_PPI, "PPI", "Producer Price Index"),
    ]

    all_success = True
    for release_id, short_name, full_name in release_types:
        try:
            events = provider.get_release_dates(
                release_id=release_id,
                start_date=today,
                end_date=today + timedelta(days=look_ahead_days),
            )

            if events:
                print_ok(f"{short_name} ({full_name}): {len(events)} dates in next {look_ahead_days} days")
                for event in events[:3]:
                    days = (event.event_date - today).days
                    print_info(f"    {event.event_date} (+{days} days)")
                if len(events) > 3:
                    print_info(f"    ... and {len(events) - 3} more")
            else:
                print_warn(f"{short_name}: No release dates found")

        except Exception as e:
            print_fail(f"{short_name} API request failed: {e}")
            all_success = False

    return all_success


def validate_event_parsing() -> bool:
    """Validate event type classification."""
    print_header("4. Event Type Classification")

    from src.data.providers.fred_calendar_provider import (
        FredCalendarProvider,
        RELEASE_TYPE_MAPPING,
    )
    from src.data.models.event import EconomicEventType

    test_cases = [
        (10, EconomicEventType.CPI),
        (50, EconomicEventType.NFP),
        (53, EconomicEventType.GDP),
        (46, EconomicEventType.PPI),
    ]

    all_passed = True
    for release_id, expected_type in test_cases:
        result = RELEASE_TYPE_MAPPING.get(release_id)
        if result == expected_type:
            print_ok(f"Release ID {release_id} -> {result.value}")
        else:
            print_fail(f"Release ID {release_id} -> {result} (expected: {expected_type.value})")
            all_passed = False

    return all_passed


def validate_economic_calendar_provider() -> bool:
    """Validate EconomicCalendarProvider integration."""
    print_header("5. EconomicCalendarProvider Integration")

    from src.data.providers.economic_calendar_provider import EconomicCalendarProvider
    from src.data.models.event import EconomicEventType

    provider = EconomicCalendarProvider()

    if not provider.is_available:
        print_fail("Provider not available")
        return False

    print_ok("Provider initialized successfully")

    # Get calendar for next 60 days
    today = date.today()
    look_ahead_days = 60
    calendar = provider.get_economic_calendar(
        start_date=today,
        end_date=today + timedelta(days=look_ahead_days),
    )

    if calendar is None:
        print_fail("Failed to get economic calendar")
        return False

    print_ok(f"Calendar retrieved: {len(calendar.events)} total events in next {look_ahead_days} days")

    # Count events by type
    event_types = [
        (EconomicEventType.FOMC, "FOMC"),
        (EconomicEventType.CPI, "CPI"),
        (EconomicEventType.NFP, "NFP"),
        (EconomicEventType.GDP, "GDP"),
        (EconomicEventType.PPI, "PPI"),
    ]

    print_info("Events by type:")
    for event_type, name in event_types:
        events = [e for e in calendar.events if e.event_type == event_type]
        if events:
            print_info(f"  {name}: {len(events)} event(s)")
            for event in events[:2]:
                days = (event.event_date - today).days
                print_info(f"    - {event.event_date} (+{days} days)")
        else:
            print_info(f"  {name}: 0 events")

    return True


def validate_blackout_check() -> bool:
    """Validate blackout period checking."""
    print_header("6. Blackout Period Check")

    from src.data.providers.economic_calendar_provider import EconomicCalendarProvider

    provider = EconomicCalendarProvider()
    today = date.today()

    is_blackout, events = provider.check_blackout_period(
        target_date=today,
        blackout_days=3,
        blackout_events=["FOMC", "CPI", "NFP"],
    )

    if is_blackout:
        print_warn("Currently in BLACKOUT period!")
        print_info("Upcoming events causing blackout:")
        for event in events:
            days = (event.event_date - today).days
            print_info(f"  - {event.name} in {days} day(s) ({event.event_date})")
        print_warn("Recommendation: Avoid opening new positions")
    else:
        print_ok("Not in blackout period - safe to open positions")

    return True


def validate_market_filter_integration() -> bool:
    """Validate MarketFilter macro event integration."""
    print_header("7. MarketFilter Integration Test")

    from unittest.mock import MagicMock

    from src.business.config.screening_config import MacroEventConfig
    from src.business.screening.filters.market_filter import MarketFilter
    from src.data.models.event import EconomicEvent, EconomicEventType, EventImpact

    # Create mock config
    config = MagicMock()
    config.market_filter = MagicMock()
    config.market_filter.macro_events = MacroEventConfig(
        enabled=True,
        blackout_days=3,
        blackout_events=["FOMC", "CPI", "NFP"],
    )

    # Test 1: Mock blackout scenario
    print_info("Test 1: Simulating blackout with FOMC tomorrow...")
    mock_provider = MagicMock()
    mock_provider.check_macro_blackout.return_value = (
        True,
        [
            EconomicEvent(
                event_type=EconomicEventType.FOMC,
                event_date=date.today() + timedelta(days=1),
                name="FOMC Interest Rate Decision",
                impact=EventImpact.HIGH,
                country="US",
            ),
        ],
    )

    market_filter = MarketFilter(config, mock_provider)
    result = market_filter._check_macro_events(config.market_filter.macro_events)

    if result and result.is_in_blackout:
        print_ok("Blackout correctly detected")
    else:
        print_fail("Failed to detect blackout")
        return False

    # Test 2: No blackout scenario
    print_info("Test 2: Simulating no upcoming events...")
    mock_provider.check_macro_blackout.return_value = (False, [])
    result = market_filter._check_macro_events(config.market_filter.macro_events)

    if result and not result.is_in_blackout:
        print_ok("No blackout correctly detected")
    else:
        print_fail("Incorrectly detected blackout")
        return False

    # Test 3: Disabled macro events
    print_info("Test 3: Testing disabled macro events...")
    config.market_filter.macro_events.enabled = False
    result = market_filter._check_macro_events(config.market_filter.macro_events)

    if result is None:
        print_ok("Disabled check returns None as expected")
    else:
        print_fail("Should return None when disabled")
        return False

    return True


def validate_unified_provider() -> bool:
    """Validate UnifiedDataProvider macro event methods."""
    print_header("8. UnifiedDataProvider Integration")

    from src.data.providers.unified_provider import UnifiedDataProvider

    provider = UnifiedDataProvider()
    today = date.today()

    # Test check_macro_blackout
    print_info("Testing UnifiedDataProvider.check_macro_blackout()...")

    try:
        is_blackout, events = provider.check_macro_blackout(
            target_date=today,
            blackout_days=3,
            blackout_events=["FOMC", "CPI", "NFP"],
        )

        print_ok(f"Blackout check successful: is_blackout={is_blackout}, events={len(events)}")
        return True

    except Exception as e:
        print_fail(f"Error calling check_macro_blackout: {e}")
        return False


def main():
    """Run all validation checks."""
    print("\n" + "=" * 60)
    print("  FRED + STATIC FOMC MACRO EVENTS VALIDATION")
    print("=" * 60)

    results = {}

    # Step 1: Check API key (optional for FRED)
    results["api_key"] = validate_api_key()

    # Step 2: Always validate static FOMC calendar
    results["static_fomc"] = validate_static_fomc_calendar()

    # Step 3: Validate FRED connectivity if API key available
    if results["api_key"]:
        results["fred_connectivity"] = validate_fred_connectivity()
    else:
        print_info("Skipping FRED API test (no API key)")

    # Run remaining tests
    results["event_parsing"] = validate_event_parsing()
    results["economic_calendar"] = validate_economic_calendar_provider()
    results["blackout"] = validate_blackout_check()
    results["market_filter"] = validate_market_filter_integration()
    results["unified_provider"] = validate_unified_provider()

    # Summary
    print_header("VALIDATION SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print()
    if passed == total:
        print(f"  All {total} checks passed!")
        return 0
    else:
        print(f"  {passed}/{total} checks passed, {total - passed} failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
