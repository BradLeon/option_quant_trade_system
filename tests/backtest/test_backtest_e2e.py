"""
End-to-End Tests for Backtest Module.

Tests the complete backtest flow from configuration to result generation.
"""

import pytest
from datetime import date
from pathlib import Path

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult
from src.backtest.engine.position_tracker import PositionTracker
from src.backtest.engine.trade_simulator import TradeSimulator
from src.engine.models.enums import StrategyType


class TestBacktestExecutorE2E:
    """End-to-end tests for BacktestExecutor."""

    def test_backtest_executor_initialization(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test BacktestExecutor can be initialized."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        assert executor is not None
        assert executor._config == sample_backtest_config

    def test_backtest_run_produces_result(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that backtest run produces a valid BacktestResult."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        # Run backtest
        result = executor.run()

        # Verify result structure
        assert isinstance(result, BacktestResult)
        assert result.config_name == sample_backtest_config.name
        assert result.start_date == sample_backtest_config.start_date
        assert result.end_date == sample_backtest_config.end_date
        assert result.strategy_type == sample_backtest_config.strategy_type
        assert result.initial_capital == sample_backtest_config.initial_capital
        assert result.trading_days > 0

    def test_backtest_result_has_equity_curve(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that backtest result includes daily snapshots."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Should have daily snapshots
        assert len(result.daily_snapshots) > 0
        assert len(result.daily_snapshots) == result.trading_days

        # Each snapshot should have required fields
        for snapshot in result.daily_snapshots:
            assert snapshot.date is not None
            assert snapshot.nlv > 0
            assert snapshot.cash >= 0

    def test_equity_curve_helper(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test equity curve helper method."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        executor.run()

        # Get equity curve
        equity_curve = executor.get_equity_curve()
        assert len(equity_curve) > 0
        assert all(isinstance(d, date) for d, _ in equity_curve)
        assert all(isinstance(v, float) for _, v in equity_curve)

    def test_drawdown_curve_helper(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test drawdown curve helper method."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        executor.run()

        # Get drawdown curve
        drawdown_curve = executor.get_drawdown_curve()
        assert len(drawdown_curve) > 0

        # Drawdown should be between 0 and 1
        for d, dd in drawdown_curve:
            assert 0 <= dd <= 1

    def test_backtest_respects_max_positions(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that backtest respects max_positions limit."""
        # Set a low max_positions limit
        sample_backtest_config.max_positions = 2

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        executor.run()

        # Check that position count never exceeded limit
        for snapshot in executor._daily_snapshots:
            assert snapshot.position_count <= sample_backtest_config.max_positions

    def test_backtest_reset(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that backtest can be reset and run again."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        # Run first time
        result1 = executor.run()

        # Reset
        executor.reset()

        # Run second time
        result2 = executor.run()

        # Results should be similar (deterministic with same data)
        assert result1.trading_days == result2.trading_days
        assert result1.initial_capital == result2.initial_capital


class TestBacktestResultValidation:
    """Test BacktestResult validation and calculations."""

    def test_total_return_calculation(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that total return is calculated correctly."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Verify return calculation
        expected_return = result.final_nlv - result.initial_capital
        assert abs(result.total_return - expected_return) < 0.01

        expected_return_pct = expected_return / result.initial_capital
        assert abs(result.total_return_pct - expected_return_pct) < 0.0001

    def test_win_rate_bounds(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that win rate is within valid bounds."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Win rate should be between 0 and 1
        assert 0 <= result.win_rate <= 1

        # Verify consistency with trade counts
        if result.total_trades > 0:
            expected_win_rate = result.winning_trades / result.total_trades
            assert abs(result.win_rate - expected_win_rate) < 0.0001

    def test_result_to_dict(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that result can be serialized to dict."""
        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
        )

        result = executor.run()

        # Convert to dict
        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert "config_name" in result_dict
        assert "start_date" in result_dict
        assert "total_return_pct" in result_dict
        assert "win_rate" in result_dict


class TestBacktestWithManualTrades:
    """Test backtest with manually injected trades."""

    def test_manual_trade_simulation(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ):
        """Test simulating trades manually."""
        # Simulate opening a SHORT PUT
        open_execution = trade_simulator.execute_open(
            symbol="AAPL 20240315 150P",
            underlying="AAPL",
            option_type="put",
            strike=150.0,
            expiration=date(2024, 3, 15),
            quantity=-1,  # Short 1 put
            mid_price=3.50,
            trade_date=date(2024, 2, 1),
            reason="manual_test",
        )

        assert open_execution is not None
        assert open_execution.side.value == "sell"
        assert open_execution.fill_price < 3.50  # Slippage for sell
        assert open_execution.commission > 0

        # Create position using the fill price from trade simulator
        position = SimulatedPosition(
            position_id="TEST001",
            symbol="AAPL 20240315 150P",
            underlying="AAPL",
            option_type="put",
            strike=150.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            entry_price=open_execution.fill_price,
            entry_date=date(2024, 2, 1),
            underlying_price=155.0,  # Need this for margin calc
        )

        # Open in position tracker (use per-contract commission)
        position_tracker.open_position(position, commission=0.65)

        assert position_tracker.position_count == 1

        # Simulate closing at a significantly lower price for clear profit
        close_execution = trade_simulator.execute_close(
            symbol="AAPL 20240315 150P",
            underlying="AAPL",
            option_type="put",
            strike=150.0,
            expiration=date(2024, 3, 15),
            quantity=1,  # Buy back
            mid_price=0.50,  # Much lower price for clear profit
            trade_date=date(2024, 3, 1),
            reason="take_profit",
        )

        assert close_execution is not None
        assert close_execution.side.value == "buy"

        # Close position
        pnl = position_tracker.close_position(
            position_id="TEST001",
            close_price=close_execution.fill_price,
            close_date=date(2024, 3, 1),
            close_reason="take_profit",
            commission=0.65,
        )

        assert pnl is not None
        # PnL should be positive: (entry_price - close_price) * |qty| * lot - commissions
        # Approximate: (3.50 - 0.50) * 1 * 100 - 1.30 = 300 - 1.30 = ~298.70
        assert pnl > 0, f"Expected positive PnL but got {pnl}"
        assert position_tracker.position_count == 0

    def test_slippage_and_commission_tracking(
        self,
        trade_simulator: TradeSimulator,
    ):
        """Test that slippage and commissions are tracked correctly."""
        # Execute multiple trades
        for i in range(5):
            trade_simulator.execute_open(
                symbol=f"TEST{i} 20240315 100P",
                underlying=f"TEST{i}",
                option_type="put",
                strike=100.0,
                expiration=date(2024, 3, 15),
                quantity=-1,
                mid_price=2.00,
                trade_date=date(2024, 2, 1),
            )

        # Check totals
        total_commission = trade_simulator.get_total_commission()
        total_slippage = trade_simulator.get_total_slippage()

        assert total_commission > 0
        assert total_slippage > 0

        # Get summary
        summary = trade_simulator.get_execution_summary()
        assert summary["total_trades"] == 5
        assert summary["total_commission"] == total_commission


class TestProgressCallback:
    """Test progress callback functionality."""

    def test_progress_callback_called(
        self,
        sample_backtest_config: BacktestConfig,
        temp_data_dir: Path,
    ):
        """Test that progress callback is called during backtest."""
        progress_calls = []

        def progress_callback(current_date, current_day, total_days):
            progress_calls.append((current_date, current_day, total_days))

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=sample_backtest_config.start_date,
        )

        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=provider,
            progress_callback=progress_callback,
        )

        result = executor.run()

        # Progress should have been called for each trading day
        assert len(progress_calls) == result.trading_days

        # Verify progress is incremental
        for i, (d, current, total) in enumerate(progress_calls):
            assert current == i + 1
            assert total == result.trading_days


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_symbols_list(self, temp_data_dir: Path):
        """Test backtest with empty symbols list."""
        config = BacktestConfig(
            name="TEST_EMPTY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            symbols=[],  # Empty
            strategy_type=StrategyType.SHORT_PUT,
            data_dir=temp_data_dir,
        )

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=config.start_date,
        )

        executor = BacktestExecutor(config=config, data_provider=provider)
        result = executor.run()

        # Should complete without error
        assert result.total_trades == 0

    def test_single_day_backtest(
        self,
        temp_data_dir: Path,
        sample_symbols: list[str],
    ):
        """Test backtest with single day."""
        config = BacktestConfig(
            name="TEST_SINGLE_DAY",
            start_date=date(2024, 2, 15),
            end_date=date(2024, 2, 15),
            symbols=sample_symbols,
            strategy_type=StrategyType.SHORT_PUT,
            data_dir=temp_data_dir,
        )

        provider = DuckDBProvider(
            data_dir=temp_data_dir,
            as_of_date=config.start_date,
        )

        executor = BacktestExecutor(config=config, data_provider=provider)
        result = executor.run()

        # Should have at most 1 trading day
        assert result.trading_days <= 1
