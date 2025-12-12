"""Unified data provider with fallback support."""

import logging
from datetime import date
from typing import Callable, TypeVar

from src.data.cache import DataCache
from src.data.models import (
    Fundamental,
    KlineBar,
    MacroData,
    OptionChain,
    OptionQuote,
    StockQuote,
)
from src.data.models.stock import KlineType
from src.data.providers.base import DataProvider
from src.data.providers.futu_provider import FutuProvider
from src.data.providers.ibkr_provider import IBKRProvider
from src.data.providers.yahoo_provider import YahooProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


class UnifiedDataProvider:
    """Unified data provider with caching and fallback support.

    Provides a single interface for accessing market data from multiple sources.
    Automatically routes requests based on market:
    - US market: IBKR (primary) → Yahoo (fallback)
    - HK market: Futu (primary) → Yahoo (fallback)
    Uses caching to reduce API calls.

    Usage:
        provider = UnifiedDataProvider()
        quote = provider.get_stock_quote("AAPL")  # Uses IBKR for US stocks
        quote = provider.get_stock_quote("HK.0700")  # Uses Futu for HK stocks
    """

    def __init__(
        self,
        primary: str = "auto",
        cache: DataCache | None = None,
        futu_provider: FutuProvider | None = None,
        ibkr_provider: IBKRProvider | None = None,
        yahoo_provider: YahooProvider | None = None,
    ) -> None:
        """Initialize unified provider.

        Args:
            primary: Primary provider name ('auto', 'ibkr', 'futu', or 'yahoo').
                     'auto' uses market-based routing (IBKR for US, Futu for HK).
            cache: Optional DataCache instance for caching.
            futu_provider: Optional pre-configured Futu provider.
            ibkr_provider: Optional pre-configured IBKR provider.
            yahoo_provider: Optional pre-configured Yahoo provider.
        """
        self._primary = primary
        self._cache = cache or DataCache()
        self._futu = futu_provider
        self._ibkr = ibkr_provider
        self._yahoo = yahoo_provider or YahooProvider()

        # Track provider status
        self._futu_available = False
        self._ibkr_available = False

    def _get_futu(self) -> FutuProvider | None:
        """Get Futu provider, initializing if needed."""
        if self._futu is not None:
            return self._futu

        try:
            self._futu = FutuProvider()
            self._futu.connect()
            self._futu_available = True
            return self._futu
        except Exception as e:
            logger.warning(f"Futu provider unavailable: {e}")
            self._futu_available = False
            return None

    def _get_ibkr(self) -> IBKRProvider | None:
        """Get IBKR provider, initializing if needed."""
        if self._ibkr is not None:
            return self._ibkr

        try:
            self._ibkr = IBKRProvider()
            self._ibkr.connect()
            self._ibkr_available = True
            return self._ibkr
        except Exception as e:
            logger.warning(f"IBKR provider unavailable: {e}")
            self._ibkr_available = False
            return None

    def _is_hk_stock(self, symbol: str) -> bool:
        """Check if symbol is a Hong Kong stock.

        Args:
            symbol: Stock symbol.

        Returns:
            True if HK stock, False otherwise.
        """
        symbol = symbol.upper()
        # HK stocks have HK. prefix or are numeric (e.g., 0700, 9988)
        if symbol.startswith("HK."):
            return True
        # Remove any prefix and check if remaining is numeric
        base_symbol = symbol.split(".")[-1] if "." in symbol else symbol
        return base_symbol.isdigit()

    def _get_provider_for_symbol(self, symbol: str) -> DataProvider:
        """Get appropriate provider based on symbol and settings.

        Args:
            symbol: Stock symbol.

        Returns:
            DataProvider instance.
        """
        if self._primary == "yahoo":
            return self._yahoo
        elif self._primary == "futu":
            futu = self._get_futu()
            if futu and futu.is_available:
                return futu
            return self._yahoo
        elif self._primary == "ibkr":
            ibkr = self._get_ibkr()
            if ibkr and ibkr.is_available:
                return ibkr
            return self._yahoo
        else:
            # Auto mode: route by market
            if self._is_hk_stock(symbol):
                futu = self._get_futu()
                if futu and futu.is_available:
                    return futu
                logger.info(f"Futu unavailable for HK stock {symbol}, using Yahoo")
                return self._yahoo
            else:
                # US market: prefer IBKR
                ibkr = self._get_ibkr()
                if ibkr and ibkr.is_available:
                    return ibkr
                logger.info(f"IBKR unavailable for US stock {symbol}, using Yahoo")
                return self._yahoo

    def _get_fallback_provider(self, symbol: str) -> DataProvider:
        """Get fallback provider for symbol.

        Args:
            symbol: Stock symbol.

        Returns:
            Fallback DataProvider instance.
        """
        # Yahoo Finance is always the ultimate fallback
        return self._yahoo

    def _with_fallback(
        self,
        symbol: str,
        operation: Callable[[DataProvider], T | None],
        operation_name: str,
    ) -> T | None:
        """Execute operation with fallback to secondary provider.

        Args:
            symbol: Stock symbol for routing.
            operation: Function that takes a provider and returns result.
            operation_name: Name of operation for logging.

        Returns:
            Result from primary or fallback provider, or None.
        """
        primary = self._get_provider_for_symbol(symbol)

        try:
            result = operation(primary)
            if result is not None:
                return result
            logger.debug(
                f"{operation_name} returned None from {primary.name}, trying fallback"
            )
        except Exception as e:
            logger.warning(
                f"{operation_name} failed on {primary.name}: {e}, trying fallback"
            )

        # Try fallback
        fallback = self._get_fallback_provider(symbol)
        if fallback.name != primary.name:
            try:
                return operation(fallback)
            except Exception as e:
                logger.error(f"{operation_name} failed on fallback {fallback.name}: {e}")

        return None

    def get_stock_quote(
        self, symbol: str, force_refresh: bool = False
    ) -> StockQuote | None:
        """Get real-time stock quote with caching.

        Args:
            symbol: Stock symbol.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            StockQuote instance or None if not available.
        """
        def fetcher() -> StockQuote | None:
            return self._with_fallback(
                symbol,
                lambda p: p.get_stock_quote(symbol),
                f"get_stock_quote({symbol})",
            )

        return self._cache.get_or_fetch_stock_quote(
            symbol, fetcher, force_refresh
        )

    def get_stock_quotes(
        self, symbols: list[str], force_refresh: bool = False
    ) -> list[StockQuote]:
        """Get real-time quotes for multiple stocks.

        Args:
            symbols: List of stock symbols.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            List of StockQuote instances.
        """
        results = []
        for symbol in symbols:
            quote = self.get_stock_quote(symbol, force_refresh)
            if quote:
                results.append(quote)
        return results

    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType = KlineType.DAY,
        start_date: date | None = None,
        end_date: date | None = None,
        force_refresh: bool = False,
    ) -> list[KlineBar]:
        """Get historical K-line data with caching.

        Args:
            symbol: Stock symbol.
            ktype: K-line type (default: day).
            start_date: Start date (default: 1 year ago).
            end_date: End date (default: today).
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            List of KlineBar instances sorted by timestamp.
        """
        from datetime import timedelta

        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=365)

        def fetcher() -> list[KlineBar]:
            result = self._with_fallback(
                symbol,
                lambda p: p.get_history_kline(symbol, ktype, start_date, end_date),
                f"get_history_kline({symbol})",
            )
            return result or []

        return self._cache.get_or_fetch_klines(
            symbol, ktype.value, start_date, end_date, fetcher, force_refresh
        )

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
    ) -> OptionChain | None:
        """Get option chain for an underlying asset.

        Args:
            underlying: Underlying stock symbol.
            expiry_start: Optional start date for expiry filter.
            expiry_end: Optional end date for expiry filter.

        Returns:
            OptionChain instance or None if not available.
        """
        return self._with_fallback(
            underlying,
            lambda p: p.get_option_chain(underlying, expiry_start, expiry_end),
            f"get_option_chain({underlying})",
        )

    def get_option_quote(
        self, symbol: str, force_refresh: bool = False
    ) -> OptionQuote | None:
        """Get quote for a specific option contract with caching.

        Args:
            symbol: Option symbol.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            OptionQuote instance or None if not available.
        """
        # Extract underlying from option symbol for routing
        # Option symbols typically start with the underlying (e.g., AAPL20240120C00150000)
        underlying = ""
        for i, char in enumerate(symbol):
            if char.isdigit():
                underlying = symbol[:i]
                break
        if not underlying:
            underlying = symbol[:4]  # Default to first 4 chars

        def fetcher() -> OptionQuote | None:
            return self._with_fallback(
                underlying,
                lambda p: p.get_option_quote(symbol),
                f"get_option_quote({symbol})",
            )

        return self._cache.get_or_fetch_option_quote(
            symbol, fetcher, force_refresh
        )

    def get_fundamental(
        self, symbol: str, force_refresh: bool = False
    ) -> Fundamental | None:
        """Get fundamental data for a stock with caching.

        Args:
            symbol: Stock symbol.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            Fundamental instance or None if not available.
        """
        def fetcher() -> Fundamental | None:
            # Fundamental data is better from Yahoo
            fundamental = self._yahoo.get_fundamental(symbol)
            if fundamental:
                return fundamental
            # Try other providers as fallback (limited data)
            return self._with_fallback(
                symbol,
                lambda p: p.get_fundamental(symbol),
                f"get_fundamental({symbol})",
            )

        return self._cache.get_or_fetch_fundamental(
            symbol, fetcher, force_refresh
        )

    def get_macro_data(
        self,
        indicator: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MacroData]:
        """Get macro economic data.

        Args:
            indicator: Macro indicator symbol (e.g., ^VIX, ^TNX).
            start_date: Start date (default: 30 days ago).
            end_date: End date (default: today).

        Returns:
            List of MacroData instances sorted by date.
        """
        from datetime import timedelta

        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        # Yahoo Finance is better for macro data
        result = self._yahoo.get_macro_data(indicator, start_date, end_date)

        if not result:
            # Try IBKR for VIX and other indices
            ibkr = self._get_ibkr()
            if ibkr and ibkr.is_available:
                result = ibkr.get_macro_data(indicator, start_date, end_date)

        return result or []

    def close(self) -> None:
        """Close all provider connections."""
        if self._futu:
            self._futu.disconnect()
            self._futu = None
            self._futu_available = False

        if self._ibkr:
            self._ibkr.disconnect()
            self._ibkr = None
            self._ibkr_available = False

    def __enter__(self) -> "UnifiedDataProvider":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
