"""
DuckDB Data Provider - 回测数据提供者

从本地 DuckDB/Parquet 文件读取历史数据，实现与 IBKRProvider/FutuProvider 相同的接口。
这是回测系统的核心数据源。

关键特性:
- 实现 DataProvider 接口，与实盘代码无缝切换
- as_of_date: 回测当前日期，所有查询只返回该日期或之前的数据
- 支持从 Parquet 直接读取或通过 DuckDB 查询

Usage:
    provider = DuckDBProvider(
        data_dir="/Volumes/TradingData/processed",
        as_of_date=date(2024, 1, 15),
    )

    # 与 IBKRProvider 完全相同的接口
    quote = provider.get_stock_quote("AAPL")
    chain = provider.get_option_chain("AAPL", expiry_start=..., expiry_end=...)

    # 回测专用: 步进日期
    provider.set_as_of_date(date(2024, 1, 16))
"""

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

import numpy as np

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
from src.data.providers.base import DataProvider

logger = logging.getLogger(__name__)


class DuckDBProvider(DataProvider):
    """DuckDB 数据提供者

    从本地 DuckDB/Parquet 读取历史数据，实现 DataProvider 接口。

    设计原则:
    - as_of_date: 回测当前日期，模拟"当时"只能看到的数据
    - 所有查询只返回 <= as_of_date 的数据 (避免未来数据泄露)
    - 与实盘 Provider 接口完全一致

    Usage:
        # 初始化
        provider = DuckDBProvider(
            data_dir="/Volumes/TradingData/processed",
            as_of_date=date(2024, 1, 15),
        )

        # 获取股票报价 (返回 as_of_date 当天的收盘数据)
        quote = provider.get_stock_quote("AAPL")

        # 获取期权链 (返回 as_of_date 当天的期权数据)
        chain = provider.get_option_chain("AAPL")

        # 步进到下一个交易日
        provider.set_as_of_date(date(2024, 1, 16))
    """

    def __init__(
        self,
        data_dir: Path | str,
        as_of_date: date | None = None,
        use_duckdb: bool = False,
        db_path: str | None = None,
        auto_download_fundamental: bool = True,
        ibkr_port: int | None = None,
    ) -> None:
        """初始化 DuckDB Provider

        Args:
            data_dir: Parquet 数据目录
            as_of_date: 回测当前日期 (默认今天)
            use_duckdb: 是否使用 DuckDB (False = 直接读 Parquet)
            db_path: DuckDB 数据库路径 (use_duckdb=True 时使用)
            auto_download_fundamental: 是否自动下载缺失的基本面数据
            ibkr_port: IBKR TWS/Gateway 端口 (auto_download 时使用)
        """
        self._data_dir = Path(data_dir)
        self._as_of_date = as_of_date or date.today()
        self._use_duckdb = use_duckdb
        self._db_path = db_path
        self._auto_download_fundamental = auto_download_fundamental
        self._ibkr_port = ibkr_port

        # DuckDB 连接 (lazy init)
        self._conn: duckdb.DuckDBPyConnection | None = None

        # 缓存
        self._trading_days_cache: list[date] | None = None
        self._stock_quote_cache: dict[tuple[str, date], StockQuote | None] = {}
        self._option_chain_cache: dict[tuple[str, date], OptionChain | None] = {}
        self._cache_max_size = 1000  # 最大缓存条目数

        # 全序列缓存（不随 set_as_of_date 清除，历史数据不可变）
        self._kline_series_cache: dict[str, list[tuple]] = {}  # symbol -> [(date, open, high, low, close, volume), ...]
        self._kline_dict_cache: dict[str, dict[date, tuple]] = {}  # symbol -> {date: row}
        self._macro_series_cache: dict[str, list[tuple]] = {}  # indicator -> [(date, open, high, low, close), ...]
        self._stock_volatility_cache: dict[tuple[str, date], StockVolatility | None] = {}  # (symbol, date) -> result
        self._macro_blackout_cache: dict[date, tuple[bool, list]] = {}  # date -> (is_blackout, events)
        self._blackout_prefetched: bool = False  # 防止重复预取

        # 已尝试下载的 symbol 缓存 (避免重复下载失败的 symbol)
        self._fundamental_download_attempted: set[str] = set()

        # 验证数据目录
        if not self._data_dir.exists():
            logger.warning(f"Data directory does not exist: {self._data_dir}")

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """获取 DuckDB 连接 (lazy init)"""
        if self._conn is None:
            if self._db_path:
                self._conn = duckdb.connect(self._db_path)
            else:
                # 内存模式，从 Parquet 查询
                self._conn = duckdb.connect(":memory:")
        return self._conn

    @property
    def name(self) -> str:
        """Provider 名称"""
        return "duckdb"

    @property
    def is_available(self) -> bool:
        """Provider 是否可用"""
        return self._data_dir.exists()

    @property
    def as_of_date(self) -> date:
        """当前回测日期"""
        return self._as_of_date

    def set_as_of_date(self, d: date) -> None:
        """设置回测日期

        Args:
            d: 新的回测日期
        """
        if d != self._as_of_date:
            self._as_of_date = d
            # 清除日期相关缓存 (trading_days 缓存保留)
            # 全序列缓存 (_kline_series_cache, _macro_series_cache) 保留 — 历史数据不可变
            # stock_volatility_cache 保留 — 按 (symbol, date) 缓存，不会有冲突
            self._stock_quote_cache.clear()
            self._option_chain_cache.clear()
            logger.debug(f"DuckDBProvider as_of_date set to {d}, cache cleared")

    def clear_cache(self) -> None:
        """清除所有缓存（包括全序列缓存）"""
        self._stock_quote_cache.clear()
        self._option_chain_cache.clear()
        self._trading_days_cache = None
        self._kline_series_cache.clear()
        self._kline_dict_cache.clear()
        self._macro_series_cache.clear()
        self._stock_volatility_cache.clear()
        self._macro_blackout_cache.clear()
        self._blackout_prefetched = False
        logger.debug("DuckDBProvider all caches cleared")

    # ========== Fundamental Auto-Download ==========

    def _has_fundamental_data(self, symbol: str) -> bool:
        """检查是否有该 symbol 的基本面数据

        Args:
            symbol: 股票代码

        Returns:
            是否存在数据
        """
        eps_path = self._data_dir / "fundamental_eps.parquet"
        if not eps_path.exists():
            return False

        try:
            conn = self._get_conn()
            result = conn.execute(
                f"""
                SELECT COUNT(*) FROM read_parquet('{eps_path}')
                WHERE symbol = ?
                """,
                [symbol],
            ).fetchone()
            return result[0] > 0 if result else False
        except Exception:
            return False

    def _download_fundamental_data(self, symbol: str) -> bool:
        """从 IBKR 下载基本面数据

        Args:
            symbol: 股票代码

        Returns:
            是否下载成功
        """
        # 避免重复尝试已失败的 symbol
        if symbol in self._fundamental_download_attempted:
            return False

        self._fundamental_download_attempted.add(symbol)

        try:
            from src.backtest.data.ibkr_fundamental_downloader import IBKRFundamentalDownloader

            port = self._ibkr_port or int(__import__("os").getenv("IBKR_PORT", "7497"))

            logger.info("=" * 50)
            logger.info(f"📥 Auto-downloading fundamental data for {symbol}")
            logger.info(f"   Connecting to IBKR TWS/Gateway on port {port}...")
            logger.info("   (This may take 5-10 seconds)")
            logger.info("=" * 50)

            downloader = IBKRFundamentalDownloader(
                data_dir=self._data_dir,
                port=self._ibkr_port,
            )

            # 进度回调
            def on_progress(sym: str, current: int, total: int):
                logger.info(f"   [{current}/{total}] Downloading {sym}...")

            results = downloader.download_and_save(
                symbols=[symbol],
                on_progress=on_progress,
                delay=0.5,
            )

            if results:
                eps_count = results.get("eps", 0)
                rev_count = results.get("revenue", 0)
                div_count = results.get("dividend", 0)
                logger.info(f"✅ Downloaded {symbol}: EPS={eps_count}, Revenue={rev_count}, Dividend={div_count}")
                return True
            else:
                logger.warning(f"❌ Failed to download fundamental data for {symbol}")
                logger.warning("   Please check: TWS/Gateway running? Market data subscription?")
                return False

        except ImportError as e:
            logger.warning(f"IBKRFundamentalDownloader not available: {e}")
            return False
        except Exception as e:
            logger.warning(f"❌ Error downloading fundamental data for {symbol}: {e}")
            return False

    # 常见 ETF 列表 (ETF 没有传统的 EPS/Revenue 数据)
    _ETF_SYMBOLS = frozenset({
        "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "EEM", "XLF", "XLE", "XLK",
        "GLD", "SLV", "TLT", "HYG", "LQD", "VXX", "UVXY", "SQQQ", "TQQQ",
        "ARKK", "XBI", "IBB", "SMH", "SOXX", "XOP", "OIH", "GDX", "GDXJ",
    })

    def _ensure_fundamental_data(self, symbol: str) -> bool:
        """确保有该 symbol 的基本面数据，没有则自动下载

        Args:
            symbol: 股票代码

        Returns:
            是否有数据可用
        """
        if self._has_fundamental_data(symbol):
            return True

        if not self._auto_download_fundamental:
            return False

        # ETF 没有传统的 EPS/Revenue 数据，跳过下载
        if symbol.upper() in self._ETF_SYMBOLS:
            return False

        return self._download_fundamental_data(symbol)

    # ========== Stock Data Methods ==========

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """获取股票报价 (as_of_date 当天)

        Args:
            symbol: 股票代码

        Returns:
            StockQuote 或 None
        """
        symbol = symbol.upper()

        # Optimization: Fetch full kline series into memory and use dictionary for O(1) lookup
        if symbol not in self._kline_series_cache:
            self._kline_series_cache[symbol] = self._load_full_kline_series(symbol)
            
            # 建立基于日期的 O(1) 索引字典
            date_dict = {}
            for row in self._kline_series_cache[symbol]:
                date_val = row[0]
                if isinstance(date_val, str):
                    date_val = date.fromisoformat(date_val)
                elif isinstance(date_val, datetime):
                    date_val = date_val.date()
                date_dict[date_val] = row
            self._kline_dict_cache[symbol] = date_dict

        # 直接从全量内存字典中取当天数据
        row = self._kline_dict_cache[symbol].get(self._as_of_date)
        
        if row is None:
            return None

        return StockQuote(
            symbol=symbol,
            timestamp=datetime.combine(self._as_of_date, datetime.min.time()),
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            source="duckdb",
        )

    def get_stock_quotes(self, symbols: list[str]) -> list[StockQuote]:
        """获取多只股票报价

        Args:
            symbols: 股票代码列表

        Returns:
            StockQuote 列表
        """
        results = []
        for symbol in symbols:
            quote = self.get_stock_quote(symbol)
            if quote:
                results.append(quote)
        return results

    def _load_full_kline_series(self, symbol: str) -> list[tuple]:
        """加载某个 symbol 的全部日线数据到内存

        一次性从 stock_daily.parquet 读取该 symbol 的所有行，
        后续查询直接在内存中按日期过滤。

        Args:
            symbol: 股票代码 (大写)

        Returns:
            [(date, open, high, low, close, volume), ...] 按日期升序
        """
        parquet_path = self._data_dir / "stock_daily.parquet"
        if not parquet_path.exists():
            return []

        try:
            conn = self._get_conn()
            rows = conn.execute(
                f"""
                SELECT date, open, high, low, close, volume
                FROM read_parquet('{parquet_path}')
                WHERE symbol = ?
                ORDER BY date
                """,
                [symbol],
            ).fetchall()
            logger.debug(f"Loaded full kline series for {symbol}: {len(rows)} rows")
            return rows
        except Exception as e:
            logger.error(f"Failed to load kline series for {symbol}: {e}")
            return []

    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """获取历史 K 线数据

        注意: 只返回 <= as_of_date 的数据 (避免未来数据泄露)
        使用全序列内存缓存，首次加载后不再查询 DuckDB。

        Args:
            symbol: 股票代码
            ktype: K 线类型 (目前只支持 DAY)
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            KlineBar 列表
        """
        if ktype != KlineType.DAY:
            logger.warning(f"DuckDBProvider only supports daily klines, got {ktype}")
            return []

        symbol = symbol.upper()

        # 首次调用时加载全序列到缓存
        if symbol not in self._kline_series_cache:
            self._kline_series_cache[symbol] = self._load_full_kline_series(symbol)

        # 限制 end_date 不超过 as_of_date
        effective_end = min(end_date, self._as_of_date)

        # 在内存中按日期范围过滤
        return [
            KlineBar(
                symbol=symbol,
                timestamp=datetime.combine(row[0], datetime.min.time()),
                ktype=KlineType.DAY,
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
                source="duckdb",
            )
            for row in self._kline_series_cache[symbol]
            if start_date <= row[0] <= effective_end
        ]

    # ========== Option Data Methods ==========

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
        # 兼容 UnifiedDataProvider/IBKRProvider 的参数
        expiry_min_days: int | None = None,
        expiry_max_days: int | None = None,
        **kwargs,  # 忽略其他参数
    ) -> OptionChain | None:
        """获取期权链

        返回 as_of_date 当天的期权数据，按到期日筛选。

        Args:
            underlying: 标的代码
            expiry_start: 到期日开始筛选
            expiry_end: 到期日结束筛选
            expiry_min_days: 最小到期天数 (相对于 as_of_date)
            expiry_max_days: 最大到期天数 (相对于 as_of_date)
            **kwargs: 忽略其他参数 (兼容性)

        Returns:
            OptionChain 或 None
        """
        underlying = underlying.upper()

        # 将 expiry_min_days/expiry_max_days 转换为 expiry_start/expiry_end
        if expiry_min_days is not None and expiry_start is None:
            expiry_start = self._as_of_date + timedelta(days=expiry_min_days)
        if expiry_max_days is not None and expiry_end is None:
            expiry_end = self._as_of_date + timedelta(days=expiry_max_days)

        # 检查全链缓存 (Optimization: Fetch whole chain once per day to avoid multiple DuckDB queries)
        cache_key = (underlying, self._as_of_date)
        
        chain = self._option_chain_cache.get(cache_key)
        
        if chain is None and cache_key not in self._option_chain_cache:
            # 查找期权数据
            option_dir = self._data_dir / "option_daily" / underlying
            if not option_dir.exists():
                logger.warning(f"Option data not found for {underlying}")
                self._option_chain_cache[cache_key] = None
                return None

            # 确定要读取的 Parquet 文件
            year = self._as_of_date.year
            parquet_files = []

            # 优先读取当年的文件
            year_file = option_dir / f"{year}.parquet"
            if year_file.exists():
                parquet_files.append(year_file)

            # 如果当年文件不存在，尝试读取所有文件
            if not parquet_files:
                parquet_files = list(option_dir.glob("*.parquet"))

            if not parquet_files:
                logger.warning(f"No parquet files found for {underlying}")
                self._option_chain_cache[cache_key] = None
                return None

            try:
                # 构建查询条件: 获取当天该标的的所有期权合约（不在这里过滤日期，而在内存中过滤）
                conditions = ["date = ?"]
                params: list[Any] = [self._as_of_date]

                where_clause = " AND ".join(conditions)

                # 合并多个 Parquet 文件的查询
                parquet_list = ", ".join([f"'{pf}'" for pf in parquet_files])

                conn = self._get_conn()
                rows = conn.execute(
                    f"""
                    SELECT
                        symbol, expiration, strike, option_type, date,
                        open, high, low, close, volume, count,
                        bid, ask, delta, gamma, theta, vega, rho,
                        implied_vol, underlying_price, open_interest
                    FROM read_parquet([{parquet_list}])
                    WHERE {where_clause}
                    ORDER BY expiration, strike, option_type
                    """,
                    params,
                ).fetchall()

                if not rows:
                    self._option_chain_cache[cache_key] = None
                    return None

                # 构建 OptionChain
                calls: list[OptionQuote] = []
                puts: list[OptionQuote] = []
                expiry_dates: set[date] = set()

                for row in rows:
                    (
                        symbol, expiration, strike, opt_type, data_date,
                        open_price, high, low, close, volume, count,
                        bid, ask, delta, gamma, theta, vega, rho,
                        implied_vol, underlying_price, open_interest,
                    ) = row

                    expiry_dates.add(expiration)

                    # 构建期权符号 (简化格式)
                    option_symbol = (
                        f"{underlying}{expiration.strftime('%y%m%d')}"
                        f"{'C' if opt_type == 'call' else 'P'}{int(strike * 1000):08d}"
                    )

                    contract = OptionContract(
                        symbol=option_symbol,
                        underlying=underlying,
                        option_type=OptionType.CALL if opt_type == "call" else OptionType.PUT,
                        strike_price=strike,
                        expiry_date=expiration,
                    )

                    greeks = Greeks(
                        delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho,
                    )

                    quote = OptionQuote(
                        contract=contract,
                        timestamp=datetime.combine(data_date, datetime.min.time()),
                        last_price=close,
                        bid=bid, ask=ask, volume=volume, open_interest=open_interest,
                        iv=implied_vol, greeks=greeks, source="duckdb",
                        open=open_price, high=high, low=low, close=close,
                    )

                    if opt_type == "call":
                        calls.append(quote)
                    else:
                        puts.append(quote)

                chain = OptionChain(
                    underlying=underlying,
                    timestamp=datetime.combine(self._as_of_date, datetime.min.time()),
                    expiry_dates=sorted(expiry_dates),
                    calls=calls, puts=puts, source="duckdb",
                )

                # 缓存全链结果
                if len(self._option_chain_cache) >= self._cache_max_size:
                    keys_to_remove = list(self._option_chain_cache.keys())[: self._cache_max_size // 2]
                    for k in keys_to_remove:
                        del self._option_chain_cache[k]
                        
                self._option_chain_cache[cache_key] = chain

            except Exception as e:
                logger.error(f"Failed to get option chain for {underlying}: {e}")
                self._option_chain_cache[cache_key] = None
                return None

        if not chain:
            return None

        # 内存中按到期日过滤
        if expiry_start is None and expiry_end is None:
            return chain
            
        filtered_calls = []
        filtered_puts = []
        filtered_expiries = set()
        
        for quote in chain.calls:
            if expiry_start and quote.contract.expiry_date < expiry_start:
                continue
            if expiry_end and quote.contract.expiry_date > expiry_end:
                continue
            filtered_calls.append(quote)
            filtered_expiries.add(quote.contract.expiry_date)
            
        for quote in chain.puts:
            if expiry_start and quote.contract.expiry_date < expiry_start:
                continue
            if expiry_end and quote.contract.expiry_date > expiry_end:
                continue
            filtered_puts.append(quote)
            filtered_expiries.add(quote.contract.expiry_date)
            
        return OptionChain(
            underlying=chain.underlying,
            timestamp=chain.timestamp,
            expiry_dates=sorted(filtered_expiries),
            calls=filtered_calls,
            puts=filtered_puts,
            source=chain.source,
        )

    def get_option_quote(self, symbol: str) -> OptionQuote | None:
        """获取单个期权合约报价

        Args:
            symbol: 期权符号

        Returns:
            OptionQuote 或 None
        """
        # TODO: 实现期权符号解析和查询
        logger.warning("get_option_quote not fully implemented for DuckDBProvider")
        return None

    # ========== Fundamental & Macro ==========

    def get_fundamental(self, symbol: str) -> Fundamental | None:
        """获取基本面数据 (历史 point-in-time)

        从 IBKR 下载的基本面数据中读取，返回 as_of_date 时点的基本面信息。
        如果数据不存在且 auto_download_fundamental=True，会自动从 IBKR 下载。

        数据来源:
        - fundamental_eps.parquet: EPS (TTM) 数据
        - fundamental_revenue.parquet: 营收数据
        - fundamental_dividend.parquet: 股息数据

        计算逻辑:
        - EPS: 使用最近一期 EPS (TTM)
        - PE: 当日股价 / EPS (TTM)
        - ex_dividend_date: 下一个除息日

        Args:
            symbol: 股票代码

        Returns:
            Fundamental 对象或 None
        """
        # 确保有该 symbol 的基本面数据（没有则自动下载）
        if not self._ensure_fundamental_data(symbol):
            logger.debug(f"No fundamental data available for {symbol}")
            return None

        eps_path = self._data_dir / "fundamental_eps.parquet"
        revenue_path = self._data_dir / "fundamental_revenue.parquet"
        dividend_path = self._data_dir / "fundamental_dividend.parquet"

        # 检查是否有基本面数据文件
        if not eps_path.exists():
            logger.debug(f"No fundamental EPS data found at {eps_path}")
            return None

        try:
            conn = self._get_conn()

            # 1. 获取最近的 EPS (TTM)
            # 选择 as_of_date 之前最近的 TTM EPS 数据
            eps_row = conn.execute(
                f"""
                SELECT as_of_date, eps, report_type, period
                FROM read_parquet('{eps_path}')
                WHERE symbol = ?
                  AND report_type = 'TTM'
                  AND period = '12M'
                  AND as_of_date <= ?
                ORDER BY as_of_date DESC
                LIMIT 1
                """,
                [symbol, self._as_of_date],
            ).fetchone()

            eps_value = None
            eps_date = None
            if eps_row:
                eps_date = eps_row[0]
                if isinstance(eps_date, str):
                    eps_date = date.fromisoformat(eps_date)
                elif isinstance(eps_date, datetime):
                    eps_date = eps_date.date()
                eps_value = eps_row[1]

            # 2. 获取最近的 Revenue (TTM)
            revenue_value = None
            if revenue_path.exists():
                rev_row = conn.execute(
                    f"""
                    SELECT as_of_date, revenue
                    FROM read_parquet('{revenue_path}')
                    WHERE symbol = ?
                      AND report_type = 'TTM'
                      AND period = '12M'
                      AND as_of_date <= ?
                    ORDER BY as_of_date DESC
                    LIMIT 1
                    """,
                    [symbol, self._as_of_date],
                ).fetchone()

                if rev_row:
                    revenue_value = rev_row[1]

            # 3. 获取下一个除息日 (as_of_date 之后的第一个)
            ex_dividend_date = None
            if dividend_path.exists():
                div_row = conn.execute(
                    f"""
                    SELECT ex_date
                    FROM read_parquet('{dividend_path}')
                    WHERE symbol = ?
                      AND ex_date > ?
                    ORDER BY ex_date ASC
                    LIMIT 1
                    """,
                    [symbol, self._as_of_date],
                ).fetchone()

                if div_row:
                    ex_dividend_date = div_row[0]
                    if isinstance(ex_dividend_date, str):
                        ex_dividend_date = date.fromisoformat(ex_dividend_date)
                    elif isinstance(ex_dividend_date, datetime):
                        ex_dividend_date = ex_dividend_date.date()

            # 4. 获取当日股价计算 PE
            pe_ratio = None
            stock_quote = self.get_stock_quote(symbol)
            if stock_quote and eps_value and eps_value != 0:
                pe_ratio = stock_quote.close / eps_value

            # 5. 构建 Fundamental 对象
            return Fundamental(
                symbol=symbol,
                date=self._as_of_date,
                eps=eps_value,
                pe_ratio=pe_ratio,
                revenue=revenue_value,
                ex_dividend_date=ex_dividend_date,
                source="duckdb",
            )

        except Exception as e:
            logger.error(f"Failed to get fundamental data for {symbol}: {e}")
            return None

    def get_historical_eps(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        report_type: str = "TTM",
    ) -> list[tuple[date, float]]:
        """获取历史 EPS 数据

        Args:
            symbol: 股票代码
            start_date: 开始日期 (默认无限制)
            end_date: 结束日期 (默认 as_of_date)
            report_type: 报告类型 (TTM, P, R, A)

        Returns:
            [(date, eps), ...] 列表
        """
        eps_path = self._data_dir / "fundamental_eps.parquet"
        if not eps_path.exists():
            return []

        effective_end = min(end_date, self._as_of_date) if end_date else self._as_of_date

        try:
            conn = self._get_conn()

            query = f"""
                SELECT as_of_date, eps
                FROM read_parquet('{eps_path}')
                WHERE symbol = ?
                  AND report_type = ?
                  AND period = '12M'
                  AND as_of_date <= ?
            """
            params = [symbol, report_type, effective_end]

            if start_date:
                query += " AND as_of_date >= ?"
                params.append(start_date)

            query += " ORDER BY as_of_date"

            rows = conn.execute(query, params).fetchall()

            results = []
            for row in rows:
                row_date = row[0]
                if isinstance(row_date, str):
                    row_date = date.fromisoformat(row_date)
                elif isinstance(row_date, datetime):
                    row_date = row_date.date()
                results.append((row_date, row[1]))

            return results

        except Exception as e:
            logger.error(f"Failed to get historical EPS for {symbol}: {e}")
            return []

    def get_dividend_dates(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        """获取历史除息日列表

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            除息日列表
        """
        dividend_path = self._data_dir / "fundamental_dividend.parquet"
        if not dividend_path.exists():
            return []

        try:
            conn = self._get_conn()

            query = f"""
                SELECT ex_date
                FROM read_parquet('{dividend_path}')
                WHERE symbol = ?
            """
            params = [symbol]

            if start_date:
                query += " AND ex_date >= ?"
                params.append(start_date)

            if end_date:
                query += " AND ex_date <= ?"
                params.append(end_date)

            query += " ORDER BY ex_date"

            rows = conn.execute(query, params).fetchall()

            results = []
            for row in rows:
                row_date = row[0]
                if isinstance(row_date, str):
                    row_date = date.fromisoformat(row_date)
                elif isinstance(row_date, datetime):
                    row_date = row_date.date()
                results.append(row_date)

            return results

        except Exception as e:
            logger.error(f"Failed to get dividend dates for {symbol}: {e}")
            return []

    def _load_full_macro_series(self, indicator: str) -> list[tuple]:
        """加载某个指标的全部宏观数据到内存

        一次性从 macro_daily.parquet 读取该 indicator 的所有行，
        后续查询直接在内存中按日期过滤。

        Args:
            indicator: 宏观指标 (如 ^VIX, ^TNX, SPY)

        Returns:
            [(date, open, high, low, close), ...] 按日期升序
        """
        parquet_path = self._data_dir / "macro_daily.parquet"
        if not parquet_path.exists():
            return []

        try:
            conn = self._get_conn()
            rows = conn.execute(
                f"""
                SELECT date, open, high, low, close
                FROM read_parquet('{parquet_path}')
                WHERE indicator = ?
                ORDER BY date
                """,
                [indicator],
            ).fetchall()
            logger.debug(f"Loaded full macro series for {indicator}: {len(rows)} rows")
            return rows
        except Exception as e:
            logger.error(f"Failed to load macro series for {indicator}: {e}")
            return []

    def get_macro_data(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroData]:
        """获取宏观数据 (VIX/TNX 等)

        从 macro_daily.parquet 读取历史数据。
        注意: 只返回 <= as_of_date 的数据 (避免未来数据泄露)
        使用全序列内存缓存，首次加载后不再查询 DuckDB。

        Args:
            indicator: 宏观指标 (如 ^VIX, ^TNX, SPY)
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            MacroData 列表 (按日期升序)
        """
        # 首次调用时加载全序列到缓存
        if indicator not in self._macro_series_cache:
            self._macro_series_cache[indicator] = self._load_full_macro_series(indicator)

        if not self._macro_series_cache[indicator]:
            return []

        # 限制 end_date 不超过 as_of_date
        effective_end = min(end_date, self._as_of_date)

        # 在内存中按日期范围过滤
        results = []
        for row in self._macro_series_cache[indicator]:
            # row: (date, open, high, low, close)
            data_date = row[0]
            if isinstance(data_date, str):
                data_date = date.fromisoformat(data_date)
            elif isinstance(data_date, datetime):
                data_date = data_date.date()

            if start_date <= data_date <= effective_end:
                results.append(MacroData(
                    indicator=indicator,
                    date=data_date,
                    value=row[4],  # close 作为 value
                    open=row[1],
                    high=row[2],
                    low=row[3],
                    close=row[4],
                    volume=None,
                    source="duckdb",
                ))

        return results

    def get_available_macro_indicators(self) -> list[str]:
        """获取可用的宏观指标列表

        Returns:
            指标列表 (如 ["^VIX", "^TNX", "SPY"])
        """
        parquet_path = self._data_dir / "macro_daily.parquet"
        if not parquet_path.exists():
            return []

        try:
            conn = self._get_conn()
            rows = conn.execute(
                f"""
                SELECT DISTINCT indicator
                FROM read_parquet('{parquet_path}')
                ORDER BY indicator
                """
            ).fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Failed to get available macro indicators: {e}")
            return []

    # ========== Backtest-Specific Methods ==========

    def get_trading_days(
        self,
        start_date: date,
        end_date: date,
        symbol: str | None = None,
    ) -> list[date]:
        """获取交易日列表

        从历史数据中提取有数据的日期作为交易日。

        Args:
            start_date: 开始日期
            end_date: 结束日期
            symbol: 标的代码 (可选，用于过滤)

        Returns:
            交易日列表 (升序)
        """
        parquet_path = self._data_dir / "stock_daily.parquet"

        if not parquet_path.exists():
            # 尝试从期权数据获取
            option_base = self._data_dir / "option_daily"
            if not option_base.exists():
                return []

            # 使用第一个有数据的标的
            symbol_dirs = list(option_base.iterdir())
            if not symbol_dirs:
                return []

            parquet_files = list(symbol_dirs[0].glob("*.parquet"))
            if not parquet_files:
                return []

            parquet_path = parquet_files[0]
            date_col = "date"
        else:
            date_col = "date"

        try:
            conn = self._get_conn()

            if symbol:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT {date_col}
                    FROM read_parquet('{parquet_path}')
                    WHERE symbol = ?
                      AND {date_col} >= ?
                      AND {date_col} <= ?
                    ORDER BY {date_col}
                    """,
                    [symbol.upper(), start_date, end_date],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT {date_col}
                    FROM read_parquet('{parquet_path}')
                    WHERE {date_col} >= ?
                      AND {date_col} <= ?
                    ORDER BY {date_col}
                    """,
                    [start_date, end_date],
                ).fetchall()

            return [row[0] for row in rows]

        except Exception as e:
            logger.error(f"Failed to get trading days: {e}")
            return []

    def get_next_trading_day(self, d: date | None = None) -> date | None:
        """获取下一个交易日

        Args:
            d: 基准日期 (默认 as_of_date)

        Returns:
            下一个交易日或 None
        """
        base = d or self._as_of_date

        # 获取交易日列表 (缓存)
        if self._trading_days_cache is None:
            # 获取未来一年的交易日
            self._trading_days_cache = self.get_trading_days(
                base, base + timedelta(days=365)
            )

        for td in self._trading_days_cache:
            if td > base:
                return td

        return None

    def get_available_symbols(self) -> list[str]:
        """获取可用的标的列表

        Returns:
            标的代码列表
        """
        option_dir = self._data_dir / "option_daily"
        if option_dir.exists():
            return sorted([d.name for d in option_dir.iterdir() if d.is_dir()])
        return []

    def close(self) -> None:
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def create_optimized_db(
        self,
        db_path: str | Path,
        symbols: list[str] | None = None,
    ) -> Path:
        """创建优化的 DuckDB 数据库

        将 Parquet 数据导入 DuckDB 并创建索引，提高查询性能。
        适合需要反复查询的大规模回测场景。

        Args:
            db_path: DuckDB 数据库路径
            symbols: 要导入的标的列表 (None 表示全部)

        Returns:
            数据库文件路径
        """
        from src.backtest.data.schema import (
            StockDailySchema,
            OptionDailySchema,
            init_duckdb_schema,
            load_parquet_to_duckdb,
        )

        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建新数据库
        conn = duckdb.connect(str(db_path))

        try:
            # 初始化 schema 和索引
            init_duckdb_schema(conn)

            # 加载数据
            load_parquet_to_duckdb(conn, self._data_dir, symbols)

            # 创建额外的复合索引以优化常见查询
            # 期权链查询: WHERE date = ? AND symbol = ? AND expiration >= ? AND expiration <= ?
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_option_daily_query
                ON option_daily(date, symbol, expiration)
            """)

            # 股票查询: WHERE date = ? AND symbol = ?
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stock_daily_query
                ON stock_daily(date, symbol)
            """)

            # 分析表以更新统计信息
            conn.execute("ANALYZE stock_daily")
            conn.execute("ANALYZE option_daily")

            logger.info(f"Created optimized DuckDB at {db_path}")

        finally:
            conn.close()

        return db_path

    def use_optimized_db(self, db_path: str | Path) -> None:
        """切换到使用优化的 DuckDB 数据库

        Args:
            db_path: DuckDB 数据库路径
        """
        self.close()
        self._db_path = str(db_path)
        self._use_duckdb = True
        self._conn = None  # Will be lazily initialized
        self.clear_cache()
        logger.info(f"Switched to optimized DuckDB: {db_path}")

    # ========== Screening Support Methods ==========

    def get_option_quotes_batch(
        self,
        contracts: list[OptionContract],
        min_volume: int | None = None,
        fetch_margin: bool = False,  # 兼容 UnifiedDataProvider (回测忽略)
        underlying_price: float | None = None,  # 兼容 UnifiedDataProvider
        **kwargs,  # 忽略其他参数
    ) -> list[OptionQuote]:
        """获取批量期权合约报价

        从 option_daily Parquet 数据获取指定合约的报价信息。

        Args:
            contracts: 要查询的期权合约列表
            min_volume: 可选的最小成交量过滤
            fetch_margin: 是否获取保证金 (回测模式忽略)
            underlying_price: 标的价格 (回测模式忽略)
            **kwargs: 忽略其他参数 (兼容性)

        Returns:
            OptionQuote 列表
        """
        if not contracts:
            return []

        results: list[OptionQuote] = []

        # 按 underlying 分组查询，提高效率
        contracts_by_underlying: dict[str, list[OptionContract]] = {}
        for contract in contracts:
            underlying = contract.underlying.upper()
            if underlying not in contracts_by_underlying:
                contracts_by_underlying[underlying] = []
            contracts_by_underlying[underlying].append(contract)

        for underlying, underlying_contracts in contracts_by_underlying.items():
            # 查找期权数据目录
            option_dir = self._data_dir / "option_daily" / underlying
            if not option_dir.exists():
                logger.debug(f"Option data not found for {underlying}")
                continue

            # 确定 Parquet 文件
            year = self._as_of_date.year
            parquet_file = option_dir / f"{year}.parquet"
            if not parquet_file.exists():
                # 尝试其他年份文件
                parquet_files = list(option_dir.glob("*.parquet"))
                if not parquet_files:
                    continue
                parquet_file = parquet_files[0]

            try:
                conn = self._get_conn()

                for contract in underlying_contracts:
                    # 转换 option_type
                    opt_type_str = "call" if contract.option_type == OptionType.CALL else "put"

                    # 查询特定合约
                    row = conn.execute(
                        f"""
                        SELECT
                            symbol, expiration, strike, option_type, date,
                            open, high, low, close, volume, count,
                            bid, ask, delta, gamma, theta, vega, rho,
                            implied_vol, underlying_price, open_interest
                        FROM read_parquet('{parquet_file}')
                        WHERE date = ?
                          AND expiration = ?
                          AND strike = ?
                          AND option_type = ?
                        LIMIT 1
                        """,
                        [
                            self._as_of_date,
                            contract.expiry_date,
                            contract.strike_price,
                            opt_type_str,
                        ],
                    ).fetchone()

                    if row is None:
                        continue

                    # 检查最小成交量
                    volume = row[9] or 0
                    if min_volume is not None and volume < min_volume:
                        continue

                    # 构建 OptionQuote
                    (
                        symbol,
                        expiration,
                        strike,
                        opt_type,
                        data_date,
                        open_price,
                        high,
                        low,
                        close,
                        volume,
                        count,
                        bid,
                        ask,
                        delta,
                        gamma,
                        theta,
                        vega,
                        rho,
                        implied_vol,
                        underlying_price,
                        open_interest,
                    ) = row

                    greeks = Greeks(
                        delta=delta,
                        gamma=gamma,
                        theta=theta,
                        vega=vega,
                        rho=rho,
                    )

                    quote = OptionQuote(
                        contract=contract,
                        timestamp=datetime.combine(data_date, datetime.min.time()),
                        last_price=close,
                        bid=bid,
                        ask=ask,
                        volume=volume,
                        open_interest=open_interest or 0,
                        iv=implied_vol,
                        greeks=greeks,
                        source="duckdb",
                        # OHLC 价格 (用于回测 price_mode)
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                    )
                    results.append(quote)

            except Exception as e:
                logger.error(f"Failed to get option quotes for {underlying}: {e}")

        return results

    def _prefetch_economic_calendar(
        self,
        blackout_days: int,
        blackout_events: list[str],
    ) -> None:
        """从本地 economic_calendar.json 加载经济日历，预计算所有交易日的黑名单状态

        首次调用 check_macro_blackout 时触发。数据来源于数据下载阶段
        (scripts/download_backtest_data.py) 预生成的 JSON 文件，不需要在线 API。
        """
        from datetime import timedelta

        try:
            import json

            from src.data.models.event import EconomicEventType, EventCalendar

            # 1. 从本地 JSON 加载经济日历
            cal_path = self._data_dir / "economic_calendar.json"
            if not cal_path.exists():
                logger.warning(f"Economic calendar not found: {cal_path}, blackout check disabled")
                return

            with open(cal_path, "r", encoding="utf-8") as f:
                cal_data = json.load(f)

            calendar = EventCalendar.from_dict(cal_data)
            logger.info(
                f"Economic calendar loaded from {cal_path.name}: "
                f"{len(calendar.events)} events ({calendar.start_date} ~ {calendar.end_date})"
            )

            # 2. 按 event_types 过滤 (e.g. ["FOMC", "CPI", "NFP"])
            type_map = {t.name: t for t in EconomicEventType}
            filter_types = [type_map[t] for t in blackout_events if t in type_map]
            if filter_types:
                calendar = calendar.filter_by_type(filter_types)

            all_events = calendar.events
            if not all_events:
                logger.info("No matching economic events found for blackout check")
                return

            # 3. 获取交易日列表
            if self._trading_days_cache:
                trading_days = self._trading_days_cache
            else:
                trading_days = self.get_trading_days(
                    calendar.start_date, calendar.end_date
                )

            # 4. 为每个交易日预计算黑名单状态
            for day in trading_days:
                day_end = day + timedelta(days=blackout_days)
                causing = [e for e in all_events if day <= e.event_date <= day_end]
                self._macro_blackout_cache[day] = (len(causing) > 0, causing)

            logger.info(
                f"Economic calendar prefetched: {len(trading_days)} days cached, "
                f"{len(all_events)} events matched ({', '.join(blackout_events)})"
            )

        except Exception as e:
            logger.warning(f"Failed to prefetch economic calendar: {e}")

    def check_macro_blackout(
        self,
        target_date: date | None = None,
        blackout_days: int = 2,
        blackout_events: list[str] | None = None,
    ) -> tuple[bool, list]:
        """检查是否处于宏观事件黑名单期

        使用 EconomicCalendarProvider 检查指定日期是否处于重大宏观事件
        (FOMC/CPI/NFP) 的黑名单期。首次调用时一次性预取整个回测期间的日历。

        Args:
            target_date: 要检查的日期 (默认 as_of_date)
            blackout_days: 事件前几天开始黑名单期
            blackout_events: 要检查的事件类型列表 (默认 ["FOMC", "CPI", "NFP"])

        Returns:
            (是否处于黑名单期, 即将到来的事件列表)
        """
        if target_date is None:
            target_date = self._as_of_date

        if blackout_events is None:
            blackout_events = ["FOMC", "CPI", "NFP"]

        # 首次调用时从本地 JSON 预取整个回测期间的经济日历
        if not self._blackout_prefetched:
            self._blackout_prefetched = True
            self._prefetch_economic_calendar(blackout_days, blackout_events)

        # 从缓存返回
        if target_date in self._macro_blackout_cache:
            return self._macro_blackout_cache[target_date]

        # 缓存未命中（日期不在交易日列表中）— fall-open
        return False, []

    def get_stock_beta(self, symbol: str, as_of_date: date | None = None) -> float | None:
        """获取股票 Beta 值

        优先从 stock_beta_daily.parquet 读取动态滚动 Beta，
        如果不存在则回退到 stock_beta.parquet 静态 Beta。

        Args:
            symbol: 股票代码
            as_of_date: 查询日期 (如果为 None，返回最新值)

        Returns:
            Beta 值或 None
        """
        conn = self._get_conn()

        # 优先使用动态滚动 Beta (stock_beta_daily.parquet)
        rolling_beta_path = self._data_dir / "stock_beta_daily.parquet"
        if rolling_beta_path.exists():
            try:
                if as_of_date:
                    # 查询指定日期或之前最近的 Beta
                    result = conn.execute(
                        f"""
                        SELECT beta FROM read_parquet('{rolling_beta_path}')
                        WHERE symbol = ? AND date <= ?
                        ORDER BY date DESC LIMIT 1
                        """,
                        [symbol.upper(), as_of_date],
                    ).fetchone()
                else:
                    # 查询最新 Beta
                    result = conn.execute(
                        f"""
                        SELECT beta FROM read_parquet('{rolling_beta_path}')
                        WHERE symbol = ?
                        ORDER BY date DESC LIMIT 1
                        """,
                        [symbol.upper()],
                    ).fetchone()

                if result:
                    return float(result[0])
            except Exception as e:
                logger.warning(f"Failed to get rolling beta for {symbol}: {e}")

        # 回退到静态 Beta (stock_beta.parquet)
        static_beta_path = self._data_dir / "stock_beta.parquet"
        if static_beta_path.exists():
            try:
                result = conn.execute(
                    f"SELECT beta FROM read_parquet('{static_beta_path}') WHERE symbol = ?",
                    [symbol.upper()],
                ).fetchone()
                if result:
                    return float(result[0])
            except Exception as e:
                logger.warning(f"Failed to get static beta for {symbol}: {e}")

        logger.debug(f"Beta data not found for {symbol}")
        return None

    def get_stock_volatility(self, symbol: str) -> StockVolatility | None:
        """获取股票波动率指标

        计算股票的 IV 和 HV:
        - HV: 20 日历史波动率 (从 stock_daily 计算)
        - IV: ATM 期权的平均隐含波动率 (从 option_daily 获取)

        结果按 (symbol, as_of_date) 缓存，避免重复计算 IV Rank 等昂贵操作。

        Args:
            symbol: 股票代码

        Returns:
            StockVolatility 对象或 None
        """
        symbol = symbol.upper()

        # 检查缓存
        cache_key = (symbol, self._as_of_date)
        if cache_key in self._stock_volatility_cache:
            return self._stock_volatility_cache[cache_key]

        # 1. 计算 60 日历史波动率
        hv = self._calculate_historical_volatility(symbol, lookback_days=60)
        if hv is None:
            logger.debug(f"Cannot calculate HV for {symbol}, insufficient data")
            self._stock_volatility_cache[cache_key] = None
            return None

        # 2. 获取 ATM 期权的 IV
        iv = self._get_atm_implied_volatility(symbol)

        # 3. 计算 IV Rank 和 IV Percentile
        iv_rank = None
        iv_percentile = None
        if iv is not None:
            iv_rank, iv_percentile = self._calculate_iv_rank(symbol, iv)

        result = StockVolatility(
            symbol=symbol,
            timestamp=datetime.combine(self._as_of_date, datetime.min.time()),
            iv=iv,
            hv=hv,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            pcr=None,  # 需要成交量数据计算
            source="duckdb",
        )
        self._stock_volatility_cache[cache_key] = result
        return result

    def _calculate_historical_volatility(
        self,
        symbol: str,
        lookback_days: int = 20,
    ) -> float | None:
        """计算历史波动率 (年化)

        使用最近 N 天的收盘价计算日收益率标准差，再年化。
        利用 kline 全序列缓存，避免重复查询 DuckDB。

        Args:
            symbol: 股票代码
            lookback_days: 回溯天数 (默认 20)

        Returns:
            年化历史波动率 (小数形式) 或 None
        """
        # 确保 kline 缓存已加载
        if symbol not in self._kline_series_cache:
            self._kline_series_cache[symbol] = self._load_full_kline_series(symbol)

        series = self._kline_series_cache[symbol]
        if not series:
            return None

        try:
            # 过滤 <= as_of_date 的数据 (series 已按日期升序)
            eligible = [row for row in series if row[0] <= self._as_of_date]

            if len(eligible) < lookback_days + 1:
                logger.debug(f"Not enough data for HV calculation: got {len(eligible)}, need {lookback_days + 1}")
                return None

            # 取最近 N+1 天的收盘价 (close 在 index 4)
            closes = [row[4] for row in eligible[-(lookback_days + 1):]]

            # 计算日收益率
            returns = np.diff(np.log(closes))

            # 年化波动率 (假设 252 个交易日)
            hv = float(np.std(returns) * np.sqrt(252))
            return hv

        except Exception as e:
            logger.error(f"Failed to calculate HV for {symbol}: {e}")
            return None

    def _get_atm_implied_volatility(self, symbol: str) -> float | None:
        """获取 ATM 期权的平均隐含波动率

        找到接近当前股价的期权 (moneyness 0.95-1.05)，计算平均 IV。

        Args:
            symbol: 股票代码

        Returns:
            平均 IV (小数形式) 或 None
        """
        # 获取当前股价
        stock_quote = self.get_stock_quote(symbol)
        if stock_quote is None:
            return None

        underlying_price = stock_quote.close

        # 查找期权数据
        option_dir = self._data_dir / "option_daily" / symbol
        if not option_dir.exists():
            return None

        # 确定 Parquet 文件
        year = self._as_of_date.year
        parquet_file = option_dir / f"{year}.parquet"
        if not parquet_file.exists():
            parquet_files = list(option_dir.glob("*.parquet"))
            if not parquet_files:
                return None
            parquet_file = parquet_files[0]

        try:
            conn = self._get_conn()

            # ATM 范围: strike 在 underlying_price 的 95%-105% 之间
            strike_low = underlying_price * 0.95
            strike_high = underlying_price * 1.05

            rows = conn.execute(
                f"""
                SELECT implied_vol
                FROM read_parquet('{parquet_file}')
                WHERE date = ?
                  AND strike >= ?
                  AND strike <= ?
                  AND implied_vol > 0
                  AND implied_vol < 5
                """,
                [self._as_of_date, strike_low, strike_high],
            ).fetchall()

            if not rows:
                return None

            # 计算平均 IV
            ivs = [row[0] for row in rows if row[0] is not None]
            if not ivs:
                return None

            return float(np.mean(ivs))

        except Exception as e:
            logger.error(f"Failed to get ATM IV for {symbol}: {e}")
            return None

    def _calculate_iv_rank(
        self,
        symbol: str,
        current_iv: float,
        lookback_days: int = 252,
    ) -> tuple[float | None, float | None]:
        """计算 IV Rank 和 IV Percentile

        基于标的股票的每日 ATM IV 历史计算:
        - IV Rank = (current - min) / (max - min) * 100
        - IV Percentile = 过去 N 天中 IV < current 的天数占比 * 100

        使用 underlying_price 列让每天的 ATM 范围基于当天实际股价。

        Args:
            symbol: 股票代码
            current_iv: 当前 IV (小数形式)
            lookback_days: 回溯天数 (默认 252)

        Returns:
            (iv_rank, iv_percentile) 元组，不可用时返回 (None, None)
        """
        option_dir = self._data_dir / "option_daily" / symbol
        if not option_dir.exists():
            return None, None

        parquet_files = sorted(option_dir.glob("*.parquet"))
        if not parquet_files:
            return None, None

        try:
            conn = self._get_conn()
            from datetime import timedelta

            lookback_start = self._as_of_date - timedelta(days=int(lookback_days * 1.5))

            # 从所有相关 parquet 文件查询，用 underlying_price 动态计算每天的 ATM 范围
            union_parts = []
            for pf in parquet_files:
                union_parts.append(
                    f"SELECT date, implied_vol FROM read_parquet('{pf}') "
                    f"WHERE date >= '{lookback_start}' AND date < '{self._as_of_date}' "
                    f"AND strike >= underlying_price * 0.95 "
                    f"AND strike <= underlying_price * 1.05 "
                    f"AND implied_vol > 0 AND implied_vol < 5"
                )

            if not union_parts:
                return None, None

            union_sql = " UNION ALL ".join(union_parts)
            rows = conn.execute(
                f"SELECT date, MEDIAN(implied_vol) as daily_iv "
                f"FROM ({union_sql}) "
                f"GROUP BY date ORDER BY date"
            ).fetchall()

            if len(rows) < 20:
                logger.debug(
                    f"Not enough IV history for {symbol}: {len(rows)} days, need >= 20"
                )
                return None, None

            historical_ivs = [row[1] for row in rows if row[1] is not None]
            if len(historical_ivs) < 20:
                return None, None

            iv_min = min(historical_ivs)
            iv_max = max(historical_ivs)

            # IV Rank
            iv_rank = None
            if iv_max > iv_min:
                iv_rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
                iv_rank = max(0.0, min(100.0, iv_rank))

            # IV Percentile
            lower_count = sum(1 for h in historical_ivs if h < current_iv)
            iv_percentile = lower_count / len(historical_ivs) * 100

            return iv_rank, iv_percentile

        except Exception as e:
            logger.debug(f"Failed to calculate IV rank for {symbol}: {e}")
            return None, None
