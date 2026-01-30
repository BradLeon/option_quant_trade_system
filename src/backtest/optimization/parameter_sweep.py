"""
Parameter Sweep - 参数优化

提供参数网格搜索和优化功能:
- DTE 范围优化
- Delta 范围优化
- 仓位大小优化
- 多参数组合搜索

Usage:
    from src.backtest.optimization import ParameterSweep

    sweep = ParameterSweep(base_config)
    sweep.add_param("dte_min", [30, 45, 60])
    sweep.add_param("dte_max", [45, 60, 90])
    results = sweep.run()
"""

import itertools
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.engine.backtest_executor import BacktestResult
from src.backtest.analysis.metrics import BacktestMetrics
from src.backtest.optimization.parallel_runner import ParallelBacktestRunner

logger = logging.getLogger(__name__)


@dataclass
class ParameterSet:
    """参数组合"""

    params: dict[str, Any]
    config_name: str = ""

    def __post_init__(self):
        if not self.config_name:
            # 生成名称
            parts = [f"{k}={v}" for k, v in sorted(self.params.items())]
            self.config_name = "_".join(parts)


@dataclass
class SweepResult:
    """参数搜索结果"""

    # 所有参数组合的结果
    results: list[tuple[ParameterSet, BacktestResult, BacktestMetrics]] = field(
        default_factory=list
    )

    # 最佳参数 (按不同指标)
    best_by_return: ParameterSet | None = None
    best_by_sharpe: ParameterSet | None = None
    best_by_sortino: ParameterSet | None = None
    best_by_calmar: ParameterSet | None = None

    # 搜索信息
    total_combinations: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    execution_time_seconds: float = 0.0

    # 参数范围
    param_ranges: dict[str, list[Any]] = field(default_factory=dict)

    def get_results_dataframe(self):
        """转换为 pandas DataFrame"""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas required for get_results_dataframe()")

        data = []
        for param_set, result, metrics in self.results:
            row = {
                "config_name": param_set.config_name,
                **param_set.params,
                "total_return": result.total_return,
                "total_return_pct": result.total_return_pct,
                "sharpe_ratio": metrics.sharpe_ratio,
                "sortino_ratio": metrics.sortino_ratio,
                "calmar_ratio": metrics.calmar_ratio,
                "max_drawdown": metrics.max_drawdown,
                "win_rate": metrics.win_rate,
                "total_trades": result.total_trades,
                "profit_factor": metrics.profit_factor,
            }
            data.append(row)

        return pd.DataFrame(data)

    def get_heatmap_data(
        self,
        x_param: str,
        y_param: str,
        metric: str = "sharpe_ratio",
    ) -> tuple[list, list, list[list]]:
        """获取热力图数据

        Args:
            x_param: X 轴参数名
            y_param: Y 轴参数名
            metric: 指标名

        Returns:
            (x_values, y_values, z_matrix)
        """
        if x_param not in self.param_ranges or y_param not in self.param_ranges:
            raise ValueError(f"Parameters {x_param}, {y_param} not in sweep")

        x_values = sorted(set(self.param_ranges[x_param]))
        y_values = sorted(set(self.param_ranges[y_param]))

        # 创建查找表
        lookup = {}
        for param_set, result, metrics in self.results:
            key = (param_set.params.get(x_param), param_set.params.get(y_param))
            value = getattr(metrics, metric, None)
            if value is None:
                value = getattr(result, metric, None)
            lookup[key] = value

        # 构建矩阵
        z_matrix = []
        for y in y_values:
            row = []
            for x in x_values:
                row.append(lookup.get((x, y)))
            z_matrix.append(row)

        return x_values, y_values, z_matrix

    def summary(self) -> str:
        """生成搜索摘要"""
        lines = [
            "=== Parameter Sweep Summary ===",
            f"Total combinations: {self.total_combinations}",
            f"Successful: {self.successful_runs}, Failed: {self.failed_runs}",
            f"Execution time: {self.execution_time_seconds:.1f}s",
            "",
            "Parameter ranges:",
        ]

        for param, values in self.param_ranges.items():
            lines.append(f"  {param}: {values}")

        lines.append("")
        lines.append("Best parameters:")

        if self.best_by_return:
            lines.append(f"  By Return: {self.best_by_return.params}")
        if self.best_by_sharpe:
            lines.append(f"  By Sharpe: {self.best_by_sharpe.params}")
        if self.best_by_sortino:
            lines.append(f"  By Sortino: {self.best_by_sortino.params}")
        if self.best_by_calmar:
            lines.append(f"  By Calmar: {self.best_by_calmar.params}")

        return "\n".join(lines)


class ParameterSweep:
    """参数搜索器

    支持多参数网格搜索，找到最优参数组合。

    Usage:
        sweep = ParameterSweep(base_config)
        sweep.add_param("max_position_pct", [0.05, 0.10, 0.15])
        sweep.add_param("max_positions", [5, 10, 15])
        results = sweep.run(max_workers=4)
    """

    def __init__(
        self,
        base_config: BacktestConfig,
        config_modifier: Callable[[BacktestConfig, dict], BacktestConfig] | None = None,
    ) -> None:
        """初始化参数搜索器

        Args:
            base_config: 基础回测配置
            config_modifier: 自定义配置修改函数
        """
        self._base_config = base_config
        self._config_modifier = config_modifier
        self._param_ranges: dict[str, list[Any]] = {}

    def add_param(self, name: str, values: list[Any]) -> "ParameterSweep":
        """添加要搜索的参数

        Args:
            name: 参数名 (必须是 BacktestConfig 的属性)
            values: 参数值列表

        Returns:
            self (支持链式调用)
        """
        self._param_ranges[name] = values
        return self

    def add_dte_range(
        self,
        min_values: list[int] = [30, 45],
        max_values: list[int] = [45, 60, 90],
    ) -> "ParameterSweep":
        """添加 DTE 范围参数

        注意: 这需要 ScreeningConfig 支持，此处仅作为示例。
        """
        self._param_ranges["dte_min"] = min_values
        self._param_ranges["dte_max"] = max_values
        return self

    def add_position_sizing(
        self,
        max_position_pcts: list[float] = [0.05, 0.10, 0.15],
        max_positions_list: list[int] = [5, 10, 15],
    ) -> "ParameterSweep":
        """添加仓位大小参数"""
        self._param_ranges["max_position_pct"] = max_position_pcts
        self._param_ranges["max_positions"] = max_positions_list
        return self

    def _generate_combinations(self) -> list[ParameterSet]:
        """生成所有参数组合"""
        if not self._param_ranges:
            return [ParameterSet(params={})]

        keys = list(self._param_ranges.keys())
        values = [self._param_ranges[k] for k in keys]

        combinations = []
        for combo in itertools.product(*values):
            params = dict(zip(keys, combo))
            combinations.append(ParameterSet(params=params))

        return combinations

    def _create_config(self, param_set: ParameterSet) -> BacktestConfig:
        """根据参数组合创建配置"""
        # 复制基础配置
        config = BacktestConfig(
            name=f"{self._base_config.name}_{param_set.config_name}",
            start_date=self._base_config.start_date,
            end_date=self._base_config.end_date,
            symbols=self._base_config.symbols.copy(),
            strategy_type=self._base_config.strategy_type,
            initial_capital=self._base_config.initial_capital,
            max_margin_utilization=self._base_config.max_margin_utilization,
            max_position_pct=self._base_config.max_position_pct,
            max_positions=self._base_config.max_positions,
            slippage_pct=self._base_config.slippage_pct,
            commission_per_contract=self._base_config.commission_per_contract,
            data_dir=self._base_config.data_dir,
        )

        # 应用参数
        for key, value in param_set.params.items():
            if hasattr(config, key):
                setattr(config, key, value)

        # 自定义修改
        if self._config_modifier:
            config = self._config_modifier(config, param_set.params)

        return config

    def run(
        self,
        max_workers: int = 4,
        use_parallel: bool = True,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> SweepResult:
        """运行参数搜索

        Args:
            max_workers: 并行工作数
            use_parallel: 是否使用并行
            progress_callback: 进度回调

        Returns:
            SweepResult
        """
        import time

        start_time = time.time()

        # 生成所有参数组合
        combinations = self._generate_combinations()
        logger.info(f"Generated {len(combinations)} parameter combinations")

        # 创建配置列表
        configs = []
        param_sets = []
        for param_set in combinations:
            config = self._create_config(param_set)
            configs.append(config)
            param_sets.append(param_set)

        # 运行回测
        if use_parallel and len(configs) > 1:
            runner = ParallelBacktestRunner(max_workers=max_workers)
            run_result = runner.run_multi_config(configs, progress_callback)
        else:
            runner = ParallelBacktestRunner(max_workers=1)
            run_result = runner.run_sequential(configs, progress_callback)

        # 整理结果
        result = SweepResult(
            total_combinations=len(combinations),
            param_ranges=self._param_ranges.copy(),
        )

        best_return = float("-inf")
        best_sharpe = float("-inf")
        best_sortino = float("-inf")
        best_calmar = float("-inf")

        for param_set, config in zip(param_sets, configs):
            if config.name in run_result.results:
                bt_result = run_result.results[config.name]
                metrics = BacktestMetrics.from_backtest_result(bt_result)

                result.results.append((param_set, bt_result, metrics))
                result.successful_runs += 1

                # 更新最佳参数
                if bt_result.total_return > best_return:
                    best_return = bt_result.total_return
                    result.best_by_return = param_set

                if metrics.sharpe_ratio is not None and metrics.sharpe_ratio > best_sharpe:
                    best_sharpe = metrics.sharpe_ratio
                    result.best_by_sharpe = param_set

                if metrics.sortino_ratio is not None and metrics.sortino_ratio > best_sortino:
                    best_sortino = metrics.sortino_ratio
                    result.best_by_sortino = param_set

                if metrics.calmar_ratio is not None and metrics.calmar_ratio > best_calmar:
                    best_calmar = metrics.calmar_ratio
                    result.best_by_calmar = param_set

            elif config.name in run_result.errors:
                result.failed_runs += 1
                logger.warning(f"Failed: {config.name} - {run_result.errors[config.name]}")

        result.execution_time_seconds = time.time() - start_time

        return result

    def run_grid_search(
        self,
        param1_name: str,
        param1_values: list[Any],
        param2_name: str,
        param2_values: list[Any],
        **kwargs,
    ) -> SweepResult:
        """便捷的双参数网格搜索

        Args:
            param1_name: 第一个参数名
            param1_values: 第一个参数值列表
            param2_name: 第二个参数名
            param2_values: 第二个参数值列表
            **kwargs: 传递给 run() 的参数

        Returns:
            SweepResult
        """
        self._param_ranges.clear()
        self.add_param(param1_name, param1_values)
        self.add_param(param2_name, param2_values)
        return self.run(**kwargs)
