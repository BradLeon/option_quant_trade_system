"""
Backtest Metrics - 回测指标计算

计算回测结果的各类绩效指标:
- 收益指标: 总回报、年化回报、月度回报
- 风险指标: 最大回撤、波动率、VaR
- 风险调整收益: Sharpe、Sortino、Calmar
- 交易指标: 胜率、盈亏比、期望收益
- 期权特定指标: 平均权利金、行权率

Usage:
    from src.backtest.analysis.metrics import BacktestMetrics

    metrics = BacktestMetrics.from_backtest_result(result)
    print(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
    print(f"Max Drawdown: {metrics.max_drawdown:.2%}")
"""

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

from src.engine.portfolio.returns import (
    calc_annualized_return,
    calc_calmar_ratio,
    calc_cvar,
    calc_max_drawdown,
    calc_profit_factor,
    calc_sharpe_ratio,
    calc_sortino_ratio,
    calc_total_return,
    calc_var,
    calc_win_rate,
    calc_drawdown_series,
    calc_average_win,
    calc_average_loss,
    calc_expected_return,
    calc_expected_std,
)

if TYPE_CHECKING:
    from src.backtest.engine.backtest_executor import BacktestResult, DailySnapshot
    from src.backtest.engine.trade_simulator import TradeRecord


@dataclass
class MonthlyReturn:
    """月度回报"""

    year: int
    month: int
    return_pct: float
    trading_days: int


@dataclass
class DrawdownPeriod:
    """回撤区间"""

    start_date: date
    end_date: date | None  # None 表示尚未恢复
    trough_date: date
    peak_value: float
    trough_value: float
    drawdown_pct: float
    duration_days: int
    recovery_days: int | None


@dataclass
class BacktestMetrics:
    """回测绩效指标

    包含完整的回测绩效分析指标。
    """

    # ========== 基本信息 ==========
    config_name: str
    start_date: date
    end_date: date
    trading_days: int
    initial_capital: float
    final_nlv: float

    # ========== 收益指标 ==========
    total_return: float  # 总收益金额
    total_return_pct: float  # 总收益率
    annualized_return: float | None = None  # 年化收益率

    # ========== 风险指标 ==========
    max_drawdown: float | None = None  # 最大回撤
    max_drawdown_duration: int | None = None  # 最大回撤持续天数
    volatility: float | None = None  # 年化波动率
    downside_volatility: float | None = None  # 下行波动率
    var_95: float | None = None  # 95% VaR
    cvar_95: float | None = None  # 95% CVaR (Expected Shortfall)

    # ========== 风险调整收益 ==========
    sharpe_ratio: float | None = None  # Sharpe 比率
    sortino_ratio: float | None = None  # Sortino 比率
    calmar_ratio: float | None = None  # Calmar 比率

    # ========== 交易指标 ==========
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float | None = None
    profit_factor: float | None = None
    average_win: float | None = None  # 平均盈利金额
    average_loss: float | None = None  # 平均亏损金额
    expectancy: float | None = None  # 期望收益
    largest_win: float | None = None
    largest_loss: float | None = None

    # ========== 期权特定指标 ==========
    avg_premium_collected: float | None = None  # 平均收取权利金
    avg_premium_paid: float | None = None  # 平均支付权利金 (用于平仓)
    assignment_rate: float | None = None  # 行权/被行权比例
    expiration_rate: float | None = None  # 到期作废比例
    avg_days_in_trade: float | None = None  # 平均持仓天数
    avg_dte_at_entry: float | None = None  # 开仓时平均 DTE

    # ========== 费用统计 ==========
    total_commission: float = 0.0
    total_slippage: float = 0.0
    commission_pct: float = 0.0  # 佣金占比

    # ========== 时间序列 (用于可视化) ==========
    monthly_returns: list[MonthlyReturn] = field(default_factory=list)
    drawdown_periods: list[DrawdownPeriod] = field(default_factory=list)

    @classmethod
    def from_backtest_result(
        cls,
        result: "BacktestResult",
        risk_free_rate: float = 0.0,
    ) -> "BacktestMetrics":
        """从 BacktestResult 计算指标

        Args:
            result: 回测结果
            risk_free_rate: 无风险利率 (年化)

        Returns:
            BacktestMetrics
        """
        # 提取数据
        daily_snapshots = result.daily_snapshots
        trade_records = result.trade_records

        # 计算日收益率序列
        daily_returns = cls._calc_daily_returns(daily_snapshots)
        equity_curve = [s.nlv for s in daily_snapshots]

        # 提取已平仓交易的盈亏
        closed_pnls = [
            t.pnl
            for t in trade_records
            if t.action == "close" and t.pnl is not None
        ]

        # 风险调整参数
        rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1

        # ========== 计算收益指标 ==========
        annualized_return = calc_annualized_return(daily_returns) if daily_returns else None

        # ========== 计算风险指标 ==========
        max_dd = calc_max_drawdown(equity_curve) if equity_curve else None
        volatility = cls._calc_annual_volatility(daily_returns) if daily_returns else None
        downside_vol = cls._calc_downside_volatility(daily_returns) if daily_returns else None
        var_95 = calc_var(daily_returns, 0.95) if daily_returns else None
        cvar_95 = calc_cvar(daily_returns, 0.95) if daily_returns else None

        # ========== 计算风险调整收益 ==========
        sharpe = calc_sharpe_ratio(daily_returns, rf_daily) if daily_returns else None
        sortino = calc_sortino_ratio(daily_returns, rf_daily) if daily_returns else None
        calmar = calc_calmar_ratio(annualized_return, max_dd) if annualized_return and max_dd else None

        # ========== 计算交易指标 ==========
        win_rate = calc_win_rate(closed_pnls) if closed_pnls else None
        profit_factor = calc_profit_factor(closed_pnls) if closed_pnls else None
        avg_win = calc_average_win(closed_pnls) if closed_pnls else None
        avg_loss = calc_average_loss(closed_pnls) if closed_pnls else None
        expectancy = calc_expected_return(win_rate, avg_win or 0, avg_loss or 0) if win_rate else None

        largest_win = max(closed_pnls) if closed_pnls else None
        largest_loss = min(closed_pnls) if closed_pnls else None

        # ========== 计算期权特定指标 ==========
        option_metrics = cls._calc_option_metrics(trade_records)

        # ========== 计算月度回报 ==========
        monthly_returns = cls._calc_monthly_returns(daily_snapshots)

        # ========== 计算回撤区间 ==========
        max_dd_duration = None
        drawdown_periods = []
        if equity_curve:
            drawdown_periods = cls._calc_drawdown_periods(daily_snapshots)
            if drawdown_periods:
                max_dd_duration = max(p.duration_days for p in drawdown_periods)

        # 费用占比
        total_fees = result.total_commission + result.total_slippage
        commission_pct = total_fees / result.initial_capital if result.initial_capital > 0 else 0

        return cls(
            # 基本信息
            config_name=result.config_name,
            start_date=result.start_date,
            end_date=result.end_date,
            trading_days=result.trading_days,
            initial_capital=result.initial_capital,
            final_nlv=result.final_nlv,
            # 收益指标
            total_return=result.total_return,
            total_return_pct=result.total_return_pct,
            annualized_return=annualized_return,
            monthly_returns=monthly_returns,
            # 风险指标
            max_drawdown=max_dd,
            max_drawdown_duration=max_dd_duration,
            volatility=volatility,
            downside_volatility=downside_vol,
            var_95=var_95,
            cvar_95=cvar_95,
            # 风险调整收益
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            # 交易指标
            total_trades=result.total_trades,
            winning_trades=result.winning_trades,
            losing_trades=result.losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_win=avg_win,
            average_loss=avg_loss,
            expectancy=expectancy,
            largest_win=largest_win,
            largest_loss=largest_loss,
            # 期权特定指标
            avg_premium_collected=option_metrics.get("avg_premium_collected"),
            avg_premium_paid=option_metrics.get("avg_premium_paid"),
            assignment_rate=option_metrics.get("assignment_rate"),
            expiration_rate=option_metrics.get("expiration_rate"),
            avg_days_in_trade=option_metrics.get("avg_days_in_trade"),
            avg_dte_at_entry=option_metrics.get("avg_dte_at_entry"),
            # 费用统计
            total_commission=result.total_commission,
            total_slippage=result.total_slippage,
            commission_pct=commission_pct,
            # 时间序列
            drawdown_periods=drawdown_periods,
        )

    @staticmethod
    def _calc_daily_returns(snapshots: list["DailySnapshot"]) -> list[float]:
        """计算日收益率序列"""
        if len(snapshots) < 2:
            return []

        returns = []
        for i in range(1, len(snapshots)):
            prev_nlv = snapshots[i - 1].nlv
            curr_nlv = snapshots[i].nlv
            if prev_nlv > 0:
                daily_return = (curr_nlv - prev_nlv) / prev_nlv
                returns.append(daily_return)

        return returns

    @staticmethod
    def _calc_annual_volatility(daily_returns: list[float]) -> float | None:
        """计算年化波动率"""
        if not daily_returns or len(daily_returns) < 2:
            return None

        std_dev = calc_expected_std(daily_returns)
        if std_dev is None:
            return None

        # 年化: 乘以 sqrt(252)
        return std_dev * np.sqrt(252)

    @staticmethod
    def _calc_downside_volatility(daily_returns: list[float]) -> float | None:
        """计算下行波动率 (只考虑负收益)"""
        if not daily_returns:
            return None

        negative_returns = [r for r in daily_returns if r < 0]
        if len(negative_returns) < 2:
            return None

        std_dev = float(np.std(negative_returns, ddof=1))
        return std_dev * np.sqrt(252)

    @staticmethod
    def _calc_monthly_returns(snapshots: list["DailySnapshot"]) -> list[MonthlyReturn]:
        """计算月度回报"""
        if not snapshots:
            return []

        monthly_data: dict[tuple[int, int], list["DailySnapshot"]] = {}

        for snapshot in snapshots:
            key = (snapshot.date.year, snapshot.date.month)
            if key not in monthly_data:
                monthly_data[key] = []
            monthly_data[key].append(snapshot)

        results = []
        for (year, month), month_snapshots in sorted(monthly_data.items()):
            if len(month_snapshots) < 1:
                continue

            first_nlv = month_snapshots[0].nlv
            last_nlv = month_snapshots[-1].nlv

            if first_nlv > 0:
                return_pct = (last_nlv - first_nlv) / first_nlv
            else:
                return_pct = 0.0

            results.append(MonthlyReturn(
                year=year,
                month=month,
                return_pct=return_pct,
                trading_days=len(month_snapshots),
            ))

        return results

    @staticmethod
    def _calc_drawdown_periods(snapshots: list["DailySnapshot"]) -> list[DrawdownPeriod]:
        """计算回撤区间"""
        if not snapshots:
            return []

        periods = []
        peak_value = snapshots[0].nlv
        peak_date = snapshots[0].date
        in_drawdown = False
        trough_value = peak_value
        trough_date = peak_date
        drawdown_start = None

        for snapshot in snapshots:
            if snapshot.nlv > peak_value:
                # 新高 - 如果之前在回撤中，记录回撤区间
                if in_drawdown and drawdown_start:
                    periods.append(DrawdownPeriod(
                        start_date=drawdown_start,
                        end_date=snapshot.date,
                        trough_date=trough_date,
                        peak_value=peak_value,
                        trough_value=trough_value,
                        drawdown_pct=(peak_value - trough_value) / peak_value,
                        duration_days=(snapshot.date - drawdown_start).days,
                        recovery_days=(snapshot.date - trough_date).days,
                    ))

                peak_value = snapshot.nlv
                peak_date = snapshot.date
                trough_value = peak_value
                trough_date = peak_date
                in_drawdown = False
                drawdown_start = None

            elif snapshot.nlv < peak_value:
                # 进入或持续回撤
                if not in_drawdown:
                    in_drawdown = True
                    drawdown_start = peak_date

                if snapshot.nlv < trough_value:
                    trough_value = snapshot.nlv
                    trough_date = snapshot.date

        # 处理未结束的回撤
        if in_drawdown and drawdown_start:
            periods.append(DrawdownPeriod(
                start_date=drawdown_start,
                end_date=None,  # 未恢复
                trough_date=trough_date,
                peak_value=peak_value,
                trough_value=trough_value,
                drawdown_pct=(peak_value - trough_value) / peak_value if peak_value > 0 else 0,
                duration_days=(snapshots[-1].date - drawdown_start).days,
                recovery_days=None,
            ))

        return periods

    @staticmethod
    def _calc_option_metrics(trade_records: list["TradeRecord"]) -> dict:
        """计算期权特定指标"""
        result = {
            "avg_premium_collected": None,
            "avg_premium_paid": None,
            "assignment_rate": None,
            "expiration_rate": None,
            "avg_days_in_trade": None,
            "avg_dte_at_entry": None,
        }

        if not trade_records:
            return result

        # 分离开仓和平仓记录
        open_records = [t for t in trade_records if t.action == "open"]
        close_records = [t for t in trade_records if t.action == "close"]
        expire_records = [t for t in trade_records if t.action == "expire"]

        # 计算平均收取权利金 (卖出期权)
        premiums_collected = [
            abs(t.price * t.quantity * 100)
            for t in open_records
            if t.quantity < 0  # 卖出
        ]
        if premiums_collected:
            result["avg_premium_collected"] = sum(premiums_collected) / len(premiums_collected)

        # 计算平均支付权利金 (平仓)
        premiums_paid = [
            abs(t.price * t.quantity * 100)
            for t in close_records
            if t.quantity > 0  # 买回
        ]
        if premiums_paid:
            result["avg_premium_paid"] = sum(premiums_paid) / len(premiums_paid)

        # 计算到期比例
        total_closed = len(close_records) + len(expire_records)
        if total_closed > 0:
            result["expiration_rate"] = len(expire_records) / total_closed

            # 计算行权比例 (ITM 到期)
            assigned = [t for t in expire_records if t.pnl and t.pnl < 0]
            result["assignment_rate"] = len(assigned) / total_closed

        # 计算平均持仓天数
        if close_records or expire_records:
            holding_days = []
            for record in close_records + expire_records:
                if hasattr(record, "entry_date") and hasattr(record, "date"):
                    days = (record.date - record.entry_date).days
                    holding_days.append(days)

            if holding_days:
                result["avg_days_in_trade"] = sum(holding_days) / len(holding_days)

        return result

    def to_dict(self) -> dict:
        """转换为字典 (用于序列化)"""
        return {
            # 基本信息
            "config_name": self.config_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "trading_days": self.trading_days,
            "initial_capital": self.initial_capital,
            "final_nlv": self.final_nlv,
            # 收益指标
            "total_return": self.total_return,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            # 风险指标
            "max_drawdown": self.max_drawdown,
            "max_drawdown_duration": self.max_drawdown_duration,
            "volatility": self.volatility,
            "downside_volatility": self.downside_volatility,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            # 风险调整收益
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            # 交易指标
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "average_win": self.average_win,
            "average_loss": self.average_loss,
            "expectancy": self.expectancy,
            "largest_win": self.largest_win,
            "largest_loss": self.largest_loss,
            # 期权特定指标
            "avg_premium_collected": self.avg_premium_collected,
            "avg_premium_paid": self.avg_premium_paid,
            "assignment_rate": self.assignment_rate,
            "expiration_rate": self.expiration_rate,
            "avg_days_in_trade": self.avg_days_in_trade,
            "avg_dte_at_entry": self.avg_dte_at_entry,
            # 费用统计
            "total_commission": self.total_commission,
            "total_slippage": self.total_slippage,
            "commission_pct": self.commission_pct,
            # 月度回报
            "monthly_returns": [
                {"year": m.year, "month": m.month, "return_pct": m.return_pct}
                for m in self.monthly_returns
            ],
        }

    def summary(self) -> str:
        """生成指标摘要字符串"""
        lines = [
            f"=== Backtest Metrics: {self.config_name} ===",
            f"Period: {self.start_date} to {self.end_date} ({self.trading_days} days)",
            "",
            "--- Returns ---",
            f"  Total Return:      ${self.total_return:,.2f} ({self.total_return_pct:.2%})",
            f"  Annualized Return: {self.annualized_return:.2%}" if self.annualized_return else "  Annualized Return: N/A",
            "",
            "--- Risk ---",
            f"  Max Drawdown:      {self.max_drawdown:.2%}" if self.max_drawdown else "  Max Drawdown: N/A",
            f"  Volatility:        {self.volatility:.2%}" if self.volatility else "  Volatility: N/A",
            f"  VaR (95%):         {self.var_95:.2%}" if self.var_95 else "  VaR (95%): N/A",
            "",
            "--- Risk-Adjusted ---",
            f"  Sharpe Ratio:      {self.sharpe_ratio:.2f}" if self.sharpe_ratio else "  Sharpe Ratio: N/A",
            f"  Sortino Ratio:     {self.sortino_ratio:.2f}" if self.sortino_ratio else "  Sortino Ratio: N/A",
            f"  Calmar Ratio:      {self.calmar_ratio:.2f}" if self.calmar_ratio else "  Calmar Ratio: N/A",
            "",
            "--- Trading ---",
            f"  Total Trades:      {self.total_trades}",
            f"  Win Rate:          {self.win_rate:.1%}" if self.win_rate else "  Win Rate: N/A",
            f"  Profit Factor:     {self.profit_factor:.2f}" if self.profit_factor else "  Profit Factor: N/A",
            f"  Avg Win:           ${self.average_win:.2f}" if self.average_win else "  Avg Win: N/A",
            f"  Avg Loss:          ${self.average_loss:.2f}" if self.average_loss else "  Avg Loss: N/A",
            "",
            "--- Costs ---",
            f"  Commission:        ${self.total_commission:,.2f}",
            f"  Slippage:          ${self.total_slippage:,.2f}",
            f"  Total Costs:       {self.commission_pct:.2%} of capital",
        ]
        return "\n".join(lines)
