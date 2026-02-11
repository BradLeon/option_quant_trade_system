"""
Data Checker - 数据缺口检查器

检查回测所需数据的缺口，支持增量下载。

功能:
- 检查股票/期权数据是否存在
- 识别缺失的标的和日期范围
- 返回需要下载的数据缺口列表

Usage:
    checker = DataChecker(data_dir)
    gaps = checker.check_stock_gaps(
        symbols=["GOOG", "AAPL"],
        required_start=date(2024, 1, 1),
        required_end=date(2026, 1, 1),
    )
    # 返回需要下载的缺口列表
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DataGap:
    """数据缺口"""

    symbol: str
    data_type: str  # "stock" | "option"
    missing_start: date
    missing_end: date
    reason: str  # "new_symbol" | "extend_before" | "extend_after"

    def __str__(self) -> str:
        return (
            f"{self.data_type}:{self.symbol} "
            f"{self.missing_start} ~ {self.missing_end} "
            f"({self.reason})"
        )


@dataclass
class DownloadProgress:
    """下载进度记录 (与 data_downloader.py 中的 DownloadProgress 兼容)"""

    symbol: str
    data_type: str
    start_date: date
    end_date: date
    status: str  # pending, in_progress, completed, failed
    last_completed_date: date | None = None
    total_records: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "DownloadProgress":
        return cls(
            symbol=data["symbol"],
            data_type=data["data_type"],
            start_date=date.fromisoformat(data["start_date"]),
            end_date=date.fromisoformat(data["end_date"]),
            status=data.get("status", "pending"),
            last_completed_date=date.fromisoformat(data["last_completed_date"])
            if data.get("last_completed_date")
            else None,
            total_records=data.get("total_records", 0),
        )


class DataChecker:
    """数据缺口检查器

    检查回测所需数据的缺口，支持:
    - 按标的增量: 只下载缺失的 symbol
    - 按日期增量: 只下载缺失的日期范围
    """

    def __init__(self, data_dir: Path | str) -> None:
        """初始化检查器

        Args:
            data_dir: 数据目录
        """
        self._data_dir = Path(data_dir)
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
                logger.debug(f"Loaded {len(self._progress)} progress records")
            except Exception as e:
                logger.warning(f"Failed to load progress file: {e}")
                self._progress = {}

    def check_stock_gaps(
        self,
        symbols: list[str],
        required_start: date,
        required_end: date,
    ) -> list[DataGap]:
        """检查股票数据缺口

        Args:
            symbols: 需要的标的列表
            required_start: 需要的开始日期
            required_end: 需要的结束日期

        Returns:
            数据缺口列表

        示例:
            需要 ["GOOG", "AAPL"], 2024-01-01 ~ 2026-01-01
            现有 ["GOOG"], 2025-01-01 ~ 2026-01-01

            返回:
            - DataGap("AAPL", "stock", 2024-01-01, 2026-01-01, "new_symbol")
            - DataGap("GOOG", "stock", 2024-01-01, 2024-12-31, "extend_before")
        """
        gaps: list[DataGap] = []

        for symbol in symbols:
            key = f"stock:{symbol.upper()}"
            progress = self._progress.get(key)

            if progress is None or progress.status != "completed":
                # 新标的或未完成，需要全量下载
                gaps.append(DataGap(
                    symbol=symbol.upper(),
                    data_type="stock",
                    missing_start=required_start,
                    missing_end=required_end,
                    reason="new_symbol",
                ))
                logger.info(f"Stock {symbol}: new symbol, need full download")
            else:
                # 检查日期范围
                if progress.start_date > required_start:
                    # 需要向前扩展
                    gap_end = progress.start_date - timedelta(days=1)
                    if gap_end >= required_start:
                        gaps.append(DataGap(
                            symbol=symbol.upper(),
                            data_type="stock",
                            missing_start=required_start,
                            missing_end=gap_end,
                            reason="extend_before",
                        ))
                        logger.info(
                            f"Stock {symbol}: extend before "
                            f"{required_start} ~ {gap_end}"
                        )

                if progress.end_date < required_end:
                    # 需要向后扩展
                    gap_start = progress.end_date + timedelta(days=1)
                    if gap_start <= required_end:
                        gaps.append(DataGap(
                            symbol=symbol.upper(),
                            data_type="stock",
                            missing_start=gap_start,
                            missing_end=required_end,
                            reason="extend_after",
                        ))
                        logger.info(
                            f"Stock {symbol}: extend after "
                            f"{gap_start} ~ {required_end}"
                        )

                # 完全覆盖
                if (
                    progress.start_date <= required_start
                    and progress.end_date >= required_end
                ):
                    logger.info(
                        f"Stock {symbol}: fully covered "
                        f"({progress.start_date} ~ {progress.end_date})"
                    )

        return gaps

    def check_option_gaps(
        self,
        symbols: list[str],
        required_start: date,
        required_end: date,
    ) -> list[DataGap]:
        """检查期权数据缺口

        Args:
            symbols: 需要的标的列表
            required_start: 需要的开始日期
            required_end: 需要的结束日期

        Returns:
            数据缺口列表
        """
        gaps: list[DataGap] = []

        for symbol in symbols:
            key = f"option:{symbol.upper()}"
            progress = self._progress.get(key)

            if progress is None or progress.status not in ("completed", "in_progress"):
                # 新标的，需要全量下载
                gaps.append(DataGap(
                    symbol=symbol.upper(),
                    data_type="option",
                    missing_start=required_start,
                    missing_end=required_end,
                    reason="new_symbol",
                ))
                logger.info(f"Option {symbol}: new symbol, need full download")
            elif progress.status == "in_progress" and progress.last_completed_date:
                # 断点续传：从上次完成的日期继续
                gap_start = progress.last_completed_date + timedelta(days=1)
                if gap_start <= required_end:
                    gaps.append(DataGap(
                        symbol=symbol.upper(),
                        data_type="option",
                        missing_start=gap_start,
                        missing_end=required_end,
                        reason="resume",
                    ))
                    logger.info(
                        f"Option {symbol}: resume from {gap_start}"
                    )
            else:
                # completed: 检查日期范围
                if progress.start_date > required_start:
                    gap_end = progress.start_date - timedelta(days=1)
                    if gap_end >= required_start:
                        gaps.append(DataGap(
                            symbol=symbol.upper(),
                            data_type="option",
                            missing_start=required_start,
                            missing_end=gap_end,
                            reason="extend_before",
                        ))
                        logger.info(
                            f"Option {symbol}: extend before "
                            f"{required_start} ~ {gap_end}"
                        )

                if progress.end_date < required_end:
                    gap_start = progress.end_date + timedelta(days=1)
                    if gap_start <= required_end:
                        gaps.append(DataGap(
                            symbol=symbol.upper(),
                            data_type="option",
                            missing_start=gap_start,
                            missing_end=required_end,
                            reason="extend_after",
                        ))
                        logger.info(
                            f"Option {symbol}: extend after "
                            f"{gap_start} ~ {required_end}"
                        )

                if (
                    progress.start_date <= required_start
                    and progress.end_date >= required_end
                ):
                    logger.info(
                        f"Option {symbol}: fully covered "
                        f"({progress.start_date} ~ {progress.end_date})"
                    )

        return gaps

    def check_macro_gaps(
        self,
        indicators: list[str],
        required_start: date,
        required_end: date,
    ) -> list[DataGap]:
        """检查宏观数据缺口

        宏观数据存储在单个文件 macro_daily.parquet 中，
        需要检查每个指标的日期范围。

        Args:
            indicators: 指标列表 (如 ["^VIX", "^TNX"])
            required_start: 需要的开始日期
            required_end: 需要的结束日期

        Returns:
            数据缺口列表
        """
        gaps: list[DataGap] = []
        macro_path = self._data_dir / "macro_daily.parquet"

        if not macro_path.exists():
            # 文件不存在，所有指标都需要下载
            for indicator in indicators:
                gaps.append(DataGap(
                    symbol=indicator,
                    data_type="macro",
                    missing_start=required_start,
                    missing_end=required_end,
                    reason="new_symbol",
                ))
            return gaps

        # 检查每个指标的日期范围
        try:
            import duckdb
            conn = duckdb.connect(":memory:")

            for indicator in indicators:
                result = conn.execute(
                    f"""
                    SELECT MIN(date), MAX(date)
                    FROM read_parquet('{macro_path}')
                    WHERE indicator = ?
                    """,
                    [indicator],
                ).fetchone()

                if result is None or result[0] is None:
                    # 该指标不存在
                    gaps.append(DataGap(
                        symbol=indicator,
                        data_type="macro",
                        missing_start=required_start,
                        missing_end=required_end,
                        reason="new_symbol",
                    ))
                else:
                    existing_start = result[0]
                    existing_end = result[1]

                    if isinstance(existing_start, str):
                        existing_start = date.fromisoformat(existing_start[:10])
                    if isinstance(existing_end, str):
                        existing_end = date.fromisoformat(existing_end[:10])

                    # 检查是否需要扩展
                    if existing_start > required_start:
                        gaps.append(DataGap(
                            symbol=indicator,
                            data_type="macro",
                            missing_start=required_start,
                            missing_end=existing_start - timedelta(days=1),
                            reason="extend_before",
                        ))

                    if existing_end < required_end:
                        gaps.append(DataGap(
                            symbol=indicator,
                            data_type="macro",
                            missing_start=existing_end + timedelta(days=1),
                            missing_end=required_end,
                            reason="extend_after",
                        ))

            conn.close()

        except Exception as e:
            logger.warning(f"Failed to check macro gaps: {e}")
            # 无法检查，假设都需要下载
            for indicator in indicators:
                gaps.append(DataGap(
                    symbol=indicator,
                    data_type="macro",
                    missing_start=required_start,
                    missing_end=required_end,
                    reason="check_failed",
                ))

        return gaps

    def check_beta_gaps(self, symbols: list[str]) -> list[str]:
        """检查 Beta 数据缺口

        Args:
            symbols: 标的列表

        Returns:
            缺失 Beta 的标的列表
        """
        missing: list[str] = []
        beta_path = self._data_dir / "stock_beta_daily.parquet"

        if not beta_path.exists():
            # 静态 Beta 文件检查
            static_beta_path = self._data_dir / "stock_beta.parquet"
            if not static_beta_path.exists():
                return symbols  # 全部缺失

        try:
            import duckdb
            conn = duckdb.connect(":memory:")

            # 优先检查滚动 Beta
            if beta_path.exists():
                result = conn.execute(
                    f"""
                    SELECT DISTINCT symbol
                    FROM read_parquet('{beta_path}')
                    """
                ).fetchall()
                existing = {row[0].upper() for row in result}
            else:
                existing = set()

            for symbol in symbols:
                if symbol.upper() not in existing and symbol.upper() != "SPY":
                    missing.append(symbol.upper())

            conn.close()

        except Exception as e:
            logger.warning(f"Failed to check beta gaps: {e}")
            return [s for s in symbols if s.upper() != "SPY"]

        return missing

    def get_summary(
        self,
        symbols: list[str],
        required_start: date,
        required_end: date,
    ) -> dict[str, list[DataGap]]:
        """获取所有数据类型的缺口汇总

        Args:
            symbols: 标的列表
            required_start: 需要的开始日期
            required_end: 需要的结束日期

        Returns:
            {data_type: [gaps]}
        """
        return {
            "stock": self.check_stock_gaps(symbols, required_start, required_end),
            "option": self.check_option_gaps(symbols, required_start, required_end),
            "macro": self.check_macro_gaps(
                ["^VIX", "^TNX"],
                required_start,
                required_end,
            ),
        }

    def print_summary(
        self,
        symbols: list[str],
        required_start: date,
        required_end: date,
    ) -> None:
        """打印数据缺口汇总"""
        summary = self.get_summary(symbols, required_start, required_end)

        print("\n" + "=" * 60)
        print("Data Gap Summary")
        print("=" * 60)
        print(f"Symbols: {symbols}")
        print(f"Date Range: {required_start} ~ {required_end}")
        print()

        total_gaps = 0
        for data_type, gaps in summary.items():
            if gaps:
                print(f"\n{data_type.upper()} ({len(gaps)} gaps):")
                for gap in gaps:
                    print(f"  - {gap}")
                total_gaps += len(gaps)
            else:
                print(f"\n{data_type.upper()}: OK (fully covered)")

        print()
        if total_gaps == 0:
            print("All data is available.")
        else:
            print(f"Total: {total_gaps} gaps need to be downloaded.")
        print("=" * 60)
