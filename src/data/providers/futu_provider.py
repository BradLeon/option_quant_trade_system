"""Futu OpenAPI data provider implementation."""

import logging
import os
import time
from datetime import date, datetime
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
    RateLimitError,
)

logger = logging.getLogger(__name__)

# Try to import futu, but allow graceful degradation
try:
    from futu import (
        KLType,
        OpenQuoteContext,
        OptionType as FutuOptionType,
        RET_ERROR,
        RET_OK,
        SubType,
    )
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    logger.warning("futu-api not installed. Futu provider will be unavailable.")


# Mapping from our KlineType to Futu's KLType
KLINE_TYPE_MAP = {
    KlineType.DAY: "KLType.K_DAY" if not FUTU_AVAILABLE else None,
    KlineType.WEEK: "KLType.K_WEEK" if not FUTU_AVAILABLE else None,
    KlineType.MONTH: "KLType.K_MON" if not FUTU_AVAILABLE else None,
    KlineType.MIN_1: "KLType.K_1M" if not FUTU_AVAILABLE else None,
    KlineType.MIN_5: "KLType.K_5M" if not FUTU_AVAILABLE else None,
    KlineType.MIN_15: "KLType.K_15M" if not FUTU_AVAILABLE else None,
    KlineType.MIN_30: "KLType.K_30M" if not FUTU_AVAILABLE else None,
    KlineType.MIN_60: "KLType.K_60M" if not FUTU_AVAILABLE else None,
}

if FUTU_AVAILABLE:
    KLINE_TYPE_MAP = {
        KlineType.DAY: KLType.K_DAY,
        KlineType.WEEK: KLType.K_WEEK,
        KlineType.MONTH: KLType.K_MON,
        KlineType.MIN_1: KLType.K_1M,
        KlineType.MIN_5: KLType.K_5M,
        KlineType.MIN_15: KLType.K_15M,
        KlineType.MIN_30: KLType.K_30M,
        KlineType.MIN_60: KLType.K_60M,
    }


class FutuProvider(DataProvider):
    """Futu OpenAPI data provider.

    Requires OpenD gateway to be running locally.

    Usage:
        with FutuProvider() as provider:
            quote = provider.get_stock_quote("US.AAPL")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """Initialize Futu provider.

        Args:
            host: OpenD gateway host. Defaults to env var or 127.0.0.1.
            port: OpenD gateway port. Defaults to env var or 11111.
        """
        load_dotenv()

        self._host = host or os.getenv("FUTU_HOST", "127.0.0.1")
        self._port = port or int(os.getenv("FUTU_PORT", "11111"))
        self._quote_ctx: Any = None
        self._connected = False
        self._lock = Lock()

        # Rate limiting
        self._last_request_time: dict[str, float] = {}
        self._rate_limits = {
            "quote": (60, 30),  # 60 requests per 30 seconds
            "option_chain": (10, 30),  # 10 requests per 30 seconds
            "history_kline": (60, 30),  # 60 requests per 30 seconds
        }

    @property
    def name(self) -> str:
        """Provider name."""
        return "futu"

    @property
    def is_available(self) -> bool:
        """Check if provider is available."""
        if not FUTU_AVAILABLE:
            return False
        return self._connected

    def __enter__(self) -> "FutuProvider":
        """Enter context manager, establish connection."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager, close connection."""
        self.disconnect()

    def connect(self) -> None:
        """Establish connection to OpenD gateway."""
        if not FUTU_AVAILABLE:
            raise ConnectionError("futu-api is not installed")

        with self._lock:
            if self._connected:
                return

            try:
                self._quote_ctx = OpenQuoteContext(
                    host=self._host, port=self._port
                )
                self._connected = True
                logger.info(f"Connected to Futu OpenD at {self._host}:{self._port}")
            except Exception as e:
                self._connected = False
                raise ConnectionError(f"Failed to connect to OpenD: {e}")

    def disconnect(self) -> None:
        """Close connection to OpenD gateway."""
        with self._lock:
            if self._quote_ctx:
                try:
                    self._quote_ctx.close()
                except Exception as e:
                    logger.warning(f"Error closing Futu connection: {e}")
                finally:
                    self._quote_ctx = None
                    self._connected = False
                    logger.info("Disconnected from Futu OpenD")

    def _check_rate_limit(self, operation: str) -> None:
        """Check and enforce rate limits.

        Args:
            operation: Operation type (quote, option_chain, history_kline).

        Raises:
            RateLimitError: If rate limit would be exceeded.
        """
        if operation not in self._rate_limits:
            return

        max_requests, period = self._rate_limits[operation]
        current_time = time.time()
        last_time = self._last_request_time.get(operation, 0)

        # Simple rate limiting: ensure minimum interval between requests
        min_interval = period / max_requests
        elapsed = current_time - last_time

        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self._last_request_time[operation] = time.time()

    def _ensure_connected(self) -> None:
        """Ensure connection is established."""
        if not self._connected:
            self.connect()

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to Futu format (e.g., US.AAPL).

        Args:
            symbol: Stock symbol.

        Returns:
            Symbol in Futu format.
        """
        symbol = symbol.upper()
        if "." not in symbol:
            # Default to US market
            return f"US.{symbol}"
        return symbol

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """Get real-time stock quote."""
        quotes = self.get_stock_quotes([symbol])
        return quotes[0] if quotes else None

    def get_stock_quotes(self, symbols: list[str]) -> list[StockQuote]:
        """Get real-time quotes for multiple stocks."""
        self._ensure_connected()
        self._check_rate_limit("quote")

        normalized = [self.normalize_symbol(s) for s in symbols]

        try:
            # Subscribe first (required by Futu API)
            ret_sub, err_msg = self._quote_ctx.subscribe(
                normalized, [SubType.QUOTE], subscribe_push=False
            )
            if ret_sub != RET_OK:
                logger.error(f"Subscribe failed: {err_msg}")
                return []

            # Get quotes
            ret, data = self._quote_ctx.get_stock_quote(normalized)
            if ret != RET_OK:
                logger.error(f"Get quote failed: {data}")
                return []

            results = []
            for _, row in data.iterrows():
                quote = StockQuote(
                    symbol=row["code"],
                    timestamp=datetime.now(),
                    open=row.get("open_price"),
                    high=row.get("high_price"),
                    low=row.get("low_price"),
                    close=row.get("last_price"),
                    volume=row.get("volume"),
                    turnover=row.get("turnover"),
                    prev_close=row.get("prev_close_price"),
                    change=row.get("price_spread"),
                    change_percent=row.get("amplitude"),
                    source=self.name,
                )
                results.append(quote)

            return results

        except Exception as e:
            logger.error(f"Error getting stock quotes: {e}")
            return []

    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """Get historical K-line data."""
        self._ensure_connected()
        self._check_rate_limit("history_kline")

        symbol = self.normalize_symbol(symbol)
        futu_ktype = KLINE_TYPE_MAP.get(ktype)

        if futu_ktype is None:
            logger.error(f"Unsupported K-line type: {ktype}")
            return []

        try:
            ret, data, page_req_key = self._quote_ctx.request_history_kline(
                symbol,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                ktype=futu_ktype,
                max_count=1000,
            )

            if ret != RET_OK:
                logger.error(f"Get history kline failed: {data}")
                return []

            results = []
            all_data = [data]

            # Handle pagination
            while page_req_key is not None:
                self._check_rate_limit("history_kline")
                ret, data, page_req_key = self._quote_ctx.request_history_kline(
                    symbol,
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    ktype=futu_ktype,
                    max_count=1000,
                    page_req_key=page_req_key,
                )
                if ret == RET_OK:
                    all_data.append(data)

            import pandas as pd
            combined = pd.concat(all_data, ignore_index=True)

            for _, row in combined.iterrows():
                bar = KlineBar(
                    symbol=row["code"],
                    timestamp=datetime.strptime(row["time_key"], "%Y-%m-%d %H:%M:%S"),
                    ktype=ktype,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    turnover=row.get("turnover"),
                    source=self.name,
                )
                results.append(bar)

            return sorted(results, key=lambda x: x.timestamp)

        except Exception as e:
            logger.error(f"Error getting history kline: {e}")
            return []

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
    ) -> OptionChain | None:
        """Get option chain for an underlying asset."""
        self._ensure_connected()
        self._check_rate_limit("option_chain")

        underlying = self.normalize_symbol(underlying)

        try:
            kwargs: dict[str, Any] = {"code": underlying}
            if expiry_start:
                kwargs["start"] = expiry_start.strftime("%Y-%m-%d")
            if expiry_end:
                kwargs["end"] = expiry_end.strftime("%Y-%m-%d")

            ret, data = self._quote_ctx.get_option_chain(**kwargs)

            if ret != RET_OK:
                logger.error(f"Get option chain failed: {data}")
                return None

            calls = []
            puts = []
            expiry_dates = set()

            for _, row in data.iterrows():
                expiry = datetime.strptime(row["strike_time"], "%Y-%m-%d").date()
                expiry_dates.add(expiry)

                option_type = (
                    OptionType.CALL
                    if row["option_type"] == "CALL"
                    else OptionType.PUT
                )

                contract = OptionContract(
                    symbol=row["code"],
                    underlying=underlying,
                    option_type=option_type,
                    strike_price=row["strike_price"],
                    expiry_date=expiry,
                    lot_size=row.get("lot_size", 100),
                )

                # Note: Greeks require additional quote subscription
                quote = OptionQuote(
                    contract=contract,
                    timestamp=datetime.now(),
                    source=self.name,
                )

                if option_type == OptionType.CALL:
                    calls.append(quote)
                else:
                    puts.append(quote)

            return OptionChain(
                underlying=underlying,
                timestamp=datetime.now(),
                expiry_dates=sorted(list(expiry_dates)),
                calls=calls,
                puts=puts,
                source=self.name,
            )

        except Exception as e:
            logger.error(f"Error getting option chain: {e}")
            return None

    def get_option_quote(self, symbol: str) -> OptionQuote | None:
        """Get quote for a specific option contract."""
        self._ensure_connected()
        self._check_rate_limit("quote")

        symbol = self.normalize_symbol(symbol)

        try:
            # Subscribe to get real-time quote
            ret_sub, err_msg = self._quote_ctx.subscribe(
                [symbol], [SubType.QUOTE], subscribe_push=False
            )
            if ret_sub != RET_OK:
                logger.error(f"Subscribe failed: {err_msg}")
                return None

            ret, data = self._quote_ctx.get_stock_quote([symbol])
            if ret != RET_OK or data.empty:
                logger.error(f"Get option quote failed: {data}")
                return None

            row = data.iloc[0]

            # Parse option details from symbol or use additional API
            # This is simplified - actual implementation needs symbol parsing
            contract = OptionContract(
                symbol=row["code"],
                underlying=row.get("stock_owner", ""),
                option_type=OptionType.CALL,  # Need to determine from symbol
                strike_price=row.get("strike_price", 0),
                expiry_date=date.today(),  # Need to parse from symbol
            )

            greeks = Greeks(
                delta=row.get("delta"),
                gamma=row.get("gamma"),
                theta=row.get("theta"),
                vega=row.get("vega"),
                rho=row.get("rho"),
            )

            # IV is stored as percentage (e.g., 25 = 25%)
            iv = row.get("implied_volatility")
            if iv is not None:
                iv = iv / 100.0

            return OptionQuote(
                contract=contract,
                timestamp=datetime.now(),
                last_price=row.get("last_price"),
                bid=row.get("bid_price"),
                ask=row.get("ask_price"),
                volume=row.get("volume"),
                open_interest=row.get("open_interest"),
                iv=iv,
                greeks=greeks,
                source=self.name,
            )

        except Exception as e:
            logger.error(f"Error getting option quote: {e}")
            return None

    def get_option_quotes_batch(
        self,
        contracts: list[OptionContract],
        min_volume: int | None = None,
    ) -> list[OptionQuote]:
        """Fetch market data for multiple option contracts.

        Args:
            contracts: List of OptionContract to fetch quotes for
            min_volume: Filter out options with volume below this (post-fetch filter)

        Returns:
            List of OptionQuote with market data (Greeks, prices, volume, etc.)
        """
        self._ensure_connected()

        if not contracts:
            return []

        # Extract symbols from contracts
        symbols = [c.symbol for c in contracts]
        contract_map = {c.symbol: c for c in contracts}

        logger.info(f"Fetching quotes for {len(contracts)} option contracts...")

        try:
            # Use get_market_snapshot which returns bid/ask and option Greeks
            self._check_rate_limit("quote")
            ret, data = self._quote_ctx.get_market_snapshot(symbols)
            if ret != RET_OK:
                logger.error(f"Get market snapshot failed: {data}")
                return []

            results = []
            skipped = 0

            # Debug: print all available columns
            logger.debug(f"Available columns in snapshot data: {list(data.columns)}")

            for _, row in data.iterrows():
                code = row["code"]
                contract = contract_map.get(code)
                if not contract:
                    logger.debug(f"Contract not found for code: {code}")
                    skipped += 1
                    continue

                # Debug: print all values for first contract
                if len(results) == 0:
                    logger.debug(f"Raw row data for {code}: {row.to_dict()}")

                # Helper to safely extract numeric value (handles NaN and 'N/A')
                def safe_float(val):
                    if val is None or val == "N/A":
                        return None
                    try:
                        f = float(val)
                        return f if f == f else None  # NaN check
                    except (ValueError, TypeError):
                        return None

                def safe_int(val):
                    f = safe_float(val)
                    return int(f) if f is not None else None

                # Extract price data
                last_price = safe_float(row.get("last_price"))
                if last_price is not None and last_price <= 0:
                    last_price = None

                bid = safe_float(row.get("bid_price"))
                if bid is not None and bid <= 0:
                    bid = None

                ask = safe_float(row.get("ask_price"))
                if ask is not None and ask <= 0:
                    ask = None

                volume = safe_int(row.get("volume"))

                # Extract Greeks (get_market_snapshot uses option_ prefix)
                greeks = Greeks(
                    delta=safe_float(row.get("option_delta")),
                    gamma=safe_float(row.get("option_gamma")),
                    theta=safe_float(row.get("option_theta")),
                    vega=safe_float(row.get("option_vega")),
                    rho=safe_float(row.get("option_rho")),
                )

                # IV is stored as percentage (e.g., 25 = 25%)
                iv = safe_float(row.get("option_implied_volatility"))
                if iv is not None:
                    iv = iv / 100.0  # Convert percentage to decimal

                # Open interest
                open_interest = safe_int(row.get("option_open_interest"))

                # Debug logging
                logger.debug(f"Quote for {code}: last={last_price}, bid={bid}, ask={ask}, "
                            f"vol={volume}, iv={iv}, delta={greeks.delta}")

                quote = OptionQuote(
                    contract=contract,
                    timestamp=datetime.now(),
                    last_price=last_price,
                    bid=bid,
                    ask=ask,
                    volume=volume,
                    open_interest=open_interest,
                    iv=iv,
                    greeks=greeks,
                    source=self.name,
                )

                # Apply volume filter
                if min_volume is not None and (quote.volume is None or quote.volume < min_volume):
                    logger.debug(f"Filtered by volume: {code} (vol={quote.volume}, min={min_volume})")
                    skipped += 1
                    continue

                results.append(quote)

            logger.info(f"Fetched {len(results)} option quotes from {len(contracts)} contracts (skipped={skipped})")
            return results

        except Exception as e:
            logger.error(f"Error getting option quotes batch: {e}")
            return []

    def get_fundamental(self, symbol: str) -> Fundamental | None:
        """Get fundamental data for a stock.

        Note: Futu API has limited fundamental data support.
        Use Yahoo Finance for comprehensive fundamentals.
        """
        logger.warning("Futu has limited fundamental data. Consider using Yahoo Finance.")
        return None

    def get_macro_data(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroData]:
        """Get macro economic data.

        Note: Use get_history_kline for index data.
        """
        # For indices like ^VIX, we can use kline data
        klines = self.get_history_kline(
            indicator, KlineType.DAY, start_date, end_date
        )

        return [
            MacroData.from_kline(
                indicator=indicator,
                data_date=k.timestamp.date(),
                open_=k.open,
                high=k.high,
                low=k.low,
                close=k.close,
                volume=k.volume,
                source=self.name,
            )
            for k in klines
        ]
