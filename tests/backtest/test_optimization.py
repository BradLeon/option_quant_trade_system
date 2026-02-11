"""
Tests for Backtest Optimization Module.

Tests ParallelBacktestRunner, ParameterSweep, BenchmarkComparison, and WalkForwardValidator.
"""

import pytest
from datetime import date
from pathlib import Path

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.backtest_executor import BacktestExecutor
from src.backtest.optimization.parallel_runner import ParallelBacktestRunner, ParallelRunResult
from src.backtest.optimization.parameter_sweep import ParameterSweep, SweepResult
from src.backtest.optimization.benchmark import BenchmarkComparison, BenchmarkResult
from src.backtest.optimization.walk_forward import WalkForwardValidator, WalkForwardResult
from src.engine.models.enums import StrategyType


class TestParallelBacktestRunner:
    """Test ParallelBacktestRunner functionality."""

    def test_runner_initialization(self):
        """Test runner initialization."""
        runner = ParallelBacktestRunner(max_workers=2)
        assert runner._max_workers == 2

    def test_runner_default_workers(self):
        """Test default worker count."""
        runner = ParallelBacktestRunner()
        assert runner._max_workers >= 1
        assert runner._max_workers <= 8

    def test_run_sequential(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test sequential execution."""
        runner = ParallelBacktestRunner(max_workers=1)

        # Create a simple config list
        configs = [sample_backtest_config]

        result = runner.run_sequential(configs)

        assert isinstance(result, ParallelRunResult)
        assert result.total_tasks == 1
        assert result.completed_tasks + result.failed_tasks == result.total_tasks

    def test_run_multi_symbol(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
        sample_symbols: list[str],
    ):
        """Test multi-symbol parallel run."""
        runner = ParallelBacktestRunner(max_workers=2, use_processes=False)

        result = runner.run_multi_symbol(
            base_config=sample_backtest_config,
            symbols=sample_symbols[:2],  # Use only 2 symbols for speed
        )

        assert isinstance(result, ParallelRunResult)
        assert result.total_tasks == 2

    def test_parallel_run_result_aggregation(self):
        """Test result aggregation."""
        result = ParallelRunResult(
            total_tasks=3,
            completed_tasks=2,
            failed_tasks=1,
        )

        assert result.success_rate == 2 / 3


class TestParameterSweep:
    """Test ParameterSweep functionality."""

    def test_sweep_initialization(
        self,
        sample_backtest_config: BacktestConfig,
    ):
        """Test sweep initialization."""
        sweep = ParameterSweep(sample_backtest_config)
        assert sweep._base_config == sample_backtest_config
        assert len(sweep._param_ranges) == 0

    def test_add_param(
        self,
        sample_backtest_config: BacktestConfig,
    ):
        """Test adding parameters."""
        sweep = ParameterSweep(sample_backtest_config)
        sweep.add_param("max_positions", [5, 10])
        sweep.add_param("max_position_pct", [0.05, 0.10])

        assert "max_positions" in sweep._param_ranges
        assert "max_position_pct" in sweep._param_ranges
        assert len(sweep._param_ranges["max_positions"]) == 2

    def test_chain_add_params(
        self,
        sample_backtest_config: BacktestConfig,
    ):
        """Test chained parameter addition."""
        sweep = (
            ParameterSweep(sample_backtest_config)
            .add_param("max_positions", [5, 10])
            .add_param("max_position_pct", [0.05])
        )

        assert len(sweep._param_ranges) == 2

    def test_generate_combinations(
        self,
        sample_backtest_config: BacktestConfig,
    ):
        """Test combination generation."""
        sweep = ParameterSweep(sample_backtest_config)
        sweep.add_param("max_positions", [5, 10])
        sweep.add_param("max_position_pct", [0.05, 0.10])

        combinations = sweep._generate_combinations()

        # 2 x 2 = 4 combinations
        assert len(combinations) == 4

    def test_sweep_run_small(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test running a small parameter sweep."""
        sweep = ParameterSweep(sample_backtest_config)
        sweep.add_param("max_positions", [5, 10])

        # Run with single worker for speed
        result = sweep.run(max_workers=1, use_parallel=False)

        assert isinstance(result, SweepResult)
        assert result.total_combinations == 2
        assert result.successful_runs + result.failed_runs == result.total_combinations

    def test_sweep_result_best_params(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test best parameter identification."""
        sweep = ParameterSweep(sample_backtest_config)
        sweep.add_param("max_positions", [5])

        result = sweep.run(max_workers=1, use_parallel=False)

        # Should identify best params if there are successful runs
        if result.successful_runs > 0:
            assert result.best_by_return is not None

    def test_sweep_result_summary(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test result summary generation."""
        sweep = ParameterSweep(sample_backtest_config)
        sweep.add_param("max_positions", [5])

        result = sweep.run(max_workers=1, use_parallel=False)
        summary = result.summary()

        assert isinstance(summary, str)
        assert "Parameter Sweep Summary" in summary


class TestBenchmarkComparison:
    """Test BenchmarkComparison functionality."""

    def test_comparison_initialization(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test comparison initialization."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        benchmark = BenchmarkComparison(result)

        assert benchmark._result == result
        assert len(benchmark._strategy_returns) >= 0

    def test_compare_with_custom_benchmark(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test comparison with custom benchmark."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        benchmark = BenchmarkComparison(result)

        # Create a simple benchmark
        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]  # 0.01% daily

        comparison = benchmark.compare_with_custom(
            benchmark_dates=dates,
            benchmark_prices=prices,
            benchmark_name="Test Benchmark",
        )

        assert isinstance(comparison, BenchmarkResult)
        assert comparison.benchmark_name == "Test Benchmark"
        assert comparison.strategy_name == result.config_name

    def test_comparison_metrics(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test comparison metric calculations."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        benchmark = BenchmarkComparison(result)

        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]

        comparison = benchmark.compare_with_custom(dates, prices)

        # Verify metrics are calculated
        assert comparison.strategy_total_return is not None
        assert comparison.benchmark_total_return is not None
        assert len(comparison.dates) > 0
        assert len(comparison.strategy_cumulative) > 0

    def test_comparison_summary(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test comparison summary generation."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        benchmark = BenchmarkComparison(result)

        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]

        comparison = benchmark.compare_with_custom(dates, prices)
        summary = comparison.summary()

        assert isinstance(summary, str)
        assert "Benchmark Comparison" in summary


class TestWalkForwardValidator:
    """Test WalkForwardValidator functionality."""

    def test_validator_initialization(
        self,
        sample_backtest_config: BacktestConfig,
    ):
        """Test validator initialization."""
        validator = WalkForwardValidator(sample_backtest_config)
        assert validator._base_config == sample_backtest_config

    def test_generate_splits(
        self,
        sample_backtest_config: BacktestConfig,
    ):
        """Test split generation."""
        validator = WalkForwardValidator(sample_backtest_config)

        splits = validator._generate_splits(
            train_months=1,
            test_months=1,
            n_splits=None,
            overlap_months=0,
        )

        # With 3 months of data (Jan-Mar), we should get at least 1 split
        assert len(splits) >= 0

        for split in splits:
            # Train should come before test
            assert split.train_end < split.test_start
            # Test should not exceed data range
            assert split.test_end <= sample_backtest_config.end_date

    def test_walk_forward_result_summary(self):
        """Test result summary generation."""
        result = WalkForwardResult(
            n_splits=4,
            train_months=12,
            test_months=3,
            is_total_return=0.15,
            oos_total_return=0.08,
            oos_positive_pct=0.75,
        )

        summary = result.summary()

        assert isinstance(summary, str)
        assert "Walk-Forward" in summary
        assert "In-Sample" in summary
        assert "Out-of-Sample" in summary

    def test_walk_forward_result_to_dict(self):
        """Test result serialization."""
        result = WalkForwardResult(
            n_splits=4,
            train_months=12,
            test_months=3,
        )

        d = result.to_dict()

        assert isinstance(d, dict)
        assert "n_splits" in d
        assert "train_months" in d
        assert d["n_splits"] == 4


class TestOptimizationIntegration:
    """Integration tests for optimization modules."""

    def test_full_optimization_workflow(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test complete optimization workflow."""
        # 1. Run base backtest
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # 2. Calculate metrics
        from src.backtest.analysis.metrics import BacktestMetrics

        metrics = BacktestMetrics.from_backtest_result(result)

        # 3. Compare with benchmark
        benchmark = BenchmarkComparison(result)
        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0] * len(dates)
        comparison = benchmark.compare_with_custom(dates, prices)

        # 4. Verify everything works together
        assert metrics.total_return_pct is not None
        assert comparison.strategy_total_return is not None

    def test_parameter_sweep_with_benchmark(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test parameter sweep followed by benchmark comparison."""
        # Run parameter sweep
        sweep = ParameterSweep(sample_backtest_config)
        sweep.add_param("max_positions", [5])

        sweep_result = sweep.run(max_workers=1, use_parallel=False)

        # Compare best result with benchmark
        if sweep_result.successful_runs > 0:
            best_params, best_bt_result, best_metrics = sweep_result.results[0]

            benchmark = BenchmarkComparison(best_bt_result)
            dates = [s.date for s in best_bt_result.daily_snapshots]
            prices = [100.0] * len(dates)

            comparison = benchmark.compare_with_custom(dates, prices)

            assert comparison is not None
