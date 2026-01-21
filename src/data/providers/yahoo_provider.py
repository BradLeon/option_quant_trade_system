"""Yahoo Finance data provider implementation."""

import logging
import time
from datetime import date, datetime
from typing import Any

import yfinance as yf

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
from src.data.providers.base import DataNotFoundError, DataProvider, RateLimitError

logger = logging.getLogger(__name__)

# Mapping from our KlineType to yfinance interval
KLINE_INTERVAL_MAP = {
    KlineType.DAY: "1d",
    KlineType.WEEK: "1wk",
    KlineType.MONTH: "1mo",
    KlineType.MIN_1: "1m",
    KlineType.MIN_5: "5m",
    KlineType.MIN_15: "15m",
    KlineType.MIN_30: "30m",
    KlineType.MIN_60: "60m",
}


class YahooProvider(DataProvider):
    """Yahoo Finance data provider.

    Provides market data through yfinance library.
    No authentication required, but has rate limits.
    """

    # 宏观数据缓存 (类级别共享，所有实例共用)
    # key: "indicator_startdate_enddate", value: (timestamp, data)
    _macro_cache: dict[str, tuple[float, list[MacroData]]] = {}
    _MACRO_CACHE_TTL = 1800  # 30 分钟

    # PCR 数据缓存 (类级别共享)
    # key: "symbol", value: (timestamp, pcr_value)
    _pcr_cache: dict[str, tuple[float, float]] = {}
    _PCR_CACHE_TTL = 1800  # 30 分钟 (PCR 数据不需要频繁更新)

    def __init__(self, rate_limit: float = 1.0) -> None:
        """Initialize Yahoo Finance provider.

        Args:
            rate_limit: 请求间隔（秒）
                - 默认 1.0s: 基于社区成功案例 (GitHub #2125, 320+ tickers)
                - Yahoo 2024年11月加强限制后的安全值
                - 推荐范围: 1.0-2.0s
        """
        self._rate_limit = rate_limit
        self._last_request_time = 0.0

    @property
    def name(self) -> str:
        """Provider name."""
        return "yahoo"

    @property
    def is_available(self) -> bool:
        """Yahoo Finance is always available (no connection required)."""
        return True

    def _check_rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        current_time = time.time()
        elapsed = current_time - self._last_request_time

        if elapsed < self._rate_limit:
            sleep_time = self._rate_limit - elapsed
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    def _retry_with_backoff(
        self,
        func: callable,
        *args,
        max_retries: int = 3,
        **kwargs
    ) -> Any:
        """429 错误时使用指数退避重试

        Args:
            func: 要调用的函数
            max_retries: 最大重试次数（默认 3）
            *args, **kwargs: 传递给函数的参数

        Returns:
            函数返回值

        Raises:
            RateLimitError: 超过最大重试次数
            Exception: 其他错误直接抛出
        """
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = str(e)
                # 检查是否为速率限制错误
                is_rate_limit = any(
                    keyword in error_msg
                    for keyword in ["Too Many Requests", "429", "Rate limit", "rate limit"]
                )

                if is_rate_limit and attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 2s, 4s, 8s
                    logger.warning(
                        f"Rate limited, retry {attempt + 1}/{max_retries} "
                        f"after {wait_time}s: {error_msg}"
                    )
                    time.sleep(wait_time)
                else:
                    # 最后一次重试失败或非速率限制错误
                    if is_rate_limit:
                        raise RateLimitError(
                            f"Exceeded max retries ({max_retries}) due to rate limiting: {error_msg}"
                        )
                    else:
                        # 非速率限制错误，直接抛出
                        raise

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol for Yahoo Finance.

        Removes market prefix if present (e.g., US.AAPL -> AAPL).

        Args:
            symbol: Stock symbol.

        Returns:
            Symbol in Yahoo format.
        """
        symbol = symbol.upper()
        # Remove market prefix (e.g., US.AAPL -> AAPL)
        if "." in symbol:
            parts = symbol.split(".")
            if parts[0] in ("US", "HK", "SH", "SZ"):
                symbol = parts[1]
                # Add suffix for non-US markets
                if parts[0] == "HK":
                    symbol = f"{symbol}.HK"
                elif parts[0] in ("SH", "SZ"):
                    symbol = f"{symbol}.{'SS' if parts[0] == 'SH' else 'SZ'}"
        return symbol

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """Get real-time stock quote."""
        self._check_rate_limit()
        symbol = self.normalize_symbol(symbol)

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            if not info or "regularMarketPrice" not in info:
                logger.warning(f"No quote data available for {symbol}")
                return None

            return StockQuote(
                symbol=symbol,
                timestamp=datetime.now(),
                open=info.get("regularMarketOpen"),
                high=info.get("regularMarketDayHigh"),
                low=info.get("regularMarketDayLow"),
                close=info.get("regularMarketPrice"),
                volume=info.get("regularMarketVolume"),
                prev_close=info.get("regularMarketPreviousClose"),
                change=info.get("regularMarketChange"),
                change_percent=info.get("regularMarketChangePercent"),
                source=self.name,
            )

        except Exception as e:
            logger.error(f"Error getting stock quote for {symbol}: {e}")
            return None

    def get_stock_quotes(self, symbols: list[str]) -> list[StockQuote]:
        """Get real-time quotes for multiple stocks."""
        results = []
        for symbol in symbols:
            quote = self.get_stock_quote(symbol)
            if quote:
                results.append(quote)
        return results

    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """Get historical K-line data with retry on rate limit."""
        self._check_rate_limit()
        symbol = self.normalize_symbol(symbol)

        return self._retry_with_backoff(
            self._get_history_kline_impl, symbol, ktype, start_date, end_date
        )

    def _get_history_kline_impl(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """实际的获取 K 线数据逻辑"""
        interval = KLINE_INTERVAL_MAP.get(ktype, "1d")

        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval=interval,
            )

            if hist.empty:
                logger.warning(f"No history data for {symbol}")
                return []

            results = []
            for timestamp, row in hist.iterrows():
                bar = KlineBar(
                    symbol=symbol,
                    timestamp=timestamp.to_pydatetime(),
                    ktype=ktype,
                    open=row["Open"],
                    high=row["High"],
                    low=row["Low"],
                    close=row["Close"],
                    volume=int(row["Volume"]),
                    source=self.name,
                )
                results.append(bar)

            return results

        except Exception as e:
            logger.error(f"Error getting history kline for {symbol}: {e}")
            # Re-raise for retry logic to handle
            raise

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
    ) -> OptionChain | None:
        """Get option chain for an underlying asset."""
        self._check_rate_limit()
        underlying = self.normalize_symbol(underlying)

        try:
            ticker = yf.Ticker(underlying)
            expiry_dates = ticker.options

            if not expiry_dates:
                logger.warning(f"No options available for {underlying}")
                return None

            # Filter expiry dates if specified
            filtered_expiries = []
            for exp_str in expiry_dates:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                if expiry_start and exp_date < expiry_start:
                    continue
                if expiry_end and exp_date > expiry_end:
                    continue
                filtered_expiries.append(exp_date)

            if not filtered_expiries:
                logger.warning(f"No options in date range for {underlying}")
                return None

            calls = []
            puts = []

            for exp_date in filtered_expiries:
                self._check_rate_limit()
                exp_str = exp_date.strftime("%Y-%m-%d")

                try:
                    opt = ticker.option_chain(exp_str)

                    # Process calls
                    for _, row in opt.calls.iterrows():
                        contract = OptionContract(
                            symbol=row["contractSymbol"],
                            underlying=underlying,
                            option_type=OptionType.CALL,
                            strike_price=row["strike"],
                            expiry_date=exp_date,
                        )

                        greeks = Greeks(
                            delta=None,  # Yahoo doesn't provide Greeks
                            gamma=None,
                            theta=None,
                            vega=None,
                        )

                        quote = OptionQuote(
                            contract=contract,
                            timestamp=datetime.now(),
                            last_price=row.get("lastPrice"),
                            bid=row.get("bid"),
                            ask=row.get("ask"),
                            volume=row.get("volume"),
                            open_interest=row.get("openInterest"),
                            iv=row.get("impliedVolatility"),
                            greeks=greeks,
                            source=self.name,
                        )
                        calls.append(quote)

                    # Process puts
                    for _, row in opt.puts.iterrows():
                        contract = OptionContract(
                            symbol=row["contractSymbol"],
                            underlying=underlying,
                            option_type=OptionType.PUT,
                            strike_price=row["strike"],
                            expiry_date=exp_date,
                        )

                        greeks = Greeks(
                            delta=None,
                            gamma=None,
                            theta=None,
                            vega=None,
                        )

                        quote = OptionQuote(
                            contract=contract,
                            timestamp=datetime.now(),
                            last_price=row.get("lastPrice"),
                            bid=row.get("bid"),
                            ask=row.get("ask"),
                            volume=row.get("volume"),
                            open_interest=row.get("openInterest"),
                            iv=row.get("impliedVolatility"),
                            greeks=greeks,
                            source=self.name,
                        )
                        puts.append(quote)

                except Exception as e:
                    logger.warning(f"Error getting options for {exp_str}: {e}")
                    continue

            return OptionChain(
                underlying=underlying,
                timestamp=datetime.now(),
                expiry_dates=filtered_expiries,
                calls=calls,
                puts=puts,
                source=self.name,
            )

        except Exception as e:
            logger.error(f"Error getting option chain for {underlying}: {e}")
            return None

    def get_option_quote(self, symbol: str) -> OptionQuote | None:
        """Get quote for a specific option contract.

        Note: Yahoo Finance doesn't support direct option quote by symbol.
        Use get_option_chain and filter instead.
        """
        logger.warning(
            "Yahoo Finance doesn't support direct option quote. "
            "Use get_option_chain and filter."
        )
        return None

    def get_fundamental(self, symbol: str) -> Fundamental | None:
        """Get fundamental data for a stock with retry."""
        self._check_rate_limit()
        symbol = self.normalize_symbol(symbol)

        return self._retry_with_backoff(self._get_fundamental_impl, symbol)

    def _get_fundamental_impl(self, symbol: str) -> Fundamental | None:
        """实际的获取基本面数据逻辑"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            if not info:
                logger.warning(f"No fundamental data for {symbol}")
                return None

            # Extract earnings date from various possible fields
            earnings_date = self._extract_earnings_date(info)

            # Extract ex-dividend date
            ex_dividend_date = self._extract_ex_dividend_date(info)

            return Fundamental(
                symbol=symbol,
                date=date.today(),
                market_cap=info.get("marketCap"),
                pe_ratio=info.get("trailingPE"),
                pb_ratio=info.get("priceToBook"),
                ps_ratio=info.get("priceToSalesTrailing12Months"),
                dividend_yield=info.get("dividendYield"),
                eps=info.get("trailingEps"),
                revenue=info.get("totalRevenue"),
                profit=info.get("netIncomeToCommon"),
                gross_margin=info.get("grossMargins"),
                operating_margin=info.get("operatingMargins"),
                profit_margin=info.get("profitMargins"),
                debt_to_equity=info.get("debtToEquity"),
                current_ratio=info.get("currentRatio"),
                quick_ratio=info.get("quickRatio"),
                roe=info.get("returnOnEquity"),
                roa=info.get("returnOnAssets"),
                beta=info.get("beta"),
                fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
                fifty_two_week_low=info.get("fiftyTwoWeekLow"),
                avg_volume=info.get("averageVolume"),
                shares_outstanding=info.get("sharesOutstanding"),
                # Growth metrics
                revenue_growth=info.get("revenueGrowth"),
                earnings_growth=info.get("earningsGrowth"),
                # Analyst ratings
                recommendation=info.get("recommendationKey"),
                recommendation_mean=info.get("recommendationMean"),
                analyst_count=info.get("numberOfAnalystOpinions"),
                target_price=info.get("targetMeanPrice"),
                source=self.name,
                # Event calendar dates
                earnings_date=earnings_date,
                ex_dividend_date=ex_dividend_date,
            )

        except Exception as e:
            logger.error(f"Error getting fundamental for {symbol}: {e}")
            return None

    def _extract_earnings_date(self, info: dict[str, Any]) -> date | None:
        """Extract earnings date from yfinance info dict.

        Tries multiple possible fields:
        - earningsTimestamp (Unix timestamp)
        - earningsTimestampStart (Unix timestamp)
        - earningsDate (may be list or date)

        Args:
            info: yfinance ticker.info dictionary

        Returns:
            Next earnings date or None
        """
        # Try earningsTimestamp first (Unix timestamp)
        timestamp = info.get("earningsTimestamp")
        if timestamp:
            try:
                return datetime.fromtimestamp(timestamp).date()
            except (ValueError, OSError, TypeError):
                pass

        # Try earningsTimestampStart (Unix timestamp)
        timestamp = info.get("earningsTimestampStart")
        if timestamp:
            try:
                return datetime.fromtimestamp(timestamp).date()
            except (ValueError, OSError, TypeError):
                pass

        # Try earningsDate (may be a list of timestamps)
        earnings_list = info.get("earningsDate")
        if earnings_list and isinstance(earnings_list, list) and len(earnings_list) > 0:
            try:
                return datetime.fromtimestamp(earnings_list[0]).date()
            except (ValueError, OSError, TypeError):
                pass

        return None

    def _extract_ex_dividend_date(self, info: dict[str, Any]) -> date | None:
        """Extract ex-dividend date from yfinance info dict.

        Tries multiple possible fields:
        - exDividendDate (Unix timestamp)
        - dividendDate (Unix timestamp)

        Args:
            info: yfinance ticker.info dictionary

        Returns:
            Ex-dividend date or None
        """
        # Try exDividendDate first (Unix timestamp)
        timestamp = info.get("exDividendDate")
        if timestamp:
            try:
                return datetime.fromtimestamp(timestamp).date()
            except (ValueError, OSError, TypeError):
                pass

        # Try dividendDate as fallback
        timestamp = info.get("dividendDate")
        if timestamp:
            try:
                return datetime.fromtimestamp(timestamp).date()
            except (ValueError, OSError, TypeError):
                pass

        return None

    def get_macro_data(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroData]:
        """Get macro economic data with caching and retry.

        Supports indices like ^VIX, ^GSPC, ^TNX, etc.
        Uses 5-minute cache to reduce API calls for repeated queries.
        """
        self._check_rate_limit()

        # 检查缓存
        cache_key = f"{indicator}_{start_date}_{end_date}"
        now = time.time()

        if cache_key in self._macro_cache:
            cached_time, cached_data = self._macro_cache[cache_key]
            if now - cached_time < self._MACRO_CACHE_TTL:
                logger.debug(f"Macro cache HIT: {cache_key}")
                return cached_data

        # 缓存未命中，获取数据（使用重试）
        logger.debug(f"Macro cache MISS: {cache_key}")
        data = self._retry_with_backoff(
            self._get_macro_data_impl,
            indicator,
            start_date,
            end_date
        )

        # 存入缓存
        if data:
            self._macro_cache[cache_key] = (now, data)

        return data

    def _get_macro_data_impl(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroData]:
        """实际的获取宏观数据逻辑"""
        try:
            ticker = yf.Ticker(indicator)
            hist = ticker.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d",
            )

            if hist.empty:
                logger.warning(f"No macro data for {indicator}")
                return []

            results = []
            for timestamp, row in hist.iterrows():
                data = MacroData.from_kline(
                    indicator=indicator,
                    data_date=timestamp.date(),
                    open_=row["Open"],
                    high=row["High"],
                    low=row["Low"],
                    close=row["Close"],
                    volume=int(row["Volume"]) if row["Volume"] else None,
                    source=self.name,
                )
                results.append(data)

            return results

        except Exception as e:
            logger.error(f"Error getting macro data for {indicator}: {e}")
            return []

    def get_put_call_ratio(self, symbol: str = "SPY") -> float | None:
        """Calculate Put/Call Ratio from option chain volume with caching and retry.

        CBOE Put/Call Ratio is not directly available via yfinance.
        This method calculates PCR from option chain data for a given symbol.

        Args:
            symbol: Symbol to calculate PCR for (default: SPY for market-wide sentiment).

        Returns:
            Put/Call Ratio (put_volume / call_volume), or None if unavailable.
            - PCR < 0.7: Bullish sentiment
            - PCR 0.7-1.0: Neutral
            - PCR > 1.0: Bearish sentiment
        """
        self._check_rate_limit()
        symbol = self.normalize_symbol(symbol)

        # 检查缓存
        now = time.time()
        if symbol in self._pcr_cache:
            cached_time, cached_pcr = self._pcr_cache[symbol]
            if now - cached_time < self._PCR_CACHE_TTL:
                logger.debug(f"PCR cache HIT: {symbol}")
                return cached_pcr

        # 缓存未命中，获取数据（使用重试）
        logger.debug(f"PCR cache MISS: {symbol}")
        pcr = self._retry_with_backoff(self._get_put_call_ratio_impl, symbol)

        # 存入缓存
        if pcr is not None:
            self._pcr_cache[symbol] = (now, pcr)

        return pcr

    def _get_put_call_ratio_impl(self, symbol: str) -> float | None:
        """实际的 PCR 计算逻辑"""
        try:
            ticker = yf.Ticker(symbol)
            expiry_dates = ticker.options

            if not expiry_dates:
                logger.warning(f"No options available for {symbol}")
                return None

            # Use the nearest expiry date for most relevant sentiment
            exp_date = expiry_dates[0]
            chain = ticker.option_chain(exp_date)

            # Sum up volumes (handle NaN values)
            call_volume = chain.calls["volume"].fillna(0).sum()
            put_volume = chain.puts["volume"].fillna(0).sum()

            if call_volume > 0:
                pcr = put_volume / call_volume
                logger.debug(
                    f"PCR for {symbol} (exp={exp_date}): "
                    f"put_vol={put_volume:.0f}, call_vol={call_volume:.0f}, pcr={pcr:.3f}"
                )
                return pcr
            else:
                logger.warning(f"No call volume for {symbol}, cannot calculate PCR")
                return None

        except Exception as e:
            logger.error(f"Error calculating put/call ratio for {symbol}: {e}")
            # Re-raise for retry logic to handle
            raise
