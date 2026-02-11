"""
Backtest Engine Integration Tests

测试回测引擎各组件的集成功能，包括：
- BacktestExecutor 初始化和运行
- PositionTracker 持仓生命周期
- AccountSimulator 保证金计算
- TradeSimulator 滑点模型
- 每日快照一致性
- 期权到期处理

Usage:
    uv run python -m pytest tests/backtest/test_engine_integration.py -v
"""

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult
from src.backtest.engine.position_tracker import PositionTracker
from src.backtest.engine.trade_simulator import (
    CommissionModel,
    OrderSide,
    SlippageModel,
    TradeSimulator,
)
from src.data.models.option import OptionType
from src.engine.models.enums import StrategyType


# ============================================================================
# BacktestExecutor Tests
# ============================================================================


class TestBacktestExecutorInitialization:
    """测试 BacktestExecutor 初始化"""

    def test_executor_initialization(
        self,
        sample_backtest_config: BacktestConfig,
        duckdb_provider: DuckDBProvider,
    ) -> None:
        """验证 BacktestExecutor 能正确初始化"""
        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=duckdb_provider,
        )

        assert executor is not None
        assert executor._config == sample_backtest_config
        assert executor._data_provider == duckdb_provider
        # 新架构: BacktestExecutor 直接持有三层组件
        assert executor._position_manager is not None
        assert executor._account_simulator is not None
        assert executor._trade_simulator is not None

    def test_executor_with_default_provider(
        self,
        sample_backtest_config: BacktestConfig,
    ) -> None:
        """验证 BacktestExecutor 能使用默认 provider 初始化"""
        # 注意：这会尝试从 config.data_dir 创建 provider
        executor = BacktestExecutor(config=sample_backtest_config)

        assert executor is not None
        assert executor._data_provider is not None


class TestBacktestExecutorRun:
    """测试 BacktestExecutor 运行"""

    def test_run_empty_period(
        self,
        temp_data_dir: Path,
        sample_symbols: list[str],
    ) -> None:
        """验证无数据日期范围的回测返回空结果"""
        # 使用一个远在未来的日期范围（无数据）
        config = BacktestConfig(
            name="TEST_EMPTY",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 31),
            symbols=sample_symbols,
            strategy_type=StrategyType.SHORT_PUT,
            initial_capital=100_000.0,
            data_dir=temp_data_dir,
        )

        executor = BacktestExecutor(config)
        result = executor.run()

        assert result is not None
        assert result.trading_days == 0
        assert result.total_trades == 0
        assert result.final_nlv == config.initial_capital
        assert result.total_return == 0.0
        assert len(result.errors) > 0  # 应该有 "No trading days" 错误

    def test_run_with_sample_data(
        self,
        sample_backtest_config: BacktestConfig,
        duckdb_provider: DuckDBProvider,
    ) -> None:
        """验证使用样本数据能完成回测"""
        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=duckdb_provider,
        )

        result = executor.run()

        assert result is not None
        assert isinstance(result, BacktestResult)
        assert result.config_name == sample_backtest_config.name
        assert result.initial_capital == sample_backtest_config.initial_capital
        # 应该有交易日（因为有样本数据）
        assert result.trading_days > 0
        # 每个交易日都应该有快照
        assert len(result.daily_snapshots) == result.trading_days

    def test_daily_snapshot_consistency(
        self,
        sample_backtest_config: BacktestConfig,
        duckdb_provider: DuckDBProvider,
    ) -> None:
        """验证每日快照的一致性: NLV = Cash + Positions Value"""
        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=duckdb_provider,
        )

        result = executor.run()

        for snapshot in result.daily_snapshots:
            # NLV 应该等于 Cash + Positions Value
            # 注意：对于空头持仓，positions_value 可能是负数
            expected_nlv = snapshot.cash + snapshot.positions_value
            assert math.isclose(snapshot.nlv, expected_nlv, rel_tol=0.01), (
                f"NLV mismatch on {snapshot.date}: "
                f"nlv={snapshot.nlv}, cash={snapshot.cash}, "
                f"positions_value={snapshot.positions_value}"
            )

    def test_equity_curve(
        self,
        sample_backtest_config: BacktestConfig,
        duckdb_provider: DuckDBProvider,
    ) -> None:
        """验证权益曲线的生成"""
        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=duckdb_provider,
        )

        result = executor.run()
        equity_curve = executor.get_equity_curve()

        # 权益曲线长度应该等于交易日数
        assert len(equity_curve) == result.trading_days

        # 第一天的 NLV 应该接近初始资金
        if equity_curve:
            first_date, first_nlv = equity_curve[0]
            assert first_nlv > 0

    def test_drawdown_curve(
        self,
        sample_backtest_config: BacktestConfig,
        duckdb_provider: DuckDBProvider,
    ) -> None:
        """验证回撤曲线的生成"""
        executor = BacktestExecutor(
            config=sample_backtest_config,
            data_provider=duckdb_provider,
        )

        result = executor.run()
        drawdowns = executor.get_drawdown_curve()

        # 回撤曲线长度应该等于交易日数
        assert len(drawdowns) == result.trading_days

        # 所有回撤值应该在 [0, 1] 范围内
        for date_, dd in drawdowns:
            assert 0.0 <= dd <= 1.0, f"Invalid drawdown on {date_}: {dd}"


# ============================================================================
# PositionTracker Tests
# ============================================================================


class TestPositionLifecycle:
    """测试持仓生命周期"""

    def test_open_position(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证开仓功能 (使用新 API)"""
        # 开仓前
        assert position_tracker.position_count == 0

        # 使用 TradeSimulator 创建 TradeExecution
        execution = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,  # Short 1 put
            mid_price=3.50,
            trade_date=date(2024, 2, 1),
        )

        # 使用 open_position_from_execution 开仓
        position = position_tracker.open_position_from_execution(execution)

        # 开仓后
        assert position is not None
        assert position_tracker.position_count == 1
        assert position.position_id in position_tracker.positions

        # 验证 TradeSimulator 的交易记录
        assert len(trade_simulator.trade_records) == 1
        record = trade_simulator.trade_records[0]
        assert record.action == "open"
        assert record.symbol == execution.symbol

    def test_close_position(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证平仓功能 (使用新 API)"""
        # 先开仓
        open_exec = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=3.50,
            trade_date=date(2024, 2, 1),
        )
        position = position_tracker.open_position_from_execution(open_exec)
        assert position is not None

        # 平仓
        close_exec = trade_simulator.execute_close(
            symbol=position.symbol,
            underlying=position.underlying,
            option_type=position.option_type,
            strike=position.strike,
            expiration=position.expiration,
            quantity=1,  # Buy to close
            mid_price=2.00,  # 低于开仓价格，卖 put 盈利
            trade_date=date(2024, 2, 15),
        )
        pnl = position_tracker.close_position_from_execution(
            position.position_id, close_exec, close_reason="take_profit"
        )

        # 验证平仓结果
        assert pnl is not None
        assert position_tracker.position_count == 0
        assert len(trade_simulator.trade_records) == 2  # 开仓 + 平仓

        # 验证 P&L 计算
        # Short put: (close - entry) * quantity * lot - commission
        # (2.00 - 3.50) * (-1) * 100 - (1.00 + 1.00) = 150 - 2.00 = 148.00
        expected_pnl = (close_exec.fill_price - open_exec.fill_price) * position.quantity * position.lot_size
        expected_pnl -= (open_exec.commission + close_exec.commission)
        assert math.isclose(pnl, expected_pnl, rel_tol=0.01)

    def test_expire_position_otm(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证 OTM 期权到期处理 (使用新 API)"""
        # 开仓
        open_exec = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=2.00,
            trade_date=date(2024, 2, 1),
        )
        position = position_tracker.open_position_from_execution(open_exec)
        assert position is not None

        # 到期处理 (OTM: underlying_price > strike)
        expire_exec = trade_simulator.execute_expire(
            symbol=position.symbol,
            underlying=position.underlying,
            option_type=position.option_type,
            strike=position.strike,
            expiration=position.expiration,
            quantity=position.quantity,
            final_underlying_price=115.0,  # OTM
            trade_date=date(2024, 3, 15),
        )
        pnl = position_tracker.close_position_from_execution(
            position.position_id, expire_exec
        )

        # OTM 到期：收取全部权利金
        assert pnl is not None
        assert position_tracker.position_count == 0
        assert expire_exec.reason == "expired_worthless"

        # 验证 P&L: (0 - 2.00) * (-1) * 100 - 1.00 = 200 - 1.00 = 199.00
        expected_pnl = (0 - open_exec.fill_price) * position.quantity * position.lot_size
        expected_pnl -= open_exec.commission  # OTM 到期无手续费
        assert math.isclose(pnl, expected_pnl, rel_tol=0.01)

    def test_expire_position_itm(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证 ITM 期权到期处理 (使用新 API)"""
        # 开仓
        open_exec = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=2.00,
            trade_date=date(2024, 2, 1),
        )
        position = position_tracker.open_position_from_execution(open_exec)
        assert position is not None

        # 到期处理 (ITM: underlying_price < strike)
        expire_exec = trade_simulator.execute_expire(
            symbol=position.symbol,
            underlying=position.underlying,
            option_type=position.option_type,
            strike=position.strike,
            expiration=position.expiration,
            quantity=position.quantity,
            final_underlying_price=95.0,  # ITM: intrinsic = 100 - 95 = 5
            trade_date=date(2024, 3, 15),
        )
        pnl = position_tracker.close_position_from_execution(
            position.position_id, expire_exec
        )

        # ITM 到期：被行权
        assert pnl is not None
        assert position_tracker.position_count == 0
        assert expire_exec.reason == "assigned"

        # 验证 P&L: (intrinsic - entry) * qty * lot - commission
        # intrinsic = 5.00 (strike 100 - underlying 95)
        # (5.00 - 2.00) * (-1) * 100 - (1.00 + 1.00) = -300 - 2.00 = -302.00
        intrinsic = position.strike - 95.0
        expected_pnl = (intrinsic - open_exec.fill_price) * position.quantity * position.lot_size
        expected_pnl -= (open_exec.commission + expire_exec.commission)  # ITM 有 stock commission
        assert math.isclose(pnl, expected_pnl, rel_tol=0.01)


# ============================================================================
# AccountSimulator Tests
# ============================================================================


class TestAccountSimulatorMargin:
    """测试账户模拟器保证金计算 (使用新 API)"""

    def test_margin_calculation_short_put(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证 Short Put 保证金计算"""
        # 使用 TradeSimulator 创建 TradeExecution
        execution = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=2.00,
            trade_date=date(2024, 2, 1),
        )

        # 开仓
        position = position_tracker.open_position_from_execution(execution)
        assert position is not None

        # 验证保证金已计算
        assert position_tracker.account.margin_used > 0

        # Reg T Short Put 公式:
        # max(20% * S - OTM + Premium, 10% * K + Premium) * lot_size * qty
        # 在开仓时, underlying_price 未设置, 使用 strike 作为默认值
        # S = K = 100, Premium ≈ 2 (with slippage), OTM = 0 (ATM)
        # Method 1: 0.20 * 100 - 0 + premium ≈ 22
        # Method 2: 0.10 * 100 + premium ≈ 12
        # Margin = max(22, 12) * 100 ≈ 2200
        fill_price = execution.fill_price
        expected_margin = max(
            0.20 * 100.0 - 0.0 + fill_price,  # ATM, OTM = 0
            0.10 * 100.0 + fill_price,
        ) * 100 * 1
        assert math.isclose(
            position_tracker.account.margin_used,
            expected_margin,
            rel_tol=0.05,  # 允许 5% 误差
        )

    def test_nlv_calculation(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证 NLV 计算"""
        initial_nlv = position_tracker.account.nlv
        assert initial_nlv == 100_000.0

        # 卖出 put 收取权利金
        execution = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=2.00,
            trade_date=date(2024, 2, 1),
        )
        position = position_tracker.open_position_from_execution(execution)
        assert position is not None

        # 卖出收取权利金: 2.00 * 100 = 200
        # 扣除手续费: 200 - 1.00 = 199.00
        # Cash = 100000 + 199.00 = 100199.00
        expected_cash = 100_000.0 + execution.net_amount
        assert math.isclose(position_tracker.account.cash, expected_cash, rel_tol=0.01)

    def test_available_margin(
        self,
        position_tracker: PositionTracker,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证可用保证金计算"""
        # 初始可用保证金 = NLV * max_utilization = 100000 * 0.70 = 70000
        initial_available = position_tracker.account.available_margin
        assert initial_available == 100_000.0 * 0.70

        # 开仓后可用保证金减少
        execution = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=2.00,
            trade_date=date(2024, 2, 1),
        )
        position = position_tracker.open_position_from_execution(execution)
        assert position is not None

        # 可用保证金应该减少
        assert position_tracker.account.available_margin < initial_available


# ============================================================================
# TradeSimulator Tests
# ============================================================================


class TestTradeSimulatorSlippage:
    """测试交易模拟器滑点模型"""

    def test_slippage_model_basic(self) -> None:
        """验证基本滑点计算"""
        model = SlippageModel(base_pct=0.001, adjust_for_price=False)

        # 卖出 (价格降低)
        fill_price, slippage = model.calculate(mid_price=5.00, side=OrderSide.SELL)
        assert fill_price < 5.00
        assert slippage > 0
        assert math.isclose(slippage, 5.00 * 0.001, rel_tol=0.01)

        # 买入 (价格升高)
        fill_price, slippage = model.calculate(mid_price=5.00, side=OrderSide.BUY)
        assert fill_price > 5.00
        assert slippage > 0

    def test_slippage_model_price_adjusted(self) -> None:
        """验证价格分层滑点"""
        model = SlippageModel(
            base_pct=0.001,
            low_price_pct=0.05,
            high_price_pct=0.002,
            adjust_for_price=True,
        )

        # 低价期权 (< $0.50) 使用更高滑点
        fill_price, slippage = model.calculate(mid_price=0.30, side=OrderSide.SELL)
        slippage_pct = slippage / 0.30
        assert slippage_pct >= 0.04  # 应该接近 5%

        # 正常价格 ($0.50-$5) 使用基础滑点
        fill_price, slippage = model.calculate(mid_price=2.00, side=OrderSide.SELL)
        slippage_pct = slippage / 2.00
        assert slippage_pct <= 0.01  # 应该接近 0.1%

        # 高价期权 (> $5) 使用较低滑点
        fill_price, slippage = model.calculate(mid_price=10.00, side=OrderSide.SELL)
        slippage_pct = slippage / 10.00
        assert slippage_pct <= 0.005  # 应该接近 0.2%

    def test_commission_model(self) -> None:
        """验证手续费计算"""
        model = CommissionModel(option_per_contract=0.65, option_min_per_order=1.00)

        # 单张合约
        commission = model.calculate_option(contracts=1)
        assert commission == 1.00  # 最低手续费

        # 多张合约
        commission = model.calculate_option(contracts=10)
        assert commission == 6.50  # 10 * 0.65

    def test_trade_simulator_execution(
        self,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证交易执行"""
        execution = trade_simulator.execute_open(
            symbol="TEST 20240315 100P",
            underlying="TEST",
            option_type=OptionType.PUT,
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=-1,  # 卖出
            mid_price=2.00,
            trade_date=date(2024, 2, 1),
            reason="test",
        )

        assert execution is not None
        assert execution.side == OrderSide.SELL
        assert execution.quantity == -1  # 有符号: 负数=卖出
        assert execution.fill_price < 2.00  # 卖出价格低于 mid
        assert execution.slippage > 0
        assert execution.commission > 0

    def test_total_slippage_and_commission(
        self,
        trade_simulator: TradeSimulator,
    ) -> None:
        """验证总滑点和手续费统计"""
        # 执行多笔交易
        for i in range(3):
            trade_simulator.execute_open(
                symbol=f"TEST{i} 20240315 100P",
                underlying=f"TEST{i}",
                option_type=OptionType.PUT,
                strike=100.0,
                expiration=date(2024, 3, 15),
                quantity=-1,
                mid_price=2.00,
                trade_date=date(2024, 2, 1),
            )

        assert trade_simulator.get_total_slippage() > 0
        assert trade_simulator.get_total_commission() > 0
        assert len(trade_simulator.executions) == 3


# ============================================================================
# Integration with Real Data (Optional)
# ============================================================================


class TestWithRealData:
    """使用真实数据的测试（需要外部数据）"""

    @pytest.fixture
    def real_data_dir(self) -> Path | None:
        """获取真实数据目录"""
        data_dir = Path("/Volumes/ORICO/option_quant")
        if data_dir.exists():
            return data_dir
        return None

    @pytest.mark.skipif(
        not Path("/Volumes/ORICO/option_quant").exists(),
        reason="Real data directory not available",
    )
    def test_run_with_real_data(self, real_data_dir: Path) -> None:
        """使用真实历史数据运行回测"""
        if real_data_dir is None:
            pytest.skip("Real data directory not available")

        # 使用真实数据的日期范围
        config = BacktestConfig(
            name="TEST_REAL_DATA",
            start_date=date(2026, 1, 27),  # 数据起始日
            end_date=date(2026, 2, 2),     # 数据结束日
            symbols=["GOOG"],
            strategy_type=StrategyType.SHORT_PUT,
            initial_capital=100_000.0,
            max_margin_utilization=0.70,
            max_positions=5,
            slippage_pct=0.001,
            commission_per_contract=0.65,
            data_dir=real_data_dir,
        )

        executor = BacktestExecutor(config)
        result = executor.run()

        # 基本验证
        assert result is not None
        assert result.trading_days > 0
        assert len(result.daily_snapshots) == result.trading_days
        print(f"\n=== Real Data Backtest Results ===")
        print(f"Trading Days: {result.trading_days}")
        print(f"Total Return: {result.total_return_pct:.2%}")
        print(f"Final NLV: ${result.final_nlv:,.2f}")
        print(f"Total Trades: {result.total_trades}")

    @pytest.mark.skipif(
        not Path("/Volumes/ORICO/option_quant").exists(),
        reason="Real data directory not available",
    )
    def test_duckdb_provider_with_real_data(self, real_data_dir: Path) -> None:
        """验证 DuckDBProvider 能读取真实数据"""
        if real_data_dir is None:
            pytest.skip("Real data directory not available")

        provider = DuckDBProvider(
            data_dir=real_data_dir,
            as_of_date=date(2026, 2, 2),
        )

        # 测试股票报价
        quote = provider.get_stock_quote("GOOG")
        assert quote is not None
        assert quote.close > 0
        print(f"\nGOOG Quote: ${quote.close:.2f}")

        # 测试期权链
        chain = provider.get_option_chain(
            underlying="GOOG",
            expiry_start=date(2026, 2, 1),
            expiry_end=date(2026, 3, 31),
        )
        assert chain is not None
        print(f"Option Chain: {len(chain.calls)} calls, {len(chain.puts)} puts")

        # 测试交易日
        trading_days = provider.get_trading_days(
            start_date=date(2026, 1, 22),
            end_date=date(2026, 2, 2),
        )
        assert len(trading_days) > 0
        print(f"Trading Days: {len(trading_days)}")
