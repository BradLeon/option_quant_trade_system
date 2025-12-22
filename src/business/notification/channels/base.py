"""
Base Notification Channel - 通知渠道基类

定义通知渠道的基类和通用接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SendStatus(str, Enum):
    """发送状态"""

    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    SILENCED = "silenced"


@dataclass
class SendResult:
    """发送结果"""

    status: SendStatus
    message_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == SendStatus.SUCCESS


class NotificationChannel(ABC):
    """通知渠道基类

    所有通知渠道都应继承此类并实现相关方法。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """渠道名称"""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """渠道是否可用"""
        pass

    @abstractmethod
    def send(
        self,
        title: str,
        content: str,
        **kwargs: Any,
    ) -> SendResult:
        """发送消息

        Args:
            title: 消息标题
            content: 消息内容
            **kwargs: 渠道特定参数

        Returns:
            SendResult: 发送结果
        """
        pass

    @abstractmethod
    def send_card(
        self,
        card_data: dict[str, Any],
    ) -> SendResult:
        """发送卡片消息

        Args:
            card_data: 卡片数据

        Returns:
            SendResult: 发送结果
        """
        pass
