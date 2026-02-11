"""
Attribution Charts - 归因可视化图表

提供 Greeks 归因相关的交互式 Plotly 图表:
- PnL 瀑布图 (单日归因分解)
- 累计归因面积图 (Delta/Gamma/Theta/Vega 随时间累计)
- 每日归因柱状图
- 组合 Greeks 暴露时间序列
- 切片对比柱状图
- Regime 表现热力图

Usage:
    charts = AttributionCharts(daily_attributions, trade_attributions, portfolio_snapshots)
    fig = charts.create_cumulative_attribution()
    fig.show()
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

if TYPE_CHECKING:
    from src.backtest.attribution.models import (
        DailyAttribution,
        PortfolioSnapshot,
        RegimeStats,
        SliceStats,
        TradeAttribution,
    )

# 配色
COLORS = {
    "delta": "#1f77b4",  # 蓝色
    "gamma": "#ff7f0e",  # 橙色
    "theta": "#2ca02c",  # 绿色
    "vega": "#d62728",  # 红色
    "residual": "#9467bd",  # 紫色
    "total": "#333333",
    "positive": "#2ca02c",
    "negative": "#d62728",
}


def _check_plotly():
    if not PLOTLY_AVAILABLE:
        raise ImportError("Plotly is required. Install with: pip install plotly")


class AttributionCharts:
    """归因可视化图表"""

    def __init__(
        self,
        daily_attributions: list[DailyAttribution],
        trade_attributions: list[TradeAttribution] | None = None,
        portfolio_snapshots: list[PortfolioSnapshot] | None = None,
    ) -> None:
        _check_plotly()
        self._daily = daily_attributions
        self._trades = trade_attributions or []
        self._portfolio = portfolio_snapshots or []

    def create_pnl_waterfall(self, target_date: date | None = None) -> go.Figure:
        """单日 PnL 瀑布图

        显示 Delta/Gamma/Theta/Vega/Residual 对 total PnL 的贡献。

        Args:
            target_date: 目标日期，默认取 PnL 绝对值最大的一天
        """
        if target_date is None:
            # 选 PnL 绝对值最大的一天
            attr = max(self._daily, key=lambda d: abs(d.total_pnl))
        else:
            attr = next((d for d in self._daily if d.date == target_date), None)
            if attr is None:
                raise ValueError(f"No attribution data for {target_date}")

        labels = ["Delta", "Gamma", "Theta", "Vega", "Residual", "Total"]
        values = [
            attr.delta_pnl,
            attr.gamma_pnl,
            attr.theta_pnl,
            attr.vega_pnl,
            attr.residual,
            attr.total_pnl,
        ]
        measures = ["relative", "relative", "relative", "relative", "relative", "total"]

        fig = go.Figure(go.Waterfall(
            name="PnL Attribution",
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            increasing={"marker": {"color": COLORS["positive"]}},
            decreasing={"marker": {"color": COLORS["negative"]}},
            totals={"marker": {"color": COLORS["total"]}},
            textposition="outside",
            text=[f"${v:,.0f}" for v in values],
        ))

        fig.update_layout(
            title=f"PnL Attribution Waterfall - {attr.date}",
            yaxis_title="PnL ($)",
            showlegend=False,
            height=450,
        )

        return fig

    def create_cumulative_attribution(self) -> go.Figure:
        """累计归因面积图

        展示 Delta/Gamma/Theta/Vega 各因子的累计 PnL 随时间的变化。
        """
        dates = [d.date for d in self._daily]
        cum_delta = _cumsum([d.delta_pnl for d in self._daily])
        cum_gamma = _cumsum([d.gamma_pnl for d in self._daily])
        cum_theta = _cumsum([d.theta_pnl for d in self._daily])
        cum_vega = _cumsum([d.vega_pnl for d in self._daily])
        cum_total = _cumsum([d.total_pnl for d in self._daily])

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=dates, y=cum_delta,
            mode="lines", name="Delta PnL",
            line=dict(color=COLORS["delta"]),
            stackgroup="one",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=cum_gamma,
            mode="lines", name="Gamma PnL",
            line=dict(color=COLORS["gamma"]),
            stackgroup="one",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=cum_theta,
            mode="lines", name="Theta PnL",
            line=dict(color=COLORS["theta"]),
            stackgroup="one",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=cum_vega,
            mode="lines", name="Vega PnL",
            line=dict(color=COLORS["vega"]),
            stackgroup="one",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=cum_total,
            mode="lines", name="Total PnL",
            line=dict(color=COLORS["total"], width=2, dash="dot"),
        ))

        fig.update_layout(
            title="Cumulative PnL Attribution",
            xaxis_title="Date",
            yaxis_title="Cumulative PnL ($)",
            hovermode="x unified",
            height=450,
        )

        return fig

    def create_daily_attribution_bar(self) -> go.Figure:
        """每日归因堆叠柱状图"""
        dates = [d.date for d in self._daily]

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=dates, y=[d.delta_pnl for d in self._daily],
            name="Delta", marker_color=COLORS["delta"],
        ))
        fig.add_trace(go.Bar(
            x=dates, y=[d.gamma_pnl for d in self._daily],
            name="Gamma", marker_color=COLORS["gamma"],
        ))
        fig.add_trace(go.Bar(
            x=dates, y=[d.theta_pnl for d in self._daily],
            name="Theta", marker_color=COLORS["theta"],
        ))
        fig.add_trace(go.Bar(
            x=dates, y=[d.vega_pnl for d in self._daily],
            name="Vega", marker_color=COLORS["vega"],
        ))
        fig.add_trace(go.Bar(
            x=dates, y=[d.residual for d in self._daily],
            name="Residual", marker_color=COLORS["residual"],
        ))

        fig.update_layout(
            title="Daily PnL Attribution",
            xaxis_title="Date",
            yaxis_title="PnL ($)",
            barmode="relative",
            hovermode="x unified",
            height=450,
        )

        return fig

    def create_greeks_exposure_timeline(self) -> go.Figure:
        """组合 Greeks 暴露时间序列 (2×2 子图)

        从 PortfolioSnapshot 数据绘制 Delta/Gamma/Theta/Vega 暴露。
        每个 Greek 独立坐标轴，避免量级差异导致互相遮盖。
        """
        if not self._portfolio:
            return go.Figure().update_layout(title="No portfolio data")

        dates = [p.date for p in self._portfolio]

        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("Portfolio Delta", "Portfolio Gamma",
                            "Portfolio Theta", "Portfolio Vega"),
            horizontal_spacing=0.12,
            vertical_spacing=0.12,
        )

        fig.add_trace(go.Scatter(
            x=dates, y=[p.portfolio_delta for p in self._portfolio],
            mode="lines", name="Delta",
            line=dict(color=COLORS["delta"]),
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=dates, y=[p.portfolio_gamma for p in self._portfolio],
            mode="lines", name="Gamma",
            line=dict(color=COLORS["gamma"]),
        ), row=1, col=2)

        fig.add_trace(go.Scatter(
            x=dates, y=[p.portfolio_theta for p in self._portfolio],
            mode="lines", name="Theta",
            line=dict(color=COLORS["theta"]),
        ), row=2, col=1)

        fig.add_trace(go.Scatter(
            x=dates, y=[p.portfolio_vega for p in self._portfolio],
            mode="lines", name="Vega",
            line=dict(color=COLORS["vega"]),
        ), row=2, col=2)

        fig.update_layout(
            title="Portfolio Greeks Exposure",
            hovermode="x unified",
            height=600,
            showlegend=False,
        )

        return fig

    def create_slice_comparison(
        self,
        slice_data: dict[str, SliceStats],
        title: str = "Slice Attribution Comparison",
    ) -> go.Figure:
        """切片对比柱状图"""
        labels = list(slice_data.keys())
        stats = list(slice_data.values())

        fig = go.Figure()

        fig.add_trace(go.Bar(
            x=labels, y=[s.delta_pnl for s in stats],
            name="Delta", marker_color=COLORS["delta"],
        ))
        fig.add_trace(go.Bar(
            x=labels, y=[s.gamma_pnl for s in stats],
            name="Gamma", marker_color=COLORS["gamma"],
        ))
        fig.add_trace(go.Bar(
            x=labels, y=[s.theta_pnl for s in stats],
            name="Theta", marker_color=COLORS["theta"],
        ))
        fig.add_trace(go.Bar(
            x=labels, y=[s.vega_pnl for s in stats],
            name="Vega", marker_color=COLORS["vega"],
        ))

        fig.update_layout(
            title=title,
            xaxis_title="Slice",
            yaxis_title="PnL ($)",
            barmode="group",
            height=400,
        )

        return fig

    def create_regime_heatmap(
        self,
        regime_stats: dict[str, RegimeStats],
    ) -> go.Figure:
        """Regime 表现热力图"""
        labels = list(regime_stats.keys())
        stats = list(regime_stats.values())

        fig = go.Figure(go.Bar(
            x=labels,
            y=[s.avg_daily_pnl for s in stats],
            marker=dict(
                color=[s.avg_daily_pnl for s in stats],
                colorscale="RdYlGn",
                showscale=True,
                colorbar=dict(title="Avg Daily PnL"),
            ),
            text=[
                f"Days: {s.trading_days}<br>"
                f"Win: {s.win_rate:.0%}<br>"
                f"Sharpe: {s.sharpe_ratio:.2f}" if s.sharpe_ratio else
                f"Days: {s.trading_days}<br>Win: {s.win_rate:.0%}"
                for s in stats
            ],
            textposition="outside",
        ))

        fig.update_layout(
            title="Strategy Performance by Market Regime",
            xaxis_title="Regime",
            yaxis_title="Average Daily PnL ($)",
            height=450,
        )

        return fig


def _cumsum(values: list[float]) -> list[float]:
    """累计求和"""
    result: list[float] = []
    running = 0.0
    for v in values:
        running += v
        result.append(running)
    return result
