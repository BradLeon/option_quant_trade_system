"""IBKR TWS API data provider implementation."""

import logging
import os
import time
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any

from dotenv import load_dotenv

from src.data.models import (
    Fundamental,
    KlineBar,
    MacroData,
    OptionChain,
    OptionQuote,
    StockQuote,
    StockVolatility,
)
from src.data.models.option import Greeks, OptionContract, OptionType
from src.data.models.stock import KlineType
from src.data.providers.base import (
    ConnectionError,
    DataNotFoundError,
    DataProvider,
)

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


class IBKRProvider(DataProvider):
    """IBKR TWS API data provider.

    Requires TWS or IB Gateway to be running locally.

    Usage:
        with IBKRProvider() as provider:
            quote = provider.get_stock_quote("AAPL")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        timeout: int = 30,
    ) -> None:
        """Initialize IBKR provider.

        Args:
            host: TWS/Gateway host. Defaults to env var or 127.0.0.1.
            port: TWS/Gateway port. Defaults to env var or 7497 (paper).
            client_id: Client ID for connection. Defaults to env var or 1.
            timeout: Request timeout in seconds.
        """
        load_dotenv()

        self._host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self._port = port or int(os.getenv("IBKR_PORT", "7497"))
        # Generate unique clientId based on process ID to avoid conflicts
        # TWS GUI uses 0, other apps commonly use 1-10
        # Use PID modulo to get a number in range 100-999
        # Note: Ignore IBKR_CLIENT_ID env var to ensure unique IDs per process
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
        """Check if provider is available."""
        if not IBKR_AVAILABLE:
            return False
        return self._connected

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
        symbol = symbol.upper()

        # Handle HK stocks: 0700.HK or HK.00700 format
        # IBKR uses symbol without leading zeros (e.g., 700 not 0700)
        if symbol.endswith(".HK"):
            # Yahoo format: 0700.HK -> symbol=700, exchange=SEHK, currency=HKD
            code = symbol[:-3].lstrip("0")  # Remove .HK and leading zeros
            return Stock(code, "SEHK", "HKD")
        elif symbol.startswith("HK."):
            # Futu format: HK.00700 -> symbol=700, exchange=SEHK, currency=HKD
            code = symbol[3:].lstrip("0")  # Remove HK. and leading zeros
            return Stock(code, "SEHK", "HKD")

        # Handle US stocks: AAPL or US.AAPL format
        if symbol.startswith("US."):
            symbol = symbol[3:]  # Remove US.

        return Stock(symbol, "SMART", "USD")

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to standard format.

        Keeps HK suffix for Hong Kong stocks to preserve market info.

        Args:
            symbol: Stock symbol.

        Returns:
            Symbol in standard format.
        """
        symbol = symbol.upper()

        # Keep HK stocks in Yahoo format for consistency (0700.HK)
        if symbol.endswith(".HK"):
            return symbol
        if symbol.startswith("HK."):
            # Convert HK.00700 -> 00700.HK
            code = symbol[3:]
            return f"{code}.HK"

        # For US stocks, remove market prefix
        if symbol.startswith("US."):
            return symbol[3:]

        return symbol

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """Get real-time stock quote."""
        quotes = self.get_stock_quotes([symbol])
        return quotes[0] if quotes else None

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
                if not qualified:
                    logger.warning(f"Could not qualify contract for {symbol}")
                    continue

                # Request market data
                ticker = self._ib.reqMktData(contract, "", False, False)

                # Wait for data with timeout
                timeout_count = 0
                while ticker.last != ticker.last and timeout_count < 50:  # NaN check
                    self._ib.sleep(0.1)
                    timeout_count += 1

                # Also try to get snapshot if streaming didn't work
                if ticker.last != ticker.last:
                    self._ib.sleep(1)

                quote = StockQuote(
                    symbol=normalized,
                    timestamp=datetime.now(),
                    open=ticker.open if ticker.open == ticker.open else None,
                    high=ticker.high if ticker.high == ticker.high else None,
                    low=ticker.low if ticker.low == ticker.low else None,
                    close=ticker.last if ticker.last == ticker.last else ticker.close,
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
            if not qualified:
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

        Returns:
            OptionChain with contract structure (no market data)
        """
        self._ensure_connected()

        underlying = self.normalize_symbol(underlying)

        try:
            # Create and qualify stock contract
            stock = self._create_stock_contract(underlying)
            qualified = self._ib.qualifyContracts(stock)
            if not qualified:
                logger.warning(f"Could not qualify contract for {underlying}")
                return None

            # Get option chain parameters
            chains = self._ib.reqSecDefOptParams(
                stock.symbol, "", stock.secType, stock.conId
            )

            if not chains:
                logger.warning(f"No option chain found for {underlying}")
                return None

            # Find the chain for SMART exchange
            chain = None
            for c in chains:
                if c.exchange == "SMART":
                    chain = c
                    break
            if chain is None:
                chain = chains[0]

            # Convert expiry_min_days/max_days to dates
            # ONLY apply min/max days defaults if expiry_start/expiry_end are not provided
            today = date.today()
            if expiry_start is None and expiry_min_days is not None:
                expiry_start = today + timedelta(days=expiry_min_days)
            if expiry_end is None and expiry_max_days is not None:
                expiry_end = today + timedelta(days=expiry_max_days)

            # Filter expirations by date range
            expirations = []
            for exp in chain.expirations:
                exp_date = datetime.strptime(exp, "%Y%m%d").date()
                if expiry_start and exp_date < expiry_start:
                    continue
                if expiry_end and exp_date > expiry_end:
                    continue
                expirations.append(exp_date)

            if not expirations:
                logger.warning(f"No expirations found in specified range for {underlying}")
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
                                lot_size=100,
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
        """Fetch market data for multiple option contracts.

        Note: min_volume filter is applied AFTER fetching market data, as volume
        is only available from the API response. Contract qualification failures
        (Error 200) are logged and skipped gracefully.

        Args:
            contracts: List of OptionContract to fetch quotes for
            min_volume: Filter out options with volume below this (post-fetch filter)
            request_delay: Delay between requests in seconds (rate limiting)

        Returns:
            List of OptionQuote with market data (Greeks, prices, volume, etc.)
        """
        self._ensure_connected()

        if not contracts:
            return []

        results = []
        skipped_contracts = 0
        filtered_by_volume = 0

        logger.info(f"Fetching quotes for {len(contracts)} contracts...")

        for i, contract in enumerate(contracts):
            try:
                # Create IBKR Option contract
                opt = Option(
                    contract.underlying,
                    contract.expiry_date.strftime("%Y%m%d"),
                    contract.strike_price,
                    "C" if contract.option_type == OptionType.CALL else "P",
                    "SMART",
                )

                # Qualify contract - this may fail for non-existent strikes
                qualified = self._ib.qualifyContracts(opt)
                # Check if qualification succeeded (conId should be populated)
                if not qualified or not hasattr(opt, 'conId') or not opt.conId:
                    logger.debug(f"Contract not found (skipping): {contract.symbol} "
                                f"(strike={contract.strike_price}, expiry={contract.expiry_date})")
                    skipped_contracts += 1
                    continue

                # Request market data with Greeks (streaming mode)
                # Generic tick types: 100=Option Volume, 101=Open Interest, 104=Historical Volatility, 106=IV
                # Note: snapshot=True does NOT work with generic tick types for options
                ticker = self._ib.reqMktData(opt, "100,101,104,106", snapshot=False, regulatorySnapshot=False)

                # Wait for streaming data - check periodically for up to 2 seconds
                for _ in range(4):
                    self._ib.sleep(0.5)
                    # Check if we got any meaningful data
                    has_price = (ticker.bid == ticker.bid and ticker.bid > 0) or \
                                (ticker.ask == ticker.ask and ticker.ask > 0) or \
                                (ticker.last == ticker.last and ticker.last > 0)
                    has_greeks = ticker.modelGreeks is not None
                    if has_price or has_greeks:
                        break

                # Debug: Log raw ticker values
                logger.debug(f"Raw ticker for {contract.symbol}: "
                            f"last={ticker.last}, bid={ticker.bid}, ask={ticker.ask}, "
                            f"close={ticker.close}, volume={ticker.volume}, "
                            f"modelGreeks={ticker.modelGreeks}")

                # Extract Greeks
                greeks = None
                model_greeks = ticker.modelGreeks
                iv = None
                if model_greeks:
                    greeks = Greeks(
                        delta=model_greeks.delta if model_greeks.delta == model_greeks.delta else None,
                        gamma=model_greeks.gamma if model_greeks.gamma == model_greeks.gamma else None,
                        theta=model_greeks.theta if model_greeks.theta == model_greeks.theta else None,
                        vega=model_greeks.vega if model_greeks.vega == model_greeks.vega else None,
                    )
                    if model_greeks.impliedVol == model_greeks.impliedVol:
                        iv = model_greeks.impliedVol

                # Extract values, checking for NaN and invalid values (-1 = no data in IBKR)
                last_price = ticker.last if ticker.last == ticker.last and ticker.last > 0 else None
                bid = ticker.bid if ticker.bid == ticker.bid and ticker.bid > 0 else None
                ask = ticker.ask if ticker.ask == ticker.ask and ticker.ask > 0 else None
                volume = int(ticker.volume) if ticker.volume == ticker.volume and ticker.volume >= 0 else None

                # Try close price if no real-time data
                if last_price is None and ticker.close == ticker.close and ticker.close > 0:
                    last_price = ticker.close

                # Debug logging for each contract
                iv_str = f"{iv:.4f}" if iv is not None else "N/A"
                delta_str = f"{greeks.delta:.4f}" if greeks and greeks.delta is not None else "N/A"
                logger.debug(f"Processed quote for {contract.symbol}: last={last_price}, bid={bid}, ask={ask}, "
                            f"vol={volume}, iv={iv_str}, delta={delta_str}")

                quote = OptionQuote(
                    contract=contract,
                    timestamp=datetime.now(),
                    last_price=last_price,
                    bid=bid,
                    ask=ask,
                    volume=volume,
                    open_interest=None,  # Not available in snapshot
                    iv=iv,
                    greeks=greeks if greeks else Greeks(),
                    source=self.name,
                )

                # Cancel streaming subscription
                self._ib.cancelMktData(opt)

                # Apply volume filter (post-fetch)
                if min_volume is not None and (quote.volume is None or quote.volume < min_volume):
                    logger.debug(f"Filtered by volume: {contract.symbol} (vol={quote.volume}, min={min_volume})")
                    filtered_by_volume += 1
                    continue

                results.append(quote)

                # Rate limiting between requests
                if request_delay > 0 and i < len(contracts) - 1:
                    self._ib.sleep(request_delay)

            except Exception as e:
                logger.warning(f"Error fetching quote for {contract.symbol}: {e}")
                skipped_contracts += 1
                continue

        logger.info(f"Fetched {len(results)} option quotes from {len(contracts)} contracts "
                   f"(skipped={skipped_contracts}, filtered_by_volume={filtered_by_volume})")
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
            if not qualified:
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
            if not qualified:
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

                contract = OptionContract(
                    symbol=f"{underlying}{exp_str}{right}{int(strike*1000):08d}",
                    underlying=underlying,
                    option_type=OptionType.CALL if right == "C" else OptionType.PUT,
                    strike_price=strike,
                    expiry_date=expiry,
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
            if not qualified:
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
                logger.warning(f"No volatility data available for {symbol}. "
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
            logger.info(f"Volatility for {normalized}: IV={iv_str}, HV={hv_str}, "
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
