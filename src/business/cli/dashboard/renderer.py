"""Dashboard renderer for CLI.

Renders the monitoring dashboard with multiple panels:
- Portfolio Health (Greeks, TGR, HHI)
- Capital Management (Sharpe, Kelly, Margin, Drawdown)
- Risk Heatmap (PREI/SAS by symbol)
- Todo List (Suggestions)
- Option Positions Table
- Stock Positions Table
"""

from datetime import datetime
from typing import Optional

from src.business.config.monitoring_config import MonitoringConfig
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    CapitalMetrics,
    MonitorResult,
    PortfolioMetrics,
    PositionData,
)
from src.business.monitoring.suggestions import PositionSuggestion, UrgencyLevel
from src.business.cli.dashboard.components import (
    alert_icon,
    box_bottom,
    box_line,
    box_title,
    format_pct,
    progress_bar,
    side_by_side,
    table_header,
    table_row,
    table_separator,
    urgency_icon,
)
from src.business.cli.dashboard.threshold_checker import ThresholdChecker


class DashboardRenderer:
    """Dashboard renderer for terminal output."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        """Initialize renderer.

        Args:
            config: Monitoring configuration for thresholds
        """
        self.config = config or MonitoringConfig.load()
        self.checker = ThresholdChecker(self.config)

    def render(self, result: MonitorResult) -> str:
        """Render complete dashboard.

        Args:
            result: MonitorResult from monitoring pipeline

        Returns:
            Formatted dashboard string
        """
        lines = []

        # Title
        title = "实时监控仪表盘"
        timestamp = result.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{'═' * 90}")
        lines.append(f"  {title}  |  {timestamp}  |  状态: {alert_icon(self._status_to_level(result.status))}")
        lines.append(f"{'═' * 90}")
        lines.append("")

        # Row 1: Portfolio Health + Capital Management (side by side)
        portfolio_panel = self._render_portfolio_health(result.portfolio_metrics)
        capital_panel = self._render_capital_panel(result.capital_metrics)
        combined = side_by_side(portfolio_panel, capital_panel, gap=4)
        lines.extend(combined)
        lines.append("")

        # Row 2: Risk Heatmap + Todo List (side by side)
        option_positions = [p for p in result.positions if p.is_option]
        heatmap_panel = self._render_risk_heatmap(option_positions)
        todo_panel = self._render_todo_panel(result.suggestions)
        combined = side_by_side(heatmap_panel, todo_panel, gap=4)
        lines.extend(combined)
        lines.append("")

        # Row 3: Option Positions Table
        if option_positions:
            lines.extend(self._render_option_table(option_positions, result.alerts))
            lines.append("")

        # Row 4: Stock Positions Table
        stock_positions = [p for p in result.positions if p.is_stock]
        if stock_positions:
            lines.extend(self._render_stock_table(stock_positions, result.alerts))
            lines.append("")

        # Footer summary
        lines.append(f"{'─' * 90}")
        lines.append(
            f"  总持仓: {result.total_positions} | "
            f"风险持仓: {result.positions_at_risk} | "
            f"机会持仓: {result.positions_opportunity} | "
            f"预警: 🔴{len(result.red_alerts)} 🟡{len(result.yellow_alerts)} 🟢{len(result.green_alerts)}"
        )
        lines.append(f"{'═' * 90}")

        return "\n".join(lines)

    def _status_to_level(self, status) -> AlertLevel:
        """Convert MonitorStatus to AlertLevel."""
        from src.business.monitoring.models import MonitorStatus
        mapping = {
            MonitorStatus.RED: AlertLevel.RED,
            MonitorStatus.YELLOW: AlertLevel.YELLOW,
            MonitorStatus.GREEN: AlertLevel.GREEN,
        }
        return mapping.get(status, AlertLevel.GREEN)

    def _render_portfolio_health(self, metrics: Optional[PortfolioMetrics]) -> list[str]:
        """Render Portfolio Health panel.

        Uses NLV-normalized percentage metrics for account-size independent display.

        Args:
            metrics: PortfolioMetrics from monitoring result

        Returns:
            List of panel lines
        """
        width = 42
        lines = [box_title("Portfolio健康度", width)]

        if metrics is None:
            lines.append(box_line("无数据", width))
            lines.append(box_bottom(width))
            return lines

        # Define metrics to display (using NLV-normalized percentages)
        # Format: (name, value, min_for_bar, max_for_bar, check_fn, is_percentage)
        items = [
            ("BWD%", metrics.beta_weighted_delta_pct, -0.5, 0.5, self.checker.check_delta_pct, True),
            ("Gamma%", metrics.gamma_pct, -0.005, 0.001, self.checker.check_gamma_pct, True),
            ("Vega%", metrics.vega_pct, -0.006, 0.006, self.checker.check_vega_pct, True),
            ("Theta%", metrics.theta_pct, 0, 0.003, self.checker.check_theta_pct, True),
            ("TGR", metrics.portfolio_tgr, 0, 0.3, self.checker.check_tgr, False),
            ("HHI", metrics.concentration_hhi, 0, 1, self.checker.check_concentration, False),
            ("IV/HV", metrics.vega_weighted_iv_hv, 0, 2, self.checker.check_iv_hv_quality, False),
        ]

        for name, value, min_v, max_v, check_fn, is_pct in items:
            if value is not None:
                if is_pct:
                    # Format as percentage with sign (2 decimal places for precision)
                    val_str = f"{value:+.2%}"
                elif name == "TGR":
                    val_str = f"{value:.2f}"
                elif name == "HHI":
                    val_str = f"{value:.2f}"
                else:  # IV/HV
                    val_str = f"{value:.2f}"
                bar = progress_bar(abs(value), 0, max(abs(min_v), abs(max_v)), 10)
                level = check_fn(value)
                icon = alert_icon(level)
                content = f"{name:7}: {val_str:>8} {bar} {icon}"
            else:
                content = f"{name:7}:        - [──────────] ⚪"
            lines.append(box_line(content, width))

        lines.append(box_bottom(width))
        return lines

    def _render_capital_panel(self, metrics: Optional[CapitalMetrics]) -> list[str]:
        """Render Capital Risk Control panel.

        Displays 4 core risk control metrics (四大支柱):
        1. Margin Utilization (生存)
        2. Cash Ratio (流动性)
        3. Gross Leverage (敞口)
        4. Stress Test Loss (稳健)

        Args:
            metrics: CapitalMetrics from monitoring result

        Returns:
            List of panel lines
        """
        width = 42
        lines = [box_title("资金风控", width)]

        if metrics is None:
            lines.append(box_line("无数据", width))
            lines.append(box_bottom(width))
            return lines

        # 1. Margin Utilization (保证金使用率)
        if metrics.margin_utilization is not None:
            level = self.checker.check_margin_utilization(metrics.margin_utilization)
            content = f"Margin Util: {metrics.margin_utilization:>7.1%}  {alert_icon(level)}"
        else:
            content = "Margin Util:        -"
        lines.append(box_line(content, width))

        # 2. Cash Ratio (现金留存率)
        if metrics.cash_ratio is not None:
            level = self.checker.check_cash_ratio(metrics.cash_ratio)
            content = f"Cash Ratio: {metrics.cash_ratio:>8.1%}  {alert_icon(level)}"
        else:
            content = "Cash Ratio:         -"
        lines.append(box_line(content, width))

        # 3. Gross Leverage (总名义杠杆)
        if metrics.gross_leverage is not None:
            level = self.checker.check_gross_leverage(metrics.gross_leverage)
            content = f"Gross Lev: {metrics.gross_leverage:>8.1f}x  {alert_icon(level)}"
        else:
            content = "Gross Lev:          -"
        lines.append(box_line(content, width))

        # 4. Stress Test Loss (压力测试风险)
        if metrics.stress_test_loss is not None:
            level = self.checker.check_stress_test_loss(metrics.stress_test_loss)
            content = f"Stress Loss: {metrics.stress_test_loss:>6.1%}  {alert_icon(level)}"
        else:
            content = "Stress Loss:        -"
        lines.append(box_line(content, width))

        lines.append(box_bottom(width))
        return lines

    def _render_risk_heatmap(self, positions: list[PositionData]) -> list[str]:
        """Render Risk Heatmap panel.

        Shows PREI and SAS scores by symbol with alert indicators.

        Args:
            positions: List of option positions

        Returns:
            List of panel lines
        """
        width = 42
        lines = [box_title("风险热力图", width)]

        if not positions:
            lines.append(box_line("无期权持仓", width))
            lines.append(box_bottom(width))
            return lines

        # Get unique symbols
        symbols = []
        for p in positions:
            sym = p.underlying or p.symbol
            if sym not in symbols:
                symbols.append(sym)

        # Limit to 6 symbols for display
        symbols = symbols[:6]

        # Header row with symbols
        header = "      " + "".join(f"{s:>6}" for s in symbols)
        lines.append(box_line(header, width))

        # PREI row
        prei_vals = []
        for sym in symbols:
            pos = next((p for p in positions if (p.underlying or p.symbol) == sym), None)
            if pos and pos.prei is not None:
                level = self.checker.check_prei(pos.prei)
                icon = alert_icon(level) if level == AlertLevel.RED else ""
                prei_vals.append(f"{pos.prei:>4.0f}{icon}")
            else:
                prei_vals.append("   -")
        prei_line = "PREI  " + "".join(f"{v:>6}" for v in prei_vals)
        lines.append(box_line(prei_line, width))

        # SAS row
        sas_vals = []
        for sym in symbols:
            pos = next((p for p in positions if (p.underlying or p.symbol) == sym), None)
            if pos and pos.sas is not None:
                level = self.checker.check_sas(pos.sas)
                icon = alert_icon(level) if level == AlertLevel.GREEN else ""
                sas_vals.append(f"{pos.sas:>4.0f}{icon}")
            else:
                sas_vals.append("   -")
        sas_line = "SAS   " + "".join(f"{v:>6}" for v in sas_vals)
        lines.append(box_line(sas_line, width))

        lines.append(box_bottom(width))
        return lines

    def _render_todo_panel(self, suggestions: list[PositionSuggestion]) -> list[str]:
        """Render Today's Todo panel.

        Shows top suggestions sorted by urgency.

        Args:
            suggestions: List of position suggestions

        Returns:
            List of panel lines
        """
        width = 42
        lines = [box_title("今日待办", width)]

        if not suggestions:
            lines.append(box_line("暂无待办事项", width))
            lines.append(box_bottom(width))
            return lines

        # Sort by urgency
        urgency_order = {UrgencyLevel.IMMEDIATE: 0, UrgencyLevel.SOON: 1, UrgencyLevel.MONITOR: 2}
        sorted_suggestions = sorted(suggestions, key=lambda s: urgency_order.get(s.urgency, 3))

        # Show top 5 items
        for s in sorted_suggestions[:5]:
            icon = urgency_icon(s.urgency.value)
            # Truncate reason if too long
            reason = s.reason[:28] if len(s.reason) > 28 else s.reason
            content = f"{icon} [{s.symbol}] {reason}"
            lines.append(box_line(content, width))

        # Pad to minimum height
        while len(lines) < 6:
            lines.append(box_line("", width))

        lines.append(box_bottom(width))
        return lines

    def _render_option_table(self, positions: list[PositionData], alerts: list[Alert]) -> list[str]:
        """Render detailed Option Positions tables.

        Displays 5 tables similar to verify_position_strategies.py output:
        1. Position Info (标的, 类型, 行权价, DTE, 数量, 权利金, IV, 标的价, 策略)
        2. Greeks (Delta, Gamma, Theta, Vega, HV, IV, IV/HV)
        3. Core Metrics (E[Return], MaxProfit, MaxLoss, Breakeven, WinProb)
        4. Risk-Adjusted Metrics (PREI, SAS, TGR, ROC, E[ROC], Sharpe, Kelly)
        5. Capital & Margin (Margin, Capital@Risk, ReturnStd)

        Args:
            positions: List of option positions
            alerts: List of alerts to check for position status

        Returns:
            List of table lines
        """
        lines = []

        # 通用前缀列：标的、类型、策略、行权价、Expiry
        def common_prefix(pos):
            """返回统一的前缀列值"""
            return [
                pos.underlying or pos.symbol[:6],
                (pos.option_type or "-")[:4].capitalize(),
                (pos.strategy_type or "-")[:12],
                f"{pos.strike:.1f}" if pos.strike else "-",
                pos.expiry if pos.expiry else "-",
            ]

        # ========== Table 1: Position Information ==========
        lines.append("┌─── 期权持仓明细 " + "─" * 72 + "┐")

        columns1 = [
            ("标的", 6),
            ("类型", 4),
            ("策略", 12),
            ("行权价", 7),
            ("Expiry", 8),
            ("DTE", 4),
            ("正股", 7),  # underlying_price (新增)
            ("OTM%", 5),
            ("Qty", 4),
            ("Prem", 6),
            ("成本", 6),
            ("现价", 6),
            ("PnL%", 7),
            ("状态", 4),
        ]

        lines.append(table_header(columns1))
        lines.append(table_separator(columns1))

        for pos in positions:
            # 数量显示（支持小数，如 1.5 contracts）
            qty = pos.quantity or 0
            qty_str = f"{abs(qty):.1f}" if qty != int(qty) else f"{int(abs(qty))}"

            # 正股现价 (underlying_price)
            underlying_str = f"{pos.underlying_price:.2f}" if pos.underlying_price else "-"

            # OTM% 显示
            otm_str = f"{pos.otm_pct:.0%}" if pos.otm_pct is not None else "-"

            # 权利金（当前价格，每股）
            prem_str = f"{abs(pos.current_price):.2f}" if pos.current_price else "-"

            # 成本价（入场价格，每股）
            cost_str = f"{abs(pos.entry_price):.2f}" if pos.entry_price else "-"

            # 现价（每股，使用绝对值）
            price_str = f"{abs(pos.current_price):.2f}" if pos.current_price else "-"

            # PnL%
            pnl_str = f"{pos.unrealized_pnl_pct:+.1%}" if pos.unrealized_pnl_pct else "-"

            level = self.checker.get_position_overall_level(
                prei=pos.prei,
                dte=pos.dte,
                tgr=pos.tgr,
                otm_pct=pos.otm_pct,
                delta=abs(pos.delta) if pos.delta else None,
                expected_roc=pos.expected_roc,
                win_probability=pos.win_probability,
            )
            status_icon = alert_icon(level) if level else ""

            values = common_prefix(pos) + [
                str(pos.dte) if pos.dte is not None else "-",
                underlying_str,  # 正股现价 (新增)
                otm_str,
                qty_str,
                prem_str,
                cost_str,
                price_str,
                pnl_str,
                status_icon,
            ]
            lines.append(table_row(values, columns1))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 2: Greeks ==========
        lines.append("┌─── Greeks " + "─" * 78 + "┐")

        columns2 = [
            ("标的", 6),
            ("类型", 4),
            ("策略", 12),
            ("行权价", 7),
            ("Expiry", 8),
            ("Delta", 6),
            ("Gamma", 6),
            ("Theta", 6),
            ("Vega", 6),
            ("HV", 6),
            ("IV", 6),
            ("IV/HV", 5),
        ]

        lines.append(table_header(columns2))
        lines.append(table_separator(columns2))

        for pos in positions:
            delta_str = f"{pos.delta:.2f}" if pos.delta is not None else "-"
            gamma_str = f"{pos.gamma:.2f}" if pos.gamma is not None else "-"
            theta_str = f"{pos.theta:.2f}" if pos.theta is not None else "-"
            vega_str = f"{pos.vega:.2f}" if pos.vega is not None else "-"
            hv_str = f"{pos.hv*100:.1f}%" if pos.hv else "-"
            iv_str = f"{pos.iv*100:.1f}%" if pos.iv else "-"
            iv_hv = f"{pos.iv/pos.hv:.2f}" if pos.iv and pos.hv and pos.hv > 0 else "-"

            values = common_prefix(pos) + [
                delta_str,
                gamma_str,
                theta_str,
                vega_str,
                hv_str,
                iv_str,
                iv_hv,
            ]
            lines.append(table_row(values, columns2))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 3: Core Metrics ==========
        lines.append("┌─── 核心指标 " + "─" * 76 + "┐")

        columns3 = [
            ("标的", 6),
            ("类型", 4),
            ("策略", 12),
            ("行权价", 7),
            ("Expiry", 8),
            ("E[Ret]", 7),
            ("MaxProf", 8),
            ("MaxLoss", 8),
            ("BE", 8),
            ("WinPr", 6),
        ]

        lines.append(table_header(columns3))
        lines.append(table_separator(columns3))

        for pos in positions:
            expected_ret = f"{pos.expected_return:.2f}" if pos.expected_return is not None else "-"
            max_prof = f"{pos.max_profit:.2f}" if pos.max_profit is not None else "-"
            max_loss_val = f"{pos.max_loss:.2f}" if pos.max_loss is not None else "-"
            if pos.breakeven is not None:
                if isinstance(pos.breakeven, list):
                    be_str = ",".join([f"{b:.1f}" for b in pos.breakeven])
                else:
                    be_str = f"{pos.breakeven:.2f}"
            else:
                be_str = "-"
            win_prob = f"{pos.win_probability:.0%}" if pos.win_probability is not None else "-"

            values = common_prefix(pos) + [
                expected_ret,
                max_prof,
                max_loss_val,
                be_str,
                win_prob,
            ]
            lines.append(table_row(values, columns3))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 4: Risk-Adjusted Metrics ==========
        lines.append("┌─── 风险调整指标 " + "─" * 72 + "┐")

        columns4 = [
            ("标的", 6),
            ("类型", 4),
            ("策略", 12),
            ("行权价", 7),
            ("Expiry", 8),
            ("PREI", 5),
            ("SAS", 5),
            ("TGR", 6),
            ("ROC", 6),
            ("E[ROC]", 6),
            ("Sharpe", 6),
            ("Kelly", 6),
        ]

        lines.append(table_header(columns4))
        lines.append(table_separator(columns4))

        for pos in positions:
            prei_str = f"{pos.prei:.1f}" if pos.prei is not None else "-"
            sas_str = f"{pos.sas:.1f}" if pos.sas is not None else "-"
            tgr_str = f"{pos.tgr:.3f}" if pos.tgr is not None else "-"
            roc_str = f"{pos.roc:.1%}" if pos.roc is not None else "-"
            eroc_str = f"{pos.expected_roc:.1%}" if pos.expected_roc is not None else "-"
            sharpe_str = f"{pos.sharpe:.3f}" if pos.sharpe is not None else "-"
            kelly_str = f"{pos.kelly:.1%}" if pos.kelly is not None else "-"

            values = common_prefix(pos) + [
                prei_str,
                sas_str,
                tgr_str,
                roc_str,
                eroc_str,
                sharpe_str,
                kelly_str,
            ]
            lines.append(table_row(values, columns4))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 5: Capital & Margin ==========
        lines.append("┌─── 资金与保证金 " + "─" * 72 + "┐")

        columns5 = [
            ("标的", 6),
            ("类型", 4),
            ("策略", 12),
            ("行权价", 7),
            ("Expiry", 8),
            ("Margin", 9),
            ("Cap@Risk", 10),
            ("RetStd", 8),
            ("Mar/Cap", 8),
        ]

        lines.append(table_header(columns5))
        lines.append(table_separator(columns5))

        for pos in positions:
            margin_str = f"${pos.margin:.2f}" if pos.margin is not None else "-"
            car_str = f"${pos.capital_at_risk:.2f}" if pos.capital_at_risk is not None else "-"
            ret_std = f"${pos.return_std:.2f}" if pos.return_std is not None else "-"
            if pos.margin is not None and pos.capital_at_risk and pos.capital_at_risk > 0:
                margin_ratio = f"{pos.margin/pos.capital_at_risk:.1%}"
            else:
                margin_ratio = "-"

            values = common_prefix(pos) + [
                margin_str,
                car_str,
                ret_std,
                margin_ratio,
            ]
            lines.append(table_row(values, columns5))

        lines.append("└" + "─" * 89 + "┘")

        return lines

    def _render_stock_table(self, positions: list[PositionData], alerts: list[Alert]) -> list[str]:
        """Render Stock Positions tables.

        Displays 5 tables for comprehensive stock position data:
        1. Market Data (行情数据)
        2. Fundamental Score (基本面评分)
        3. Volatility Score (波动率评分)
        4. Technical Score (技术面评分)
        5. Technical Signal (技术信号)

        Args:
            positions: List of stock positions
            alerts: List of alerts to check for position status

        Returns:
            List of table lines
        """
        lines = []

        # ========== Table 1: Market Data ==========
        lines.append("┌─── 股票行情 (Market Data) " + "─" * 62 + "┐")

        columns1 = [
            ("标的", 8),
            ("数量", 6),
            ("现价", 8),
            ("成本", 8),
            ("市值", 10),
            ("盈亏%", 8),
            ("盈亏$", 10),
            ("状态", 4),
        ]

        lines.append(table_header(columns1))
        lines.append(table_separator(columns1))

        for pos in positions:
            pnl_pct = f"{pos.unrealized_pnl_pct:+.1%}" if pos.unrealized_pnl_pct else "-"
            pnl_val = f"${pos.unrealized_pnl:,.0f}" if pos.unrealized_pnl else "-"
            market_val = f"${pos.market_value:,.0f}" if pos.market_value else "-"

            # Status based on P&L
            if pos.unrealized_pnl_pct is not None:
                if pos.unrealized_pnl_pct > 0.05:
                    status_icon = alert_icon(AlertLevel.GREEN)
                elif pos.unrealized_pnl_pct < -0.05:
                    status_icon = alert_icon(AlertLevel.RED)
                else:
                    status_icon = ""
            else:
                status_icon = ""

            values = [
                pos.symbol[:8],
                f"{pos.quantity:.0f}" if pos.quantity else "-",
                f"{pos.current_price:.2f}" if pos.current_price else "-",
                f"{pos.entry_price:.2f}" if pos.entry_price else "-",
                market_val,
                pnl_pct,
                pnl_val,
                status_icon,
            ]
            lines.append(table_row(values, columns1))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 2: Fundamental Score ==========
        lines.append("┌─── 基本面评分 (Fundamental) " + "─" * 60 + "┐")

        columns2 = [
            ("标的", 8),
            ("Score", 8),
            ("Rating", 8),
            ("PE", 8),
            ("Beta", 6),
        ]

        lines.append(table_header(columns2))
        lines.append(table_separator(columns2))

        for pos in positions:
            score_str = f"{pos.fundamental_score:.1f}" if pos.fundamental_score is not None else "-"
            rating_str = pos.analyst_rating if pos.analyst_rating else "-"
            pe_str = f"{pos.pe_ratio:.1f}" if pos.pe_ratio is not None else "-"
            beta_str = f"{pos.beta:.2f}" if pos.beta is not None else "-"

            values = [
                pos.symbol[:8],
                score_str,
                rating_str,
                pe_str,
                beta_str,
            ]
            lines.append(table_row(values, columns2))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 3: Volatility Score ==========
        lines.append("┌─── 波动率评分 (Volatility) " + "─" * 61 + "┐")

        columns3 = [
            ("标的", 8),
            ("Score", 8),
            ("Rating", 8),
            ("IV Rank", 8),
            ("IV/HV", 8),
            ("IV Pctl", 8),
        ]

        lines.append(table_header(columns3))
        lines.append(table_separator(columns3))

        for pos in positions:
            score_str = f"{pos.volatility_score:.1f}" if pos.volatility_score is not None else "-"
            rating_str = pos.volatility_rating if pos.volatility_rating else "-"
            iv_rank_str = f"{pos.iv_rank:.1f}" if pos.iv_rank is not None else "-"
            iv_hv_str = f"{pos.iv_hv_ratio:.2f}" if pos.iv_hv_ratio is not None else "-"
            iv_pctl_str = f"{pos.iv_percentile:.0%}" if pos.iv_percentile is not None else "-"

            values = [
                pos.symbol[:8],
                score_str,
                rating_str,
                iv_rank_str,
                iv_hv_str,
                iv_pctl_str,
            ]
            lines.append(table_row(values, columns3))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 4: Technical Score ==========
        lines.append("┌─── 技术面评分 (Technical Score) " + "─" * 56 + "┐")

        columns4 = [
            ("标的", 8),
            ("趋势", 6),
            ("MA对齐", 12),
            ("RSI", 6),
            ("RSI区", 10),
            ("ADX", 6),
            ("支撑", 8),
            ("阻力", 8),
        ]

        lines.append(table_header(columns4))
        lines.append(table_separator(columns4))

        for pos in positions:
            trend_str = (pos.trend_signal or "-")[:6]
            ma_str = (pos.ma_alignment or "-")[:12]
            rsi_str = f"{pos.rsi:.1f}" if pos.rsi is not None else "-"
            rsi_zone_str = (pos.rsi_zone or "-")[:10]
            adx_str = f"{pos.adx:.1f}" if pos.adx is not None else "-"
            support_str = f"{pos.support:.1f}" if pos.support else "-"
            resist_str = f"{pos.resistance:.1f}" if pos.resistance else "-"

            values = [
                pos.symbol[:8],
                trend_str,
                ma_str,
                rsi_str,
                rsi_zone_str,
                adx_str,
                support_str,
                resist_str,
            ]
            lines.append(table_row(values, columns4))

        lines.append("└" + "─" * 89 + "┘")
        lines.append("")

        # ========== Table 5: Technical Signal ==========
        lines.append("┌─── 技术信号 (Technical Signal) " + "─" * 57 + "┐")

        columns5 = [
            ("标的", 8),
            ("市场状态", 12),
            ("趋势强度", 10),
            ("卖Put", 8),
            ("卖Call", 8),
            ("危险期", 6),
        ]

        lines.append(table_header(columns5))
        lines.append(table_separator(columns5))

        for pos in positions:
            regime_str = (pos.market_regime or "-")[:12]
            strength_str = (pos.tech_trend_strength or "-")[:10]
            put_str = (pos.sell_put_signal or "-")[:8]
            call_str = (pos.sell_call_signal or "-")[:8]
            danger_str = "Yes" if pos.is_dangerous_period else "No"

            values = [
                pos.symbol[:8],
                regime_str,
                strength_str,
                put_str,
                call_str,
                danger_str,
            ]
            lines.append(table_row(values, columns5))

        lines.append("└" + "─" * 89 + "┘")

        return lines
