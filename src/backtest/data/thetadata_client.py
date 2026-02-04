"""
ThetaData REST API Client

封装 ThetaData v3 REST API，支持股票和期权历史数据获取。

ThetaData 需要本地运行 Terminal 客户端，API 通过 localhost:25503 访问。

Usage:
    client = ThetaDataClient()

    # 获取股票 EOD 数据
    stock_data = client.get_stock_eod("AAPL", date(2024, 1, 1), date(2024, 1, 31))

    # 获取期权到期日列表
    expirations = client.get_option_expirations("AAPL")

    # 获取期权 EOD 数据 (含 Greeks)
    option_data = client.get_option_eod_greeks("AAPL", date(2024, 1, 15), date(2024, 1, 15))

Rate Limits:
    - Free: 20 requests/minute
    - Pro: Unlimited
"""

import csv
import io
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

import httpx
import requests

logger = logging.getLogger(__name__)


@dataclass
class ThetaDataConfig:
    """ThetaData 客户端配置"""

    # Terminal 地址
    host: str = "127.0.0.1"
    port: int = 25503

    # 订阅层级: "free" 或 "pro"
    subscription_tier: Literal["free", "pro"] = "free"

    # Rate limit (Free tier: 20 req/min, 保守设为 10)
    rate_limit_requests: int = 10
    rate_limit_period: int = 60  # seconds

    # 请求间隔 (Free tier: 6s, Pro: 0s)
    min_request_interval: float = 6.0

    # FREE tier 跳过 Greeks API（避免无效请求浪费配额）
    skip_greeks_api: bool = True

    # 请求超时
    timeout: int = 30

    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self) -> None:
        """根据订阅层级调整配置"""
        if self.subscription_tier == "pro":
            self.rate_limit_requests = 1000  # 实际无限制
            self.min_request_interval = 0.0
            self.skip_greeks_api = False  # Pro 可以使用 Greeks API

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v3"


@dataclass
class StockEOD:
    """股票 EOD 数据"""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    count: int  # trade count
    bid: float | None = None
    ask: float | None = None


@dataclass
class OptionEOD:
    """期权 EOD 数据"""

    symbol: str
    expiration: date
    strike: float
    option_type: Literal["call", "put"]  # Call 或 Put
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    count: int
    bid: float
    ask: float
    open_interest: int | None = None


@dataclass
class OptionEODGreeks:
    """期权 EOD 数据 (含 Greeks)"""

    # 合约信息
    symbol: str
    expiration: date
    strike: float
    option_type: Literal["call", "put"]  # Call 或 Put
    date: date

    # OHLCV
    open: float
    high: float
    low: float
    close: float
    volume: int
    count: int
    bid: float
    ask: float

    # Greeks
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    implied_vol: float

    # 标的价格
    underlying_price: float

    # 可选字段
    open_interest: int | None = None
    iv_error: float | None = None


class ThetaDataError(Exception):
    """ThetaData API 错误"""

    pass


class RateLimitError(ThetaDataError):
    """Rate limit 错误"""

    pass


class ThetaDataClient:
    """ThetaData REST API 客户端

    封装 ThetaData v3 REST API，提供股票/期权历史数据查询。

    Usage:
        client = ThetaDataClient()

        # 股票 EOD
        stocks = client.get_stock_eod("AAPL", date(2024, 1, 1), date(2024, 12, 31))

        # 期权链 EOD (含 Greeks)
        options = client.get_option_eod_greeks("AAPL", date(2024, 1, 15), date(2024, 1, 15))
    """

    def __init__(self, config: ThetaDataConfig | None = None) -> None:
        """初始化客户端

        Args:
            config: 客户端配置
        """
        self._config = config or ThetaDataConfig()
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

        # Rate limiting (sliding window)
        self._request_timestamps: list[float] = []

        # Stock data cache (避免重复请求)
        self._stock_cache: dict[tuple, dict[date, float]] = {}

    def _check_rate_limit(self) -> None:
        """检查并等待 rate limit

        使用滑动窗口算法，确保在 rate_limit_period 秒内不超过 rate_limit_requests 次请求。
        同时强制执行最小请求间隔（FREE tier: 4s）。
        """
        now = time.time()

        # 1. 强制最小请求间隔
        if self._request_timestamps and self._config.min_request_interval > 0:
            last_request = self._request_timestamps[-1]
            elapsed = now - last_request
            if elapsed < self._config.min_request_interval:
                wait_time = self._config.min_request_interval - elapsed
                logger.debug(f"Enforcing min interval, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
                now = time.time()

        # 2. 滑动窗口 rate limit
        window_start = now - self._config.rate_limit_period

        # 清除过期的时间戳
        self._request_timestamps = [
            ts for ts in self._request_timestamps if ts > window_start
        ]

        # 如果达到限制，等待最早的请求过期
        if len(self._request_timestamps) >= self._config.rate_limit_requests:
            oldest = self._request_timestamps[0]
            wait_time = oldest + self._config.rate_limit_period - now
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
                # 清除过期的时间戳
                now = time.time()
                window_start = now - self._config.rate_limit_period
                self._request_timestamps = [
                    ts for ts in self._request_timestamps if ts > window_start
                ]

        # 记录本次请求时间
        self._request_timestamps.append(time.time())

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """发送 API 请求

        Args:
            endpoint: API 端点 (e.g., "/stock/history/eod")
            params: 请求参数

        Returns:
            响应数据列表

        Raises:
            ThetaDataError: API 错误
        """
        self._check_rate_limit()

        url = f"{self._config.base_url}{endpoint}"
        params = params or {}
        # ThetaData 默认返回 CSV，需要指定 JSON 格式
        params["format"] = "json"

        logger.debug(f"Request: {endpoint} params={params}")

        for attempt in range(self._config.max_retries):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._config.timeout,
                )

                # HTTP 429: Standard rate limit exceeded
                if response.status_code == 429:
                    wait_time = self._config.retry_delay * (attempt + 1)
                    logger.warning(f"Rate limit exceeded (429), waiting {wait_time}s")
                    time.sleep(wait_time)
                    continue

                # HTTP 472: ThetaData "No data found" (不是 rate limit!)
                if response.status_code == 472:
                    # 尝试解析响应体获取更多信息
                    try:
                        error_body = response.text[:200]
                    except Exception:
                        error_body = "N/A"
                    logger.debug(f"ThetaData 472: No data found. Response: {error_body}")
                    # 返回空列表而不是重试
                    return []

                response.raise_for_status()

                data = response.json()

                # ThetaData 返回格式: {"response": [...]}
                if isinstance(data, dict) and "response" in data:
                    return data["response"]
                elif isinstance(data, list):
                    return data
                else:
                    return [data] if data else []

            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout, attempt {attempt + 1}")
                if attempt < self._config.max_retries - 1:
                    time.sleep(self._config.retry_delay)
                    continue
                raise ThetaDataError(f"Request timeout after {self._config.max_retries} attempts")

            except requests.exceptions.ConnectionError as e:
                raise ThetaDataError(
                    f"Connection error: {e}. "
                    f"Is ThetaData Terminal running on {self._config.host}:{self._config.port}?"
                )

            except requests.exceptions.HTTPError as e:
                raise ThetaDataError(f"HTTP error: {e}")

        raise ThetaDataError("Max retries exceeded")

    def _request_csv_stream(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """使用 CSV 流式读取发送 API 请求

        适用于大数据量请求，避免 JSON 解析内存问题。

        Args:
            endpoint: API 端点 (e.g., "/option/history/eod")
            params: 请求参数

        Returns:
            响应数据列表 (字典形式)

        Raises:
            ThetaDataError: API 错误
        """
        self._check_rate_limit()

        url = f"{self._config.base_url}{endpoint}"
        params = params or {}
        params["format"] = "csv"

        logger.debug(f"CSV Stream Request: {endpoint} params={params}")

        for attempt in range(self._config.max_retries):
            try:
                results: list[dict[str, Any]] = []
                headers: list[str] | None = None

                with httpx.stream(
                    "GET",
                    url,
                    params=params,
                    timeout=httpx.Timeout(self._config.timeout, read=120.0),
                ) as response:
                    # HTTP 429: Rate limit
                    if response.status_code == 429:
                        wait_time = self._config.retry_delay * (attempt + 1)
                        logger.warning(f"Rate limit exceeded (429), waiting {wait_time}s")
                        time.sleep(wait_time)
                        continue

                    # HTTP 472: No data found
                    if response.status_code == 472:
                        logger.debug("ThetaData 472: No data found (CSV)")
                        return []

                    response.raise_for_status()

                    # 流式读取 CSV
                    for line in response.iter_lines():
                        if not line:
                            continue

                        # 解析 CSV 行
                        reader = csv.reader(io.StringIO(line))
                        for row in reader:
                            if not row:
                                continue

                            # 第一行是 header
                            if headers is None:
                                headers = [h.strip().lower() for h in row]
                                logger.debug(f"CSV headers: {headers}")
                                continue

                            # 数据行
                            if len(row) == len(headers):
                                record = dict(zip(headers, row))
                                results.append(record)

                logger.debug(f"CSV stream received {len(results)} records")
                return results

            except httpx.TimeoutException:
                logger.warning(f"CSV request timeout, attempt {attempt + 1}")
                if attempt < self._config.max_retries - 1:
                    time.sleep(self._config.retry_delay)
                    continue
                raise ThetaDataError(f"CSV request timeout after {self._config.max_retries} attempts")

            except httpx.ConnectError as e:
                raise ThetaDataError(
                    f"Connection error: {e}. "
                    f"Is ThetaData Terminal running on {self._config.host}:{self._config.port}?"
                )

            except httpx.HTTPStatusError as e:
                raise ThetaDataError(f"HTTP error: {e}")

        raise ThetaDataError("Max retries exceeded (CSV)")

    @staticmethod
    def _format_date(d: date) -> str:
        """格式化日期为 YYYYMMDD"""
        return d.strftime("%Y%m%d")

    @staticmethod
    def _parse_date(s: str) -> date:
        """解析日期字符串 (YYYY-MM-DD 或 YYYYMMDD)"""
        if "-" in s:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        return datetime.strptime(s[:8], "%Y%m%d").date()

    # ========== Stock API ==========

    def get_stock_symbols(self) -> list[str]:
        """获取所有股票代码列表

        Returns:
            股票代码列表
        """
        data = self._request("/stock/list/symbols")
        return [item["symbol"] for item in data if "symbol" in item]

    def get_stock_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StockEOD]:
        """获取股票 EOD 数据

        Args:
            symbol: 股票代码 (e.g., "AAPL")
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            StockEOD 列表
        """
        params = {
            "symbol": symbol.upper(),
            "start_date": self._format_date(start_date),
            "end_date": self._format_date(end_date),
        }

        data = self._request("/stock/history/eod", params)
        results = []

        for item in data:
            try:
                # 解析日期 (从 created 或 timestamp 字段)
                date_str = item.get("created") or item.get("timestamp") or item.get("date")
                if not date_str:
                    continue

                eod = StockEOD(
                    symbol=item.get("symbol", symbol),
                    date=self._parse_date(date_str),
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close", 0)),
                    volume=int(item.get("volume", 0)),
                    count=int(item.get("count", 0)),
                    bid=float(item["bid"]) if item.get("bid") else None,
                    ask=float(item["ask"]) if item.get("ask") else None,
                )
                results.append(eod)
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse stock EOD: {e}, data={item}")
                continue

        return results

    # ========== Option API ==========

    def get_option_expirations(
        self,
        symbol: str,
    ) -> list[date]:
        """获取期权到期日列表

        Args:
            symbol: 标的代码 (e.g., "AAPL")

        Returns:
            到期日列表
        """
        params = {"symbol": symbol.upper()}
        data = self._request("/option/list/expirations", params)

        results = []
        for item in data:
            exp_str = item.get("expiration") or item.get("date")
            if exp_str:
                try:
                    results.append(self._parse_date(exp_str))
                except ValueError:
                    continue

        return sorted(results)

    def get_option_strikes(
        self,
        symbol: str,
        expiration: date,
    ) -> list[float]:
        """获取期权行权价列表

        Args:
            symbol: 标的代码
            expiration: 到期日

        Returns:
            行权价列表
        """
        params = {
            "symbol": symbol.upper(),
            "expiration": self._format_date(expiration),
        }
        data = self._request("/option/list/strikes", params)

        results = []
        for item in data:
            strike = item.get("strike")
            if strike is not None:
                results.append(float(strike))

        return sorted(results)

    def get_option_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        expiration: date | None = None,
        strike: float | None = None,
        right: Literal["call", "put"] | None = None,
        max_dte: int | None = None,
        strike_range: int | None = None,
        use_csv: bool = True,
    ) -> list[OptionEOD]:
        """获取期权 EOD 数据

        Args:
            symbol: 标的代码
            start_date: 开始日期
            end_date: 结束日期
            expiration: 到期日 (可选，None 表示所有到期日)
            strike: 行权价 (可选)
            right: call 或 put (可选)
            max_dte: 最大 DTE 过滤 (可选)
            strike_range: 返回 ATM 上下各 N 个 strikes (可选，建议 50)
            use_csv: 使用 CSV 流式读取 (默认 True，大数据量推荐)

        Returns:
            OptionEOD 列表
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "start_date": self._format_date(start_date),
            "end_date": self._format_date(end_date),
        }

        if expiration:
            params["expiration"] = self._format_date(expiration)
        else:
            params["expiration"] = "*"  # 所有到期日

        if strike is not None:
            params["strike"] = f"{strike:.3f}"

        if right:
            params["right"] = right.lower()

        if max_dte is not None:
            params["max_dte"] = max_dte

        if strike_range is not None:
            params["strike_range"] = strike_range

        # 使用 CSV 流式读取 (大数据量)
        if use_csv:
            return self._parse_option_eod_csv(symbol, params)

        # JSON 格式 (小数据量)
        data = self._request("/option/history/eod", params)
        return self._parse_option_eod_json(symbol, data)

    def _parse_option_eod_csv(
        self,
        symbol: str,
        params: dict[str, Any],
    ) -> list[OptionEOD]:
        """从 CSV 流解析期权 EOD 数据

        ThetaData CSV 格式示例:
        symbol,expiration,strike,right,created,open,high,low,close,volume,count,bid,ask
        "SPY","2026-02-03",693.000,"CALL",2026-01-30T17:18:32.295,3.47,4.16,1.46,2.59,14339,1871,2.58,2.59
        """
        data = self._request_csv_stream("/option/history/eod", params)
        results = []

        for item in data:
            try:
                # created 字段包含 ISO 格式的日期时间 (YYYY-MM-DDTHH:MM:SS)
                created_str = item.get("created", "")
                if not created_str:
                    continue

                # 解析 created 日期 (取 YYYY-MM-DD 部分)
                if "T" in created_str:
                    date_part = created_str.split("T")[0]
                else:
                    date_part = created_str[:10]
                parsed_date = self._parse_date(date_part)

                # expiration 格式: YYYY-MM-DD
                exp_str = item.get("expiration", "")
                if not exp_str:
                    continue
                parsed_exp = self._parse_date(exp_str)

                # right 格式: "CALL" 或 "PUT"
                right_val = item.get("right", "").upper()
                if right_val not in ("CALL", "PUT"):
                    continue

                # strike 是十进制格式 (693.000)
                strike_val = float(item.get("strike", 0))

                # 价格字段是十进制格式 (3.47)
                eod = OptionEOD(
                    symbol=item.get("symbol", symbol).strip('"').upper(),
                    expiration=parsed_exp,
                    strike=strike_val,
                    option_type="call" if right_val == "CALL" else "put",
                    date=parsed_date,
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close", 0)),
                    volume=int(item.get("volume", 0)),
                    count=int(item.get("count", 0)),
                    bid=float(item.get("bid", 0)),
                    ask=float(item.get("ask", 0)),
                )
                results.append(eod)
            except (KeyError, ValueError) as e:
                logger.debug(f"Failed to parse CSV option EOD: {e}, data={item}")
                continue

        logger.debug(f"Parsed {len(results)} option EOD records from CSV")
        return results

    def _parse_option_eod_json(
        self,
        symbol: str,
        data: list[dict[str, Any]],
    ) -> list[OptionEOD]:
        """从 JSON 解析期权 EOD 数据"""
        results = []

        for item in data:
            try:
                # ThetaData v3 返回嵌套结构: {"contract": {...}, "data": [...]}
                contract = item.get("contract", {})
                data_list = item.get("data", [])

                if not contract or not data_list:
                    # 尝试旧格式 (扁平结构)
                    date_str = item.get("created") or item.get("timestamp")
                    if not date_str:
                        continue

                    exp_str = item.get("expiration")
                    if not exp_str:
                        continue

                    right_val = item.get("right", "").upper()
                    if right_val not in ("CALL", "PUT"):
                        continue

                    eod = OptionEOD(
                        symbol=item.get("symbol", symbol),
                        expiration=self._parse_date(exp_str),
                        strike=float(item.get("strike", 0)),
                        option_type="call" if right_val == "CALL" else "put",
                        date=self._parse_date(date_str),
                        open=float(item.get("open", 0)),
                        high=float(item.get("high", 0)),
                        low=float(item.get("low", 0)),
                        close=float(item.get("close", 0)),
                        volume=int(item.get("volume", 0)),
                        count=int(item.get("count", 0)),
                        bid=float(item.get("bid", 0)),
                        ask=float(item.get("ask", 0)),
                    )
                    results.append(eod)
                    continue

                # 新格式 (嵌套结构)
                exp_str = contract.get("expiration")
                right_val = contract.get("right", "").upper()
                strike_val = float(contract.get("strike", 0))
                sym = contract.get("symbol", symbol)

                if right_val not in ("CALL", "PUT"):
                    continue

                for record in data_list:
                    date_str = record.get("created") or record.get("timestamp")
                    if not date_str:
                        continue

                    eod = OptionEOD(
                        symbol=sym,
                        expiration=self._parse_date(exp_str),
                        strike=strike_val,
                        option_type="call" if right_val == "CALL" else "put",
                        date=self._parse_date(date_str),
                        open=float(record.get("open", 0)),
                        high=float(record.get("high", 0)),
                        low=float(record.get("low", 0)),
                        close=float(record.get("close", 0)),
                        volume=int(record.get("volume", 0)),
                        count=int(record.get("count", 0)),
                        bid=float(record.get("bid", 0)),
                        ask=float(record.get("ask", 0)),
                    )
                    results.append(eod)

            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse option EOD: {e}")
                continue

        return results

    def get_option_eod_greeks(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        expiration: date | None = None,
        strike: float | None = None,
        right: Literal["call", "put"] | None = None,
        max_dte: int | None = None,
        strike_range: int | None = None,
    ) -> list[OptionEODGreeks]:
        """获取期权 EOD 数据 (含 Greeks)

        这是回测的主要数据获取方法，返回包含完整 Greeks 的期权数据。

        Args:
            symbol: 标的代码
            start_date: 开始日期
            end_date: 结束日期
            expiration: 到期日 (可选，None 表示所有到期日)
            strike: 行权价 (可选)
            right: call 或 put (可选)
            max_dte: 最大 DTE 过滤 (可选)
            strike_range: 返回 ATM 上下各 N 个 strikes (可选，建议 50)

        Returns:
            OptionEODGreeks 列表

        Note:
            expiration=* 时必须按天请求 (start_date == end_date)
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "start_date": self._format_date(start_date),
            "end_date": self._format_date(end_date),
        }

        if expiration:
            params["expiration"] = self._format_date(expiration)
        else:
            params["expiration"] = "*"

        if strike is not None:
            params["strike"] = f"{strike:.3f}"

        if right:
            params["right"] = right.lower()

        if max_dte is not None:
            params["max_dte"] = max_dte

        if strike_range is not None:
            params["strike_range"] = strike_range

        data = self._request("/option/history/greeks/eod", params)
        results = []

        for item in data:
            try:
                # 解析日期
                date_str = item.get("timestamp")
                if not date_str:
                    continue

                exp_str = item.get("expiration")
                if not exp_str:
                    continue

                right_val = item.get("right", "").upper()
                if right_val not in ("CALL", "PUT"):
                    continue

                eod = OptionEODGreeks(
                    symbol=item.get("symbol", symbol),
                    expiration=self._parse_date(exp_str),
                    strike=float(item.get("strike", 0)),
                    option_type="call" if right_val == "CALL" else "put",
                    date=self._parse_date(date_str),
                    open=float(item.get("open", 0)),
                    high=float(item.get("high", 0)),
                    low=float(item.get("low", 0)),
                    close=float(item.get("close", 0)),
                    volume=int(item.get("volume", 0)),
                    count=int(item.get("count", 0)),
                    bid=float(item.get("bid", 0)),
                    ask=float(item.get("ask", 0)),
                    delta=float(item.get("delta", 0)),
                    gamma=float(item.get("gamma", 0)),
                    theta=float(item.get("theta", 0)),
                    vega=float(item.get("vega", 0)),
                    rho=float(item.get("rho", 0)),
                    implied_vol=float(item.get("implied_vol", 0)),
                    underlying_price=float(item.get("underlying_price", 0)),
                    iv_error=float(item["iv_error"]) if item.get("iv_error") else None,
                )
                results.append(eod)
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to parse option Greeks EOD: {e}")
                continue

        return results

    def get_option_open_interest(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        expiration: date | None = None,
    ) -> dict[tuple[date, date, float, str], int]:
        """获取期权未平仓量

        Args:
            symbol: 标的代码
            start_date: 开始日期
            end_date: 结束日期
            expiration: 到期日 (可选)

        Returns:
            {(date, expiration, strike, right): open_interest} 字典
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "start_date": self._format_date(start_date),
            "end_date": self._format_date(end_date),
        }

        if expiration:
            params["expiration"] = self._format_date(expiration)
        else:
            params["expiration"] = "*"

        data = self._request("/option/history/open_interest", params)
        results = {}

        for item in data:
            try:
                date_str = item.get("timestamp") or item.get("date")
                exp_str = item.get("expiration")
                if not date_str or not exp_str:
                    continue

                right_val = item.get("right", "").upper()
                if right_val not in ("CALL", "PUT"):
                    continue

                key = (
                    self._parse_date(date_str),
                    self._parse_date(exp_str),
                    float(item.get("strike", 0)),
                    "call" if right_val == "CALL" else "put",
                )
                results[key] = int(item.get("open_interest", 0))
            except (KeyError, ValueError):
                continue

        return results

    def check_connection(self) -> bool:
        """检查与 ThetaData Terminal 的连接

        Returns:
            True 如果连接正常
        """
        try:
            # 尝试获取股票列表 (轻量级请求)
            self._request("/stock/list/symbols")
            return True
        except ThetaDataError:
            return False

    def get_option_with_greeks(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        expiration: date | None = None,
        strike: float | None = None,
        right: Literal["call", "put"] | None = None,
        max_dte: int | None = None,
        strike_range: int | None = None,
        rate: float | None = None,
        otm_only: bool = True,
    ) -> list[OptionEODGreeks]:
        """获取期权数据 (含 Greeks)，自动 fallback 计算

        优先尝试从 API 获取 Greeks (需要 STANDARD 订阅)，
        如果失败 (403)，则自动从 EOD 数据计算 Greeks。

        Args:
            symbol: 标的代码
            start_date: 开始日期
            end_date: 结束日期
            expiration: 到期日 (可选)
            strike: 行权价 (可选)
            right: call 或 put (可选)
            max_dte: 最大 DTE 过滤 (可选)
            strike_range: 返回 ATM 上下各 N 个 strikes (可选，建议 50)
            rate: 无风险利率 (用于计算 Greeks，默认 0.045)
            otm_only: 只保留 OTM 期权 (默认 True，过滤深度 ITM)

        Returns:
            OptionEODGreeks 列表
        """
        # 1. 尝试从 API 获取 Greeks (除非配置跳过)
        if not self._config.skip_greeks_api:
            try:
                return self.get_option_eod_greeks(
                    symbol, start_date, end_date, expiration, strike, right, max_dte, strike_range
                )
            except ThetaDataError as e:
                if "403" not in str(e):
                    raise  # 非 403 错误，直接抛出
                logger.info("Greeks API not available (FREE tier), falling back to calculation")
        else:
            logger.debug("Skipping Greeks API (FREE tier config)")

        # 2. Fallback: 获取 EOD 数据 + 计算 Greeks
        from src.backtest.data.greeks_calculator import GreeksCalculator

        # 获取期权 EOD (无 Greeks)
        options = self.get_option_eod(
            symbol, start_date, end_date, expiration, strike, right, max_dte, strike_range
        )

        if not options:
            return []

        # 获取股票 EOD (使用缓存避免重复请求)
        cache_key = (symbol, start_date, end_date)
        if not hasattr(self, "_stock_cache"):
            self._stock_cache: dict[tuple, dict[date, float]] = {}

        if cache_key not in self._stock_cache:
            stocks = self.get_stock_eod(symbol, start_date, end_date)
            if not stocks:
                logger.warning(f"No stock data for {symbol}, cannot calculate Greeks")
                return []
            self._stock_cache[cache_key] = {d.date: d.close for d in stocks}

        stock_prices = self._stock_cache[cache_key]

        # 计算 Greeks
        calc = GreeksCalculator()
        calc_rate = rate if rate is not None else 0.045

        results: list[OptionEODGreeks] = []

        itm_filtered = 0
        for opt in options:
            spot = stock_prices.get(opt.date)
            if spot is None:
                continue

            # OTM 过滤：只保留 OTM 期权
            # CALL OTM: strike > spot
            # PUT OTM: strike < spot
            if otm_only:
                is_call = opt.option_type == "call"
                if is_call and opt.strike <= spot:
                    itm_filtered += 1
                    continue
                if not is_call and opt.strike >= spot:
                    itm_filtered += 1
                    continue

            # 计算 mid price
            if opt.bid > 0 and opt.ask > 0:
                mid_price = (opt.bid + opt.ask) / 2
            elif opt.close > 0:
                mid_price = opt.close
            else:
                continue

            # 计算 DTE
            dte = (opt.expiration - opt.date).days
            if dte <= 0:
                continue

            tte = dte / 365.0

            # 计算 Greeks
            greeks = calc.calculate(
                option_price=mid_price,
                spot=spot,
                strike=opt.strike,
                tte=tte,
                rate=calc_rate,
                is_call=(opt.option_type == "call"),
            )

            if not greeks.is_valid:
                continue

            # 转换为 OptionEODGreeks
            results.append(
                OptionEODGreeks(
                    symbol=opt.symbol,
                    expiration=opt.expiration,
                    strike=opt.strike,
                    option_type=opt.option_type,
                    date=opt.date,
                    open=opt.open,
                    high=opt.high,
                    low=opt.low,
                    close=opt.close,
                    volume=opt.volume,
                    count=opt.count,
                    bid=opt.bid,
                    ask=opt.ask,
                    delta=greeks.delta,
                    gamma=greeks.gamma,
                    theta=greeks.theta,
                    vega=greeks.vega,
                    rho=greeks.rho,
                    implied_vol=greeks.iv,
                    underlying_price=spot,
                )
            )

        if itm_filtered > 0:
            logger.info(
                f"Calculated Greeks for {len(results)}/{len(options)} options "
                f"(rate={calc_rate:.2%}, ITM filtered={itm_filtered})"
            )
        else:
            logger.info(
                f"Calculated Greeks for {len(results)}/{len(options)} options "
                f"(rate={calc_rate:.2%})"
            )

        return results
