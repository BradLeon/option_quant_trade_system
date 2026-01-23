"""
Trading Models - 交易执行数据模型

定义:
- TradingAccountType: 账户类型 (PAPER ONLY!)
- TradingProviderError: 交易提供者错误
- AccountTypeError: 账户类型错误
- TradingResult: 交易结果
- OrderQueryResult: 订单查询结果
- CancelResult: 取消结果
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TradingAccountType(str, Enum):
    """交易账户类型

    ⚠️  CRITICAL: 仅支持 PAPER 账户

    DO NOT ADD REAL ACCOUNT TYPE. This is intentional.
    Real trading is NOT supported by this system.
    """

    PAPER = "paper"
    # REAL = "real"  # ⛔ INTENTIONALLY NOT DEFINED - DO NOT ADD


class TradingProviderError(Exception):
    """交易提供者错误基类"""

    pass


class AccountTypeError(TradingProviderError):
    """账户类型错误

    Raised when attempting to trade on non-paper account.
    """

    pass


class ConnectionError(TradingProviderError):
    """连接错误"""

    pass


class OrderSubmitError(TradingProviderError):
    """订单提交错误"""

    pass


@dataclass
class TradingResult:
    """交易执行结果

    TradingProvider.submit_order() 的返回值。
    """

    success: bool
    internal_order_id: str | None = None
    broker_order_id: str | None = None

    # 错误信息
    error_code: str | None = None
    error_message: str | None = None

    # 执行信息
    executed_quantity: int = 0
    executed_price: float | None = None
    commission: float = 0.0

    timestamp: datetime = field(default_factory=datetime.now)

    # 额外上下文
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls,
        internal_order_id: str,
        broker_order_id: str,
        **kwargs: Any,
    ) -> "TradingResult":
        """创建成功结果"""
        return cls(
            success=True,
            internal_order_id=internal_order_id,
            broker_order_id=broker_order_id,
            **kwargs,
        )

    @classmethod
    def failure_result(
        cls,
        internal_order_id: str | None,
        error_code: str,
        error_message: str,
        **kwargs: Any,
    ) -> "TradingResult":
        """创建失败结果"""
        return cls(
            success=False,
            internal_order_id=internal_order_id,
            error_code=error_code,
            error_message=error_message,
            **kwargs,
        )


@dataclass
class OrderQueryResult:
    """订单查询结果

    TradingProvider.query_order() 的返回值。
    """

    found: bool
    broker_order_id: str | None = None
    status: str | None = None  # Broker-specific status string

    filled_quantity: int = 0
    remaining_quantity: int = 0
    average_price: float | None = None

    last_updated: datetime | None = None

    # 额外信息
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def not_found(cls, broker_order_id: str | None = None) -> "OrderQueryResult":
        """创建未找到结果"""
        return cls(found=False, broker_order_id=broker_order_id)

    @property
    def is_filled(self) -> bool:
        """是否已完全成交"""
        return self.remaining_quantity == 0 and self.filled_quantity > 0

    @property
    def is_partially_filled(self) -> bool:
        """是否部分成交"""
        return self.remaining_quantity > 0 and self.filled_quantity > 0


@dataclass
class CancelResult:
    """取消订单结果

    TradingProvider.cancel_order() 的返回值。
    """

    success: bool
    broker_order_id: str | None = None
    error_message: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    @classmethod
    def success_cancel(cls, broker_order_id: str) -> "CancelResult":
        """创建成功取消结果"""
        return cls(success=True, broker_order_id=broker_order_id)

    @classmethod
    def failure_cancel(
        cls, broker_order_id: str | None, error_message: str
    ) -> "CancelResult":
        """创建失败取消结果"""
        return cls(
            success=False,
            broker_order_id=broker_order_id,
            error_message=error_message,
        )
