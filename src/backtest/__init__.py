"""
Backtest Module - 策略回测系统

提供期权策略的历史回测能力，最大化复用现有 ScreeningPipeline/MonitoringPipeline。

模块结构:
- config/: 回测配置
- data/: ThetaData 客户端、数据下载器、DuckDB 提供者
- engine/: 回测执行器、账户/持仓/交易模拟器
- analysis/: 指标计算、交易分析
- visualization/: Plotly 仪表板
- optimization/: 并行执行、参数优化、基准比较、滚动验证
- cli/: CLI 命令

Usage:
    from src.backtest import BacktestConfig, DuckDBProvider

    # 配置回测
    config = BacktestConfig(
        name="SHORT_PUT_2020_2024",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        symbols=["AAPL", "MSFT"],
    )

    # 使用 DuckDB 提供数据
    provider = DuckDBProvider(
        data_dir=config.data_dir,
        as_of_date=config.start_date,
    )
"""

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.data.thetadata_client import ThetaDataClient
from src.backtest.data.data_downloader import DataDownloader
from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.position_manager import PositionManager
from src.backtest.engine.trade_simulator import TradeSimulator

# 向后兼容：PositionTracker 是旧名称，现已重命名为 PositionManager
PositionTracker = PositionManager
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult, run_backtest
from src.backtest.analysis.metrics import BacktestMetrics
from src.backtest.analysis.trade_analyzer import TradeAnalyzer
from src.backtest.visualization.dashboard import BacktestDashboard
from src.backtest.optimization.parallel_runner import ParallelBacktestRunner
from src.backtest.optimization.parameter_sweep import ParameterSweep, SweepResult
from src.backtest.optimization.benchmark import BenchmarkComparison, BenchmarkResult
from src.backtest.optimization.walk_forward import WalkForwardValidator, WalkForwardResult
from src.backtest.pipeline import BacktestPipeline, PipelineResult, DataStatus
from src.backtest.data.data_checker import DataChecker, DataGap

__all__ = [
    # Config
    "BacktestConfig",
    # Data
    "DuckDBProvider",
    "ThetaDataClient",
    "DataDownloader",
    # Engine
    "AccountSimulator",
    "SimulatedPosition",
    "PositionManager",
    "PositionTracker",  # 向后兼容别名
    "TradeSimulator",
    "BacktestExecutor",
    "BacktestResult",
    "run_backtest",
    # Analysis
    "BacktestMetrics",
    "TradeAnalyzer",
    # Visualization
    "BacktestDashboard",
    # Optimization
    "ParallelBacktestRunner",
    "ParameterSweep",
    "SweepResult",
    "BenchmarkComparison",
    "BenchmarkResult",
    "WalkForwardValidator",
    "WalkForwardResult",
    # Pipeline
    "BacktestPipeline",
    "PipelineResult",
    "DataStatus",
    "DataChecker",
    "DataGap",
]
