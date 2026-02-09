"""
Benchmark Comparison - 基准比较

提供回测结果与基准策略的比较:
- SPY Buy & Hold 基准
- 自定义基准
- 相对绩效指标计算

Usage:
    from src.backtest.optimization import BenchmarkComparison

    benchmark = BenchmarkComparison(backtest_result)
    comparison = benchmark.compare_with_spy(data_provider)
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

from src.engine.portfolio.returns import (
    calc_annualized_return,
    calc_max_drawdown,
    calc_sharpe_ratio,
    calc_sortino_ratio,
)

if TYPE_CHECKING:
    from src.backtest.engine.backtest_executor import BacktestResult, DailySnapshot
    from src.backtest.data.duckdb_provider import DuckDBProvider

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkData:
    """基准数据"""

    name: str
    dates: list[date]
    prices: list[float]
    returns: list[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.returns and len(self.prices) > 1:
            self.returns = [
                (self.prices[i] - self.prices[i - 1]) / self.prices[i - 1]
                for i in range(1, len(self.prices))
            ]


@dataclass
class BenchmarkResult:
    """基准比较结果"""

    # 策略绩效
    strategy_name: str
    strategy_total_return: float
    strategy_annualized_return: float | None
    strategy_sharpe: float | None
    strategy_sortino: float | None
    strategy_max_drawdown: float | None

    # 基准绩效
    benchmark_name: str
    benchmark_total_return: float
    benchmark_annualized_return: float | None
    benchmark_sharpe: float | None
    benchmark_sortino: float | None
    benchmark_max_drawdown: float | None

    # 相对指标
    alpha: float | None = None  # 超额收益 (年化)
    beta: float | None = None  # 相对波动
    tracking_error: float | None = None  # 跟踪误差
    information_ratio: float | None = None  # 信息比率
    correlation: float | None = None  # 相关性

    # 胜率
    outperformance_days: int = 0  # 跑赢天数
    underperformance_days: int = 0  # 跑输天数
    daily_win_rate: float = 0.0  # 日胜率

    # 时间序列 (用于绘图)
    dates: list[date] = field(default_factory=list)
    strategy_cumulative: list[float] = field(default_factory=list)
    benchmark_cumulative: list[float] = field(default_factory=list)
    relative_performance: list[float] = field(default_factory=list)

    def summary(self) -> str:
        """生成比较摘要"""
        lines = [
            "=== Benchmark Comparison ===",
            f"Strategy: {self.strategy_name}",
            f"Benchmark: {self.benchmark_name}",
            "",
            "--- Returns ---",
            f"  Strategy Total Return:  {self.strategy_total_return:.2%}",
            f"  Benchmark Total Return: {self.benchmark_total_return:.2%}",
            f"  Excess Return:          {self.strategy_total_return - self.benchmark_total_return:.2%}",
            "",
        ]

        if self.strategy_annualized_return is not None:
            lines.extend([
                f"  Strategy Annualized:    {self.strategy_annualized_return:.2%}",
                f"  Benchmark Annualized:   {self.benchmark_annualized_return:.2%}" if self.benchmark_annualized_return else "  Benchmark Annualized:   N/A",
            ])

        lines.extend([
            "",
            "--- Risk-Adjusted ---",
            f"  Strategy Sharpe:   {self.strategy_sharpe:.2f}" if self.strategy_sharpe else "  Strategy Sharpe:   N/A",
            f"  Benchmark Sharpe:  {self.benchmark_sharpe:.2f}" if self.benchmark_sharpe else "  Benchmark Sharpe:  N/A",
            f"  Strategy Max DD:   {self.strategy_max_drawdown:.2%}" if self.strategy_max_drawdown else "  Strategy Max DD:   N/A",
            f"  Benchmark Max DD:  {self.benchmark_max_drawdown:.2%}" if self.benchmark_max_drawdown else "  Benchmark Max DD:  N/A",
            "",
            "--- Relative Performance ---",
            f"  Alpha:             {self.alpha:.4f}" if self.alpha else "  Alpha:             N/A",
            f"  Beta:              {self.beta:.2f}" if self.beta else "  Beta:              N/A",
            f"  Information Ratio: {self.information_ratio:.2f}" if self.information_ratio else "  Information Ratio: N/A",
            f"  Correlation:       {self.correlation:.2f}" if self.correlation else "  Correlation:       N/A",
            "",
            f"  Daily Win Rate:    {self.daily_win_rate:.1%}",
            f"  Outperform Days:   {self.outperformance_days}",
            f"  Underperform Days: {self.underperformance_days}",
        ])

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "strategy_name": self.strategy_name,
            "benchmark_name": self.benchmark_name,
            "strategy_total_return": self.strategy_total_return,
            "benchmark_total_return": self.benchmark_total_return,
            "strategy_annualized_return": self.strategy_annualized_return,
            "benchmark_annualized_return": self.benchmark_annualized_return,
            "strategy_sharpe": self.strategy_sharpe,
            "benchmark_sharpe": self.benchmark_sharpe,
            "strategy_max_drawdown": self.strategy_max_drawdown,
            "benchmark_max_drawdown": self.benchmark_max_drawdown,
            "alpha": self.alpha,
            "beta": self.beta,
            "information_ratio": self.information_ratio,
            "correlation": self.correlation,
            "daily_win_rate": self.daily_win_rate,
        }


class BenchmarkComparison:
    """基准比较器

    将回测结果与基准策略进行比较。

    Usage:
        benchmark = BenchmarkComparison(backtest_result)
        result = benchmark.compare_with_spy(data_provider)
    """

    def __init__(self, backtest_result: "BacktestResult") -> None:
        """初始化比较器

        Args:
            backtest_result: 回测结果
        """
        self._result = backtest_result
        self._strategy_returns = self._calc_daily_returns(backtest_result.daily_snapshots)
        self._strategy_dates = [s.date for s in backtest_result.daily_snapshots]

    @staticmethod
    def _calc_daily_returns(snapshots: list["DailySnapshot"]) -> list[float]:
        """计算日收益率"""
        if len(snapshots) < 2:
            return []

        returns = []
        for i in range(1, len(snapshots)):
            prev_nlv = snapshots[i - 1].nlv
            curr_nlv = snapshots[i].nlv
            if prev_nlv > 0:
                returns.append((curr_nlv - prev_nlv) / prev_nlv)

        return returns

    def compare_with_spy(
        self,
        data_provider: "DuckDBProvider",
        spy_symbol: str = "SPY",
    ) -> BenchmarkResult:
        """与 SPY Buy & Hold 策略比较

        Args:
            data_provider: 数据提供者
            spy_symbol: SPY 或其他 ETF 符号

        Returns:
            BenchmarkResult
        """
        # 获取 SPY 数据
        benchmark_data = self._get_benchmark_data(
            data_provider,
            spy_symbol,
            self._result.start_date,
            self._result.end_date,
        )

        if benchmark_data is None:
            logger.warning(f"Could not get {spy_symbol} data, using synthetic benchmark")
            benchmark_data = self._create_synthetic_benchmark()

        return self._compare_with_benchmark(benchmark_data)

    def compare_with_custom(
        self,
        benchmark_dates: list[date],
        benchmark_prices: list[float],
        benchmark_name: str = "Custom Benchmark",
    ) -> BenchmarkResult:
        """与自定义基准比较

        Args:
            benchmark_dates: 日期列表
            benchmark_prices: 价格列表
            benchmark_name: 基准名称

        Returns:
            BenchmarkResult
        """
        benchmark_data = BenchmarkData(
            name=benchmark_name,
            dates=benchmark_dates,
            prices=benchmark_prices,
        )
        return self._compare_with_benchmark(benchmark_data)

    def _get_benchmark_data(
        self,
        data_provider: "DuckDBProvider",
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> BenchmarkData | None:
        """从数据提供者获取基准数据"""
        try:
            # 获取交易日列表
            trading_days = data_provider.get_trading_days(start_date, end_date)

            dates = []
            prices = []

            for d in trading_days:
                data_provider.set_as_of_date(d)
                quote = data_provider.get_stock_quote(symbol)
                if quote and quote.close:
                    dates.append(d)
                    prices.append(quote.close)

            if len(dates) < 2:
                return None

            return BenchmarkData(
                name=f"{symbol} Buy & Hold",
                dates=dates,
                prices=prices,
            )

        except Exception as e:
            logger.warning(f"Failed to get benchmark data: {e}")
            return None

    def _create_synthetic_benchmark(self) -> BenchmarkData:
        """创建合成基准 (假设 8% 年化收益)"""
        dates = self._strategy_dates
        daily_return = (1.08) ** (1 / 252) - 1  # 8% 年化

        prices = [100.0]
        for _ in range(1, len(dates)):
            prices.append(prices[-1] * (1 + daily_return))

        return BenchmarkData(
            name="Synthetic (8% Annual)",
            dates=dates,
            prices=prices,
        )

    def _compare_with_benchmark(self, benchmark_data: BenchmarkData) -> BenchmarkResult:
        """执行比较计算"""
        # 对齐日期
        strategy_by_date = {
            s.date: s for s in self._result.daily_snapshots
        }
        benchmark_by_date = dict(zip(benchmark_data.dates, benchmark_data.prices))

        common_dates = sorted(
            set(strategy_by_date.keys()) & set(benchmark_by_date.keys())
        )

        if len(common_dates) < 2:
            raise ValueError("Insufficient overlapping dates for comparison")

        # 提取对齐的数据
        strategy_nlvs = [strategy_by_date[d].nlv for d in common_dates]
        benchmark_prices = [benchmark_by_date[d] for d in common_dates]

        # 计算收益率序列
        strategy_returns = []
        benchmark_returns = []
        for i in range(1, len(common_dates)):
            if strategy_nlvs[i - 1] > 0:
                strategy_returns.append(
                    (strategy_nlvs[i] - strategy_nlvs[i - 1]) / strategy_nlvs[i - 1]
                )
            else:
                strategy_returns.append(0)

            if benchmark_prices[i - 1] > 0:
                benchmark_returns.append(
                    (benchmark_prices[i] - benchmark_prices[i - 1]) / benchmark_prices[i - 1]
                )
            else:
                benchmark_returns.append(0)

        # 计算总收益
        strategy_total_return = (strategy_nlvs[-1] - strategy_nlvs[0]) / strategy_nlvs[0]
        benchmark_total_return = (benchmark_prices[-1] - benchmark_prices[0]) / benchmark_prices[0]

        # 计算风险调整指标
        strategy_ann_return = calc_annualized_return(strategy_returns)
        benchmark_ann_return = calc_annualized_return(benchmark_returns)

        strategy_sharpe = calc_sharpe_ratio(strategy_returns)
        benchmark_sharpe = calc_sharpe_ratio(benchmark_returns)

        strategy_sortino = calc_sortino_ratio(strategy_returns)
        benchmark_sortino = calc_sortino_ratio(benchmark_returns)

        strategy_max_dd = calc_max_drawdown(strategy_nlvs)
        benchmark_max_dd = calc_max_drawdown(benchmark_prices)

        # 计算相对指标
        alpha, beta, correlation = self._calc_regression_metrics(
            strategy_returns, benchmark_returns
        )

        tracking_error = self._calc_tracking_error(strategy_returns, benchmark_returns)
        info_ratio = self._calc_information_ratio(
            strategy_returns, benchmark_returns, tracking_error
        )

        # 计算胜率
        outperform = 0
        underperform = 0
        for sr, br in zip(strategy_returns, benchmark_returns):
            if sr > br:
                outperform += 1
            elif sr < br:
                underperform += 1

        # 计算累积序列
        strategy_cum = [1.0]
        benchmark_cum = [1.0]
        relative = [0.0]

        for sr, br in zip(strategy_returns, benchmark_returns):
            strategy_cum.append(strategy_cum[-1] * (1 + sr))
            benchmark_cum.append(benchmark_cum[-1] * (1 + br))
            relative.append(strategy_cum[-1] / benchmark_cum[-1] - 1)

        return BenchmarkResult(
            strategy_name=self._result.config_name,
            strategy_total_return=strategy_total_return,
            strategy_annualized_return=strategy_ann_return,
            strategy_sharpe=strategy_sharpe,
            strategy_sortino=strategy_sortino,
            strategy_max_drawdown=strategy_max_dd,
            benchmark_name=benchmark_data.name,
            benchmark_total_return=benchmark_total_return,
            benchmark_annualized_return=benchmark_ann_return,
            benchmark_sharpe=benchmark_sharpe,
            benchmark_sortino=benchmark_sortino,
            benchmark_max_drawdown=benchmark_max_dd,
            alpha=alpha,
            beta=beta,
            tracking_error=tracking_error,
            information_ratio=info_ratio,
            correlation=correlation,
            outperformance_days=outperform,
            underperformance_days=underperform,
            daily_win_rate=outperform / len(strategy_returns) if strategy_returns else 0,
            dates=common_dates,
            strategy_cumulative=strategy_cum,
            benchmark_cumulative=benchmark_cum,
            relative_performance=relative,
        )

    @staticmethod
    def _calc_regression_metrics(
        strategy_returns: list[float],
        benchmark_returns: list[float],
    ) -> tuple[float | None, float | None, float | None]:
        """计算回归指标 (Alpha, Beta, Correlation)"""
        if len(strategy_returns) < 10:
            return None, None, None

        try:
            sr = np.array(strategy_returns)
            br = np.array(benchmark_returns)

            # 计算 Beta
            covariance = np.cov(sr, br)[0, 1]
            variance = np.var(br, ddof=1)

            # 防止除零和异常值: 方差太小时返回 None
            if variance < 1e-10:
                return None, None, None

            beta = covariance / variance

            # 防止 Beta 异常值 (合理范围: -10 ~ 10)
            if abs(beta) > 10:
                return None, None, None

            # 计算 Alpha (年化)
            mean_sr = np.mean(sr) * 252
            mean_br = np.mean(br) * 252
            alpha = mean_sr - beta * mean_br

            # 计算相关性
            correlation = np.corrcoef(sr, br)[0, 1]

            # 检查 NaN
            if np.isnan(correlation):
                correlation = None

            return alpha, beta, float(correlation) if correlation is not None else None

        except Exception:
            return None, None, None

    @staticmethod
    def _calc_tracking_error(
        strategy_returns: list[float],
        benchmark_returns: list[float],
    ) -> float | None:
        """计算跟踪误差"""
        if len(strategy_returns) < 2:
            return None

        excess = [s - b for s, b in zip(strategy_returns, benchmark_returns)]
        return float(np.std(excess, ddof=1)) * np.sqrt(252)

    @staticmethod
    def _calc_information_ratio(
        strategy_returns: list[float],
        benchmark_returns: list[float],
        tracking_error: float | None,
    ) -> float | None:
        """计算信息比率"""
        if tracking_error is None or tracking_error == 0:
            return None

        excess = [s - b for s, b in zip(strategy_returns, benchmark_returns)]
        mean_excess = np.mean(excess) * 252  # 年化

        return mean_excess / tracking_error
