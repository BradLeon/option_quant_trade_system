"""
Order Configuration - 订单管理配置

加载和管理订单管理器的配置参数。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class OrderConfig:
    """订单管理配置"""

    # 存储配置
    storage_path: str = "data/trading/orders"
    storage_format: str = "json"  # json or sqlite

    # 订单默认值
    default_time_in_force: str = "DAY"  # DAY, GTC, IOC
    default_order_type: str = "limit"  # limit, market

    # 价格偏离限制
    max_price_deviation_pct: float = 0.05  # 5%

    # 重试配置
    max_retries: int = 3
    retry_delay_seconds: int = 5

    # 通知配置
    notify_on_submit: bool = True
    notify_on_fill: bool = True
    notify_on_reject: bool = True
    notify_on_cancel: bool = True

    # 执行模式
    execution_mode: str = "manual"  # manual or auto
    require_confirm: bool = True  # CLI 需要 --confirm

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "OrderConfig":
        """从 YAML 文件加载配置"""
        if config_path is None:
            config_path = Path("config/trading/order.yaml")
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderConfig":
        """从字典创建配置"""
        return cls(
            storage_path=data.get("storage_path", "data/trading/orders"),
            storage_format=data.get("storage_format", "json"),
            default_time_in_force=data.get("default_time_in_force", "DAY"),
            default_order_type=data.get("default_order_type", "limit"),
            max_price_deviation_pct=data.get("max_price_deviation_pct", 0.05),
            max_retries=data.get("max_retries", 3),
            retry_delay_seconds=data.get("retry_delay_seconds", 5),
            notify_on_submit=data.get("notify_on_submit", True),
            notify_on_fill=data.get("notify_on_fill", True),
            notify_on_reject=data.get("notify_on_reject", True),
            notify_on_cancel=data.get("notify_on_cancel", True),
            execution_mode=data.get("execution_mode", "manual"),
            require_confirm=data.get("require_confirm", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "storage_path": self.storage_path,
            "storage_format": self.storage_format,
            "default_time_in_force": self.default_time_in_force,
            "default_order_type": self.default_order_type,
            "max_price_deviation_pct": self.max_price_deviation_pct,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "notify_on_submit": self.notify_on_submit,
            "notify_on_fill": self.notify_on_fill,
            "notify_on_reject": self.notify_on_reject,
            "notify_on_cancel": self.notify_on_cancel,
            "execution_mode": self.execution_mode,
            "require_confirm": self.require_confirm,
        }
