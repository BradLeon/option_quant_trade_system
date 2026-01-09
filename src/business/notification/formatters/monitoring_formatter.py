"""
Monitoring Formatter - 监控结果格式化器

将监控结果格式化为推送消息。
"""

from typing import Any

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    MonitorResult,
    MonitorStatus,
)
from src.business.notification.channels.feishu import FeishuCardBuilder


class MonitoringFormatter:
    """监控结果格式化器

    将 MonitorResult 转换为飞书卡片消息。
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

    def format_report(
        self,
        result: MonitorResult,
    ) -> dict[str, Any]:
        """格式化监控报告

        Args:
            result: 监控结果

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "monitor_report_title",
            "📋 持仓监控报告",
        )

        # 构建预警列表
        alerts_data = [
            {
                "level": alert.level.value,
                "message": alert.message,
                "symbol": alert.symbol,
            }
            for alert in result.alerts[:10]  # 最多 10 个
        ]

        return FeishuCardBuilder.create_monitor_report_card(
            title=title,
            status=result.status.value,
            alerts=alerts_data,
            summary=result.summary,
        )

    def format_risk_alert(
        self,
        alert: Alert,
    ) -> dict[str, Any]:
        """格式化风险预警

        Args:
            alert: 预警信息

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "risk_alert_title",
            "🔴 风险预警 - {alert_type}",
        ).format(alert_type=alert.alert_type.value)

        details = {}
        if alert.symbol:
            details["标的"] = alert.symbol
        if alert.current_value is not None:
            details["当前值"] = f"{alert.current_value:.2f}"
        if alert.threshold_value is not None:
            details["阈值"] = f"{alert.threshold_value:.2f}"

        return FeishuCardBuilder.create_alert_card(
            title=title,
            level="red",
            message=alert.message,
            details=details if details else None,
            suggestion=alert.suggested_action,
        )

    def format_attention_alert(
        self,
        alert: Alert,
    ) -> dict[str, Any]:
        """格式化关注提醒

        Args:
            alert: 预警信息

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "attention_alert_title",
            "🟡 关注提醒 - {alert_type}",
        ).format(alert_type=alert.alert_type.value)

        details = {}
        if alert.symbol:
            details["标的"] = alert.symbol
        if alert.current_value is not None:
            details["当前值"] = f"{alert.current_value:.2f}"

        return FeishuCardBuilder.create_alert_card(
            title=title,
            level="yellow",
            message=alert.message,
            details=details if details else None,
            suggestion=alert.suggested_action,
        )

    def format_opportunity_alert(
        self,
        alert: Alert,
    ) -> dict[str, Any]:
        """格式化机会提醒

        Args:
            alert: 预警信息

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "opportunity_alert_title",
            "🟢 发现机会 - {alert_type}",
        ).format(alert_type=alert.alert_type.value)

        details = {}
        if alert.symbol:
            details["标的"] = alert.symbol
        if alert.current_value is not None:
            details["当前值"] = f"{alert.current_value:.2f}"

        return FeishuCardBuilder.create_alert_card(
            title=title,
            level="green",
            message=alert.message,
            details=details if details else None,
            suggestion=alert.suggested_action,
        )

    def format_alert(self, alert: Alert) -> dict[str, Any]:
        """格式化单个预警

        根据预警级别自动选择格式。

        Args:
            alert: 预警信息

        Returns:
            飞书卡片数据
        """
        if alert.level == AlertLevel.RED:
            return self.format_risk_alert(alert)
        elif alert.level == AlertLevel.YELLOW:
            return self.format_attention_alert(alert)
        else:
            return self.format_opportunity_alert(alert)

    def format(
        self,
        result: MonitorResult,
        alert_levels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """格式化监控结果

        根据配置的预警级别生成消息列表。

        Args:
            result: 监控结果
            alert_levels: 要推送的预警级别 ["red", "yellow", "green"]

        Returns:
            卡片数据列表
        """
        if alert_levels is None:
            alert_levels = ["red", "yellow"]

        cards: list[dict[str, Any]] = []

        # 如果有红色预警，发送报告
        if result.red_alerts:
            cards.append(self.format_report(result))

        # 单独发送每个预警
        for alert in result.alerts:
            if alert.level.value in alert_levels:
                cards.append(self.format_alert(alert))

        return cards
