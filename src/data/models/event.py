"""Economic event models for macro event calendar."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class EconomicEventType(str, Enum):
    """Types of economic events that may impact trading."""

    FOMC = "fomc"  # Federal Reserve meeting
    CPI = "cpi"  # Consumer Price Index
    NFP = "nfp"  # Non-Farm Payrolls
    GDP = "gdp"  # Gross Domestic Product
    EARNINGS = "earnings"  # Company earnings report
    PPI = "ppi"  # Producer Price Index
    RETAIL_SALES = "retail_sales"  # Retail Sales
    UNEMPLOYMENT = "unemployment"  # Unemployment Rate
    ISM = "ism"  # ISM Manufacturing/Services Index
    PCE = "pce"  # Personal Consumption Expenditures
    OTHER = "other"  # Other events


class EventImpact(str, Enum):
    """Impact level of an economic event."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EconomicEvent:
    """Represents a single economic event.

    Attributes:
        event_type: Type of the event (FOMC, CPI, etc.)
        event_date: Date of the event
        name: Human-readable name of the event
        impact: Expected market impact level
        country: Country code (US, CN, etc.)
        time: Optional time of the event (HH:MM format)
        actual: Actual value if released
        forecast: Forecasted value
        previous: Previous value
        source: Data source
    """

    event_type: EconomicEventType
    event_date: date
    name: str
    impact: EventImpact = EventImpact.MEDIUM
    country: str = "US"
    time: str | None = None
    actual: float | str | None = None
    forecast: float | str | None = None
    previous: float | str | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_type": self.event_type.value,
            "event_date": self.event_date.isoformat(),
            "name": self.name,
            "impact": self.impact.value,
            "country": self.country,
            "time": self.time,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EconomicEvent":
        """Create instance from dictionary."""
        return cls(
            event_type=EconomicEventType(data["event_type"]),
            event_date=date.fromisoformat(data["event_date"]),
            name=data["name"],
            impact=EventImpact(data.get("impact", "medium")),
            country=data.get("country", "US"),
            time=data.get("time"),
            actual=data.get("actual"),
            forecast=data.get("forecast"),
            previous=data.get("previous"),
            source=data.get("source", "unknown"),
        )

    @property
    def is_high_impact(self) -> bool:
        """Check if event is high impact."""
        return self.impact == EventImpact.HIGH

    @property
    def is_market_moving(self) -> bool:
        """Check if event is typically market-moving.

        FOMC, CPI, and NFP are considered major market-moving events.
        """
        return self.event_type in (
            EconomicEventType.FOMC,
            EconomicEventType.CPI,
            EconomicEventType.NFP,
        )


@dataclass
class EventCalendar:
    """Container for economic events within a date range.

    Attributes:
        start_date: Start of the calendar range
        end_date: End of the calendar range
        events: List of events in the range
        source: Data source
    """

    start_date: date
    end_date: date
    events: list[EconomicEvent] = field(default_factory=list)
    source: str = "unknown"

    def filter_by_type(
        self, event_types: list[EconomicEventType]
    ) -> "EventCalendar":
        """Filter events by type.

        Args:
            event_types: List of event types to include

        Returns:
            New EventCalendar with filtered events
        """
        filtered = [e for e in self.events if e.event_type in event_types]
        return EventCalendar(
            start_date=self.start_date,
            end_date=self.end_date,
            events=filtered,
            source=self.source,
        )

    def filter_by_country(self, country: str) -> "EventCalendar":
        """Filter events by country.

        Args:
            country: Country code to filter

        Returns:
            New EventCalendar with filtered events
        """
        filtered = [e for e in self.events if e.country == country]
        return EventCalendar(
            start_date=self.start_date,
            end_date=self.end_date,
            events=filtered,
            source=self.source,
        )

    def filter_by_impact(
        self, impacts: list[EventImpact]
    ) -> "EventCalendar":
        """Filter events by impact level.

        Args:
            impacts: List of impact levels to include

        Returns:
            New EventCalendar with filtered events
        """
        filtered = [e for e in self.events if e.impact in impacts]
        return EventCalendar(
            start_date=self.start_date,
            end_date=self.end_date,
            events=filtered,
            source=self.source,
        )

    def get_events_on_date(self, event_date: date) -> list[EconomicEvent]:
        """Get all events on a specific date.

        Args:
            event_date: Date to query

        Returns:
            List of events on that date
        """
        return [e for e in self.events if e.event_date == event_date]

    def get_events_in_range(
        self, start: date, end: date
    ) -> list[EconomicEvent]:
        """Get events within a date range.

        Args:
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            List of events in the range
        """
        return [
            e for e in self.events
            if start <= e.event_date <= end
        ]

    def has_market_moving_event(
        self, start: date, end: date
    ) -> tuple[bool, list[EconomicEvent]]:
        """Check if there are market-moving events in a date range.

        Args:
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            Tuple of (has_event, list of events)
        """
        events = [
            e for e in self.events
            if start <= e.event_date <= end and e.is_market_moving
        ]
        return len(events) > 0, events

    @property
    def high_impact_events(self) -> list[EconomicEvent]:
        """Get all high impact events."""
        return [e for e in self.events if e.is_high_impact]

    @property
    def market_moving_events(self) -> list[EconomicEvent]:
        """Get all market-moving events."""
        return [e for e in self.events if e.is_market_moving]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "events": [e.to_dict() for e in self.events],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventCalendar":
        """Create instance from dictionary."""
        return cls(
            start_date=date.fromisoformat(data["start_date"]),
            end_date=date.fromisoformat(data["end_date"]),
            events=[EconomicEvent.from_dict(e) for e in data.get("events", [])],
            source=data.get("source", "unknown"),
        )
