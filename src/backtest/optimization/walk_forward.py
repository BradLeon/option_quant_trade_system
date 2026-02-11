"""
Walk-Forward Validation - 滚动验证

提供策略的样本外验证能力，检测过拟合:
- 训练/测试集分割
- 滚动窗口验证
- 样本外绩效分析
- 过拟合检测报告

Usage:
    from src.backtest.optimization import WalkForwardValidator

    validator = WalkForwardValidator(config, data_provider)
    result = validator.run(
        train_months=12,
        test_months=3,
        n_splits=4,
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from dateutil.relativedelta import relativedelta

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.backtest_executor import BacktestExecutor, BacktestResult
from src.backtest.analysis.metrics import BacktestMetrics

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardSplit:
    """单次分割结果"""

    split_index: int

    # 训练期
    train_start: date
    train_end: date

    # 测试期
    test_start: date
    test_end: date

    # 训练/测试结果 (运行后填充)
    train_result: BacktestResult | None = None
    train_metrics: BacktestMetrics | None = None
    test_result: BacktestResult | None = None
    test_metrics: BacktestMetrics | None = None

    # 性能衰减
    return_decay: float | None = None  # (测试收益 - 训练收益) / 训练收益
    sharpe_decay: float | None = None
    win_rate_decay: float | None = None

    @property
    def train_period(self) -> str:
        return f"{self.train_start} ~ {self.train_end}"

    @property
    def test_period(self) -> str:
        return f"{self.test_start} ~ {self.test_end}"

    def __post_init__(self):
        if self.train_metrics and self.test_metrics:
            self._calc_decay()

    def _calc_decay(self):
        """计算性能衰减"""
        if self.train_metrics.total_return_pct != 0:
            train_pct = self.train_metrics.total_return_pct
            test_pct = self.test_metrics.total_return_pct
            self.return_decay = (test_pct - train_pct) / abs(train_pct) if train_pct != 0 else None

        if self.train_metrics.sharpe_ratio and self.test_metrics.sharpe_ratio:
            train_sharpe = self.train_metrics.sharpe_ratio
            test_sharpe = self.test_metrics.sharpe_ratio
            self.sharpe_decay = (test_sharpe - train_sharpe) / abs(train_sharpe) if train_sharpe != 0 else None

        if self.train_metrics.win_rate and self.test_metrics.win_rate:
            train_wr = self.train_metrics.win_rate
            test_wr = self.test_metrics.win_rate
            self.win_rate_decay = (test_wr - train_wr) / train_wr if train_wr != 0 else None


@dataclass
class WalkForwardResult:
    """滚动验证结果"""

    # 分割结果
    splits: list[WalkForwardSplit] = field(default_factory=list)

    # 总体样本内 (In-Sample) 指标
    is_total_return: float = 0.0
    is_avg_sharpe: float | None = None
    is_avg_win_rate: float | None = None

    # 总体样本外 (Out-of-Sample) 指标
    oos_total_return: float = 0.0
    oos_avg_sharpe: float | None = None
    oos_avg_win_rate: float | None = None

    # 过拟合指标
    avg_return_decay: float | None = None
    avg_sharpe_decay: float | None = None
    overfitting_score: float | None = None  # 0-1, 越高越可能过拟合

    # 一致性指标
    oos_positive_pct: float = 0.0  # OOS 正收益的分割比例
    oos_consistent_sharpe: float = 0.0  # OOS Sharpe > 0 的分割比例

    # 执行信息
    n_splits: int = 0
    train_months: int = 0
    test_months: int = 0
    execution_time_seconds: float = 0.0

    def summary(self) -> str:
        """生成验证摘要"""
        lines = [
            "=== Walk-Forward Validation Summary ===",
            f"Splits: {self.n_splits}",
            f"Train Period: {self.train_months} months",
            f"Test Period: {self.test_months} months",
            "",
            "--- In-Sample (Training) ---",
            f"  Total Return:  {self.is_total_return:.2%}",
            f"  Avg Sharpe:    {self.is_avg_sharpe:.2f}" if self.is_avg_sharpe else "  Avg Sharpe:    N/A",
            f"  Avg Win Rate:  {self.is_avg_win_rate:.1%}" if self.is_avg_win_rate else "  Avg Win Rate:  N/A",
            "",
            "--- Out-of-Sample (Testing) ---",
            f"  Total Return:  {self.oos_total_return:.2%}",
            f"  Avg Sharpe:    {self.oos_avg_sharpe:.2f}" if self.oos_avg_sharpe else "  Avg Sharpe:    N/A",
            f"  Avg Win Rate:  {self.oos_avg_win_rate:.1%}" if self.oos_avg_win_rate else "  Avg Win Rate:  N/A",
            "",
            "--- Overfitting Analysis ---",
            f"  Return Decay:     {self.avg_return_decay:.1%}" if self.avg_return_decay else "  Return Decay:     N/A",
            f"  Sharpe Decay:     {self.avg_sharpe_decay:.1%}" if self.avg_sharpe_decay else "  Sharpe Decay:     N/A",
            f"  Overfitting Score: {self.overfitting_score:.2f}" if self.overfitting_score else "  Overfitting Score: N/A",
            "",
            "--- Consistency ---",
            f"  OOS Positive %:   {self.oos_positive_pct:.0%}",
            f"  OOS Sharpe > 0:   {self.oos_consistent_sharpe:.0%}",
        ]

        # 风险评估
        lines.append("")
        if self.overfitting_score is not None:
            if self.overfitting_score < 0.3:
                lines.append("Assessment: LOW overfitting risk")
            elif self.overfitting_score < 0.6:
                lines.append("Assessment: MODERATE overfitting risk")
            else:
                lines.append("Assessment: HIGH overfitting risk - strategy may not generalize well")

        return "\n".join(lines)

    def get_splits_dataframe(self):
        """转换为 DataFrame"""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas required")

        data = []
        for split in self.splits:
            row = {
                "split": split.split_index,
                "train_period": split.train_period,
                "test_period": split.test_period,
                "train_return": split.train_metrics.total_return_pct if split.train_metrics else None,
                "test_return": split.test_metrics.total_return_pct if split.test_metrics else None,
                "train_sharpe": split.train_metrics.sharpe_ratio if split.train_metrics else None,
                "test_sharpe": split.test_metrics.sharpe_ratio if split.test_metrics else None,
                "return_decay": split.return_decay,
                "sharpe_decay": split.sharpe_decay,
            }
            data.append(row)

        return pd.DataFrame(data)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "n_splits": self.n_splits,
            "train_months": self.train_months,
            "test_months": self.test_months,
            "is_total_return": self.is_total_return,
            "is_avg_sharpe": self.is_avg_sharpe,
            "oos_total_return": self.oos_total_return,
            "oos_avg_sharpe": self.oos_avg_sharpe,
            "avg_return_decay": self.avg_return_decay,
            "avg_sharpe_decay": self.avg_sharpe_decay,
            "overfitting_score": self.overfitting_score,
            "oos_positive_pct": self.oos_positive_pct,
            "oos_consistent_sharpe": self.oos_consistent_sharpe,
        }


class WalkForwardValidator:
    """滚动验证器

    执行 Walk-Forward 分析来检测策略过拟合。

    Usage:
        validator = WalkForwardValidator(config, data_provider)
        result = validator.run(
            train_months=12,
            test_months=3,
            n_splits=4,
        )
    """

    def __init__(
        self,
        base_config: BacktestConfig,
        data_provider: DuckDBProvider | None = None,
    ) -> None:
        """初始化验证器

        Args:
            base_config: 基础回测配置
            data_provider: 数据提供者 (可选)
        """
        self._base_config = base_config
        self._data_provider = data_provider

    def run(
        self,
        train_months: int = 12,
        test_months: int = 3,
        n_splits: int | None = None,
        overlap_months: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> WalkForwardResult:
        """运行滚动验证

        Args:
            train_months: 训练期月数
            test_months: 测试期月数
            n_splits: 分割数 (默认自动计算)
            overlap_months: 重叠月数 (默认 0 表示无重叠)
            progress_callback: 进度回调

        Returns:
            WalkForwardResult
        """
        import time

        start_time = time.time()

        # 生成分割
        splits = self._generate_splits(
            train_months, test_months, n_splits, overlap_months
        )

        if not splits:
            raise ValueError("Could not generate any valid splits")

        logger.info(f"Generated {len(splits)} walk-forward splits")

        result = WalkForwardResult(
            n_splits=len(splits),
            train_months=train_months,
            test_months=test_months,
        )

        # 执行每个分割
        for i, split in enumerate(splits):
            try:
                self._run_split(split)
                result.splits.append(split)

            except Exception as e:
                logger.warning(f"Split {i} failed: {e}")

            if progress_callback:
                progress_callback(i + 1, len(splits))

        # 计算汇总指标
        self._calc_summary(result)

        result.execution_time_seconds = time.time() - start_time
        return result

    def _generate_splits(
        self,
        train_months: int,
        test_months: int,
        n_splits: int | None,
        overlap_months: int,
    ) -> list[WalkForwardSplit]:
        """生成分割"""
        total_start = self._base_config.start_date
        total_end = self._base_config.end_date

        # 计算总月数
        total_months = (total_end.year - total_start.year) * 12 + (total_end.month - total_start.month)

        # 每个分割的步长
        step_months = test_months - overlap_months
        if step_months <= 0:
            step_months = test_months

        # 计算可能的分割数
        window_months = train_months + test_months
        if n_splits is None:
            n_splits = (total_months - window_months) // step_months + 1
            n_splits = max(1, n_splits)

        splits = []
        current_start = total_start

        for i in range(n_splits):
            train_start = current_start
            train_end = train_start + relativedelta(months=train_months) - timedelta(days=1)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + relativedelta(months=test_months) - timedelta(days=1)

            # 检查是否超出范围
            if test_end > total_end:
                break

            splits.append(WalkForwardSplit(
                split_index=i + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ))

            # 移动到下一个分割
            current_start = current_start + relativedelta(months=step_months)

        return splits

    def _run_split(self, split: WalkForwardSplit) -> None:
        """执行单个分割"""
        # 训练期回测
        train_config = BacktestConfig(
            name=f"{self._base_config.name}_train_{split.split_index}",
            start_date=split.train_start,
            end_date=split.train_end,
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

        train_provider = DuckDBProvider(
            data_dir=train_config.data_dir,
            as_of_date=train_config.start_date,
        )

        train_executor = BacktestExecutor(train_config, data_provider=train_provider)
        split.train_result = train_executor.run()
        split.train_metrics = BacktestMetrics.from_backtest_result(split.train_result)

        # 测试期回测
        test_config = BacktestConfig(
            name=f"{self._base_config.name}_test_{split.split_index}",
            start_date=split.test_start,
            end_date=split.test_end,
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

        test_provider = DuckDBProvider(
            data_dir=test_config.data_dir,
            as_of_date=test_config.start_date,
        )

        test_executor = BacktestExecutor(test_config, data_provider=test_provider)
        split.test_result = test_executor.run()
        split.test_metrics = BacktestMetrics.from_backtest_result(split.test_result)

        # 计算衰减
        split._calc_decay()

    def _calc_summary(self, result: WalkForwardResult) -> None:
        """计算汇总指标"""
        if not result.splits:
            return

        # 收集指标
        is_returns = []
        is_sharpes = []
        is_win_rates = []
        oos_returns = []
        oos_sharpes = []
        oos_win_rates = []
        return_decays = []
        sharpe_decays = []

        for split in result.splits:
            if split.train_metrics:
                is_returns.append(split.train_metrics.total_return_pct)
                if split.train_metrics.sharpe_ratio is not None:
                    is_sharpes.append(split.train_metrics.sharpe_ratio)
                if split.train_metrics.win_rate is not None:
                    is_win_rates.append(split.train_metrics.win_rate)

            if split.test_metrics:
                oos_returns.append(split.test_metrics.total_return_pct)
                if split.test_metrics.sharpe_ratio is not None:
                    oos_sharpes.append(split.test_metrics.sharpe_ratio)
                if split.test_metrics.win_rate is not None:
                    oos_win_rates.append(split.test_metrics.win_rate)

            if split.return_decay is not None:
                return_decays.append(split.return_decay)
            if split.sharpe_decay is not None:
                sharpe_decays.append(split.sharpe_decay)

        # 计算 IS 指标
        result.is_total_return = sum(is_returns) if is_returns else 0
        result.is_avg_sharpe = sum(is_sharpes) / len(is_sharpes) if is_sharpes else None
        result.is_avg_win_rate = sum(is_win_rates) / len(is_win_rates) if is_win_rates else None

        # 计算 OOS 指标
        result.oos_total_return = sum(oos_returns) if oos_returns else 0
        result.oos_avg_sharpe = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else None
        result.oos_avg_win_rate = sum(oos_win_rates) / len(oos_win_rates) if oos_win_rates else None

        # 计算衰减
        result.avg_return_decay = sum(return_decays) / len(return_decays) if return_decays else None
        result.avg_sharpe_decay = sum(sharpe_decays) / len(sharpe_decays) if sharpe_decays else None

        # 计算一致性指标
        oos_positive = sum(1 for r in oos_returns if r > 0)
        result.oos_positive_pct = oos_positive / len(oos_returns) if oos_returns else 0

        oos_sharpe_positive = sum(1 for s in oos_sharpes if s > 0)
        result.oos_consistent_sharpe = oos_sharpe_positive / len(oos_sharpes) if oos_sharpes else 0

        # 计算过拟合分数 (0-1)
        result.overfitting_score = self._calc_overfitting_score(result)

    def _calc_overfitting_score(self, result: WalkForwardResult) -> float | None:
        """计算过拟合分数

        综合考虑:
        - OOS vs IS 性能衰减
        - OOS 一致性
        - 收益稳定性
        """
        if not result.splits:
            return None

        score = 0.0
        components = 0

        # 1. 收益衰减 (0-0.4 分)
        if result.avg_return_decay is not None:
            # 如果 OOS 收益远低于 IS，说明过拟合
            decay = max(0, -result.avg_return_decay)  # 负的衰减是不好的
            score += min(0.4, decay * 0.4)
            components += 1

        # 2. Sharpe 衰减 (0-0.3 分)
        if result.avg_sharpe_decay is not None:
            decay = max(0, -result.avg_sharpe_decay)
            score += min(0.3, decay * 0.3)
            components += 1

        # 3. OOS 一致性 (0-0.3 分)
        # 如果 OOS 表现不一致，加分
        inconsistency = 1 - result.oos_positive_pct
        score += inconsistency * 0.3
        components += 1

        return score if components > 0 else None

    def run_expanding_window(
        self,
        initial_train_months: int = 12,
        test_months: int = 3,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> WalkForwardResult:
        """扩展窗口验证

        训练窗口逐渐扩大，而非滚动。

        Args:
            initial_train_months: 初始训练月数
            test_months: 测试月数
            progress_callback: 进度回调

        Returns:
            WalkForwardResult
        """
        import time

        start_time = time.time()

        total_start = self._base_config.start_date
        total_end = self._base_config.end_date

        splits = []
        train_start = total_start
        split_idx = 1

        while True:
            train_end = train_start + relativedelta(months=initial_train_months + (split_idx - 1) * test_months) - timedelta(days=1)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + relativedelta(months=test_months) - timedelta(days=1)

            if test_end > total_end:
                break

            split = WalkForwardSplit(
                split_index=split_idx,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
            splits.append(split)
            split_idx += 1

        result = WalkForwardResult(
            n_splits=len(splits),
            train_months=initial_train_months,
            test_months=test_months,
        )

        for i, split in enumerate(splits):
            try:
                self._run_split(split)
                result.splits.append(split)
            except Exception as e:
                logger.warning(f"Split {i} failed: {e}")

            if progress_callback:
                progress_callback(i + 1, len(splits))

        self._calc_summary(result)
        result.execution_time_seconds = time.time() - start_time

        return result
