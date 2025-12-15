"""Data caching layer with Supabase backend."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, TypeVar

from src.data.cache.supabase_client import SupabaseClient
from src.data.models import (
    Fundamental,
    KlineBar,
    MacroData,
    OptionQuote,
    StockQuote,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DataCache:
    """Data caching layer using Supabase as backend.

    Provides get-or-fetch functionality to minimize API calls.
    """

    # Default TTL values in seconds
    DEFAULT_TTL = {
        "stock_quotes": 60,  # 1 minute for real-time quotes
        "kline_bars": 86400,  # 1 day for historical data
        "option_quotes": 300,  # 5 minutes for option data
        "fundamentals": 86400,  # 1 day for fundamental data
        "macro_data": 3600,  # 1 hour for macro data
    }

    def __init__(self, supabase_client: SupabaseClient | None = None) -> None:
        """Initialize data cache.

        Args:
            supabase_client: Optional Supabase client instance.
                           Creates a new one if not provided.
        """
        self._client = supabase_client or SupabaseClient()

    @property
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self._client.is_available

    def _is_expired(
        self, created_at: str | datetime, ttl_seconds: int
    ) -> bool:
        """Check if cached data is expired.

        Args:
            created_at: Timestamp when data was cached.
            ttl_seconds: Time-to-live in seconds.

        Returns:
            True if data is expired, False otherwise.
        """
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        # Make created_at offset-naive if it has timezone info
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)

        expiry_time = created_at + timedelta(seconds=ttl_seconds)
        return datetime.utcnow() > expiry_time

    def get_or_fetch_stock_quote(
        self,
        symbol: str,
        fetcher: Callable[[], StockQuote | None],
        force_refresh: bool = False,
    ) -> StockQuote | None:
        """Get stock quote from cache or fetch from API.

        Args:
            symbol: Stock symbol.
            fetcher: Function to fetch data if cache miss.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            StockQuote instance or None if not available.
        """
        if not self.is_available:
            logger.debug("Cache unavailable, fetching directly")
            return fetcher()

        if not force_refresh:
            try:
                result = self._client.table("stock_quotes").select("*").eq(
                    "symbol", symbol
                ).order("timestamp", desc=True).limit(1).execute()

                if result.data:
                    record = result.data[0]
                    ttl = self.DEFAULT_TTL["stock_quotes"]
                    if not self._is_expired(record["created_at"], ttl):
                        logger.debug(f"Cache hit for stock quote: {symbol}")
                        return StockQuote.from_dict(record)
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")

        # Cache miss or expired, fetch from API
        logger.debug(f"Cache miss for stock quote: {symbol}, fetching...")
        data = fetcher()

        if data:
            self._save_stock_quote(data)

        return data

    def _save_stock_quote(self, quote: StockQuote) -> None:
        """Save stock quote to cache."""
        if not self.is_available:
            return

        try:
            self._client.table("stock_quotes").upsert(
                quote.to_dict(),
                on_conflict="symbol,timestamp"
            ).execute()
            logger.debug(f"Cached stock quote: {quote.symbol}")
        except Exception as e:
            logger.warning(f"Failed to cache stock quote: {e}")

    def get_or_fetch_klines(
        self,
        symbol: str,
        ktype: str,
        start_date: date,
        end_date: date,
        fetcher: Callable[[], list[KlineBar]],
        force_refresh: bool = False,
    ) -> list[KlineBar]:
        """Get K-line data from cache or fetch from API.

        Args:
            symbol: Stock symbol.
            ktype: K-line type (day, 1min, etc.).
            start_date: Start date for data.
            end_date: End date for data.
            fetcher: Function to fetch data if cache miss.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            List of KlineBar instances.
        """
        if not self.is_available:
            logger.debug("Cache unavailable, fetching directly")
            return fetcher()

        if not force_refresh:
            try:
                result = self._client.table("kline_bars").select("*").eq(
                    "symbol", symbol
                ).eq("ktype", ktype).gte(
                    "timestamp", start_date.isoformat()
                ).lte(
                    "timestamp", end_date.isoformat()
                ).order("timestamp").execute()

                if result.data:
                    # Check if we have all the data we need
                    ttl = self.DEFAULT_TTL["kline_bars"]
                    if not self._is_expired(result.data[-1]["created_at"], ttl):
                        logger.debug(f"Cache hit for klines: {symbol} {ktype}")
                        return [KlineBar.from_dict(r) for r in result.data]
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")

        # Cache miss or expired, fetch from API
        logger.debug(f"Cache miss for klines: {symbol} {ktype}, fetching...")
        data = fetcher()

        if data:
            self._save_klines(data)

        return data

    def _save_klines(self, klines: list[KlineBar]) -> None:
        """Save K-line data to cache."""
        if not self.is_available or not klines:
            return

        try:
            records = [k.to_dict() for k in klines]
            self._client.table("kline_bars").upsert(
                records,
                on_conflict="symbol,ktype,timestamp"
            ).execute()
            logger.debug(f"Cached {len(klines)} kline bars")
        except Exception as e:
            logger.warning(f"Failed to cache klines: {e}")

    def get_or_fetch_option_quote(
        self,
        symbol: str,
        fetcher: Callable[[], OptionQuote | None],
        force_refresh: bool = False,
    ) -> OptionQuote | None:
        """Get option quote from cache or fetch from API.

        Args:
            symbol: Option symbol.
            fetcher: Function to fetch data if cache miss.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            OptionQuote instance or None if not available.
        """
        if not self.is_available:
            logger.debug("Cache unavailable, fetching directly")
            return fetcher()

        if not force_refresh:
            try:
                result = self._client.table("option_quotes").select("*").eq(
                    "symbol", symbol
                ).order("timestamp", desc=True).limit(1).execute()

                if result.data:
                    record = result.data[0]
                    ttl = self.DEFAULT_TTL["option_quotes"]
                    if not self._is_expired(record["created_at"], ttl):
                        logger.debug(f"Cache hit for option quote: {symbol}")
                        return OptionQuote.from_dict(record)
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")

        # Cache miss or expired, fetch from API
        logger.debug(f"Cache miss for option quote: {symbol}, fetching...")
        data = fetcher()

        if data:
            self._save_option_quote(data)

        return data

    def _save_option_quote(self, quote: OptionQuote) -> None:
        """Save option quote to cache."""
        if not self.is_available:
            return

        try:
            self._client.table("option_quotes").upsert(
                quote.to_dict(),
                on_conflict="symbol,timestamp"
            ).execute()
            logger.debug(f"Cached option quote: {quote.contract.symbol}")
        except Exception as e:
            logger.warning(f"Failed to cache option quote: {e}")

    def get_or_fetch_fundamental(
        self,
        symbol: str,
        fetcher: Callable[[], Fundamental | None],
        force_refresh: bool = False,
    ) -> Fundamental | None:
        """Get fundamental data from cache or fetch from API.

        Args:
            symbol: Stock symbol.
            fetcher: Function to fetch data if cache miss.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            Fundamental instance or None if not available.
        """
        if not self.is_available:
            logger.debug("Cache unavailable, fetching directly")
            return fetcher()

        if not force_refresh:
            try:
                result = self._client.table("fundamentals").select("*").eq(
                    "symbol", symbol
                ).order("date", desc=True).limit(1).execute()

                if result.data:
                    record = result.data[0]
                    ttl = self.DEFAULT_TTL["fundamentals"]
                    if not self._is_expired(record["created_at"], ttl):
                        logger.debug(f"Cache hit for fundamental: {symbol}")
                        return Fundamental.from_dict(record)
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")

        # Cache miss or expired, fetch from API
        logger.debug(f"Cache miss for fundamental: {symbol}, fetching...")
        data = fetcher()

        if data:
            self._save_fundamental(data)

        return data

    def _save_fundamental(self, fundamental: Fundamental) -> None:
        """Save fundamental data to cache."""
        if not self.is_available:
            return

        try:
            self._client.table("fundamentals").upsert(
                fundamental.to_dict(),
                on_conflict="symbol,date"
            ).execute()
            logger.debug(f"Cached fundamental: {fundamental.symbol}")
        except Exception as e:
            logger.warning(f"Failed to cache fundamental: {e}")

    def get_or_fetch_macro(
        self,
        indicator: str,
        data_date: date,
        fetcher: Callable[[], MacroData | None],
        force_refresh: bool = False,
    ) -> MacroData | None:
        """Get macro data from cache or fetch from API.

        Args:
            indicator: Macro indicator symbol.
            data_date: Date for the data point.
            fetcher: Function to fetch data if cache miss.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            MacroData instance or None if not available.
        """
        if not self.is_available:
            logger.debug("Cache unavailable, fetching directly")
            return fetcher()

        if not force_refresh:
            try:
                result = self._client.table("macro_data").select("*").eq(
                    "indicator", indicator
                ).eq("date", data_date.isoformat()).execute()

                if result.data:
                    record = result.data[0]
                    ttl = self.DEFAULT_TTL["macro_data"]
                    if not self._is_expired(record["created_at"], ttl):
                        logger.debug(f"Cache hit for macro: {indicator}")
                        return MacroData.from_dict(record)
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")

        # Cache miss or expired, fetch from API
        logger.debug(f"Cache miss for macro: {indicator}, fetching...")
        data = fetcher()

        if data:
            self._save_macro(data)

        return data

    def _save_macro(self, macro: MacroData) -> None:
        """Save macro data to cache."""
        if not self.is_available:
            return

        try:
            self._client.table("macro_data").upsert(
                macro.to_dict(),
                on_conflict="indicator,date"
            ).execute()
            logger.debug(f"Cached macro: {macro.indicator}")
        except Exception as e:
            logger.warning(f"Failed to cache macro: {e}")

    def clear_cache(self, table_name: str | None = None) -> None:
        """Clear cached data.

        Args:
            table_name: Specific table to clear.
                       If None, clears all cache tables.
        """
        if not self.is_available:
            return

        tables = (
            [table_name]
            if table_name
            else ["stock_quotes", "kline_bars", "option_quotes", "fundamentals", "macro_data"]
        )

        for table in tables:
            try:
                self._client.table(table).delete().neq("id", 0).execute()
                logger.info(f"Cleared cache table: {table}")
            except Exception as e:
                logger.warning(f"Failed to clear cache table {table}: {e}")
