"""
Order Configuration - 订单管理配置

订单管理器的配置参数。
"""

import os
from dataclasses import dataclass, fields
from typing import Any


@dataclass
class OrderConfig:
    """订单管理配置

    支持通过环境变量覆盖默认值 (前缀: ORDER_)

    示例:
        export ORDER_EXECUTION_MODE=auto
        export ORDER_REQUIRE_CONFIRM=false
    """

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

    _ENV_PREFIX = "ORDER_"

    # bool 字段需要特殊解析
    _BOOL_FIELDS = {
        "notify_on_submit", "notify_on_fill", "notify_on_reject",
        "notify_on_cancel", "require_confirm",
    }

    @classmethod
    def load(cls) -> "OrderConfig":
        """加载配置

        优先级: 环境变量 > dataclass 字段默认值
        环境变量命名规则: ORDER_ + 字段名大写，如 ORDER_EXECUTION_MODE
        """
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            env_key = f"{cls._ENV_PREFIX}{f.name.upper()}"
            val = os.getenv(env_key)
            if val is not None:
                if f.name in cls._BOOL_FIELDS:
                    kwargs[f.name] = val.lower() in ("true", "1", "yes")
                else:
                    try:
                        kwargs[f.name] = f.type(val) if callable(f.type) else val
                    except (ValueError, TypeError):
                        pass
        return cls(**kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderConfig":
        """从字典创建配置 (用于测试)

        只覆盖字典中存在的字段，缺失字段使用 dataclass 默认值。
        """
        valid_fields = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**kwargs)

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
