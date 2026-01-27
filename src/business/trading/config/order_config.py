"""
Order Configuration - 订单管理配置

订单管理器的配置参数。
"""

import os
from dataclasses import dataclass
from typing import Any


def _env_str(key: str, default: str) -> str:
    """从环境变量获取 str"""
    return os.getenv(key, default)


def _env_float(key: str, default: float) -> float:
    """从环境变量获取 float"""
    val = os.getenv(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _env_int(key: str, default: int) -> int:
    """从环境变量获取 int"""
    val = os.getenv(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool) -> bool:
    """从环境变量获取 bool"""
    val = os.getenv(key)
    if val is not None:
        return val.lower() in ("true", "1", "yes")
    return default


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

    @classmethod
    def load(cls) -> "OrderConfig":
        """加载配置

        优先级: 环境变量 > 默认值
        """
        return cls(
            storage_path=_env_str("ORDER_STORAGE_PATH", "data/trading/orders"),
            storage_format=_env_str("ORDER_STORAGE_FORMAT", "json"),
            default_time_in_force=_env_str("ORDER_DEFAULT_TIME_IN_FORCE", "DAY"),
            default_order_type=_env_str("ORDER_DEFAULT_ORDER_TYPE", "limit"),
            max_price_deviation_pct=_env_float("ORDER_MAX_PRICE_DEVIATION_PCT", 0.05),
            max_retries=_env_int("ORDER_MAX_RETRIES", 3),
            retry_delay_seconds=_env_int("ORDER_RETRY_DELAY_SECONDS", 5),
            notify_on_submit=_env_bool("ORDER_NOTIFY_ON_SUBMIT", True),
            notify_on_fill=_env_bool("ORDER_NOTIFY_ON_FILL", True),
            notify_on_reject=_env_bool("ORDER_NOTIFY_ON_REJECT", True),
            notify_on_cancel=_env_bool("ORDER_NOTIFY_ON_CANCEL", True),
            execution_mode=_env_str("ORDER_EXECUTION_MODE", "manual"),
            require_confirm=_env_bool("ORDER_REQUIRE_CONFIRM", True),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderConfig":
        """从字典创建配置 (用于测试)"""
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
