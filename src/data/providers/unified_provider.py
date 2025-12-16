"""Unified data provider with intelligent routing and fallback support."""

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, TypeVar

from src.data.cache import DataCache
from src.data.models import (
    Fundamental,
    KlineBar,
    MacroData,
    OptionChain,
    OptionQuote,
    StockQuote,
)
from src.data.models.enums import DataType, Market
from src.data.models.option import OptionContract
from src.data.models.stock import KlineType
from src.data.providers.base import DataProvider
from src.data.providers.futu_provider import FutuProvider
from src.data.providers.ibkr_provider import IBKRProvider
from src.data.providers.routing import RoutingConfig
from src.data.providers.yahoo_provider import YahooProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


class UnifiedDataProvider:
    """Unified data provider with intelligent routing and fallback support.

    Provides a single interface for accessing market data from multiple sources.
    Automatically routes requests based on data type and market using configurable
    routing rules.

    Routing Strategy:
    - Fundamental data → Yahoo (唯一提供者)
    - Macro data → Yahoo (最全面)
    - HK stocks/options → Futu → Yahoo
    - US stocks → IBKR → Futu → Yahoo
    - US options → IBKR → Futu → Yahoo

    Features:
    - Configurable routing via YAML config file
    - Automatic fallback on provider failure
    - Warning logs before fallback
    - Caching support

    Usage:
        # Default configuration
        provider = UnifiedDataProvider()

        # Custom config file
        provider = UnifiedDataProvider(routing_config="config/routing.yaml")

        # Auto-routed requests
        quote = provider.get_stock_quote("AAPL")      # → IBKR → Futu → Yahoo
        quote = provider.get_stock_quote("HK.0700")   # → Futu → Yahoo
        fundamental = provider.get_fundamental("AAPL") # → Yahoo
    """

    def __init__(
        self,
        routing_config: RoutingConfig | str | Path | None = None,
        cache: DataCache | None = None,
        futu_provider: FutuProvider | None = None,
        ibkr_provider: IBKRProvider | None = None,
        yahoo_provider: YahooProvider | None = None,
    ) -> None:
        """Initialize unified provider with routing configuration.

        Args:
            routing_config: Routing configuration. Can be:
                - RoutingConfig instance
                - Path to YAML config file (str or Path)
                - None to use default configuration
            cache: Optional DataCache instance for caching.
            futu_provider: Optional pre-configured Futu provider.
            ibkr_provider: Optional pre-configured IBKR provider.
            yahoo_provider: Optional pre-configured Yahoo provider.
        """
        # Load routing configuration
        if isinstance(routing_config, RoutingConfig):
            self._routing = routing_config
        elif isinstance(routing_config, (str, Path)):
            self._routing = RoutingConfig(routing_config)
        else:
            self._routing = RoutingConfig()  # Use defaults

        self._cache = cache or DataCache()

        # Store provider instances
        self._providers: dict[str, DataProvider | None] = {
            "yahoo": yahoo_provider or YahooProvider(),
            "futu": futu_provider,
            "ibkr": ibkr_provider,
        }

        # Track initialization status
        self._provider_initialized: dict[str, bool] = {
            "yahoo": True,  # Yahoo is always initialized
            "futu": futu_provider is not None,
            "ibkr": ibkr_provider is not None,
        }

    # =========================================================================
    # Provider Management
    # =========================================================================

    def _get_provider(self, name: str) -> DataProvider | None:
        """Get provider instance, initializing if needed.

        Args:
            name: Provider name ('yahoo', 'futu', 'ibkr').

        Returns:
            Provider instance or None if unavailable.
        """
        if name == "yahoo":
            return self._providers["yahoo"]

        if name == "futu":
            return self._init_futu()

        if name == "ibkr":
            return self._init_ibkr()

        return None

    def _init_futu(self) -> FutuProvider | None:
        """Initialize Futu provider if not already done."""
        if self._providers["futu"] is not None:
            return self._providers["futu"]

        if self._provider_initialized.get("futu"):
            return None  # Already tried and failed

        try:
            provider = FutuProvider()
            provider.connect()
            self._providers["futu"] = provider
            self._provider_initialized["futu"] = True
            logger.info("Futu provider connected successfully")
            return provider
        except Exception as e:
            logger.warning(f"Futu provider unavailable: {e}")
            self._provider_initialized["futu"] = True
            return None

    def _init_ibkr(self) -> IBKRProvider | None:
        """Initialize IBKR provider if not already done."""
        if self._providers["ibkr"] is not None:
            return self._providers["ibkr"]

        if self._provider_initialized.get("ibkr"):
            return None  # Already tried and failed

        try:
            provider = IBKRProvider()
            provider.connect()
            self._providers["ibkr"] = provider
            self._provider_initialized["ibkr"] = True
            logger.info("IBKR provider connected successfully")
            return provider
        except Exception as e:
            logger.warning(f"IBKR provider unavailable: {e}")
            self._provider_initialized["ibkr"] = True
            return None

    # =========================================================================
    # Market Detection
    # =========================================================================

    def _detect_market(self, symbol: str) -> Market:
        """Detect market type from symbol.

        Args:
            symbol: Stock/option symbol.

        Returns:
            Market enum value.
        """
        symbol = symbol.upper()

        # HK market indicators
        if symbol.startswith("HK."):
            return Market.HK
        if symbol.endswith(".HK"):
            return Market.HK

        # Check if symbol is purely numeric (HK stock code)
        base_symbol = symbol.split(".")[-1] if "." in symbol else symbol
        if base_symbol.isdigit() and len(base_symbol) <= 5:
            return Market.HK

        # China mainland market
        if symbol.endswith(".SS") or symbol.endswith(".SZ"):
            return Market.CN
        if symbol.startswith("SH.") or symbol.startswith("SZ."):
            return Market.CN

        # Default to US market
        return Market.US

    # =========================================================================
    # Routing Logic
    # =========================================================================

    def _route(self, data_type: DataType, symbol: str) -> list[DataProvider]:
        """Route request to appropriate providers based on data type and symbol.

        Args:
            data_type: Type of data being requested.
            symbol: Symbol for market detection.

        Returns:
            List of available providers in priority order.
        """
        market = self._detect_market(symbol)
        provider_names = self._routing.select_providers(data_type, market)

        providers = []
        for name in provider_names:
            provider = self._get_provider(name)
            if provider is not None and provider.is_available:
                providers.append(provider)

        if not providers:
            logger.warning(
                f"No providers available for {data_type.value}/{market.value}, "
                f"requested: {provider_names}"
            )

        return providers

    def _execute_with_fallback(
        self,
        providers: list[DataProvider],
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute method on providers with automatic fallback.

        Args:
            providers: List of providers to try in order.
            method: Method name to call on provider.
            *args: Positional arguments for method.
            **kwargs: Keyword arguments for method.

        Returns:
            Result from first successful provider, or None.
        """
        for i, provider in enumerate(providers):
            try:
                result = getattr(provider, method)(*args, **kwargs)
                if result is not None:
                    if i > 0:
                        logger.info(f"Successfully routed {method} to {provider.name} (fallback)")
                    else:
                        logger.debug(f"Routed {method} to {provider.name}")
                    return result
                else:
                    logger.debug(f"{method} returned None from {provider.name}")
            except Exception as e:
                remaining = len(providers) - i - 1
                if remaining > 0:
                    logger.warning(
                        f"Provider {provider.name} failed for {method}: {e}, "
                        f"trying fallback ({remaining} remaining)..."
                    )
                else:
                    logger.warning(
                        f"Provider {provider.name} failed for {method}: {e}, "
                        f"no more fallbacks available"
                    )

        logger.warning(f"All providers failed for {method}")
        return None

    # =========================================================================
    # Stock Data Methods
    # =========================================================================

    def get_stock_quote(
        self, symbol: str, force_refresh: bool = False
    ) -> StockQuote | None:
        """Get real-time stock quote with intelligent routing.

        Routing:
        - HK stocks → Futu → Yahoo
        - US stocks → IBKR → Futu → Yahoo

        Args:
            symbol: Stock symbol (e.g., 'AAPL', 'HK.0700', '0700.HK').
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            StockQuote instance or None if not available.
        """
        def fetcher() -> StockQuote | None:
            providers = self._route(DataType.STOCK_QUOTE, symbol)
            return self._execute_with_fallback(providers, "get_stock_quote", symbol)

        return self._cache.get_or_fetch_stock_quote(symbol, fetcher, force_refresh)

    def get_stock_quotes(
        self, symbols: list[str], force_refresh: bool = False
    ) -> list[StockQuote]:
        """Get real-time quotes for multiple stocks.

        Each symbol is routed independently based on its market.

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
        """Get historical K-line data with intelligent routing.

        Routing:
        - HK stocks → Futu → Yahoo
        - US stocks → IBKR → Futu → Yahoo

        Args:
            symbol: Stock symbol.
            ktype: K-line type (default: day).
            start_date: Start date (default: 1 year ago).
            end_date: End date (default: today).
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            List of KlineBar instances sorted by timestamp.
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=365)

        def fetcher() -> list[KlineBar]:
            providers = self._route(DataType.HISTORY_KLINE, symbol)
            result = self._execute_with_fallback(
                providers, "get_history_kline", symbol, ktype, start_date, end_date
            )
            return result or []

        return self._cache.get_or_fetch_klines(
            symbol, ktype.value, start_date, end_date, fetcher, force_refresh
        )

    # =========================================================================
    # Option Data Methods
    # =========================================================================

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
    ) -> OptionChain | None:
        """Get option chain with intelligent routing.

        Routing:
        - HK options → Futu (only provider with HK options)
        - US options → IBKR → Futu → Yahoo

        Note: Yahoo provides option chain but no Greeks.

        Args:
            underlying: Underlying stock symbol.
            expiry_start: Optional start date for expiry filter.
            expiry_end: Optional end date for expiry filter.

        Returns:
            OptionChain instance or None if not available.
        """
        providers = self._route(DataType.OPTION_CHAIN, underlying)
        return self._execute_with_fallback(
            providers, "get_option_chain", underlying, expiry_start, expiry_end
        )

    def get_option_quote(
        self, symbol: str, force_refresh: bool = False
    ) -> OptionQuote | None:
        """Get quote for a specific option contract.

        Args:
            symbol: Option symbol.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            OptionQuote instance or None if not available.
        """
        # Extract underlying from option symbol for routing
        underlying = self._extract_underlying(symbol)

        def fetcher() -> OptionQuote | None:
            providers = self._route(DataType.OPTION_QUOTE, underlying)
            return self._execute_with_fallback(providers, "get_option_quote", symbol)

        return self._cache.get_or_fetch_option_quote(symbol, fetcher, force_refresh)

    def get_option_quotes_batch(
        self,
        contracts: list[OptionContract],
        min_volume: int | None = None,
    ) -> list[OptionQuote]:
        """Get quotes for multiple option contracts.

        Routes based on the underlying of the first contract.

        Args:
            contracts: List of option contracts.
            min_volume: Minimum volume filter (optional).

        Returns:
            List of OptionQuote instances.
        """
        if not contracts:
            return []

        # Route based on first contract's underlying
        underlying = contracts[0].underlying
        providers = self._route(DataType.OPTION_QUOTES, underlying)

        for provider in providers:
            try:
                # Check if provider has batch method
                if hasattr(provider, "get_option_quotes_batch"):
                    result = provider.get_option_quotes_batch(contracts, min_volume)
                    if result:
                        logger.debug(
                            f"get_option_quotes_batch routed to {provider.name}, "
                            f"got {len(result)} quotes"
                        )
                        return result
            except Exception as e:
                logger.warning(
                    f"Provider {provider.name} failed for get_option_quotes_batch: {e}"
                )

        logger.warning("All providers failed for get_option_quotes_batch")
        return []

    def _extract_underlying(self, option_symbol: str) -> str:
        """Extract underlying symbol from option symbol.

        Args:
            option_symbol: Option contract symbol.

        Returns:
            Underlying stock symbol.
        """
        # Option symbols typically start with underlying (e.g., AAPL20240120C00150000)
        for i, char in enumerate(option_symbol):
            if char.isdigit():
                return option_symbol[:i] if i > 0 else option_symbol[:4]
        return option_symbol[:4]

    # =========================================================================
    # Fundamental Data Methods
    # =========================================================================

    def get_fundamental(
        self, symbol: str, force_refresh: bool = False
    ) -> Fundamental | None:
        """Get fundamental data for a stock.

        Routing: Always uses Yahoo (唯一提供基本面数据).

        Args:
            symbol: Stock symbol.
            force_refresh: Force fetch from API, ignoring cache.

        Returns:
            Fundamental instance or None if not available.
        """
        def fetcher() -> Fundamental | None:
            providers = self._route(DataType.FUNDAMENTAL, symbol)
            return self._execute_with_fallback(providers, "get_fundamental", symbol)

        return self._cache.get_or_fetch_fundamental(symbol, fetcher, force_refresh)

    # =========================================================================
    # Macro Data Methods
    # =========================================================================

    def get_macro_data(
        self,
        indicator: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MacroData]:
        """Get macro economic data.

        Routing: Always uses Yahoo (最全面的宏观数据).

        Args:
            indicator: Macro indicator symbol (e.g., '^VIX', '^TNX').
            start_date: Start date (default: 30 days ago).
            end_date: End date (default: today).

        Returns:
            List of MacroData instances sorted by date.
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        providers = self._route(DataType.MACRO_DATA, indicator)
        result = self._execute_with_fallback(
            providers, "get_macro_data", indicator, start_date, end_date
        )
        return result or []

    def get_put_call_ratio(self, symbol: str = "SPY") -> float | None:
        """Get Put/Call Ratio from option chain.

        This is only available from Yahoo provider.

        Args:
            symbol: Symbol to calculate PCR for (default: SPY).

        Returns:
            Put/Call Ratio or None if unavailable.
        """
        yahoo = self._providers.get("yahoo")
        if yahoo and hasattr(yahoo, "get_put_call_ratio"):
            return yahoo.get_put_call_ratio(symbol)
        return None

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_routing_info(self, data_type: DataType, symbol: str) -> dict[str, Any]:
        """Get routing information for debugging.

        Args:
            data_type: Type of data.
            symbol: Symbol for routing.

        Returns:
            Dictionary with routing details.
        """
        market = self._detect_market(symbol)
        provider_names = self._routing.select_providers(data_type, market)

        available_providers = []
        for name in provider_names:
            provider = self._get_provider(name)
            if provider and provider.is_available:
                available_providers.append(name)

        return {
            "symbol": symbol,
            "market": market.value,
            "data_type": data_type.value,
            "configured_providers": provider_names,
            "available_providers": available_providers,
        }

    def close(self) -> None:
        """Close all provider connections."""
        if self._providers.get("futu"):
            try:
                self._providers["futu"].disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting Futu: {e}")
            self._providers["futu"] = None

        if self._providers.get("ibkr"):
            try:
                self._providers["ibkr"].disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting IBKR: {e}")
            self._providers["ibkr"] = None

    def __enter__(self) -> "UnifiedDataProvider":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
