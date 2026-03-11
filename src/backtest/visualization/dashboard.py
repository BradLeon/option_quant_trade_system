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
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from src.backtest.engine.trade_simulator import TradeAction

if TYPE_CHECKING:
    from src.backtest.analysis.metrics import BacktestMetrics
    from src.backtest.attribution.models import EntryQualityReport, ExitQualityReport
    from src.backtest.engine.backtest_executor import BacktestResult
    from src.backtest.engine.trade_simulator import TradeAction
    from src.backtest.optimization.benchmark import BenchmarkResult
    from src.backtest.visualization.attribution_charts import AttributionCharts


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
        attribution_charts: "AttributionCharts | None" = None,
        market_context=None,
        entry_report: "EntryQualityReport | None" = None,
        exit_report: "ExitQualityReport | None" = None,
    ) -> None:
        """初始化仪表盘

        Args:
            result: 回测结果
            metrics: 回测指标 (可选，如果不提供会自动计算)
            benchmark_result: 基准比较结果 (可选)
            attribution_charts: 归因图表实例 (可选)
            market_context: 市场上下文数据 (可选，用于 K 线/事件图表)
            entry_report: 入场质量分析报告 (可选)
            exit_report: 出场质量分析报告 (可选)
        """
        _check_plotly()

        self._result = result
        self._metrics = metrics
        self._benchmark_result = benchmark_result
        self._attribution_charts: "AttributionCharts | None" = attribution_charts
        self._market_context = market_context
        self._entry_report: "EntryQualityReport | None" = entry_report
        self._exit_report: "ExitQualityReport | None" = exit_report

        # 如果没有提供指标，自动计算
        if self._metrics is None:
            from src.backtest.analysis.metrics import BacktestMetrics

            self._metrics = BacktestMetrics.from_backtest_result(result)

    def create_equity_curve(self, show_trades: bool = True) -> go.Figure:
        """创建权益曲线图

        显示:
        - Portfolio Value (蓝色实线)
        - SPY 基准曲线 (橙色虚线，如果有 benchmark_result)
        - 可选显示交易标记

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
        initial = self._result.initial_capital

        fig = go.Figure()

        # 权益曲线 (Portfolio Value)
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=nlv,
                mode="lines",
                name="Portfolio Value",
                line=dict(color=self.COLORS["primary"], width=2),
                hovertemplate="NLV: $%{y:,.2f}<extra></extra>",
            ),
        )

        # 如果有 benchmark 数据，显示 SPY 基准曲线 (美元)
        if self._benchmark_result is not None:
            br = self._benchmark_result
            # 将 benchmark 累积收益转为美元价值
            benchmark_nlv = [initial * cum for cum in br.benchmark_cumulative]
            fig.add_trace(
                go.Scatter(
                    x=br.dates,
                    y=benchmark_nlv,
                    mode="lines",
                    name=f"{br.benchmark_name} (Buy & Hold)",
                    line=dict(color=self.COLORS["secondary"], width=2, dash="dash"),
                    hovertemplate=f"{br.benchmark_name}: $%{{y:,.2f}}<extra></extra>",
                ),
            )

        # 添加初始资金基准线
        fig.add_hline(
            y=initial,
            line_dash="dot",
            line_color=self.COLORS["neutral"],
            annotation_text="Initial Capital",
            annotation_position="bottom right",
        )

        # 添加交易标记 (含详细 hover 信息)
        if show_trades:
            nlv_by_date = {s.date: s.nlv for s in snapshots}

            open_data = []
            close_data = []

            for record in self._result.trade_records:
                if record.trade_date not in nlv_by_date:
                    continue

                option_type = getattr(record, "option_type", None)
                option_type_str = option_type.name if hasattr(option_type, "name") else str(option_type) if option_type else "STOCK"
                strike = getattr(record, "strike", None)
                strike_str = f"${strike:.0f}" if strike is not None else ""
                qty = record.quantity
                price = record.price or 0
                pnl = record.pnl

                if record.action in (TradeAction.OPEN, TradeAction.STOCK_BUY):
                    hover = (
                        f"<b>OPEN</b><br>"
                        f"{record.underlying} {option_type_str} {strike_str}<br>"
                        f"Qty: {qty} @ ${price:.2f}"
                    )
                    open_data.append((record.trade_date, nlv_by_date[record.trade_date], hover))
                elif record.action in (TradeAction.CLOSE, TradeAction.ROLL, TradeAction.EXPIRE, TradeAction.ASSIGN_PUT, TradeAction.ASSIGN_CALL, TradeAction.STOCK_SELL):
                    # 根据action类型显示不同标题
                    action_label = "ROLL" if record.action == TradeAction.ROLL else "CLOSE" if record.action == TradeAction.CLOSE else "EXPIRE" if record.action == TradeAction.EXPIRE else "ASSIGN" if record.action in (TradeAction.ASSIGN_PUT, TradeAction.ASSIGN_CALL) else str(record.action.value).upper()
                    pnl_str = f"${pnl:,.2f}" if pnl else "-"
                    pnl_color = "green" if pnl and pnl > 0 else "red" if pnl and pnl < 0 else "gray"
                    hover = (
                        f"<b>{action_label}</b><br>"
                        f"{record.underlying} {option_type_str} {strike_str}<br>"
                        f"Qty: {qty} @ ${price:.2f}<br>"
                        f"<span style='color:{pnl_color}'>PnL: {pnl_str}</span>"
                    )
                    close_data.append((record.trade_date, nlv_by_date[record.trade_date], hover))

            if open_data:
                fig.add_trace(
                    go.Scatter(
                        x=[d[0] for d in open_data],
                        y=[d[1] for d in open_data],
                        mode="markers",
                        name="Open",
                        marker=dict(
                            symbol="triangle-up",
                            size=10,
                            color=self.COLORS["positive"],
                            line=dict(width=1, color="white"),
                        ),
                        text=[d[2] for d in open_data],
                        hovertemplate="%{text}<extra></extra>",
                    ),
                )

            if close_data:
                fig.add_trace(
                    go.Scatter(
                        x=[d[0] for d in close_data],
                        y=[d[1] for d in close_data],
                        mode="markers",
                        name="Close",
                        marker=dict(
                            symbol="triangle-down",
                            size=10,
                            color=self.COLORS["negative"],
                            line=dict(width=1, color="white"),
                        ),
                        text=[d[2] for d in close_data],
                        hovertemplate="%{text}<extra></extra>",
                    ),
                )

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
        """创建回撤图 (策略 + 基准)

        Returns:
            Plotly Figure
        """
        snapshots = self._result.daily_snapshots
        if not snapshots:
            return go.Figure()

        dates = [s.date for s in snapshots]
        nlv = [s.nlv for s in snapshots]

        # 计算策略回撤序列
        peak = nlv[0]
        drawdowns = []
        for v in nlv:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            drawdowns.append(-dd)

        fig = go.Figure()

        # 策略回撤区域图
        strategy_name = "Strategy"
        fig.add_trace(go.Scatter(
            x=dates,
            y=drawdowns,
            fill="tozeroy",
            mode="lines",
            name=strategy_name,
            line=dict(color=self.COLORS["negative"], width=1),
            fillcolor="rgba(231, 76, 60, 0.2)",
            hovertemplate="Date: %{x}<br>Drawdown: %{y:.2%}<extra></extra>",
        ))

        # 基准回撤
        br = self._benchmark_result
        if br is not None and br.benchmark_cumulative:
            bm_peak = br.benchmark_cumulative[0]
            bm_drawdowns = []
            for v in br.benchmark_cumulative:
                if v > bm_peak:
                    bm_peak = v
                dd = (bm_peak - v) / bm_peak if bm_peak > 0 else 0
                bm_drawdowns.append(-dd)

            fig.add_trace(go.Scatter(
                x=br.dates,
                y=bm_drawdowns,
                mode="lines",
                name=br.benchmark_name,
                line=dict(color=self.COLORS["secondary"], width=1.5, dash="dash"),
                hovertemplate="Date: %{x}<br>Drawdown: %{y:.2%}<extra></extra>",
            ))

            # 标记基准最大回撤
            bm_min_idx = bm_drawdowns.index(min(bm_drawdowns))
            fig.add_annotation(
                x=br.dates[bm_min_idx],
                y=bm_drawdowns[bm_min_idx],
                text=f"{br.benchmark_name} Max DD: {-bm_drawdowns[bm_min_idx]:.2%}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                ax=-60,
                ay=30,
                font=dict(color=self.COLORS["secondary"], size=10),
                arrowcolor=self.COLORS["secondary"],
            )

        # 标记策略最大回撤
        if self._metrics.max_drawdown:
            min_idx = drawdowns.index(min(drawdowns))
            fig.add_annotation(
                x=dates[min_idx],
                y=drawdowns[min_idx],
                text=f"Strategy Max DD: {-drawdowns[min_idx]:.2%}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                ax=50,
                ay=-30,
                font=dict(color=self.COLORS["negative"], size=10),
                arrowcolor=self.COLORS["negative"],
            )

        fig.update_layout(
            title=dict(text="Drawdown", x=0.5, xanchor="center"),
            xaxis_title="Date",
            yaxis_title="Drawdown",
            yaxis_tickformat=".1%",
            hovermode="x unified",
            showlegend=True,
            legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99),
            template="plotly_white",
        )

        return fig

    def _compute_benchmark_monthly_returns(self) -> dict[tuple[int, int], float]:
        """从基准累积收益序列计算月度收益百分比

        Returns:
            dict: {(year, month): return_pct} e.g. {(2020, 3): -0.125}
        """
        br = self._benchmark_result
        if br is None or not br.dates or not br.benchmark_cumulative:
            return {}

        # 按年月分组，取每月首尾累积值计算收益
        from collections import defaultdict
        monthly_data: dict[tuple[int, int], list[tuple[date, float]]] = defaultdict(list)
        for d, cum in zip(br.dates, br.benchmark_cumulative):
            monthly_data[(d.year, d.month)].append((d, cum))

        result = {}
        for (year, month), entries in monthly_data.items():
            entries.sort(key=lambda x: x[0])
            first_cum = entries[0][1]
            last_cum = entries[-1][1]
            if first_cum > 0:
                result[(year, month)] = (last_cum - first_cum) / first_cum
        return result

    def create_monthly_returns_heatmap(self) -> go.Figure:
        """创建月度收益热力图 (策略 + 基准)

        有基准数据时显示两个热力图 (Strategy / Benchmark)，否则只显示策略。

        Returns:
            Plotly Figure
        """
        monthly = self._metrics.monthly_returns
        if not monthly:
            return go.Figure()

        # 基准月度收益
        bm_monthly = self._compute_benchmark_monthly_returns()
        has_benchmark = bool(bm_monthly)

        # 合并年份列表 (策略 + 基准)
        strategy_years = set(m.year for m in monthly)
        bm_years = set(y for (y, _) in bm_monthly) if bm_monthly else set()
        years = sorted(strategy_years | bm_years)
        months = list(range(1, 13))
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        year_labels = [str(y) for y in years]

        # 策略矩阵
        z_strategy = []
        text_strategy = []
        for year in years:
            row = []
            text_row = []
            for month in months:
                found = None
                for m in monthly:
                    if m.year == year and m.month == month:
                        found = m
                        break
                if found:
                    row.append(found.return_pct * 100)
                    text_row.append(f"{found.return_pct:.1%}")
                else:
                    row.append(None)
                    text_row.append("")
            z_strategy.append(row)
            text_strategy.append(text_row)

        colorscale = [
            [0, self.COLORS["negative"]],
            [0.5, "white"],
            [1, self.COLORS["positive"]],
        ]

        if not has_benchmark:
            # 无基准: 单图
            fig = go.Figure(data=go.Heatmap(
                z=z_strategy,
                x=month_names,
                y=year_labels,
                text=text_strategy,
                texttemplate="%{text}",
                textfont=dict(size=10),
                colorscale=colorscale,
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

        # 基准矩阵
        z_benchmark = []
        text_benchmark = []
        for year in years:
            row = []
            text_row = []
            for month in months:
                val = bm_monthly.get((year, month))
                if val is not None:
                    row.append(val * 100)
                    text_row.append(f"{val:.1%}")
                else:
                    row.append(None)
                    text_row.append("")
            z_benchmark.append(row)
            text_benchmark.append(text_row)

        # 计算共享 color range
        all_vals = [v for row in z_strategy for v in row if v is not None]
        all_vals += [v for row in z_benchmark for v in row if v is not None]
        z_abs_max = max(abs(v) for v in all_vals) if all_vals else 20

        bm_name = self._benchmark_result.benchmark_name if self._benchmark_result else "Benchmark"

        # 两行子图
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=[f"Strategy Monthly Returns", f"{bm_name} Monthly Returns"],
            vertical_spacing=0.12,
        )

        # 策略热力图
        fig.add_trace(go.Heatmap(
            z=z_strategy,
            x=month_names,
            y=year_labels,
            text=text_strategy,
            texttemplate="%{text}",
            textfont=dict(size=10),
            colorscale=colorscale,
            zmin=-z_abs_max,
            zmax=z_abs_max,
            hoverongaps=False,
            hovertemplate="Year: %{y}<br>Month: %{x}<br>Return: %{text}<extra></extra>",
            showscale=False,
        ), row=1, col=1)

        # 基准热力图 (共享色阶范围)
        fig.add_trace(go.Heatmap(
            z=z_benchmark,
            x=month_names,
            y=year_labels,
            text=text_benchmark,
            texttemplate="%{text}",
            textfont=dict(size=10),
            colorscale=colorscale,
            zmin=-z_abs_max,
            zmax=z_abs_max,
            hoverongaps=False,
            hovertemplate="Year: %{y}<br>Month: %{x}<br>Return: %{text}<extra></extra>",
            colorbar=dict(title="Return %", ticksuffix="%"),
        ), row=2, col=1)

        fig.update_layout(
            title=dict(text="Monthly Returns", x=0.5, xanchor="center"),
            template="plotly_white",
            height=max(500, len(years) * 50 + 200),
        )

        return fig

    def create_trade_timeline(self) -> go.Figure:
        """创建交易时间线 (Gantt 风格)

        使用 Plotly 的时间线图表展示每个持仓的持有周期。
        每一行代表一个独立的期权合约，颜色表示盈亏。

        Returns:
            Plotly Figure
        """
        trade_records = self._result.trade_records
        if not trade_records:
            fig = go.Figure()
            fig.add_annotation(
                text="No trade records available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text="Position Timeline", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        from collections import defaultdict

        # 配对开平仓记录 (使用 position_id 避免同合约多笔交易覆盖)
        positions_dict: dict[str, dict] = defaultdict(dict)

        for record in trade_records:
            key = record.position_id or record.symbol
            # 开仓类：期权开仓 + 股票买入
            if record.action in (TradeAction.OPEN, TradeAction.STOCK_BUY):
                positions_dict[key]["open"] = record
            # 平仓类：期权平仓/到期/行权 + 股票卖出
            elif record.action in (TradeAction.CLOSE, TradeAction.ROLL, TradeAction.EXPIRE, TradeAction.ASSIGN_PUT, TradeAction.ASSIGN_CALL, TradeAction.STOCK_SELL):
                positions_dict[key]["close"] = record

        # 构建时间线数据
        timeline_data = []
        for symbol, pos in positions_dict.items():
            if "open" not in pos:
                continue

            open_rec = pos["open"]
            close_rec = pos.get("close")

            underlying = getattr(open_rec, "underlying", "Unknown")
            option_type_raw = getattr(open_rec, "option_type", None)
            option_type = option_type_raw.name if hasattr(option_type_raw, "name") else str(option_type_raw) if option_type_raw else "STOCK"
            strike = getattr(open_rec, "strike", None)
            quantity = open_rec.quantity

            start_date = open_rec.trade_date
            end_date = close_rec.trade_date if close_rec else self._result.end_date
            # 同日开平仓: 最小 1 天宽度，否则水平条不可见
            if start_date == end_date:
                end_date = end_date + timedelta(days=1)
            pnl = close_rec.pnl if close_rec and close_rec.pnl else 0
            is_open = close_rec is None

            # 构建标签: "GOOG PUT $325" 或 "SPY STOCK"
            label = f"{underlying} {option_type} ${strike:.0f}" if strike is not None else f"{underlying} {option_type}"

            timeline_data.append({
                "label": label,
                "underlying": underlying,
                "start": start_date,
                "end": end_date,
                "pnl": pnl,
                "is_open": is_open,
                "quantity": quantity,
                "symbol": symbol,
            })

        if not timeline_data:
            fig = go.Figure()
            fig.add_annotation(
                text="No positions to display",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text="Position Timeline", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        # 按标的和开始日期排序
        timeline_data.sort(key=lambda x: (x["underlying"] or "", x["start"]))

        # 创建 Gantt 图
        fig = go.Figure()

        # 为每个位置分配 y 坐标
        labels = [d["label"] for d in timeline_data]
        y_positions = list(range(len(labels)))

        for i, data in enumerate(timeline_data):
            # 颜色: 未平仓灰色，已平仓按盈亏
            if data["is_open"]:
                color = self.COLORS["neutral"]
                status = "(Open)"
            elif data["pnl"] >= 0:
                color = self.COLORS["positive"]
                status = f"+${data['pnl']:.2f}"
            else:
                color = self.COLORS["negative"]
                status = f"-${abs(data['pnl']):.2f}"

            # 添加水平条形 (使用 ISO 字符串避免 Plotly 显示时间戳)
            fig.add_trace(go.Scatter(
                x=[data["start"].isoformat(), data["end"].isoformat()],
                y=[i, i],
                mode="lines+markers",
                line=dict(color=color, width=15),
                marker=dict(size=8, color=color, symbol=["circle", "square"]),
                name=data["label"],
                showlegend=False,
                hovertemplate=(
                    f"<b>{data['label']}</b><br>"
                    f"Qty: {data['quantity']}<br>"
                    f"Open: {data['start']}<br>"
                    f"Close: {data['end']}<br>"
                    f"PnL: {status}<extra></extra>"
                ),
            ))

        fig.update_layout(
            title=dict(text="Position Timeline", x=0.5, xanchor="center"),
            xaxis_title="Date",
            xaxis=dict(type="date"),
            yaxis=dict(
                tickmode="array",
                tickvals=y_positions,
                ticktext=labels,
                autorange="reversed",  # 最新的在上面
            ),
            height=max(400, 50 + 30 * len(labels)),  # 动态高度
            hovermode="closest",
            template="plotly_white",
        )

        return fig

    def create_asset_volume(self) -> go.Figure:
        """创建 Asset Volume 热力图 (Treemap)

        展示各标的的敞口分布和盈亏贡献:
        - 方块面积 = Gross 敞口占比 (Σ|quantity|)
        - 颜色深度 = 占比越大越深
        - 颜色方向 = 红=亏损, 绿=盈利
        - 同时展示 Net (净敞口) 和 Gross (总敞口)

        Returns:
            Plotly Figure
        """
        from collections import defaultdict
        from src.data.models.option import OptionType

        trade_records = self._result.trade_records
        if not trade_records:
            fig = go.Figure()
            fig.add_annotation(
                text="No trade data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text="Asset Volume", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        # 按标的统计 Gross 和 Net 敞口 (市值)
        # Gross Market Value = Σ(|quantity| × price × multiplier)
        # Net Market Value = Σ(direction × quantity × price × multiplier)
        MULTIPLIER = 100  # 标准期权乘数

        stats_by_underlying: dict[str, dict] = defaultdict(
            lambda: {"gross_mv": 0.0, "net_mv": 0.0, "pnl": 0.0, "trades": 0, "contracts": 0}
        )

        def get_direction(option_type: OptionType) -> int:
            """PUT=-1 (看跌工具), CALL=+1 (看涨工具)"""
            return 1 if option_type == OptionType.CALL else -1

        for record in trade_records:
            underlying = getattr(record, "underlying", "Unknown")
            option_type = getattr(record, "option_type", None)

            # 平仓类（计算 PnL）：期权平仓/到期/行权 + 股票卖出
            if record.action in (TradeAction.CLOSE, TradeAction.ROLL, TradeAction.EXPIRE, TradeAction.ASSIGN_PUT, TradeAction.ASSIGN_CALL, TradeAction.STOCK_SELL) and record.pnl is not None:
                stats_by_underlying[underlying]["pnl"] += record.pnl

            # 开仓类：期权开仓 + 股票买入
            if record.action in (TradeAction.OPEN, TradeAction.STOCK_BUY):
                stats_by_underlying[underlying]["trades"] += 1
                stats_by_underlying[underlying]["contracts"] += abs(record.quantity)

                # 计算市值 (Market Value)
                market_value = abs(record.quantity) * record.price * MULTIPLIER

                # Gross Market Value = Σ(|quantity| × price × multiplier)
                stats_by_underlying[underlying]["gross_mv"] += market_value

                # Net Market Value = Σ(direction × quantity × price × multiplier)
                if option_type is not None:
                    direction = get_direction(option_type)
                    # 注意: quantity 已经有符号 (负数=卖出)
                    # direction: CALL=+1 (看涨), PUT=-1 (看跌)
                    stats_by_underlying[underlying]["net_mv"] += direction * record.quantity * record.price * MULTIPLIER

        if not stats_by_underlying:
            fig = go.Figure()
            fig.add_annotation(
                text="No asset data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color="gray"),
            )
            return fig

        # 计算权重 (基于 Gross Market Value)
        total_gross_mv = sum(s["gross_mv"] for s in stats_by_underlying.values())
        if total_gross_mv == 0:
            total_gross_mv = 1  # 避免除零

        for stats in stats_by_underlying.values():
            stats["weight"] = stats["gross_mv"] / total_gross_mv

        def calculate_color(weight: float, pnl: float) -> str:
            """根据权重和盈亏计算颜色

            - weight 决定颜色深度 (0.3 ~ 1.0)
            - pnl 决定红/绿
            """
            # 深度: 权重越大越深 (最小 0.3 避免太浅)
            intensity = 0.3 + 0.7 * min(weight * 2, 1.0)  # 放大权重效果

            if pnl >= 0:
                # 绿色系
                r = int(255 * (1 - intensity))
                g = int(150 + 105 * intensity)
                b = int(100 * (1 - intensity))
            else:
                # 红色系
                r = int(150 + 105 * intensity)
                g = int(100 * (1 - intensity))
                b = int(100 * (1 - intensity))

            return f"rgb({r},{g},{b})"

        # 准备 Treemap 数据
        labels = []
        parents = []
        values = []
        colors = []
        customdata = []

        # 根节点
        total_pnl = sum(s["pnl"] for s in stats_by_underlying.values())
        total_net_mv = sum(s["net_mv"] for s in stats_by_underlying.values())
        total_trades = sum(s["trades"] for s in stats_by_underlying.values())
        total_contracts = sum(s["contracts"] for s in stats_by_underlying.values())

        labels.append("Portfolio")
        parents.append("")
        values.append(max(1, total_gross_mv))  # Treemap value 基于 Gross MV
        colors.append(self.COLORS["primary"])  # Portfolio 用蓝色
        # customdata: [weight, pnl, net_mv, gross_mv, trades, contracts]
        customdata.append([1.0, total_pnl, total_net_mv, total_gross_mv, total_trades, total_contracts])

        # 按 Gross Market Value 排序
        sorted_underlyings = sorted(
            stats_by_underlying.items(),
            key=lambda x: x[1]["gross_mv"],
            reverse=True
        )

        for underlying, stats in sorted_underlyings:
            labels.append(underlying)
            parents.append("Portfolio")
            values.append(max(1, stats["gross_mv"]))
            colors.append(calculate_color(stats["weight"], stats["pnl"]))
            customdata.append([
                stats["weight"],
                stats["pnl"],
                stats["net_mv"],
                stats["gross_mv"],
                stats["trades"],
                stats["contracts"],
            ])

        fig = go.Figure(go.Treemap(
            labels=labels,
            parents=parents,
            values=values,
            customdata=customdata,
            marker=dict(colors=colors),
            textfont=dict(size=14),
            texttemplate=(
                "<b>%{label}</b><br>"
                "Gross: $%{customdata[3]:,.0f}<br>"
                "Net: $%{customdata[2]:+,.0f}"
            ),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Weight: %{customdata[0]:.1%}<br>"
                "Gross MV: $%{customdata[3]:,.2f}<br>"
                "Net MV: $%{customdata[2]:+,.2f} (正=看涨, 负=看跌)<br>"
                "Contracts: %{customdata[5]}<br>"
                "Trades: %{customdata[4]}<br>"
                "PnL: $%{customdata[1]:,.2f}<extra></extra>"
            ),
        ))

        fig.update_layout(
            title=dict(text="Asset Volume (by Market Value)", x=0.5, xanchor="center"),
            template="plotly_white",
        )

        return fig

    # 保留旧方法名作为别名，保持兼容性
    def create_asset_breakdown(self) -> go.Figure:
        """别名，调用 create_asset_volume()"""
        return self.create_asset_volume()

    def create_symbol_kline(self, symbol: str) -> go.Figure:
        """创建标的日 K 线图 (Candlestick + Volume + 交易标记)

        Args:
            symbol: 标的代码

        Returns:
            Plotly Figure
        """
        if not self._market_context or symbol not in self._market_context.symbol_klines:
            fig = go.Figure()
            fig.add_annotation(
                text=f"No kline data for {symbol}",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text=f"{symbol} Daily K-Line", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        klines = self._market_context.symbol_klines[symbol]
        dates = [k.timestamp.date().isoformat() for k in klines]
        opens = [k.open for k in klines]
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]
        closes = [k.close for k in klines]
        volumes = [k.volume for k in klines]

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.7, 0.3], vertical_spacing=0.03,
        )

        # Candlestick
        fig.add_trace(go.Candlestick(
            x=dates, open=opens, high=highs, low=lows, close=closes,
            name=symbol,
            increasing_line_color=self.COLORS["positive"],
            decreasing_line_color=self.COLORS["negative"],
        ), row=1, col=1)

        # Volume bars
        vol_colors = [
            self.COLORS["positive"] if c >= o else self.COLORS["negative"]
            for o, c in zip(opens, closes)
        ]
        fig.add_trace(go.Bar(
            x=dates, y=volumes, name="Volume",
            marker_color=vol_colors, opacity=0.5, showlegend=False,
        ), row=2, col=1)

        # 叠加交易标记
        if self._market_context.trade_records:
            close_by_date = {k.timestamp.date(): k.close for k in klines}
            open_marks = []
            close_marks = []
            roll_marks = []

            for rec in self._market_context.trade_records:
                if getattr(rec, "underlying", None) != symbol:
                    continue
                if rec.trade_date not in close_by_date:
                    continue
                price = close_by_date[rec.trade_date]
                dt_str = rec.trade_date.isoformat()
                if rec.action == "OPEN":
                    open_marks.append((dt_str, price))
                elif rec.action == "ROLL":
                    roll_marks.append((dt_str, price))
                elif rec.action in ("CLOSE", "EXPIRE"):
                    close_marks.append((dt_str, price))

            if open_marks:
                fig.add_trace(go.Scatter(
                    x=[m[0] for m in open_marks],
                    y=[m[1] for m in open_marks],
                    mode="markers", name="Open Trade",
                    marker=dict(symbol="triangle-up", size=12,
                                color=self.COLORS["positive"],
                                line=dict(width=1, color="white")),
                ), row=1, col=1)

            if roll_marks:
                fig.add_trace(go.Scatter(
                    x=[m[0] for m in roll_marks],
                    y=[m[1] for m in roll_marks],
                    mode="markers", name="Roll",
                    marker=dict(symbol="diamond", size=10,
                                color=self.COLORS["secondary"],
                                line=dict(width=1, color="white")),
                ), row=1, col=1)

            if close_marks:
                fig.add_trace(go.Scatter(
                    x=[m[0] for m in close_marks],
                    y=[m[1] for m in close_marks],
                    mode="markers", name="Close Trade",
                    marker=dict(symbol="triangle-down", size=12,
                                color=self.COLORS["negative"],
                                line=dict(width=1, color="white")),
                ), row=1, col=1)

        fig.update_layout(
            title=dict(text=f"{symbol} Daily K-Line", x=0.5, xanchor="center"),
            xaxis2_title="Date",
            yaxis_title="Price ($)",
            yaxis2_title="Volume",
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            template="plotly_white",
            height=500,
        )

        return fig

    def create_signal_timeline(self, symbol: str, sma_period: int = 200) -> go.Figure:
        """创建信号时间线图 (股价 + SMA + 交易信号标记)

        显示:
        - 股票收盘价 (蓝色实线)
        - SMA 均线 (橙色虚线)
        - 开仓标记 (绿色向上三角，含 hover 信息)
        - 平仓标记 (红色向下三角，含 hover 信息)
        - 投资/现金区间背景色

        Args:
            symbol: 标的代码
            sma_period: SMA 周期 (默认 200)

        Returns:
            Plotly Figure
        """
        if not self._market_context or symbol not in self._market_context.symbol_klines:
            fig = go.Figure()
            fig.add_annotation(
                text=f"No kline data for {symbol}",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text=f"{symbol} Signal Timeline", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        klines = self._market_context.symbol_klines[symbol]
        dates = [k.timestamp.date() for k in klines]
        closes = [k.close for k in klines]
        date_strs = [d.isoformat() for d in dates]

        fig = go.Figure()

        # 1. 股价收盘线
        fig.add_trace(go.Scatter(
            x=date_strs, y=closes,
            mode="lines", name=f"{symbol} Close",
            line=dict(color=self.COLORS["primary"], width=1.5),
        ))

        # 2. 计算并绘制 SMA
        sma_values = []
        for i in range(len(closes)):
            if i + 1 >= sma_period:
                sma_val = sum(closes[i + 1 - sma_period : i + 1]) / sma_period
                sma_values.append(sma_val)
            else:
                sma_values.append(None)

        sma_dates = [d for d, v in zip(date_strs, sma_values) if v is not None]
        sma_vals = [v for v in sma_values if v is not None]

        if sma_vals:
            fig.add_trace(go.Scatter(
                x=sma_dates, y=sma_vals,
                mode="lines", name=f"SMA{sma_period}",
                line=dict(color=self.COLORS["secondary"], width=1.5, dash="dash"),
            ))

        # 3. 投资/现金区间背景色 (close > SMA → invested, else → cash)
        if sma_values:
            prev_invested = None
            region_start = None
            for i, (d, close_val, sma_val) in enumerate(zip(date_strs, closes, sma_values)):
                if sma_val is None:
                    continue
                invested = close_val > sma_val
                if prev_invested is None:
                    prev_invested = invested
                    region_start = d
                elif invested != prev_invested:
                    # 结束上一个区间
                    fig.add_vrect(
                        x0=region_start, x1=d,
                        fillcolor="rgba(46,204,113,0.08)" if prev_invested else "rgba(231,76,60,0.08)",
                        layer="below", line_width=0,
                    )
                    prev_invested = invested
                    region_start = d
            # 最后一段区间
            if region_start is not None and prev_invested is not None:
                fig.add_vrect(
                    x0=region_start, x1=date_strs[-1],
                    fillcolor="rgba(46,204,113,0.08)" if prev_invested else "rgba(231,76,60,0.08)",
                    layer="below", line_width=0,
                )

        # 4. 交易标记
        trade_records = self._result.trade_records or []
        close_by_date = {d: c for d, c in zip(dates, closes)}

        open_x, open_y, open_hover = [], [], []
        close_x, close_y, close_hover = [], [], []
        roll_x, roll_y, roll_hover = [], [], []

        for rec in trade_records:
            underlying = getattr(rec, "underlying", None) or (
                rec.symbol.split("_")[0] if "_" in rec.symbol else rec.symbol
            )
            if underlying != symbol:
                continue

            td = rec.trade_date
            if td not in close_by_date:
                continue
            price = close_by_date[td]

            # 构建 hover 文本
            action_str = rec.action.value if hasattr(rec.action, "value") else str(rec.action)
            opt_type = ""
            if rec.option_type:
                opt_type = rec.option_type.value if hasattr(rec.option_type, "value") else str(rec.option_type)
            strike_str = f"K={rec.strike}" if rec.strike else ""
            exp_str = f"Exp={rec.expiration}" if rec.expiration else ""
            qty_str = f"Qty={rec.quantity}"
            price_str = f"@${rec.price:.2f}"

            parts = [f"<b>{action_str.upper()}</b>"]
            if opt_type or strike_str:
                parts.append(" ".join(filter(None, [opt_type, strike_str, exp_str])))
            parts.append(f"{qty_str} {price_str}")

            # 决策原因
            if rec.decision_reason:
                parts.append(f"Reason: {rec.decision_reason}")
            elif rec.reason:
                parts.append(f"Reason: {rec.reason}")

            # 触发信号
            if rec.trigger_alerts:
                alerts = ", ".join(rec.trigger_alerts[:3])
                parts.append(f"Alerts: {alerts}")

            # PnL (平仓时)
            if rec.pnl is not None:
                parts.append(f"PnL: ${rec.pnl:+,.0f}")

            hover = "<br>".join(parts)

            if rec.action in (TradeAction.OPEN, TradeAction.STOCK_BUY):
                open_x.append(td.isoformat())
                open_y.append(price)
                open_hover.append(hover)
            elif rec.action == TradeAction.ROLL:
                roll_x.append(td.isoformat())
                roll_y.append(price)
                roll_hover.append(hover)
            elif rec.action in (TradeAction.CLOSE, TradeAction.EXPIRE,
                                TradeAction.ASSIGN_PUT, TradeAction.ASSIGN_CALL,
                                TradeAction.STOCK_SELL):
                close_x.append(td.isoformat())
                close_y.append(price)
                close_hover.append(hover)

        if open_x:
            fig.add_trace(go.Scatter(
                x=open_x, y=open_y,
                mode="markers", name="Entry",
                marker=dict(symbol="triangle-up", size=14,
                            color=self.COLORS["positive"],
                            line=dict(width=1, color="white")),
                hovertext=open_hover,
                hoverinfo="text",
            ))

        if roll_x:
            fig.add_trace(go.Scatter(
                x=roll_x, y=roll_y,
                mode="markers", name="Roll",
                marker=dict(symbol="diamond", size=12,
                            color=self.COLORS["secondary"],
                            line=dict(width=1, color="white")),
                hovertext=roll_hover,
                hoverinfo="text",
            ))

        if close_x:
            fig.add_trace(go.Scatter(
                x=close_x, y=close_y,
                mode="markers", name="Exit",
                marker=dict(symbol="triangle-down", size=14,
                            color=self.COLORS["negative"],
                            line=dict(width=1, color="white")),
                hovertext=close_hover,
                hoverinfo="text",
            ))

        fig.update_layout(
            title=dict(
                text=f"{symbol} Signal Timeline (SMA{sma_period} Timing)",
                x=0.5, xanchor="center",
            ),
            xaxis_title="Date",
            yaxis_title="Price ($)",
            hovermode="closest",
            template="plotly_white",
            height=500,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        return fig

    def create_spy_kline(self) -> go.Figure:
        """创建 SPY 日 K 线图 (Candlestick + Volume)

        Returns:
            Plotly Figure
        """
        if not self._market_context or not self._market_context.spy_klines:
            fig = go.Figure()
            fig.add_annotation(
                text="No SPY kline data available",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text="SPY Daily K-Line", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        klines = self._market_context.spy_klines
        dates = [k.timestamp.date().isoformat() for k in klines]
        opens = [k.open for k in klines]
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]
        closes = [k.close for k in klines]
        volumes = [k.volume for k in klines]

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.7, 0.3], vertical_spacing=0.03,
        )

        fig.add_trace(go.Candlestick(
            x=dates, open=opens, high=highs, low=lows, close=closes,
            name="SPY",
            increasing_line_color=self.COLORS["positive"],
            decreasing_line_color=self.COLORS["negative"],
        ), row=1, col=1)

        vol_colors = [
            self.COLORS["positive"] if c >= o else self.COLORS["negative"]
            for o, c in zip(opens, closes)
        ]
        fig.add_trace(go.Bar(
            x=dates, y=volumes, name="Volume",
            marker_color=vol_colors, opacity=0.5, showlegend=False,
        ), row=2, col=1)

        fig.update_layout(
            title=dict(text="SPY Daily K-Line", x=0.5, xanchor="center"),
            xaxis2_title="Date",
            yaxis_title="Price ($)",
            yaxis2_title="Volume",
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            template="plotly_white",
            height=500,
        )

        return fig

    def create_vix_kline(self) -> go.Figure:
        """创建 VIX 日 K 线图 (反色: 上涨=红, 下跌=绿)

        Returns:
            Plotly Figure
        """
        if not self._market_context or not self._market_context.vix_data:
            fig = go.Figure()
            fig.add_annotation(
                text="No VIX data available",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text="VIX Daily K-Line", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        vix = self._market_context.vix_data
        dates = [d.date.isoformat() for d in vix]
        # MacroData OHLC 可能为 None，fallback 到 value
        opens = [d.open if d.open is not None else d.value for d in vix]
        highs = [d.high if d.high is not None else d.value for d in vix]
        lows = [d.low if d.low is not None else d.value for d in vix]
        closes = [d.close if d.close is not None else d.value for d in vix]

        fig = go.Figure()

        fig.add_trace(go.Candlestick(
            x=dates, open=opens, high=highs, low=lows, close=closes,
            name="VIX",
            increasing_line_color=self.COLORS["positive"],
            decreasing_line_color=self.COLORS["negative"],
        ))

        fig.update_layout(
            title=dict(text="VIX Daily K-Line", x=0.5, xanchor="center"),
            xaxis_title="Date",
            yaxis_title="VIX",
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
            template="plotly_white",
            height=400,
        )

        return fig

    def create_events_calendar(self) -> go.Figure:
        """创建重大事件日历

        y 轴: FOMC / CPI / NFP / GDP / PPI
        x 轴: 日期时间线
        每个事件 = 菱形标记，颜色按 impact

        Returns:
            Plotly Figure
        """
        # 收集事件 (优先使用 market_context，补充 FOMC 静态数据)
        events = []
        if self._market_context and self._market_context.economic_events:
            events = list(self._market_context.economic_events)

        # 始终尝试补充 FOMC 静态日历
        try:
            import yaml

            fomc_path = Path(__file__).parent.parent.parent.parent / "config" / "screening" / "fomc_calendar.yaml"
            if fomc_path.exists():
                with open(fomc_path) as f:
                    fomc_data = yaml.safe_load(f)

                existing_fomc_dates = set()
                for ev in events:
                    if getattr(ev, "event_type", None) and ev.event_type.name == "FOMC":
                        existing_fomc_dates.add(ev.event_date)

                start = self._result.start_date
                end = self._result.end_date

                for _year, dates_list in fomc_data.get("fomc_meetings", {}).items():
                    for date_str in dates_list:
                        fomc_date = date.fromisoformat(date_str)
                        if start <= fomc_date <= end and fomc_date not in existing_fomc_dates:
                            # 创建简单的事件 dict (非 EconomicEvent dataclass)
                            events.append(_FOMCEvent(fomc_date))
        except Exception:
            pass

        if not events:
            fig = go.Figure()
            fig.add_annotation(
                text="No economic events available",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(
                title=dict(text="Economic Events Calendar", x=0.5, xanchor="center"),
                template="plotly_white",
            )
            return fig

        # 事件分类映射
        event_rows = {"FOMC": 0, "CPI": 1, "NFP": 2, "GDP": 3, "PPI": 4}
        row_labels = list(event_rows.keys())

        # Impact 颜色映射
        impact_colors = {"HIGH": "#e74c3c", "MEDIUM": "#ff7f0e", "LOW": "#95a5a6"}

        fig = go.Figure()

        # 按类型分组绘制
        for event in events:
            event_type_name = _get_event_type_name(event)
            if event_type_name not in event_rows:
                continue

            y_val = event_rows[event_type_name]
            event_date = _get_event_date(event)
            impact_name = _get_event_impact(event)
            color = impact_colors.get(impact_name, "#95a5a6")
            name = _get_event_name(event)

            fig.add_trace(go.Scatter(
                x=[event_date.isoformat()],
                y=[y_val],
                mode="markers",
                marker=dict(symbol="diamond", size=14, color=color,
                            line=dict(width=1, color="white")),
                name=event_type_name,
                showlegend=False,
                hovertemplate=(
                    f"<b>{name}</b><br>"
                    f"Date: {event_date}<br>"
                    f"Impact: {impact_name}<extra></extra>"
                ),
            ))

        # 图例: impact 级别
        for impact_label, color in impact_colors.items():
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers",
                marker=dict(symbol="diamond", size=12, color=color),
                name=f"{impact_label} Impact",
            ))

        fig.update_layout(
            title=dict(text="Economic Events Calendar", x=0.5, xanchor="center"),
            xaxis_title="Date",
            xaxis=dict(type="date"),
            yaxis=dict(
                tickmode="array",
                tickvals=list(range(len(row_labels))),
                ticktext=row_labels,
            ),
            hovermode="closest",
            template="plotly_white",
            height=350,
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
                text=f"Alpha: {br.alpha:.4f} | Beta: {br.beta:.2f}",
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
                        <tr><td>Alpha</td><td style="text-align: right; font-weight: bold;">{fmt_num(br.alpha, 4)}</td></tr>
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

    def create_holdings_table(self) -> str:
        """创建持仓报表 (HTML)

        显示回测结束时的未平仓持仓，包括现金和 NLV 汇总行。
        参考 IBKR Portfolio 面板的风格。

        Returns:
            HTML 字符串
        """
        open_positions = self._result.open_positions
        last_snapshot = self._result.daily_snapshots[-1] if self._result.daily_snapshots else None

        cash = last_snapshot.cash if last_snapshot else 0.0
        nlv = last_snapshot.nlv if last_snapshot else 0.0

        def fmt_money(v: float, show_sign: bool = False) -> str:
            if v is None:
                return "--"
            prefix = "+" if show_sign and v > 0 else ""
            return f"{prefix}${v:,.2f}"

        def pnl_cell(v: float | None) -> str:
            if v is None or v == 0:
                return '<td style="text-align: right;">--</td>'
            color = "#2ecc71" if v > 0 else "#e74c3c"
            return f'<td style="text-align: right; color: {color}; font-weight: bold;">{fmt_money(v, show_sign=True)}</td>'

        # 构建仪器名称
        def instrument_name(pos: dict) -> str:
            if pos["asset_type"] == "stock":
                return f'{pos["symbol"]} STOCK'
            # 期权: SPY Mar14'25 604 PUT
            parts = [pos.get("underlying") or pos["symbol"]]
            if pos.get("expiration"):
                parts.append(pos["expiration"])
            if pos.get("strike"):
                parts.append(str(pos["strike"]))
            if pos.get("option_type"):
                parts.append(pos["option_type"].upper())
            return " ".join(parts)

        rows = []

        # Cash row
        cash_color = "#2ecc71" if cash >= 0 else "#e74c3c"
        rows.append(f"""
            <tr style="background-color: #1a1a2e; color: #fff;">
                <td></td>
                <td style="font-weight: bold;">USD CASH</td>
                <td></td>
                <td style="text-align: right; color: {cash_color}; font-weight: bold;">{fmt_money(cash)}</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
        """)

        # Position rows
        for pos in open_positions:
            name = instrument_name(pos)
            qty = pos["quantity"]
            mv = pos["market_value"]
            avg_px = pos["entry_price"]
            cur_px = pos["current_price"]
            unrl = pos["unrealized_pnl"]
            real = pos.get("realized_pnl")

            # Row background (alternate)
            bg = "#0d1117"

            rows.append(f"""
            <tr style="background-color: {bg}; color: #c9d1d9;">
                <td></td>
                <td style="font-weight: bold;">{name}</td>
                <td style="text-align: right;">{qty}</td>
                <td style="text-align: right;">{fmt_money(mv)}</td>
                <td style="text-align: right;">${avg_px:,.2f}</td>
                <td style="text-align: right;">${cur_px:,.2f}</td>
                {pnl_cell(unrl)}
                {pnl_cell(real)}
            </tr>
            """)

        # NLV summary row
        nlv_color = "#2ecc71" if nlv >= self._result.initial_capital else "#e74c3c"
        total_unrl = sum(p["unrealized_pnl"] for p in open_positions if p.get("unrealized_pnl"))
        rows.append(f"""
            <tr style="background-color: #161b22; color: #fff; font-weight: bold; border-top: 2px solid #30363d;">
                <td></td>
                <td>NET LIQUIDATION VALUE</td>
                <td></td>
                <td style="text-align: right; color: {nlv_color};">{fmt_money(nlv)}</td>
                <td></td>
                <td></td>
                {pnl_cell(total_unrl)}
                <td></td>
            </tr>
        """)

        table_html = f"""
        <h2 style="text-align: center; color: #333; margin-top: 30px;">Portfolio Holdings (End of Backtest)</h2>
        <div style="overflow-x: auto; margin: 10px 0;">
        <table style="width: 100%; border-collapse: collapse; font-size: 13px; font-family: 'Consolas', 'Monaco', monospace;">
            <thead>
                <tr style="background-color: #21262d; color: #8b949e; font-size: 11px; text-transform: uppercase;">
                    <th style="padding: 8px 12px; text-align: left; width: 60px;">Dly P&L</th>
                    <th style="padding: 8px 12px; text-align: left;">Financial Instrument</th>
                    <th style="padding: 8px 12px; text-align: right;">Position</th>
                    <th style="padding: 8px 12px; text-align: right;">Market Value</th>
                    <th style="padding: 8px 12px; text-align: right;">Avg Price</th>
                    <th style="padding: 8px 12px; text-align: right;">Last Price</th>
                    <th style="padding: 8px 12px; text-align: right;">Unrlzd P&L</th>
                    <th style="padding: 8px 12px; text-align: right;">Realized P&L</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
        </div>
        """
        return table_html

    def create_trade_records_table(self) -> str:
        """创建交易记录表格 (HTML)

        Returns:
            HTML 字符串
        """
        trade_records = self._result.trade_records
        if not trade_records:
            return ""

        # 排序：按日期
        sorted_records = sorted(trade_records, key=lambda r: r.trade_date)

        rows = []
        for record in sorted_records:
            # 获取属性
            trade_date = record.trade_date.isoformat()
            # 使用 .value 获取枚举的字符串值，然后转大写
            action = str(record.action.value).upper() if hasattr(record.action, "value") else str(record.action).upper()
            underlying = getattr(record, "underlying", "N/A")
            option_type = getattr(record, "option_type", None)
            option_type_str = option_type.name if hasattr(option_type, "name") else str(option_type) if option_type else "N/A"
            strike = getattr(record, "strike", None)
            strike_str = f"${strike:.2f}" if strike else "N/A"
            expiry = getattr(record, "expiration", None)
            expiry_str = expiry.isoformat() if expiry else "N/A"

            # 计算 DTE (Days To Expiration)
            if expiry:
                dte = (expiry - record.trade_date).days
                dte_str = str(dte)
            else:
                dte_str = "N/A"

            quantity = record.quantity
            price = record.price or 0
            net_amount = getattr(record, "net_amount", 0) or 0
            pnl = record.pnl

            # PnL 颜色
            if pnl is not None and pnl != 0:
                pnl_color = "green" if pnl > 0 else "red"
                pnl_str = f'<span style="color: {pnl_color};">${pnl:,.2f}</span>'
            else:
                pnl_str = "-"

            # 操作颜色
            action_color = "#2ecc71" if action == "OPEN" else "#e74c3c" if action == "CLOSE" else "#ff7f0e" if action == "EXPIRE" else "#3498db" if action == "ROLL" else "#95a5a6" if action == "ASSIGN_PUT" else "#e67e22" if action == "ASSIGN_CALL" else "#16a085" if action == "STOCK_BUY" else "#27ae60" if action == "STOCK_SELL" else "#999"

            # Reason (所有 action 均显示)
            reason = getattr(record, "reason", None)
            if reason:
                reason_str = reason
            else:
                reason_str = "-"

            rows.append(f"""
                <tr>
                    <td>{trade_date}</td>
                    <td style="color: {action_color}; font-weight: bold;">{action}</td>
                    <td>{underlying}</td>
                    <td>{option_type_str}</td>
                    <td>{strike_str}</td>
                    <td>{expiry_str}</td>
                    <td style="text-align: right;">{dte_str}</td>
                    <td style="text-align: right;">{quantity}</td>
                    <td style="text-align: right;">${price:,.2f}</td>
                    <td style="text-align: right;">${net_amount:,.2f}</td>
                    <td style="text-align: right;">{pnl_str}</td>
                    <td style="font-size: 11px; color: #666;">{reason_str}</td>
                </tr>
            """)

        html = f"""
        <div class="trade-records" style="margin-top: 30px;">
            <h3 style="text-align: center; color: #333; margin-bottom: 15px;">Trade Records</h3>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
                    <thead>
                        <tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;">
                            <th style="padding: 10px; text-align: left;">Date</th>
                            <th style="padding: 10px; text-align: left;">Action</th>
                            <th style="padding: 10px; text-align: left;">Underlying</th>
                            <th style="padding: 10px; text-align: left;">Type</th>
                            <th style="padding: 10px; text-align: left;">Strike</th>
                            <th style="padding: 10px; text-align: left;">Expiry</th>
                            <th style="padding: 10px; text-align: right;">DTE</th>
                            <th style="padding: 10px; text-align: right;">Qty</th>
                            <th style="padding: 10px; text-align: right;">Price</th>
                            <th style="padding: 10px; text-align: right;">Value</th>
                            <th style="padding: 10px; text-align: right;">PnL</th>
                            <th style="padding: 10px; text-align: left;">Reason</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(rows)}
                    </tbody>
                </table>
            </div>
            <p style="text-align: center; color: #999; margin-top: 10px;">
                Total: {len(sorted_records)} transactions
            </p>
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
                        <tr><td>P/L Ratio</td><td style="text-align: right;">{fmt_num(m.profit_loss_ratio)}</td></tr>
                        <tr><td>Avg Win</td><td style="text-align: right;">{fmt_money(m.average_win)}</td></tr>
                        <tr><td>Avg Loss</td><td style="text-align: right;">{fmt_money(m.average_loss)}</td></tr>
                    </table>
                </div>
            </div>
        </div>
        """
        return html

    def create_position_pct_chart(self) -> "go.Figure":
        """Position% 时序图: target_pct + current_pct"""
        _check_plotly()

        snapshots = self._result.daily_snapshots
        dates = []
        target_pcts = []
        current_pcts = []

        for s in snapshots:
            sm = getattr(s, "strategy_metrics", {}) or {}
            dates.append(s.date)
            target_pcts.append(sm.get("target_pct"))
            current_pcts.append(sm.get("current_pct"))

        # 回退: 若无 strategy_metrics，用 positions_value/nlv 作近似
        has_data = any(t is not None for t in target_pcts)
        if not has_data:
            target_pcts = [None] * len(dates)
            current_pcts = [
                s.positions_value / s.nlv if s.nlv > 0 else 0.0
                for s in snapshots
            ]

        fig = go.Figure()

        if has_data:
            fig.add_trace(go.Scatter(
                x=dates, y=target_pcts,
                mode="lines", name="Target %",
                line=dict(color="#1f77b4", width=2),
            ))

        fig.add_trace(go.Scatter(
            x=dates, y=current_pcts,
            mode="lines", name="Current %",
            fill="tozeroy",
            line=dict(color="#9467bd", width=1.5),
            fillcolor="rgba(148, 103, 189, 0.25)",
        ))

        fig.add_hline(y=1.0, line_dash="dash", line_color="gray",
                       annotation_text="100%", annotation_position="bottom right")

        fig.update_layout(
            title="Position Exposure %",
            xaxis_title="Date",
            yaxis_title="Exposure (fraction of NLV)",
            yaxis=dict(tickformat=".0%"),
            height=350,
            margin=dict(l=60, r=40, t=50, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        return fig

    def create_strategy_indicators_chart(self) -> "go.Figure":
        """策略指标时序图: 价格+SMA / 动量分+VIX / target_pct+current_pct+vol_scalar"""
        _check_plotly()

        snapshots = self._result.daily_snapshots
        dates = []
        closes = []
        sma20s = []
        sma50s = []
        sma200s = []
        scores = []
        vixes = []
        target_pcts = []
        current_pcts = []
        vol_scalars = []

        for s in snapshots:
            sm = getattr(s, "strategy_metrics", {}) or {}
            dates.append(s.date)
            closes.append(sm.get("close"))
            sma20s.append(sm.get("sma20"))
            sma50s.append(sm.get("sma50"))
            sma200s.append(sm.get("sma200"))
            scores.append(sm.get("momentum_score"))
            vixes.append(sm.get("vix"))
            target_pcts.append(sm.get("target_pct"))
            current_pcts.append(sm.get("current_pct"))
            vol_scalars.append(sm.get("vol_scalar"))

        has_data = any(c is not None for c in closes)
        if not has_data:
            return go.Figure().update_layout(
                title="Strategy Indicators (no data)",
                annotations=[dict(text="No strategy_metrics available", showarrow=False,
                                  xref="paper", yref="paper", x=0.5, y=0.5, font=dict(size=16))]
            )

        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.45, 0.25, 0.30],
            subplot_titles=("Price & SMAs", "Momentum Score & VIX", "Exposure & Vol Scalar"),
            specs=[[{"secondary_y": False}],
                   [{"secondary_y": True}],
                   [{"secondary_y": True}]],
        )

        # Row 1: Price + SMAs
        fig.add_trace(go.Scatter(
            x=dates, y=closes, mode="lines", name="Close",
            line=dict(color="#333", width=1.5),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=sma20s, mode="lines", name="SMA20",
            line=dict(color="#ff7f0e", width=1, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=sma50s, mode="lines", name="SMA50",
            line=dict(color="#2ca02c", width=1, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=sma200s, mode="lines", name="SMA200",
            line=dict(color="#d62728", width=1.5, dash="dash"),
        ), row=1, col=1)

        # Row 2: Momentum Score (bar) + VIX (right axis)
        # Color bars by score value
        bar_colors = [
            "#2ca02c" if (s or 0) >= 5 else "#ff7f0e" if (s or 0) >= 3 else "#d62728"
            for s in scores
        ]
        fig.add_trace(go.Bar(
            x=dates, y=scores, name="Momentum Score",
            marker_color=bar_colors, opacity=0.7,
        ), row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(
            x=dates, y=vixes, mode="lines", name="VIX",
            line=dict(color="#9467bd", width=1.5),
        ), row=2, col=1, secondary_y=True)

        # Row 3: target_pct + current_pct + vol_scalar (right axis)
        fig.add_trace(go.Scatter(
            x=dates, y=target_pcts, mode="lines", name="Target %",
            line=dict(color="#1f77b4", width=2),
        ), row=3, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(
            x=dates, y=current_pcts, mode="lines", name="Current %",
            fill="tonexty",
            line=dict(color="#9467bd", width=1.5),
            fillcolor="rgba(148, 103, 189, 0.2)",
        ), row=3, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(
            x=dates, y=vol_scalars, mode="lines", name="Vol Scalar",
            line=dict(color="#ff7f0e", width=1, dash="dash"),
        ), row=3, col=1, secondary_y=True)

        # Axis labels
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Score (0-7)", row=2, col=1, secondary_y=False,
                         range=[0, 7.5])
        fig.update_yaxes(title_text="VIX", row=2, col=1, secondary_y=True)
        fig.update_yaxes(title_text="Exposure %", row=3, col=1, secondary_y=False,
                         tickformat=".0%")
        fig.update_yaxes(title_text="Vol Scalar", row=3, col=1, secondary_y=True)

        fig.update_layout(
            title="Strategy Indicators",
            height=800,
            margin=dict(l=60, r=60, t=60, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            barmode="overlay",
        )
        return fig

    def generate_report(
        self,
        output_path: str | Path,
        include_charts: list[str] | None = None,
        slice_engine=None,
    ) -> Path:
        """生成独立 HTML 报告

        Args:
            output_path: 输出文件路径
            include_charts: 要包含的图表 (默认全部)
                可选: ["equity", "benchmark", "drawdown", "monthly", "asset", "timeline",
                       "symbol_klines", "spy_kline", "vix_kline", "events_calendar", "attribution"]
            slice_engine: SliceAttributionEngine 实例 (可选，用于切片归因图表)

        Returns:
            输出文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 默认包含所有图表
        if include_charts is None:
            include_charts = [
                "equity", "benchmark", "drawdown", "monthly", "asset",
                "position_pct", "strategy_indicators",
                "signal_timeline",
                "symbol_klines", "spy_kline", "vix_kline", "events_calendar",
                "attribution",
            ]

        # 生成图表 HTML
        chart_html_list = []

        if "equity" in include_charts:
            fig = self.create_equity_curve()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        # Benchmark comparison chart (单独的收益率对比图)
        if "benchmark" in include_charts and self._benchmark_result is not None:
            fig = self.create_benchmark_comparison()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "drawdown" in include_charts:
            fig = self.create_drawdown_chart()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "monthly" in include_charts:
            fig = self.create_monthly_returns_heatmap()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        if "asset" in include_charts:
            fig = self.create_asset_breakdown()
            chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

        # Position Exposure % chart
        if "position_pct" in include_charts:
            try:
                fig = self.create_position_pct_chart()
                chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception:
                pass

        # Strategy Indicators chart
        if "strategy_indicators" in include_charts:
            try:
                fig = self.create_strategy_indicators_chart()
                chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception:
                pass

        # Signal Timeline (股价 + 均线 + 交易信号)
        if "signal_timeline" in include_charts and self._market_context:
            for symbol in self._market_context.symbol_klines:
                try:
                    fig = self.create_signal_timeline(symbol)
                    chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
                except Exception:
                    pass

        # Symbol K-lines (每个标的一张)
        if "symbol_klines" in include_charts and self._market_context:
            for symbol in self._market_context.symbol_klines:
                try:
                    fig = self.create_symbol_kline(symbol)
                    chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
                except Exception:
                    pass

        # SPY K-line
        if "spy_kline" in include_charts:
            try:
                fig = self.create_spy_kline()
                chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception:
                pass

        # VIX K-line
        if "vix_kline" in include_charts:
            try:
                fig = self.create_vix_kline()
                chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception:
                pass

        # Events Calendar
        if "events_calendar" in include_charts:
            try:
                fig = self.create_events_calendar()
                chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception:
                pass

        # 归因图表 (如果有归因数据)
        if "attribution" in include_charts and self._attribution_charts is not None:
            try:
                fig = self._attribution_charts.create_cumulative_attribution()
                chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

                # 切片归因图表
                if slice_engine is not None:
                    by_underlying = slice_engine.by_underlying()
                    if by_underlying:
                        fig = self._attribution_charts.create_slice_comparison(
                            by_underlying, title="Attribution by Underlying"
                        )
                        chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

                    by_exit = slice_engine.by_exit_reason()
                    if by_exit:
                        fig = self._attribution_charts.create_slice_comparison(
                            by_exit, title="Attribution by Exit Reason"
                        )
                        chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

                    by_type = slice_engine.by_option_type()
                    if by_type:
                        fig = self._attribution_charts.create_slice_comparison(
                            by_type, title="Attribution by Option Type"
                        )
                        chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

                # Entry Quality Analysis
                if self._entry_report is not None:
                    fig = self._attribution_charts.create_entry_quality_chart(
                        self._entry_report
                    )
                    chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))

                # Exit Quality Analysis
                if self._exit_report is not None:
                    fig = self._attribution_charts.create_exit_quality_chart(
                        self._exit_report
                    )
                    chart_html_list.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception:
                pass

        # 生成指标面板
        metrics_html = self.create_metrics_panel()
        benchmark_metrics_html = self.create_benchmark_metrics_panel()
        trade_records_html = self.create_trade_records_table()
        holdings_html = self.create_holdings_table()

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

        {holdings_html}

        <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">

        {charts_combined}

        {trade_records_html}

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


class _FOMCEvent:
    """轻量 FOMC 事件 (从静态 YAML 加载，无需完整 EconomicEvent)"""

    def __init__(self, event_date: date) -> None:
        self.event_date = event_date
        self.event_type = type("_ET", (), {"name": "FOMC"})()
        self.impact = type("_EI", (), {"name": "HIGH"})()
        self.name = "FOMC Meeting"


def _get_event_type_name(event) -> str:
    """获取事件类型名称 (兼容 EconomicEvent 和 _FOMCEvent)"""
    et = getattr(event, "event_type", None)
    if et is None:
        return "OTHER"
    return et.name if hasattr(et, "name") else str(et)


def _get_event_date(event) -> date:
    """获取事件日期"""
    return getattr(event, "event_date", date.today())


def _get_event_impact(event) -> str:
    """获取事件影响级别"""
    impact = getattr(event, "impact", None)
    if impact is None:
        return "LOW"
    return impact.name if hasattr(impact, "name") else str(impact)


def _get_event_name(event) -> str:
    """获取事件名称"""
    return getattr(event, "name", "Unknown Event")
