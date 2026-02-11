"""IBKR TWS API data provider implementation."""

import logging
import math
import os
from re import S
import time
from datetime import date, datetime, timedelta
from functools import wraps
from threading import Lock
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

from dotenv import load_dotenv

from src.data.models import (
    AccountCash,
    AccountPosition,
    AccountSummary,
    AccountType,
    AssetType,
    Fundamental,
    KlineBar,
    MacroData,
    Market,
    OptionChain,
    OptionQuote,
    StockQuote,
    StockVolatility,
)
from src.data.models.option import Greeks, OptionContract, OptionType
from src.data.models.stock import KlineType
from src.data.providers.base import (
    AccountProvider,
    ConnectionError,
    DataNotFoundError,
    DataProvider,
)
from src.data.utils import SymbolFormatter

logger = logging.getLogger(__name__)

# Try to import ib_async, but allow graceful degradation
try:
    from ib_async import IB, Contract, Option, Stock, util
    IBKR_AVAILABLE = True
    # Configure ib_async to use Python's logging
    # Suppress default ib_async logging to avoid duplicate/encoded messages
    logging.getLogger("ib_async").setLevel(logging.CRITICAL)
except ImportError:
    IBKR_AVAILABLE = False
    logger.warning("ib_async not installed. IBKR provider will be unavailable.")


# Mapping from our KlineType to IBKR bar sizes
KLINE_TYPE_MAP = {
    KlineType.MIN_1: "1 min",
    KlineType.MIN_5: "5 mins",
    KlineType.MIN_15: "15 mins",
    KlineType.MIN_30: "30 mins",
    KlineType.MIN_60: "1 hour",
    KlineType.DAY: "1 day",
    KlineType.WEEK: "1 week",
    KlineType.MONTH: "1 month",
}

# Duration strings for historical data requests
KLINE_DURATION_MAP = {
    KlineType.MIN_1: "1 D",
    KlineType.MIN_5: "1 D",
    KlineType.MIN_15: "2 D",
    KlineType.MIN_30: "5 D",
    KlineType.MIN_60: "10 D",
    KlineType.DAY: "1 Y",
    KlineType.WEEK: "2 Y",
    KlineType.MONTH: "5 Y",
}


def auto_reconnect(func: F) -> F:
    """Decorator: auto-reconnect on connection failure.

    Detects connection issues and attempts to reconnect once before retrying.
    """

    @wraps(func)
    def wrapper(self: "IBKRProvider", *args: Any, **kwargs: Any) -> Any:
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            # Check for connection-related errors
            if any(
                keyword in error_msg
                for keyword in ["not connected", "timeout", "connection", "socket"]
            ):
                logger.warning(
                    f"Connection issue detected in {func.__name__}: {e}, "
                    "attempting reconnect..."
                )
                if self.reconnect(max_retries=2, initial_delay=2.0):
                    logger.info(f"Reconnected, retrying {func.__name__}")
                    return func(self, *args, **kwargs)
            raise

    return wrapper  # type: ignore


class IBKRProvider(DataProvider, AccountProvider):
    """IBKR TWS API data provider.

    Requires TWS or IB Gateway to be running locally.
    Supports both market data and account/position queries.

    Usage:
        with IBKRProvider() as provider:
            quote = provider.get_stock_quote("AAPL")
            positions = provider.get_positions()
    """

    # Port mapping for account types
    # TWS ports: Paper=7497, Live=7496
    # Gateway ports: Paper=4002, Live=4001
    # Default to TWS ports (set IBKR_APP_TYPE=gateway to use Gateway ports)
    TWS_PAPER_PORT = 7497
    TWS_LIVE_PORT = 7496
    GATEWAY_PAPER_PORT = 4002
    GATEWAY_LIVE_PORT = 4001

    @classmethod
    def _get_ports(cls) -> tuple[int, int]:
        """Get paper and live ports based on IBKR_APP_TYPE setting.

        Returns:
            Tuple of (paper_port, live_port)
        """
        app_type = os.getenv("IBKR_APP_TYPE", "tws").lower()
        if app_type == "gateway":
            return cls.GATEWAY_PAPER_PORT, cls.GATEWAY_LIVE_PORT
        return cls.TWS_PAPER_PORT, cls.TWS_LIVE_PORT

    @property
    def PAPER_PORT(self) -> int:  # noqa: N802
        """Paper trading port (depends on IBKR_APP_TYPE)."""
        return self._get_ports()[0]

    @property
    def LIVE_PORT(self) -> int:  # noqa: N802
        """Live trading port (depends on IBKR_APP_TYPE)."""
        return self._get_ports()[1]

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        timeout: int = 30,
        account_type: AccountType = AccountType.LIVE,
    ) -> None:
        """Initialize IBKR provider.

        Args:
            host: TWS/Gateway host. Defaults to env var or 127.0.0.1.
            port: TWS/Gateway port. If not specified, auto-selects based on account_type.
            client_id: Client ID for connection. Defaults to PID-based unique ID.
            timeout: Request timeout in seconds.
            account_type: Account type (PAPER or REAL). Used to auto-select port if not specified.
        """
        load_dotenv()

        self._host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self._account_type = account_type

        # Auto-select port based on account_type
        # Priority: explicit port > account_type-based > env var > default (live)
        # Get ports based on IBKR_APP_TYPE (tws or gateway)
        paper_port, live_port = self._get_ports()

        if port is not None:
            self._port = port
        elif account_type is not None:
            # When account_type is explicitly specified, use the corresponding port
            # This takes priority over env var to ensure correct account connection
            self._port = paper_port if account_type == AccountType.PAPER else live_port
        else:
            env_port = os.getenv("IBKR_PORT")
            if env_port:
                self._port = int(env_port)
            else:
                # Default to live port if nothing specified
                self._port = live_port

        # Generate unique clientId based on process ID to avoid conflicts
        # TWS GUI uses 0, other apps commonly use 1-10
        # Use PID modulo to get a number in range 100-999
        default_client_id = 100 + (os.getpid() % 900)
        self._client_id = client_id if client_id is not None else default_client_id
        self._timeout = timeout
        self._ib: Any = None
        self._connected = False
        self._lock = Lock()

    @property
    def name(self) -> str:
        """Provider name."""
        return "ibkr"

    @property
    def is_available(self) -> bool:
        """Check if provider is available with active health check."""
        if not IBKR_AVAILABLE:
            return False
        if not self._connected:
            return False
        # Perform active health check
        return self._check_connection_health()

    def _check_connection_health(self) -> bool:
        """Lightweight connection health check.

        Uses managedAccounts() as a heartbeat to verify connection is alive.
        """
        try:
            if self._ib is None:
                self._connected = False
                return False
            # managedAccounts() is a lightweight call that verifies connection
            accounts = self._ib.managedAccounts()
            return accounts is not None and len(accounts) > 0
        except Exception as e:
            logger.warning(f"Connection health check failed: {e}")
            self._connected = False
            return False

    def __enter__(self) -> "IBKRProvider":
        """Enter context manager, establish connection."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager, close connection."""
        self.disconnect()

    def connect(self) -> None:
        """Establish connection to TWS/Gateway."""
        if not IBKR_AVAILABLE:
            raise ConnectionError("ib_async is not installed")

        with self._lock:
            if self._connected:
                return

            try:
                self._ib = IB()
                self._ib.connect(
                    self._host,
                    self._port,
                    clientId=self._client_id,
                    timeout=self._timeout,
                )
                self._connected = True
                logger.info(
                    f"Connected to IBKR TWS at {self._host}:{self._port} "
                    f"(clientId={self._client_id})"
                )
            except Exception as e:
                self._connected = False
                raise ConnectionError(f"Failed to connect to TWS/Gateway: {e}")

    def disconnect(self) -> None:
        """Close connection to TWS/Gateway."""
        with self._lock:
            if self._ib:
                try:
                    self._ib.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting from IBKR: {e}")
                finally:
                    self._ib = None
                    self._connected = False
                    logger.info("Disconnected from IBKR TWS")

    def _ensure_connected(self) -> None:
        """Ensure connection is established."""
        if not self._connected:
            self.connect()

    def _create_stock_contract(self, symbol: str) -> Any:
        """Create a stock contract for IBKR API.

        Args:
            symbol: Stock symbol (e.g., 'AAPL', '0700.HK').

        Returns:
            Stock contract object.
        """
        # Use SymbolFormatter to get IBKR contract parameters
        contract = SymbolFormatter.to_ibkr_contract(symbol)
        return Stock(contract.symbol, contract.exchange, contract.currency)

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to standard format.

        Keeps HK suffix for Hong Kong stocks to preserve market info.

        Args:
            symbol: Stock symbol.

        Returns:
            Symbol in standard format.
        """
        # Use SymbolFormatter for consistent normalization
        return SymbolFormatter.to_standard(symbol)

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """Get real-time stock quote."""
        quotes = self.get_stock_quotes([symbol])
        return quotes[0] if quotes else None

    @auto_reconnect
    def get_stock_quotes(self, symbols: list[str]) -> list[StockQuote]:
        """Get real-time quotes for multiple stocks."""
        self._ensure_connected()

        results = []
        for symbol in symbols:
            try:
                normalized = self.normalize_symbol(symbol)
                contract = self._create_stock_contract(normalized)

                # Qualify the contract
                qualified = self._ib.qualifyContracts(contract)
                if not qualified or not contract.conId:
                    logger.warning(f"Could not qualify contract for {symbol}")
                    continue

                # Request market data with generic tick 221 (Mark Price) for HK stocks
                ticker = self._ib.reqMktData(contract, "221", False, False)

                # Wait for data with timeout (10 seconds for HK market)
                timeout_count = 0
                while ticker.last != ticker.last and timeout_count < 100:  # NaN check
                    self._ib.sleep(0.1)
                    timeout_count += 1

                # Also try to get snapshot if streaming didn't work
                if ticker.last != ticker.last:
                    self._ib.sleep(1)

                # Improved close price retrieval with multiple fallbacks
                close_price = None
                # 1. Priority: last price
                if ticker.last == ticker.last:
                    close_price = ticker.last
                # 2. Fallback: prev close
                elif ticker.close == ticker.close:
                    close_price = ticker.close
                # 3. Fallback: bid/ask midpoint
                elif ticker.bid == ticker.bid and ticker.ask == ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                    close_price = (ticker.bid + ticker.ask) / 2
                    logger.debug(f"Using bid/ask midpoint for {normalized}: {close_price}")
                # 4. Fallback: markPrice (from generic tick 221)
                elif hasattr(ticker, 'markPrice') and ticker.markPrice == ticker.markPrice:
                    close_price = ticker.markPrice
                    logger.debug(f"Using markPrice for {normalized}: {close_price}")

                quote = StockQuote(
                    symbol=normalized,
                    timestamp=datetime.now(),
                    open=ticker.open if ticker.open == ticker.open else None,
                    high=ticker.high if ticker.high == ticker.high else None,
                    low=ticker.low if ticker.low == ticker.low else None,
                    close=close_price,
                    volume=int(ticker.volume) if ticker.volume == ticker.volume else None,
                    prev_close=ticker.close if ticker.close == ticker.close else None,
                    source=self.name,
                )
                # Store bid/ask as attributes for later use (not in base model)
                quote._bid = ticker.bid if ticker.bid == ticker.bid else None
                quote._ask = ticker.ask if ticker.ask == ticker.ask else None
                results.append(quote)

                # Cancel market data subscription
                self._ib.cancelMktData(contract)

            except Exception as e:
                logger.error(f"Error getting quote for {symbol}: {e}")

        return results

    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """Get historical K-line data."""
        self._ensure_connected()

        symbol = self.normalize_symbol(symbol)
        bar_size = KLINE_TYPE_MAP.get(ktype)

        if bar_size is None:
            logger.error(f"Unsupported K-line type: {ktype}")
            return []

        try:
            contract = self._create_stock_contract(symbol)
            qualified = self._ib.qualifyContracts(contract)
            if not qualified or not contract.conId:
                logger.warning(f"Could not qualify contract for {symbol}")
                return []

            # Calculate duration based on date range
            days = (end_date - start_date).days + 1
            if days <= 1:
                duration = "1 D"
            elif days <= 7:
                duration = f"{days} D"
            elif days <= 30:
                duration = f"{(days + 6) // 7} W"
            elif days <= 365:
                duration = f"{(days + 29) // 30} M"
            else:
                duration = f"{(days + 364) // 365} Y"

            # Request historical data
            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime=end_date.strftime("%Y%m%d 23:59:59"),
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )

            results = []
            for bar in bars:
                # Filter by date range
                bar_date = bar.date
                if isinstance(bar_date, datetime):
                    bar_dt = bar_date
                else:
                    bar_dt = datetime.strptime(str(bar_date), "%Y-%m-%d")

                if start_date <= bar_dt.date() <= end_date:
                    kline = KlineBar(
                        symbol=symbol,
                        timestamp=bar_dt,
                        ktype=ktype,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=int(bar.volume),
                        source=self.name,
                    )
                    results.append(kline)

            return sorted(results, key=lambda x: x.timestamp)

        except Exception as e:
            logger.error(f"Error getting history kline for {symbol}: {e}")
            return []

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
        expiry_min_days: int | None = 15,
        expiry_max_days: int | None = 45,
        strike_range_pct: float | None = 0.20,
        strike_min: float | None = None,
        strike_max: float | None = None,
        # ===== 统一过滤参数（后处理实现） =====
        option_type: str | None = None,  # "call" / "put" / None
        option_cond_type: str | None = None,  # "otm" / "itm" / None
    ) -> OptionChain | None:
        """Get option chain structure for an underlying asset.

        Returns option contracts without market data. Use get_option_quotes_batch()
        to fetch actual quotes for selected contracts.

        Args:
            underlying: Underlying symbol (e.g., "AAPL")
            expiry_start: Earliest expiry date (inclusive)
            expiry_end: Latest expiry date (inclusive)
            expiry_min_days: Minimum days to expiry (default 15)
            expiry_max_days: Maximum days to expiry (default 45)
            strike_range_pct: Filter strikes within ±X% of underlying price (default 20%)
            strike_min: Minimum strike price (overrides strike_range_pct)
            strike_max: Maximum strike price (overrides strike_range_pct)
            option_type: "call" / "put" / None (None = all) - 后处理过滤
            option_cond_type: "otm" (虚值) / "itm" (实值) / None - 后处理过滤

        Returns:
            OptionChain with contract structure (no market data)
        """
        self._ensure_connected()

        underlying = self.normalize_symbol(underlying)

        try:
            # Create and qualify stock contract
            stock = self._create_stock_contract(underlying)
            qualified = self._ib.qualifyContracts(stock)
            if not qualified or not stock.conId:
                logger.warning(f"Could not qualify contract for {underlying}")
                return None

            # Get option chain parameters
            chains = self._ib.reqSecDefOptParams(
                stock.symbol, "", stock.secType, stock.conId
            )

            if not chains:
                logger.warning(f"No option chain found for {underlying}")
                return None

            # Detect market for exchange selection
            market = SymbolFormatter.detect_market(underlying)

            # Debug: log all available chains
            logger.debug(f"IBKR {underlying} found {len(chains)} chains:")
            for i, c in enumerate(chains):
                tc = getattr(c, 'tradingClass', 'N/A')
                exp_count = len(c.expirations) if c.expirations else 0
                exp_sample = c.expirations[:3] if c.expirations else []
                logger.debug(f"  Chain[{i}]: exchange={c.exchange}, tradingClass={tc}, "
                            f"expirations={exp_count} (sample: {exp_sample})")

            # Find the chain with the most expirations for US stocks (weekly options)
            # For HK stocks, still prefer SEHK exchange
            chain = None
            preferred_exchange = "SEHK" if market == Market.HK else "SMART"

            if market != Market.HK:
                # US stocks: find chain with most expirations (to include weeklies)
                best_chain = None
                max_expirations = 0
                for c in chains:
                    exp_count = len(c.expirations) if c.expirations else 0
                    if exp_count > max_expirations:
                        max_expirations = exp_count
                        best_chain = c
                if best_chain:
                    chain = best_chain
                    logger.debug(f"Selected chain with most expirations: "
                                f"tradingClass={getattr(chain, 'tradingClass', 'N/A')}, "
                                f"expirations={max_expirations}")
            else:
                # HK stocks: prefer SEHK exchange
                for c in chains:
                    if c.exchange == preferred_exchange:
                        chain = c
                        break

            if chain is None:
                chain = chains[0]

            # Extract trading class (important for HK options like "TCH" for 700)
            trading_class = getattr(chain, 'tradingClass', None)
            if trading_class:
                logger.debug(f"Trading class for {underlying}: {trading_class}")

            # Extract multiplier (lot_size) from chain
            lot_size = 100  # default
            chain_multiplier = getattr(chain, 'multiplier', None)
            if chain_multiplier:
                try:
                    lot_size = int(chain_multiplier)
                    logger.debug(f"Multiplier for {underlying}: {chain_multiplier} -> lot_size={lot_size}")
                except (ValueError, TypeError):
                    pass

            # Convert expiry_min_days/max_days to dates
            # ONLY apply min/max days defaults if expiry_start/expiry_end are not provided
            today = date.today()
            if expiry_start is None and expiry_min_days is not None:
                expiry_start = today + timedelta(days=expiry_min_days)
            if expiry_end is None and expiry_max_days is not None:
                expiry_end = today + timedelta(days=expiry_max_days)

            # Filter expirations by date range
            expirations = []

            # Debug: log available expirations and filter range
            logger.debug(f"IBKR {underlying} available expirations: {chain.expirations[:10]}...")
            logger.debug(f"IBKR filter range: {expiry_start} to {expiry_end} (today={today})")

            for exp in chain.expirations:
                exp_date = datetime.strptime(exp, "%Y%m%d").date()
                if expiry_start and exp_date < expiry_start:
                    continue
                if expiry_end and exp_date > expiry_end:
                    continue
                expirations.append(exp_date)

            if not expirations:
                logger.warning(f"No expirations found in specified range for {underlying}. "
                              f"Available: {chain.expirations[:5]}, Range: {expiry_start} to {expiry_end}")
                return None

            # Get underlying price for strike filtering
            ticker = self._ib.reqMktData(stock, "", False, False)
            self._ib.sleep(1)
            underlying_price = ticker.last if ticker.last == ticker.last else ticker.close
            if underlying_price != underlying_price:  # NaN check
                underlying_price = 100  # Fallback
            self._ib.cancelMktData(stock)

            # Filter strikes
            all_strikes = sorted(chain.strikes)

            # Apply strike_min/max if specified
            if strike_min is not None or strike_max is not None:
                s_min = strike_min if strike_min is not None else 0
                s_max = strike_max if strike_max is not None else float('inf')
                strikes = [s for s in all_strikes if s_min <= s <= s_max]
            elif strike_range_pct is not None:
                # Apply percentage range around underlying price
                strike_range = underlying_price * strike_range_pct
                strikes = [
                    s for s in all_strikes
                    if underlying_price - strike_range <= s <= underlying_price + strike_range
                ]
            else:
                strikes = all_strikes

            # Build option contracts
            calls = []
            puts = []
            expiry_dates = sorted(expirations)

            for expiry in expiry_dates:
                exp_str = expiry.strftime("%Y%m%d")
                for strike in strikes:
                    for right in ["C", "P"]:
                        try:
                            contract = OptionContract(
                                symbol=f"{underlying}{exp_str}{right}{int(strike*1000):08d}",
                                underlying=underlying,
                                option_type=OptionType.CALL if right == "C" else OptionType.PUT,
                                strike_price=strike,
                                expiry_date=expiry,
                                lot_size=lot_size,  # From chain.multiplier
                                trading_class=trading_class,  # For HK options (e.g., "TCH")
                            )
                            # Create OptionQuote with contract info only (no market data)
                            quote = OptionQuote(
                                contract=contract,
                                timestamp=datetime.now(),
                                source=self.name,
                            )
                            if right == "C":
                                calls.append(quote)
                            else:
                                puts.append(quote)
                        except Exception as e:
                            logger.debug(f"Error creating option contract: {e}")

            # ===== 后处理：option_type 过滤 =====
            if option_type:
                opt_type_lower = option_type.lower()
                if opt_type_lower == "call":
                    puts = []
                elif opt_type_lower == "put":
                    calls = []

            # ===== 后处理：option_cond_type 过滤 (OTM/ITM) =====
            if option_cond_type:
                cond_lower = option_cond_type.lower()
                if cond_lower == "otm":
                    # PUT OTM: strike < underlying_price
                    # CALL OTM: strike > underlying_price
                    puts = [
                        q for q in puts
                        if q.contract.strike_price < underlying_price
                    ]
                    calls = [
                        q for q in calls
                        if q.contract.strike_price > underlying_price
                    ]
                elif cond_lower == "itm":
                    # PUT ITM: strike > underlying_price
                    # CALL ITM: strike < underlying_price
                    puts = [
                        q for q in puts
                        if q.contract.strike_price > underlying_price
                    ]
                    calls = [
                        q for q in calls
                        if q.contract.strike_price < underlying_price
                    ]

            logger.info(f"Option chain for {underlying}: {len(expiry_dates)} expiries, "
                       f"{len(calls)} calls, {len(puts)} puts (underlying=${underlying_price:.2f})")

            return OptionChain(
                underlying=underlying,
                timestamp=datetime.now(),
                expiry_dates=expiry_dates,
                calls=calls,
                puts=puts,
                source=self.name,
            )

        except Exception as e:
            logger.error(f"Error getting option chain for {underlying}: {e}")
            return None

    def get_option_quotes_batch(
        self,
        contracts: list[OptionContract],
        min_volume: int | None = None,
        request_delay: float = 0.5,
    ) -> list[OptionQuote]:
        """Fetch market data for multiple option contracts using batch parallel processing.

        Optimized for IBKR: subscribes to underlying + option contracts simultaneously,
        waits for Greeks to populate, then extracts all data.

        IMPORTANT: IBKR requires market data subscriptions for BOTH the option AND
        the underlying contract to receive live Greek values.

        Args:
            contracts: List of OptionContract to fetch quotes for
            min_volume: Filter out options with volume below this (post-fetch filter)
            request_delay: Unused, kept for API compatibility

        Returns:
            List of OptionQuote with market data (Greeks, prices, volume, etc.)
        """
        self._ensure_connected()

        if not contracts:
            return []

        results = []
        skipped_contracts = 0
        filtered_by_volume = 0
        api_greeks_count = 0
        bs_fallback_count = 0

        # Batch size: 20 contracts per batch
        # NOTE: 减小批次以避免超过 IBKR 100 条并发市场数据限制
        # 预留空间给其他订阅（持仓监控、底层股票等）
        BATCH_SIZE = 20
        WAIT_SECONDS = 5  # Wait time for Greeks to populate

        total_batches = (len(contracts) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Fetching quotes for {len(contracts)} contracts in {total_batches} batches...")

        # NOTE: Underlying subscription disabled - testing showed it may interfere with
        # option data retrieval during non-market hours. Greeks can still be computed
        # via Black-Scholes fallback when API Greeks unavailable.
        underlying_tickers: dict[str, tuple[any, any]] = {}

        import time as _time

        # Pre-fetch underlying data for all unique underlyings (optimization for BS fallback)
        # This avoids repeated get_stock_volatility() calls for the same underlying
        unique_underlyings = set(c.underlying for c in contracts)
        underlying_cache: dict[str, dict] = {}  # {underlying: {price, iv}}

        if len(unique_underlyings) <= 10:  # Only pre-fetch if reasonable number
            logger.info(f"Pre-fetching data for {len(unique_underlyings)} unique underlyings...")
            for underlying in unique_underlyings:
                try:
                    underlying_symbol = SymbolFormatter.to_standard(underlying)
                    cache_entry = {"price": None, "iv": None}

                    # Get price
                    stock_quote = self.get_stock_quote(underlying_symbol)
                    if stock_quote and stock_quote.close is not None:
                        try:
                            if not math.isnan(stock_quote.close):
                                cache_entry["price"] = stock_quote.close
                        except (TypeError, ValueError):
                            pass

                    # Get volatility
                    vol_data = self.get_stock_volatility(underlying_symbol, include_iv_rank=False)
                    if vol_data:
                        cache_entry["iv"] = vol_data.iv or vol_data.hv

                    underlying_cache[underlying] = cache_entry
                    logger.debug(f"Cached {underlying}: price={cache_entry['price']}, iv={cache_entry['iv']}")
                except Exception as e:
                    logger.warning(f"Failed to pre-fetch data for {underlying}: {e}")

            logger.info(f"Pre-fetch complete: {len(underlying_cache)} underlyings cached")

        batch_start_time = _time.time()

        for batch_start in range(0, len(contracts), BATCH_SIZE):
            batch_contracts = contracts[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1

            logger.info(f"[Batch {batch_num}/{total_batches}] Processing {len(batch_contracts)} contracts...")

            # Phase 1: Create and qualify all IBKR Option contracts
            qualified_items: list[tuple[OptionContract, Option]] = []

            for contract in batch_contracts:
                try:
                    market = SymbolFormatter.detect_market(contract.underlying)
                    underlying_symbol = SymbolFormatter.to_ibkr_symbol(contract.underlying)

                    if market == Market.HK:
                        trading_class = contract.trading_class
                        if not trading_class:
                            logger.debug(f"No trading class for {contract.symbol}, skipping")
                            skipped_contracts += 1
                            continue

                        expiry_str = contract.expiry_date.strftime("%Y%m%d")
                        right = "C" if contract.option_type == OptionType.CALL else "P"

                        opt = Option(
                            underlying_symbol,
                            expiry_str,
                            contract.strike_price,
                            right,
                            "SEHK",
                            currency="HKD",
                        )
                        opt.tradingClass = trading_class
                    else:
                        # US options
                        opt = Option(
                            underlying_symbol,
                            contract.expiry_date.strftime("%Y%m%d"),
                            contract.strike_price,
                            "C" if contract.option_type == OptionType.CALL else "P",
                            "SMART",
                        )
                        # Set tradingClass if available (important for weeklies vs standard)
                        if contract.trading_class:
                            opt.tradingClass = contract.trading_class
                            logger.debug(f"Using tradingClass={contract.trading_class} for {contract.symbol}")

                    # Qualify contract (this can block - log progress)
                    qualify_start = _time.time()
                    qualified = self._ib.qualifyContracts(opt)
                    qualify_elapsed = _time.time() - qualify_start

                    if qualify_elapsed > 5:
                        logger.warning(f"qualifyContracts for {contract.symbol} took {qualify_elapsed:.1f}s")

                    if not qualified or not hasattr(opt, 'conId') or not opt.conId:
                        logger.debug(f"Contract not found: {contract.symbol}")
                        skipped_contracts += 1
                        continue

                    # Log qualified contract details for debugging
                    if batch_num == 1 and len(qualified_items) < 3:
                        logger.debug(
                            f"Qualified: {opt.localSymbol}, conId={opt.conId}, "
                            f"exchange={opt.exchange}, tradingClass={opt.tradingClass}, "
                            f"multiplier={opt.multiplier}"
                        )

                    qualified_items.append((contract, opt))

                except Exception as e:
                    logger.warning(f"Error qualifying {contract.symbol}: {e}")
                    skipped_contracts += 1

            if not qualified_items:
                continue

            # Phase 2: Subscribe to all contracts in batch (parallel)
            # NOTE: 必须使用 snapshot=False，因为 generic ticks 不支持 snapshot 模式
            tickers: list[tuple[OptionContract, Option, any]] = []
            for contract, opt in qualified_items:
                ticker = self._ib.reqMktData(opt, "100,101,104,106", snapshot=False, regulatorySnapshot=False)
                tickers.append((contract, opt, ticker))

            # Phase 3: Wait once for all Greeks to populate
            logger.debug(f"Waiting {WAIT_SECONDS}s for Greeks on {len(tickers)} contracts...")
            for _ in range(WAIT_SECONDS):
                self._ib.sleep(1)
                # Check if most have Greeks
                greeks_count = sum(1 for _, _, t in tickers if t.modelGreeks or t.bidGreeks or t.askGreeks)
                if greeks_count >= len(tickers) * 0.8:  # 80% threshold
                    logger.debug(f"Early exit: {greeks_count}/{len(tickers)} have Greeks")
                    break

            # Phase 4: Log Greeks status for first few contracts
            greeks_status = []
            for _, opt, ticker in tickers[:3]:
                has_model = ticker.modelGreeks is not None
                has_bid = ticker.bidGreeks is not None
                has_ask = ticker.askGreeks is not None
                # Also log price data to verify we're getting any data at all
                bid = ticker.bid if ticker.bid == ticker.bid else None
                ask = ticker.ask if ticker.ask == ticker.ask else None
                last = ticker.last if ticker.last == ticker.last else None
                # Check for market data errors
                has_error = hasattr(ticker, 'marketDataType') or hasattr(ticker, 'errorCode')
                error_info = ""
                if hasattr(ticker, 'marketDataType'):
                    error_info += f",mktType={ticker.marketDataType}"
                greeks_status.append(
                    f"{opt.localSymbol}(M={has_model},B={has_bid},A={has_ask},"
                    f"bid={bid},ask={ask},last={last}{error_info})"
                )
            logger.debug(f"Ticker data: {'; '.join(greeks_status)}")

            # Phase 4: Extract data from all tickers
            for contract, opt, ticker in tickers:
                try:
                    # Extract Greeks
                    greeks = None
                    iv = None
                    mg = ticker.modelGreeks or ticker.bidGreeks or ticker.askGreeks

                    if mg and mg.delta == mg.delta:
                        greeks = Greeks(
                            delta=mg.delta if mg.delta == mg.delta else None,
                            gamma=mg.gamma if mg.gamma == mg.gamma else None,
                            theta=mg.theta if mg.theta == mg.theta else None,
                            vega=mg.vega if mg.vega == mg.vega else None,
                        )
                        if mg.impliedVol == mg.impliedVol:
                            iv = mg.impliedVol
                        api_greeks_count += 1
                        logger.debug(f"Have API Greeks for {contract.symbol}: delta={greeks.delta:.4f}, iv={iv:.4f}")
                    else:
                        # Fallback to Black-Scholes (use cached underlying data if available)
                        logger.debug(f"No API Greeks for {contract.symbol}, using BS fallback")
                        cached_data = underlying_cache.get(contract.underlying)
                        bs_result = self._calculate_greeks_from_params(
                            underlying=contract.underlying,
                            strike=contract.strike_price,
                            expiry=contract.expiry_date.strftime("%Y%m%d"),
                            option_type="call" if contract.option_type == OptionType.CALL else "put",
                            ticker=ticker,
                            cached_price=cached_data.get("price") if cached_data else None,
                            cached_iv=cached_data.get("iv") if cached_data else None,
                        )
                        if bs_result and bs_result.get("delta") is not None:
                            greeks = Greeks(
                                delta=bs_result.get("delta"),
                                gamma=bs_result.get("gamma"),
                                theta=bs_result.get("theta"),
                                vega=bs_result.get("vega"),
                            )
                            iv = bs_result.get("iv")
                            bs_fallback_count += 1
                        else:
                            logger.debug(f"No Greeks for {contract.symbol}, skipping")
                            skipped_contracts += 1
                            continue

                    # Extract price data
                    last_price = ticker.last if ticker.last == ticker.last and ticker.last > 0 else None
                    bid = ticker.bid if ticker.bid == ticker.bid and ticker.bid > 0 else None
                    ask = ticker.ask if ticker.ask == ticker.ask and ticker.ask > 0 else None
                    volume = int(ticker.volume) if ticker.volume == ticker.volume and ticker.volume >= 0 else None

                    if last_price is None and ticker.close == ticker.close and ticker.close > 0:
                        last_price = ticker.close

                    # Extract Open Interest
                    open_interest = None
                    if contract.option_type == OptionType.PUT:
                        oi = getattr(ticker, 'putOpenInterest', None)
                    else:
                        oi = getattr(ticker, 'callOpenInterest', None)
                    if oi is not None and oi == oi and oi >= 0:
                        open_interest = int(oi)

                    # Create new contract with correct lot_size from IBKR multiplier
                    lot_size = 100  # default
                    if opt.multiplier:
                        try:    
                            lot_size = int(opt.multiplier)
                        except (ValueError, TypeError):
                            pass

                    enriched_contract = OptionContract(
                        symbol=contract.symbol,
                        underlying=contract.underlying,
                        option_type=contract.option_type,
                        strike_price=contract.strike_price,
                        expiry_date=contract.expiry_date,
                        lot_size=lot_size,
                        trading_class=contract.trading_class,
                    )

                    quote = OptionQuote(
                        contract=enriched_contract,
                        timestamp=datetime.now(),
                        last_price=last_price,
                        bid=bid,
                        ask=ask,
                        volume=volume,
                        open_interest=open_interest,
                        iv=iv,
                        greeks=greeks if greeks else Greeks(),
                        source=self.name,
                    )

                    # Apply volume filter
                    if min_volume is not None and (quote.volume is None or quote.volume < min_volume):
                        filtered_by_volume += 1
                        continue

                    results.append(quote)

                except Exception as e:
                    logger.warning(f"Error processing {contract.symbol}: {e}")
                    skipped_contracts += 1

            # Phase 5: Cancel all subscriptions in batch
            for _, opt, _ in tickers:
                try:
                    self._ib.cancelMktData(opt)
                except Exception:
                    pass

            # Log batch completion time
            batch_elapsed = _time.time() - batch_start_time
            logger.info(f"[Batch {batch_num}/{total_batches}] Completed in {batch_elapsed:.1f}s, {len(results)} quotes so far")
            batch_start_time = _time.time()

        # Phase 6: Cancel underlying subscriptions
        for underlying, (stock, _) in underlying_tickers.items():
            try:
                self._ib.cancelMktData(stock)
                logger.debug(f"Cancelled underlying subscription: {underlying}")
            except Exception:
                pass

        logger.info(
            f"Fetched {len(results)} quotes from {len(contracts)} contracts "
            f"(API Greeks: {api_greeks_count}, BS fallback: {bs_fallback_count}, "
            f"skipped: {skipped_contracts}, filtered: {filtered_by_volume})"
        )
        return results

    def get_option_quote(self, symbol: str) -> OptionQuote | None:
        """Get quote for a specific option contract with Greeks."""
        self._ensure_connected()

        try:
            # Parse option symbol to extract components
            # Expected format: AAPL20240120C00150000
            # or standard OCC format
            contract = self._parse_option_symbol(symbol)
            if contract is None:
                logger.error(f"Could not parse option symbol: {symbol}")
                return None

            opt = Option(
                contract.underlying,
                contract.expiry_date.strftime("%Y%m%d"),
                contract.strike_price,
                "C" if contract.option_type == OptionType.CALL else "P",
                "SMART",
            )

            qualified = self._ib.qualifyContracts(opt)
            if not qualified or not opt.conId:
                logger.warning(f"Could not qualify option contract: {symbol}")
                return None

            # Request market data with Greeks
            # Generic tick types: 100=Option Volume, 101=Open Interest, 104=Historical Volatility
            # 106=Implied Volatility, 107=Index Future Premium, 411=RT Historical Vol
            ticker = self._ib.reqMktData(opt, "100,101,104,106", False, False)

            # Wait for data to populate - options may need more time
            for _ in range(5):  # Try up to 5 times (5 seconds total)
                self._ib.sleep(1)
                # Check if we have any data
                if ticker.bid == ticker.bid or ticker.ask == ticker.ask or ticker.last == ticker.last:
                    break

            logger.debug(f"Option ticker for {symbol}: bid={ticker.bid}, ask={ticker.ask}, "
                        f"last={ticker.last}, modelGreeks={ticker.modelGreeks}")

            # Extract Greeks from modelGreeks (or bidGreeks/askGreeks)
            greeks = None
            model_greeks = ticker.modelGreeks
            if model_greeks:
                greeks = Greeks(
                    delta=model_greeks.delta if model_greeks.delta == model_greeks.delta else None,
                    gamma=model_greeks.gamma if model_greeks.gamma == model_greeks.gamma else None,
                    theta=model_greeks.theta if model_greeks.theta == model_greeks.theta else None,
                    vega=model_greeks.vega if model_greeks.vega == model_greeks.vega else None,
                )

            # Extract values, checking for NaN and invalid values (-1 means no data in IBKR)
            last_price = ticker.last if ticker.last == ticker.last and ticker.last > 0 else None
            bid = ticker.bid if ticker.bid == ticker.bid and ticker.bid > 0 else None
            ask = ticker.ask if ticker.ask == ticker.ask and ticker.ask > 0 else None
            volume = int(ticker.volume) if ticker.volume == ticker.volume and ticker.volume >= 0 else None

            # Try close price if no real-time data
            if last_price is None and ticker.close == ticker.close and ticker.close > 0:
                last_price = ticker.close
                logger.debug(f"Using close price for {symbol}: {last_price}")

            # Warn if no market data (subscription might be required)
            if last_price is None and bid is None and ask is None:
                logger.warning(f"No market data for option {symbol}. "
                              "Option market data subscription may be required.")

            quote = OptionQuote(
                contract=contract,
                timestamp=datetime.now(),
                last_price=last_price,
                bid=bid,
                ask=ask,
                volume=volume,
                open_interest=None,  # Not directly available in streaming
                iv=model_greeks.impliedVol if model_greeks and model_greeks.impliedVol == model_greeks.impliedVol else None,
                greeks=greeks,
                source=self.name,
            )

            self._ib.cancelMktData(opt)
            return quote

        except Exception as e:
            logger.error(f"Error getting option quote for {symbol}: {e}")
            return None

    def _parse_option_symbol(self, symbol: str) -> OptionContract | None:
        """Parse option symbol to extract contract details.

        Args:
            symbol: Option symbol (e.g., AAPL20240120C00150000).

        Returns:
            OptionContract or None if parsing fails.
        """
        try:
            # Standard OCC format: AAPL  240120C00150000
            # Our format: AAPL20240120C00150000
            symbol = symbol.replace(" ", "")

            # Find where digits start (after underlying symbol)
            i = 0
            while i < len(symbol) and not symbol[i].isdigit():
                i += 1

            underlying = symbol[:i]
            rest = symbol[i:]

            # Extract date (8 digits)
            if len(rest) >= 8:
                date_str = rest[:8]
                rest = rest[8:]
            else:
                # Try 6 digit date format (YYMMDD)
                date_str = "20" + rest[:6]
                rest = rest[6:]

            # Extract option type (C or P)
            option_type_char = rest[0].upper()
            option_type = OptionType.CALL if option_type_char == "C" else OptionType.PUT
            rest = rest[1:]

            # Extract strike price (remaining digits, divide by 1000)
            strike_price = float(rest) / 1000

            expiry_date = datetime.strptime(date_str, "%Y%m%d").date()

            return OptionContract(
                symbol=symbol,
                underlying=underlying,
                option_type=option_type,
                strike_price=strike_price,
                expiry_date=expiry_date,
            )
        except Exception as e:
            logger.error(f"Error parsing option symbol {symbol}: {e}")
            return None

    def get_option_quotes_with_greeks(
        self,
        underlying: str,
        expiry: date,
        strikes: list[float] | None = None,
    ) -> list[OptionQuote]:
        """Get option quotes with Greeks for multiple strikes.

        Args:
            underlying: Underlying stock symbol.
            expiry: Expiration date.
            strikes: List of strike prices (optional, will auto-detect if None).

        Returns:
            List of OptionQuote instances with Greeks.
        """
        self._ensure_connected()

        underlying = self.normalize_symbol(underlying)
        results = []

        try:
            stock = self._create_stock_contract(underlying)
            qualified = self._ib.qualifyContracts(stock)
            if not qualified or not stock.conId:
                return []

            # Get underlying price if strikes not specified
            if strikes is None:
                ticker = self._ib.reqMktData(stock, "", False, False)
                self._ib.sleep(1)
                underlying_price = ticker.last if ticker.last == ticker.last else 100
                self._ib.cancelMktData(stock)

                # Get option parameters
                chains = self._ib.reqSecDefOptParams(
                    stock.symbol, "", stock.secType, stock.conId
                )
                if chains:
                    chain = next((c for c in chains if c.exchange == "SMART"), chains[0])
                    strike_range = underlying_price * 0.1
                    strikes = [
                        s for s in chain.strikes
                        if underlying_price - strike_range <= s <= underlying_price + strike_range
                    ][:10]

            if not strikes:
                return []

            # Build option contracts
            exp_str = expiry.strftime("%Y%m%d")
            contracts = []
            for strike in strikes:
                for right in ["C", "P"]:
                    opt = Option(underlying, exp_str, strike, right, "SMART")
                    contracts.append((opt, strike, right))

            # Qualify all contracts
            opts_only = [c[0] for c in contracts]
            self._ib.qualifyContracts(*opts_only)

            # Request tickers for all
            tickers = self._ib.reqTickers(*opts_only)

            # Process results
            for (opt, strike, right), ticker in zip(contracts, tickers):
                greeks = None
                if ticker.modelGreeks:
                    mg = ticker.modelGreeks
                    greeks = Greeks(
                        delta=mg.delta if mg.delta == mg.delta else None,
                        gamma=mg.gamma if mg.gamma == mg.gamma else None,
                        theta=mg.theta if mg.theta == mg.theta else None,
                        vega=mg.vega if mg.vega == mg.vega else None,
                    )

                # Get lot_size from IBKR multiplier
                lot_size = 100  # default
                if opt.multiplier:
                    try:
                        lot_size = int(opt.multiplier)
                    except (ValueError, TypeError):
                        pass

                contract = OptionContract(
                    symbol=f"{underlying}{exp_str}{right}{int(strike*1000):08d}",
                    underlying=underlying,
                    option_type=OptionType.CALL if right == "C" else OptionType.PUT,
                    strike_price=strike,
                    expiry_date=expiry,
                    lot_size=lot_size,
                )

                quote = OptionQuote(
                    contract=contract,
                    timestamp=datetime.now(),
                    last_price=ticker.last if ticker.last == ticker.last else None,
                    bid=ticker.bid if ticker.bid == ticker.bid else None,
                    ask=ticker.ask if ticker.ask == ticker.ask else None,
                    volume=int(ticker.volume) if ticker.volume == ticker.volume else None,
                    iv=ticker.modelGreeks.impliedVol if ticker.modelGreeks else None,
                    greeks=greeks,
                    source=self.name,
                )
                results.append(quote)

        except Exception as e:
            logger.error(f"Error getting option quotes with Greeks: {e}")

        return results

    def get_fundamental(self, symbol: str) -> Fundamental | None:
        """Get fundamental data for a stock.

        Note: IBKR fundamental data is not implemented.
        Use Yahoo provider for fundamental data (via routing).

        Args:
            symbol: Stock symbol.

        Returns:
            None - fundamental data not supported by this provider.
        """
        return None

    @auto_reconnect
    def get_stock_volatility(
        self,
        symbol: str,
        include_iv_rank: bool = True,
    ) -> StockVolatility | None:
        """Get stock-level volatility metrics from IBKR.

        Uses TWS API tick types:
        - Tick 24 (generic tick 106): 30-day Implied Volatility
        - Tick 23 (generic tick 104): 30-day Historical Volatility
        - Tick 101: Option Open Interest (Call/Put for PCR calculation)

        For IV Rank and IV Percentile, fetches 1-year historical IV data using
        reqHistoricalData with whatToShow='OPTION_IMPLIED_VOLATILITY'.

        Note: PCR is calculated using Open Interest (not Volume) to ensure
        consistent metrics across US and HK markets.

        Args:
            symbol: Stock symbol (e.g., 'AAPL', '0700.HK').
            include_iv_rank: Whether to fetch historical IV for IV Rank/Percentile.
                            Set to False for faster response without IV Rank.

        Returns:
            StockVolatility with IV, HV, PCR, IV Rank, and IV Percentile.
        """
        self._ensure_connected()

        normalized = self.normalize_symbol(symbol)

        try:
            contract = self._create_stock_contract(normalized)

            # Qualify the contract
            qualified = self._ib.qualifyContracts(contract)
            if not qualified or not contract.conId:
                logger.warning(f"Could not qualify contract for {symbol}")
                return None

            # Request market data with generic ticks for volatility and option open interest
            # 101 = Option Open Interest (for PCR calculation)
            # 104 = Historical Volatility (Tick ID 23)
            # 106 = Implied Volatility (Tick ID 24)
            ticker = self._ib.reqMktData(contract, "101,104,106", snapshot=False, regulatorySnapshot=False)

            # Wait for volatility data to populate
            iv = None
            hv = None
            call_oi = None
            put_oi = None

            for i in range(10):  # Try up to 5 seconds
                self._ib.sleep(0.5)

                # Check for IV (tick 24, delivered via tickGeneric)
                if hasattr(ticker, 'impliedVolatility') and ticker.impliedVolatility == ticker.impliedVolatility:
                    iv = ticker.impliedVolatility

                # Check for HV (tick 23, delivered via tickGeneric)
                if hasattr(ticker, 'histVolatility') and ticker.histVolatility == ticker.histVolatility:
                    hv = ticker.histVolatility

                # Check for option open interest (tick 101)
                if hasattr(ticker, 'callOpenInterest') and ticker.callOpenInterest == ticker.callOpenInterest:
                    call_oi = ticker.callOpenInterest
                if hasattr(ticker, 'putOpenInterest') and ticker.putOpenInterest == ticker.putOpenInterest:
                    put_oi = ticker.putOpenInterest

                # Exit early if we have all data, or after minimum wait if we have volatility
                has_volatility = iv is not None and hv is not None
                has_oi = call_oi is not None and put_oi is not None

                if has_volatility and has_oi:
                    break
                if has_volatility and i >= 5:  # Wait at least 2.5s for OI
                    break

            # Cancel market data subscription
            self._ib.cancelMktData(contract)

            # Calculate PCR from Open Interest
            pcr = None
            if call_oi is not None and put_oi is not None and call_oi > 0:
                pcr = put_oi / call_oi
                logger.debug(f"PCR from open interest: {pcr:.2f} (put_oi={put_oi}, call_oi={call_oi})")

            # If no volatility data available, return None
            if iv is None and hv is None:
                logger.warning(f"No volatility data available for {normalized} (input: {symbol}). "
                              "Options market data subscription may be required.")
                return None

            # Fetch historical IV for IV Rank and IV Percentile calculation
            iv_rank = None
            iv_percentile = None

            if include_iv_rank and iv is not None:
                historical_ivs = self._get_historical_iv(contract, days=252)
                if historical_ivs and len(historical_ivs) >= 20:
                    # Calculate IV Rank: (Current IV - Min IV) / (Max IV - Min IV) * 100
                    iv_min = min(historical_ivs)
                    iv_max = max(historical_ivs)
                    if iv_max > iv_min:
                        iv_rank = (iv - iv_min) / (iv_max - iv_min) * 100
                        iv_rank = max(0.0, min(100.0, iv_rank))  # Clamp to 0-100

                    # Calculate IV Percentile: % of days IV was lower than current
                    count_lower = sum(1 for hist_iv in historical_ivs if hist_iv < iv)
                    iv_percentile = count_lower / len(historical_ivs) * 100

                    logger.debug(f"IV Rank calculation: current={iv:.4f}, min={iv_min:.4f}, "
                                f"max={iv_max:.4f}, rank={iv_rank:.1f}")
                    logger.debug(f"IV Percentile: {count_lower}/{len(historical_ivs)} = {iv_percentile:.1f}%")

            iv_str = f"{iv:.4f}" if iv is not None else "N/A"
            hv_str = f"{hv:.4f}" if hv is not None else "N/A"
            pcr_str = f"{pcr:.2f}" if pcr is not None else "N/A"
            ivr_str = f"{iv_rank:.1f}" if iv_rank is not None else "N/A"
            ivp_str = f"{iv_percentile:.1f}%" if iv_percentile is not None else "N/A"
            logger.debug(f"Volatility for {normalized}: IV={iv_str}, HV={hv_str}, "
                        f"PCR={pcr_str}, IV Rank={ivr_str}, IV Pctl={ivp_str}")

            return StockVolatility(
                symbol=normalized,
                timestamp=datetime.now(),
                iv=iv,
                hv=hv,
                iv_rank=iv_rank,
                iv_percentile=iv_percentile / 100 if iv_percentile is not None else None,  # Store as decimal
                pcr=pcr,
                source=self.name,
            )

        except Exception as e:
            logger.error(f"Error getting stock volatility for {symbol}: {e}")
            return None

    def _get_historical_iv(
        self,
        contract: Any,
        days: int = 252,
    ) -> list[float]:
        """Fetch historical implied volatility data.

        Uses reqHistoricalData with whatToShow='OPTION_IMPLIED_VOLATILITY'.

        Args:
            contract: Qualified stock contract.
            days: Number of days of historical data to fetch.

        Returns:
            List of historical IV values (as decimals, e.g., 0.25 for 25%).
        """
        try:
            # Calculate duration string
            if days <= 365:
                duration = "1 Y"
            else:
                years = (days + 364) // 365
                duration = f"{years} Y"

            # Request historical IV data
            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",  # Current time
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow="OPTION_IMPLIED_VOLATILITY",
                useRTH=True,
                formatDate=1,
            )

            if not bars:
                logger.warning(f"No historical IV data returned for {contract.symbol}")
                return []

            # Extract IV values from bars (close price contains IV)
            historical_ivs = []
            for bar in bars:
                # IV is stored in the 'close' field of the bar
                if bar.close == bar.close and bar.close > 0:  # NaN check and positive
                    historical_ivs.append(bar.close)

            logger.debug(f"Fetched {len(historical_ivs)} historical IV data points for {contract.symbol}")
            return historical_ivs

        except Exception as e:
            logger.warning(f"Error fetching historical IV for {contract.symbol}: {e}")
            return []

    def get_macro_data(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroData]:
        """Get macro economic data.

        Uses historical data for index symbols like VIX.
        """
        # For indices like ^VIX, we can use kline data
        # Map common indicator symbols to IBKR format
        symbol_map = {
            "^VIX": "VIX",
            "^TNX": "TNX",
            "^SPX": "SPX",
            "^NDX": "NDX",
        }

        ibkr_symbol = symbol_map.get(indicator, indicator)

        try:
            # Try to get as index data
            contract = Contract()
            contract.symbol = ibkr_symbol
            contract.secType = "IND"
            contract.exchange = "CBOE" if "VIX" in ibkr_symbol else "SMART"
            contract.currency = "USD"

            self._ensure_connected()
            qualified = self._ib.qualifyContracts(contract)

            if qualified:
                days = (end_date - start_date).days + 1
                duration = f"{max(1, days)} D" if days <= 365 else "1 Y"

                bars = self._ib.reqHistoricalData(
                    contract,
                    endDateTime=end_date.strftime("%Y%m%d 23:59:59"),
                    durationStr=duration,
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                )

                return [
                    MacroData.from_kline(
                        indicator=indicator,
                        data_date=bar.date if isinstance(bar.date, date) else datetime.strptime(str(bar.date), "%Y-%m-%d").date(),
                        open_=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=int(bar.volume) if bar.volume else None,
                        source=self.name,
                    )
                    for bar in bars
                    if start_date <= (bar.date if isinstance(bar.date, date) else datetime.strptime(str(bar.date), "%Y-%m-%d").date()) <= end_date
                ]
        except Exception as e:
            logger.warning(f"Could not get macro data for {indicator}: {e}")

        return []

    def health_check(self) -> bool:
        """Check if connection is healthy.

        Returns:
            True if connected and responsive, False otherwise.
        """
        if not self._connected or not self._ib:
            return False

        try:
            # Try to get account summary as a health check
            self._ib.reqCurrentTime()
            return True
        except Exception:
            return False

    def reconnect(self, max_retries: int = 3, initial_delay: float = 5.0) -> bool:
        """Attempt to reconnect with exponential backoff.

        Args:
            max_retries: Maximum number of reconnection attempts.
            initial_delay: Initial delay between attempts in seconds.

        Returns:
            True if reconnection successful, False otherwise.
        """
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                logger.info(f"Reconnection attempt {attempt + 1}/{max_retries}")
                self.disconnect()
                self.connect()
                if self.is_available:
                    logger.info("Reconnection successful")
                    return True
            except Exception as e:
                logger.warning(f"Reconnection attempt failed: {e}")

            if attempt < max_retries - 1:
                logger.info(f"Waiting {delay}s before next attempt")
                time.sleep(delay)
                delay *= 2  # Exponential backoff

        logger.error("All reconnection attempts failed")
        return False

    # Account Provider Methods

    def get_account_summary(
        self,
        account_type: AccountType | None = None,
    ) -> AccountSummary | None:
        """Get account summary information.

        Note: IBKR account type is determined at connection time by the port.
        The account_type parameter is for interface compatibility; if provided
        and mismatched, a warning will be logged.

        Args:
            account_type: Optional. If provided and different from the connected
                         account type, a warning will be logged.

        Returns:
            AccountSummary instance or None if not available.
        """
        self._ensure_connected()
        self._validate_account_type(account_type)

        try:
            # Get account values - this returns a list of AccountValue objects
            account_values = self._ib.accountValues()

            if not account_values:
                logger.warning("No account values returned from IBKR")
                return None

            # Extract account ID from first value
            account_id = account_values[0].account if account_values else "unknown"

            # Build a lookup dict for easier access
            values: dict[str, dict[str, float]] = {}
            for av in account_values:
                key = av.tag
                currency = av.currency
                try:
                    value = float(av.value)
                except (ValueError, TypeError):
                    continue
                if key not in values:
                    values[key] = {}
                values[key][currency] = value

            # Extract key metrics
            # For most metrics, prefer USD then BASE
            # For P&L metrics, prefer BASE (total across all currencies) then USD
            def get_value(tag: str, prefer_base: bool = False) -> float | None:
                if tag in values:
                    if prefer_base:
                        # For P&L, BASE contains the total across all currencies
                        return values[tag].get("BASE") or values[tag].get("USD") or values[tag].get("")
                    return values[tag].get("USD") or values[tag].get("BASE") or values[tag].get("")
                return None

            total_assets = get_value("NetLiquidation")
            cash = get_value("TotalCashValue") or get_value("AvailableFunds")
            market_value = get_value("GrossPositionValue") or get_value("StockMarketValue")
            # Use BASE for unrealized P&L to get total across all currencies
            unrealized_pnl = get_value("UnrealizedPnL", prefer_base=True)
            margin_used = get_value("MaintMarginReq") or get_value("InitMarginReq")
            margin_available = get_value("AvailableFunds")
            buying_power = get_value("BuyingPower")

            # Get cash by currency
            cash_by_currency: dict[str, float] = {}
            if "CashBalance" in values:
                for currency, amount in values["CashBalance"].items():
                    if currency and currency not in ("BASE", ""):
                        cash_by_currency[currency] = amount

            logger.info(f"IBKR account summary: NetLiq={total_assets}, Cash={cash}, "
                       f"MarketValue={market_value}, UnrealizedPnL={unrealized_pnl}")

            return AccountSummary(
                broker="ibkr",
                account_type=self._account_type,
                account_id=account_id,
                total_assets=total_assets or 0.0,
                cash=cash or 0.0,
                market_value=market_value or 0.0,
                unrealized_pnl=unrealized_pnl or 0.0,
                margin_used=margin_used,
                margin_available=margin_available,
                buying_power=buying_power,
                cash_by_currency=cash_by_currency if cash_by_currency else None,
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Error getting account summary: {e}")
            return None

    def _validate_account_type(self, account_type: AccountType | None) -> None:
        """Validate that requested account type matches connected account.

        Args:
            account_type: Requested account type.
        """
        if account_type is not None and account_type != self._account_type:
            logger.warning(
                f"Requested account_type={account_type.value} but connected to "
                f"{self._account_type.value} (port {self._port}). "
                f"Returning {self._account_type.value} account data."
            )

    def get_positions(
        self,
        account_type: AccountType | None = None,
        fetch_greeks: bool = True,
    ) -> list[AccountPosition]:
        """Get all positions in the account.

        Note: IBKR account type is determined at connection time by the port.
        The account_type parameter is for interface compatibility.

        Args:
            account_type: Optional. If provided and different from the connected
                         account type, a warning will be logged.
            fetch_greeks: Whether to fetch Greeks for option positions.
                Set to False when using a centralized Greeks fetcher (e.g., UnifiedProvider).

        Returns:
            List of AccountPosition instances.
        """
        self._ensure_connected()
        self._validate_account_type(account_type)

        try:
            # Get positions from IBKR
            positions = self._ib.positions()

            if not positions:
                logger.info("No positions found in IBKR account")
                return []

            results = []
            for pos in positions:
                contract = pos.contract
                avg_cost = pos.avgCost

                # Determine market based on contract
                market = Market.US
                currency = contract.currency or "USD"
                if currency == "HKD":
                    market = Market.HK
                elif currency == "CNY" or currency == "CNH":
                    market = Market.CN

                # Determine asset type
                sec_type = contract.secType
                if sec_type == "OPT":
                    asset_type = AssetType.OPTION
                else:
                    asset_type = AssetType.STOCK

                # Build symbol using SymbolFormatter
                # For options, contract.symbol is the underlying symbol
                # For stocks, it's the stock symbol
                symbol = SymbolFormatter.from_ibkr_contract(contract.symbol, contract.exchange)

                # Create position
                position = AccountPosition(
                    symbol=symbol,
                    asset_type=asset_type,
                    market=market,
                    quantity=float(pos.position),
                    avg_cost=avg_cost,
                    market_value=0.0,  # Will be calculated below
                    unrealized_pnl=0.0,  # Will be calculated below
                    currency=currency,
                    broker="ibkr",
                    last_updated=datetime.now(),
                )

                # Add option-specific fields
                if sec_type == "OPT":
                    # Convert IBKR underlying to standard format for cross-provider compatibility
                    position.underlying = SymbolFormatter.from_ibkr_contract(
                        contract.symbol, contract.exchange
                    )  # e.g., "700" + "SEHK" -> "0700.HK"
                    position.strike = contract.strike
                    position.expiry = contract.lastTradeDateOrContractMonth
                    position.option_type = "call" if contract.right == "C" else "put"
                    # IBKR returns multiplier as string, convert to int
                    mult = contract.multiplier
                    position.contract_multiplier = int(mult)
                    # Capture trading class (important for HK options)
                    position.trading_class = getattr(contract, 'tradingClass', None)
                    # Capture contract ID (unique identifier for precise order matching)
                    position.con_id = getattr(contract, 'conId', None)
                else:
                    # Stock Greeks: delta = +1 (long) or -1 (short), others = 0
                    position.delta = 1.0 if position.quantity > 0 else -1.0 if position.quantity < 0 else 0.0
                    position.gamma = 0.0
                    position.theta = 0.0
                    position.vega = 0.0
                    position.iv = None

                results.append(position)

            # Try to get market values and P&L from portfolio
            try:
                portfolio = self._ib.portfolio()
                portfolio_lookup = {
                    (p.contract.conId): p for p in portfolio
                }

                for i, pos in enumerate(positions):
                    if pos.contract.conId in portfolio_lookup:
                        port_item = portfolio_lookup[pos.contract.conId]
                        results[i].market_value = port_item.marketValue
                        results[i].unrealized_pnl = port_item.unrealizedPNL
                        # Use averageCost from portfolio (more reliable than Position.avgCost)
                        # IBKR's averageCost for OPTIONS is per-contract (price × multiplier)
                        # Normalize to per-share price for consistent calculation across brokers
                        # NOTE: Only apply to OPTIONS, Stock avg_cost is already per-share
                        if results[i].asset_type == AssetType.OPTION and results[i].contract_multiplier > 0:
                            results[i].avg_cost = port_item.averageCost / results[i].contract_multiplier
                        else:
                            results[i].avg_cost = port_item.averageCost

                        # For stocks, underlying_price = market_value / quantity
                        if results[i].asset_type == AssetType.STOCK and results[i].quantity != 0:
                            results[i].underlying_price = abs(port_item.marketValue / results[i].quantity)

                        # Get Greeks for options from market data (if enabled)
                        if fetch_greeks and results[i].asset_type == AssetType.OPTION:
                            self._fetch_option_greeks(results[i], pos.contract)

            except Exception as e:
                logger.warning(f"Could not fetch portfolio details: {e}")

            logger.info(f"Found {len(results)} positions in IBKR account")
            return results

        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def _fetch_option_greeks(self, position: AccountPosition, contract: Any) -> None:
        """Fetch Greeks for an option position.

        Args:
            position: AccountPosition to update with Greeks.
            contract: IBKR contract object.
        """
        try:
            # Ensure contract is qualified
            qualified = self._ib.qualifyContracts(contract)
            if not qualified or not contract.conId:
                logger.warning(f"Could not qualify contract for {position.symbol}")
                return

            logger.debug(f"Requesting Greeks for {position.symbol}, asset_type:{position.asset_type}, "
                         f"underlying:{position.underlying}, strike:{position.strike}, expiry:{position.expiry}, "
                         f"option_type:{position.option_type}, conId={contract.conId}, "
                         f"secType={contract.secType}, exchange={contract.exchange}")

            # Request market data with Greeks
            # Generic tick types: 100=Option Volume, 101=Open Interest, 104=Historical Volatility
            # 106=Implied Volatility - need multiple tick types for Greeks to populate
            ticker = self._ib.reqMktData(contract, "100,101,104,106", snapshot=False, regulatorySnapshot=False)

            # Wait for Greeks to populate - options may need more time
            for i in range(5):  # Try up to 5 times (5 seconds total)
                self._ib.sleep(1)
                if ticker.modelGreeks is not None:
                    logger.debug(f"Got modelGreeks after {i+1}s for {position.symbol}")
                    break
                # Also check bidGreeks and askGreeks as alternatives
                if ticker.bidGreeks is not None or ticker.askGreeks is not None:
                    logger.debug(f"Got bid/askGreeks after {i+1}s for {position.symbol}")
                    break

            # Try modelGreeks first, then bidGreeks, then askGreeks
            mg = ticker.modelGreeks or ticker.bidGreeks or ticker.askGreeks

            if mg:
                position.delta = mg.delta if mg.delta == mg.delta else None
                position.gamma = mg.gamma if mg.gamma == mg.gamma else None
                position.theta = mg.theta if mg.theta == mg.theta else None
                position.vega = mg.vega if mg.vega == mg.vega else None
                position.iv = mg.impliedVol if mg.impliedVol == mg.impliedVol else None
                # Get underlying price from modelGreeks
                if hasattr(mg, "undPrice") and mg.undPrice == mg.undPrice:
                    position.underlying_price = mg.undPrice

                # Fallback: If undPrice not available from Greeks, fetch stock quote
                if position.underlying_price is None:
                    underlying_code = position.underlying or position.symbol.split()[0]
                    logger.debug(f"undPrice not in Greeks for {position.symbol}, fetching stock quote for {underlying_code}")
                    try:
                        # Convert to standard format for quote fetching
                        std_symbol = SymbolFormatter.to_standard(underlying_code)
                        stock_quote = self.get_stock_quote(std_symbol)
                        if stock_quote:
                            # Priority: close (last price), then bid/ask midpoint
                            if stock_quote.close is not None:
                                try:
                                    if not math.isnan(stock_quote.close):
                                        position.underlying_price = stock_quote.close
                                        logger.debug(f"Got undPrice from stock quote for {position.symbol}: {position.underlying_price}")
                                except (TypeError, ValueError):
                                    pass
                            # Try bid/ask midpoint if close is nan
                            if position.underlying_price is None:
                                bid = getattr(stock_quote, '_bid', None)
                                ask = getattr(stock_quote, '_ask', None)
                                if bid is not None and ask is not None and bid > 0 and ask > 0:
                                    position.underlying_price = (bid + ask) / 2
                                    logger.debug(f"Got undPrice from bid/ask midpoint for {position.symbol}: {position.underlying_price}")
                    except Exception as e:
                        logger.debug(f"Could not fetch stock quote for {underlying_code}: {e}")


                logger.debug(f"Fetched Greeks for {position.symbol} asset_type:{position.asset_type},  underlying:{position.underlying}, strike:{position.strike}, expiry:{position.expiry}, option_type:{position.option_type}: delta={position.delta}, "
                           f"iv={position.iv}, undPrice={position.underlying_price}")
            else:
                # Log what we got from ticker for debugging
                logger.warning(f"No Greeks available for {position.symbol}, asset_type:{position.asset_type},  underlying:{position.underlying}, strike:{position.strike}, expiry:{position.expiry}, option_type:{position.option_type}"
                             f"Ticker: bid={ticker.bid}, ask={ticker.ask}, last={ticker.last}")

                # Fallback: Calculate Greeks using Black-Scholes if we have enough data
                logger.debug(f"Attempting to calculate Greeks using Black-Scholes for {position.symbol}")
                self._calculate_greeks_fallback(position, ticker)

            self._ib.cancelMktData(contract)

        except Exception as e:
            logger.debug(f"Could not fetch Greeks for {position.symbol}: {e}")

    def _calculate_greeks_fallback(self, position: AccountPosition, ticker: Any) -> None:
        """Calculate Greeks using Black-Scholes when API Greeks are unavailable.

        This is a wrapper around _calculate_greeks_from_params that works with AccountPosition.

        Args:
            position: AccountPosition to update with calculated Greeks.
            ticker: IBKR ticker object (may have price data).
        """
        try:
            # Extract parameters from position
            underlying = position.underlying or position.symbol.split()[0]

            # Call core calculation function
            result = self._calculate_greeks_from_params(
                underlying=underlying,
                strike=position.strike,
                expiry=position.expiry,
                option_type=position.option_type,
                ticker=ticker
            )

            # Update position with calculated Greeks
            if result:
                position.delta = result.get("delta")
                position.gamma = result.get("gamma")
                position.theta = result.get("theta")
                position.vega = result.get("vega")
                position.iv = result.get("iv")
                position.underlying_price = result.get("underlying_price")

                logger.debug(f"Calculated Greeks for {position.symbol} using Black-Scholes: "
                            f"delta={position.delta:.4f}, gamma={position.gamma:.4f}, "
                            f"theta={position.theta:.4f}, vega={position.vega:.4f}, "
                            f"iv={position.iv:.4f}, underlying_price={position.underlying_price:.2f}")
            else:
                logger.warning(f"Could not calculate Greeks for {position.symbol}")

        except Exception as e:
            logger.warning(f"Failed to calculate Greeks fallback for {position.symbol}: {e}")

    def _calculate_greeks_from_params(
        self,
        underlying: str,
        strike: float,
        expiry: str,
        option_type: str,
        ticker: Any = None,
        cached_price: float | None = None,
        cached_iv: float | None = None,
    ) -> dict[str, float | None] | None:
        """Calculate Greeks using Black-Scholes from raw parameters.

        Args:
            underlying: Underlying stock code (e.g., "9988").
            strike: Strike price.
            expiry: Expiry date in YYYYMMDD format.
            option_type: "call" or "put".
            ticker: Optional IBKR ticker object.
            cached_price: Pre-fetched underlying price (optimization).
            cached_iv: Pre-fetched IV (optimization).

        Returns:
            Dictionary with calculated Greeks, or None if calculation fails.
        """
        try:
            from datetime import datetime
            from src.engine.bs import calc_bs_greeks
            from src.engine.models import BSParams

            # Step 1: Normalize underlying symbol using SymbolFormatter
            underlying_symbol = SymbolFormatter.to_standard(underlying)

            # Step 2: Get underlying price (use cached if available)
            underlying_price = cached_price
            if underlying_price is None:
                try:
                    stock_quote = self.get_stock_quote(underlying_symbol)
                    if stock_quote:
                        # Priority: close (last price)
                        if stock_quote.close is not None:
                            try:
                                if not math.isnan(stock_quote.close):
                                    underlying_price = stock_quote.close
                                    logger.debug(f"Fetched underlying price from close: {underlying_price}")
                            except (TypeError, ValueError):
                                pass
                        # Fallback: bid/ask midpoint
                        if underlying_price is None:
                            bid = getattr(stock_quote, '_bid', None)
                            ask = getattr(stock_quote, '_ask', None)
                            if bid is not None and ask is not None and bid > 0 and ask > 0:
                                underlying_price = (bid + ask) / 2
                                logger.debug(f"Fetched underlying price from bid/ask midpoint: {underlying_price}")
                except Exception as e:
                    logger.debug(f"Could not fetch underlying stock quote: {e}")

            if underlying_price is None:
                logger.warning(f"Cannot calculate Greeks: no underlying price for {underlying_symbol}")
                return None

            # Step 3: Get or estimate IV (use cached if available)
            iv = cached_iv

            # Try to get IV from ticker if not cached
            if iv is None and ticker and hasattr(ticker, 'impliedVolatility') and ticker.impliedVolatility == ticker.impliedVolatility:
                iv = ticker.impliedVolatility

            # If no IV from ticker or cache, try to get from stock volatility
            if iv is None:
                try:
                    volatility_data = self.get_stock_volatility(underlying_symbol, include_iv_rank=False)
                    if volatility_data:
                        iv = volatility_data.iv or volatility_data.hv
                        if iv:
                            logger.debug(f"Using volatility={iv:.4f} from stock data")
                except Exception as e:
                    logger.debug(f"Could not fetch volatility data: {e}")

            # Use default IV if still None
            if iv is None:
                iv = 0.30
                logger.debug(f"Using default IV={iv:.2f}")

            # Step 4: Calculate time to expiry
            try:
                expiry_date = datetime.strptime(expiry, "%Y%m%d")
                days_to_expiry = (expiry_date - datetime.now()).days
                time_to_expiry = max(days_to_expiry / 365.0, 1/365.0)
            except ValueError:
                logger.warning(f"Invalid expiry format: {expiry}")
                return None

            # Step 5: Build BSParams and calculate Greeks
            is_call = option_type.lower() == "call"

            params = BSParams(
                spot_price=underlying_price,
                strike_price=strike,
                risk_free_rate=0.03,
                volatility=iv,
                time_to_expiry=time_to_expiry,
                is_call=is_call,
            )

            greeks = calc_bs_greeks(params)

            result = {
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
                "iv": iv,
                "underlying_price": underlying_price,
            }

            logger.debug(f"Calculated Greeks for {underlying} using Black-Scholes: "
                        f"delta={result['delta']:.4f}, gamma={result['gamma']:.4f}, "
                        f"theta={result['theta']:.4f}, vega={result['vega']:.4f}, "
                        f"iv={result['iv']:.4f}, underlying_price={result['underlying_price']:.2f}")

            return result

        except Exception as e:
            logger.warning(f"Failed to calculate Greeks from params for {underlying}: {e}")
            return None

    def fetch_greeks_for_hk_option(
        self,
        underlying: str,
        strike: float,
        expiry: str,
        option_type: str,
    ) -> dict[str, float | None] | None:
        """Fetch Greeks for a Hong Kong option position via IBKR.

        This method is used to get Greeks for options held at other brokers
        (e.g., Futu) that don't provide Greeks data directly.

        Args:
            underlying: Underlying stock code (e.g., "9988" for Alibaba).
            strike: Strike price.
            expiry: Expiry date string in YYYYMMDD format (e.g., "20260129").
            option_type: "call" or "put".

        Returns:
            Dictionary with Greeks (delta, gamma, theta, vega, iv) or None if failed.
        """
        self._ensure_connected()

        try:
            # Normalize underlying to IBKR symbol format
            underlying_code = SymbolFormatter.to_ibkr_symbol(underlying)

            # Convert option_type to IBKR right format
            right = "C" if option_type.lower() == "call" else "P"

            logger.debug(f"Fetching Greeks for HK option: symbol={underlying_code}, "
                        f"expiry={expiry}, strike={strike}, right={right}")

            # Build Contract for HK option
            # HK options: SEHK exchange, HKD currency, multiplier 500
            contract = Contract()
            contract.conId = 0
            contract.symbol = underlying_code
            contract.secType = "OPT"
            contract.exchange = "SEHK"
            contract.currency = "HKD"
            contract.lastTradeDateOrContractMonth = expiry
            contract.strike = strike
            contract.right = right

            # Qualify the contract
            self._ib.qualifyContracts(contract)
            if not contract.conId:
                logger.warning(f"Could not qualify HK option contract: "
                             f"{underlying_code} {expiry} {right} @ {strike}")
                return None

            logger.info(f"Qualified contract: conId={contract.conId}")

            # Request market data with Greeks
            ticker = self._ib.reqMktData(contract, "100,101,104,106", snapshot=False, regulatorySnapshot=False)

            # Wait for Greeks to populate (up to 5 seconds)
            for _ in range(5):
                self._ib.sleep(1)
                if ticker.modelGreeks is not None:
                    break
                if ticker.bidGreeks is not None or ticker.askGreeks is not None:
                    break

            # Extract Greeks from model, bid, or ask Greeks
            mg = ticker.modelGreeks or ticker.bidGreeks or ticker.askGreeks
            self._ib.cancelMktData(contract)

            if mg:
                # Check for NaN values (NaN != NaN is True)
                und_price = None
                if hasattr(mg, "undPrice") and mg.undPrice == mg.undPrice:
                    und_price = mg.undPrice

                # Fallback: If undPrice not available from Greeks, fetch stock quote
                if und_price is None:
                    logger.debug(f"undPrice not in Greeks, fetching stock quote for {underlying_code}")
                    try:
                        # Convert to standard format for quote fetching
                        std_symbol = SymbolFormatter.to_standard(underlying_code)  # "700" → "0700.HK"
                        stock_quote = self.get_stock_quote(std_symbol)
                        if stock_quote:
                            # Priority: close (last price), then bid/ask midpoint
                            if stock_quote.close is not None:
                                try:
                                    if not math.isnan(stock_quote.close):
                                        und_price = stock_quote.close
                                        logger.debug(f"Got undPrice from stock quote: {und_price}")
                                except (TypeError, ValueError):
                                    pass
                            # Try bid/ask midpoint if close is nan
                            if und_price is None:
                                bid = getattr(stock_quote, '_bid', None)
                                ask = getattr(stock_quote, '_ask', None)
                                if bid is not None and ask is not None and bid > 0 and ask > 0:
                                    und_price = (bid + ask) / 2
                                    logger.debug(f"Got undPrice from bid/ask midpoint: {und_price}")
                    except Exception as e:
                        logger.debug(f"Could not fetch stock quote for {underlying_code}: {e}")

                result = {
                    "delta": mg.delta if mg.delta == mg.delta else None,
                    "gamma": mg.gamma if mg.gamma == mg.gamma else None,
                    "theta": mg.theta if mg.theta == mg.theta else None,
                    "vega": mg.vega if mg.vega == mg.vega else None,
                    "iv": mg.impliedVol if mg.impliedVol == mg.impliedVol else None,
                    "underlying_price": und_price,
                }
                logger.debug(f"Got Greeks for {underlying_code} {expiry} {right}@{strike}: "
                            f"delta={result['delta']}, iv={result['iv']}, undPrice={und_price}")
                return result
            else:
                logger.warning(f"No Greeks available for HK option: {underlying_code} {expiry} {right} @ {strike}")

                # Fallback: Calculate Greeks using Black-Scholes
                logger.debug(f"Attempting to calculate Greeks using Black-Scholes for HK option: {underlying_code}")
                return self._calculate_greeks_from_params(
                    underlying=underlying_code,
                    strike=strike,
                    expiry=expiry,
                    option_type=option_type,
                    ticker=ticker
                )

        except Exception as e:
            logger.error(f"Error fetching Greeks for HK option {underlying}: {e}")
            return None

    def get_cash_balances(
        self,
        account_type: AccountType | None = None,
    ) -> list[AccountCash]:
        """Get cash balances by currency.

        Note: IBKR account type is determined at connection time by the port.
        The account_type parameter is for interface compatibility.

        Args:
            account_type: Optional. If provided and different from the connected
                         account type, a warning will be logged.

        Returns:
            List of AccountCash instances.
        """
        self._ensure_connected()
        self._validate_account_type(account_type)

        try:
            # Get account values
            account_values = self._ib.accountValues()

            if not account_values:
                logger.warning("No account values returned from IBKR")
                return []

            # Extract cash balances by currency
            cash_balances: dict[str, dict[str, float]] = {}

            for av in account_values:
                currency = av.currency
                if not currency or currency in ("", "BASE"):
                    continue

                try:
                    value = float(av.value)
                except (ValueError, TypeError):
                    continue

                if currency not in cash_balances:
                    cash_balances[currency] = {"balance": 0.0, "available": 0.0}

                if av.tag == "CashBalance":
                    cash_balances[currency]["balance"] = value
                elif av.tag == "AvailableFunds":
                    cash_balances[currency]["available"] = value

            results = []
            for currency, amounts in cash_balances.items():
                if amounts["balance"] != 0 or amounts["available"] != 0:
                    results.append(AccountCash(
                        currency=currency,
                        balance=amounts["balance"],
                        available=amounts["available"],
                        broker="ibkr",
                    ))

            logger.info(f"Found cash balances in {len(results)} currencies")
            return results

        except Exception as e:
            logger.error(f"Error getting cash balances: {e}")
            return []
