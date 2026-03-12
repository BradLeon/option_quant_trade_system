"""
Strategy Formatter - V2 策略执行结果格式化器

将 LiveExecutionResult 格式化为飞书推送卡片。
包含: 策略名/标的/账户信息, 市场快照, 资金概览+风控指标,
      股票/期权持仓表格(红绿标识), 信号管线汇总, 订单详情。
"""

from typing import Any

from src.business.notification.channels.feishu import FeishuCardBuilder


class StrategyFormatter:
    """V2 策略执行结果 → 飞书卡片"""

    def __init__(self, templates: dict[str, str] | None = None) -> None:
        self.templates = templates or {}

    def format_strategy_result(
        self,
        result: Any,
        strategy_name: str,
        symbols: list[str],
        account: str,
        dry_run: bool,
    ) -> dict[str, Any]:
        """格式化策略执行结果为飞书卡片"""
        # 确定卡片样式
        has_orders = len(result.orders) > 0
        has_signals = result.signals_generated > 0
        has_errors = len(result.errors) > 0

        if has_errors:
            color, emoji, status = "red", "❌", "ERROR"
        elif has_orders:
            color, emoji, status = "green", "✅", "EXECUTED"
        elif has_signals:
            color, emoji, status = "blue", "📋", ("DRY-RUN" if dry_run else "NO ORDER")
        else:
            color, emoji, status = "grey", "⏸️", "NO SIGNAL"

        title = f"{emoji} Strategy {strategy_name} [{status}]"
        elements: list[dict[str, Any]] = []

        # ── 摘要 ──
        elements.append(FeishuCardBuilder.create_fields([
            ("策略", strategy_name),
            ("标的", ", ".join(symbols)),
            ("账户", account.upper()),
            ("模式", "EXECUTE" if not dry_run else "DRY-RUN"),
        ]))
        elements.append(FeishuCardBuilder.create_divider())

        # ── 市场快照 ──
        if result.market_snapshot:
            ms = result.market_snapshot
            price_parts = [f"{sym}: **${p:,.2f}**" for sym, p in ms.prices.items()]
            vix_str = f"{ms.vix:.1f}" if ms.vix else "N/A"
            rfr_str = f"{ms.risk_free_rate:.2%}" if ms.risk_free_rate else "N/A"
            elements.append(FeishuCardBuilder.create_text_element(
                f"📊 **市场**: {' | '.join(price_parts)}\n"
                f"VIX: {vix_str} | 无风险利率: {rfr_str}"
            ))

        # ── 资金概览 + 风控指标 ──
        if result.portfolio_state:
            ps = result.portfolio_state
            elements.extend(self._format_capital_summary(ps))

            # ── 持仓表格 ──
            stocks = [p for p in ps.positions if p.is_stock]
            options = [p for p in ps.positions if p.is_option]

            if stocks:
                elements.append(self._format_stock_table(stocks))
            if options:
                elements.append(self._format_option_table(options))
            if not stocks and not options:
                elements.append(FeishuCardBuilder.create_text_element("暂无持仓"))

            elements.append(FeishuCardBuilder.create_divider())

        # ── 信号管线 ──
        elements.append(FeishuCardBuilder.create_text_element(
            f"🔄 **管线**: 信号 **{result.signals_generated}** → "
            f"风控后 **{result.signals_after_risk}** → "
            f"决策 **{result.decisions_count}** → "
            f"订单 **{len(result.orders)}**"
        ))

        # ── 订单详情 ──
        if result.orders:
            elements.append(FeishuCardBuilder.create_divider())
            from src.business.trading.models.order import OrderStatus

            for i, record in enumerate(result.orders[:10], 1):
                order = record.order
                is_success = order.status in (
                    OrderStatus.SUBMITTED, OrderStatus.FILLED,
                    OrderStatus.ACKNOWLEDGED, OrderStatus.APPROVED,
                )
                icon = "✅" if is_success else "❌"
                side = order.side.value.upper() if order.side else "N/A"
                price_str = f"${order.limit_price:.2f}" if order.limit_price else "MKT"
                symbol_str = order.underlying or order.symbol or "?"

                line = f"{icon} #{i} {side} {order.quantity} {symbol_str} @ {price_str}"
                if record.broker_order_id:
                    line += f" | IBKR#{record.broker_order_id}"
                line += f" | {record.broker_status or order.status.value}"

                elements.append(FeishuCardBuilder.create_text_element(line))

                if record.error_message:
                    elements.append(FeishuCardBuilder.create_text_element(
                        f"  ⚠️ {record.error_message}"
                    ))

        # ── 错误信息 ──
        if result.errors:
            elements.append(FeishuCardBuilder.create_divider())
            for err in result.errors[:5]:
                elements.append(FeishuCardBuilder.create_text_element(f"⚠️ {err}"))

        # ── Dry-run 提示 ──
        if dry_run and has_signals:
            elements.append(FeishuCardBuilder.create_divider())
            elements.append(FeishuCardBuilder.create_text_element(
                "⚠️ **DRY-RUN 模式**，信号不会执行。使用 `--execute` 实际下单。"
            ))

        # ── 时间戳 ──
        elements.append(FeishuCardBuilder.create_note(
            f"执行时间: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        ))

        return {
            "header": FeishuCardBuilder.create_header(title, color),
            "elements": elements,
        }

    # ── Private helpers ──

    def _format_capital_summary(self, ps: Any) -> list[dict[str, Any]]:
        """资金概览 + 风控指标 (仿 dashboard _format_capital_section)"""
        elements: list[dict[str, Any]] = []

        # 总盈亏
        total_pnl = sum(p.unrealized_pnl for p in ps.positions if p.unrealized_pnl)
        pnl_str = f"${total_pnl:+,.0f}" if total_pnl else "$0"

        elements.append(FeishuCardBuilder.create_text_element(
            f"**💰 资金概览**\n"
            f"总权益: **${ps.nlv:,.0f}** | "
            f"现金: ${ps.cash:,.0f} | "
            f"未实现盈亏: {pnl_str}"
        ))

        # 风控指标
        margin_util = ps.margin_used / ps.nlv if ps.nlv > 0 else 0
        cash_ratio = ps.cash / ps.nlv if ps.nlv > 0 else 0

        margin_icon = _pillar_status(margin_util, 0.4, 0.7, higher_is_better=False)
        cash_icon = _pillar_status(cash_ratio, 0.3, 0.1, higher_is_better=True)

        elements.append(FeishuCardBuilder.create_text_element(
            f"**🛡️ 风控指标**\n"
            f"{margin_icon} 保证金使用率: {margin_util:.1%} (目标<40%)\n"
            f"{cash_icon} 现金比率: {cash_ratio:.1%} (目标>30%)\n"
            f"持仓: {len(ps.positions)} 个"
        ))

        return elements

    def _format_stock_table(self, positions: list[Any]) -> dict[str, Any]:
        """股票持仓 Markdown 表格 (仿 dashboard _format_stock_market_table)"""
        content = "**📈 股票持仓**\n\n"
        content += "| 标的 | 数量 | 现价 | 成本 | 市值 | 盈亏% | 盈亏$ | 状态 |\n"
        content += "|:----:|-----:|-----:|-----:|------:|------:|------:|:----:|\n"

        for p in positions:
            symbol = p.instrument.symbol[:10]
            qty = f"{p.quantity}"
            price = f"{p.current_price:.2f}"
            cost = f"{p.entry_price:.2f}"
            mkt_val = f"${p.market_value:,.0f}"

            # PnL %
            entry_cost = p.entry_price * abs(p.quantity) * p.lot_size
            pnl_pct = p.unrealized_pnl / entry_cost if entry_cost > 0 else 0
            pnl_pct_str = f"{pnl_pct:+.1%}"
            pnl_val = f"${p.unrealized_pnl:+,.0f}" if p.unrealized_pnl else "$0"

            # 状态
            if pnl_pct > 0.05:
                status = "🟢"
            elif pnl_pct < -0.05:
                status = "🔴"
            else:
                status = ""

            content += f"| {symbol} | {qty} | {price} | {cost} | {mkt_val} | {pnl_pct_str} | {pnl_val} | {status} |\n"

        return FeishuCardBuilder.create_text_element(content)

    def _format_option_table(self, positions: list[Any]) -> dict[str, Any]:
        """期权持仓 Markdown 表格"""
        content = "**📊 期权持仓**\n\n"
        content += "| 标的 | 类型 | 行权价 | Expiry | DTE | Qty | 成本 | 现价 | PnL$ | 状态 |\n"
        content += "|:----:|:----:|------:|:------:|----:|----:|-----:|-----:|-----:|:----:|\n"

        for p in positions:
            underlying = p.instrument.underlying
            opt_type = p.instrument.right.value.capitalize() if p.instrument.right else "-"
            strike = f"{p.instrument.strike:.0f}" if p.instrument.strike else "-"
            expiry = p.instrument.expiry.strftime("%y%m%d") if p.instrument.expiry else "-"
            dte = str(p.dte) if p.dte is not None else "-"
            qty = f"{p.quantity}"
            cost = f"{abs(p.entry_price):.2f}"
            price = f"{abs(p.current_price):.2f}"
            pnl_val = f"${p.unrealized_pnl:+,.0f}" if p.unrealized_pnl else "$0"

            # PnL %
            entry_cost = abs(p.entry_price) * abs(p.quantity) * p.lot_size
            pnl_pct = p.unrealized_pnl / entry_cost if entry_cost > 0 else 0

            # 状态
            status = "🟢"
            if p.dte is not None and p.dte <= 7:
                status = "🔴"
            elif pnl_pct < -0.5:
                status = "🔴"

            content += f"| {underlying} | {opt_type} | {strike} | {expiry} | {dte} | {qty} | {cost} | {price} | {pnl_val} | {status} |\n"

        return FeishuCardBuilder.create_text_element(content)


def _pillar_status(
    val: float,
    green_threshold: float,
    yellow_threshold: float,
    higher_is_better: bool = False,
) -> str:
    """风控指标颜色 (复用 dashboard 逻辑)"""
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
