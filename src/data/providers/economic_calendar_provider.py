"""Economic calendar provider integrating FRED API and static FOMC calendar.

This provider combines:
- FRED API: CPI, NFP, GDP, PPI release dates
- Static YAML: FOMC meeting dates (published annually by the Fed)

Usage:
    provider = EconomicCalendarProvider()
    calendar = provider.get_economic_calendar(start_date, end_date)
    is_blackout, events = provider.check_blackout_period(target_date)
"""

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from src.data.models.event import (
    EconomicEvent,
    EconomicEventType,
    EventCalendar,
    EventImpact,
)
from src.data.providers.fred_calendar_provider import FredCalendarProvider

logger = logging.getLogger(__name__)

# Default path for FOMC calendar
DEFAULT_FOMC_CALENDAR_PATH = Path(__file__).parent.parent.parent.parent / "config" / "screening" / "fomc_calendar.yaml"


class EconomicCalendarProvider:
    """Economic calendar provider integrating FRED and static FOMC data.

    Combines multiple data sources to provide a unified economic calendar:
    - FRED API: CPI, NFP, GDP, PPI release dates (dynamic)
    - Static YAML: FOMC meeting dates (updated annually)

    Usage:
        provider = EconomicCalendarProvider()

        # Get full calendar
        calendar = provider.get_economic_calendar(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31)
        )

        # Check blackout period
        is_blackout, events = provider.check_blackout_period(
            target_date=date.today(),
            blackout_days=2,
            blackout_events=["FOMC", "CPI", "NFP"]
        )
    """

    def __init__(
        self,
        fred_api_key: str | None = None,
        fomc_calendar_path: str | Path | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            fred_api_key: FRED API key. If not provided, reads from
                FRED_API_KEY environment variable.
            fomc_calendar_path: Path to FOMC calendar YAML file.
                If not provided, uses default config path.
        """
        self._fred = FredCalendarProvider(api_key=fred_api_key)
        self._fomc_calendar_path = Path(fomc_calendar_path or DEFAULT_FOMC_CALENDAR_PATH)
        self._fomc_dates: dict[int, list[date]] = {}
        self._load_fomc_calendar()

    @property
    def name(self) -> str:
        """Provider name."""
        return "fred+static"

    @property
    def is_available(self) -> bool:
        """Check if provider is available.

        Returns True if either FRED API or static FOMC calendar is available.
        """
        return self._fred.is_available or bool(self._fomc_dates)

    def _load_fomc_calendar(self) -> None:
        """Load FOMC meeting dates from YAML file."""
        if not self._fomc_calendar_path.exists():
            logger.warning(f"FOMC calendar file not found: {self._fomc_calendar_path}")
            return

        try:
            with open(self._fomc_calendar_path) as f:
                data = yaml.safe_load(f)

            fomc_meetings = data.get("fomc_meetings", {})

            for year, dates in fomc_meetings.items():
                year_int = int(year)
                self._fomc_dates[year_int] = []

                for date_str in dates:
                    if isinstance(date_str, str):
                        meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    elif isinstance(date_str, date):
                        meeting_date = date_str
                    else:
                        continue
                    self._fomc_dates[year_int].append(meeting_date)

            total_dates = sum(len(dates) for dates in self._fomc_dates.values())
            logger.debug(f"Loaded {total_dates} FOMC meeting dates from {self._fomc_calendar_path}")

        except Exception as e:
            logger.error(f"Failed to load FOMC calendar: {e}")
            self._fomc_dates = {}

    def _get_fomc_events(
        self,
        start_date: date,
        end_date: date,
    ) -> list[EconomicEvent]:
        """Get FOMC events from static calendar.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of FOMC events in the date range
        """
        events = []

        # Get relevant years
        start_year = start_date.year
        end_year = end_date.year

        for year in range(start_year, end_year + 1):
            year_dates = self._fomc_dates.get(year, [])

            for meeting_date in year_dates:
                if start_date <= meeting_date <= end_date:
                    events.append(
                        EconomicEvent(
                            event_type=EconomicEventType.FOMC,
                            event_date=meeting_date,
                            name="FOMC Interest Rate Decision",
                            impact=EventImpact.HIGH,
                            country="US",
                            time="14:00",  # 2:00 PM ET
                            source="static",
                        )
                    )

        return events

    def get_economic_calendar(
        self,
        start_date: date,
        end_date: date,
        event_types: list[str] | None = None,
        country: str | None = None,
    ) -> EventCalendar:
        """Get economic calendar for a date range.

        Combines FRED release dates and static FOMC calendar.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            event_types: Optional list of event types to include
                (e.g., ["FOMC", "CPI", "NFP"]). If None, includes all.
            country: Optional country filter. Currently only "US" is supported.

        Returns:
            EventCalendar with all events in the date range
        """
        events = []

        # Parse event types filter
        include_fomc = event_types is None or "FOMC" in event_types
        include_cpi = event_types is None or "CPI" in event_types
        include_nfp = event_types is None or "NFP" in event_types
        include_gdp = event_types is None or "GDP" in event_types
        include_ppi = event_types is None or "PPI" in event_types

        # Get FOMC events from static calendar
        if include_fomc:
            fomc_events = self._get_fomc_events(start_date, end_date)
            events.extend(fomc_events)
            logger.debug(f"Added {len(fomc_events)} FOMC events from static calendar")

        # Get FRED events if available
        if self._fred.is_available:
            fred_releases = []

            if include_cpi:
                fred_releases.append(FredCalendarProvider.RELEASE_CPI)
            if include_nfp:
                fred_releases.append(FredCalendarProvider.RELEASE_NFP)
            if include_gdp:
                fred_releases.append(FredCalendarProvider.RELEASE_GDP)
            if include_ppi:
                fred_releases.append(FredCalendarProvider.RELEASE_PPI)

            if fred_releases:
                fred_events = self._fred.get_all_release_dates(
                    start_date, end_date, fred_releases
                )
                events.extend(fred_events)
                logger.debug(f"Added {len(fred_events)} events from FRED API")
        else:
            logger.warning("FRED API not available (no API key), only FOMC events included")

        # Apply country filter
        if country:
            events = [e for e in events if e.country == country]

        # Sort by date
        events.sort(key=lambda e: e.event_date)

        return EventCalendar(
            start_date=start_date,
            end_date=end_date,
            events=events,
            source=self.name,
        )

    def get_market_moving_events(
        self,
        start_date: date,
        end_date: date,
    ) -> list[EconomicEvent]:
        """Get only market-moving events (FOMC, CPI, NFP).

        Convenience method for filtering to high-impact events.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of market-moving events
        """
        calendar = self.get_economic_calendar(
            start_date,
            end_date,
            event_types=["FOMC", "CPI", "NFP"],
        )
        return calendar.events

    def check_blackout_period(
        self,
        target_date: date,
        blackout_days: int = 2,
        blackout_events: list[str] | None = None,
    ) -> tuple[bool, list[EconomicEvent]]:
        """Check if target date is within blackout period of major events.

        Args:
            target_date: Date to check
            blackout_days: Number of days before event to avoid
            blackout_events: List of event types to check
                (default: ["FOMC", "CPI", "NFP"])

        Returns:
            Tuple of (is_in_blackout, list of upcoming events causing blackout)
        """
        if blackout_events is None:
            blackout_events = ["FOMC", "CPI", "NFP"]

        # Look ahead for events
        start_date = target_date
        end_date = target_date + timedelta(days=blackout_days)

        calendar = self.get_economic_calendar(
            start_date,
            end_date,
            event_types=blackout_events,
        )

        # Find events in blackout period
        blackout_causing_events = [
            e for e in calendar.events
            if start_date <= e.event_date <= end_date
        ]

        is_in_blackout = len(blackout_causing_events) > 0

        if is_in_blackout:
            event_names = ", ".join(e.name for e in blackout_causing_events)
            logger.info(f"Blackout period active due to: {event_names}")

        return is_in_blackout, blackout_causing_events

    def get_upcoming_fomc(
        self,
        days_ahead: int = 90,
    ) -> list[EconomicEvent]:
        """Get upcoming FOMC meetings.

        Args:
            days_ahead: Number of days to look ahead

        Returns:
            List of FOMC events
        """
        start_date = date.today()
        end_date = start_date + timedelta(days=days_ahead)

        return self._get_fomc_events(start_date, end_date)

    def get_next_fomc(self) -> EconomicEvent | None:
        """Get the next FOMC meeting date.

        Returns:
            Next FOMC event or None if not found
        """
        fomc_events = self.get_upcoming_fomc(days_ahead=90)
        return fomc_events[0] if fomc_events else None
