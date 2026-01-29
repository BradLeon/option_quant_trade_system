"""
Trading Formatter - 交易结果格式化器

将交易决策和执行结果格式化为飞书推送消息。
"""

from datetime import datetime
from typing import Any, Optional

from src.business.notification.channels.feishu import FeishuCardBuilder
from src.business.trading.models.decision import TradingDecision, DecisionType, DecisionPriority
from src.business.trading.models.order import OrderRecord, OrderStatus


class TradingFormatter:
    """交易结果格式化器

    将 TradingDecision 和 OrderRecord 转换为飞书卡片消息。
    """

    def __init__(
        self,
        templates: dict[str, str] | None = None,
        max_decisions: int = 10,
    ) -> None:
        """初始化格式化器

        Args:
            templates: 消息模板配置
            max_decisions: 最多推送的决策数量
        """
        self.templates = templates or {}
        self.max_decisions = max_decisions

    def format_decisions(
        self,
        decisions: list[TradingDecision],
        dry_run: bool = True,
        command: str = "trade",
        market: str = "",
        strategy: str = "",
    ) -> dict[str, Any]:
        """格式化决策列表为飞书卡片

        Args:
            decisions: 决策列表
            dry_run: 是否为 dry-run 模式
            command: 命令类型 (screen/monitor)
            market: 市场 (us/hk)
            strategy: 策略

        Returns:
            飞书卡片数据
        """
        mode = "DRY-RUN" if dry_run else "PENDING"
        emoji = "📋" if dry_run else "🔔"
        color = "orange" if dry_run else "blue"

        title = f"{emoji} Trade {command.capitalize()} [{mode}]"

        elements = []

        # 摘要信息
        summary_parts = []
        if market:
            summary_parts.append(f"市场: {market.upper()}")
        if strategy:
            summary_parts.append(f"策略: {strategy.upper()}")
        summary_parts.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        if summary_parts:
            elements.append(FeishuCardBuilder.create_text_element(" | ".join(summary_parts)))
            elements.append(FeishuCardBuilder.create_divider())

        # 决策统计
        open_count = sum(1 for d in decisions if d.decision_type == DecisionType.OPEN)
        close_count = sum(1 for d in decisions if d.decision_type == DecisionType.CLOSE)
        roll_count = sum(1 for d in decisions if d.decision_type == DecisionType.ROLL)
        other_count = len(decisions) - open_count - close_count - roll_count

        stats_parts = [f"📋 生成 **{len(decisions)}** 个决策"]
        if open_count:
            stats_parts.append(f"开仓: {open_count}")
        if close_count:
            stats_parts.append(f"平仓: {close_count}")
        if roll_count:
            stats_parts.append(f"展期: {roll_count}")
        if other_count:
            stats_parts.append(f"其他: {other_count}")

        elements.append(FeishuCardBuilder.create_text_element(" | ".join(stats_parts)))
        elements.append(FeishuCardBuilder.create_divider())

        # 决策详情
        display_decisions = decisions[:self.max_decisions]
        for i, decision in enumerate(display_decisions, 1):
            elements.extend(self._format_decision_elements(decision, i))

            # 分隔线（除了最后一个）
            if i < len(display_decisions):
                elements.append(FeishuCardBuilder.create_divider())

        # 剩余数量提示
        if len(decisions) > self.max_decisions:
            remaining = len(decisions) - self.max_decisions
            elements.append(FeishuCardBuilder.create_text_element(
                f"... 还有 {remaining} 个决策未显示"
            ))

        # Dry-run 提示
        if dry_run:
            elements.append(FeishuCardBuilder.create_divider())
            elements.append(FeishuCardBuilder.create_text_element(
                "⚠️ **DRY-RUN 模式**，决策不会执行。使用 `--execute` 执行下单。"
            ))

        # 时间戳
        elements.append(FeishuCardBuilder.create_note(
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ))

        return {
            "header": FeishuCardBuilder.create_header(title, color),
            "elements": elements,
        }

    def format_execution_results(
        self,
        results: list[OrderRecord],
        command: str = "trade",
        market: str = "",
        strategy: str = "",
    ) -> dict[str, Any]:
        """格式化执行结果为飞书卡片

        Args:
            results: 订单记录列表
            command: 命令类型 (screen/monitor)
            market: 市场 (us/hk)
            strategy: 策略

        Returns:
            飞书卡片数据
        """
        # 统计成功/失败
        success_count = sum(
            1 for r in results
            if r.order.status in (OrderStatus.SUBMITTED, OrderStatus.FILLED, OrderStatus.ACKNOWLEDGED)
        )
        failed_count = len(results) - success_count

        # 确定卡片颜色
        if failed_count == 0:
            color = "green"
            emoji = "✅"
            status = "SUCCESS"
        elif success_count == 0:
            color = "red"
            emoji = "❌"
            status = "FAILED"
        else:
            color = "orange"
            emoji = "⚠️"
            status = "PARTIAL"

        title = f"{emoji} Trade {command.capitalize()} [{status}]"

        elements = []

        # 摘要信息
        summary_parts = []
        if market:
            summary_parts.append(f"市场: {market.upper()}")
        if strategy:
            summary_parts.append(f"策略: {strategy.upper()}")
        summary_parts.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        if summary_parts:
            elements.append(FeishuCardBuilder.create_text_element(" | ".join(summary_parts)))
            elements.append(FeishuCardBuilder.create_divider())

        # 执行统计
        stats_text = f"📤 提交 **{len(results)}** 个订单 | ✅ 成功: {success_count} | ❌ 失败: {failed_count}"
        elements.append(FeishuCardBuilder.create_text_element(stats_text))
        elements.append(FeishuCardBuilder.create_divider())

        # 订单详情
        display_results = results[:self.max_decisions]
        for i, record in enumerate(display_results, 1):
            elements.extend(self._format_order_elements(record, i))

            # 分隔线（除了最后一个）
            if i < len(display_results):
                elements.append(FeishuCardBuilder.create_divider())

        # 剩余数量提示
        if len(results) > self.max_decisions:
            remaining = len(results) - self.max_decisions
            elements.append(FeishuCardBuilder.create_text_element(
                f"... 还有 {remaining} 个订单未显示"
            ))

        # 时间戳
        elements.append(FeishuCardBuilder.create_note(
            f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ))

        return {
            "header": FeishuCardBuilder.create_header(title, color),
            "elements": elements,
        }

    def _format_decision_elements(
        self,
        decision: TradingDecision,
        index: int,
    ) -> list[dict[str, Any]]:
        """格式化单个决策为卡片元素列表

        Args:
            decision: 交易决策
            index: 序号

        Returns:
            卡片元素列表
        """
        elements = []

        # 决策类型 emoji
        type_emoji = {
            DecisionType.OPEN: "🟢",
            DecisionType.CLOSE: "🔴",
            DecisionType.ROLL: "🔄",
            DecisionType.ADJUST: "⚙️",
            DecisionType.HEDGE: "🛡️",
            DecisionType.HOLD: "⏸️",
        }.get(decision.decision_type, "📌")

        # 优先级 emoji
        priority_emoji = {
            DecisionPriority.CRITICAL: "🚨",
            DecisionPriority.HIGH: "⚡",
            DecisionPriority.NORMAL: "",
            DecisionPriority.LOW: "",
        }.get(decision.priority, "")

        # 标题行：#1 🟢 OPEN NVDA PUT K=120 Exp=2025-02-21
        opt_type = (decision.option_type or "").upper()
        strike_str = self._format_strike(decision.strike)
        exp_str = decision.expiry.replace("-", "") if decision.expiry else "N/A"

        header_parts = [f"**#{index}**", type_emoji, decision.decision_type.value.upper()]
        if decision.underlying:
            header_parts.append(decision.underlying)
        if opt_type:
            header_parts.append(opt_type)
        if strike_str:
            header_parts.append(f"K={strike_str}")
        if decision.expiry:
            header_parts.append(f"Exp={exp_str}")
        if priority_emoji:
            header_parts.append(priority_emoji)

        elements.append(FeishuCardBuilder.create_text_element(" ".join(header_parts)))

        # 交易参数行：Qty: -1 | Price: $2.50 | Priority: NORMAL
        qty_str = f"{decision.quantity:+d}" if decision.quantity else "N/A"
        price_str = f"${decision.limit_price:.2f}" if decision.limit_price else "Market"
        price_type = decision.price_type or "mid"

        params_text = f"Qty: {qty_str} | Price: {price_str} ({price_type}) | Priority: {decision.priority.value}"
        elements.append(FeishuCardBuilder.create_text_element(params_text))

        # 原因行（截断过长的原因）
        reason = decision.reason or "无"
        if len(reason) > 80:
            reason = reason[:77] + "..."
        elements.append(FeishuCardBuilder.create_text_element(f"💡 {reason}"))

        # 展期信息（仅 ROLL 类型）
        if decision.decision_type == DecisionType.ROLL and decision.roll_to_expiry:
            roll_info = f"🔄 展期到: {decision.roll_to_expiry}"
            if decision.roll_to_strike:
                roll_info += f" K={self._format_strike(decision.roll_to_strike)}"
            if decision.roll_credit:
                roll_info += f" Credit=${decision.roll_credit:.2f}"
            elements.append(FeishuCardBuilder.create_text_element(roll_info))

        return elements

    def _format_order_elements(
        self,
        record: OrderRecord,
        index: int,
    ) -> list[dict[str, Any]]:
        """格式化单个订单结果为卡片元素列表

        Args:
            record: 订单记录
            index: 序号

        Returns:
            卡片元素列表
        """
        elements = []
        order = record.order

        # 状态 emoji
        is_success = order.status in (
            OrderStatus.SUBMITTED,
            OrderStatus.FILLED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.APPROVED,
        )
        status_emoji = "✅" if is_success else "❌"

        # 标题行：✅ NVDA PUT K=120 | IBKR#12345 | Submitted
        opt_type = (order.option_type or "").upper()
        strike_str = self._format_strike(order.strike)

        header_parts = [status_emoji]
        if order.underlying:
            header_parts.append(order.underlying)
        elif order.symbol:
            # 从 symbol 提取 underlying
            underlying = order.symbol.split()[0] if " " in order.symbol else order.symbol
            header_parts.append(underlying)
        if opt_type:
            header_parts.append(opt_type)
        if strike_str:
            header_parts.append(f"K={strike_str}")

        # 券商订单信息
        if record.broker_order_id:
            header_parts.append(f"| IBKR#{record.broker_order_id}")
        header_parts.append(f"| {record.broker_status or order.status.value}")

        elements.append(FeishuCardBuilder.create_text_element(" ".join(header_parts)))

        # 订单参数行
        qty_str = f"{order.quantity}" if order.quantity else "N/A"
        side_str = order.side.value.upper() if order.side else "N/A"
        price_str = f"${order.limit_price:.2f}" if order.limit_price else "Market"

        params_text = f"Side: {side_str} | Qty: {qty_str} | Price: {price_str}"
        elements.append(FeishuCardBuilder.create_text_element(params_text))

        # 错误信息（如果有）
        if record.error_message:
            elements.append(FeishuCardBuilder.create_text_element(
                f"⚠️ 错误: {record.error_message}"
            ))

        # 成交信息（如果有）
        if record.total_filled_quantity > 0:
            fill_text = f"成交: {record.total_filled_quantity}"
            if record.average_fill_price:
                fill_text += f" @ ${record.average_fill_price:.2f}"
            if record.total_commission:
                fill_text += f" | 佣金: ${record.total_commission:.2f}"
            elements.append(FeishuCardBuilder.create_text_element(fill_text))

        return elements

    def _format_strike(self, strike: float | None) -> str:
        """格式化行权价"""
        if strike is None:
            return ""
        # 整数显示为整数，小数保留小数位
        if strike == int(strike):
            return f"{int(strike)}"
        return f"{strike:.2f}"

    def format(
        self,
        decisions: list[TradingDecision],
        results: list[OrderRecord] | None = None,
        dry_run: bool = True,
        command: str = "trade",
        market: str = "",
        strategy: str = "",
    ) -> dict[str, Any]:
        """格式化交易结果

        根据参数自动选择合适的格式：
        - 有执行结果: 使用 format_execution_results
        - 仅有决策: 使用 format_decisions

        Args:
            decisions: 决策列表
            results: 执行结果列表
            dry_run: 是否为 dry-run 模式
            command: 命令类型
            market: 市场
            strategy: 策略

        Returns:
            飞书卡片数据
        """
        if results:
            return self.format_execution_results(
                results,
                command=command,
                market=market,
                strategy=strategy,
            )
        else:
            return self.format_decisions(
                decisions,
                dry_run=dry_run,
                command=command,
                market=market,
                strategy=strategy,
            )
