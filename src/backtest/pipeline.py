"""
Backtest Pipeline - 回测管道

从数据收集到可视化的完整回测流程：
1. 数据收集 - 智能增量下载
2. 执行回测 - BacktestExecutor
3. 计算绩效 - BacktestMetrics + BenchmarkComparison
4. 可视化展示 - HTML 报告

Usage:
    from src.backtest import BacktestConfig, BacktestPipeline

    config = BacktestConfig(
        name="MY_BACKTEST",
        start_date=date(2025, 12, 1),
        end_date=date(2026, 2, 1),
        symbols=["GOOG", "SPY"],
    )

    pipeline = BacktestPipeline(config)
    result = pipeline.run()

    print(f"总收益率: {result.metrics.total_return_pct:.2%}")
    print(f"报告: {result.report_path}")
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtest.analysis.metrics import BacktestMetrics
    from src.backtest.engine.backtest_executor import BacktestResult
    from src.backtest.optimization.benchmark import BenchmarkResult

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.data_checker import DataChecker, DataGap

logger = logging.getLogger(__name__)


@dataclass
class DataStatus:
    """数据状态报告"""

    stock_gaps: list[DataGap] = field(default_factory=list)
    option_gaps: list[DataGap] = field(default_factory=list)
    macro_gaps: list[DataGap] = field(default_factory=list)
    beta_missing: list[str] = field(default_factory=list)

    stock_downloaded: dict[str, int] = field(default_factory=dict)
    option_downloaded: dict[str, int] = field(default_factory=dict)
    macro_downloaded: int = 0
    beta_calculated: bool = False

    @property
    def has_gaps(self) -> bool:
        """是否有数据缺口"""
        return bool(
            self.stock_gaps
            or self.option_gaps
            or self.macro_gaps
            or self.beta_missing
        )

    def summary(self) -> str:
        """返回状态摘要"""
        lines = []

        if self.stock_gaps:
            lines.append(f"Stock: {len(self.stock_gaps)} gaps")
        if self.option_gaps:
            lines.append(f"Option: {len(self.option_gaps)} gaps")
        if self.macro_gaps:
            lines.append(f"Macro: {len(self.macro_gaps)} gaps")
        if self.beta_missing:
            lines.append(f"Beta: {len(self.beta_missing)} missing")

        if self.stock_downloaded:
            total = sum(self.stock_downloaded.values())
            lines.append(f"Stock downloaded: {total} records")
        if self.option_downloaded:
            total = sum(self.option_downloaded.values())
            lines.append(f"Option downloaded: {total} records")
        if self.macro_downloaded:
            lines.append(f"Macro downloaded: {self.macro_downloaded} records")
        if self.beta_calculated:
            lines.append("Beta: calculated")

        return "; ".join(lines) if lines else "All data available"


@dataclass
class PipelineResult:
    """Pipeline 执行结果"""

    backtest_result: "BacktestResult"
    metrics: "BacktestMetrics"
    benchmark_result: "BenchmarkResult | None" = None
    report_path: Path | None = None
    data_status: DataStatus = field(default_factory=DataStatus)


class BacktestPipeline:
    """回测 Pipeline

    从数据收集到可视化的完整回测流程。

    Features:
    - 智能增量数据下载（按标的/日期范围）
    - 自动计算绩效指标
    - 与 SPY 基准比较
    - 生成 HTML 报告
    """

    # 滚动 Beta 所需的额外天数 (252 天 + 缓冲)
    BETA_LOOKBACK_DAYS = 280

    # 默认宏观指标
    DEFAULT_MACRO_INDICATORS = ["^VIX", "^TNX"]

    def __init__(
        self,
        config: BacktestConfig,
        ibkr_port: int | None = None,
    ) -> None:
        """初始化 Pipeline

        Args:
            config: 回测配置
            ibkr_port: IBKR TWS/Gateway 端口 (用于基本面数据下载)
        """
        self.config = config
        self._data_dir = Path(config.data_dir)
        self._ibkr_port = ibkr_port

        # 延迟初始化
        self._data_checker: DataChecker | None = None
        self._data_downloader = None
        self._macro_downloader = None
        self._beta_downloader = None

    def run(
        self,
        skip_data_check: bool = False,
        generate_report: bool = True,
        report_dir: Path | str = "reports",
        verbose: bool = False,
    ) -> PipelineResult:
        """运行完整 Pipeline

        Args:
            skip_data_check: 跳过数据检查和下载
            generate_report: 是否生成 HTML 报告
            report_dir: 报告输出目录
            verbose: 详细输出

        Returns:
            PipelineResult
        """
        if verbose:
            logging.getLogger("src.backtest").setLevel(logging.DEBUG)

        logger.info("=" * 60)
        logger.info("Backtest Pipeline Started")
        logger.info("=" * 60)
        logger.info(f"Name: {self.config.name}")
        logger.info(f"Period: {self.config.start_date} ~ {self.config.end_date}")
        logger.info(f"Symbols: {self.config.symbols}")
        logger.info(f"Data Dir: {self._data_dir}")

        # Step 1: 数据收集
        data_status = DataStatus()
        if not skip_data_check:
            logger.info("\n[Step 1/4] Checking and downloading data...")
            data_status = self._ensure_all_data()
            logger.info(f"Data Status: {data_status.summary()}")
        else:
            logger.info("\n[Step 1/4] Skipping data check (--skip-download)")

        # Step 2: 执行回测
        logger.info("\n[Step 2/4] Running backtest...")
        from src.backtest.engine.backtest_executor import BacktestExecutor

        executor = BacktestExecutor(self.config)
        backtest_result = executor.run()
        logger.info(
            f"Backtest completed: {backtest_result.trading_days} days, "
            f"{backtest_result.total_trades} trades"
        )

        # Step 3: 计算绩效
        logger.info("\n[Step 3/4] Calculating metrics...")
        from src.backtest.analysis.metrics import BacktestMetrics

        metrics = BacktestMetrics.from_backtest_result(backtest_result)
        logger.info(f"Total Return: {metrics.total_return_pct:.2%}")
        if metrics.sharpe_ratio:
            logger.info(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
        if metrics.max_drawdown:
            logger.info(f"Max Drawdown: {metrics.max_drawdown:.2%}")

        # Benchmark 比较
        benchmark_result = self._run_benchmark(backtest_result)
        if benchmark_result:
            logger.info(
                f"vs SPY: {benchmark_result.strategy_total_return:.2%} vs "
                f"{benchmark_result.benchmark_total_return:.2%}"
            )

        # Step 4: 生成报告
        report_path = None
        if generate_report:
            logger.info("\n[Step 4/4] Generating report...")
            report_path = self._generate_report(
                backtest_result,
                metrics,
                benchmark_result,
                report_dir,
            )
            logger.info(f"Report: {report_path}")
        else:
            logger.info("\n[Step 4/4] Skipping report generation (--no-report)")

        logger.info("\n" + "=" * 60)
        logger.info("Pipeline Completed")
        logger.info("=" * 60)

        return PipelineResult(
            backtest_result=backtest_result,
            metrics=metrics,
            benchmark_result=benchmark_result,
            report_path=report_path,
            data_status=data_status,
        )

    def _ensure_all_data(self) -> DataStatus:
        """确保所有数据存在，返回状态报告"""
        status = DataStatus()

        # 初始化检查器
        self._data_checker = DataChecker(self._data_dir)

        # 计算所需日期范围
        # 股票数据需要更早的日期用于滚动 Beta 计算
        stock_start = self.config.start_date - timedelta(days=self.BETA_LOOKBACK_DAYS)
        stock_end = self.config.end_date

        # 回测标的 + SPY (用于 Benchmark 和 Beta)
        all_symbols = list(set(self.config.symbols + ["SPY"]))

        # 1. 检查股票数据缺口
        status.stock_gaps = self._data_checker.check_stock_gaps(
            symbols=all_symbols,
            required_start=stock_start,
            required_end=stock_end,
        )

        # 2. 检查期权数据缺口
        status.option_gaps = self._data_checker.check_option_gaps(
            symbols=self.config.symbols,  # 期权只需回测标的
            required_start=self.config.start_date,
            required_end=self.config.end_date,
        )

        # 3. 检查宏观数据缺口
        status.macro_gaps = self._data_checker.check_macro_gaps(
            indicators=self.DEFAULT_MACRO_INDICATORS,
            required_start=self.config.start_date,
            required_end=self.config.end_date,
        )

        # 4. 检查 Beta 数据缺口
        status.beta_missing = self._data_checker.check_beta_gaps(
            symbols=[s for s in all_symbols if s != "SPY"]
        )

        # 下载缺失数据
        if status.stock_gaps:
            status.stock_downloaded = self._download_stocks(status.stock_gaps)

        if status.option_gaps:
            status.option_downloaded = self._download_options(status.option_gaps)

        if status.macro_gaps:
            status.macro_downloaded = self._download_macro(status.macro_gaps)

        if status.beta_missing:
            status.beta_calculated = self._calculate_beta(status.beta_missing)

        return status

    def _download_stocks(self, gaps: list[DataGap]) -> dict[str, int]:
        """下载股票数据"""
        if not gaps:
            return {}

        logger.info(f"Downloading stock data: {len(gaps)} gaps")

        from src.backtest.data.data_downloader import DataDownloader

        if self._data_downloader is None:
            self._data_downloader = DataDownloader(self._data_dir)

        return self._data_downloader.download_stocks_incremental(gaps)

    def _download_options(self, gaps: list[DataGap]) -> dict[str, int]:
        """下载期权数据"""
        if not gaps:
            return {}

        logger.info(f"Downloading option data: {len(gaps)} gaps")

        from src.backtest.data.data_downloader import DataDownloader

        if self._data_downloader is None:
            self._data_downloader = DataDownloader(self._data_dir)

        # 从 config 获取期权筛选参数
        screening = self.config.screening_overrides or {}
        contract_filter = screening.get("contract_filter", {})
        dte_range = contract_filter.get("dte_range", [7, 60])
        max_dte = dte_range[1] if len(dte_range) > 1 else 60

        return self._data_downloader.download_options_incremental(
            gaps,
            max_dte=max_dte,
            strike_range=30,
        )

    def _download_macro(self, gaps: list[DataGap]) -> int:
        """下载宏观数据"""
        if not gaps:
            return 0

        logger.info(f"Downloading macro data: {len(gaps)} gaps")

        try:
            from src.backtest.data.macro_downloader import MacroDownloader

            if self._macro_downloader is None:
                self._macro_downloader = MacroDownloader(self._data_dir)

            # 收集需要下载的指标和日期范围
            indicators = list(set(gap.symbol for gap in gaps))
            min_start = min(gap.missing_start for gap in gaps)
            max_end = max(gap.missing_end for gap in gaps)

            results = self._macro_downloader.download_indicators(
                indicators=indicators,
                start_date=min_start,
                end_date=max_end,
            )

            return sum(results.values())

        except Exception as e:
            logger.warning(f"Failed to download macro data: {e}")
            return 0

    def _calculate_beta(self, symbols: list[str]) -> bool:
        """计算滚动 Beta"""
        if not symbols:
            return False

        logger.info(f"Calculating rolling beta for: {symbols}")

        try:
            from src.backtest.data.beta_downloader import BetaDownloader

            if self._beta_downloader is None:
                self._beta_downloader = BetaDownloader(self._data_dir)

            self._beta_downloader.calculate_and_save_rolling_beta(
                symbols=symbols,
                window=252,
            )
            return True

        except Exception as e:
            logger.warning(f"Failed to calculate beta: {e}")
            return False

    def _run_benchmark(self, result) -> "BenchmarkResult | None":
        """运行 Benchmark 比较"""
        try:
            from src.backtest.data.duckdb_provider import DuckDBProvider
            from src.backtest.optimization.benchmark import BenchmarkComparison

            provider = DuckDBProvider(str(self._data_dir))
            benchmark = BenchmarkComparison(result)
            return benchmark.compare_with_spy(provider)

        except Exception as e:
            logger.warning(f"Failed to run benchmark comparison: {e}")
            return None

    def _generate_report(
        self,
        result,
        metrics,
        benchmark_result,
        report_dir: Path | str,
    ) -> Path:
        """生成 HTML 报告"""
        from src.backtest.visualization.dashboard import BacktestDashboard

        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        dashboard = BacktestDashboard(
            result=result,
            metrics=metrics,
            benchmark_result=benchmark_result,
        )

        # 使用回测名称作为文件名
        report_name = f"{self.config.name.lower().replace(' ', '_')}_report.html"
        report_path = report_dir / report_name

        return dashboard.generate_report(report_path)

    def check_data(self) -> DataStatus:
        """仅检查数据缺口（不下载）

        Returns:
            DataStatus 数据状态报告
        """
        self._data_checker = DataChecker(self._data_dir)

        stock_start = self.config.start_date - timedelta(days=self.BETA_LOOKBACK_DAYS)
        stock_end = self.config.end_date
        all_symbols = list(set(self.config.symbols + ["SPY"]))

        status = DataStatus(
            stock_gaps=self._data_checker.check_stock_gaps(
                all_symbols, stock_start, stock_end
            ),
            option_gaps=self._data_checker.check_option_gaps(
                self.config.symbols, self.config.start_date, self.config.end_date
            ),
            macro_gaps=self._data_checker.check_macro_gaps(
                self.DEFAULT_MACRO_INDICATORS,
                self.config.start_date,
                self.config.end_date,
            ),
            beta_missing=self._data_checker.check_beta_gaps(
                [s for s in all_symbols if s != "SPY"]
            ),
        )

        return status

    def print_data_status(self) -> None:
        """打印数据状态"""
        status = self.check_data()

        print("\n" + "=" * 60)
        print("Data Status Check")
        print("=" * 60)
        print(f"Backtest: {self.config.name}")
        print(f"Period: {self.config.start_date} ~ {self.config.end_date}")
        print(f"Symbols: {self.config.symbols}")
        print()

        if status.stock_gaps:
            print(f"Stock Data Gaps ({len(status.stock_gaps)}):")
            for gap in status.stock_gaps:
                print(f"  - {gap}")
        else:
            print("Stock Data: OK")

        if status.option_gaps:
            print(f"\nOption Data Gaps ({len(status.option_gaps)}):")
            for gap in status.option_gaps:
                print(f"  - {gap}")
        else:
            print("\nOption Data: OK")

        if status.macro_gaps:
            print(f"\nMacro Data Gaps ({len(status.macro_gaps)}):")
            for gap in status.macro_gaps:
                print(f"  - {gap}")
        else:
            print("\nMacro Data: OK")

        if status.beta_missing:
            print(f"\nBeta Missing: {status.beta_missing}")
        else:
            print("\nBeta Data: OK")

        print()
        if status.has_gaps:
            print("Run pipeline to download missing data.")
        else:
            print("All data available. Ready to run backtest.")
        print("=" * 60)
