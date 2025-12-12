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
        self._client_id = client_id or int(os.getenv("IBKR_CLIENT_ID", "1"))
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
            symbol: Stock symbol (e.g., 'AAPL').

        Returns:
            Stock contract object.
        """
        # Remove any market prefix if present
        if "." in symbol:
            symbol = symbol.split(".")[-1]
        return Stock(symbol, "SMART", "USD")

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to standard format.

        Args:
            symbol: Stock symbol.

        Returns:
            Symbol in standard format (without market prefix).
        """
        symbol = symbol.upper()
        # Remove market prefix if present (e.g., US.AAPL -> AAPL)
        if "." in symbol:
            return symbol.split(".")[-1]
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
    ) -> OptionChain | None:
        """Get option chain for an underlying asset."""
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

            # Filter expirations by date range
            expirations = []
            for exp in chain.expirations:
                exp_date = datetime.strptime(exp, "%Y%m%d").date()
                if expiry_start and exp_date < expiry_start:
                    continue
                if expiry_end and exp_date > expiry_end:
                    continue
                expirations.append(exp_date)

            # Get underlying price for strike filtering
            ticker = self._ib.reqMktData(stock, "", False, False)
            self._ib.sleep(1)
            underlying_price = ticker.last if ticker.last == ticker.last else 100
            self._ib.cancelMktData(stock)

            # Filter strikes around current price (±20%)
            strike_range = underlying_price * 0.2
            strikes = [
                s for s in chain.strikes
                if underlying_price - strike_range <= s <= underlying_price + strike_range
            ]

            # Limit strikes to avoid too many contracts
            if len(strikes) > 20:
                # Take nearest 20 strikes
                strikes = sorted(strikes, key=lambda x: abs(x - underlying_price))[:20]
                strikes = sorted(strikes)

            # Build option contracts (limit to first 3 expirations)
            calls = []
            puts = []
            expiry_dates = sorted(expirations)[:3]

            for expiry in expiry_dates:
                exp_str = expiry.strftime("%Y%m%d")
                for strike in strikes:
                    for right in ["C", "P"]:
                        try:
                            opt = Option(
                                underlying,
                                exp_str,
                                strike,
                                right,
                                "SMART",
                            )
                            contract = OptionContract(
                                symbol=f"{underlying}{exp_str}{right}{int(strike*1000):08d}",
                                underlying=underlying,
                                option_type=OptionType.CALL if right == "C" else OptionType.PUT,
                                strike_price=strike,
                                expiry_date=expiry,
                                lot_size=100,
                            )
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
            ticker = self._ib.reqMktData(opt, "100,101,104,106", False, False)
            self._ib.sleep(2)  # Wait for Greeks to populate

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

            quote = OptionQuote(
                contract=contract,
                timestamp=datetime.now(),
                last_price=ticker.last if ticker.last == ticker.last else None,
                bid=ticker.bid if ticker.bid == ticker.bid else None,
                ask=ticker.ask if ticker.ask == ticker.ask else None,
                volume=int(ticker.volume) if ticker.volume == ticker.volume else None,
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

        Note: IBKR API has limited fundamental data support.
        Use Yahoo Finance for comprehensive fundamentals.
        """
        logger.warning("IBKR has limited fundamental data. Consider using Yahoo Finance.")
        return None

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
