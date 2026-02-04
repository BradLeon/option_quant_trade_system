"""
Macro Data Downloader - 宏观数据下载工具

从 yfinance 下载 VIX、TNX 等宏观指数历史数据并保存为 Parquet 文件。
供 DuckDBProvider 的 get_macro_data() 使用。

支持指标:
- ^VIX: CBOE 波动率指数
- ^VIX3M: CBOE 3个月波动率指数 (VIX 期限结构)
- ^TNX: 10年期美国国债收益率
- ^TYX: 30年期美国国债收益率
- ^IRX: 13周美国国债利率
- ^GSPC: S&P 500 指数
- SPY: S&P 500 ETF

Usage:
    downloader = MacroDownloader(data_dir="/Volumes/TradingData/processed")

    # 下载所有默认指标
    downloader.download_all(date(2015, 1, 1), date(2024, 12, 31))

    # 下载特定指标
    downloader.download_indicators(["^VIX", "^TNX"], date(2015, 1, 1), date(2024, 12, 31))
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


# 默认宏观指标列表
DEFAULT_MACRO_INDICATORS = [
    # 波动率
    "^VIX",      # CBOE Volatility Index
    "^VIX3M",    # CBOE 3-Month Volatility Index
    # 利率
    "^TNX",      # 10-Year Treasury Note Yield
    "^TYX",      # 30-Year Treasury Bond Yield
    "^IRX",      # 13-Week Treasury Bill
    "^FVX",      # 5-Year Treasury Note Yield
    # 主要指数
    "^GSPC",     # S&P 500
    "^DJI",      # Dow Jones Industrial Average
    "^IXIC",     # NASDAQ Composite
    "^RUT",      # Russell 2000
    # ETF 代理
    "SPY",       # S&P 500 ETF
    "QQQ",       # NASDAQ-100 ETF
    "TLT",       # 20+ Year Treasury Bond ETF
]


@dataclass
class MacroEOD:
    """宏观数据 EOD 记录"""
    indicator: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    adj_close: float | None = None


class MacroDownloader:
    """宏观数据下载器

    从 yfinance 下载宏观指数历史数据并保存为 Parquet 文件。

    Features:
    - 支持多种宏观指标 (VIX, TNX, SPY 等)
    - 自动处理 yfinance rate limit
    - 保存为 Parquet 格式供 DuckDBProvider 使用
    """

    def __init__(
        self,
        data_dir: Path | str,
        rate_limit: float = 1.0,
    ) -> None:
        """初始化下载器

        Args:
            data_dir: 数据存储目录
            rate_limit: yfinance 请求间隔（秒）
        """
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._rate_limit = rate_limit

    def _get_parquet_path(self) -> Path:
        """获取宏观数据 Parquet 文件路径"""
        return self._data_dir / "macro_daily.parquet"

    def download_all(
        self,
        start_date: date,
        end_date: date,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, int]:
        """下载所有默认宏观指标

        Args:
            start_date: 开始日期
            end_date: 结束日期
            on_progress: 进度回调 (indicator, current, total)

        Returns:
            {indicator: record_count} 下载记录数
        """
        return self.download_indicators(
            DEFAULT_MACRO_INDICATORS,
            start_date,
            end_date,
            on_progress,
        )

    def download_indicators(
        self,
        indicators: list[str],
        start_date: date,
        end_date: date,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, int]:
        """下载指定宏观指标

        Args:
            indicators: 指标列表 (如 ["^VIX", "^TNX"])
            start_date: 开始日期
            end_date: 结束日期
            on_progress: 进度回调

        Returns:
            {indicator: record_count} 下载记录数
        """
        import time
        import yfinance as yf

        results = {}
        total = len(indicators)
        all_records: list[MacroEOD] = []

        for i, indicator in enumerate(indicators):
            if on_progress:
                on_progress(indicator, i + 1, total)

            try:
                # Rate limiting
                if i > 0:
                    time.sleep(self._rate_limit)

                logger.info(f"Downloading {indicator}...")

                # 使用 yfinance 下载
                ticker = yf.Ticker(indicator)
                hist = ticker.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                    interval="1d",
                )

                if hist.empty:
                    logger.warning(f"No data for {indicator}")
                    results[indicator] = 0
                    continue

                # 转换为 MacroEOD 记录
                records = []
                for timestamp, row in hist.iterrows():
                    record = MacroEOD(
                        indicator=indicator,
                        date=timestamp.date(),
                        open=row["Open"],
                        high=row["High"],
                        low=row["Low"],
                        close=row["Close"],
                        volume=int(row["Volume"]) if row["Volume"] else None,
                        adj_close=row.get("Adj Close"),
                    )
                    records.append(record)

                all_records.extend(records)
                results[indicator] = len(records)
                logger.info(f"Downloaded {len(records)} records for {indicator}")

            except Exception as e:
                logger.error(f"Failed to download {indicator}: {e}")
                results[indicator] = 0

        # 保存所有数据
        if all_records:
            self._save_parquet(all_records)
            logger.info(f"Saved {len(all_records)} total macro records")

        # 更新数据目录
        self._update_catalog()

        return results

    def _update_catalog(self) -> None:
        """更新数据目录（如果 DataDownloader 可用）"""
        try:
            from src.backtest.data.data_downloader import DataDownloader
            downloader = DataDownloader(data_dir=self._data_dir)
            downloader.update_catalog()
        except Exception as e:
            logger.debug(f"Catalog update skipped: {e}")

    def _save_parquet(self, records: list[MacroEOD]) -> None:
        """保存宏观数据为 Parquet

        追加模式：如果文件存在，读取现有数据并合并去重。
        """
        parquet_path = self._get_parquet_path()

        # 转换为 PyArrow Table
        data = {
            "indicator": [r.indicator for r in records],
            "date": [r.date for r in records],
            "open": [r.open for r in records],
            "high": [r.high for r in records],
            "low": [r.low for r in records],
            "close": [r.close for r in records],
            "volume": [r.volume for r in records],
            "adj_close": [r.adj_close for r in records],
        }

        new_table = pa.Table.from_pydict(data)

        # 如果文件存在，合并数据
        if parquet_path.exists():
            existing_table = pq.read_table(parquet_path)
            combined = pa.concat_tables([existing_table, new_table])

            # 去重 (按 indicator, date)
            combined_df = combined.to_pandas()
            combined_df = combined_df.drop_duplicates(
                subset=["indicator", "date"], keep="last"
            )
            combined_df = combined_df.sort_values(["indicator", "date"])
            new_table = pa.Table.from_pandas(combined_df, preserve_index=False)

        pq.write_table(new_table, parquet_path)
        logger.debug(f"Saved macro data to {parquet_path}")

    def get_available_indicators(self) -> list[str]:
        """获取已下载的指标列表"""
        parquet_path = self._get_parquet_path()
        if not parquet_path.exists():
            return []

        try:
            import duckdb
            conn = duckdb.connect(":memory:")
            result = conn.execute(
                f"SELECT DISTINCT indicator FROM read_parquet('{parquet_path}') ORDER BY indicator"
            ).fetchall()
            return [r[0] for r in result]
        except Exception as e:
            logger.error(f"Failed to get available indicators: {e}")
            return []

    def get_date_range(self, indicator: str | None = None) -> tuple[date, date] | None:
        """获取数据的日期范围

        Args:
            indicator: 指定指标，None 表示所有数据

        Returns:
            (start_date, end_date) 或 None
        """
        parquet_path = self._get_parquet_path()
        if not parquet_path.exists():
            return None

        try:
            import duckdb
            conn = duckdb.connect(":memory:")

            if indicator:
                result = conn.execute(
                    f"""
                    SELECT MIN(date), MAX(date)
                    FROM read_parquet('{parquet_path}')
                    WHERE indicator = ?
                    """,
                    [indicator],
                ).fetchone()
            else:
                result = conn.execute(
                    f"SELECT MIN(date), MAX(date) FROM read_parquet('{parquet_path}')"
                ).fetchone()

            if result and result[0] and result[1]:
                return result[0], result[1]
            return None

        except Exception as e:
            logger.error(f"Failed to get date range: {e}")
            return None

    def get_record_count(self, indicator: str | None = None) -> int:
        """获取记录数

        Args:
            indicator: 指定指标，None 表示所有数据

        Returns:
            记录数
        """
        parquet_path = self._get_parquet_path()
        if not parquet_path.exists():
            return 0

        try:
            import duckdb
            conn = duckdb.connect(":memory:")

            if indicator:
                result = conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM read_parquet('{parquet_path}')
                    WHERE indicator = ?
                    """,
                    [indicator],
                ).fetchone()
            else:
                result = conn.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
                ).fetchone()

            return result[0] if result else 0

        except Exception as e:
            logger.error(f"Failed to get record count: {e}")
            return 0
