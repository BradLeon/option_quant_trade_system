"""
Parallel Backtest Runner - 并行回测执行器

支持多标的/多参数的并行回测执行，提高回测效率。

Features:
- 多进程并行执行
- 进度追踪
- 结果聚合
- 资源管理

Usage:
    from src.backtest.optimization import ParallelBacktestRunner

    runner = ParallelBacktestRunner(max_workers=4)
    results = runner.run_multi_symbol(config, symbols)
"""

import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult
from src.backtest.data.duckdb_provider import DuckDBProvider

logger = logging.getLogger(__name__)


@dataclass
class ParallelRunResult:
    """并行回测结果"""

    # 成功的结果
    results: dict[str, BacktestResult] = field(default_factory=dict)

    # 失败的任务
    errors: dict[str, str] = field(default_factory=dict)

    # 执行信息
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    execution_time_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks

    def get_aggregated_metrics(self) -> dict:
        """聚合所有成功结果的指标"""
        if not self.results:
            return {}

        total_return = sum(r.total_return for r in self.results.values())
        total_trades = sum(r.total_trades for r in self.results.values())
        total_commission = sum(r.total_commission for r in self.results.values())

        # 加权平均胜率
        weighted_win_rate = 0.0
        total_trade_count = 0
        for r in self.results.values():
            if r.total_trades > 0:
                weighted_win_rate += r.win_rate * r.total_trades
                total_trade_count += r.total_trades

        avg_win_rate = weighted_win_rate / total_trade_count if total_trade_count > 0 else 0

        return {
            "symbols_count": len(self.results),
            "total_return": total_return,
            "total_trades": total_trades,
            "total_commission": total_commission,
            "avg_win_rate": avg_win_rate,
        }


def _run_single_backtest(args: tuple) -> tuple[str, BacktestResult | None, str | None]:
    """单个回测任务 (用于进程池)

    Args:
        args: (task_id, config_dict, data_dir)

    Returns:
        (task_id, result, error)
    """
    task_id, config_dict, data_dir_str = args

    try:
        # 重建配置 (因为跨进程序列化)
        from src.backtest.config.backtest_config import BacktestConfig
        from src.backtest.data.duckdb_provider import DuckDBProvider
        from src.backtest.engine.backtest_executor import BacktestExecutor
        from src.engine.models.enums import StrategyType

        config = BacktestConfig(
            name=config_dict["name"],
            start_date=date.fromisoformat(config_dict["start_date"]),
            end_date=date.fromisoformat(config_dict["end_date"]),
            symbols=config_dict["symbols"],
            strategy_type=StrategyType(config_dict["strategy_type"]),
            initial_capital=config_dict.get("initial_capital", 100000.0),
            max_margin_utilization=config_dict.get("max_margin_utilization", 0.70),
            max_position_pct=config_dict.get("max_position_pct", 0.10),
            max_positions=config_dict.get("max_positions", 10),
            slippage_pct=config_dict.get("slippage_pct", 0.001),
            commission_per_contract=config_dict.get("commission_per_contract", 0.65),
            data_dir=Path(data_dir_str),
        )

        provider = DuckDBProvider(
            data_dir=config.data_dir,
            as_of_date=config.start_date,
        )

        executor = BacktestExecutor(config=config, data_provider=provider)
        result = executor.run()

        return (task_id, result, None)

    except Exception as e:
        return (task_id, None, str(e))


class ParallelBacktestRunner:
    """并行回测执行器

    支持多标的和多参数的并行回测。

    Usage:
        runner = ParallelBacktestRunner(max_workers=4)

        # 多标的并行
        results = runner.run_multi_symbol(base_config, symbols)

        # 多参数并行
        results = runner.run_multi_config(configs)
    """

    def __init__(
        self,
        max_workers: int | None = None,
        use_processes: bool = True,
    ) -> None:
        """初始化并行执行器

        Args:
            max_workers: 最大并行数 (默认 CPU 核心数)
            use_processes: 使用多进程 (True) 或多线程 (False)
        """
        import os

        self._max_workers = max_workers or min(os.cpu_count() or 4, 8)
        self._use_processes = use_processes

    def run_multi_symbol(
        self,
        base_config: BacktestConfig,
        symbols: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ParallelRunResult:
        """多标的并行回测

        为每个标的单独运行回测。

        Args:
            base_config: 基础配置
            symbols: 标的列表
            progress_callback: 进度回调 (completed, total)

        Returns:
            ParallelRunResult
        """
        import time

        start_time = time.time()

        # 为每个标的创建配置
        tasks = []
        for symbol in symbols:
            # 使用 strategy_types (新字段) 而不是 strategy_type (已废弃)
            strategy_types = [st.value for st in base_config.strategy_types]
            config_dict = {
                "name": f"{base_config.name}_{symbol}",
                "start_date": base_config.start_date.isoformat(),
                "end_date": base_config.end_date.isoformat(),
                "symbols": [symbol],
                "strategy_types": strategy_types,
                "initial_capital": base_config.initial_capital,
                "max_margin_utilization": base_config.max_margin_utilization,
                "max_position_pct": base_config.max_position_pct,
                "max_positions": base_config.max_positions,
                "slippage_pct": base_config.slippage_pct,
                "commission_per_contract": base_config.commission_per_contract,
            }
            tasks.append((symbol, config_dict, str(base_config.data_dir)))

        # 执行并行任务
        result = self._run_parallel(tasks, progress_callback)
        result.execution_time_seconds = time.time() - start_time

        return result

    def run_multi_config(
        self,
        configs: list[BacktestConfig],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ParallelRunResult:
        """多配置并行回测

        Args:
            configs: 配置列表
            progress_callback: 进度回调

        Returns:
            ParallelRunResult
        """
        import time

        start_time = time.time()

        # 创建任务
        tasks = []
        for config in configs:
            # 使用 strategy_types (新字段) 而不是 strategy_type (已废弃)
            strategy_types = [st.value for st in config.strategy_types]
            config_dict = {
                "name": config.name,
                "start_date": config.start_date.isoformat(),
                "end_date": config.end_date.isoformat(),
                "symbols": config.symbols,
                "strategy_types": strategy_types,
                "initial_capital": config.initial_capital,
                "max_margin_utilization": config.max_margin_utilization,
                "max_position_pct": config.max_position_pct,
                "max_positions": config.max_positions,
                "slippage_pct": config.slippage_pct,
                "commission_per_contract": config.commission_per_contract,
            }
            tasks.append((config.name, config_dict, str(config.data_dir)))

        # 执行
        result = self._run_parallel(tasks, progress_callback)
        result.execution_time_seconds = time.time() - start_time

        return result

    def _run_parallel(
        self,
        tasks: list[tuple],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ParallelRunResult:
        """执行并行任务

        Args:
            tasks: 任务列表 [(task_id, config_dict, data_dir), ...]
            progress_callback: 进度回调

        Returns:
            ParallelRunResult
        """
        result = ParallelRunResult(total_tasks=len(tasks))

        if not tasks:
            return result

        # 选择执行器
        executor_class = ProcessPoolExecutor if self._use_processes else ThreadPoolExecutor

        completed = 0
        with executor_class(max_workers=self._max_workers) as executor:
            # 提交所有任务
            futures = {
                executor.submit(_run_single_backtest, task): task[0]
                for task in tasks
            }

            # 收集结果
            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    tid, bt_result, error = future.result()

                    if bt_result is not None:
                        result.results[tid] = bt_result
                        result.completed_tasks += 1
                    else:
                        result.errors[tid] = error or "Unknown error"
                        result.failed_tasks += 1

                except Exception as e:
                    result.errors[task_id] = str(e)
                    result.failed_tasks += 1

                completed += 1
                if progress_callback:
                    progress_callback(completed, len(tasks))

        return result

    def run_sequential(
        self,
        configs: list[BacktestConfig],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ParallelRunResult:
        """顺序执行回测 (用于调试或低内存环境)

        Args:
            configs: 配置列表
            progress_callback: 进度回调

        Returns:
            ParallelRunResult
        """
        import time

        start_time = time.time()
        result = ParallelRunResult(total_tasks=len(configs))

        for i, config in enumerate(configs):
            try:
                provider = DuckDBProvider(
                    data_dir=config.data_dir,
                    as_of_date=config.start_date,
                )

                executor = BacktestExecutor(config=config, data_provider=provider)
                bt_result = executor.run()

                result.results[config.name] = bt_result
                result.completed_tasks += 1

            except Exception as e:
                result.errors[config.name] = str(e)
                result.failed_tasks += 1

            if progress_callback:
                progress_callback(i + 1, len(configs))

        result.execution_time_seconds = time.time() - start_time
        return result
