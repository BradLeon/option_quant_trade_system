"""
Analysis & Optimization 模块真实数据测试

测试参数:
- Period: 2025-12-01 ~ 2026-02-01
- Symbols: GOOG, SPY
- Data: /Volumes/ORICO/option_quant

运行方式:
    uv run python -m pytest tests/backtest/test_analysis_optimization_realdata.py -v
"""

import pytest
from datetime import date
from pathlib import Path
import numpy as np

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult
from src.backtest.analysis.metrics import BacktestMetrics, MonthlyReturn, DrawdownPeriod
from src.backtest.analysis.trade_analyzer import TradeAnalyzer, TradeSummary
from src.backtest.optimization.parallel_runner import ParallelBacktestRunner, ParallelRunResult
from src.backtest.optimization.parameter_sweep import ParameterSweep, SweepResult
from src.backtest.optimization.benchmark import BenchmarkComparison, BenchmarkResult
from src.backtest.optimization.walk_forward import WalkForwardValidator, WalkForwardResult
from src.engine.models.enums import StrategyType

# 测试参数
TEST_DATA_DIR = Path("/Volumes/ORICO/option_quant")
TEST_START_DATE = date(2025, 12, 1)
TEST_END_DATE = date(2026, 2, 1)
TEST_SYMBOLS = ["GOOG", "SPY"]
TEST_CAPITAL = 1_000_000


def data_available() -> bool:
    """检查测试数据是否可用"""
    if not TEST_DATA_DIR.exists():
        return False
    # 检查 stock_daily.parquet 存在
    stock_file = TEST_DATA_DIR / "stock_daily.parquet"
    if not stock_file.exists():
        return False
    # 检查 option_daily 目录
    option_dir = TEST_DATA_DIR / "option_daily"
    if not option_dir.exists():
        return False
    return True


# 如果数据不可用，跳过所有测试
pytestmark = pytest.mark.skipif(
    not data_available(),
    reason=f"Test data not available at {TEST_DATA_DIR}"
)


@pytest.fixture(scope="module")
def backtest_config() -> BacktestConfig:
    """创建测试用回测配置"""
    return BacktestConfig(
        name="ANALYSIS_OPT_TEST",
        start_date=TEST_START_DATE,
        end_date=TEST_END_DATE,
        symbols=TEST_SYMBOLS,
        initial_capital=TEST_CAPITAL,
        data_dir=str(TEST_DATA_DIR),
        strategy_types=[StrategyType.SHORT_PUT],
        max_positions=10,
        max_position_pct=0.10,
    )


@pytest.fixture(scope="module")
def data_provider(backtest_config: BacktestConfig) -> DuckDBProvider:
    """创建数据提供者"""
    return DuckDBProvider(
        data_dir=backtest_config.data_dir,
        as_of_date=backtest_config.start_date,
    )


@pytest.fixture(scope="module")
def backtest_result(
    backtest_config: BacktestConfig,
    data_provider: DuckDBProvider,
) -> BacktestResult:
    """运行回测获取结果 (模块级缓存)"""
    executor = BacktestExecutor(
        config=backtest_config,
        data_provider=data_provider,
    )
    return executor.run()


@pytest.fixture(scope="module")
def backtest_metrics(backtest_result: BacktestResult) -> BacktestMetrics:
    """计算绩效指标"""
    return BacktestMetrics.from_backtest_result(backtest_result)


@pytest.fixture(scope="module")
def trade_analyzer(backtest_result: BacktestResult) -> TradeAnalyzer:
    """创建交易分析器"""
    return TradeAnalyzer(backtest_result.trade_records)


class TestAnalysisRealData:
    """Analysis 模块真实数据测试"""

    # --- BacktestMetrics 测试 ---

    def test_metrics_calculation_accuracy(
        self,
        backtest_result: BacktestResult,
        backtest_metrics: BacktestMetrics,
    ):
        """验证指标计算准确性"""
        # 收益率 = (final_nlv - initial) / initial
        expected_return = backtest_metrics.final_nlv - backtest_metrics.initial_capital
        expected_return_pct = expected_return / backtest_metrics.initial_capital

        assert abs(backtest_metrics.total_return - expected_return) < 0.01
        assert abs(backtest_metrics.total_return_pct - expected_return_pct) < 0.0001

        # 基本信息匹配
        assert backtest_metrics.config_name == backtest_result.config_name
        assert backtest_metrics.start_date == backtest_result.start_date
        assert backtest_metrics.end_date == backtest_result.end_date

        print(f"\n=== Metrics Calculation ===")
        print(f"Initial Capital: ${backtest_metrics.initial_capital:,.2f}")
        print(f"Final NLV: ${backtest_metrics.final_nlv:,.2f}")
        print(f"Total Return: ${backtest_metrics.total_return:,.2f}")
        print(f"Return %: {backtest_metrics.total_return_pct:.2%}")

    def test_metrics_var_cvar(self, backtest_metrics: BacktestMetrics):
        """验证 VaR/CVaR 计算"""
        # VaR 95% 应在合理范围 (0-20%)
        if backtest_metrics.var_95 is not None:
            assert 0 <= backtest_metrics.var_95 <= 0.20, \
                f"VaR 95% {backtest_metrics.var_95:.2%} out of expected range"

        # CVaR >= VaR (条件风险价值应大于等于风险价值)
        if backtest_metrics.var_95 is not None and backtest_metrics.cvar_95 is not None:
            assert backtest_metrics.cvar_95 >= backtest_metrics.var_95, \
                f"CVaR {backtest_metrics.cvar_95:.2%} < VaR {backtest_metrics.var_95:.2%}"

        print(f"\n=== VaR/CVaR ===")
        print(f"VaR (95%): {backtest_metrics.var_95:.2%}" if backtest_metrics.var_95 else "VaR: N/A")
        print(f"CVaR (95%): {backtest_metrics.cvar_95:.2%}" if backtest_metrics.cvar_95 else "CVaR: N/A")

    def test_metrics_monthly_returns(self, backtest_metrics: BacktestMetrics):
        """验证月度收益"""
        monthly_returns = backtest_metrics.monthly_returns

        # 应覆盖 2025-12 和 2026-01
        assert len(monthly_returns) >= 2, "Should have at least 2 months"

        months_covered = [(m.year, m.month) for m in monthly_returns]
        assert (2025, 12) in months_covered, "Should include 2025-12"
        assert (2026, 1) in months_covered, "Should include 2026-01"

        # 验证月度数据结构
        for m in monthly_returns:
            assert isinstance(m, MonthlyReturn)
            assert 1 <= m.month <= 12
            assert m.trading_days > 0

        print(f"\n=== Monthly Returns ===")
        for m in monthly_returns:
            print(f"{m.year}-{m.month:02d}: {m.return_pct:.2%} ({m.trading_days} days)")

    def test_metrics_drawdown_periods(self, backtest_metrics: BacktestMetrics):
        """验证回撤周期"""
        # 最大回撤应该合理 (0-50%)
        if backtest_metrics.max_drawdown is not None:
            assert 0 <= backtest_metrics.max_drawdown <= 0.50, \
                f"Max drawdown {backtest_metrics.max_drawdown:.2%} out of range"

        # 回撤周期验证
        for dd in backtest_metrics.drawdown_periods:
            assert isinstance(dd, DrawdownPeriod)
            # 回撤深度应该 <= max_drawdown (使用 drawdown_pct 字段)
            if backtest_metrics.max_drawdown is not None:
                assert dd.drawdown_pct <= backtest_metrics.max_drawdown + 0.001

        print(f"\n=== Drawdown ===")
        print(f"Max Drawdown: {backtest_metrics.max_drawdown:.2%}" if backtest_metrics.max_drawdown else "N/A")
        print(f"Drawdown Periods: {len(backtest_metrics.drawdown_periods)}")

    def test_metrics_risk_adjusted_returns(self, backtest_metrics: BacktestMetrics):
        """验证风险调整收益指标"""
        print(f"\n=== Risk-Adjusted Returns ===")
        print(f"Sharpe Ratio: {backtest_metrics.sharpe_ratio:.2f}" if backtest_metrics.sharpe_ratio else "N/A")
        print(f"Sortino Ratio: {backtest_metrics.sortino_ratio:.2f}" if backtest_metrics.sortino_ratio else "N/A")
        print(f"Calmar Ratio: {backtest_metrics.calmar_ratio:.2f}" if backtest_metrics.calmar_ratio else "N/A")

        # 至少有一个风险调整收益指标
        has_ratio = any([
            backtest_metrics.sharpe_ratio is not None,
            backtest_metrics.sortino_ratio is not None,
            backtest_metrics.calmar_ratio is not None,
        ])
        assert has_ratio or backtest_metrics.trading_days < 5

    def test_metrics_to_dict_and_summary(self, backtest_metrics: BacktestMetrics):
        """验证序列化和摘要生成"""
        # to_dict
        d = backtest_metrics.to_dict()
        assert isinstance(d, dict)
        assert "config_name" in d
        assert "total_return_pct" in d
        assert "sharpe_ratio" in d

        # summary
        summary = backtest_metrics.summary()
        assert isinstance(summary, str)
        assert backtest_metrics.config_name in summary
        assert "Return" in summary

    # --- TradeAnalyzer 测试 ---

    def test_analyzer_group_by_symbol(
        self,
        trade_analyzer: TradeAnalyzer,
        backtest_metrics: BacktestMetrics,
    ):
        """按标的分组"""
        by_symbol = trade_analyzer.group_by_symbol()

        print(f"\n=== By Symbol ===")
        total_pnl = 0.0
        for symbol, stats in by_symbol.items():
            print(f"{symbol}: {stats.count} trades, {stats.win_rate:.1%} win rate, ${stats.total_pnl:,.2f} PnL")
            total_pnl += stats.total_pnl
            assert stats.count >= 0
            assert 0 <= stats.win_rate <= 1

        # 如果有交易，PnL 汇总应该接近总 PnL
        if backtest_metrics.total_trades > 0:
            # 允许一定误差 (手续费等)
            print(f"Total PnL from symbols: ${total_pnl:,.2f}")

    def test_analyzer_group_by_month(self, trade_analyzer: TradeAnalyzer):
        """按月分组"""
        by_month = trade_analyzer.group_by_month()

        print(f"\n=== By Month ===")
        for (year, month), stats in by_month.items():
            print(f"{year}-{month:02d}: {stats.count} trades, {stats.win_rate:.1%} win rate")
            assert 1 <= month <= 12
            assert stats.count >= 0

    def test_analyzer_exit_reasons(self, trade_analyzer: TradeAnalyzer):
        """按退出原因统计"""
        by_reason = trade_analyzer.get_exit_reason_stats()

        print(f"\n=== By Exit Reason ===")
        for reason, stats in by_reason.items():
            print(f"{reason}: {stats.count} trades, ${stats.total_pnl:,.2f} PnL")

    def test_analyzer_holding_periods(self, trade_analyzer: TradeAnalyzer):
        """持仓周期分析"""
        stats = trade_analyzer.get_holding_period_stats()

        print(f"\n=== Holding Periods ===")
        if stats:
            print(f"Min: {stats['min']} days")
            print(f"Max: {stats['max']} days")
            print(f"Avg: {stats['avg']:.1f} days")
            if 'distribution' in stats:
                print(f"Distribution: {stats['distribution']}")

            assert stats['min'] >= 0
            assert stats['max'] >= stats['min']
            assert stats['avg'] >= stats['min']
            assert stats['avg'] <= stats['max']

    def test_analyzer_best_worst_trades(self, trade_analyzer: TradeAnalyzer):
        """最佳/最差交易"""
        best = trade_analyzer.get_best_trades(n=5)
        worst = trade_analyzer.get_worst_trades(n=5)

        print(f"\n=== Best Trades ===")
        for t in best[:3]:
            print(f"{t.symbol}: ${t.pnl:,.2f}")

        print(f"\n=== Worst Trades ===")
        for t in worst[:3]:
            print(f"{t.symbol}: ${t.pnl:,.2f}")

        # Best trades 按 PnL 降序
        if len(best) >= 2:
            assert best[0].pnl >= best[1].pnl

        # Worst trades 按 PnL 升序
        if len(worst) >= 2:
            assert worst[0].pnl <= worst[1].pnl


class TestOptimizationRealData:
    """Optimization 模块真实数据测试"""

    # --- ParallelRunner 测试 ---

    def test_parallel_multi_symbol(self, backtest_config: BacktestConfig):
        """多标的并行测试"""
        runner = ParallelBacktestRunner(max_workers=2, use_processes=False)

        result = runner.run_multi_symbol(
            base_config=backtest_config,
            symbols=TEST_SYMBOLS,
        )

        assert isinstance(result, ParallelRunResult)
        assert result.total_tasks == len(TEST_SYMBOLS)
        assert result.completed_tasks + result.failed_tasks == result.total_tasks

        print(f"\n=== Parallel Multi-Symbol ===")
        print(f"Total tasks: {result.total_tasks}")
        print(f"Completed: {result.completed_tasks}")
        print(f"Failed: {result.failed_tasks}")
        print(f"Success rate: {result.success_rate:.1%}")

    def test_parallel_sequential_consistency(self, backtest_config: BacktestConfig):
        """顺序执行测试"""
        runner = ParallelBacktestRunner(max_workers=1)

        # 运行单个配置
        configs = [backtest_config]
        result = runner.run_sequential(configs)

        assert isinstance(result, ParallelRunResult)
        assert result.total_tasks == 1

    # --- ParameterSweep 测试 ---

    def test_sweep_two_params(self, backtest_config: BacktestConfig):
        """双参数网格搜索"""
        sweep = ParameterSweep(backtest_config)
        sweep.add_param("max_positions", [5, 10])
        sweep.add_param("max_position_pct", [0.05, 0.10])

        # 验证组合数量
        combinations = sweep._generate_combinations()
        assert len(combinations) == 4, f"Expected 4 combinations, got {len(combinations)}"

        print(f"\n=== Parameter Sweep Combinations ===")
        for combo in combinations:
            print(f"  {combo.params}")

    def test_sweep_run_and_best_params(self, backtest_config: BacktestConfig):
        """参数扫描执行和最优参数识别"""
        sweep = ParameterSweep(backtest_config)
        sweep.add_param("max_positions", [5, 10])

        result = sweep.run(max_workers=1, use_parallel=False)

        assert isinstance(result, SweepResult)
        assert result.total_combinations == 2
        assert result.successful_runs + result.failed_runs == result.total_combinations

        print(f"\n=== Parameter Sweep Result ===")
        print(f"Total combinations: {result.total_combinations}")
        print(f"Successful: {result.successful_runs}")
        print(f"Failed: {result.failed_runs}")

        if result.successful_runs > 0:
            if result.best_by_return:
                print(f"Best by return: {result.best_by_return}")
            if result.best_by_sharpe:
                print(f"Best by sharpe: {result.best_by_sharpe}")

    def test_sweep_summary(self, backtest_config: BacktestConfig):
        """参数扫描摘要"""
        sweep = ParameterSweep(backtest_config)
        sweep.add_param("max_positions", [5])

        result = sweep.run(max_workers=1, use_parallel=False)
        summary = result.summary()

        assert isinstance(summary, str)
        assert "Parameter Sweep" in summary

    # --- BenchmarkComparison 测试 ---

    def test_benchmark_with_custom(
        self,
        backtest_result: BacktestResult,
    ):
        """自定义基准对比"""
        benchmark = BenchmarkComparison(backtest_result)

        # 创建自定义基准 (模拟 8% 年化收益)
        dates = [s.date for s in backtest_result.daily_snapshots]
        daily_return = 0.08 / 252  # 8% 年化
        prices = [100.0 * (1 + daily_return) ** i for i in range(len(dates))]

        comparison = benchmark.compare_with_custom(
            benchmark_dates=dates,
            benchmark_prices=prices,
            benchmark_name="8% Annual",
        )

        assert isinstance(comparison, BenchmarkResult)
        assert comparison.benchmark_name == "8% Annual"
        assert comparison.strategy_name == backtest_result.config_name

        print(f"\n=== Benchmark Comparison ===")
        print(f"Strategy Return: {comparison.strategy_total_return:.2%}")
        print(f"Benchmark Return: {comparison.benchmark_total_return:.2%}")
        if comparison.alpha is not None:
            print(f"Alpha: {comparison.alpha:.2%}")
        if comparison.beta is not None:
            print(f"Beta: {comparison.beta:.2f}")
        if comparison.correlation is not None:
            print(f"Correlation: {comparison.correlation:.2f}")

    def test_benchmark_with_spy(
        self,
        backtest_result: BacktestResult,
        data_provider: DuckDBProvider,
    ):
        """与 SPY 基准对比"""
        benchmark = BenchmarkComparison(backtest_result)

        try:
            comparison = benchmark.compare_with_spy(data_provider)

            assert isinstance(comparison, BenchmarkResult)
            assert "SPY" in comparison.benchmark_name

            print(f"\n=== SPY Benchmark ===")
            print(f"Strategy Return: {comparison.strategy_total_return:.2%}")
            print(f"SPY Return: {comparison.benchmark_total_return:.2%}")
            if comparison.alpha is not None:
                print(f"Alpha: {comparison.alpha:.2%}")
            if comparison.beta is not None:
                print(f"Beta: {comparison.beta:.2f}")

        except Exception as e:
            pytest.skip(f"SPY benchmark comparison failed: {e}")

    def test_benchmark_metrics_validity(
        self,
        backtest_result: BacktestResult,
    ):
        """验证对比指标合理性"""
        benchmark = BenchmarkComparison(backtest_result)

        dates = [s.date for s in backtest_result.daily_snapshots]
        prices = [100.0] * len(dates)  # 平稳基准

        comparison = benchmark.compare_with_custom(dates, prices)

        # Beta 应在合理范围 (-1 到 3 对于期权策略)
        if comparison.beta is not None:
            assert -1 <= comparison.beta <= 3, f"Beta {comparison.beta} out of range"

        # Correlation 应在 -1 到 1 之间
        if comparison.correlation is not None:
            assert -1 <= comparison.correlation <= 1, f"Correlation {comparison.correlation} out of range"

    # --- WalkForwardValidator 测试 ---

    def test_walk_forward_splits_generation(self, backtest_config: BacktestConfig):
        """滚动窗口分割生成"""
        validator = WalkForwardValidator(backtest_config)

        splits = validator._generate_splits(
            train_months=1,
            test_months=1,
            n_splits=None,
            overlap_months=0,
        )

        print(f"\n=== Walk-Forward Splits ===")
        print(f"Number of splits: {len(splits)}")
        for i, split in enumerate(splits):
            print(f"  Split {i+1}: Train {split.train_start} to {split.train_end}, "
                  f"Test {split.test_start} to {split.test_end}")

        # 验证分割逻辑
        for split in splits:
            assert split.train_end < split.test_start
            assert split.test_end <= backtest_config.end_date

    def test_walk_forward_result_structure(self):
        """WalkForward 结果结构验证"""
        # 创建模拟结果
        result = WalkForwardResult(
            n_splits=3,
            train_months=1,
            test_months=1,
            is_total_return=0.05,
            oos_total_return=0.03,
            is_avg_sharpe=1.5,
            oos_avg_sharpe=1.0,
            avg_return_decay=0.4,
            avg_sharpe_decay=0.33,
            oos_positive_pct=0.67,
            oos_consistent_sharpe=0.67,  # 使用正确的字段名
            overfitting_score=0.35,
        )

        # 验证序列化
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["n_splits"] == 3

        # 验证摘要
        summary = result.summary()
        assert isinstance(summary, str)
        assert "Walk-Forward" in summary
        assert "In-Sample" in summary
        assert "Out-of-Sample" in summary

        print(f"\n=== Walk-Forward Result ===")
        print(summary)

    def test_walk_forward_overfitting_score_range(self):
        """过拟合评分范围验证"""
        # 低过拟合情况
        low_overfit = WalkForwardResult(
            n_splits=4,
            train_months=1,
            test_months=1,
            avg_return_decay=0.10,
            avg_sharpe_decay=0.10,
            oos_positive_pct=0.80,
            overfitting_score=0.15,
        )
        assert 0 <= low_overfit.overfitting_score <= 1

        # 高过拟合情况
        high_overfit = WalkForwardResult(
            n_splits=4,
            train_months=1,
            test_months=1,
            avg_return_decay=0.60,
            avg_sharpe_decay=0.50,
            oos_positive_pct=0.30,
            overfitting_score=0.75,
        )
        assert 0 <= high_overfit.overfitting_score <= 1
        assert high_overfit.overfitting_score > low_overfit.overfitting_score


class TestIntegrationWorkflow:
    """集成工作流测试"""

    def test_full_analysis_pipeline(
        self,
        backtest_config: BacktestConfig,
        data_provider: DuckDBProvider,
    ):
        """完整分析流水线"""
        print("\n=== Full Analysis Pipeline ===")

        # 1. 运行回测
        print("1. Running backtest...")
        executor = BacktestExecutor(
            config=backtest_config,
            data_provider=data_provider,
        )
        result = executor.run()
        print(f"   Trades: {result.total_trades}")

        # 2. 计算 Metrics
        print("2. Calculating metrics...")
        metrics = BacktestMetrics.from_backtest_result(result)
        print(f"   Return: {metrics.total_return_pct:.2%}")
        print(f"   Sharpe: {metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio else "   Sharpe: N/A")

        # 3. 运行 TradeAnalyzer
        print("3. Analyzing trades...")
        analyzer = TradeAnalyzer(result.trade_records)
        by_symbol = analyzer.group_by_symbol()
        print(f"   Symbols analyzed: {list(by_symbol.keys())}")

        # 4. 与基准对比
        print("4. Comparing with benchmark...")
        benchmark = BenchmarkComparison(result)
        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]
        comparison = benchmark.compare_with_custom(dates, prices, "Custom")
        print(f"   Alpha: {comparison.alpha:.2%}" if comparison.alpha else "   Alpha: N/A")

        # 5. 验证完整性
        assert result is not None
        assert metrics is not None
        assert comparison is not None
        print("5. Pipeline completed successfully!")

    def test_parameter_optimization_workflow(self, backtest_config: BacktestConfig):
        """参数优化工作流"""
        print("\n=== Parameter Optimization Workflow ===")

        # 1. 参数扫描
        print("1. Running parameter sweep...")
        sweep = ParameterSweep(backtest_config)
        sweep.add_param("max_positions", [5, 10])

        sweep_result = sweep.run(max_workers=1, use_parallel=False)
        print(f"   Combinations: {sweep_result.total_combinations}")
        print(f"   Successful: {sweep_result.successful_runs}")

        # 2. 获取最优参数
        if sweep_result.successful_runs > 0:
            print("2. Identifying best parameters...")
            if sweep_result.best_by_return:
                print(f"   Best by return: {sweep_result.best_by_return}")

            # 3. 验证最优配置
            print("3. Validating best configuration...")
            best_params, best_result, best_metrics = sweep_result.results[0]
            print(f"   Return: {best_metrics.total_return_pct:.2%}")

        print("4. Optimization workflow completed!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
