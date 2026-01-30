"""Backtest optimization module.

Provides performance optimization and validation tools:
- Parallel backtest execution
- Parameter sweep and grid search
- Benchmark comparison
- Walk-forward validation
"""

from src.backtest.optimization.parallel_runner import ParallelBacktestRunner
from src.backtest.optimization.parameter_sweep import ParameterSweep, SweepResult
from src.backtest.optimization.benchmark import BenchmarkComparison, BenchmarkResult
from src.backtest.optimization.walk_forward import WalkForwardValidator, WalkForwardResult

__all__ = [
    "ParallelBacktestRunner",
    "ParameterSweep",
    "SweepResult",
    "BenchmarkComparison",
    "BenchmarkResult",
    "WalkForwardValidator",
    "WalkForwardResult",
]
