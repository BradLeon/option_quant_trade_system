"""
Message Dispatcher - 消息调度器

负责：
- 消息去重
- 频率限制
- 静默时段控制
- 消息聚合
"""

import hashlib
import logging
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from src.business.monitoring.models import Alert, MonitorResult
from src.business.notification.channels.base import NotificationChannel, SendResult, SendStatus
from src.business.notification.channels.feishu import FeishuChannel
from src.business.notification.formatters.dashboard_formatter import DashboardFormatter
from src.business.notification.formatters.monitoring_formatter import MonitoringFormatter
from src.business.notification.formatters.screening_formatter import ScreeningFormatter
from src.business.screening.models import ScreeningResult

logger = logging.getLogger(__name__)


class MessageDispatcher:
    """消息调度器

    负责统一管理消息推送：
    1. 消息去重 - 避免短时间内发送重复消息
    2. 频率限制 - 控制推送频率
    3. 静默时段 - 在指定时间段内不推送
    4. 消息聚合 - 将多条预警聚合为一条消息
    """

    def __init__(
        self,
        channel: Optional[NotificationChannel] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        """初始化消息调度器

        Args:
            channel: 通知渠道，默认使用飞书
            config: 配置，默认从 YAML 加载
        """
        self.channel = channel or FeishuChannel.from_env()
        self.config = config or self._load_config()

        # 初始化格式化器
        templates = self.config.get("templates", {})
        self.screening_formatter = ScreeningFormatter(templates)
        self.monitoring_formatter = MonitoringFormatter(templates)
        self.dashboard_formatter = DashboardFormatter(templates)

        # 消息去重缓存
        self._sent_messages: dict[str, datetime] = {}
        self._dedup_window = self.config.get("rate_limit", {}).get("dedup_window", 1800)

        # 频率限制
        self._last_send_time: Optional[datetime] = None
        self._min_interval = self.config.get("rate_limit", {}).get("min_interval", 60)

        # 静默时段配置
        silent_config = self.config.get("rate_limit", {}).get("silent_hours", {})
        self._silent_enabled = silent_config.get("enabled", False)
        self._silent_start = self._parse_time(silent_config.get("start", "23:00"))
        self._silent_end = self._parse_time(silent_config.get("end", "07:00"))

        # 预警级别配置
        self._alert_levels = self.config.get("content", {}).get(
            "alert_levels", ["red", "yellow"]
        )

    def _load_config(self) -> dict[str, Any]:
        """加载配置"""
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "notification" / "feishu.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _parse_time(self, time_str: str) -> time:
        """解析时间字符串"""
        try:
            parts = time_str.split(":")
            return time(int(parts[0]), int(parts[1]))
        except Exception:
            return time(0, 0)

    def _is_silent_period(self) -> bool:
        """检查是否在静默时段"""
        if not self._silent_enabled:
            return False

        now = datetime.now().time()

        # 处理跨午夜的情况
        if self._silent_start > self._silent_end:
            # 例如 23:00 - 07:00
            return now >= self._silent_start or now <= self._silent_end
        else:
            return self._silent_start <= now <= self._silent_end

    def _is_rate_limited(self) -> bool:
        """检查是否触发频率限制"""
        if self._last_send_time is None:
            return False

        elapsed = (datetime.now() - self._last_send_time).total_seconds()
        return elapsed < self._min_interval

    def _get_message_hash(self, content: Any) -> str:
        """计算消息哈希（用于去重）"""
        content_str = str(content)
        return hashlib.md5(content_str.encode()).hexdigest()[:16]

    def _is_duplicate(self, content: Any) -> bool:
        """检查消息是否重复"""
        msg_hash = self._get_message_hash(content)
        now = datetime.now()

        # 清理过期的缓存
        expired_keys = [
            k for k, v in self._sent_messages.items()
            if (now - v).total_seconds() > self._dedup_window
        ]
        for k in expired_keys:
            del self._sent_messages[k]

        # 检查是否重复
        if msg_hash in self._sent_messages:
            return True

        return False

    def _mark_sent(self, content: Any) -> None:
        """标记消息已发送"""
        msg_hash = self._get_message_hash(content)
        self._sent_messages[msg_hash] = datetime.now()
        self._last_send_time = datetime.now()

    def send_screening_result(
        self,
        result: ScreeningResult,
        force: bool = False,
    ) -> SendResult:
        """发送筛选结果

        Args:
            result: 筛选结果
            force: 是否强制发送（忽略限制）

        Returns:
            SendResult
        """
        # 检查限制
        if not force:
            if self._is_silent_period():
                return SendResult(
                    status=SendStatus.SILENCED,
                    error="In silent period",
                )

            if self._is_rate_limited():
                return SendResult(
                    status=SendStatus.RATE_LIMITED,
                    error="Rate limited",
                )

        # 格式化消息
        card_data = self.screening_formatter.format(result)

        # 检查去重
        if not force and self._is_duplicate(card_data):
            return SendResult(
                status=SendStatus.RATE_LIMITED,
                error="Duplicate message",
            )

        # 发送消息
        send_result = self.channel.send_card(card_data)

        if send_result.is_success:
            self._mark_sent(card_data)

        return send_result

    def send_monitoring_result(
        self,
        result: MonitorResult,
        force: bool = False,
    ) -> list[SendResult]:
        """发送监控结果

        Args:
            result: 监控结果
            force: 是否强制发送

        Returns:
            SendResult 列表
        """
        results: list[SendResult] = []

        # 检查限制
        if not force:
            if self._is_silent_period():
                return [SendResult(
                    status=SendStatus.SILENCED,
                    error="In silent period",
                )]

        # 格式化消息
        cards = self.monitoring_formatter.format(result, self._alert_levels)

        for card_data in cards:
            # 检查频率限制
            if not force and self._is_rate_limited():
                results.append(SendResult(
                    status=SendStatus.RATE_LIMITED,
                    error="Rate limited",
                ))
                continue

            # 检查去重
            if not force and self._is_duplicate(card_data):
                results.append(SendResult(
                    status=SendStatus.RATE_LIMITED,
                    error="Duplicate message",
                ))
                continue

            # 发送消息
            send_result = self.channel.send_card(card_data)

            if send_result.is_success:
                self._mark_sent(card_data)

            results.append(send_result)

        return results

    def send_alert(
        self,
        alert: Alert,
        force: bool = False,
    ) -> SendResult:
        """发送单个预警

        Args:
            alert: 预警信息
            force: 是否强制发送

        Returns:
            SendResult
        """
        # 检查级别
        if alert.level.value not in self._alert_levels:
            return SendResult(
                status=SendStatus.SILENCED,
                error=f"Alert level {alert.level.value} not in configured levels",
            )

        # 检查限制
        if not force:
            if self._is_silent_period():
                return SendResult(
                    status=SendStatus.SILENCED,
                    error="In silent period",
                )

            if self._is_rate_limited():
                return SendResult(
                    status=SendStatus.RATE_LIMITED,
                    error="Rate limited",
                )

        # 格式化消息
        card_data = self.monitoring_formatter.format_alert(alert)

        # 检查去重
        if not force and self._is_duplicate(card_data):
            return SendResult(
                status=SendStatus.RATE_LIMITED,
                error="Duplicate message",
            )

        # 发送消息
        send_result = self.channel.send_card(card_data)

        if send_result.is_success:
            self._mark_sent(card_data)

        return send_result

    def send_text(
        self,
        title: str,
        content: str,
        force: bool = False,
    ) -> SendResult:
        """发送文本消息

        Args:
            title: 标题
            content: 内容
            force: 是否强制发送

        Returns:
            SendResult
        """
        # 检查限制
        if not force:
            if self._is_silent_period():
                return SendResult(
                    status=SendStatus.SILENCED,
                    error="In silent period",
                )

            if self._is_rate_limited():
                return SendResult(
                    status=SendStatus.RATE_LIMITED,
                    error="Rate limited",
                )

        # 发送消息
        send_result = self.channel.send(title, content)

        if send_result.is_success:
            self._last_send_time = datetime.now()

        return send_result

    def send_dashboard_result(
        self,
        result: MonitorResult,
        force: bool = False,
    ) -> SendResult:
        """发送仪表盘每日报告

        Args:
            result: 监控结果
            force: 是否强制发送（忽略限制）

        Returns:
            SendResult
        """
        # 检查限制
        if not force:
            if self._is_silent_period():
                return SendResult(
                    status=SendStatus.SILENCED,
                    error="In silent period",
                )

            if self._is_rate_limited():
                return SendResult(
                    status=SendStatus.RATE_LIMITED,
                    error="Rate limited",
                )

        # 格式化消息
        card_data = self.dashboard_formatter.format(result)

        # 检查去重
        if not force and self._is_duplicate(card_data):
            return SendResult(
                status=SendStatus.RATE_LIMITED,
                error="Duplicate message",
            )

        # 发送消息
        send_result = self.channel.send_card(card_data)

        if send_result.is_success:
            self._mark_sent(card_data)

        return send_result


# 便捷函数
def create_dispatcher(
    config_path: Optional[str] = None,
) -> MessageDispatcher:
    """创建消息调度器

    Args:
        config_path: 配置文件路径

    Returns:
        MessageDispatcher 实例
    """
    config = None
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

    return MessageDispatcher(config=config)
