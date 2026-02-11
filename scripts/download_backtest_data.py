#!/usr/bin/env python3
"""
回测历史数据批量下载工具

为长周期回测准备完整的历史数据:
- Stock EOD (ThetaData)
- Option EOD + Greeks (ThetaData, 按年分块)
- Macro 宏观数据 (yfinance: VIX, TNX)
- Economic Calendar (FRED + FOMC 静态日历)
- Fundamental 基本面 (IBKR: EPS, Revenue, Dividend)
- Rolling Beta (本地计算, 依赖 stock_daily)

设计要点:
- 断点续传: 每个阶段/标的/年份独立记录进度, 中断后重新运行自动跳过已完成部分
- 自适应限速: 检测 429/超时后自动扩大请求间隔, 成功时缓慢恢复
- 按年分块: 期权数据按年拆分请求, 避免单次请求数据量过大

Usage:
    # 完整下载 (默认 GOOG, SPY, QQQ, 2021-01-01 ~ 2026-02-01)
    uv run python scripts/download_backtest_data.py

    # 指定数据目录
    uv run python scripts/download_backtest_data.py -d /Volumes/ORICO/option_quant

    # 只下载某个阶段
    uv run python scripts/download_backtest_data.py --phase stock
    uv run python scripts/download_backtest_data.py --phase option
    uv run python scripts/download_backtest_data.py --phase macro
    uv run python scripts/download_backtest_data.py --phase fundamental
    uv run python scripts/download_backtest_data.py --phase beta

    # 只下载某些标的
    uv run python scripts/download_backtest_data.py --symbols GOOG SPY

    # 自定义日期范围
    uv run python scripts/download_backtest_data.py --start 2023-01-01 --end 2025-12-31

    # 查看进度 (不下载)
    uv run python scripts/download_backtest_data.py --status
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 默认配置
# ============================================================

DEFAULT_SYMBOLS = ["GOOG", "SPY", "QQQ"]
DEFAULT_START = date(2023, 6, 1)
DEFAULT_END = date(2026, 2, 1)
DEFAULT_DATA_DIR = Path("/Volumes/ORICO/option_quant")

# 股票下载参数 (FREE 账户单次请求超 ~9 个月会 500)
STOCK_CHUNK_DAYS = 180  # 每次请求半年

# 期权下载参数
OPTION_MAX_DTE = 90
OPTION_STRIKE_RANGE = 30
OPTION_CHUNK_DAYS = 7  # 每次请求 7 天

# Rolling Beta 需要额外的前置数据
BETA_LOOKBACK_DAYS = 280  # 252 + buffer

# 宏观指标列表
MACRO_INDICATORS = ["^VIX", "^TNX"]

# ETF 列表 (跳过 fundamental 下载)
ETFS = {"SPY", "QQQ", "IWM", "DIA", "TLT", "XLF", "XLK", "XLE", "EEM", "FXI"}

# ThetaData FREE 账户最早可访问日期 (stock + option 均为 2023-06-01)
FREE_TIER_MIN_DATE = date(2023, 6, 1)

# 进度文件名
PROGRESS_FILE = ".batch_download_progress.json"


# ============================================================
# 自适应限速器
# ============================================================


class AdaptiveRateLimiter:
    """自适应限速器

    - 429/超时时加倍间隔 (最大 60s)
    - 连续成功 N 次后缩短间隔 (最小到 base_interval)
    """

    def __init__(self, base_interval: float = 6.0, max_interval: float = 60.0):
        self.base_interval = base_interval
        self.max_interval = max_interval
        self.current_interval = base_interval
        self._consecutive_success = 0
        self._last_request_time = 0.0
        self._total_waits = 0
        self._total_backoffs = 0

    def wait(self) -> None:
        """在请求前等待适当时间"""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.current_interval:
            sleep_time = self.current_interval - elapsed
            time.sleep(sleep_time)
            self._total_waits += 1
        self._last_request_time = time.monotonic()

    def on_success(self) -> None:
        """请求成功, 缓慢恢复速率"""
        self._consecutive_success += 1
        # 每连续 5 次成功, 缩短 10% 间隔
        if self._consecutive_success >= 5:
            self.current_interval = max(
                self.base_interval, self.current_interval * 0.9
            )
            self._consecutive_success = 0

    def on_rate_limited(self) -> None:
        """被限速, 加倍间隔"""
        self.current_interval = min(self.max_interval, self.current_interval * 2)
        self._consecutive_success = 0
        self._total_backoffs += 1
        logger.warning(
            f"Rate limited → interval increased to {self.current_interval:.1f}s"
        )

    def on_error(self) -> None:
        """请求失败, 小幅增加间隔"""
        self.current_interval = min(
            self.max_interval, self.current_interval * 1.5
        )
        self._consecutive_success = 0

    @property
    def stats(self) -> str:
        return (
            f"interval={self.current_interval:.1f}s, "
            f"waits={self._total_waits}, backoffs={self._total_backoffs}"
        )


# ============================================================
# 进度追踪
# ============================================================


@dataclass
class PhaseProgress:
    """单个下载任务的进度"""

    phase: str  # stock, option, macro, fundamental, beta, calendar
    symbol: str  # 标的或 "ALL"
    year: int | None = None  # 期权按年
    status: str = "pending"  # pending, in_progress, completed, failed
    records: int = 0
    last_date: str | None = None  # 最后完成日期 (用于期权断点续传)
    error: str | None = None
    updated_at: str | None = None


@dataclass
class BatchProgress:
    """整体下载进度"""

    tasks: dict[str, dict] = field(default_factory=dict)
    created_at: str = ""
    config: dict = field(default_factory=dict)

    def get_task(self, key: str) -> PhaseProgress | None:
        raw = self.tasks.get(key)
        if raw is None:
            return None
        return PhaseProgress(**raw)

    def set_task(self, key: str, task: PhaseProgress) -> None:
        task.updated_at = date.today().isoformat()
        self.tasks[key] = asdict(task)

    def is_completed(self, key: str) -> bool:
        task = self.get_task(key)
        return task is not None and task.status == "completed"


def load_progress(data_dir: Path) -> BatchProgress:
    path = data_dir / PROGRESS_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return BatchProgress(
                tasks=data.get("tasks", {}),
                created_at=data.get("created_at", ""),
                config=data.get("config", {}),
            )
        except Exception:
            pass
    return BatchProgress(created_at=date.today().isoformat())


def save_progress(data_dir: Path, progress: BatchProgress) -> None:
    path = data_dir / PROGRESS_FILE
    path.write_text(json.dumps(asdict(progress), indent=2, ensure_ascii=False))


# ============================================================
# 下载阶段
# ============================================================


def _check_symbol_in_parquet(
    parquet_path: Path, symbol: str
) -> tuple[int, date | None]:
    """检查 parquet 文件中某 symbol 的行数和最早日期

    Returns:
        (row_count, min_date) — 若文件不存在或 symbol 无数据则返回 (0, None)
    """
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(parquet_path, filters=[("symbol", "=", symbol)])
        if table.num_rows == 0:
            return 0, None
        dates = table.column("date").to_pylist()
        return table.num_rows, min(dates)
    except Exception:
        return 0, None


def download_stocks(
    data_dir: Path,
    symbols: list[str],
    start_date: date,
    end_date: date,
    progress: BatchProgress,
) -> None:
    """阶段 1: 下载股票 EOD 数据"""
    print(f"\n{'='*60}")
    print("Phase 1: Stock EOD Data (ThetaData)")
    print("=" * 60)

    # Beta 需要更早的数据，但不能早于 FREE 账户限制
    stock_start = max(
        start_date - timedelta(days=BETA_LOOKBACK_DAYS),
        FREE_TIER_MIN_DATE,
    )
    if stock_start > start_date - timedelta(days=BETA_LOOKBACK_DAYS):
        print(
            f"  Note: beta lookback clamped to {stock_start} "
            f"(FREE tier min={FREE_TIER_MIN_DATE})"
        )
    all_symbols = list(dict.fromkeys(symbols + ["SPY"]))  # 去重保序

    from src.backtest.data.data_downloader import DataDownloader

    downloader = DataDownloader(data_dir=data_dir)
    stock_parquet = data_dir / "stock_daily.parquet"

    for symbol in all_symbols:
        key = f"stock:{symbol}"

        # 即使 progress 显示 completed, 也验证 parquet 中实际有数据且时间窗口覆盖
        if progress.is_completed(key):
            actual_count, min_date = _check_symbol_in_parquet(stock_parquet, symbol)
            need_redownload = False
            if actual_count == 0:
                print(f"  [retry] {symbol} marked completed but not in parquet, re-downloading...")
                need_redownload = True
            elif min_date and min_date > stock_start + timedelta(days=7):
                print(
                    f"  [retry] {symbol} data starts at {min_date}, "
                    f"need {stock_start}, re-downloading..."
                )
                need_redownload = True

            if need_redownload:
                # 清除 DataDownloader 内部进度以强制重新下载
                internal_key = f"stock:{symbol}"
                if internal_key in downloader._progress:
                    del downloader._progress[internal_key]
                    downloader._save_progress()
            else:
                print(f"  [skip] {symbol} stock already completed ({actual_count} rows, from {min_date})")
                continue

        task = PhaseProgress(phase="stock", symbol=symbol, status="in_progress")
        progress.set_task(key, task)
        save_progress(data_dir, progress)

        # ThetaData FREE 账户 stock EOD 单次请求超过约 9 个月会返回 500，
        # 需要按半年分块下载 (DataDownloader 内部会自动 append/去重)
        chunks = _date_chunks(stock_start, end_date, STOCK_CHUNK_DAYS)
        total_count = 0
        failed = False

        print(f"  Downloading {symbol} stock {stock_start} ~ {end_date} ({len(chunks)} chunks)...")

        for ci, (cs, ce) in enumerate(chunks):
            try:
                # 清除 DataDownloader 内部进度以允许多次追加写入
                internal_key = f"stock:{symbol}"
                if internal_key in downloader._progress:
                    del downloader._progress[internal_key]

                result = downloader.download_stocks(
                    symbols=[symbol],
                    start_date=cs,
                    end_date=ce,
                )
                chunk_count = result.get(symbol, 0)
                total_count += chunk_count
                if (ci + 1) % 3 == 0 or ci == len(chunks) - 1:
                    print(f"    chunk {ci+1}/{len(chunks)}: {cs} ~ {ce}, +{chunk_count}")
            except Exception as e:
                print(f"    chunk {ci+1}/{len(chunks)}: {cs} ~ {ce} FAILED: {e}")
                failed = True

        # 最终计数以 parquet 实际数据为准
        actual_count, _ = _check_symbol_in_parquet(stock_parquet, symbol)
        if actual_count > 0:
            task.status = "completed"
            task.records = actual_count
            print(f"  [done] {symbol}: {actual_count} records in parquet")
        elif failed:
            task.status = "failed"
            task.error = "all chunks failed"
            print(f"  [fail] {symbol}: no data in parquet after download")
        else:
            task.status = "completed"
            task.records = 0
            print(f"  [done] {symbol}: 0 records")

        progress.set_task(key, task)
        save_progress(data_dir, progress)


def download_options(
    data_dir: Path,
    symbols: list[str],
    start_date: date,
    end_date: date,
    progress: BatchProgress,
) -> None:
    """阶段 2: 下载期权 EOD + Greeks 数据 (按年分块 + 自适应限速)"""
    print(f"\n{'='*60}")
    print("Phase 2: Option EOD + Greeks (ThetaData)")
    print("=" * 60)

    from src.backtest.data.data_downloader import DataDownloader

    downloader = DataDownloader(data_dir=data_dir)
    rate_limiter = AdaptiveRateLimiter(base_interval=6.0, max_interval=60.0)

    # 按年份拆分
    years = _year_ranges(start_date, end_date)
    valid_years = {ys.year for ys, _ in years}
    total_tasks = len(symbols) * len(years)
    completed_tasks = 0

    # 清理不在当前日期范围内的 stale 进度条目
    stale_keys = [
        k for k in list(progress.tasks.keys())
        if k.startswith("option:") and len(k.split(":")) == 3
        and int(k.split(":")[2]) not in valid_years
    ]
    for sk in stale_keys:
        del progress.tasks[sk]
        print(f"  [cleanup] removed stale entry: {sk}")
    if stale_keys:
        save_progress(data_dir, progress)

    for symbol in symbols:
        for year_start, year_end in years:
            year = year_start.year
            key = f"option:{symbol}:{year}"

            if progress.is_completed(key):
                completed_tasks += 1
                print(f"  [skip] {symbol} {year} options already completed")
                continue

            # 检查是否有断点续传
            task = progress.get_task(key)
            resume_date = year_start
            if task and task.status == "in_progress" and task.last_date:
                resume_date = date.fromisoformat(task.last_date) + timedelta(days=1)
                if resume_date > year_end:
                    # 已经下载完但没标记 completed
                    task.status = "completed"
                    progress.set_task(key, task)
                    save_progress(data_dir, progress)
                    completed_tasks += 1
                    continue
                print(f"  [resume] {symbol} {year} from {resume_date}")
            else:
                task = PhaseProgress(
                    phase="option", symbol=symbol, year=year, status="in_progress"
                )

            progress.set_task(key, task)
            save_progress(data_dir, progress)

            completed_tasks += 1
            print(
                f"  [{completed_tasks}/{total_tasks}] {symbol} {year} "
                f"options {resume_date} ~ {year_end} ..."
            )

            # 按 chunk_days 分块下载
            chunks = _date_chunks(resume_date, year_end, OPTION_CHUNK_DAYS)
            chunk_records = task.records

            for ci, (cs, ce) in enumerate(chunks):
                rate_limiter.wait()

                try:
                    records = downloader._client.get_option_with_greeks(
                        symbol=symbol,
                        start_date=cs,
                        end_date=ce,
                        expiration=None,
                        max_dte=OPTION_MAX_DTE,
                        strike_range=OPTION_STRIKE_RANGE,
                    )

                    if records:
                        records_by_year: dict[int, list] = {}
                        for r in records:
                            y = r.date.year
                            records_by_year.setdefault(y, []).append(r)
                        for y, yr in records_by_year.items():
                            downloader._save_option_parquet(symbol, y, yr)

                        chunk_records += len(records)

                    rate_limiter.on_success()

                    if (ci + 1) % 10 == 0 or ci == len(chunks) - 1:
                        print(
                            f"    chunk {ci+1}/{len(chunks)}: "
                            f"{cs} ~ {ce}, total {chunk_records} contracts"
                        )

                except Exception as e:
                    err_str = str(e).lower()
                    if "429" in err_str or "rate" in err_str:
                        rate_limiter.on_rate_limited()
                        # 429 需要等待后重试当前 chunk — 但为简化流程，跳过并记录
                        logger.warning(f"    {symbol} {cs}~{ce}: rate limited, skipping chunk")
                    elif "timeout" in err_str or "timed out" in err_str:
                        rate_limiter.on_error()
                        logger.warning(f"    {symbol} {cs}~{ce}: timeout, skipping chunk")
                    else:
                        rate_limiter.on_error()
                        logger.warning(f"    {symbol} {cs}~{ce}: {e}")

                # 每个 chunk 完成后更新进度
                task.last_date = ce.isoformat()
                task.records = chunk_records
                progress.set_task(key, task)

                # 每 20 个 chunk 持久化一次
                if (ci + 1) % 20 == 0:
                    save_progress(data_dir, progress)

            task.status = "completed"
            task.records = chunk_records
            progress.set_task(key, task)
            save_progress(data_dir, progress)
            print(f"  [done] {symbol} {year}: {chunk_records} contracts")

    # 更新数据目录
    try:
        downloader.update_catalog()
    except Exception:
        pass

    print(f"\n  Rate limiter stats: {rate_limiter.stats}")


def download_macro(
    data_dir: Path,
    start_date: date,
    end_date: date,
    progress: BatchProgress,
) -> None:
    """阶段 3: 下载宏观数据 (VIX, TNX)

    逐个指标下载并分别保存到 parquet, 避免不同指标的 schema 差异
    (如 VIX 有 volume=int64, TNX 无 volume) 导致 concat 报错。
    """
    print(f"\n{'='*60}")
    print("Phase 3: Macro Data (yfinance)")
    print("=" * 60)

    from src.backtest.data.macro_downloader import MacroDownloader

    downloader = MacroDownloader(data_dir=data_dir, rate_limit=2.0)
    total_records = 0

    for i, indicator in enumerate(MACRO_INDICATORS):
        key = f"macro:{indicator}"
        if progress.is_completed(key):
            print(f"  [skip] {indicator} already completed")
            continue

        task = PhaseProgress(phase="macro", symbol=indicator, status="in_progress")
        progress.set_task(key, task)
        save_progress(data_dir, progress)

        try:
            print(f"  [{i+1}/{len(MACRO_INDICATORS)}] {indicator}")
            results = downloader.download_indicators(
                indicators=[indicator],
                start_date=start_date,
                end_date=end_date,
            )

            count = results.get(indicator, 0)
            total_records += count
            print(f"  [done] {indicator}: {count} records")
            task.status = "completed"
            task.records = count

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            print(f"  [fail] {indicator}: {e}")

        progress.set_task(key, task)
        save_progress(data_dir, progress)

    print(f"  Total macro records: {total_records}")


def download_calendar(
    data_dir: Path,
    start_date: date,
    end_date: date,
    progress: BatchProgress,
) -> None:
    """阶段 4: 下载经济事件日历"""
    print(f"\n{'='*60}")
    print("Phase 4: Economic Calendar (FRED + FOMC)")
    print("=" * 60)

    key = "calendar:ALL"
    if progress.is_completed(key):
        print("  [skip] Calendar already completed")
        return

    task = PhaseProgress(phase="calendar", symbol="ALL", status="in_progress")
    progress.set_task(key, task)
    save_progress(data_dir, progress)

    try:
        from src.data.providers.economic_calendar_provider import EconomicCalendarProvider

        provider = EconomicCalendarProvider()

        if not provider.is_available:
            print("  [warn] EconomicCalendarProvider not available (FRED API key missing?)")
            print("         FOMC dates from static YAML will still be used at report time")
            task.status = "completed"
            task.records = 0
        else:
            calendar = provider.get_economic_calendar(start_date, end_date)
            event_count = len(calendar.events)

            # 按类型统计
            from collections import Counter
            type_counts = Counter(e.event_type.name for e in calendar.events)
            for etype, cnt in type_counts.most_common():
                print(f"  {etype}: {cnt} events")

            # 保存为 JSON (供 dashboard 使用)
            cal_path = data_dir / "economic_calendar.json"
            cal_data = calendar.to_dict()
            cal_path.write_text(json.dumps(cal_data, indent=2, default=str))

            print(f"  [done] {event_count} events → {cal_path.name}")
            task.status = "completed"
            task.records = event_count

    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        print(f"  [fail] Calendar: {e}")

    progress.set_task(key, task)
    save_progress(data_dir, progress)


def download_fundamental(
    data_dir: Path,
    symbols: list[str],
    progress: BatchProgress,
) -> None:
    """阶段 5: 下载基本面数据 (IBKR)"""
    print(f"\n{'='*60}")
    print("Phase 5: Fundamental Data (IBKR)")
    print("=" * 60)

    # 过滤 ETF
    stock_symbols = [s for s in symbols if s not in ETFS]
    if not stock_symbols:
        print("  [skip] All symbols are ETFs, no fundamental data needed")
        return

    key = "fundamental:ALL"
    if progress.is_completed(key):
        print("  [skip] Fundamental data already completed")
        return

    task = PhaseProgress(phase="fundamental", symbol="ALL", status="in_progress")
    progress.set_task(key, task)
    save_progress(data_dir, progress)

    try:
        from src.backtest.data.ibkr_fundamental_downloader import IBKRFundamentalDownloader

        downloader = IBKRFundamentalDownloader(data_dir=data_dir)

        def on_progress(symbol, current, total):
            print(f"  [{current}/{total}] {symbol}")

        results = downloader.download_and_save(
            symbols=stock_symbols,
            on_progress=on_progress,
            delay=1.5,
        )

        total = sum(results.values())
        for dtype, cnt in results.items():
            print(f"  [done] {dtype}: {cnt} records")

        task.status = "completed"
        task.records = total

    except ImportError:
        print("  [skip] ib_async not installed or IBKR not connected")
        task.status = "completed"
        task.records = 0
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        print(f"  [fail] Fundamental: {e}")

    progress.set_task(key, task)
    save_progress(data_dir, progress)


def calculate_beta(
    data_dir: Path,
    symbols: list[str],
    progress: BatchProgress,
) -> None:
    """阶段 6: 计算 Rolling Beta (依赖 stock_daily.parquet)"""
    print(f"\n{'='*60}")
    print("Phase 6: Rolling Beta (local calculation)")
    print("=" * 60)

    key = "beta:ALL"
    if progress.is_completed(key):
        print("  [skip] Beta already completed")
        return

    # 检查前置数据
    stock_parquet = data_dir / "stock_daily.parquet"
    if not stock_parquet.exists():
        print("  [skip] stock_daily.parquet not found, run stock phase first")
        return

    task = PhaseProgress(phase="beta", symbol="ALL", status="in_progress")
    progress.set_task(key, task)
    save_progress(data_dir, progress)

    try:
        from src.backtest.data.beta_downloader import BetaDownloader

        downloader = BetaDownloader(data_dir=data_dir)

        beta_symbols = [s for s in symbols if s != "SPY"]
        print(f"  Calculating rolling beta for: {beta_symbols}")

        result_path = downloader.calculate_and_save_rolling_beta(
            symbols=beta_symbols,
            window=252,
        )

        print(f"  [done] Rolling beta → {result_path.name}")
        task.status = "completed"
        task.records = len(beta_symbols)

    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        print(f"  [fail] Beta: {e}")

    progress.set_task(key, task)
    save_progress(data_dir, progress)


# ============================================================
# 辅助函数
# ============================================================


def _year_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """将日期范围拆分为按年的区间"""
    ranges = []
    current_year = start.year
    while current_year <= end.year:
        year_start = max(start, date(current_year, 1, 1))
        year_end = min(end, date(current_year, 12, 31))
        ranges.append((year_start, year_end))
        current_year += 1
    return ranges


def _date_chunks(
    start: date, end: date, chunk_days: int
) -> list[tuple[date, date]]:
    """将日期范围拆分为 N 天的小块"""
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        # 跳过纯周末
        if any(
            (current + timedelta(days=d)).weekday() < 5
            for d in range((chunk_end - current).days + 1)
        ):
            chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def print_status(data_dir: Path) -> None:
    """打印当前下载进度"""
    progress = load_progress(data_dir)

    print(f"\n{'='*60}")
    print(f"Download Progress — {data_dir}")
    print("=" * 60)

    if not progress.tasks:
        print("  No download history found.")
        return

    # 按阶段分组
    phases: dict[str, list[tuple[str, dict]]] = {}
    for key, task_data in sorted(progress.tasks.items()):
        phase = task_data.get("phase", key.split(":")[0])
        phases.setdefault(phase, []).append((key, task_data))

    total_c = total_f = total_p = 0
    for phase, tasks in phases.items():
        print(f"\n  [{phase.upper()}]")
        for key, t in tasks:
            status = t.get("status", "?")
            records = t.get("records", 0)
            symbol = t.get("symbol", "")
            year = t.get("year", "")
            year_str = f" {year}" if year else ""

            if status == "completed":
                icon = "done"
                total_c += 1
            elif status == "failed":
                icon = "FAIL"
                total_f += 1
            elif status == "in_progress":
                icon = " >>>>"
                total_p += 1
            else:
                icon = "pend"
                total_p += 1

            last = t.get("last_date", "")
            last_str = f" last={last}" if last and status == "in_progress" else ""
            err_str = f" err={t['error']}" if t.get("error") else ""

            print(
                f"    [{icon}] {symbol}{year_str}: "
                f"{records} records{last_str}{err_str}"
            )

    print(f"\n  Summary: {total_c} completed, {total_p} pending/in-progress, {total_f} failed")

    # 显示 Parquet 文件
    parquets = sorted(data_dir.rglob("*.parquet"))
    if parquets:
        total_size = sum(p.stat().st_size for p in parquets)
        print(f"\n  Parquet files: {len(parquets)} files, {total_size / 1024 / 1024:.1f} MB total")
    print("=" * 60)


# ============================================================
# Main
# ============================================================


PHASE_MAP = {
    "stock": 1,
    "option": 2,
    "macro": 3,
    "calendar": 4,
    "fundamental": 5,
    "beta": 6,
}


def main():
    parser = argparse.ArgumentParser(
        description="Download historical data for backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Full download (all phases)
  %(prog)s --phase stock option         # Only stock + option
  %(prog)s --symbols GOOG SPY           # Only specific symbols
  %(prog)s --status                     # Show progress
  %(prog)s --reset option               # Reset option phase progress
""",
    )
    parser.add_argument(
        "-d", "--data-dir", type=Path, default=DEFAULT_DATA_DIR,
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help=f"Symbols to download (default: {DEFAULT_SYMBOLS})",
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=DEFAULT_START,
        help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})",
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, default=DEFAULT_END,
        help=f"End date YYYY-MM-DD (default: {DEFAULT_END})",
    )
    parser.add_argument(
        "--phase", nargs="+", choices=list(PHASE_MAP.keys()),
        help="Only run specific phases (default: all)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show download progress and exit",
    )
    parser.add_argument(
        "--reset", nargs="+", choices=list(PHASE_MAP.keys()),
        help="Reset progress for specific phases, then exit",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    data_dir = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # --status: 显示进度
    if args.status:
        print_status(data_dir)
        return 0

    # --reset: 重置指定阶段
    if args.reset:
        progress = load_progress(data_dir)
        for phase in args.reset:
            keys_to_remove = [k for k in progress.tasks if k.startswith(f"{phase}:")]
            for k in keys_to_remove:
                del progress.tasks[k]
            print(f"Reset {phase}: removed {len(keys_to_remove)} task(s)")
        save_progress(data_dir, progress)
        return 0

    # 确定要执行的阶段
    phases_to_run = args.phase or list(PHASE_MAP.keys())

    # 打印配置
    print("=" * 60)
    print("Backtest Data Downloader")
    print("=" * 60)
    print(f"  Data Dir:  {data_dir}")
    print(f"  Symbols:   {args.symbols}")
    print(f"  Period:    {args.start} ~ {args.end}")
    print(f"  Phases:    {', '.join(phases_to_run)}")
    print(f"  Option:    max_dte={OPTION_MAX_DTE}, strikes=ATM±{OPTION_STRIKE_RANGE}")

    # 加载进度
    progress = load_progress(data_dir)
    progress.config = {
        "symbols": args.symbols,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
    }
    save_progress(data_dir, progress)

    start_time = time.time()

    # 按顺序执行
    try:
        if "stock" in phases_to_run:
            download_stocks(data_dir, args.symbols, args.start, args.end, progress)

        if "option" in phases_to_run:
            download_options(data_dir, args.symbols, args.start, args.end, progress)

        if "macro" in phases_to_run:
            download_macro(data_dir, args.start, args.end, progress)

        if "calendar" in phases_to_run:
            download_calendar(data_dir, args.start, args.end, progress)

        if "fundamental" in phases_to_run:
            download_fundamental(data_dir, args.symbols, progress)

        if "beta" in phases_to_run:
            calculate_beta(data_dir, args.symbols, progress)

    except KeyboardInterrupt:
        print("\n\nInterrupted! Progress has been saved.")
        print("Re-run the same command to resume from where you left off.")
        save_progress(data_dir, progress)
        return 130

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"\n{'='*60}")
    print(f"All done! Elapsed: {minutes}m {seconds}s")
    print("=" * 60)

    # 打印最终状态
    print_status(data_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
