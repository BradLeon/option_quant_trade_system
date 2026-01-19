"""Unified data provider with intelligent routing and fallback support."""

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, TypeVar

from src.data.cache import DataCache, RedisCache
from src.data.models import (
    EconomicEvent,
    EventCalendar,
    Fundamental,
    KlineBar,
    MacroData,
    MarginRequirement,
    MarginSource,
    OptionChain,
    OptionQuote,
    StockQuote,
    StockVolatility,
    calc_reg_t_margin_short_call,
    calc_reg_t_margin_short_put,
)
from src.data.models.account import AccountType
from src.data.models.enums import DataType, Market
from src.data.models.option import OptionContract, OptionType
from src.data.models.stock import KlineType
from src.data.providers.base import DataProvider
from src.data.providers.economic_calendar_provider import EconomicCalendarProvider
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
        # Default configuration (uses routing.py defaults)
        provider = UnifiedDataProvider()

        # Auto-routed requests
        quote = provider.get_stock_quote("AAPL")       # US → IBKR → Yahoo
        quote = provider.get_stock_quote("0700.HK")    # HK → Futu → IBKR → Yahoo
        fundamental = provider.get_fundamental("AAPL") # → Yahoo only

    Routing Rules (see src/data/providers/routing.py):
        - US K-line: IBKR > Yahoo
        - HK K-line: Futu > IBKR > Yahoo (Futu supports HK indices 800xxx.HK)
        - HK options: Futu only
        - Fundamental: Yahoo only
    """

    def __init__(
        self,
        routing_config: RoutingConfig | str | Path | None = None,
        cache: DataCache | None = None,
        futu_provider: FutuProvider | None = None,
        ibkr_provider: IBKRProvider | None = None,
        yahoo_provider: YahooProvider | None = None,
        economic_calendar_provider: EconomicCalendarProvider | None = None,
        use_cache: bool = False,
        use_redis_cache: bool = True,
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
            economic_calendar_provider: Optional pre-configured economic calendar provider.
            use_cache: Whether to use Supabase caching. Default False (disabled).
            use_redis_cache: Whether to use Redis caching for klines/fundamentals.
                            Default True (enabled). Requires Redis server running.
        """
        # Load routing configuration
        if isinstance(routing_config, RoutingConfig):
            self._routing = routing_config
        elif isinstance(routing_config, (str, Path)):
            self._routing = RoutingConfig(routing_config)
        else:
            self._routing = RoutingConfig()  # Use defaults

        # Supabase cache is disabled by default
        self._cache = cache if use_cache else None

        # Redis cache for klines and fundamentals (enabled by default)
        self._redis_cache: RedisCache | None = None
        if use_redis_cache:
            try:
                self._redis_cache = RedisCache()
                if not self._redis_cache.is_available:
                    logger.warning(
                        "Redis cache not available, "
                        "klines/fundamentals will be fetched on every request"
                    )
                    self._redis_cache = None
            except Exception as e:
                logger.warning(f"Failed to initialize Redis cache: {e}")
                self._redis_cache = None

        # Store provider instances
        self._providers: dict[str, DataProvider | None] = {
            "yahoo": yahoo_provider or YahooProvider(),
            "futu": futu_provider,
            "ibkr": ibkr_provider,
        }

        # Economic calendar provider (FRED + static FOMC, separate from routing)
        self._economic_calendar = economic_calendar_provider

        # Track initialization status
        self._provider_initialized: dict[str, bool] = {
            "yahoo": True,  # Yahoo is always initialized
            "futu": futu_provider is not None,
            "ibkr": ibkr_provider is not None,
            "economic_calendar": economic_calendar_provider is not None,
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

    def _apply_otm_pct_filter(
        self,
        chain: "OptionChain",
        otm_pct_min: float | None,
        otm_pct_max: float | None,
    ) -> "OptionChain":
        """Apply OTM% filter to option chain.

        OTM% calculation:
        - PUT OTM%: (S - K) / S  (positive when K < S, i.e., OTM)
        - CALL OTM%: (K - S) / S  (positive when K > S, i.e., OTM)

        Args:
            chain: OptionChain to filter.
            otm_pct_min: Minimum OTM% (e.g., 0.05 = 5%).
            otm_pct_max: Maximum OTM% (e.g., 0.15 = 15%).

        Returns:
            Filtered OptionChain.
        """
        from src.data.models.option import OptionChain

        # Get underlying price - try from chain or fetch it
        underlying_price = None

        # Try to get price from provider
        try:
            stock_quote = self.get_stock_quote(chain.underlying)
            if stock_quote:
                underlying_price = stock_quote.close or stock_quote.last_price
        except Exception as e:
            logger.warning(f"Could not fetch underlying price for OTM% filter: {e}")

        if not underlying_price or underlying_price <= 0:
            logger.warning(f"No underlying price for OTM% filter, skipping filter")
            return chain

        original_puts = len(chain.puts)
        original_calls = len(chain.calls)

        def calc_otm_pct(strike: float, is_put: bool) -> float:
            """Calculate OTM% for a contract."""
            if is_put:
                # PUT OTM%: (S - K) / S
                return (underlying_price - strike) / underlying_price
            else:
                # CALL OTM%: (K - S) / S
                return (strike - underlying_price) / underlying_price

        def passes_filter(strike: float, is_put: bool) -> bool:
            """Check if contract passes OTM% filter."""
            otm_pct = calc_otm_pct(strike, is_put)
            # Only consider OTM options (positive OTM%)
            if otm_pct < 0:
                return False
            if otm_pct_min is not None and otm_pct < otm_pct_min:
                return False
            if otm_pct_max is not None and otm_pct > otm_pct_max:
                return False
            return True

        # Filter puts and calls
        filtered_puts = [
            q for q in chain.puts
            if passes_filter(q.contract.strike_price, is_put=True)
        ]
        filtered_calls = [
            q for q in chain.calls
            if passes_filter(q.contract.strike_price, is_put=False)
        ]

        logger.info(
            f"OTM% filter ({otm_pct_min:.1%}-{otm_pct_max:.1%}): "
            f"underlying=${underlying_price:.2f}, "
            f"puts {original_puts}->{len(filtered_puts)}, "
            f"calls {original_calls}->{len(filtered_calls)}"
        )

        return OptionChain(
            underlying=chain.underlying,
            timestamp=chain.timestamp,
            expiry_dates=chain.expiry_dates,
            calls=filtered_calls,
            puts=filtered_puts,
            source=chain.source,
        )

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

        if self._cache:
            return self._cache.get_or_fetch_stock_quote(symbol, fetcher, force_refresh)
        return fetcher()

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

        # Try Redis cache first (for daily klines only)
        if self._redis_cache and ktype == KlineType.DAY and not force_refresh:
            cached = self._redis_cache.get_klines(symbol, ktype.value)
            if cached:
                logger.debug(f"Redis cache hit for klines: {symbol}")
                return [KlineBar(**bar) for bar in cached]

        def fetcher() -> list[KlineBar]:
            providers = self._route(DataType.HISTORY_KLINE, symbol)
            result = self._execute_with_fallback(
                providers, "get_history_kline", symbol, ktype, start_date, end_date
            )
            return result or []

        if self._cache:
            result = self._cache.get_or_fetch_klines(
                symbol, ktype.value, start_date, end_date, fetcher, force_refresh
            )
        else:
            result = fetcher()

        # Write to Redis cache (for daily klines only)
        if self._redis_cache and ktype == KlineType.DAY and result:
            try:
                klines_data = [
                    {
                        "symbol": bar.symbol,
                        "timestamp": bar.timestamp.isoformat()
                        if hasattr(bar.timestamp, "isoformat")
                        else str(bar.timestamp),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                    for bar in result
                ]
                self._redis_cache.set_klines(symbol, ktype.value, klines_data)
            except Exception as e:
                logger.warning(f"Failed to cache klines to Redis: {e}")

        return result

    # =========================================================================
    # Option Data Methods
    # =========================================================================

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
        # ===== 统一过滤参数 =====
        expiry_min_days: int | None = None,  # IBKR 原生, Futu 转换为 expiry_start
        expiry_max_days: int | None = None,  # IBKR 原生, Futu 转换为 expiry_end
        option_type: str | None = None,  # Futu 原生, IBKR 后处理
        option_cond_type: str | None = None,  # Futu 原生 (otm/itm), IBKR 后处理
        delta_min: float | None = None,  # Futu 原生, IBKR 不支持
        delta_max: float | None = None,  # Futu 原生, IBKR 不支持
        open_interest_min: int | None = None,  # Futu 原生, IBKR 不支持
        vol_min: int | None = None,  # Futu 原生, IBKR 不支持
        strike_range_pct: float | None = None,  # IBKR 原生, Futu 忽略
        # ===== OTM% 过滤 (后处理) =====
        otm_pct_min: float | None = None,  # 最小 OTM% (如 0.05 = 5%)
        otm_pct_max: float | None = None,  # 最大 OTM% (如 0.15 = 15%)
    ) -> OptionChain | None:
        """Get option chain with intelligent routing and unified filtering.

        Routing:
        - HK options → Futu (only provider with HK options)
        - US options → IBKR → Futu → Yahoo

        Note: Yahoo provides option chain but no Greeks.

        Filter Support:
        - Futu: option_type, option_cond_type (原生), delta/OI (OptionDataFilter)
        - IBKR: expiry_min/max_days, strike_range_pct (原生), option_type/cond_type (后处理)
        - OTM%: 后处理过滤，公式: PUT=(S-K)/S, CALL=(K-S)/S

        Args:
            underlying: Underlying stock symbol.
            expiry_start: Optional start date for expiry filter.
            expiry_end: Optional end date for expiry filter.
            expiry_min_days: Minimum DTE (IBKR native, converted to expiry_start for Futu).
            expiry_max_days: Maximum DTE (IBKR native, converted to expiry_end for Futu).
            option_type: "call" / "put" / None.
            option_cond_type: "otm" (虚值) / "itm" (实值) / None.
            delta_min: Minimum delta (Futu only).
            delta_max: Maximum delta (Futu only).
            open_interest_min: Minimum open interest (Futu only).
            vol_min: Minimum volume (Futu only).
            strike_range_pct: Strike price range percentage (IBKR only).
            otm_pct_min: Minimum OTM% filter (e.g., 0.05 = 5%). PUT: (S-K)/S, CALL: (K-S)/S.
            otm_pct_max: Maximum OTM% filter (e.g., 0.15 = 15%).

        Returns:
            OptionChain instance or None if not available.
        """
        # 转换 DTE 参数为日期（用于 Futu 或覆盖显式日期）
        today = date.today()
        if expiry_min_days is not None and expiry_start is None:
            expiry_start = today + timedelta(days=expiry_min_days)
        if expiry_max_days is not None and expiry_end is None:
            expiry_end = today + timedelta(days=expiry_max_days)

        # 日期范围调试日志
        if expiry_start and expiry_end:
            span_days = (expiry_end - expiry_start).days
            logger.debug(
                f"get_option_chain {underlying}: expiry_start={expiry_start}, "
                f"expiry_end={expiry_end}, span={span_days}天"
            )
            if span_days > 30:
                logger.warning(
                    f"Futu API 日期跨度限制: {span_days}天 > 30天上限，"
                    f"Futu可能返回错误或空数据"
                )

        market = self._detect_market(underlying)
        providers = self._route(DataType.OPTION_CHAIN, underlying)

        for i, provider in enumerate(providers):
            try:
                result = None
                # 根据 provider 类型传递不同的参数
                if provider.name == "futu":
                    # Futu: 原生支持 option_type, option_cond_type, delta/OI filter
                    result = provider.get_option_chain(
                        underlying,
                        expiry_start=expiry_start,
                        expiry_end=expiry_end,
                        option_type=option_type,
                        option_cond_type=option_cond_type,
                        delta_min=delta_min,
                        delta_max=delta_max,
                        open_interest_min=open_interest_min,
                        vol_min=vol_min,
                    )
                elif provider.name == "ibkr":
                    # IBKR: 原生支持 DTE/strike_range, 后处理 option_type/cond_type
                    result = provider.get_option_chain(
                        underlying,
                        expiry_start=expiry_start,
                        expiry_end=expiry_end,
                        expiry_min_days=expiry_min_days,
                        expiry_max_days=expiry_max_days,
                        strike_range_pct=strike_range_pct,
                        option_type=option_type,
                        option_cond_type=option_cond_type,
                    )
                else:
                    # Yahoo or other providers: basic params only
                    result = provider.get_option_chain(
                        underlying,
                        expiry_start=expiry_start,
                        expiry_end=expiry_end,
                    )

                if result is not None:
                    # 检查链是否为空（calls 和 puts 都是空列表）
                    is_empty = not result.calls and not result.puts
                    if is_empty:
                        remaining = len(providers) - i - 1
                        if remaining > 0:
                            logger.debug(
                                f"get_option_chain returned empty chain from {provider.name}, "
                                f"trying fallback ({remaining} remaining)..."
                            )
                            continue  # 尝试下一个 provider
                        # 没有更多 fallback，返回空链

                    if i > 0:
                        logger.info(
                            f"Successfully routed get_option_chain to {provider.name} (fallback)"
                        )
                    else:
                        logger.debug(f"Routed get_option_chain to {provider.name}")

                    # ===== 后处理：OTM% 过滤 =====
                    # 公式: PUT OTM% = (S-K)/S, CALL OTM% = (K-S)/S
                    if otm_pct_min is not None or otm_pct_max is not None:
                        result = self._apply_otm_pct_filter(
                            result, otm_pct_min, otm_pct_max
                        )

                    return result
                else:
                    logger.debug(f"get_option_chain returned None from {provider.name}")

            except Exception as e:
                remaining = len(providers) - i - 1
                if remaining > 0:
                    logger.warning(
                        f"Provider {provider.name} failed for get_option_chain: {e}, "
                        f"trying fallback ({remaining} remaining)..."
                    )
                else:
                    logger.warning(
                        f"Provider {provider.name} failed for get_option_chain: {e}, "
                        f"no more fallbacks available"
                    )

        logger.warning("All providers failed for get_option_chain")
        return None

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

        if self._cache:
            return self._cache.get_or_fetch_option_quote(symbol, fetcher, force_refresh)
        return fetcher()

    def _detect_option_symbol_format(self, symbol: str) -> str:
        """Detect the format of an option symbol.

        Returns:
            "futu" for Futu format (HK.TCH260116C490000)
            "ibkr" for IBKR format (0700.HK20260129P00500000)
            "us" for US format (AAPL20260116C00150000)
            "unknown" if format cannot be determined
        """
        if symbol.startswith("HK.") and len(symbol) > 10:
            # Futu HK format: HK.TCH260116C490000
            return "futu"
        elif ".HK" in symbol and len(symbol) > 15:
            # IBKR HK format: 0700.HK20260129P00500000
            return "ibkr"
        elif symbol[0].isalpha() and len(symbol) > 10:
            # US format: AAPL20260116C00150000
            return "us"
        return "unknown"

    def get_option_quotes_batch(
        self,
        contracts: list[OptionContract],
        min_volume: int | None = None,
        fetch_margin: bool = False,
        underlying_price: float | None = None,
    ) -> list[OptionQuote]:
        """Get quotes for multiple option contracts.

        Routes based on the underlying of the first contract.
        Also checks symbol format compatibility with each provider.

        Args:
            contracts: List of option contracts.
            min_volume: Minimum volume filter (optional).
            fetch_margin: If True, populate margin field in quotes.
                - US market: Uses Reg T formula (accurate within 1%)
                - HK market: Uses Futu API (Reg T not applicable)
            underlying_price: Current underlying price for margin calc.
                If not provided, will try to fetch from provider.

        Returns:
            List of OptionQuote instances with optional margin data.
        """
        if not contracts:
            return []

        # Route based on first contract's underlying
        underlying = contracts[0].underlying
        providers = self._route(DataType.OPTION_QUOTES, underlying)

        # Detect symbol format from first contract
        symbol_format = self._detect_option_symbol_format(contracts[0].symbol)
        logger.debug(f"Option symbol format detected: {symbol_format} (symbol: {contracts[0].symbol})")

        for provider in providers:
            try:
                # Check symbol format compatibility
                # Futu can only handle Futu format symbols
                # IBKR can handle IBKR and US format symbols
                if provider.name == "futu" and symbol_format == "ibkr":
                    logger.debug(f"Skipping Futu provider - incompatible symbol format ({symbol_format})")
                    continue

                # Check if provider has batch method
                if hasattr(provider, "get_option_quotes_batch"):
                    result = provider.get_option_quotes_batch(contracts, min_volume)
                    if result:
                        logger.debug(
                            f"get_option_quotes_batch routed to {provider.name}, "
                            f"got {len(result)} quotes"
                        )

                        # Populate margin if requested
                        if fetch_margin and result:
                            result = self._populate_margins(
                                result, underlying, underlying_price
                            )

                        return result
            except Exception as e:
                logger.warning(
                    f"Provider {provider.name} failed for get_option_quotes_batch: {e}"
                )

        logger.warning("All providers failed for get_option_quotes_batch")
        return []

    def _populate_margins(
        self,
        quotes: list[OptionQuote],
        underlying: str,
        underlying_price: float | None = None,
    ) -> list[OptionQuote]:
        """Populate margin field for option quotes.

        Strategy:
        - US market: Use Reg T formula (verified accurate within 1%)
        - HK market: Use Futu API (Reg T is ~70% off for HK)

        Args:
            quotes: List of option quotes to populate.
            underlying: Underlying symbol for market detection.
            underlying_price: Current underlying price (optional).

        Returns:
            Same quotes with margin field populated.
        """
        from src.data.utils import SymbolFormatter

        market = SymbolFormatter.detect_market(underlying)

        # Get underlying price if not provided
        if underlying_price is None:
            stock_quote = self.get_stock_quote(underlying)
            if stock_quote:
                underlying_price = stock_quote.close or stock_quote.last_price

        if underlying_price is None:
            logger.warning(f"Could not get underlying price for {underlying}, skipping margin calc")
            return quotes

        for quote in quotes:
            try:
                premium = quote.mid_price or quote.last_price or 0
                if premium <= 0:
                    continue

                strike = quote.contract.strike_price
                lot_size = quote.contract.lot_size
                option_type = quote.contract.option_type

                if market == Market.HK:
                    # HK market: Try Futu API first, then fallback to Reg T
                    margin = None
                    symbol_format = self._detect_option_symbol_format(quote.contract.symbol)
                    if symbol_format == "futu":
                        margin = self._get_futu_margin(quote, lot_size)
                        if margin is None:
                            # Futu API returned None (e.g., CALL options may return 0)
                            logger.debug(
                                f"Futu margin API returned None for {quote.contract.symbol}, "
                                f"falling back to Reg T formula"
                            )
                    else:
                        # Symbol is in IBKR format (from fallback)
                        logger.debug(
                            f"HK symbol {quote.contract.symbol} in {symbol_format} format, "
                            f"using Reg T formula"
                        )

                    # Fallback to Reg T formula if Futu API didn't return margin
                    if margin is None:
                        if option_type == OptionType.PUT:
                            margin_per_share = calc_reg_t_margin_short_put(
                                underlying_price, strike, premium
                            )
                        else:
                            margin_per_share = calc_reg_t_margin_short_call(
                                underlying_price, strike, premium
                            )
                        margin = MarginRequirement(
                            initial_margin=margin_per_share,
                            maintenance_margin=margin_per_share * 0.8,
                            source=MarginSource.REG_T_FORMULA,
                            is_estimated=True,
                            currency="HKD",
                        )
                else:
                    # US market: Use Reg T formula
                    if option_type == OptionType.PUT:
                        margin_per_share = calc_reg_t_margin_short_put(
                            underlying_price, strike, premium
                        )
                    else:
                        margin_per_share = calc_reg_t_margin_short_call(
                            underlying_price, strike, premium
                        )

                    margin = MarginRequirement(
                        initial_margin=margin_per_share,
                        maintenance_margin=margin_per_share * 0.8,
                        source=MarginSource.REG_T_FORMULA,
                        is_estimated=True,
                        currency="USD",
                    )

                quote.margin = margin

            except Exception as e:
                logger.debug(f"Error calculating margin for {quote.contract.symbol}: {e}")

        return quotes

    def _get_futu_margin(
        self,
        quote: OptionQuote,
        lot_size: int,
    ) -> MarginRequirement | None:
        """Get margin from Futu API for HK options.

        Args:
            quote: Option quote to get margin for.
            lot_size: Contract multiplier.

        Returns:
            MarginRequirement or None if query fails.
        """
        futu_provider = self._providers.get("futu")
        if not futu_provider:
            logger.warning("Futu provider not available for margin query")
            return None

        premium = quote.mid_price or quote.last_price or 0
        if premium <= 0:
            return None

        try:
            return futu_provider.get_margin_requirement(
                option_symbol=quote.contract.symbol,
                price=premium,
                lot_size=lot_size,
                account_type=AccountType.REAL,
            )
        except Exception as e:
            logger.debug(f"Futu margin query failed for {quote.contract.symbol}: {e}")
            return None

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
        # Try Redis cache first
        if self._redis_cache and not force_refresh:
            cached = self._redis_cache.get_fundamental(symbol)
            if cached:
                logger.debug(f"Redis cache hit for fundamental: {symbol}")
                return Fundamental(**cached)

        def fetcher() -> Fundamental | None:
            providers = self._route(DataType.FUNDAMENTAL, symbol)
            return self._execute_with_fallback(providers, "get_fundamental", symbol)

        if self._cache:
            result = self._cache.get_or_fetch_fundamental(symbol, fetcher, force_refresh)
        else:
            result = fetcher()

        # Write to Redis cache
        if self._redis_cache and result:
            try:
                fundamental_data = {
                    "symbol": result.symbol,
                    "pe_ratio": result.pe_ratio,
                    "forward_pe": result.forward_pe,
                    "peg_ratio": result.peg_ratio,
                    "price_to_book": result.price_to_book,
                    "market_cap": result.market_cap,
                    "revenue": result.revenue,
                    "revenue_growth": result.revenue_growth,
                    "earnings_growth": result.earnings_growth,
                    "profit_margin": result.profit_margin,
                    "debt_to_equity": result.debt_to_equity,
                    "current_ratio": result.current_ratio,
                    "dividend_yield": result.dividend_yield,
                    "recommendation": result.recommendation,
                    "target_price": result.target_price,
                    "num_analysts": result.num_analysts,
                    "earnings_date": result.earnings_date.isoformat()
                    if result.earnings_date
                    else None,
                    "ex_dividend_date": result.ex_dividend_date.isoformat()
                    if result.ex_dividend_date
                    else None,
                }
                self._redis_cache.set_fundamental(symbol, fundamental_data)
            except Exception as e:
                logger.warning(f"Failed to cache fundamental to Redis: {e}")

        return result

    # =========================================================================
    # Stock Volatility Methods
    # =========================================================================

    def get_stock_volatility(self, symbol: str) -> StockVolatility | None:
        """Get stock-level volatility metrics.

        Routing: IBKR only (直接提供IV/HV via Tick 23/24).
        Other providers don't directly provide stock-level volatility.

        Args:
            symbol: Stock symbol.

        Returns:
            StockVolatility with IV/HV populated, or None if unavailable.
        """
        # IBKR is the only provider that directly provides stock-level volatility
        ibkr = self._get_provider("ibkr")
        if ibkr and hasattr(ibkr, 'get_stock_volatility'):
            try:
                result = ibkr.get_stock_volatility(symbol)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"IBKR get_stock_volatility failed: {e}")

        # No fallback - other providers don't support this directly
        logger.debug(f"Stock volatility not available for {symbol} (IBKR required)")
        return None

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
    # Economic Calendar Methods
    # =========================================================================

    def _init_economic_calendar(self) -> EconomicCalendarProvider | None:
        """Initialize economic calendar provider if not already done."""
        if self._economic_calendar is not None:
            return self._economic_calendar

        if self._provider_initialized.get("economic_calendar"):
            return None  # Already tried and failed

        try:
            provider = EconomicCalendarProvider()
            if provider.is_available:
                self._economic_calendar = provider
                self._provider_initialized["economic_calendar"] = True
                logger.info("Economic calendar provider initialized successfully")
                return provider
            else:
                logger.warning("Economic calendar provider not available (no FRED API key or FOMC calendar)")
                self._provider_initialized["economic_calendar"] = True
                return None
        except Exception as e:
            logger.warning(f"Economic calendar provider unavailable: {e}")
            self._provider_initialized["economic_calendar"] = True
            return None

    def get_economic_calendar(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        country: str | None = "US",
    ) -> EventCalendar | None:
        """Get economic calendar for a date range.

        Uses FRED API + static FOMC calendar for economic event data.

        Args:
            start_date: Start date (default: today).
            end_date: End date (default: 30 days from start).
            country: Country filter (default: "US").

        Returns:
            EventCalendar instance or None if unavailable.
        """
        if start_date is None:
            start_date = date.today()
        if end_date is None:
            end_date = start_date + timedelta(days=30)

        calendar_provider = self._init_economic_calendar()
        if calendar_provider is None:
            logger.warning("Economic calendar provider not available")
            return None

        try:
            return calendar_provider.get_economic_calendar(start_date, end_date, country=country)
        except Exception as e:
            logger.error(f"Failed to get economic calendar: {e}")
            return None

    def get_market_moving_events(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[EconomicEvent]:
        """Get market-moving events (FOMC, CPI, NFP).

        Convenience method for getting high-impact events.

        Args:
            start_date: Start date (default: today).
            end_date: End date (default: 30 days from start).

        Returns:
            List of market-moving events.
        """
        if start_date is None:
            start_date = date.today()
        if end_date is None:
            end_date = start_date + timedelta(days=30)

        calendar_provider = self._init_economic_calendar()
        if calendar_provider is None:
            return []

        try:
            return calendar_provider.get_market_moving_events(start_date, end_date)
        except Exception as e:
            logger.error(f"Failed to get market-moving events: {e}")
            return []

    def check_macro_blackout(
        self,
        target_date: date | None = None,
        blackout_days: int = 2,
        blackout_events: list[str] | None = None,
    ) -> tuple[bool, list[EconomicEvent]]:
        """Check if date is in macro event blackout period.

        Args:
            target_date: Date to check (default: today).
            blackout_days: Days before event to avoid.
            blackout_events: Event types to check (default: FOMC, CPI, NFP).

        Returns:
            Tuple of (is_in_blackout, list of events causing blackout).
        """
        if target_date is None:
            target_date = date.today()

        calendar_provider = self._init_economic_calendar()
        if calendar_provider is None:
            # Fail-open: if we can't check, assume no blackout
            logger.warning("Cannot check macro blackout - economic calendar unavailable")
            return False, []

        try:
            return calendar_provider.check_blackout_period(
                target_date, blackout_days, blackout_events
            )
        except Exception as e:
            logger.error(f"Failed to check macro blackout: {e}")
            return False, []

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
