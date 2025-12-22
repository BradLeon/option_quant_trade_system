"""
Notification Channels - 通知渠道

支持的渠道：
- FeishuChannel: 飞书 Webhook 推送
"""

from src.business.notification.channels.base import (
    NotificationChannel,
    SendResult,
    SendStatus,
)
from src.business.notification.channels.feishu import (
    FeishuChannel,
    FeishuCardBuilder,
    FeishuConfig,
)

__all__ = [
    "NotificationChannel",
    "SendResult",
    "SendStatus",
    "FeishuChannel",
    "FeishuCardBuilder",
    "FeishuConfig",
]
