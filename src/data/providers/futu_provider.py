"""Futu OpenAPI data provider implementation."""

import logging
import os
import time
from datetime import date, datetime
from threading import Lock
from typing import Any

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
    MarginRequirement,
    MarginSource,
    OptionChain,
    OptionQuote,
    StockQuote,
)
from src.data.models.option import Greeks, OptionContract, OptionType
from src.data.models.stock import KlineType
from src.data.providers.base import (
    AccountProvider,
    ConnectionError,
    DataNotFoundError,
    DataProvider,
    RateLimitError,
)
from src.data.utils import SymbolFormatter

logger = logging.getLogger(__name__)

# Try to import futu, but allow graceful degradation
try:
    from futu import (
        KLType,
        OpenQuoteContext,
        OpenSecTradeContext,
        OptionCondType,
        OptionDataFilter,
        OptionType as FutuOptionType,
        OrderType as FutuOrderType,
        RET_ERROR,
        RET_OK,
        SubType,
        TrdEnv,
        TrdMarket,
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


class FutuProvider(DataProvider, AccountProvider):
    """Futu OpenAPI data provider.

    Requires OpenD gateway to be running locally.
    Supports both market data and account/position queries.

    Usage:
        with FutuProvider() as provider:
            quote = provider.get_stock_quote("US.AAPL")
            positions = provider.get_positions()
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        account_type: AccountType = AccountType.PAPER,
    ) -> None:
        """Initialize Futu provider.

        Args:
            host: OpenD gateway host. Defaults to env var or 127.0.0.1.
            port: OpenD gateway port. Defaults to env var or 11111.
            account_type: Account type for trading context (PAPER or REAL).
        """
        load_dotenv()

        self._host = host or os.getenv("FUTU_HOST", "127.0.0.1")
        self._port = port or int(os.getenv("FUTU_PORT", "11111"))
        self._account_type = account_type
        self._quote_ctx: Any = None
        self._trd_ctx: Any = None  # Trade context for account queries
        self._connected = False
        self._lock = Lock()

        # Rate limiting
        self._last_request_time: dict[str, float] = {}
        self._rate_limits = {
            "quote": (60, 30),  # 60 requests per 30 seconds
            "option_chain": (10, 30),  # 10 requests per 30 seconds
            "history_kline": (60, 30),  # 60 requests per 30 seconds
            "option_expiration": (10, 30),  # 10 requests per 30 seconds
            "margin_query": (10, 30),  # 10 requests per 30 seconds (acctradinginfo_query)
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
        """Normalize symbol to Futu format (e.g., US.AAPL, HK.00700).

        Handles various input formats:
        - Plain symbol: AAPL → US.AAPL
        - Yahoo HK format: 0700.HK → HK.00700
        - Yahoo US format: AAPL (no suffix) → US.AAPL
        - Futu format: US.AAPL, HK.00700 (unchanged)

        Args:
            symbol: Stock symbol in any supported format.

        Returns:
            Symbol in Futu format.
        """
        symbol = symbol.upper()

        # Handle Yahoo-style HK format: 0700.HK → HK.00700
        if symbol.endswith(".HK"):
            code = symbol[:-3]  # Remove .HK suffix
            code = code.zfill(5)  # Pad to 5 digits (e.g., 700 → 00700)
            return f"HK.{code}"

        # Handle Yahoo-style SZ format: 000001.SZ → SZ.000001
        if symbol.endswith(".SZ"):
            code = symbol[:-3]
            return f"SZ.{code}"

        # Handle Yahoo-style SS format (Shanghai): 600000.SS → SH.600000
        if symbol.endswith(".SS"):
            code = symbol[:-3]
            return f"SH.{code}"

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
        subscribed = False

        try:
            # Subscribe first (required by Futu API)
            ret_sub, err_msg = self._quote_ctx.subscribe(
                normalized, [SubType.QUOTE], subscribe_push=False
            )
            if ret_sub != RET_OK:
                logger.error(f"Subscribe failed: {err_msg}")
                return []
            subscribed = True

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
        finally:
            # Unsubscribe to free quota
            if subscribed:
                self._quote_ctx.unsubscribe(normalized, [SubType.QUOTE])

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

    def get_option_expiration_dates(
        self,
        underlying: str,
    ) -> list[date]:
        """Get available option expiration dates for an underlying.

        必须先调用此 API 获取有效到期日，再用于 get_option_chain。
        港股期权是月频到期，直接用任意日期范围会返回空数据。

        Args:
            underlying: Underlying symbol (e.g., "0700.HK")

        Returns:
            List of available expiration dates, sorted ascending.
        """
        self._ensure_connected()
        self._check_rate_limit("option_expiration")

        underlying = self.normalize_symbol(underlying)

        try:
            ret, data = self._quote_ctx.get_option_expiration_date(code=underlying)

            if ret != RET_OK:
                logger.error(f"Get option expiration dates failed: {data}")
                return []

            # 解析到期日列表
            expiry_dates = []
            for _, row in data.iterrows():
                expiry_str = row["strike_time"]
                expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                expiry_dates.append(expiry)

            logger.debug(f"{underlying} 可用到期日: {expiry_dates}")
            return sorted(expiry_dates)

        except Exception as e:
            logger.error(f"Error getting option expiration dates: {e}")
            return []

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
        # ===== Futu 原生过滤参数 =====
        option_type: str | None = None,  # "call" / "put" / None
        option_cond_type: str | None = None,  # "otm" / "itm" / None
        delta_min: float | None = None,
        delta_max: float | None = None,
        open_interest_min: int | None = None,
        vol_min: int | None = None,
    ) -> OptionChain | None:
        """Get option chain for an underlying asset.

        正确流程（参考 Futu 官方 Demo）：
        1. 先调用 get_option_expiration_dates 获取有效到期日
        2. 按日期范围过滤
        3. 对每个有效到期日调用 get_option_chain (start=date, end=date)

        Args:
            underlying: Underlying symbol (e.g., "2800.HK")
            expiry_start: Filter options with expiry >= this date
            expiry_end: Filter options with expiry <= this date
            option_type: "call" / "put" / None (None = all)
            option_cond_type: "otm" (虚值) / "itm" (实值) / None
            delta_min: Minimum delta filter
            delta_max: Maximum delta filter
            open_interest_min: Minimum open interest filter
            vol_min: Minimum volume filter
        """
        self._ensure_connected()

        underlying = self.normalize_symbol(underlying)

        try:
            # ===== Step 1: 获取有效到期日 =====
            all_expiry_dates = self.get_option_expiration_dates(underlying)
            if not all_expiry_dates:
                logger.warning(f"{underlying} 无可用到期日")
                return None

            # ===== Step 2: 按日期范围过滤 =====
            # 注意: 到期日是固定的（如每月最后一个交易日），可能刚好在边界外
            # 使用 7 天容差，避免 expiry_end=2/25 而到期日=2/26 被排除的情况
            BOUNDARY_TOLERANCE_DAYS = 7

            valid_dates = all_expiry_dates
            if expiry_start:
                valid_dates = [d for d in valid_dates if d >= expiry_start]
            if expiry_end:
                from datetime import timedelta
                expiry_end_with_tolerance = expiry_end + timedelta(days=BOUNDARY_TOLERANCE_DAYS)
                valid_dates = [d for d in valid_dates if d <= expiry_end_with_tolerance]

            if not valid_dates:
                logger.warning(
                    f"{underlying} 无符合条件的到期日 "
                    f"(范围: {expiry_start} ~ {expiry_end}+{BOUNDARY_TOLERANCE_DAYS}d, "
                    f"可用: {all_expiry_dates[:3]}...)"
                )
                return None

            logger.debug(f"{underlying} 符合条件的到期日: {valid_dates}")

            # ===== Step 3: 构建公共请求参数 =====
            base_kwargs: dict[str, Any] = {"code": underlying}

            # 期权类型过滤
            if option_type:
                type_map = {
                    "call": FutuOptionType.CALL,
                    "put": FutuOptionType.PUT,
                }
                base_kwargs["option_type"] = type_map.get(
                    option_type.lower(), FutuOptionType.ALL
                )

            # 数据过滤器
            # 注意: open_interest_min 不在 API 层过滤，改为应用层后处理
            # 因为 Futu API 的 OI 过滤可能过于严格，导致返回空数据
            filter_params: dict[str, Any] = {}
            if delta_min is not None:
                filter_params["delta_min"] = delta_min
            if delta_max is not None:
                filter_params["delta_max"] = delta_max
            # open_interest_min: 移到应用层后处理
            if vol_min is not None:
                filter_params["vol_min"] = vol_min

            if filter_params:
                base_kwargs["data_filter"] = OptionDataFilter(**filter_params)

            # 记录被忽略的 API 层过滤器
            if open_interest_min is not None:
                logger.debug(f"OI过滤 (>={open_interest_min}) 将在应用层后处理")

            # ===== Step 4: 对每个到期日查询 =====
            all_data = []
            for expiry_date in valid_dates:
                self._check_rate_limit("option_chain")

                kwargs = base_kwargs.copy()
                date_str = expiry_date.strftime("%Y-%m-%d")
                kwargs["start"] = date_str
                kwargs["end"] = date_str

                logger.debug(f"Futu get_option_chain: {expiry_date}")

                ret, data = self._quote_ctx.get_option_chain(**kwargs)

                if ret != RET_OK:
                    logger.warning(f"Get option chain for {expiry_date} failed: {data}")
                    continue

                if data.empty:
                    # 记录空数据的原因（可能是过滤条件太严格）
                    logger.debug(
                        f"  -> 0 rows (过滤条件: option_type={option_type}, "
                        f"option_cond_type={option_cond_type}, "
                        f"OI>={open_interest_min}, delta={delta_min}~{delta_max})"
                    )
                else:
                    all_data.append(data)
                    logger.debug(f"  -> {len(data)} rows")

            # ===== Step 5: 合并结果 =====
            if not all_data:
                logger.warning(f"{underlying} 所有到期日均无数据")
                return None

            import pandas as pd
            data = pd.concat(all_data, ignore_index=True)
            logger.debug(f"Futu get_option_chain 合计 {len(data)} rows")

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

            # ===== 后处理：OTM/ITM 过滤 (Futu API 对美股可能不生效) =====
            if option_cond_type and (calls or puts):
                # 获取标的价格用于 OTM/ITM 判断
                underlying_price = None
                try:
                    stock_quote = self.get_stock_quote(underlying)
                    if stock_quote and stock_quote.close:
                        underlying_price = stock_quote.close
                except Exception as e:
                    logger.warning(f"Could not fetch underlying price for OTM filter: {e}")

                if underlying_price:
                    cond_lower = option_cond_type.lower()
                    original_calls = len(calls)
                    original_puts = len(puts)

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

                    logger.debug(f"Futu OTM/ITM post-filter ({cond_lower}): "
                                f"underlying=${underlying_price:.2f}, "
                                f"calls {original_calls}->{len(calls)}, "
                                f"puts {original_puts}->{len(puts)}")

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
        subscribed = False

        try:
            # Subscribe to get real-time quote
            ret_sub, err_msg = self._quote_ctx.subscribe(
                [symbol], [SubType.QUOTE], subscribe_push=False
            )
            if ret_sub != RET_OK:
                logger.error(f"Subscribe failed: {err_msg}")
                return None
            subscribed = True

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
                lot_size=row.get("lot_size", 100),
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
        finally:
            # Unsubscribe to free quota
            if subscribed:
                self._quote_ctx.unsubscribe([symbol], [SubType.QUOTE])

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
        logger.debug(f"First 5 symbols: {symbols[:5]}")

        try:
            # Use subscribe + get_stock_quote for reliable batch fetching
            # This works better than get_market_snapshot for HK options
            BATCH_SIZE = 50
            all_data_rows = []

            for i in range(0, len(symbols), BATCH_SIZE):
                batch_symbols = symbols[i:i + BATCH_SIZE]
                logger.debug(f"Fetching batch {i//BATCH_SIZE + 1}: {len(batch_symbols)} symbols")

                self._check_rate_limit("quote")

                # Subscribe to quotes first
                ret_sub, err = self._quote_ctx.subscribe(
                    batch_symbols, [SubType.QUOTE], subscribe_push=False
                )
                if ret_sub != RET_OK:
                    logger.warning(f"Subscribe failed for batch {i//BATCH_SIZE + 1}: {err}")
                    continue

                # Get quotes
                ret, data = self._quote_ctx.get_stock_quote(batch_symbols)
                if ret != RET_OK:
                    logger.error(f"Get stock quote failed for batch {i//BATCH_SIZE + 1}: {data}")
                    continue

                # Collect successful rows
                for _, row in data.iterrows():
                    all_data_rows.append(row)

                # Unsubscribe to free resources
                self._quote_ctx.unsubscribe(batch_symbols, [SubType.QUOTE])

            if not all_data_rows:
                logger.warning("No data received from any batch")
                return []

            results = []
            skipped = 0

            # Process collected data
            for item in all_data_rows:
                row = item
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

                # get_stock_quote doesn't have bid/ask, use high/low as fallback
                bid = safe_float(row.get("bid_price"))  # Might not exist
                ask = safe_float(row.get("ask_price"))  # Might not exist
                if bid is None and ask is None and last_price:
                    # Use last_price as mid estimate
                    bid = last_price
                    ask = last_price

                volume = safe_int(row.get("volume"))

                # Extract Greeks (get_stock_quote uses no prefix, get_market_snapshot uses option_ prefix)
                # Try both column naming conventions
                greeks = Greeks(
                    delta=safe_float(row.get("delta") or row.get("option_delta")),
                    gamma=safe_float(row.get("gamma") or row.get("option_gamma")),
                    theta=safe_float(row.get("theta") or row.get("option_theta")),
                    vega=safe_float(row.get("vega") or row.get("option_vega")),
                    rho=safe_float(row.get("rho") or row.get("option_rho")),
                )

                # IV is stored as percentage (e.g., 25 = 25%)
                # Try both column naming conventions
                iv = safe_float(row.get("implied_volatility") or row.get("option_implied_volatility"))
                if iv is not None and iv > 1:
                    iv = iv / 100.0  # Convert percentage to decimal if > 100%

                # Open interest - try both column names
                open_interest = safe_int(row.get("open_interest") or row.get("option_open_interest"))

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

        Note: Futu fundamental data is not implemented due to API timeout issues.
        Use Yahoo provider for fundamental data (via routing).

        Args:
            symbol: Stock symbol.

        Returns:
            None - fundamental data not supported by this provider.
        """
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

    # Account Provider Methods

    def _get_trade_context(self, account_type: AccountType) -> Any:
        """Get or create trade context for account operations.

        Args:
            account_type: Real or paper account.

        Returns:
            OpenSecTradeContext instance.
        """
        if not FUTU_AVAILABLE:
            raise ConnectionError("futu-api is not installed")

        # Map account type to TrdEnv
        trd_env = TrdEnv.SIMULATE if account_type == AccountType.PAPER else TrdEnv.REAL

        # Create trade context if not exists or env changed
        if self._trd_ctx is None:
            self._trd_ctx = OpenSecTradeContext(
                host=self._host,
                port=self._port,
            )
            logger.info(f"Created Futu trade context (env={trd_env})")

        return self._trd_ctx

    def _close_trade_context(self) -> None:
        """Close trade context if open."""
        if self._trd_ctx:
            try:
                self._trd_ctx.close()
            except Exception as e:
                logger.warning(f"Error closing trade context: {e}")
            finally:
                self._trd_ctx = None

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        """Safely convert value to float, handling 'N/A' and other invalid values.

        Args:
            val: Value to convert.
            default: Default value if conversion fails.

        Returns:
            Float value or default.
        """
        if val is None or val == "N/A" or val == "":
            return default
        try:
            f = float(val)
            return f if f == f else default  # NaN check
        except (ValueError, TypeError):
            return default

    def get_margin_requirement(
        self,
        option_symbol: str,
        price: float,
        lot_size: int = 100,
        account_type: AccountType = AccountType.REAL,
    ) -> MarginRequirement | None:
        """Get margin requirement for a short option position.

        Uses Futu acctradinginfo_query API to get real margin requirements.
        Returns per-share margin (divided by lot_size) for consistency with
        other metrics.

        Args:
            option_symbol: Futu option symbol (e.g., "HK.TCH260123P580000").
            price: Option price for margin calculation.
            lot_size: Contract multiplier (default 100, varies by underlying).
            account_type: REAL or PAPER account (PAPER may not support options).

        Returns:
            MarginRequirement with per-share initial and maintenance margin,
            or None if query fails.

        Note:
            This API requires REAL account for HK options.
            PAPER account returns error "当前模拟账号不支持此证券类型".
        """
        if not FUTU_AVAILABLE:
            logger.warning("Futu API not available")
            return None

        try:
            self._check_rate_limit("margin_query")

            trd_ctx = self._get_trade_context(account_type)
            trd_env = TrdEnv.SIMULATE if account_type == AccountType.PAPER else TrdEnv.REAL

            # Query trading info
            ret, data = trd_ctx.acctradinginfo_query(
                order_type=FutuOrderType.NORMAL,
                code=option_symbol,
                price=price,
                trd_env=trd_env,
            )

            if ret != RET_OK or data is None or data.empty:
                logger.warning(f"acctradinginfo_query failed for {option_symbol}: {data}")
                return None

            row = data.iloc[0]

            # 调试：打印 API 返回的原始数据
            logger.debug(
                f"Margin API raw for {option_symbol}: "
                f"short_required_im={row.get('short_required_im')}, "
                f"long_required_im={row.get('long_required_im')}, "
                f"all_keys={list(row.keys())[:10]}..."
            )

            # Extract margin values (these are total contract margins)
            short_init_margin = self._safe_float(row.get("short_required_im"))
            long_init_margin = self._safe_float(row.get("long_required_im"))

            # Use short margin for selling options
            total_margin = short_init_margin if short_init_margin > 0 else long_init_margin

            if total_margin <= 0:
                logger.warning(
                    f"No valid margin data for {option_symbol}: "
                    f"short_im={short_init_margin}, long_im={long_init_margin}"
                )
                return None

            # Convert to per-share for consistency with other metrics
            per_share_margin = total_margin / lot_size

            # Futu doesn't provide maintenance margin separately
            # Estimate as ~80% of initial (typical for HK options)
            maintenance_margin = per_share_margin * 0.8

            return MarginRequirement(
                initial_margin=per_share_margin,
                maintenance_margin=maintenance_margin,
                source=MarginSource.FUTU_API,
                is_estimated=False,
                currency="HKD",  # Futu primarily for HK market
            )

        except Exception as e:
            logger.error(f"Error querying Futu margin for {option_symbol}: {e}")
            return None

    def get_account_summary(
        self,
        account_type: AccountType = AccountType.PAPER,
    ) -> AccountSummary | None:
        """Get account summary information.

        Args:
            account_type: Real or paper account.

        Returns:
            AccountSummary instance or None if not available.
        """
        try:
            trd_ctx = self._get_trade_context(account_type)
            trd_env = TrdEnv.SIMULATE if account_type == AccountType.PAPER else TrdEnv.REAL

            # Get account info
            ret, data = trd_ctx.accinfo_query(trd_env=trd_env)

            if ret != RET_OK:
                logger.error(f"Get account info failed: {data}")
                return None

            if data.empty:
                logger.warning("No account info returned from Futu")
                return None

            row = data.iloc[0]

            # Extract values using safe_float to handle 'N/A' strings
            total_assets = self._safe_float(row.get("total_assets", 0))
            cash = self._safe_float(row.get("cash", 0))
            market_value = self._safe_float(row.get("market_val", 0))
            unrealized_pnl = self._safe_float(row.get("unrealized_pl", 0))
            margin_used = self._safe_float(row.get("maintenance_margin")) if row.get("maintenance_margin") not in (None, "N/A") else None
            margin_available = self._safe_float(row.get("avl_withdrawal_cash")) if row.get("avl_withdrawal_cash") not in (None, "N/A") else None
            buying_power = self._safe_float(row.get("max_power_short")) if row.get("max_power_short") not in (None, "N/A") else None

            # Get account ID
            account_id = str(row.get("acc_id", "unknown"))

            logger.info(f"Futu account summary: TotalAssets={total_assets}, Cash={cash}, "
                       f"MarketValue={market_value}, UnrealizedPnL={unrealized_pnl}")

            return AccountSummary(
                broker="futu",
                account_type=account_type,
                account_id=account_id,
                total_assets=total_assets,
                cash=cash,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                margin_used=margin_used,
                margin_available=margin_available,
                buying_power=buying_power,
                cash_by_currency=None,  # Futu returns aggregated values
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Error getting account summary: {e}")
            return None

    # Mapping from Futu option codes to standard HK stock codes (Yahoo format)
    # These are HKEX standardized option abbreviations
    # Add new mappings here when encountering unknown option codes
    # Format: "0700.HK" is compatible with both Yahoo and Futu (via normalize_symbol)
    FUTU_TO_STANDARD_CODE = {
        "ALB": "9988.HK",   # 阿里巴巴
        "TCH": "0700.HK",   # 腾讯
        "MIU": "1810.HK",   # 小米
        "BDU": "9888.HK",   # 百度
        "JDH": "9618.HK",   # 京东
        "NTE": "9999.HK",   # 网易
        "BLB": "9626.HK",   # 哔哩哔哩
        "HCH": "2318.HK",   # 中国平安
        "HSI": "^HSI",      # 恒生指数 (Yahoo format)
    }

    # HK option contract multiplier (shares per contract)
    # Most HK stocks: 100, some like ALB: 500
    HK_OPTION_MULTIPLIER = {
        "ALB": 500,   # 阿里巴巴 9988
        "TCH": 100,   # 腾讯 700
        "MIU": 500,   # 小米 1810
        "BDU": 100,   # 百度 9888
        "JDH": 100,   # 京东 9618
        "NTE": 100,   # 网易 9999
        "BLB": 100,   # 哔哩哔哩 9626
        "HCH": 500,   # 中国平安 2318
        "HSI": 50,    # 恒生指数
    }
    HK_OPTION_MULTIPLIER_DEFAULT = 100

    def _get_option_multiplier(self, futu_code: str) -> int:
        """Get contract multiplier for a Futu option code.

        Args:
            futu_code: Futu option abbreviation (e.g., "ALB", "TCH").

        Returns:
            Contract multiplier (shares per contract).
        """
        return self.HK_OPTION_MULTIPLIER.get(futu_code, self.HK_OPTION_MULTIPLIER_DEFAULT)

    def _get_underlying_code(self, futu_code: str) -> str:
        """Get standard HK stock code for a Futu option code.

        Args:
            futu_code: Short Futu code (e.g., "ALB").

        Returns:
            Standard HK stock code in Yahoo format (e.g., "9988.HK").
            This format is compatible with:
            - Yahoo Finance (direct use)
            - Futu (via normalize_symbol: "9988.HK" -> "HK.09988")
            - UnifiedProvider market detection
        """
        if futu_code in self.FUTU_TO_STANDARD_CODE:
            return self.FUTU_TO_STANDARD_CODE[futu_code]

        # Unknown code - log warning and return with .HK suffix
        logger.warning(
            f"Unknown Futu option code '{futu_code}'. "
            f"Please add mapping to FUTU_TO_STANDARD_CODE in FutuProvider."
        )
        # Return with .HK suffix so it's at least recognized as HK market
        return f"{futu_code}.HK"

    def _parse_futu_option_symbol(self, code: str, stock_name: str) -> dict | None:
        """Parse Futu option symbol to extract option details.

        Futu option format: HK.ALB260129C160000
        - ALB = underlying (阿里巴巴) -> mapped to standard code 9988.HK
        - 260129 = expiry date (YYMMDD)
        - C = Call, P = Put
        - 160000 = strike * 1000

        Args:
            code: Option symbol code (e.g., HK.ALB260129C160000).
            stock_name: Stock name that may contain option info (e.g., "阿里 260129 160.00 购").

        Returns:
            Dict with option details or None if not an option.
            The 'underlying' field is in Yahoo format (e.g., "9988.HK") for
            cross-provider compatibility.
        """
        import re

        # Remove market prefix
        symbol = code
        if "." in code:
            symbol = code.split(".", 1)[1]

        # Pattern: <underlying><YYMMDD><C/P><strike*1000>
        # Options have numeric date + C/P + numeric strike at the end
        option_pattern = r'^([A-Z]+)(\d{6})([CP])(\d+)$'
        match = re.match(option_pattern, symbol)

        if match:
            futu_code = match.group(1)
            expiry_str = match.group(2)  # YYMMDD
            option_type_char = match.group(3)
            strike_raw = match.group(4)

            # Get standard HK stock code from mapping (Yahoo format)
            standard_code = self._get_underlying_code(futu_code)

            # Parse expiry date - return in YYYYMMDD format
            try:
                expiry_date = datetime.strptime(f"20{expiry_str}", "%Y%m%d").strftime("%Y%m%d")
            except ValueError:
                expiry_date = f"20{expiry_str}"

            # Parse strike price (divide by 1000)
            try:
                strike = float(strike_raw) / 1000
            except ValueError:
                strike = 0.0

            return {
                "underlying": standard_code,  # Standard HK code in Yahoo format (e.g., "0700.HK")
                "expiry": expiry_date,
                "option_type": "call" if option_type_char == "C" else "put",
                "strike": strike,
                "multiplier": self._get_option_multiplier(futu_code),
            }

        # Also check stock_name for option indicators (购=call, 沽=put)
        if stock_name and ("购" in stock_name or "沽" in stock_name or "认购" in stock_name or "认沽" in stock_name):
            # Try to parse from stock_name: "阿里 260129 160.00 购"
            name_pattern = r'.*?(\d{6})\s+(\d+\.?\d*)\s*(购|沽|认购|认沽)'
            name_match = re.search(name_pattern, stock_name)
            if name_match:
                expiry_str = name_match.group(1)
                strike_str = name_match.group(2)
                type_str = name_match.group(3)

                # Parse expiry date - return in YYYYMMDD format for IBKR
                try:
                    expiry_date = datetime.strptime(f"20{expiry_str}", "%Y%m%d").strftime("%Y%m%d")
                except ValueError:
                    expiry_date = f"20{expiry_str}"

                try:
                    strike = float(strike_str)
                except ValueError:
                    strike = 0.0

                # Extract Futu code and get standard code from mapping
                futu_code = symbol[:3] if len(symbol) > 3 else symbol
                standard_code = self._get_underlying_code(futu_code)

                return {
                    "underlying": standard_code,  # Standard HK code in Yahoo format
                    "expiry": expiry_date,
                    "option_type": "call" if "购" in type_str else "put",
                    "strike": strike,
                    "multiplier": self._get_option_multiplier(futu_code),
                }

        return None

    def get_positions(
        self,
        account_type: AccountType = AccountType.PAPER,
        fetch_greeks: bool = True,
    ) -> list[AccountPosition]:
        """Get all positions in the account.

        Args:
            account_type: Real or paper account.
            fetch_greeks: Whether to fetch Greeks for option positions.
                Set to False when using a centralized Greeks fetcher (e.g., UnifiedProvider).

        Returns:
            List of AccountPosition instances.
        """
        try:
            trd_ctx = self._get_trade_context(account_type)
            trd_env = TrdEnv.SIMULATE if account_type == AccountType.PAPER else TrdEnv.REAL

            # Get positions
            ret, data = trd_ctx.position_list_query(trd_env=trd_env)

            if ret != RET_OK:
                logger.error(f"Get positions failed: {data}")
                return []

            if data.empty:
                logger.info("No positions found in Futu account")
                return []

            # Log available columns for debugging
            logger.debug(f"Position columns: {list(data.columns)}")

            results = []
            for _, row in data.iterrows():
                code = row.get("code", "")
                stock_name = row.get("stock_name", "")

                # Determine market and currency from code prefix or position_market
                position_market = row.get("position_market", "")
                currency = row.get("currency", "USD")

                market = Market.US
                if code.startswith("HK.") or position_market == "HK":
                    market = Market.HK
                    if not currency:
                        currency = "HKD"
                elif code.startswith("SH.") or code.startswith("SZ."):
                    market = Market.CN
                    if not currency:
                        currency = "CNY"

                # Check if this is an option by parsing the symbol
                option_info = self._parse_futu_option_symbol(code, stock_name)
                asset_type = AssetType.OPTION if option_info else AssetType.STOCK

                # Get average cost price
                # Futu API: cost_price = diluted cost (not what we want)
                #           average_cost = average cost price (correct field)
                # Always prefer average_cost; fall back to cost_price only if average_cost is unavailable
                avg_cost = self._safe_float(row.get("average_cost", 0))
                if avg_cost == 0:
                    avg_cost = self._safe_float(row.get("cost_price", 0))

                # Get unrealized P&L - Futu uses pl_val
                unrealized_pnl = self._safe_float(row.get("pl_val", 0))
                if unrealized_pnl == 0:
                    unrealized_pnl = self._safe_float(row.get("unrealized_pl", 0))

                # Get realized P&L
                realized_pnl = self._safe_float(row.get("realized_pl", 0))

                # For stocks, convert symbol to standard format for cross-provider compatibility
                # US.TSM -> TSM, HK.00700 -> 0700.HK
                # For options, keep original code as it's a contract identifier
                if option_info:
                    # Option: keep original Futu code (e.g., HK.TCH260129P600000)
                    position_symbol = code
                else:
                    # Stock: convert to standard format
                    position_symbol = SymbolFormatter.to_standard(code)

                # Create position
                position = AccountPosition(
                    symbol=position_symbol,
                    asset_type=asset_type,
                    market=market,
                    quantity=self._safe_float(row.get("qty", 0)),
                    avg_cost=avg_cost,
                    market_value=self._safe_float(row.get("market_val", 0)),
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=realized_pnl,
                    currency=currency,
                    broker="futu",
                    last_updated=datetime.now(),
                )

                # Add option-specific fields if applicable
                if option_info:
                    position.underlying = option_info["underlying"]  # IBKR-compatible code
                    position.strike = option_info["strike"]
                    position.expiry = option_info["expiry"]
                    position.option_type = option_info["option_type"]
                    position.contract_multiplier = option_info.get("multiplier", 100)
                else:
                    # Stock Greeks: delta = +1 (long) or -1 (short), others = 0
                    position.delta = 1.0 if position.quantity > 0 else -1.0 if position.quantity < 0 else 0.0
                    position.gamma = 0.0
                    position.theta = 0.0
                    position.vega = 0.0
                    position.iv = None
                    # For stocks, underlying_price = market_value / quantity
                    if position.quantity != 0:
                        position.underlying_price = abs(position.market_value / position.quantity)

                results.append(position)

            # Fetch Greeks for option positions (if enabled)
            if fetch_greeks:
                option_positions = [p for p in results if p.asset_type == AssetType.OPTION]
                if option_positions:
                    self._fetch_option_greeks(option_positions)

            logger.info(f"Found {len(results)} positions in Futu account")
            return results

        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def _fetch_option_greeks(self, positions: list[AccountPosition]) -> None:
        """Fetch Greeks for option positions using get_stock_quote.

        Uses get_stock_quote instead of get_market_snapshot as it's more reliable
        and returns option Greeks directly.

        Args:
            positions: List of option positions to update with Greeks.
        """
        if not positions:
            return

        symbols = [p.symbol for p in positions]
        logger.debug(f"Fetching Greeks for option symbols: {symbols}")

        # Try up to 3 times with increasing delay
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._check_rate_limit("quote")
                # Use get_stock_quote instead of get_market_snapshot
                ret, data = self._quote_ctx.get_stock_quote(symbols)

                if ret != RET_OK:
                    if "Timeout" in str(data) and attempt < max_retries - 1:
                        logger.warning(f"Timeout fetching option Greeks (attempt {attempt+1}/{max_retries}), retrying...")
                        import time
                        time.sleep(1)  # Wait before retry
                        continue
                    logger.warning(f"Failed to fetch option Greeks: {data}")
                    return

                if data.empty:
                    logger.warning(f"No quote data returned for options: {symbols}")
                    return

                # Log available columns for debugging
                logger.debug(f"Quote columns: {list(data.columns)}")

                # Build lookup by symbol
                greeks_lookup = {}
                for _, row in data.iterrows():
                    code = row["code"]
                    # get_stock_quote returns Greeks directly (not with option_ prefix)
                    delta = self._safe_float(row.get("delta"))
                    gamma = self._safe_float(row.get("gamma"))
                    theta = self._safe_float(row.get("theta"))
                    vega = self._safe_float(row.get("vega"))
                    iv = self._safe_float(row.get("implied_volatility"))
                    logger.debug(f"Option {code}: delta={delta}, gamma={gamma}, theta={theta}, vega={vega}, iv={iv}")
                    greeks_lookup[code] = {
                        "delta": delta,
                        "gamma": gamma,
                        "theta": theta,
                        "vega": vega,
                        "iv": iv,
                    }

                # Update positions with Greeks
                for pos in positions:
                    if pos.symbol in greeks_lookup:
                        g = greeks_lookup[pos.symbol]
                        # Don't filter out 0 values - they might be valid
                        pos.delta = g["delta"] if g["delta"] is not None else None
                        pos.gamma = g["gamma"] if g["gamma"] is not None else None
                        pos.theta = g["theta"] if g["theta"] is not None else None
                        pos.vega = g["vega"] if g["vega"] is not None else None
                        # IV is stored as percentage, convert to decimal
                        pos.iv = g["iv"] / 100.0 if g["iv"] else None
                        logger.debug(f"Updated {pos.symbol}: delta={pos.delta}, iv={pos.iv}")
                    else:
                        logger.warning(f"No Greeks found for {pos.symbol}")

                logger.info(f"Fetched Greeks for {len(positions)} option positions")
                return  # Success, exit retry loop

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Error fetching option Greeks (attempt {attempt+1}/{max_retries}): {e}")
                    import time
                    time.sleep(1)
                else:
                    logger.warning(f"Error fetching option Greeks after {max_retries} attempts: {e}")

    def get_cash_balances(
        self,
        account_type: AccountType = AccountType.PAPER,
    ) -> list[AccountCash]:
        """Get cash balances by currency.

        Note: Futu API returns aggregated cash, not by currency.
        This method returns a single cash entry with the account's cash balance.

        Args:
            account_type: Real or paper account.

        Returns:
            List of AccountCash instances.
        """
        try:
            trd_ctx = self._get_trade_context(account_type)
            trd_env = TrdEnv.SIMULATE if account_type == AccountType.PAPER else TrdEnv.REAL

            # Get account info
            ret, data = trd_ctx.accinfo_query(trd_env=trd_env)

            if ret != RET_OK:
                logger.error(f"Get account info failed: {data}")
                return []

            if data.empty:
                return []

            row = data.iloc[0]
            cash = float(row.get("cash", 0))
            available = float(row.get("avl_withdrawal_cash", 0))

            # Futu returns aggregated values, assume HKD for HK accounts
            # This is a simplification - actual currency depends on account type
            currency = "HKD"

            results = [
                AccountCash(
                    currency=currency,
                    balance=cash,
                    available=available,
                    broker="futu",
                )
            ]

            logger.info(f"Found cash balance: {cash} {currency}")
            return results

        except Exception as e:
            logger.error(f"Error getting cash balances: {e}")
            return []
