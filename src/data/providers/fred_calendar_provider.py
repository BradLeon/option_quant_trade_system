"""FRED (Federal Reserve Economic Data) provider for economic release dates.

FRED provides official economic data release dates including CPI, NFP, GDP, PPI.
API documentation: https://fred.stlouisfed.org/docs/api/fred/

Free tier: 120 requests per minute (no daily limit).
"""

import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

from src.data.models.event import (
    EconomicEvent,
    EconomicEventType,
    EventImpact,
)

logger = logging.getLogger(__name__)


# FRED Release IDs for key economic indicators
# See: https://fred.stlouisfed.org/releases
FRED_RELEASE_IDS = {
    "CPI": 10,  # Consumer Price Index
    "NFP": 50,  # Employment Situation (Non-Farm Payrolls)
    "GDP": 53,  # Gross Domestic Product
    "PPI": 46,  # Producer Price Index
}

# Mapping from release_id to EconomicEventType
RELEASE_TYPE_MAPPING = {
    10: EconomicEventType.CPI,
    50: EconomicEventType.NFP,
    53: EconomicEventType.GDP,
    46: EconomicEventType.PPI,
}

# Mapping from release_id to event name
RELEASE_NAME_MAPPING = {
    10: "Consumer Price Index",
    50: "Employment Situation (Non-Farm Payrolls)",
    53: "Gross Domestic Product",
    46: "Producer Price Index",
}

# High impact releases
HIGH_IMPACT_RELEASES = {10, 50, 53}  # CPI, NFP, GDP


class FredCalendarProvider:
    """FRED API provider for economic release dates.

    Provides economic data release dates from the Federal Reserve Economic Data API.
    Requires API key (free, 120 requests/minute).

    Usage:
        provider = FredCalendarProvider(api_key="your_key")
        events = provider.get_release_dates(
            release_id=10,  # CPI
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
    """

    BASE_URL = "https://api.stlouisfed.org/fred"
    MAX_REQUESTS_PER_MINUTE = 120

    # Release IDs as class constants for convenience
    RELEASE_CPI = 10
    RELEASE_NFP = 50
    RELEASE_GDP = 53
    RELEASE_PPI = 46

    def __init__(
        self,
        api_key: str | None = None,
        rate_limit: float = 0.5,
    ) -> None:
        """Initialize FRED provider.

        Args:
            api_key: FRED API key. If not provided, reads from
                FRED_API_KEY environment variable.
            rate_limit: Minimum seconds between requests (default 0.5).
        """
        # 加载环境变量（如果尚未加载）
        load_dotenv()

        self._api_key = api_key or os.environ.get("FRED_API_KEY")
        self._rate_limit = rate_limit
        self._last_request_time = 0.0

    @property
    def name(self) -> str:
        """Provider name."""
        return "fred"

    @property
    def is_available(self) -> bool:
        """Check if provider is available (API key configured)."""
        return bool(self._api_key)

    def _check_rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        current_time = time.time()
        elapsed = current_time - self._last_request_time

        if elapsed < self._rate_limit:
            sleep_time = self._rate_limit - elapsed
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    def _make_request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Make API request to FRED.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            JSON response or None on error
        """
        if not self._api_key:
            logger.error("FRED API key not configured")
            return None

        self._check_rate_limit()

        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {}
        params["api_key"] = self._api_key
        params["file_type"] = "json"

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.error(f"FRED API bad request: {e.response.text}")
            elif e.response.status_code == 401:
                logger.error("FRED API authentication failed - check your API key")
            elif e.response.status_code == 429:
                logger.error("FRED API rate limit exceeded")
            else:
                logger.error(f"FRED API HTTP error: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"FRED API request failed: {e}")
            return None
        except ValueError as e:
            logger.error(f"FRED API response parse error: {e}")
            return None

    def get_release_dates(
        self,
        release_id: int,
        start_date: date,
        end_date: date,
    ) -> list[EconomicEvent]:
        """Get release dates for a specific economic indicator.

        Args:
            release_id: FRED release ID (10=CPI, 50=NFP, 53=GDP, 46=PPI)
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of EconomicEvent instances for the release dates
        """
        if not self.is_available:
            logger.warning("FRED API key not configured")
            return []

        # FRED API expects these parameters for future dates
        params = {
            "release_id": release_id,
            "realtime_start": start_date.strftime("%Y-%m-%d"),
            "realtime_end": "9999-12-31",  # Required for future dates
            "include_release_dates_with_no_data": "true",  # Key: get future dates
            "sort_order": "asc",
        }

        data = self._make_request("release/dates", params)

        if data is None:
            return []

        # FRED returns {"release_dates": [...]}
        release_dates = data.get("release_dates", [])

        if not isinstance(release_dates, list):
            logger.error(f"Unexpected FRED response format: {type(release_dates)}")
            return []

        events = []
        event_type = RELEASE_TYPE_MAPPING.get(release_id, EconomicEventType.OTHER)
        event_name = RELEASE_NAME_MAPPING.get(release_id, f"Release {release_id}")
        impact = (
            EventImpact.HIGH if release_id in HIGH_IMPACT_RELEASES else EventImpact.MEDIUM
        )

        for item in release_dates:
            try:
                # Parse date from item
                date_str = item.get("date") if isinstance(item, dict) else item
                if not date_str:
                    continue

                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                # Filter by date range
                if not (start_date <= event_date <= end_date):
                    continue

                events.append(
                    EconomicEvent(
                        event_type=event_type,
                        event_date=event_date,
                        name=event_name,
                        impact=impact,
                        country="US",
                        source=self.name,
                    )
                )

            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse release date: {e}, item={item}")
                continue

        logger.debug(
            f"FRED: fetched {len(events)} release dates for {event_name} "
            f"({start_date} to {end_date})"
        )

        return events

    def get_all_release_dates(
        self,
        start_date: date,
        end_date: date,
        release_ids: list[int] | None = None,
    ) -> list[EconomicEvent]:
        """Get release dates for multiple economic indicators.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            release_ids: List of release IDs to fetch. If None, fetches all
                (CPI, NFP, GDP, PPI).

        Returns:
            List of EconomicEvent instances, sorted by date
        """
        if release_ids is None:
            release_ids = list(FRED_RELEASE_IDS.values())

        all_events = []

        for release_id in release_ids:
            events = self.get_release_dates(release_id, start_date, end_date)
            all_events.extend(events)

        # Sort by date
        all_events.sort(key=lambda e: e.event_date)

        return all_events

    def get_upcoming_releases(
        self,
        days_ahead: int = 30,
        release_ids: list[int] | None = None,
    ) -> list[EconomicEvent]:
        """Get upcoming release dates.

        Convenience method to get releases in the next N days.

        Args:
            days_ahead: Number of days to look ahead
            release_ids: List of release IDs to fetch

        Returns:
            List of upcoming EconomicEvent instances
        """
        start_date = date.today()
        end_date = start_date + timedelta(days=days_ahead)

        return self.get_all_release_dates(start_date, end_date, release_ids)

    def get_release_info(self, release_id: int) -> dict[str, Any] | None:
        """Get information about a release.

        Args:
            release_id: FRED release ID

        Returns:
            Release information dictionary or None
        """
        params = {"release_id": release_id}
        data = self._make_request("release", params)

        if data is None:
            return None

        releases = data.get("releases", [])
        if releases:
            return releases[0]

        return None
