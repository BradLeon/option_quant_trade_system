"""
Signal Push System - 信号推送系统

推送渠道和消息格式化：
- channels: 推送渠道 (飞书等)
- formatters: 消息格式化器
- dispatcher: 消息调度器
"""

from src.business.notification.channels.base import NotificationChannel, SendResult
from src.business.notification.dispatcher import MessageDispatcher

__all__ = ["NotificationChannel", "SendResult", "MessageDispatcher"]
