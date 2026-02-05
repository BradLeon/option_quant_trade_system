"""Backtest engine module - Account, Position, Trade simulators and Executor.

组件架构 (BacktestExecutor 直接访问所有组件):
- Trade 层: TradeSimulator (滑点计算、手续费、交易记录)
- Position 层: PositionManager (创建持仓、计算 margin、计算 PnL、市场数据更新)
- Account 层: AccountSimulator (现金管理、保证金检查、持仓存储、权益快照)
"""

from src.backtest.engine.account_simulator import (
    AccountSimulator,
    EquitySnapshot,
    SimulatedPosition,
)
from src.backtest.engine.position_manager import (
    DataNotFoundError,
    PositionManager,
    PositionPnL,
)
from src.backtest.engine.trade_simulator import (
    CommissionModel,
    ExecutionStatus,
    OrderSide,
    SlippageModel,
    TradeExecution,
    TradeRecord,
    TradeSimulator,
)
from src.backtest.engine.backtest_executor import (
    BacktestExecutor,
    BacktestResult,
    DailySnapshot,
    run_backtest,
)

# 向后兼容: PositionTracker 是旧名称，现已重命名为 PositionManager
PositionTracker = PositionManager

__all__ = [
    # Account Simulator
    "AccountSimulator",
    "EquitySnapshot",
    "SimulatedPosition",
    # Position Manager
    "DataNotFoundError",
    "PositionManager",
    "PositionPnL",
    "PositionTracker",  # 向后兼容别名
    # Trade Simulator
    "CommissionModel",
    "ExecutionStatus",
    "OrderSide",
    "SlippageModel",
    "TradeExecution",
    "TradeRecord",
    "TradeSimulator",
    # Backtest Executor
    "BacktestExecutor",
    "BacktestResult",
    "DailySnapshot",
    "run_backtest",
]
