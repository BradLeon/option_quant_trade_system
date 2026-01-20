"""
Dashboard Formatter - 仪表盘结果格式化器

将 MonitorResult 格式化为每日报告推送消息。
复用 CLI Dashboard 的表格格式，确保飞书推送与终端输出一致。
"""

from datetime import datetime
from typing import Any

from src.business.monitoring.models import (
    AlertLevel,
    MonitorResult,
    MonitorStatus,
    PositionData,
)
from src.business.notification.channels.feishu import FeishuCardBuilder
from src.engine.models.capital import CapitalMetrics
from src.engine.models.portfolio import PortfolioMetrics


class DashboardFormatter:
    """仪表盘结果格式化器

    将 MonitorResult 转换为飞书每日报告卡片消息。
    """

    def __init__(
        self,
        templates: dict[str, str] | None = None,
    ) -> None:
        """初始化格式化器

        Args:
            templates: 消息模板配置
        """
        self.templates = templates or {}

    def format(self, result: MonitorResult) -> dict[str, Any]:
        """格式化监控结果为每日报告卡片

        Args:
            result: 监控结果

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "dashboard_report_title",
            "📋 每日持仓报告",
        )

        # 根据状态选择颜色
        color_map = {
            MonitorStatus.GREEN: "green",
            MonitorStatus.YELLOW: "orange",
            MonitorStatus.RED: "red",
        }
        color = color_map.get(result.status, "blue")

        elements: list[dict[str, Any]] = []

        # 1. 状态概览
        elements.append(self._format_status_summary(result))
        elements.append(FeishuCardBuilder.create_divider())

        # 2. Capital 概览
        if result.capital_metrics:
            elements.append(self._format_capital_section(result.capital_metrics))
            elements.append(FeishuCardBuilder.create_divider())

        # 3. Portfolio 健康度
        if result.portfolio_metrics:
            elements.append(self._format_portfolio_section(result.portfolio_metrics))
            elements.append(FeishuCardBuilder.create_divider())

        # 4. 期权持仓表格组
        option_positions = [p for p in result.positions if p.is_option]
        if option_positions:
            # 4.1 期权持仓明细
            elements.append(self._format_option_position_table(option_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 4.2 Greeks 明细
            elements.append(self._format_greeks_table(option_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 4.3 核心指标
            elements.append(self._format_core_metrics_table(option_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 4.4 风险调整指标
            elements.append(self._format_risk_adjusted_table(option_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 4.5 资金与保证金
            elements.append(self._format_capital_margin_table(option_positions))
            elements.append(FeishuCardBuilder.create_divider())

        # 5. 股票持仓表格组
        stock_positions = [p for p in result.positions if p.is_stock]
        if stock_positions:
            # 5.1 股票行情
            elements.append(self._format_stock_market_table(stock_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 5.2 基本面评分
            elements.append(self._format_fundamental_table(stock_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 5.3 波动率评分
            elements.append(self._format_volatility_table(stock_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 5.4 技术面评分
            elements.append(self._format_technical_score_table(stock_positions))
            elements.append(FeishuCardBuilder.create_divider())

            # 5.5 技术信号
            elements.append(self._format_technical_signal_table(stock_positions))
            elements.append(FeishuCardBuilder.create_divider())

        # 6. 预警统计
        if result.alerts:
            elements.append(self._format_alerts_section(result))
            elements.append(FeishuCardBuilder.create_divider())

        # 7. 待办事项
        if result.suggestions:
            elements.append(self._format_todos_section(result))
            elements.append(FeishuCardBuilder.create_divider())

        # 时间戳
        elements.append(
            FeishuCardBuilder.create_note(
                f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        )

        return {
            "header": FeishuCardBuilder.create_header(title, color),
            "elements": elements,
        }

    def _format_status_summary(self, result: MonitorResult) -> dict[str, Any]:
        """格式化状态概览"""
        status_emoji = {
            MonitorStatus.GREEN: "🟢",
            MonitorStatus.YELLOW: "🟡",
            MonitorStatus.RED: "🔴",
        }
        status_text = {
            MonitorStatus.GREEN: "正常",
            MonitorStatus.YELLOW: "关注",
            MonitorStatus.RED: "风险",
        }

        emoji = status_emoji.get(result.status, "⚪")
        text = status_text.get(result.status, "未知")

        content = (
            f"**整体状态**: {emoji} {text}\n"
            f"**持仓数量**: {result.total_positions} 个\n"
            f"**风险持仓**: {result.positions_at_risk} 个\n"
            f"**机会持仓**: {result.positions_opportunity} 个"
        )

        return FeishuCardBuilder.create_text_element(content)

    def _format_capital_section(self, capital: CapitalMetrics) -> dict[str, Any]:
        """格式化资金概览"""

        def fmt_pct(val: float | None, decimals: int = 1) -> str:
            return f"{val * 100:.{decimals}f}%" if val is not None else "N/A"

        def fmt_money(val: float | None) -> str:
            if val is None:
                return "N/A"
            return f"${val:,.0f}"

        def fmt_ratio(val: float | None) -> str:
            return f"{val:.2f}x" if val is not None else "N/A"

        def pillar_status(
            val: float | None,
            green_threshold: float,
            yellow_threshold: float,
            higher_is_better: bool = False,
        ) -> str:
            if val is None:
                return "⚪"
            if higher_is_better:
                if val >= green_threshold:
                    return "🟢"
                elif val >= yellow_threshold:
                    return "🟡"
                else:
                    return "🔴"
            else:
                if val <= green_threshold:
                    return "🟢"
                elif val <= yellow_threshold:
                    return "🟡"
                else:
                    return "🔴"

        margin_status = pillar_status(capital.margin_utilization, 0.4, 0.7)
        cash_status = pillar_status(capital.cash_ratio, 0.3, 0.1, higher_is_better=True)
        leverage_status = pillar_status(capital.gross_leverage, 2.0, 4.0)
        stress_status = pillar_status(capital.stress_test_loss, 0.1, 0.2)

        content = (
            f"**💰 资金概览**\n"
            f"总权益: {fmt_money(capital.total_equity)} | "
            f"现金: {fmt_money(capital.cash_balance)} | "
            f"未实现盈亏: {fmt_money(capital.unrealized_pnl)}\n\n"
            f"**🛡️ 风控四大支柱**\n"
            f"{margin_status} 保证金使用率: {fmt_pct(capital.margin_utilization)}\n"
            f"{cash_status} 现金比率: {fmt_pct(capital.cash_ratio)}\n"
            f"{leverage_status} 总杠杆: {fmt_ratio(capital.gross_leverage)}\n"
            f"{stress_status} 压力测试亏损: {fmt_pct(capital.stress_test_loss)}"
        )

        return FeishuCardBuilder.create_text_element(content)

    def _format_portfolio_section(self, portfolio: PortfolioMetrics) -> dict[str, Any]:
        """格式化组合健康度"""

        def fmt_val(val: float | None, decimals: int = 2) -> str:
            return f"{val:.{decimals}f}" if val is not None else "N/A"

        def fmt_pct(val: float | None, decimals: int = 2) -> str:
            return f"{val * 100:.{decimals}f}%" if val is not None else "N/A"

        def tgr_status(val: float | None) -> str:
            if val is None:
                return "⚪"
            if val >= 0.5:
                return "🟢"
            elif val >= 0.3:
                return "🟡"
            else:
                return "🔴"

        def hhi_status(val: float | None) -> str:
            if val is None:
                return "⚪"
            if val <= 0.2:
                return "🟢"
            elif val <= 0.35:
                return "🟡"
            else:
                return "🔴"

        content = (
            f"**📊 组合健康度**\n"
            f"Beta加权Delta: {fmt_val(portfolio.beta_weighted_delta)} "
            f"({fmt_pct(portfolio.beta_weighted_delta_pct)})\n"
            f"总Theta: ${fmt_val(portfolio.total_theta)}/日 "
            f"({fmt_pct(portfolio.theta_pct)})\n"
            f"总Gamma: ${fmt_val(portfolio.total_gamma)} "
            f"({fmt_pct(portfolio.gamma_pct)})\n"
            f"总Vega: ${fmt_val(portfolio.total_vega)} "
            f"({fmt_pct(portfolio.vega_pct)})\n\n"
            f"**📈 风险指标**\n"
            f"{tgr_status(portfolio.portfolio_tgr)} TGR: {fmt_val(portfolio.portfolio_tgr)}\n"
            f"{hhi_status(portfolio.concentration_hhi)} 集中度(HHI): {fmt_val(portfolio.concentration_hhi)}\n"
            f"Vega加权IV/HV: {fmt_val(portfolio.vega_weighted_iv_hv)}"
        )

        return FeishuCardBuilder.create_text_element(content)

    # ========== 期权表格 ==========

    def _format_option_position_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化期权持仓明细表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无期权持仓")

        content = "**📊 期权持仓明细**\n\n"
        content += "| 标的 | 类型 | 策略 | 行权价 | Expiry | DTE | 正股 | OTM% | Qty | 成本 | 现价 | PnL% | 状态 |\n"
        content += "|:----:|:----:|:----:|------:|:------:|----:|-----:|-----:|----:|-----:|-----:|-----:|:----:|\n"

        for pos in positions:
            underlying = pos.underlying or pos.symbol[:6]
            opt_type = "Put" if pos.option_type == "put" else "Call"
            strategy = pos.strategy_type or "-"
            strike = f"{pos.strike:.1f}" if pos.strike else "-"
            expiry = pos.expiry if pos.expiry else "-"
            dte = str(pos.dte) if pos.dte is not None else "-"
            underlying_price = f"{pos.underlying_price:.2f}" if pos.underlying_price else "-"
            otm_pct = f"{pos.otm_pct * 100:.0f}%" if pos.otm_pct is not None else "-"
            qty = str(int(pos.quantity)) if pos.quantity else "-"
            cost = f"{abs(pos.entry_price):.2f}" if pos.entry_price else "-"
            price = f"{abs(pos.current_price):.2f}" if pos.current_price else "-"
            pnl_pct = f"{pos.unrealized_pnl_pct * 100:+.1f}%" if pos.unrealized_pnl_pct is not None else "-"

            # 状态指示
            status = "🟢"
            if pos.dte is not None and pos.dte <= 7:
                status = "🔴"
            elif pos.otm_pct is not None and pos.otm_pct < 0.05:
                status = "🟡"
            elif pos.unrealized_pnl_pct is not None and pos.unrealized_pnl_pct < -0.5:
                status = "🔴"

            content += f"| {underlying} | {opt_type} | {strategy} | {strike} | {expiry} | {dte} | {underlying_price} | {otm_pct} | {qty} | {cost} | {price} | {pnl_pct} | {status} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_greeks_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化 Greeks 表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无期权持仓")

        content = "**📈 Greeks 明细**\n\n"
        content += "| 标的 | 类型 | 策略 | 行权价 | Expiry | Delta | Gamma | Theta | Vega | HV | IV | IV/HV |\n"
        content += "|:----:|:----:|:----:|------:|:------:|------:|------:|------:|-----:|---:|---:|------:|\n"

        for pos in positions:
            underlying = pos.underlying or pos.symbol[:6]
            opt_type = "Put" if pos.option_type == "put" else "Call"
            strategy = pos.strategy_type or "-"
            strike = f"{pos.strike:.1f}" if pos.strike else "-"
            expiry = pos.expiry if pos.expiry else "-"
            delta = f"{pos.delta:.2f}" if pos.delta is not None else "-"
            gamma = f"{pos.gamma:.3f}" if pos.gamma is not None else "-"
            theta = f"{pos.theta:.2f}" if pos.theta is not None else "-"
            vega = f"{pos.vega:.2f}" if pos.vega is not None else "-"
            hv = f"{pos.hv * 100:.1f}%" if pos.hv else "-"
            iv = f"{pos.iv * 100:.1f}%" if pos.iv else "-"
            iv_hv = f"{pos.iv / pos.hv:.2f}" if pos.iv and pos.hv and pos.hv > 0 else "-"

            content += f"| {underlying} | {opt_type} | {strategy} | {strike} | {expiry} | {delta} | {gamma} | {theta} | {vega} | {hv} | {iv} | {iv_hv} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_core_metrics_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化核心指标表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无期权持仓")

        content = "**📊 核心指标**\n\n"
        content += "| 标的 | 类型 | 策略 | 行权价 | Expiry | E[Ret] | MaxProf | MaxLoss | BE | WinPr |\n"
        content += "|:----:|:----:|:----:|------:|:------:|-------:|--------:|--------:|---:|------:|\n"

        for pos in positions:
            underlying = pos.underlying or pos.symbol[:6]
            opt_type = "Put" if pos.option_type == "put" else "Call"
            strategy = pos.strategy_type or "-"
            strike = f"{pos.strike:.1f}" if pos.strike else "-"
            expiry = pos.expiry if pos.expiry else "-"
            expected_ret = f"{pos.expected_return:.2f}" if pos.expected_return is not None else "-"
            max_prof = f"{pos.max_profit:.2f}" if pos.max_profit is not None else "-"
            max_loss = f"{pos.max_loss:.2f}" if pos.max_loss is not None else "-"
            if pos.breakeven is not None:
                if isinstance(pos.breakeven, list):
                    be_str = ",".join([f"{b:.1f}" for b in pos.breakeven])
                else:
                    be_str = f"{pos.breakeven:.2f}"
            else:
                be_str = "-"
            win_prob = f"{pos.win_probability:.0%}" if pos.win_probability is not None else "-"

            content += f"| {underlying} | {opt_type} | {strategy} | {strike} | {expiry} | {expected_ret} | {max_prof} | {max_loss} | {be_str} | {win_prob} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_risk_adjusted_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化风险调整指标表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无期权持仓")

        content = "**📉 风险调整指标**\n\n"
        content += "| 标的 | 类型 | 策略 | 行权价 | Expiry | PREI | SAS | TGR | ROC | E[ROC] | Sharpe | Kelly |\n"
        content += "|:----:|:----:|:----:|------:|:------:|-----:|----:|----:|----:|-------:|-------:|------:|\n"

        for pos in positions:
            underlying = pos.underlying or pos.symbol[:6]
            opt_type = "Put" if pos.option_type == "put" else "Call"
            strategy = pos.strategy_type or "-"
            strike = f"{pos.strike:.1f}" if pos.strike else "-"
            expiry = pos.expiry if pos.expiry else "-"
            prei = f"{pos.prei:.1f}" if pos.prei is not None else "-"
            sas = f"{pos.sas:.1f}" if pos.sas is not None else "-"
            tgr = f"{pos.tgr:.3f}" if pos.tgr is not None else "-"
            roc = f"{pos.roc:.1%}" if pos.roc is not None else "-"
            eroc = f"{pos.expected_roc:.1%}" if pos.expected_roc is not None else "-"
            sharpe = f"{pos.sharpe:.3f}" if pos.sharpe is not None else "-"
            kelly = f"{pos.kelly:.1%}" if pos.kelly is not None else "-"

            content += f"| {underlying} | {opt_type} | {strategy} | {strike} | {expiry} | {prei} | {sas} | {tgr} | {roc} | {eroc} | {sharpe} | {kelly} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_capital_margin_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化资金与保证金表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无期权持仓")

        content = "**💰 资金与保证金**\n\n"
        content += "| 标的 | 类型 | 策略 | 行权价 | Expiry | Margin | Cap@Risk | RetStd | Mar/Cap |\n"
        content += "|:----:|:----:|:----:|------:|:------:|-------:|---------:|-------:|--------:|\n"

        for pos in positions:
            underlying = pos.underlying or pos.symbol[:6]
            opt_type = "Put" if pos.option_type == "put" else "Call"
            strategy = pos.strategy_type or "-"
            strike = f"{pos.strike:.1f}" if pos.strike else "-"
            expiry = pos.expiry if pos.expiry else "-"
            margin = f"${pos.margin:.2f}" if pos.margin is not None else "-"
            car = f"${pos.capital_at_risk:.2f}" if pos.capital_at_risk is not None else "-"
            ret_std = f"${pos.return_std:.2f}" if pos.return_std is not None else "-"
            if pos.margin is not None and pos.capital_at_risk and pos.capital_at_risk > 0:
                margin_ratio = f"{pos.margin / pos.capital_at_risk:.1%}"
            else:
                margin_ratio = "-"

            content += f"| {underlying} | {opt_type} | {strategy} | {strike} | {expiry} | {margin} | {car} | {ret_std} | {margin_ratio} |\n"

        return FeishuCardBuilder.create_text_element(content)

    # ========== 股票表格 ==========

    def _format_stock_market_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化股票行情表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无股票持仓")

        content = "**📈 股票行情 (Market Data)**\n\n"
        content += "| 标的 | 数量 | 现价 | 成本 | 市值 | 盈亏% | 盈亏$ | 状态 |\n"
        content += "|:----:|-----:|-----:|-----:|-----:|------:|------:|:----:|\n"

        for pos in positions:
            symbol = pos.symbol[:8]
            qty = f"{pos.quantity:.0f}" if pos.quantity else "-"
            price = f"{pos.current_price:.2f}" if pos.current_price else "-"
            cost = f"{pos.entry_price:.2f}" if pos.entry_price else "-"
            market_val = f"${pos.market_value:,.0f}" if pos.market_value else "-"
            pnl_pct = f"{pos.unrealized_pnl_pct:+.1%}" if pos.unrealized_pnl_pct else "-"
            pnl_val = f"${pos.unrealized_pnl:,.0f}" if pos.unrealized_pnl else "-"

            # 状态
            if pos.unrealized_pnl_pct is not None:
                if pos.unrealized_pnl_pct > 0.05:
                    status = "🟢"
                elif pos.unrealized_pnl_pct < -0.05:
                    status = "🔴"
                else:
                    status = ""
            else:
                status = ""

            content += f"| {symbol} | {qty} | {price} | {cost} | {market_val} | {pnl_pct} | {pnl_val} | {status} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_fundamental_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化基本面评分表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无股票持仓")

        content = "**📊 基本面评分 (Fundamental)**\n\n"
        content += "| 标的 | Score | Rating | PE | Beta |\n"
        content += "|:----:|------:|:------:|---:|-----:|\n"

        for pos in positions:
            symbol = pos.symbol[:8]
            score = f"{pos.fundamental_score:.1f}" if pos.fundamental_score is not None else "-"
            rating = pos.analyst_rating if pos.analyst_rating else "-"
            pe = f"{pos.pe_ratio:.1f}" if pos.pe_ratio is not None else "-"
            beta = f"{pos.beta:.2f}" if pos.beta is not None else "-"

            content += f"| {symbol} | {score} | {rating} | {pe} | {beta} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_volatility_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化波动率评分表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无股票持仓")

        content = "**📉 波动率评分 (Volatility)**\n\n"
        content += "| 标的 | Score | Rating | IV Rank | IV/HV | IV Pctl |\n"
        content += "|:----:|------:|:------:|--------:|------:|--------:|\n"

        for pos in positions:
            symbol = pos.symbol[:8]
            score = f"{pos.volatility_score:.1f}" if pos.volatility_score is not None else "-"
            rating = pos.volatility_rating if pos.volatility_rating else "-"
            iv_rank = f"{pos.iv_rank:.1f}" if pos.iv_rank is not None else "-"
            iv_hv = f"{pos.iv_hv_ratio:.2f}" if pos.iv_hv_ratio is not None else "-"
            iv_pctl = f"{pos.iv_percentile:.0%}" if pos.iv_percentile is not None else "-"

            content += f"| {symbol} | {score} | {rating} | {iv_rank} | {iv_hv} | {iv_pctl} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_technical_score_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化技术面评分表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无股票持仓")

        content = "**📈 技术面评分 (Technical Score)**\n\n"
        content += "| 标的 | 趋势 | MA对齐 | RSI | RSI区 | ADX | 支撑 | 阻力 |\n"
        content += "|:----:|:----:|:------:|----:|:-----:|----:|-----:|-----:|\n"

        for pos in positions:
            symbol = pos.symbol[:8]
            trend = (pos.trend_signal or "-")[:6]
            ma = (pos.ma_alignment or "-")[:12]
            rsi = f"{pos.rsi:.1f}" if pos.rsi is not None else "-"
            rsi_zone = (pos.rsi_zone or "-")[:10]
            adx = f"{pos.adx:.1f}" if pos.adx is not None else "-"
            support = f"{pos.support:.1f}" if pos.support else "-"
            resist = f"{pos.resistance:.1f}" if pos.resistance else "-"

            content += f"| {symbol} | {trend} | {ma} | {rsi} | {rsi_zone} | {adx} | {support} | {resist} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_technical_signal_table(self, positions: list[PositionData]) -> dict[str, Any]:
        """格式化技术信号表格"""
        if not positions:
            return FeishuCardBuilder.create_text_element("暂无股票持仓")

        content = "**📊 技术信号 (Technical Signal)**\n\n"
        content += "| 标的 | 市场状态 | 趋势强度 | 卖Put | 卖Call | 危险期 |\n"
        content += "|:----:|:--------:|:--------:|:-----:|:------:|:------:|\n"

        for pos in positions:
            symbol = pos.symbol[:8]
            regime = (pos.market_regime or "-")[:12]
            strength = (pos.tech_trend_strength or "-")[:10]
            put_signal = (pos.sell_put_signal or "-")[:8]
            call_signal = (pos.sell_call_signal or "-")[:8]
            danger = "Yes" if pos.is_dangerous_period else "No"

            content += f"| {symbol} | {regime} | {strength} | {put_signal} | {call_signal} | {danger} |\n"

        return FeishuCardBuilder.create_text_element(content)

    # ========== 预警和待办 ==========

    def _format_alerts_section(self, result: MonitorResult) -> dict[str, Any]:
        """格式化预警统计"""
        red_count = len(result.red_alerts)
        yellow_count = len(result.yellow_alerts)
        green_count = len(result.green_alerts)

        content = (
            f"**⚠️ 预警统计**\n"
            f"🔴 风险预警: {red_count} 个\n"
            f"🟡 关注提醒: {yellow_count} 个\n"
            f"🟢 机会提示: {green_count} 个"
        )

        # 显示所有红色预警详情
        if result.red_alerts:
            content += "\n\n**🔴 红色预警详情:**"
            for alert in result.red_alerts:
                symbol_str = f"[{alert.symbol}] " if alert.symbol else ""
                value_str = ""
                if alert.current_value is not None:
                    if alert.threshold_range:
                        value_str = f" (当前: {alert.current_value:.2f}, 正常: {alert.threshold_range})"
                    elif alert.threshold_value is not None:
                        value_str = f" (当前: {alert.current_value:.2f}, 阈值: {alert.threshold_value:.2f})"
                content += f"\n• {symbol_str}{alert.message}{value_str}"

        # 显示黄色预警详情（最多 10 个）
        if result.yellow_alerts:
            content += "\n\n**🟡 关注提醒详情:**"
            for alert in result.yellow_alerts[:10]:
                symbol_str = f"[{alert.symbol}] " if alert.symbol else ""
                content += f"\n• {symbol_str}{alert.message}"
            if len(result.yellow_alerts) > 10:
                content += f"\n... 还有 {len(result.yellow_alerts) - 10} 个"

        return FeishuCardBuilder.create_text_element(content)

    def _format_todos_section(self, result: MonitorResult) -> dict[str, Any]:
        """格式化待办事项"""
        from src.business.monitoring.suggestions import UrgencyLevel

        immediate = [s for s in result.suggestions if s.urgency == UrgencyLevel.IMMEDIATE]
        soon = [s for s in result.suggestions if s.urgency == UrgencyLevel.SOON]
        monitor = [s for s in result.suggestions if s.urgency == UrgencyLevel.MONITOR]

        content = (
            f"**📝 待办事项**\n"
            f"立即处理: {len(immediate)} 个 | "
            f"尽快处理: {len(soon)} 个 | "
            f"持续观察: {len(monitor)} 个"
        )

        # 显示立即处理的建议（最多 5 个）
        if immediate:
            content += "\n\n**立即处理:**"
            for sug in immediate[:5]:
                content += f"\n• [{sug.symbol}] {sug.action.value}: {sug.reason}"
            if len(immediate) > 5:
                content += f"\n... 还有 {len(immediate) - 5} 个"

        # 显示尽快处理的建议（最多 3 个）
        if soon:
            content += "\n\n**尽快处理:**"
            for sug in soon[:3]:
                content += f"\n• [{sug.symbol}] {sug.action.value}: {sug.reason}"
            if len(soon) > 3:
                content += f"\n... 还有 {len(soon) - 3} 个"

        return FeishuCardBuilder.create_text_element(content)
