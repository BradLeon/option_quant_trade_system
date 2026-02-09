"""
Backtest Dashboard - 回测可视化

使用 Plotly 生成交互式回测报告:
- 权益曲线图 (带交易标记)
- 回撤图
- 月度收益热力图
- 交易时间线
- 指标汇总面板
- 独立 HTML 报告

Usage:
    from src.backtest.visualization.dashboard import BacktestDashboard

    dashboard = BacktestDashboard(result, metrics)
    dashboard.generate_report("reports/backtest_report.html")
"""

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

if TYPE_CHECKING:
    from src.backtest.analysis.metrics import BacktestMetrics
    from src.backtest.engine.backtest_executor import BacktestResult
    from src.backtest.optimization.benchmark import BenchmarkResult


def _check_plotly():
    """检查 Plotly 是否可用"""
    if not PLOTLY_AVAILABLE:
        raise ImportError(
            "Plotly is required for visualization. "
            "Install with: pip install plotly"
        )


class BacktestDashboard:
    """回测可视化仪表盘

    生成交互式 Plotly 图表和 HTML 报告。

    Usage:
        dashboard = BacktestDashboard(result, metrics)
        dashboard.generate_report("reports/backtest.html")
    """

    # 配色方案
    COLORS = {
        "primary": "#1f77b4",
        "secondary": "#ff7f0e",
        "positive": "#2ecc71",
        "negative": "#e74c3c",
        "neutral": "#95a5a6",
        "background": "#ffffff",
        "grid": "#e0e0e0",
    }

    def __init__(
        self,
        result: "BacktestResult",
        metrics: "BacktestMetrics | None" = None,
        benchmark_result: "BenchmarkResult | None" = None,
    ) -> None:
        """初始化仪表盘

        Args:
            result: 回测结果
            metrics: 回测指标 (可选，如果不提供会自动计算)
            benchmark_result: 基准比较结果 (可选)
        """
        _check_plotly()

        self._result = result
        self._metrics = metrics
        self._benchmark_result = benchmark_result

        # 如果没有提供指标，自动计算
        if self._metrics is None:
            from src.backtest.analysis.metrics import BacktestMetrics

            self._metrics = BacktestMetrics.from_backtest_result(result)

    def create_equity_curve(self, show_trades: bool = True) -> go.Figure:
        """创建权益曲线图

        Args:
            show_trades: 是否显示交易标记

        Returns:
            Plotly Figure
        """
        snapshots = self._result.daily_snapshots
        if not snapshots:
            return go.Figure()

        dates = [s.date for s in snapshots]
        nlv = [s.nlv for s in snapshots]

        fig = go.Figure()

        # 权益曲线
        fig.add_trace(go.Scatter(
            x=dates,
            y=nlv,
            mode="lines",
            name="Portfolio Value",
            line=dict(color=self.COLORS["primary"], width=2),
            hovertemplate="Date: %{x}<br>NLV: $%{y:,.2f}<extra></extra>",
        ))

        # 添加初始资金基准线
        fig.add_hline(
            y=self._result.initial_capital,
            line_dash="dash",
            line_color=self.COLORS["neutral"],
            annotation_text="Initial Capital",
            annotation_position="bottom right",
        )

        # 添加交易标记
        if show_trades:
            # 找出有交易的日期
            open_dates = []
            open_nlv = []
            close_dates = []
            close_nlv = []

            nlv_by_date = {s.date: s.nlv for s in snapshots}

            for record in self._result.trade_records:
                if record.action == "open" and record.trade_date in nlv_by_date:
                    open_dates.append(record.trade_date)
                    open_nlv.append(nlv_by_date[record.trade_date])
                elif record.action in ("close", "expire") and record.trade_date in nlv_by_date:
                    close_dates.append(record.trade_date)
                    close_nlv.append(nlv_by_date[record.trade_date])

            # 开仓标记
            if open_dates:
                fig.add_trace(go.Scatter(
                    x=open_dates,
                    y=open_nlv,
                    mode="markers",
                    name="Open",
                    marker=dict(
                        symbol="triangle-up",
                        size=10,
                        color=self.COLORS["positive"],
                        line=dict(width=1, color="white"),
                    ),
                    hovertemplate="Open Position<br>Date: %{x}<extra></extra>",
                ))

            # 平仓标记
            if close_dates:
                fig.add_trace(go.Scatter(
                    x=close_dates,
                    y=close_nlv,
                    mode="markers",
                    name="Close",
                    marker=dict(
                        symbol="triangle-down",
                        size=10,
                        color=self.COLORS["negative"],
                        line=dict(width=1, color="white"),
                    ),
                    hovertemplate="Close Position<br>Date: %{x}<extra></extra>",
                ))

        # 布局
        fig.update_layout(
            title=dict(
                text=f"Equity Curve: {self._result.config_name}",
                x=0.5,
                xanchor="center",
            ),
            xaxis_title="Date",
            yaxis_title="Portfolio Value ($)",
            hovermode="x unified",
            showlegend=True,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
            template="plotly_white",
        )

        return fig

    def create_drawdown_chart(self) -> go.Figure:
        """创建回撤图

        Returns:
            Plotly Figure
        """
        snapshots = self._result.daily_snapshots
        if not snapshots:
            return go.Figure()

        dates = [s.date for s in snapshots]
        nlv = [s.nlv for s in snapshots]

        # 计算回撤序列
        peak = nlv[0]
        drawdowns = []
        for v in nlv:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            drawdowns.append(-dd)  # 负数表示回撤

        fig = go.Figure()

        # 回撤区域图
        fig.add_trace(go.Scatter(
            x=dates,
            y=drawdowns,
            fill="tozeroy",
            mode="lines",
            name="Drawdown",
            line=dict(color=self.COLORS["negative"], width=1),
            fillcolor="rgba(231, 76, 60, 0.3)",
            hovertemplate="Date: %{x}<br>Drawdown: %{y:.2%}<extra></extra>",
        ))

        # 标记最大回撤
        if self._metrics.max_drawdown:
            min_idx = drawdowns.index(min(drawdowns))
            fig.add_annotation(
                x=dates[min_idx],
                y=drawdowns[min_idx],
                text=f"Max DD: {-drawdowns[min_idx]:.2%}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                ax=50,
                ay=-30,
            )

        fig.update_layout(
            title=dict(text="Drawdown", x=0.5, xanchor="center"),
            xaxis_title="Date",
            yaxis_title="Drawdown",
            yaxis_tickformat=".1%",
            hovermode="x unified",
            showlegend=False,
            template="plotly_white",
        )

        return fig

    def create_monthly_returns_heatmap(self) -> go.Figure:
        """创建月度收益热力图

        Returns:
            Plotly Figure
        """
        monthly = self._metrics.monthly_returns
        if not monthly:
            return go.Figure()

        # 构建矩阵
        years = sorted(set(m.year for m in monthly))
        months = list(range(1, 13))

        z = []
        text = []
        for year in years:
            row = []
            text_row = []
            for month in months:
                # 查找对应月份
                found = None
                for m in monthly:
                    if m.year == year and m.month == month:
                        found = m
                        break

                if found:
                    row.append(found.return_pct * 100)  # 转为百分比
                    text_row.append(f"{found.return_pct:.1%}")
                else:
                    row.append(None)
                    text_row.append("")

            z.append(row)
            text.append(text_row)

        # 月份名称
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=month_names,
            y=[str(y) for y in years],
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=10),
            colorscale=[
                [0, self.COLORS["negative"]],
                [0.5, "white"],
                [1, self.COLORS["positive"]],
            ],
            zmid=0,
            hoverongaps=False,
            hovertemplate="Year: %{y}<br>Month: %{x}<br>Return: %{text}<extra></extra>",
        ))

        fig.update_layout(
            title=dict(text="Monthly Returns", x=0.5, xanchor="center"),
            xaxis_title="Month",
            yaxis_title="Year",
            template="plotly_white",
        )

        return fig

    def create_trade_timeline(self) -> go.Figure:
        """创建交易时间线 (按标的)

        Returns:
            Plotly Figure
        """
        trade_records = self._result.trade_records
        if not trade_records:
            return go.Figure()

        # 按 position_id 配对开平仓
        from collections import defaultdict

        positions = defaultdict(dict)
        for record in trade_records:
            if hasattr(record, "position_id") and record.position_id:
                pid = record.position_id
                if record.action == "open":
                    positions[pid]["open"] = record
                elif record.action in ("close", "expire"):
                    positions[pid]["close"] = record

        fig = go.Figure()

        # 获取所有标的
        underlyings = sorted(set(
            getattr(positions[pid].get("open"), "symbol", "").split()[0]
            for pid in positions
            if "open" in positions[pid]
        ))

        # 为每个标的创建 y 轴位置
        y_map = {u: i for i, u in enumerate(underlyings)}

        for pid, pos in positions.items():
            if "open" not in pos:
                continue

            open_rec = pos["open"]
            close_rec = pos.get("close")

            underlying = open_rec.symbol.split()[0] if hasattr(open_rec, "symbol") else "Unknown"
            y = y_map.get(underlying, 0)

            start_date = open_rec.trade_date
            end_date = close_rec.trade_date if close_rec else self._result.end_date

            # 确定颜色 (盈利/亏损)
            pnl = close_rec.pnl if close_rec and close_rec.pnl else 0
            color = self.COLORS["positive"] if pnl >= 0 else self.COLORS["negative"]

            # 添加线段
            fig.add_trace(go.Scatter(
                x=[start_date, end_date],
                y=[y, y],
                mode="lines+markers",
                line=dict(color=color, width=8),
                marker=dict(size=10, color=color),
                name=underlying,
                showlegend=False,
                hovertemplate=(
                    f"Position: {pid}<br>"
                    f"Symbol: {open_rec.symbol}<br>"
                    f"Entry: {start_date}<br>"
                    f"Exit: {end_date}<br>"
                    f"PnL: ${pnl:.2f}<extra></extra>"
                ),
            ))

        fig.update_layout(
            title=dict(text="Trade Timeline", x=0.5, xanchor="center"),
            xaxis_title="Date",
            yaxis=dict(
                tickmode="array",
                tickvals=list(range(len(underlyings))),
                ticktext=underlyings,
            ),
            hovermode="closest",
            template="plotly_white",
        )

        return fig

    def create_benchmark_comparison(self) -> go.Figure:
        """创建基准比较图

        显示策略 vs 基准的累积收益对比。

        Returns:
            Plotly Figure
        """
        if self._benchmark_result is None:
            # 无基准数据时返回空图
            fig = go.Figure()
            fig.add_annotation(
                text="No benchmark data available",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color="gray"),
            )
            fig.update_layout(
                title=dict(text="Benchmark Comparison", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        br = self._benchmark_result

        fig = go.Figure()

        # 策略累积收益曲线
        strategy_pct = [(v - 1) * 100 for v in br.strategy_cumulative]  # 转为百分比
        fig.add_trace(go.Scatter(
            x=br.dates,
            y=strategy_pct,
            mode="lines",
            name=br.strategy_name,
            line=dict(color=self.COLORS["primary"], width=2),
            hovertemplate="Date: %{x}<br>Return: %{y:.2f}%<extra></extra>",
        ))

        # 基准累积收益曲线
        benchmark_pct = [(v - 1) * 100 for v in br.benchmark_cumulative]
        fig.add_trace(go.Scatter(
            x=br.dates,
            y=benchmark_pct,
            mode="lines",
            name=br.benchmark_name,
            line=dict(color=self.COLORS["secondary"], width=2, dash="dash"),
            hovertemplate="Date: %{x}<br>Return: %{y:.2f}%<extra></extra>",
        ))

        # 相对表现 (策略 - 基准)
        relative_pct = [r * 100 for r in br.relative_performance]
        fig.add_trace(go.Scatter(
            x=br.dates,
            y=relative_pct,
            mode="lines",
            name="Relative Performance",
            line=dict(color=self.COLORS["positive"], width=1.5),
            opacity=0.7,
            hovertemplate="Date: %{x}<br>Alpha: %{y:.2f}%<extra></extra>",
        ))

        # 零线
        fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)

        # 添加注释显示关键指标
        annotations = []

        # 总收益对比
        annotations.append(dict(
            text=f"Strategy: {br.strategy_total_return:.1%}",
            xref="paper",
            yref="paper",
            x=0.02,
            y=0.98,
            showarrow=False,
            font=dict(size=11, color=self.COLORS["primary"]),
            bgcolor="rgba(255,255,255,0.8)",
        ))
        annotations.append(dict(
            text=f"Benchmark: {br.benchmark_total_return:.1%}",
            xref="paper",
            yref="paper",
            x=0.02,
            y=0.93,
            showarrow=False,
            font=dict(size=11, color=self.COLORS["secondary"]),
            bgcolor="rgba(255,255,255,0.8)",
        ))

        # Alpha 和 Beta
        if br.alpha is not None and br.beta is not None:
            annotations.append(dict(
                text=f"Alpha: {br.alpha:.2%} | Beta: {br.beta:.2f}",
                xref="paper",
                yref="paper",
                x=0.02,
                y=0.88,
                showarrow=False,
                font=dict(size=10, color="gray"),
                bgcolor="rgba(255,255,255,0.8)",
            ))

        fig.update_layout(
            title=dict(
                text=f"Strategy vs {br.benchmark_name}",
                x=0.5,
                xanchor="center",
            ),
            xaxis_title="Date",
            yaxis_title="Cumulative Return (%)",
            hovermode="x unified",
            showlegend=True,
            legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
            template="plotly_white",
            annotations=annotations,
        )

        return fig

    def create_benchmark_metrics_panel(self) -> str:
        """创建基准比较指标面板 (HTML)

        Returns:
            HTML 字符串
        """
        if self._benchmark_result is None:
            return ""

        br = self._benchmark_result

        def fmt_pct(v):
            return f"{v:.2%}" if v is not None else "N/A"

        def fmt_num(v, decimals=2):
            return f"{v:.{decimals}f}" if v is not None else "N/A"

        html = f"""
        <div class="benchmark-panel" style="font-family: Arial, sans-serif; padding: 20px; margin-top: 30px; background: #f8f9fa; border-radius: 8px;">
            <h3 style="text-align: center; color: #333; margin-bottom: 20px;">Benchmark Comparison: {br.benchmark_name}</h3>

            <div style="display: flex; flex-wrap: wrap; justify-content: space-around;">
                <!-- Returns Comparison -->
                <div style="min-width: 200px; margin: 10px;">
                    <h4 style="color: #1f77b4; margin-bottom: 10px;">Returns</h4>
                    <table style="width: 100%;">
                        <tr><td>Strategy</td><td style="text-align: right; font-weight: bold;">{fmt_pct(br.strategy_total_return)}</td></tr>
                        <tr><td>Benchmark</td><td style="text-align: right;">{fmt_pct(br.benchmark_total_return)}</td></tr>
                        <tr><td>Excess</td><td style="text-align: right; color: {'green' if (br.strategy_total_return - br.benchmark_total_return) > 0 else 'red'};">{fmt_pct(br.strategy_total_return - br.benchmark_total_return)}</td></tr>
                    </table>
                </div>

                <!-- Risk Metrics -->
                <div style="min-width: 200px; margin: 10px;">
                    <h4 style="color: #e74c3c; margin-bottom: 10px;">Risk-Adjusted</h4>
                    <table style="width: 100%;">
                        <tr><td>Strategy Sharpe</td><td style="text-align: right;">{fmt_num(br.strategy_sharpe)}</td></tr>
                        <tr><td>Benchmark Sharpe</td><td style="text-align: right;">{fmt_num(br.benchmark_sharpe)}</td></tr>
                        <tr><td>Strategy Max DD</td><td style="text-align: right;">{fmt_pct(br.strategy_max_drawdown)}</td></tr>
                        <tr><td>Benchmark Max DD</td><td style="text-align: right;">{fmt_pct(br.benchmark_max_drawdown)}</td></tr>
                    </table>
                </div>

                <!-- Relative Metrics -->
                <div style="min-width: 200px; margin: 10px;">
                    <h4 style="color: #2ecc71; margin-bottom: 10px;">Relative Performance</h4>
                    <table style="width: 100%;">
                        <tr><td>Alpha</td><td style="text-align: right; font-weight: bold;">{fmt_pct(br.alpha)}</td></tr>
                        <tr><td>Beta</td><td style="text-align: right;">{fmt_num(br.beta)}</td></tr>
                        <tr><td>Information Ratio</td><td style="text-align: right;">{fmt_num(br.information_ratio)}</td></tr>
                        <tr><td>Correlation</td><td style="text-align: right;">{fmt_num(br.correlation)}</td></tr>
                    </table>
                </div>

                <!-- Win Rate -->
                <div style="min-width: 200px; margin: 10px;">
                    <h4 style="color: #ff7f0e; margin-bottom: 10px;">Daily Win Rate</h4>
                    <table style="width: 100%;">
                        <tr><td>Outperform Days</td><td style="text-align: right;">{br.outperformance_days}</td></tr>
                        <tr><td>Underperform Days</td><td style="text-align: right;">{br.underperformance_days}</td></tr>
                        <tr><td>Win Rate</td><td style="text-align: right; font-weight: bold;">{fmt_pct(br.daily_win_rate)}</td></tr>
                    </table>
                </div>
            </div>
        </div>
        """
        return html

    def create_metrics_panel(self) -> str:
        """创建指标汇总面板 (HTML)

        Returns:
            HTML 字符串
        """
        m = self._metrics

        # 格式化辅助函数
        def fmt_pct(v):
            return f"{v:.2%}" if v is not None else "N/A"

        def fmt_num(v, decimals=2):
            return f"{v:.{decimals}f}" if v is not None else "N/A"

        def fmt_money(v):
            return f"${v:,.2f}" if v is not None else "N/A"

        html = f"""
        <div class="metrics-panel" style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="text-align: center; color: #333;">Backtest Summary: {m.config_name}</h2>
            <p style="text-align: center; color: #666;">
                {m.start_date} to {m.end_date} ({m.trading_days} trading days)
            </p>

            <div style="display: flex; flex-wrap: wrap; justify-content: space-around; margin-top: 20px;">
                <!-- Returns -->
                <div class="metric-card" style="background: #f8f9fa; border-radius: 8px; padding: 15px; margin: 10px; min-width: 200px;">
                    <h3 style="color: #1f77b4; margin-bottom: 10px;">Returns</h3>
                    <table style="width: 100%;">
                        <tr><td>Total Return</td><td style="text-align: right; font-weight: bold;">{fmt_pct(m.total_return_pct)}</td></tr>
                        <tr><td>Annualized</td><td style="text-align: right;">{fmt_pct(m.annualized_return)}</td></tr>
                        <tr><td>Final NLV</td><td style="text-align: right;">{fmt_money(m.final_nlv)}</td></tr>
                    </table>
                </div>

                <!-- Risk -->
                <div class="metric-card" style="background: #f8f9fa; border-radius: 8px; padding: 15px; margin: 10px; min-width: 200px;">
                    <h3 style="color: #e74c3c; margin-bottom: 10px;">Risk</h3>
                    <table style="width: 100%;">
                        <tr><td>Max Drawdown</td><td style="text-align: right; font-weight: bold;">{fmt_pct(m.max_drawdown)}</td></tr>
                        <tr><td>Volatility</td><td style="text-align: right;">{fmt_pct(m.volatility)}</td></tr>
                        <tr><td>VaR (95%)</td><td style="text-align: right;">{fmt_pct(m.var_95)}</td></tr>
                    </table>
                </div>

                <!-- Risk-Adjusted -->
                <div class="metric-card" style="background: #f8f9fa; border-radius: 8px; padding: 15px; margin: 10px; min-width: 200px;">
                    <h3 style="color: #2ecc71; margin-bottom: 10px;">Risk-Adjusted</h3>
                    <table style="width: 100%;">
                        <tr><td>Sharpe Ratio</td><td style="text-align: right; font-weight: bold;">{fmt_num(m.sharpe_ratio)}</td></tr>
                        <tr><td>Sortino Ratio</td><td style="text-align: right;">{fmt_num(m.sortino_ratio)}</td></tr>
                        <tr><td>Calmar Ratio</td><td style="text-align: right;">{fmt_num(m.calmar_ratio)}</td></tr>
                    </table>
                </div>

                <!-- Trading -->
                <div class="metric-card" style="background: #f8f9fa; border-radius: 8px; padding: 15px; margin: 10px; min-width: 200px;">
                    <h3 style="color: #ff7f0e; margin-bottom: 10px;">Trading</h3>
                    <table style="width: 100%;">
                        <tr><td>Total Trades</td><td style="text-align: right; font-weight: bold;">{m.total_trades}</td></tr>
                        <tr><td>Win Rate</td><td style="text-align: right;">{fmt_pct(m.win_rate)}</td></tr>
                        <tr><td>Profit Factor</td><td style="text-align: right;">{fmt_num(m.profit_factor)}</td></tr>
                        <tr><td>Avg Win</td><td style="text-align: right;">{fmt_money(m.average_win)}</td></tr>
                        <tr><td>Avg Loss</td><td style="text-align: right;">{fmt_money(m.average_loss)}</td></tr>
                    </table>
                </div>
            </div>
        </div>
        """
        return html

    def generate_report(
        self,
        output_path: str | Path,
        include_charts: list[str] | None = None,
    ) -> Path:
        """生成独立 HTML 报告

        Args:
            output_path: 输出文件路径
            include_charts: 要包含的图表 (默认全部)
                可选: ["equity", "drawdown", "monthly", "timeline", "benchmark"]

        Returns:
            输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 默认包含所有图表 (benchmark 只在有数据时包含)
        if include_charts is None:
            include_charts = ["equity", "drawdown", "monthly", "timeline"]
            if self._benchmark_result is not None:
                include_charts.append("benchmark")

        # 生成图表 HTML
        chart_html_list = []

        if "equity" in include_charts:
            fig = self.create_equity_curve()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "benchmark" in include_charts:
            fig = self.create_benchmark_comparison()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "drawdown" in include_charts:
            fig = self.create_drawdown_chart()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "monthly" in include_charts:
            fig = self.create_monthly_returns_heatmap()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "timeline" in include_charts:
            fig = self.create_trade_timeline()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        # 生成指标面板
        metrics_html = self.create_metrics_panel()
        benchmark_metrics_html = self.create_benchmark_metrics_panel()

        # 组装完整 HTML
        charts_combined = "\n".join(
            f'<div class="chart-container" style="margin: 20px 0;">{html}</div>'
            for html in chart_html_list
        )

        full_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Report: {self._result.config_name}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            text-align: center;
            color: #333;
        }}
        .chart-container {{
            margin: 30px 0;
        }}
        .footer {{
            text-align: center;
            color: #999;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Backtest Report</h1>

        {metrics_html}

        {benchmark_metrics_html}

        <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">

        {charts_combined}

        <div class="footer">
            <p>Generated by Option Quant Trade System</p>
            <p>Report Date: {date.today().isoformat()}</p>
        </div>
    </div>
</body>
</html>
"""

        # 写入文件
        output_path.write_text(full_html, encoding="utf-8")

        return output_path

    def show(self) -> None:
        """在浏览器中显示报告 (适用于 Jupyter 或命令行)"""
        import tempfile
        import webbrowser

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            report_path = self.generate_report(f.name)
            webbrowser.open(f"file://{report_path}")
