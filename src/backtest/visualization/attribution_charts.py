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
        EntryQualityReport,
        ExitQualityReport,
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
        cum_residual = _cumsum([d.residual for d in self._daily])
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
            x=dates, y=cum_residual,
            mode="lines", name="Residual PnL",
            line=dict(color=COLORS["residual"]),
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
        fig.add_trace(go.Bar(
            x=labels, y=[s.residual for s in stats],
            name="Residual", marker_color=COLORS["residual"],
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


    def create_trade_attribution_table(self) -> go.Figure:
        """Per-Trade 归因表 (Plotly Table)

        显示每笔交易的归因分解，按 total_pnl 降序排列。
        盈利行绿色，亏损行红色。
        """
        if not self._trades:
            fig = go.Figure()
            fig.add_annotation(
                text="No trade attribution data",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(title="Per-Trade Attribution")
            return fig

        sorted_trades = sorted(self._trades, key=lambda t: t.total_pnl, reverse=True)

        # Build columns
        underlyings = [t.underlying for t in sorted_trades]
        opt_types = [t.option_type.upper() if t.option_type else "" for t in sorted_trades]
        strikes = [f"${t.strike:.0f}" for t in sorted_trades]
        entry_dates = [t.entry_date.isoformat() for t in sorted_trades]
        exit_dates = [t.exit_date.isoformat() if t.exit_date else "-" for t in sorted_trades]
        qtys = [t.quantity for t in sorted_trades]
        holding = [t.holding_days for t in sorted_trades]

        # ROC Annual = (total_pnl / cost_basis) * (365 / holding_days)
        # cost_basis = entry_price * abs(quantity) * lot_size
        roc_annuals = []
        for t in sorted_trades:
            cost_basis = t.entry_price * abs(t.quantity) * t.lot_size
            if cost_basis > 0 and t.holding_days > 0:
                roc_ann = (t.total_pnl / cost_basis) * (365 / t.holding_days)
                roc_annuals.append(f"{roc_ann:.0%}")
            else:
                roc_annuals.append("-")

        total_pnls = [f"${t.total_pnl:,.0f}" for t in sorted_trades]
        delta_pnls = [f"${t.delta_pnl:,.0f}" for t in sorted_trades]
        gamma_pnls = [f"${t.gamma_pnl:,.0f}" for t in sorted_trades]
        theta_pnls = [f"${t.theta_pnl:,.0f}" for t in sorted_trades]
        vega_pnls = [f"${t.vega_pnl:,.0f}" for t in sorted_trades]
        residuals = [f"${t.residual:,.0f}" for t in sorted_trades]
        entry_ivs = [f"{t.entry_iv:.1%}" if t.entry_iv else "-" for t in sorted_trades]
        exit_ivs = [f"{t.exit_iv:.1%}" if t.exit_iv else "-" for t in sorted_trades]
        exit_reasons = [t.exit_reason or "-" for t in sorted_trades]

        # Row colors: green for profit, red for loss
        row_colors = [
            "rgba(46, 204, 113, 0.15)" if t.total_pnl >= 0 else "rgba(231, 76, 60, 0.15)"
            for t in sorted_trades
        ]

        n_cols = 17
        fig = go.Figure(go.Table(
            header=dict(
                values=["Underlying", "Type", "Strike", "Entry", "Exit",
                        "Qty", "Days", "ROC Ann.",
                        "Total PnL", "Delta", "Gamma", "Theta",
                        "Vega", "Residual", "Entry IV", "Exit IV", "Exit Reason"],
                fill_color="#f8f9fa",
                align="center",
                font=dict(size=11, color="#333"),
                line_color="#dee2e6",
            ),
            cells=dict(
                values=[underlyings, opt_types, strikes, entry_dates, exit_dates,
                        qtys, holding, roc_annuals,
                        total_pnls, delta_pnls, gamma_pnls, theta_pnls,
                        vega_pnls, residuals, entry_ivs, exit_ivs, exit_reasons],
                fill_color=[row_colors] * n_cols,
                align=["left", "center", "right", "center", "center",
                       "right", "right", "right",
                       "right", "right", "right", "right",
                       "right", "right", "right", "right", "left"],
                font=dict(size=10),
                line_color="#dee2e6",
                height=25,
            ),
        ))

        fig.update_layout(
            title="Per-Trade Attribution",
            height=max(400, 60 + 25 * len(sorted_trades)),
            margin=dict(l=20, r=20, t=40, b=20),
        )

        return fig

    def create_entry_quality_chart(
        self,
        entry_report: "EntryQualityReport",
    ) -> go.Figure:
        """入场质量散点图

        优先 X = Entry IV Rank；若 IV Rank 全部不可用，fallback 到 Entry IV。
        Y = Trade PnL，颜色区分正/负 VRP (IV-RV spread)。
        """
        # 优先使用 iv_rank
        trades_with_rank = [
            t for t in entry_report.trades if t.entry_iv_rank is not None
        ]
        # fallback: 用 entry_iv
        trades_with_iv = [
            t for t in entry_report.trades if t.entry_iv is not None
        ]

        if trades_with_rank:
            trades_with_data = trades_with_rank
            x_values = [t.entry_iv_rank for t in trades_with_data]
            x_label = "Entry IV Rank (0-100)"
            vline_x = 50
        elif trades_with_iv:
            trades_with_data = trades_with_iv
            x_values = [t.entry_iv * 100 for t in trades_with_data]  # 转为百分比显示
            x_label = "Entry IV (%)"
            vline_x = None
        else:
            fig = go.Figure()
            fig.add_annotation(
                text="No entry quality data (IV unavailable)",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(title="Entry Quality Analysis")
            return fig

        # Match trades to trade_attributions for PnL
        pnl_map = {t.trade_id: t.total_pnl for t in self._trades}

        pnls = [pnl_map.get(t.trade_id, 0.0) for t in trades_with_data]
        colors = [
            COLORS["positive"] if (t.iv_rv_spread is not None and t.iv_rv_spread > 0)
            else COLORS["negative"] if (t.iv_rv_spread is not None and t.iv_rv_spread <= 0)
            else COLORS["residual"]
            for t in trades_with_data
        ]

        def _hover(t):
            parts = [t.underlying]
            if t.entry_iv_rank is not None:
                parts.append(f"IV Rank: {t.entry_iv_rank:.0f}")
            if t.entry_iv is not None:
                parts.append(f"Entry IV: {t.entry_iv:.1%}")
            if t.realized_vol is not None:
                parts.append(f"RV: {t.realized_vol:.1%}")
            if t.iv_rv_spread is not None:
                parts.append(f"VRP: {t.iv_rv_spread:+.1%}")
            return "<br>".join(parts)

        hover_texts = [_hover(t) for t in trades_with_data]

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=x_values,
            y=pnls,
            mode="markers",
            marker=dict(
                size=10,
                color=colors,
                line=dict(width=1, color="white"),
            ),
            text=hover_texts,
            hovertemplate="%{text}<br>PnL: $%{y:,.0f}<extra></extra>",
        ))

        fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
        if vline_x is not None:
            fig.add_vline(x=vline_x, line_dash="dot", line_color="gray", opacity=0.5)

        # Summary annotations
        summary_parts = []
        if entry_report.avg_entry_iv_rank is not None:
            summary_parts.append(f"Avg IV Rank: {entry_report.avg_entry_iv_rank:.0f}")
            summary_parts.append(f"High IV Entry: {entry_report.high_iv_entry_pct:.0%}")
        if entry_report.avg_iv_rv_spread is not None:
            summary_parts.append(f"Avg VRP: {entry_report.avg_iv_rv_spread:+.1%}")
        summary_parts.append(f"Positive VRP: {entry_report.positive_vrp_pct:.0%}")
        summary_text = "  |  ".join(summary_parts)

        fig.update_layout(
            title="Entry Quality Analysis",
            xaxis_title=x_label,
            yaxis_title="Trade PnL ($)",
            height=450,
            annotations=[dict(
                text=summary_text,
                xref="paper", yref="paper",
                x=0.5, y=1.05,
                showarrow=False,
                font=dict(size=11, color="#666"),
            )],
        )

        return fig

    def create_exit_quality_chart(
        self,
        exit_report: "ExitQualityReport",
    ) -> go.Figure:
        """出场质量分析

        交易数 <= 20: 水平分组柱状图 (Actual PnL vs If Held PnL per trade)
        交易数 > 20: 交互式表格 + 汇总结论

        每条 Y 轴为一笔被 CLOSE 的交易，标签为 per-trade 标识。
        """
        evaluated = [t for t in exit_report.trades if t.pnl_if_held_to_expiry is not None]

        if not evaluated:
            fig = go.Figure()
            fig.add_annotation(
                text="No exit quality data (no counterfactual available)",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=14, color="gray"),
            )
            fig.update_layout(title="Exit Quality Analysis")
            return fig

        # 关联 trade_attributions 获取 option_type / strike
        ta_map = {t.trade_id: t for t in self._trades}

        # Sort by exit_benefit descending
        evaluated.sort(key=lambda t: (t.exit_benefit or 0), reverse=True)

        # Per-trade labels: "SPY PUT $550 (03-15)"
        def _make_label(t, idx: int) -> str:
            ta = ta_map.get(t.trade_id)
            if ta:
                opt = ta.option_type.upper() if ta.option_type else ""
                strike = f"${ta.strike:.0f}" if ta.strike else ""
                exit_dt = ta.exit_date.strftime("%m-%d") if ta.exit_date else ""
                return f"{t.underlying} {opt} {strike} ({exit_dt})"
            return f"Trade #{idx + 1} {t.underlying}"

        labels = [_make_label(t, i) for i, t in enumerate(evaluated)]

        # 交易数多时用表格
        if len(evaluated) > 20:
            return self._exit_quality_table(evaluated, ta_map, exit_report)

        # 交易数少时用分组柱状图
        actual_pnls = [t.actual_pnl for t in evaluated]
        held_pnls = [t.pnl_if_held_to_expiry for t in evaluated]

        # Build verdict hover text
        verdict_hovers = []
        for t in evaluated:
            reason = getattr(t, "verdict_reason", "")
            if t.was_good_exit:
                if reason == "freed_capital":
                    verdict_hovers.append("Good (freed capital)")
                elif reason == "better_ann_return":
                    verdict_hovers.append("Good (better ann. return)")
                else:
                    verdict_hovers.append("Good")
            else:
                verdict_hovers.append("Bad")

        fig = go.Figure()

        fig.add_trace(go.Bar(
            y=labels,
            x=actual_pnls,
            name="Actual PnL",
            orientation="h",
            marker_color=[
                COLORS["positive"] if p >= 0 else COLORS["negative"]
                for p in actual_pnls
            ],
            opacity=0.9,
            customdata=verdict_hovers,
            hovertemplate="%{y}<br>Actual PnL: $%{x:,.0f}<br>Verdict: %{customdata}<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            y=labels,
            x=held_pnls,
            name="If Held to Expiry",
            orientation="h",
            marker_color="#95a5a6",
            opacity=0.6,
            hovertemplate="%{y}<br>If Held: $%{x:,.0f}<extra></extra>",
        ))

        # 构建统计结论 — 嵌入 title 副标题行
        summary_line = (
            f"Good Exit Rate: {exit_report.good_exit_rate:.0%}"
            f"  |  Avg Benefit: ${exit_report.avg_exit_benefit:+,.0f}/trade"
            f"  |  Saved: ${exit_report.total_saved_by_exit:,.0f}"
            f"  |  Lost: ${exit_report.total_lost_by_exit:,.0f}"
            f"  |  Net Exit Value: ${exit_report.net_exit_value:+,.0f}"
        )
        title_html = (
            "Exit Quality Analysis (Actual vs Hold-to-Expiry)"
            f"<br><span style='font-size:12px;color:#666'>{summary_line}</span>"
        )

        fig.update_layout(
            title=dict(text=title_html),
            xaxis_title="PnL ($)",
            barmode="group",
            height=max(400, 60 + 35 * len(evaluated)),
        )

        return fig

    def _exit_quality_table(
        self,
        evaluated: list,
        ta_map: dict,
        exit_report: "ExitQualityReport | None" = None,
    ) -> go.Figure:
        """出场质量表格 (交易数多时使用)"""
        # Build columns
        underlyings = []
        opt_types = []
        strikes = []
        entry_dates = []
        qtys = []
        expire_dates = []
        exit_dates = []
        exit_reasons = []
        actual_pnls = []
        held_pnls = []
        benefits = []
        verdicts = []

        for t in evaluated:
            ta = ta_map.get(t.trade_id)
            underlyings.append(t.underlying)
            opt_types.append(
                (ta.option_type.upper() if ta and ta.option_type else "")
            )
            strikes.append(f"${ta.strike:.0f}" if ta and ta.strike else "-")
            entry_dates.append(
                t.entry_date.isoformat() if t.entry_date else
                (ta.entry_date.isoformat() if ta and ta.entry_date else "-")
            )
            qtys.append(ta.quantity if ta else 0)
            expire_dates.append(
                t.expiration.isoformat() if t.expiration else "-"
            )
            exit_dates.append(
                ta.exit_date.isoformat() if ta and ta.exit_date else "-"
            )
            exit_reasons.append(t.exit_reason[:30] if t.exit_reason else "-")
            actual_pnls.append(f"${t.actual_pnl:,.0f}")
            held_pnls.append(
                f"${t.pnl_if_held_to_expiry:,.0f}"
                if t.pnl_if_held_to_expiry is not None else "-"
            )
            eb = t.exit_benefit or 0
            benefits.append(f"${eb:+,.0f}")
            reason = getattr(t, "verdict_reason", "")
            if t.was_good_exit:
                if reason == "freed_capital":
                    verdicts.append("Good*")
                elif reason == "better_ann_return":
                    verdicts.append("Good\u2020")
                else:
                    verdicts.append("Good")
            else:
                verdicts.append("Bad")

        # 添加汇总行
        total_actual = sum(t.actual_pnl for t in evaluated)
        total_held = sum(
            t.pnl_if_held_to_expiry for t in evaluated
            if t.pnl_if_held_to_expiry is not None
        )
        total_benefit = sum((t.exit_benefit or 0) for t in evaluated)
        good_count = sum(1 for t in evaluated if t.was_good_exit)

        underlyings.append(f"TOTAL ({len(evaluated)} trades)")
        opt_types.append("")
        strikes.append("")
        entry_dates.append("")
        qtys.append("")
        exit_dates.append("")
        expire_dates.append("")
        exit_reasons.append("")
        actual_pnls.append(f"${total_actual:,.0f}")
        held_pnls.append(f"${total_held:,.0f}")
        benefits.append(f"${total_benefit:+,.0f}")
        verdicts.append(f"{good_count}/{len(evaluated)} Good")

        row_colors = [
            "rgba(46, 204, 113, 0.15)" if t.was_good_exit
            else "rgba(231, 76, 60, 0.15)"
            for t in evaluated
        ]
        # 汇总行使用加粗背景
        row_colors.append("rgba(52, 73, 94, 0.12)")

        # 字体：汇总行加粗
        n = len(evaluated)
        n_cols = 12
        font_sizes = [[10] * n + [11]] * n_cols
        font_colors = [["#333"] * n + ["#222"]] * n_cols

        fig = go.Figure(go.Table(
            header=dict(
                values=["Underlying", "Type", "Strike", "Entry Date",
                        "Qty", "Exit Date", "Expire Date",
                        "Exit Reason", "Actual PnL", "If Held", "Benefit", "Verdict"],
                fill_color="#f8f9fa",
                align="center",
                font=dict(size=11, color="#333"),
                line_color="#dee2e6",
            ),
            cells=dict(
                values=[underlyings, opt_types, strikes, entry_dates,
                        qtys, exit_dates, expire_dates,
                        exit_reasons, actual_pnls, held_pnls, benefits, verdicts],
                fill_color=[row_colors] * n_cols,
                align=["left", "center", "right", "center",
                       "right", "center", "center",
                       "left", "right", "right", "right", "center"],
                font=dict(size=font_sizes[0], color=font_colors[0]),
                line_color="#dee2e6",
                height=25,
            ),
        ))

        # 检查是否需要脚注
        has_freed = any(getattr(t, "verdict_reason", "") == "freed_capital" for t in evaluated)
        has_ann = any(getattr(t, "verdict_reason", "") == "better_ann_return" for t in evaluated)
        footnotes = []
        if has_freed:
            footnotes.append("* Same PnL as hold-to-expiry, but freed capital & time earlier")
        if has_ann:
            footnotes.append("\u2020 Negative benefit, but higher annualized return (more efficient capital use)")

        # 构建统计结论 — 嵌入 title 副标题行（annotation 在 Table 中容易被裁剪）
        if exit_report:
            summary_line = (
                f"Good Exit Rate: {exit_report.good_exit_rate:.0%}"
                f"  |  Avg Benefit: ${exit_report.avg_exit_benefit:+,.0f}/trade"
                f"  |  Saved: ${exit_report.total_saved_by_exit:,.0f}"
                f"  |  Lost: ${exit_report.total_lost_by_exit:,.0f}"
                f"  |  Net Exit Value: ${exit_report.net_exit_value:+,.0f}"
            )
        else:
            summary_line = f"Good Exit Rate: {good_count}/{len(evaluated)}"

        title_html = (
            "Exit Quality Analysis"
            f"<br><span style='font-size:12px;color:#666'>{summary_line}</span>"
        )

        footnote_text = "<br>".join(footnotes)
        annotations = []
        if footnote_text:
            annotations.append(dict(
                text=footnote_text,
                xref="paper", yref="paper",
                x=0.0, y=-0.02,
                showarrow=False,
                font=dict(size=9, color="#999"),
                align="left",
                xanchor="left",
                yanchor="top",
            ))

        fig.update_layout(
            title=dict(text=title_html),
            height=max(400, 80 + 25 * (len(evaluated) + 1)),
            margin=dict(l=20, r=20, t=70, b=40 if footnotes else 20),
            annotations=annotations if annotations else None,
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
