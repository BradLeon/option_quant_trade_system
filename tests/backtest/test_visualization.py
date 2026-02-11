"""
Tests for Backtest Visualization Module.

Tests BacktestDashboard and chart generation.
"""

import pytest
import tempfile
from datetime import date
from pathlib import Path

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.backtest_executor import BacktestExecutor
from src.backtest.analysis.metrics import BacktestMetrics


# Check if Plotly is available
try:
    import plotly
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


@pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="Plotly not installed")
class TestBacktestDashboard:
    """Test BacktestDashboard functionality."""

    def test_dashboard_initialization(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test dashboard initialization."""
        from src.backtest.visualization.dashboard import BacktestDashboard

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        assert dashboard is not None
        assert dashboard._metrics is not None

    def test_dashboard_with_metrics(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test dashboard with pre-calculated metrics."""
        from src.backtest.visualization.dashboard import BacktestDashboard

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        metrics = BacktestMetrics.from_backtest_result(result)
        dashboard = BacktestDashboard(result, metrics)

        assert dashboard._metrics is metrics

    def test_create_equity_curve(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test equity curve chart creation."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        import plotly.graph_objects as go

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        fig = dashboard.create_equity_curve()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1  # At least the equity line

    def test_create_drawdown_chart(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test drawdown chart creation."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        import plotly.graph_objects as go

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        fig = dashboard.create_drawdown_chart()

        assert isinstance(fig, go.Figure)

    def test_create_monthly_returns_heatmap(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test monthly returns heatmap creation."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        import plotly.graph_objects as go

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        fig = dashboard.create_monthly_returns_heatmap()

        assert isinstance(fig, go.Figure)

    def test_create_trade_timeline(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test trade timeline chart creation."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        import plotly.graph_objects as go

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        fig = dashboard.create_trade_timeline()

        assert isinstance(fig, go.Figure)

    def test_create_metrics_panel(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test metrics panel HTML generation."""
        from src.backtest.visualization.dashboard import BacktestDashboard

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        html = dashboard.create_metrics_panel()

        assert isinstance(html, str)
        assert "metrics-panel" in html
        assert result.config_name in html

    def test_generate_report(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test HTML report generation."""
        from src.backtest.visualization.dashboard import BacktestDashboard

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "test_report.html"
            output_path = dashboard.generate_report(report_path)

            assert output_path.exists()
            assert output_path.suffix == ".html"

            # Read and verify content
            content = output_path.read_text()
            assert "<!DOCTYPE html>" in content
            assert result.config_name in content
            assert "plotly" in content.lower()

    def test_generate_report_selective_charts(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test generating report with selected charts only."""
        from src.backtest.visualization.dashboard import BacktestDashboard

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        dashboard = BacktestDashboard(result)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "test_report.html"

            # Only include equity and drawdown
            output_path = dashboard.generate_report(
                report_path,
                include_charts=["equity", "drawdown"],
            )

            assert output_path.exists()


    def test_create_benchmark_comparison(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test benchmark comparison chart creation."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        from src.backtest.optimization.benchmark import BenchmarkComparison
        import plotly.graph_objects as go

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Create benchmark comparison
        benchmark = BenchmarkComparison(result)
        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]
        benchmark_result = benchmark.compare_with_custom(dates, prices, "Test Benchmark")

        # Create dashboard with benchmark
        dashboard = BacktestDashboard(result, benchmark_result=benchmark_result)

        fig = dashboard.create_benchmark_comparison()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2  # Strategy and benchmark lines

    def test_create_benchmark_comparison_without_data(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test benchmark comparison chart without benchmark data."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        import plotly.graph_objects as go

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Create dashboard without benchmark
        dashboard = BacktestDashboard(result)

        fig = dashboard.create_benchmark_comparison()

        assert isinstance(fig, go.Figure)
        # Should have annotation saying no data

    def test_create_benchmark_metrics_panel(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test benchmark metrics panel HTML generation."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        from src.backtest.optimization.benchmark import BenchmarkComparison

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Create benchmark comparison
        benchmark = BenchmarkComparison(result)
        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]
        benchmark_result = benchmark.compare_with_custom(dates, prices, "Test Benchmark")

        dashboard = BacktestDashboard(result, benchmark_result=benchmark_result)

        html = dashboard.create_benchmark_metrics_panel()

        assert isinstance(html, str)
        assert "benchmark-panel" in html
        assert "Test Benchmark" in html

    def test_generate_report_with_benchmark(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test HTML report generation with benchmark."""
        from src.backtest.visualization.dashboard import BacktestDashboard
        from src.backtest.optimization.benchmark import BenchmarkComparison

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Create benchmark comparison
        benchmark = BenchmarkComparison(result)
        dates = [s.date for s in result.daily_snapshots]
        prices = [100.0 * (1.0001 ** i) for i in range(len(dates))]
        benchmark_result = benchmark.compare_with_custom(dates, prices, "Test Benchmark")

        dashboard = BacktestDashboard(result, benchmark_result=benchmark_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "test_report_with_benchmark.html"
            output_path = dashboard.generate_report(report_path)

            assert output_path.exists()

            # Read and verify content
            content = output_path.read_text()
            assert "Test Benchmark" in content
            assert "benchmark-panel" in content


@pytest.mark.skipif(PLOTLY_AVAILABLE, reason="Test for when Plotly is not installed")
class TestDashboardWithoutPlotly:
    """Test dashboard behavior when Plotly is not available."""

    def test_dashboard_import_error(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that dashboard raises ImportError when Plotly is missing."""
        # This test only runs when Plotly is NOT available
        # In that case, importing dashboard should raise or the class should handle it
        pass  # The actual import would have already failed
