"""
Data Downloader - 批量数据下载工具

从 ThetaData 下载历史数据并保存为 Parquet 文件。

支持功能:
- 多标的批量下载
- 日期范围分块下载
- 进度追踪和断点续传
- 自动 rate limit 处理

Usage:
    downloader = DataDownloader(
        data_dir="/Volumes/TradingData/processed",
        client=ThetaDataClient(),
    )

    # 下载股票数据
    downloader.download_stocks(["AAPL", "MSFT"], date(2015, 1, 1), date(2024, 12, 31))

    # 下载期权数据
    downloader.download_options(["AAPL"], date(2020, 1, 1), date(2024, 12, 31))
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq

from src.backtest.data.schema import (
    OptionDailySchema,
    StockDailySchema,
    get_parquet_path,
)
from src.backtest.data.thetadata_client import (
    OptionEODGreeks,
    StockEOD,
    ThetaDataClient,
)

logger = logging.getLogger(__name__)


@dataclass
class DownloadProgress:
    """下载进度追踪"""

    symbol: str
    data_type: str  # "stock" or "option"
    start_date: date
    end_date: date
    last_completed_date: date | None = None
    total_records: int = 0
    status: str = "pending"  # pending, in_progress, completed, failed
    error_message: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "data_type": self.data_type,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "last_completed_date": self.last_completed_date.isoformat()
            if self.last_completed_date
            else None,
            "total_records": self.total_records,
            "status": self.status,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DownloadProgress":
        return cls(
            symbol=data["symbol"],
            data_type=data["data_type"],
            start_date=date.fromisoformat(data["start_date"]),
            end_date=date.fromisoformat(data["end_date"]),
            last_completed_date=date.fromisoformat(data["last_completed_date"])
            if data.get("last_completed_date")
            else None,
            total_records=data.get("total_records", 0),
            status=data.get("status", "pending"),
            error_message=data.get("error_message"),
        )


class DataDownloader:
    """批量数据下载器

    从 ThetaData 下载历史数据并保存为 Parquet 文件。

    Features:
    - 多标的批量下载
    - 日期范围分块 (避免单次请求数据量过大)
    - 断点续传 (记录进度)
    - 自动 rate limit 处理
    """

    def __init__(
        self,
        data_dir: Path | str,
        client: ThetaDataClient | None = None,
    ) -> None:
        """初始化下载器

        Args:
            data_dir: 数据存储目录
            client: ThetaData 客户端 (可选)
        """
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._client = client or ThetaDataClient()
        self._progress_file = self._data_dir / ".download_progress.json"
        self._progress: dict[str, DownloadProgress] = {}

        self._load_progress()

    def _load_progress(self) -> None:
        """加载下载进度"""
        if self._progress_file.exists():
            try:
                with open(self._progress_file) as f:
                    data = json.load(f)
                self._progress = {
                    k: DownloadProgress.from_dict(v) for k, v in data.items()
                }
            except Exception as e:
                logger.warning(f"Failed to load progress file: {e}")
                self._progress = {}

    def _save_progress(self) -> None:
        """保存下载进度"""
        try:
            data = {k: v.to_dict() for k, v in self._progress.items()}
            with open(self._progress_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save progress file: {e}")

    def _get_progress_key(self, symbol: str, data_type: str) -> str:
        """生成进度 key"""
        return f"{data_type}:{symbol}"

    # ========== Stock Data Download ==========

    def download_stocks(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, int]:
        """下载股票历史数据

        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            on_progress: 进度回调 (symbol, downloaded, total)

        Returns:
            {symbol: record_count} 下载记录数
        """
        results = {}
        total = len(symbols)

        for i, symbol in enumerate(symbols):
            if on_progress:
                on_progress(symbol, i, total)

            try:
                count = self._download_stock(symbol, start_date, end_date)
                results[symbol] = count
                logger.info(f"Downloaded {count} records for {symbol}")
            except Exception as e:
                logger.error(f"Failed to download {symbol}: {e}")
                results[symbol] = 0

        # 更新数据目录
        self.update_catalog()

        return results

    def _download_stock(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> int:
        """下载单只股票数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            下载的记录数
        """
        progress_key = self._get_progress_key(symbol, "stock")

        # 检查是否有未完成的进度
        progress = self._progress.get(progress_key)
        if progress and progress.status == "completed":
            if progress.start_date <= start_date and progress.end_date >= end_date:
                logger.info(f"Stock {symbol} already downloaded")
                return progress.total_records

        # 初始化进度
        progress = DownloadProgress(
            symbol=symbol,
            data_type="stock",
            start_date=start_date,
            end_date=end_date,
            status="in_progress",
        )
        self._progress[progress_key] = progress
        self._save_progress()

        # 下载数据
        all_records: list[StockEOD] = []

        try:
            # 股票数据量较小，可以一次性请求
            records = self._client.get_stock_eod(symbol, start_date, end_date)
            all_records.extend(records)

            # 保存为 Parquet
            if all_records:
                self._save_stock_parquet(symbol, all_records)

            # 更新进度
            progress.total_records = len(all_records)
            progress.last_completed_date = end_date
            progress.status = "completed"
            self._save_progress()

            return len(all_records)

        except Exception as e:
            progress.status = "failed"
            progress.error_message = str(e)
            self._save_progress()
            raise

    def _save_stock_parquet(self, symbol: str, records: list[StockEOD]) -> None:
        """保存股票数据为 Parquet

        追加模式：如果文件存在，读取现有数据并合并去重。
        """
        parquet_path = get_parquet_path(self._data_dir, "stock")

        # 转换为 PyArrow Table
        data = {
            "symbol": [r.symbol for r in records],
            "date": [r.date for r in records],
            "open": [r.open for r in records],
            "high": [r.high for r in records],
            "low": [r.low for r in records],
            "close": [r.close for r in records],
            "volume": [r.volume for r in records],
            "count": [r.count for r in records],
            "bid": [r.bid for r in records],
            "ask": [r.ask for r in records],
        }

        new_table = pa.Table.from_pydict(data)

        # 如果文件存在，合并数据
        if parquet_path.exists():
            existing_table = pq.read_table(parquet_path)
            combined = pa.concat_tables([existing_table, new_table])

            # 去重 (按 symbol, date)
            # DuckDB 方式去重
            import duckdb

            combined_df = combined.to_pandas()
            combined_df = combined_df.drop_duplicates(
                subset=["symbol", "date"], keep="last"
            )
            combined_df = combined_df.sort_values(["symbol", "date"])
            new_table = pa.Table.from_pandas(combined_df, preserve_index=False)

        pq.write_table(new_table, parquet_path)
        logger.debug(f"Saved stock data to {parquet_path}")

    # ========== Option Data Download ==========

    def download_options(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        max_dte: int = 90,
        strike_range: int = 30,
        chunk_days: int = 7,
        on_progress: Callable[[str, date, int, int], None] | None = None,
    ) -> dict[str, int]:
        """下载期权历史数据

        Args:
            symbols: 标的代码列表
            start_date: 开始日期
            end_date: 结束日期
            max_dte: 最大 DTE 过滤 (默认 60 天)
            strike_range: ATM 上下各 N 个 strikes (默认 30)
            chunk_days: 每次请求的天数 (默认 7，使用 CSV 流式读取)
            on_progress: 进度回调 (symbol, chunk_start, chunk_idx, total_chunks)

        Returns:
            {symbol: record_count} 下载记录数

        Note:
            使用 expiration=* + max_dte + strike_range 约束减少数据量。
            使用 CSV 流式读取处理大数据量，避免 JSON 解析失败。
        """
        results = {}

        for symbol in symbols:
            try:
                count = self._download_option(
                    symbol, start_date, end_date, max_dte, strike_range,
                    chunk_days, on_progress
                )
                results[symbol] = count
                logger.info(f"Downloaded {count} option records for {symbol}")
            except Exception as e:
                logger.error(f"Failed to download options for {symbol}: {e}")
                results[symbol] = 0

        # 更新数据目录
        self.update_catalog()

        return results

    def _is_trading_day(self, d: date) -> bool:
        """检查是否为交易日（排除周末）"""
        return d.weekday() < 5

    def _download_option(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        max_dte: int,
        strike_range: int | None,
        chunk_days: int,
        on_progress: Callable[[str, date, int, int], None] | None = None,
    ) -> int:
        """下载单只标的的期权数据

        使用 CSV 流式读取 + 日期范围分块请求，有效处理大数据量。
        使用 expiration=* + max_dte + strike_range 约束减少数据量。

        Args:
            symbol: 标的代码
            start_date: 开始日期
            end_date: 结束日期
            max_dte: 最大 DTE 过滤
            strike_range: ATM 上下各 N 个 strikes
            chunk_days: 每次请求的天数 (建议 7-14 天)
            on_progress: 进度回调
        """
        progress_key = self._get_progress_key(symbol, "option")

        # 检查是否有未完成的进度
        progress = self._progress.get(progress_key)
        resume_date = start_date

        if progress:
            if progress.status == "completed":
                if progress.start_date <= start_date and progress.end_date >= end_date:
                    logger.info(f"Options for {symbol} already downloaded")
                    return progress.total_records
            elif progress.status == "in_progress" and progress.last_completed_date:
                resume_date = progress.last_completed_date + timedelta(days=1)
                logger.info(f"Resuming {symbol} from {resume_date}")

        # 初始化进度
        if not progress or progress.status != "in_progress":
            progress = DownloadProgress(
                symbol=symbol,
                data_type="option",
                start_date=start_date,
                end_date=end_date,
                status="in_progress",
            )
        self._progress[progress_key] = progress
        self._save_progress()

        # 生成日期分块 (按 chunk_days 分组)
        chunks: list[tuple[date, date]] = []
        current = resume_date
        while current <= end_date:
            chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
            # 跳过纯周末的 chunk
            if self._has_trading_day(current, chunk_end):
                chunks.append((current, chunk_end))
            current = chunk_end + timedelta(days=1)

        if not chunks:
            logger.warning(f"No chunks to download for {resume_date} - {end_date}")
            progress.status = "completed"
            self._save_progress()
            return progress.total_records

        total_records = progress.total_records
        total_chunks = len(chunks)

        try:
            for chunk_idx, (chunk_start, chunk_end) in enumerate(chunks):
                if on_progress:
                    on_progress(symbol, chunk_start, chunk_idx, total_chunks)

                try:
                    # 使用日期范围请求 (CSV 流式读取)
                    records = self._client.get_option_with_greeks(
                        symbol=symbol,
                        start_date=chunk_start,
                        end_date=chunk_end,
                        expiration=None,  # expiration=*
                        max_dte=max_dte,
                        strike_range=strike_range,
                    )

                    if records:
                        # 按年份分组保存
                        records_by_year: dict[int, list] = {}
                        for r in records:
                            year = r.date.year
                            if year not in records_by_year:
                                records_by_year[year] = []
                            records_by_year[year].append(r)

                        for year, year_records in records_by_year.items():
                            self._save_option_parquet(symbol, year, year_records)

                        total_records += len(records)
                        logger.info(
                            f"{symbol} {chunk_start} - {chunk_end}: {len(records)} contracts"
                        )
                    else:
                        logger.debug(f"{symbol} {chunk_start} - {chunk_end}: No data")

                except Exception as e:
                    logger.warning(f"{symbol} {chunk_start} - {chunk_end}: {e}")

                progress.last_completed_date = chunk_end
                progress.total_records = total_records
                self._save_progress()

            progress.status = "completed"
            self._save_progress()
            logger.info(f"{symbol}: Total {total_records} contracts")

            return total_records

        except Exception as e:
            progress.status = "failed"
            progress.error_message = str(e)
            self._save_progress()
            raise

    def _has_trading_day(self, start: date, end: date) -> bool:
        """检查日期范围内是否有交易日"""
        current = start
        while current <= end:
            if self._is_trading_day(current):
                return True
            current += timedelta(days=1)
        return False

    def _save_option_parquet(
        self,
        symbol: str,
        year: int,
        records: list[OptionEODGreeks],
    ) -> None:
        """保存期权数据为 Parquet (按年份分文件)

        追加模式：如果文件存在，读取现有数据并合并去重。
        """
        parquet_path = get_parquet_path(self._data_dir, "option", symbol, year)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)

        # 转换为 PyArrow Table
        data = {
            "symbol": [r.symbol for r in records],
            "expiration": [r.expiration for r in records],
            "strike": [r.strike for r in records],
            "option_type": [r.option_type for r in records],
            "date": [r.date for r in records],
            "open": [r.open for r in records],
            "high": [r.high for r in records],
            "low": [r.low for r in records],
            "close": [r.close for r in records],
            "volume": [r.volume for r in records],
            "count": [r.count for r in records],
            "bid": [r.bid for r in records],
            "ask": [r.ask for r in records],
            "delta": [r.delta for r in records],
            "gamma": [r.gamma for r in records],
            "theta": [r.theta for r in records],
            "vega": [r.vega for r in records],
            "rho": [r.rho for r in records],
            "implied_vol": [r.implied_vol for r in records],
            "underlying_price": [r.underlying_price for r in records],
            "open_interest": [r.open_interest for r in records],
            "iv_error": [r.iv_error for r in records],
        }

        new_table = pa.Table.from_pydict(data)

        # 如果文件存在，合并数据
        if parquet_path.exists():
            existing_table = pq.read_table(parquet_path)
            combined = pa.concat_tables([existing_table, new_table])

            # 去重 (按 symbol, expiration, strike, option_type, date)
            combined_df = combined.to_pandas()
            combined_df = combined_df.drop_duplicates(
                subset=["symbol", "expiration", "strike", "option_type", "date"],
                keep="last",
            )
            combined_df = combined_df.sort_values(
                ["symbol", "date", "expiration", "strike", "option_type"]
            )
            new_table = pa.Table.from_pandas(combined_df, preserve_index=False)

        pq.write_table(new_table, parquet_path)

    # ========== Utility Methods ==========

    def get_download_status(self) -> dict[str, DownloadProgress]:
        """获取所有下载进度"""
        return self._progress.copy()

    def reset_progress(self, symbol: str | None = None, data_type: str | None = None) -> None:
        """重置下载进度

        Args:
            symbol: 重置特定标的 (None 表示全部)
            data_type: 重置特定类型 ("stock" 或 "option")
        """
        if symbol is None and data_type is None:
            self._progress = {}
        else:
            keys_to_remove = []
            for key, progress in self._progress.items():
                if symbol and progress.symbol != symbol:
                    continue
                if data_type and progress.data_type != data_type:
                    continue
                keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._progress[key]

        self._save_progress()

    def get_available_symbols(self) -> list[str]:
        """获取已下载的标的列表"""
        option_dir = self._data_dir / "option_daily"
        if option_dir.exists():
            return [d.name for d in option_dir.iterdir() if d.is_dir()]
        return []

    def get_date_range(self, symbol: str) -> tuple[date, date] | None:
        """获取标的的数据日期范围

        Args:
            symbol: 标的代码

        Returns:
            (start_date, end_date) 或 None
        """
        option_dir = self._data_dir / "option_daily" / symbol.upper()
        if not option_dir.exists():
            return None

        parquet_files = list(option_dir.glob("*.parquet"))
        if not parquet_files:
            return None

        # 读取所有年份的数据，找到日期范围
        all_dates = []
        for pf in parquet_files:
            table = pq.read_table(pf, columns=["date"])
            dates = table["date"].to_pylist()
            all_dates.extend(dates)

        if not all_dates:
            return None

        return min(all_dates), max(all_dates)

    def update_catalog(self) -> dict:
        """更新数据目录文件

        扫描所有 Parquet 文件，生成统一的数据目录。
        保存到 data_catalog.json。

        Returns:
            目录字典
        """
        import duckdb
        from datetime import datetime as dt

        catalog: dict = {
            "updated_at": dt.now().isoformat(),
            "data_dir": str(self._data_dir),
            "datasets": {}
        }

        conn = duckdb.connect(":memory:")

        # 1. Stock Data
        stock_path = self._data_dir / "stock_daily.parquet"
        if stock_path.exists():
            try:
                rows = conn.execute(f"""
                    SELECT symbol,
                           MIN(date) as start_date,
                           MAX(date) as end_date,
                           COUNT(*) as records
                    FROM read_parquet('{stock_path}')
                    GROUP BY symbol
                    ORDER BY symbol
                """).fetchall()

                catalog["datasets"]["stock"] = {
                    "file": "stock_daily.parquet",
                    "symbols": {
                        row[0]: {
                            "start_date": str(row[1]),
                            "end_date": str(row[2]),
                            "records": row[3]
                        }
                        for row in rows
                    }
                }
            except Exception as e:
                logger.warning(f"Failed to scan stock data: {e}")

        # 2. Option Data
        option_dir = self._data_dir / "option_daily"
        if option_dir.exists():
            option_catalog: dict = {"symbols": {}}
            for sym_dir in sorted(option_dir.iterdir()):
                if not sym_dir.is_dir():
                    continue
                files = list(sym_dir.glob("*.parquet"))
                if not files:
                    continue

                try:
                    parquet_list = ", ".join([f"'{f}'" for f in files])
                    result = conn.execute(f"""
                        SELECT MIN(date), MAX(date), COUNT(*)
                        FROM read_parquet([{parquet_list}])
                    """).fetchone()

                    if result:
                        option_catalog["symbols"][sym_dir.name] = {
                            "start_date": str(result[0]),
                            "end_date": str(result[1]),
                            "records": result[2],
                            "files": [f.name for f in files]
                        }
                except Exception as e:
                    logger.warning(f"Failed to scan option data for {sym_dir.name}: {e}")

            if option_catalog["symbols"]:
                catalog["datasets"]["option"] = option_catalog

        # 3. Macro Data
        macro_path = self._data_dir / "macro_daily.parquet"
        if macro_path.exists():
            try:
                rows = conn.execute(f"""
                    SELECT indicator,
                           MIN(date) as start_date,
                           MAX(date) as end_date,
                           COUNT(*) as records
                    FROM read_parquet('{macro_path}')
                    GROUP BY indicator
                    ORDER BY indicator
                """).fetchall()

                catalog["datasets"]["macro"] = {
                    "file": "macro_daily.parquet",
                    "indicators": {
                        row[0]: {
                            "start_date": str(row[1]),
                            "end_date": str(row[2]),
                            "records": row[3]
                        }
                        for row in rows
                    }
                }
            except Exception as e:
                logger.warning(f"Failed to scan macro data: {e}")

        # 4. Fundamental Data
        for data_type in ["eps", "revenue", "dividend"]:
            path = self._data_dir / f"fundamental_{data_type}.parquet"
            if path.exists():
                try:
                    rows = conn.execute(f"""
                        SELECT symbol,
                               MIN(as_of_date) as start_date,
                               MAX(as_of_date) as end_date,
                               COUNT(*) as records
                        FROM read_parquet('{path}')
                        GROUP BY symbol
                        ORDER BY symbol
                    """).fetchall()

                    if f"fundamental_{data_type}" not in catalog["datasets"]:
                        catalog["datasets"][f"fundamental_{data_type}"] = {
                            "file": f"fundamental_{data_type}.parquet",
                            "symbols": {}
                        }

                    for row in rows:
                        catalog["datasets"][f"fundamental_{data_type}"]["symbols"][row[0]] = {
                            "start_date": str(row[1]),
                            "end_date": str(row[2]),
                            "records": row[3]
                        }
                except Exception as e:
                    logger.warning(f"Failed to scan fundamental {data_type} data: {e}")

        # 保存目录文件
        catalog_path = self._data_dir / "data_catalog.json"
        try:
            with open(catalog_path, "w") as f:
                json.dump(catalog, f, indent=2, default=str)
            logger.info(f"Updated data catalog: {catalog_path}")
        except Exception as e:
            logger.warning(f"Failed to save catalog: {e}")

        return catalog

    def print_catalog(self) -> None:
        """打印数据目录摘要"""
        catalog_path = self._data_dir / "data_catalog.json"

        if not catalog_path.exists():
            self.update_catalog()

        try:
            with open(catalog_path) as f:
                catalog = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read catalog: {e}")
            return

        print("=" * 60)
        print(f"📊 Data Catalog (updated: {catalog.get('updated_at', 'N/A')})")
        print("=" * 60)

        datasets = catalog.get("datasets", {})

        # Stock
        if "stock" in datasets:
            print("\n📈 Stock Data:")
            for sym, info in datasets["stock"].get("symbols", {}).items():
                print(f"   {sym}: {info['start_date']} ~ {info['end_date']} ({info['records']} days)")

        # Option
        if "option" in datasets:
            print("\n📊 Option Data:")
            for sym, info in datasets["option"].get("symbols", {}).items():
                print(f"   {sym}: {info['start_date']} ~ {info['end_date']} ({info['records']} records)")

        # Macro
        if "macro" in datasets:
            print("\n🌍 Macro Data:")
            for ind, info in datasets["macro"].get("indicators", {}).items():
                print(f"   {ind}: {info['start_date']} ~ {info['end_date']} ({info['records']} days)")

        # Fundamental
        for data_type in ["eps", "revenue", "dividend"]:
            key = f"fundamental_{data_type}"
            if key in datasets:
                print(f"\n📑 Fundamental {data_type.upper()}:")
                for sym, info in datasets[key].get("symbols", {}).items():
                    print(f"   {sym}: {info['start_date']} ~ {info['end_date']} ({info['records']} records)")

        print("\n" + "=" * 60)

    # ========== Incremental Download Methods ==========

    def download_stocks_incremental(
        self,
        gaps: list,  # list[DataGap] from data_checker
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, int]:
        """根据数据缺口增量下载股票数据

        Args:
            gaps: DataChecker.check_stock_gaps() 返回的缺口列表
            on_progress: 进度回调 (symbol, current, total)

        Returns:
            {symbol: downloaded_records}
        """
        if not gaps:
            logger.info("No stock data gaps to download")
            return {}

        results: dict[str, int] = {}
        total = len(gaps)

        for i, gap in enumerate(gaps):
            if on_progress:
                on_progress(gap.symbol, i, total)

            logger.info(
                f"Downloading stock {gap.symbol} "
                f"{gap.missing_start} ~ {gap.missing_end} ({gap.reason})"
            )

            try:
                # 直接调用底层下载方法（不走进度检查）
                records = self._client.get_stock_eod(
                    gap.symbol,
                    gap.missing_start,
                    gap.missing_end,
                )

                if records:
                    self._save_stock_parquet(gap.symbol, records)
                    count = len(records)
                    results[gap.symbol] = results.get(gap.symbol, 0) + count
                    logger.info(f"Downloaded {count} stock records for {gap.symbol}")

                    # 更新进度（扩展现有范围）
                    self._update_progress_range(
                        gap.symbol,
                        "stock",
                        gap.missing_start,
                        gap.missing_end,
                        count,
                    )

            except Exception as e:
                logger.error(f"Failed to download stock {gap.symbol}: {e}")

        # 更新数据目录
        if results:
            self.update_catalog()

        return results

    def download_options_incremental(
        self,
        gaps: list,  # list[DataGap] from data_checker
        max_dte: int = 90,
        strike_range: int = 30,
        chunk_days: int = 7,
        on_progress: Callable[[str, date, int, int], None] | None = None,
    ) -> dict[str, int]:
        """根据数据缺口增量下载期权数据

        Args:
            gaps: DataChecker.check_option_gaps() 返回的缺口列表
            max_dte: 最大 DTE
            strike_range: ATM 上下各 N 个 strikes
            chunk_days: 每次请求的天数
            on_progress: 进度回调

        Returns:
            {symbol: downloaded_records}
        """
        if not gaps:
            logger.info("No option data gaps to download")
            return {}

        results: dict[str, int] = {}

        for gap in gaps:
            logger.info(
                f"Downloading option {gap.symbol} "
                f"{gap.missing_start} ~ {gap.missing_end} ({gap.reason})"
            )

            try:
                count = self._download_option(
                    gap.symbol,
                    gap.missing_start,
                    gap.missing_end,
                    max_dte,
                    strike_range,
                    chunk_days,
                    on_progress,
                )
                results[gap.symbol] = results.get(gap.symbol, 0) + count
                logger.info(f"Downloaded {count} option records for {gap.symbol}")

            except Exception as e:
                logger.error(f"Failed to download option {gap.symbol}: {e}")

        # 更新数据目录
        if results:
            self.update_catalog()

        return results

    def _update_progress_range(
        self,
        symbol: str,
        data_type: str,
        new_start: date,
        new_end: date,
        records: int,
    ) -> None:
        """更新进度记录的日期范围（扩展模式）

        Args:
            symbol: 标的代码
            data_type: 数据类型
            new_start: 新下载的开始日期
            new_end: 新下载的结束日期
            records: 新下载的记录数
        """
        progress_key = self._get_progress_key(symbol, data_type)
        existing = self._progress.get(progress_key)

        if existing and existing.status == "completed":
            # 扩展现有范围
            updated_start = min(existing.start_date, new_start)
            updated_end = max(existing.end_date, new_end)
            updated_records = existing.total_records + records

            self._progress[progress_key] = DownloadProgress(
                symbol=symbol,
                data_type=data_type,
                start_date=updated_start,
                end_date=updated_end,
                last_completed_date=updated_end,
                total_records=updated_records,
                status="completed",
            )
        else:
            # 创建新记录
            self._progress[progress_key] = DownloadProgress(
                symbol=symbol,
                data_type=data_type,
                start_date=new_start,
                end_date=new_end,
                last_completed_date=new_end,
                total_records=records,
                status="completed",
            )

        self._save_progress()
        logger.debug(
            f"Updated progress for {data_type}:{symbol}: "
            f"{self._progress[progress_key].start_date} ~ "
            f"{self._progress[progress_key].end_date}"
        )
