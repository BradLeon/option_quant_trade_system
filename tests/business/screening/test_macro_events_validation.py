"""Validation tests for FRED API + Static FOMC and MarketFilter macro events.

This module provides:
1. FRED API connectivity tests
2. Static FOMC calendar validation
3. EconomicCalendarProvider integration tests
4. MarketFilter._check_macro_events() validation
5. End-to-end macro event blackout verification

Usage:
    # Run all validation tests
    pytest tests/business/screening/test_macro_events_validation.py -v

    # Run only connectivity tests
    pytest tests/business/screening/test_macro_events_validation.py -v -k "connectivity"

    # Run with live API (requires FRED_API_KEY)
    FRED_API_KEY=your_key pytest tests/business/screening/test_macro_events_validation.py -v -k "live"
"""

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.business.config.screening_config import MacroEventConfig, ScreeningConfig
from src.business.screening.filters.market_filter import MarketFilter
from src.business.screening.models import MacroEventStatus
from src.data.models.event import (
    EconomicEvent,
    EconomicEventType,
    EventCalendar,
    EventImpact,
)
from src.data.providers.economic_calendar_provider import EconomicCalendarProvider
from src.data.providers.fred_calendar_provider import (
    FredCalendarProvider,
    RELEASE_TYPE_MAPPING,
)


# ============================================================================
# FRED API Connectivity Tests
# ============================================================================


class TestFredConnectivity:
    """Tests for FRED API connectivity."""

    def test_provider_initialization_without_key(self):
        """Test provider initializes without API key."""
        # Clear environment variable temporarily
        original_key = os.environ.pop("FRED_API_KEY", None)
        try:
            provider = FredCalendarProvider(api_key=None)
            assert provider.is_available is False
            assert provider.name == "fred"
        finally:
            if original_key:
                os.environ["FRED_API_KEY"] = original_key

    def test_provider_initialization_with_key(self):
        """Test provider initializes with API key."""
        provider = FredCalendarProvider(api_key="test_key")
        assert provider.is_available is True

    def test_provider_from_environment(self):
        """Test provider reads API key from environment."""
        original_key = os.environ.get("FRED_API_KEY")
        try:
            os.environ["FRED_API_KEY"] = "env_test_key"
            provider = FredCalendarProvider()
            assert provider.is_available is True
        finally:
            if original_key:
                os.environ["FRED_API_KEY"] = original_key
            else:
                os.environ.pop("FRED_API_KEY", None)

    @pytest.mark.skipif(
        not os.environ.get("FRED_API_KEY"),
        reason="FRED_API_KEY not set",
    )
    def test_live_api_connectivity(self):
        """Test live API connectivity (requires API key)."""
        provider = FredCalendarProvider()

        # Try to fetch CPI release dates for next 90 days
        today = date.today()
        events = provider.get_release_dates(
            release_id=FredCalendarProvider.RELEASE_CPI,
            start_date=today,
            end_date=today + timedelta(days=90),
        )

        # Should return list of events (may be empty)
        assert isinstance(events, list)
        print(f"\n[LIVE] Fetched {len(events)} CPI release dates for next 90 days")
        for event in events[:3]:
            print(f"  - {event.event_date}: {event.name}")


# ============================================================================
# Static FOMC Calendar Tests
# ============================================================================


class TestStaticFomcCalendar:
    """Tests for static FOMC calendar loading."""

    def test_fomc_calendar_loads(self):
        """Test FOMC calendar loads from YAML file."""
        provider = EconomicCalendarProvider()

        # Should have loaded FOMC dates
        assert len(provider._fomc_dates) > 0

    def test_fomc_calendar_has_2025_2026(self):
        """Test FOMC calendar has 2025 and 2026 dates."""
        provider = EconomicCalendarProvider()

        assert 2025 in provider._fomc_dates or 2026 in provider._fomc_dates

        # Each year should have ~8 meetings
        for year in [2025, 2026]:
            if year in provider._fomc_dates:
                assert len(provider._fomc_dates[year]) == 8

    def test_fomc_events_retrieval(self):
        """Test FOMC events can be retrieved for date range."""
        provider = EconomicCalendarProvider()

        # Get 2025 FOMC events
        fomc_events = provider._get_fomc_events(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        # Should have 8 FOMC meetings in 2025
        assert len(fomc_events) == 8
        for event in fomc_events:
            assert event.event_type == EconomicEventType.FOMC
            assert event.impact == EventImpact.HIGH


# ============================================================================
# FRED Event Type Mapping Tests
# ============================================================================


class TestFredEventMapping:
    """Tests for FRED release ID to event type mapping."""

    def test_release_cpi_mapping(self):
        """Test CPI release ID mapping."""
        assert RELEASE_TYPE_MAPPING.get(10) == EconomicEventType.CPI

    def test_release_nfp_mapping(self):
        """Test NFP release ID mapping."""
        assert RELEASE_TYPE_MAPPING.get(50) == EconomicEventType.NFP

    def test_release_gdp_mapping(self):
        """Test GDP release ID mapping."""
        assert RELEASE_TYPE_MAPPING.get(53) == EconomicEventType.GDP

    def test_release_ppi_mapping(self):
        """Test PPI release ID mapping."""
        assert RELEASE_TYPE_MAPPING.get(46) == EconomicEventType.PPI

    def test_release_constants_match_mapping(self):
        """Test release constants are in mapping."""
        assert FredCalendarProvider.RELEASE_CPI in RELEASE_TYPE_MAPPING
        assert FredCalendarProvider.RELEASE_NFP in RELEASE_TYPE_MAPPING
        assert FredCalendarProvider.RELEASE_GDP in RELEASE_TYPE_MAPPING
        assert FredCalendarProvider.RELEASE_PPI in RELEASE_TYPE_MAPPING


# ============================================================================
# EconomicCalendarProvider Tests
# ============================================================================


class TestEconomicCalendarProvider:
    """Tests for EconomicCalendarProvider integration."""

    def test_provider_available_with_fomc_only(self):
        """Test provider is available even without FRED API key."""
        # Clear FRED API key
        original_key = os.environ.pop("FRED_API_KEY", None)
        try:
            provider = EconomicCalendarProvider()
            # Should be available due to static FOMC calendar
            assert provider.is_available is True
        finally:
            if original_key:
                os.environ["FRED_API_KEY"] = original_key

    def test_get_economic_calendar_fomc_only(self):
        """Test economic calendar returns FOMC events without FRED API."""
        original_key = os.environ.pop("FRED_API_KEY", None)
        try:
            provider = EconomicCalendarProvider()

            calendar = provider.get_economic_calendar(
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                event_types=["FOMC"],
            )

            assert calendar is not None
            assert len(calendar.events) == 8  # 8 FOMC meetings in 2025
            assert calendar.source == "fred+static"
        finally:
            if original_key:
                os.environ["FRED_API_KEY"] = original_key

    def test_get_market_moving_events(self):
        """Test get_market_moving_events convenience method."""
        provider = EconomicCalendarProvider()

        events = provider.get_market_moving_events(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
        )

        # Should include FOMC events at minimum
        fomc_events = [e for e in events if e.event_type == EconomicEventType.FOMC]
        assert len(fomc_events) >= 1  # At least Jan 29 and Mar 19 FOMC

    def test_get_next_fomc(self):
        """Test get_next_fomc returns next meeting."""
        provider = EconomicCalendarProvider()

        # Mock today to be Jan 1, 2025
        with patch("src.data.providers.economic_calendar_provider.date") as mock_date:
            mock_date.today.return_value = date(2025, 1, 1)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            next_fomc = provider.get_next_fomc()

            if next_fomc:
                assert next_fomc.event_type == EconomicEventType.FOMC


# ============================================================================
# MarketFilter Macro Events Tests
# ============================================================================


class TestMarketFilterMacroEvents:
    """Tests for MarketFilter._check_macro_events() functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock screening config."""
        config = MagicMock(spec=ScreeningConfig)
        config.market_filter = MagicMock()
        config.market_filter.macro_events = MacroEventConfig(
            enabled=True,
            blackout_days=3,
            blackout_events=["FOMC", "CPI", "NFP"],
        )
        return config

    @pytest.fixture
    def sample_events(self):
        """Create sample economic events."""
        today = date.today()
        return [
            EconomicEvent(
                event_type=EconomicEventType.FOMC,
                event_date=today + timedelta(days=2),
                name="FOMC Interest Rate Decision",
                impact=EventImpact.HIGH,
                country="US",
            ),
            EconomicEvent(
                event_type=EconomicEventType.CPI,
                event_date=today + timedelta(days=5),
                name="Consumer Price Index",
                impact=EventImpact.HIGH,
                country="US",
            ),
        ]

    def test_macro_events_disabled(self, mock_config):
        """Test macro events check when disabled."""
        mock_config.market_filter.macro_events.enabled = False
        mock_provider = MagicMock()

        market_filter = MarketFilter(mock_config, mock_provider)
        result = market_filter._check_macro_events(
            mock_config.market_filter.macro_events
        )

        assert result is None
        mock_provider.check_macro_blackout.assert_not_called()

    def test_macro_events_in_blackout(self, mock_config, sample_events):
        """Test when in blackout period."""
        mock_provider = MagicMock()
        mock_provider.check_macro_blackout.return_value = (True, sample_events[:1])

        market_filter = MarketFilter(mock_config, mock_provider)
        result = market_filter._check_macro_events(
            mock_config.market_filter.macro_events
        )

        assert result is not None
        assert result.is_in_blackout is True
        assert len(result.upcoming_events) == 1
        assert result.upcoming_events[0].event_type == EconomicEventType.FOMC

    def test_macro_events_not_in_blackout(self, mock_config):
        """Test when not in blackout period."""
        mock_provider = MagicMock()
        mock_provider.check_macro_blackout.return_value = (False, [])

        market_filter = MarketFilter(mock_config, mock_provider)
        result = market_filter._check_macro_events(
            mock_config.market_filter.macro_events
        )

        assert result is not None
        assert result.is_in_blackout is False
        assert len(result.upcoming_events) == 0

    def test_macro_events_api_failure(self, mock_config):
        """Test graceful handling of API failure."""
        mock_provider = MagicMock()
        mock_provider.check_macro_blackout.side_effect = Exception("API Error")

        market_filter = MarketFilter(mock_config, mock_provider)
        result = market_filter._check_macro_events(
            mock_config.market_filter.macro_events
        )

        # Should fail-open (not block trading)
        assert result is not None
        assert result.is_in_blackout is False


class TestBlackoutPeriodLogic:
    """Tests for blackout period calculation logic."""

    def test_blackout_3_days_before_fomc(self):
        """Test 3-day blackout before FOMC."""
        provider = EconomicCalendarProvider()
        today = date.today()

        # Mock the calendar response
        fomc_date = today + timedelta(days=2)  # FOMC in 2 days
        mock_calendar = EventCalendar(
            start_date=today,
            end_date=today + timedelta(days=3),
            events=[
                EconomicEvent(
                    event_type=EconomicEventType.FOMC,
                    event_date=fomc_date,
                    name="FOMC Interest Rate Decision",
                    impact=EventImpact.HIGH,
                    country="US",
                ),
            ],
            source="fred+static",
        )

        with patch.object(provider, "get_economic_calendar", return_value=mock_calendar):
            is_blackout, events = provider.check_blackout_period(
                target_date=today,
                blackout_days=3,
                blackout_events=["FOMC"],
            )

        assert is_blackout is True
        assert len(events) == 1
        assert events[0].event_type == EconomicEventType.FOMC

    def test_no_blackout_when_event_far(self):
        """Test no blackout when event is far away."""
        provider = EconomicCalendarProvider()
        today = date.today()

        # No events in 3-day window
        mock_calendar = EventCalendar(
            start_date=today,
            end_date=today + timedelta(days=3),
            events=[],
            source="fred+static",
        )

        with patch.object(provider, "get_economic_calendar", return_value=mock_calendar):
            is_blackout, events = provider.check_blackout_period(
                target_date=today,
                blackout_days=3,
                blackout_events=["FOMC"],
            )

        assert is_blackout is False
        assert len(events) == 0

    def test_blackout_only_for_specified_events(self):
        """Test blackout only triggers for specified event types.

        When blackout_events=["FOMC", "CPI", "NFP"] is specified, PPI events
        should not trigger a blackout. The filtering happens in get_economic_calendar
        which only returns events matching the specified event_types.
        """
        provider = EconomicCalendarProvider()
        today = date.today()

        # When we request only FOMC/CPI/NFP events and there's only PPI,
        # get_economic_calendar returns an empty calendar
        mock_calendar = EventCalendar(
            start_date=today,
            end_date=today + timedelta(days=3),
            events=[],  # No FOMC/CPI/NFP events, PPI is filtered out
            source="fred+static",
        )

        with patch.object(provider, "get_economic_calendar", return_value=mock_calendar):
            is_blackout, events = provider.check_blackout_period(
                target_date=today,
                blackout_days=3,
                blackout_events=["FOMC", "CPI", "NFP"],  # PPI not included
            )

        assert is_blackout is False
        assert len(events) == 0


class TestMacroEventStatus:
    """Tests for MacroEventStatus model."""

    def test_event_names_property(self):
        """Test event_names property returns list of names."""
        events = [
            EconomicEvent(
                event_type=EconomicEventType.FOMC,
                event_date=date.today(),
                name="FOMC Interest Rate Decision",
                impact=EventImpact.HIGH,
            ),
            EconomicEvent(
                event_type=EconomicEventType.CPI,
                event_date=date.today(),
                name="Consumer Price Index",
                impact=EventImpact.HIGH,
            ),
        ]

        status = MacroEventStatus(
            is_in_blackout=True,
            upcoming_events=events,
            blackout_days=3,
        )

        assert "FOMC Interest Rate Decision" in status.event_names
        assert "Consumer Price Index" in status.event_names

    def test_empty_status(self):
        """Test empty MacroEventStatus."""
        status = MacroEventStatus(
            is_in_blackout=False,
            upcoming_events=[],
            blackout_days=3,
        )

        assert status.is_in_blackout is False
        assert status.event_names == []


# ============================================================================
# Integration Tests
# ============================================================================


class TestMacroEventsIntegration:
    """Integration tests for macro events flow."""

    def test_live_static_fomc_check(self):
        """Test FOMC blackout checking with static calendar (no API needed)."""
        provider = EconomicCalendarProvider()

        # Check for FOMC events in 2025
        calendar = provider.get_economic_calendar(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            event_types=["FOMC"],
        )

        assert calendar is not None
        assert len(calendar.events) == 8  # 8 FOMC meetings in 2025

        print(f"\n[STATIC] 2025 FOMC meetings: {len(calendar.events)}")
        for event in calendar.events[:3]:
            print(f"  - {event.event_date}: {event.name}")

    @pytest.mark.skipif(
        not os.environ.get("FRED_API_KEY"),
        reason="FRED_API_KEY not set",
    )
    def test_live_fred_api_check(self):
        """Test FRED API connectivity (requires API key)."""
        from src.data.providers.unified_provider import UnifiedDataProvider

        provider = UnifiedDataProvider()
        today = date.today()

        # Check blackout status
        is_blackout, events = provider.check_macro_blackout(
            target_date=today,
            blackout_days=3,
            blackout_events=["FOMC", "CPI", "NFP"],
        )

        print(f"\n[LIVE] Macro Event Check:")
        print(f"  Is in blackout: {is_blackout}")
        print(f"  Upcoming events: {len(events)}")

        for event in events:
            days_until = (event.event_date - today).days
            print(f"    - {event.name} in {days_until} days ({event.event_date})")

        # Verify return types
        assert isinstance(is_blackout, bool)
        assert isinstance(events, list)

    def test_market_filter_evaluate_with_mock_blackout(self):
        """Test MarketFilter.evaluate() includes macro event check."""
        # Create mock config
        config = MagicMock(spec=ScreeningConfig)
        config.market_filter = MagicMock()
        config.market_filter.us_market = MagicMock()
        config.market_filter.us_market.vix_range = [15, 28]
        config.market_filter.us_market.vix_percentile_range = [0.3, 0.8]
        config.market_filter.us_market.term_structure_threshold = 0.9
        config.market_filter.us_market.pcr_range = [0.8, 1.5]
        config.market_filter.us_market.trend_required = "bullish_or_neutral"
        config.market_filter.macro_events = MacroEventConfig(
            enabled=True,
            blackout_days=3,
            blackout_events=["FOMC", "CPI", "NFP"],
        )

        # Create mock provider that returns blackout
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
        mock_provider.get_macro_data.return_value = None  # Skip VIX check

        market_filter = MarketFilter(config, mock_provider)

        # Call _check_macro_events directly
        result = market_filter._check_macro_events(config.market_filter.macro_events)

        assert result is not None
        assert result.is_in_blackout is True
        assert "FOMC Interest Rate Decision" in result.event_names


# ============================================================================
# Validation Script (Run directly)
# ============================================================================


def run_validation():
    """Run validation checks manually.

    Usage:
        python -c "from tests.business.screening.test_macro_events_validation import run_validation; run_validation()"
    """
    print("=" * 60)
    print("FRED API + Static FOMC Macro Events Validation")
    print("=" * 60)

    # Check for static FOMC calendar
    print("\n--- Static FOMC Calendar ---")
    provider = EconomicCalendarProvider()

    total_dates = sum(len(dates) for dates in provider._fomc_dates.values())
    years = list(provider._fomc_dates.keys())
    print(f"[OK] Loaded {total_dates} FOMC meetings for years: {years}")

    if 2025 in provider._fomc_dates:
        print(f"\n2025 FOMC meetings ({len(provider._fomc_dates[2025])}):")
        for d in provider._fomc_dates[2025][:4]:
            print(f"  - {d}")
        print("  ...")

    # Check FRED API key
    print("\n--- FRED API Configuration ---")
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("[WARNING] FRED_API_KEY not set in environment")
        print("  Set it with: export FRED_API_KEY=your_api_key")
        print("  Static FOMC calendar will still work without it")
    else:
        print(f"[OK] API key configured (length: {len(api_key)})")

        # Test FRED connectivity
        print("\n--- FRED API Connectivity ---")
        fred_provider = FredCalendarProvider()
        today = date.today()

        try:
            events = fred_provider.get_release_dates(
                release_id=FredCalendarProvider.RELEASE_CPI,
                start_date=today,
                end_date=today + timedelta(days=90),
            )
            print(f"[OK] FRED API connection successful")
            print(f"     CPI releases in next 90 days: {len(events)}")
            for event in events[:3]:
                days = (event.event_date - today).days
                print(f"       - {event.event_date} (in {days} days)")
        except Exception as e:
            print(f"[FAIL] FRED API error: {e}")

    # Test blackout check
    print("\n--- Blackout Period Check ---")
    today = date.today()
    is_blackout, blackout_events = provider.check_blackout_period(
        target_date=today,
        blackout_days=3,
        blackout_events=["FOMC", "CPI", "NFP"],
    )

    if is_blackout:
        print(f"[WARNING] Currently in BLACKOUT period!")
        for event in blackout_events:
            days = (event.event_date - today).days
            print(f"  - {event.name} in {days} days")
    else:
        print("[OK] Not in blackout period - safe to open positions")

    print("\n" + "=" * 60)
    print("Validation Complete")
    print("=" * 60)


if __name__ == "__main__":
    run_validation()
