"""
Tests for Backtest Analysis Module.

Tests BacktestMetrics and TradeAnalyzer.
"""

import pytest
from datetime import date
from pathlib import Path

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult
from src.backtest.analysis.metrics import BacktestMetrics, MonthlyReturn, DrawdownPeriod
from src.backtest.analysis.trade_analyzer import TradeAnalyzer, TradeSummary
from src.engine.models.enums import StrategyType


class TestBacktestMetrics:
    """Test BacktestMetrics calculation."""

    def test_metrics_from_backtest_result(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test creating metrics from backtest result."""
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

        # Basic info
        assert metrics.config_name == result.config_name
        assert metrics.start_date == result.start_date
        assert metrics.end_date == result.end_date
        assert metrics.trading_days == result.trading_days
        assert metrics.initial_capital == result.initial_capital

        # Return metrics should match
        assert abs(metrics.total_return - result.total_return) < 0.01
        assert abs(metrics.total_return_pct - result.total_return_pct) < 0.0001

    def test_metrics_return_calculations(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test return metric calculations."""
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

        # Total return should equal final - initial
        expected_total = metrics.final_nlv - metrics.initial_capital
        assert abs(metrics.total_return - expected_total) < 0.01

        # Return percentage
        expected_pct = expected_total / metrics.initial_capital
        assert abs(metrics.total_return_pct - expected_pct) < 0.0001

    def test_metrics_risk_indicators(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test risk metric calculations."""
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

        # Max drawdown should be between 0 and 1
        if metrics.max_drawdown is not None:
            assert 0 <= metrics.max_drawdown <= 1

        # Volatility should be non-negative
        if metrics.volatility is not None:
            assert metrics.volatility >= 0

        # VaR should be non-negative (expressed as potential loss)
        if metrics.var_95 is not None:
            assert metrics.var_95 >= 0

    def test_metrics_risk_adjusted_returns(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test risk-adjusted return calculations."""
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

        # Sharpe, Sortino, Calmar can be any real number
        # Just verify they are calculated when data is available
        assert (
            metrics.sharpe_ratio is not None
            or metrics.trading_days < 3  # Not enough data
        )

    def test_metrics_trade_statistics(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test trade statistics calculations."""
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

        # Trade counts
        assert metrics.total_trades >= 0
        assert metrics.winning_trades >= 0
        assert metrics.losing_trades >= 0
        assert metrics.winning_trades + metrics.losing_trades == metrics.total_trades

        # Win rate
        if metrics.total_trades > 0:
            assert metrics.win_rate is not None
            assert 0 <= metrics.win_rate <= 1

    def test_metrics_monthly_returns(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test monthly return calculations."""
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

        # Should have monthly returns
        assert len(metrics.monthly_returns) > 0

        for m in metrics.monthly_returns:
            assert isinstance(m, MonthlyReturn)
            assert 1 <= m.month <= 12
            assert m.trading_days > 0

    def test_metrics_to_dict(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test metrics serialization to dict."""
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

        # Convert to dict
        d = metrics.to_dict()

        assert isinstance(d, dict)
        assert "config_name" in d
        assert "total_return_pct" in d
        assert "sharpe_ratio" in d
        assert "monthly_returns" in d

    def test_metrics_summary(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test metrics summary string generation."""
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

        # Generate summary
        summary = metrics.summary()

        assert isinstance(summary, str)
        assert metrics.config_name in summary
        assert "Returns" in summary
        assert "Risk" in summary


class TestTradeAnalyzer:
    """Test TradeAnalyzer functionality."""

    def test_analyzer_initialization(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test TradeAnalyzer initialization."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        analyzer = TradeAnalyzer(result.trade_records)

        assert analyzer is not None

    def test_group_by_symbol(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test grouping trades by symbol."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        analyzer = TradeAnalyzer(result.trade_records)

        by_symbol = analyzer.group_by_symbol()

        # Each symbol should have stats
        for symbol, stats in by_symbol.items():
            assert stats.symbol == symbol
            assert stats.count >= 0
            assert stats.winning >= 0
            assert stats.losing >= 0

    def test_group_by_month(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test grouping trades by month."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        analyzer = TradeAnalyzer(result.trade_records)

        by_month = analyzer.group_by_month()

        for (year, month), stats in by_month.items():
            assert stats.year == year
            assert stats.month == month
            assert 1 <= month <= 12

    def test_best_worst_trades(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test getting best and worst trades."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        analyzer = TradeAnalyzer(result.trade_records)

        best = analyzer.get_best_trades(n=3)
        worst = analyzer.get_worst_trades(n=3)

        # Best trades should be sorted by PnL descending
        if len(best) >= 2:
            assert best[0].pnl >= best[1].pnl

        # Worst trades should be sorted by PnL ascending
        if len(worst) >= 2:
            assert worst[0].pnl <= worst[1].pnl

    def test_holding_period_stats(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test holding period statistics."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        analyzer = TradeAnalyzer(result.trade_records)

        stats = analyzer.get_holding_period_stats()

        if stats:  # Only if there are trades
            assert "min" in stats
            assert "max" in stats
            assert "avg" in stats
            assert "distribution" in stats

    def test_summary_report(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test summary report generation."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()
        analyzer = TradeAnalyzer(result.trade_records)

        report = analyzer.summary_report()

        assert isinstance(report, str)
        assert "Trade Analysis Report" in report
