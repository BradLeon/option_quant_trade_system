"""
Dashboard Formatter - 仪表盘 IM 推送格式化器

将 MonitorResult 格式化为简洁的每日持仓报告卡片。
设计目标：手机飞书一屏可读（6 个 section），适用于股票+期权买方/卖方混合组合。
"""

from datetime import datetime
from typing import Any

from src.business.monitoring.models import (
    MonitorResult,
    MonitorStatus,
    PositionData,
)
from src.business.notification.channels.feishu import FeishuCardBuilder
from src.strategy.cash_sweep import CASH_EQUIVALENT_SYMBOLS


class DashboardFormatter:
    """仪表盘结果格式化器 — 飞书卡片推送。

    6 个 section：账户概览 → 持仓总览 → 组合Greeks → 风险提醒 → 市场环境 → 时间戳。
    """

    def __init__(self, templates: dict[str, str] | None = None) -> None:
        self.templates = templates or {}

    def format(self, result: MonitorResult) -> dict[str, Any]:
        """格式化监控结果为飞书卡片。"""
        title = self.templates.get("dashboard_report_title", "📋 每日持仓报告")

        color_map = {
            MonitorStatus.GREEN: "green",
            MonitorStatus.YELLOW: "orange",
            MonitorStatus.RED: "red",
        }
        color = color_map.get(result.status, "blue")

        elements: list[dict[str, Any]] = []

        # § 1. 账户概览
        if result.capital_metrics:
            elements.append(self._format_account_overview(result))
            elements.append(FeishuCardBuilder.create_divider())

        # § 2. 持仓总览
        elements.append(self._format_holdings_table(result))
        elements.append(FeishuCardBuilder.create_divider())

        # § 3. 组合 Greeks（仅有期权时）
        option_positions = [p for p in result.positions if p.is_option]
        if option_positions and result.portfolio_metrics:
            elements.append(self._format_portfolio_greeks(result))
            elements.append(FeishuCardBuilder.create_divider())

        # § 4. 风险提醒（仅有风险时）
        if result.red_alerts or result.yellow_alerts:
            elements.append(self._format_risk_alerts(result))
            elements.append(FeishuCardBuilder.create_divider())

        # § 5. 市场环境
        if result.market_sentiment:
            elements.append(self._format_market_context(result))
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

    # ----------------------------------------------------------------
    # § 1. 账户概览
    # ----------------------------------------------------------------

    def _format_account_overview(self, result: MonitorResult) -> dict[str, Any]:
        capital = result.capital_metrics
        if capital is None:
            return FeishuCardBuilder.create_text_element("暂无账户数据")

        nlv = capital.total_equity or 0
        cash = capital.cash_balance or 0
        margin_pct = (capital.margin_utilization or 0) * 100
        unrealized = capital.unrealized_pnl or 0

        # Cash ETF 汇总
        cash_etf_positions = [
            p for p in result.positions
            if p.is_stock and (p.symbol in CASH_EQUIVALENT_SYMBOLS
                              or (p.underlying or "") in CASH_EQUIVALENT_SYMBOLS)
        ]
        cash_etf_value = sum(
            (p.market_value or (p.current_price or 0) * (p.quantity or 0))
            for p in cash_etf_positions
        )
        cash_etf_symbols = ", ".join(sorted({
            p.underlying or p.symbol for p in cash_etf_positions
        })) or "无"

        # 非现金ETF持仓数
        active_count = len([
            p for p in result.positions
            if not (p.is_stock and (p.symbol in CASH_EQUIVALENT_SYMBOLS
                                    or (p.underlying or "") in CASH_EQUIVALENT_SYMBOLS))
        ])

        content = f"**💰 账户概览**\n"
        content += f"总权益: {_fmt_money(nlv)}"
        if unrealized != 0:
            content += f" | 未实现: {_fmt_money(unrealized, sign=True)}"
        content += f"\n现金: {_fmt_money(cash)} ({cash / nlv * 100:.1f}%)" if nlv > 0 else f"\n现金: {_fmt_money(cash)}"
        if margin_pct > 0:
            content += f" | 保证金: {margin_pct:.1f}%"
        if cash_etf_value > 0 and nlv > 0:
            content += f"\nCash ETF: {_fmt_money(cash_etf_value)} {cash_etf_symbols} ({cash_etf_value / nlv * 100:.1f}%)"
        content += f"\n持仓: {active_count} 个"

        return FeishuCardBuilder.create_text_element(content)

    # ----------------------------------------------------------------
    # § 2. 持仓总览
    # ----------------------------------------------------------------

    def _format_holdings_table(self, result: MonitorResult) -> dict[str, Any]:
        # 分离期权、股票、现金ETF
        options: list[PositionData] = []
        stocks: list[PositionData] = []

        for p in result.positions:
            if p.is_option:
                options.append(p)
            elif p.is_stock:
                sym = p.underlying or p.symbol
                if sym in CASH_EQUIVALENT_SYMBOLS:
                    continue  # 已在账户概览汇总
                stocks.append(p)

        if not options and not stocks:
            return FeishuCardBuilder.create_text_element("**📊 持仓总览**\n暂无持仓")

        content = "**📊 持仓总览**\n"

        # 期权子表
        if options:
            content += "\n期权:\n"
            content += "| 标的 | 方向 | 行权价 | 到期 | DTE | 数量 | 成本 | 现价 | 盈亏 | Delta |\n"
            content += "|------|------|-------:|-----:|----:|-----:|-----:|-----:|-----:|------:|\n"
            for p in options:
                underlying = (p.underlying or p.symbol)[:8]
                direction = "Put" if p.option_type == "put" else "Call"
                strike = f"{p.strike:.0f}" if p.strike else "-"
                expiry = p.expiry[-4:] if p.expiry and len(p.expiry) >= 4 else (p.expiry or "-")
                dte = str(p.dte) if p.dte is not None else "-"
                qty = str(int(p.quantity)) if p.quantity else "-"
                cost = f"{abs(p.entry_price):.2f}" if p.entry_price else "-"
                price = f"{abs(p.current_price):.2f}" if p.current_price else "-"
                pnl = _fmt_pnl(p)
                delta = f"{p.delta:.2f}" if p.delta is not None else "-"
                content += f"| {underlying} | {direction} | {strike} | {expiry} | {dte} | {qty} | {cost} | {price} | {pnl} | {delta} |\n"

        # 股票子表
        if stocks:
            content += "\n股票:\n"
            content += "| 标的 | 数量 | 成本 | 现价 | 市值 | 盈亏 | 盈亏% |\n"
            content += "|------|-----:|-----:|-----:|-----:|-----:|------:|\n"
            for p in stocks:
                symbol = (p.symbol or "")[:8]
                qty = str(int(p.quantity)) if p.quantity else "-"
                cost = f"{p.entry_price:.2f}" if p.entry_price else "-"
                price = f"{p.current_price:.2f}" if p.current_price else "-"
                mkt_val = _fmt_money(p.market_value or (p.current_price or 0) * (p.quantity or 0))
                pnl_val = _fmt_money(p.unrealized_pnl, sign=True) if p.unrealized_pnl else "-"
                pnl_pct = f"{p.unrealized_pnl_pct:+.1%}" if p.unrealized_pnl_pct is not None else "-"
                content += f"| {symbol} | {qty} | {cost} | {price} | {mkt_val} | {pnl_val} | {pnl_pct} |\n"

        return FeishuCardBuilder.create_text_element(content)

    # ----------------------------------------------------------------
    # § 3. 组合 Greeks
    # ----------------------------------------------------------------

    def _format_portfolio_greeks(self, result: MonitorResult) -> dict[str, Any]:
        pm = result.portfolio_metrics
        if pm is None:
            return FeishuCardBuilder.create_text_element("")

        delta_pct = f" ({pm.beta_weighted_delta_pct * 100:.1f}%)" if pm.beta_weighted_delta_pct else ""
        content = (
            f"**📐 组合 Greeks**\n"
            f"Delta: ${pm.beta_weighted_delta or 0:,.0f}{delta_pct} | "
            f"Theta: ${pm.total_theta or 0:,.1f}/日\n"
            f"Gamma: ${pm.total_gamma or 0:,.2f} | "
            f"Vega: ${pm.total_vega or 0:,.1f}"
        )
        if pm.vega_weighted_iv_hv is not None:
            content += f" | 加权IV/HV: {pm.vega_weighted_iv_hv:.2f}"

        return FeishuCardBuilder.create_text_element(content)

    # ----------------------------------------------------------------
    # § 4. 风险提醒
    # ----------------------------------------------------------------

    def _format_risk_alerts(self, result: MonitorResult) -> dict[str, Any]:
        content = "**⚠️ 风险提醒**\n"

        # 所有红色预警
        for alert in result.red_alerts:
            symbol_str = f"[{alert.symbol}] " if alert.symbol else ""
            content += f"🔴 {symbol_str}{alert.message}\n"

        # 黄色预警（最多 5 个）
        for alert in result.yellow_alerts[:5]:
            symbol_str = f"[{alert.symbol}] " if alert.symbol else ""
            content += f"🟡 {symbol_str}{alert.message}\n"
        if len(result.yellow_alerts) > 5:
            content += f"... 还有 {len(result.yellow_alerts) - 5} 个关注项\n"

        return FeishuCardBuilder.create_text_element(content.rstrip())

    # ----------------------------------------------------------------
    # § 5. 市场环境
    # ----------------------------------------------------------------

    def _format_market_context(self, result: MonitorResult) -> dict[str, Any]:
        ctx = result.market_sentiment or {}

        vix = ctx.get("vix")
        spy_price = ctx.get("spy_price")
        risk_free = ctx.get("risk_free_rate")

        parts: list[str] = []
        if vix is not None:
            vix_emoji = "🟢" if vix < 20 else ("🟡" if vix < 30 else "🔴")
            parts.append(f"{vix_emoji} VIX: {vix:.1f}")
        if spy_price is not None:
            parts.append(f"SPY: ${spy_price:,.2f}")
        if risk_free is not None:
            parts.append(f"10Y: {risk_free * 100:.2f}%")

        content = "**🌍 市场环境**\n" + " | ".join(parts) if parts else ""
        return FeishuCardBuilder.create_text_element(content)


# ====================================================================
# 格式化工具函数
# ====================================================================

def _fmt_money(val: float | None, sign: bool = False) -> str:
    if val is None:
        return "-"
    fmt = f"${abs(val):,.0f}"
    if sign:
        return f"+{fmt}" if val > 0 else f"-{fmt}" if val < 0 else fmt
    return fmt


def _fmt_pnl(pos: PositionData) -> str:
    """期权盈亏：优先用 unrealized_pnl，如果为 0 则尝试计算"""
    if pos.unrealized_pnl and pos.unrealized_pnl != 0:
        return _fmt_money(pos.unrealized_pnl, sign=True)
    # Fallback: (current - entry) * qty * multiplier
    if pos.entry_price and pos.current_price and pos.quantity:
        mult = pos.contract_multiplier or 100
        pnl = (pos.current_price - pos.entry_price) * pos.quantity * mult
        return _fmt_money(pnl, sign=True)
    return "-"
