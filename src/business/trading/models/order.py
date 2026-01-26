"""
Order Models - 订单管理数据模型

定义:
- OrderSide: 买卖方向
- OrderType: 订单类型
- OrderStatus: 订单状态
- AssetClass: 资产类别
- OrderRequest: 订单请求
- OrderFill: 成交记录
- OrderRecord: 完整订单记录
- RiskCheckResult: 风控检查结果
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    """买卖方向"""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """订单状态"""

    PENDING_VALIDATION = "pending_validation"  # 待验证
    VALIDATION_FAILED = "validation_failed"  # 验证失败
    APPROVED = "approved"  # 已批准
    SUBMITTED = "submitted"  # 已提交
    ACKNOWLEDGED = "acknowledged"  # 已确认
    PARTIAL_FILLED = "partial_filled"  # 部分成交
    FILLED = "filled"  # 完全成交
    CANCELLED = "cancelled"  # 已取消
    REJECTED = "rejected"  # 被拒绝
    EXPIRED = "expired"  # 已过期
    ERROR = "error"  # 错误


class AssetClass(str, Enum):
    """资产类别"""

    STOCK = "stock"
    OPTION = "option"


@dataclass
class OrderRequest:
    """订单请求

    从 TradingDecision 生成，提交给 TradingProvider 执行。
    """

    order_id: str
    decision_id: str

    # 标的信息
    symbol: str
    asset_class: AssetClass
    underlying: str | None = None
    option_type: str | None = None  # "put" / "call"
    strike: float | None = None
    expiry: str | None = None  # YYYYMMDD or YYYY-MM-DD
    trading_class: str | None = None

    # 订单参数
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.LIMIT
    quantity: int = 0
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "DAY"  # DAY, GTC, IOC

    # 合约参数
    contract_multiplier: int = 100  # 合约乘数 (US=100, HK 视标的而定)
    currency: str = "USD"  # 交易币种

    # 券商信息
    broker: str = ""  # "ibkr" or "futu"
    account_type: str = "paper"  # MUST be "paper"

    # 状态
    status: OrderStatus = OrderStatus.PENDING_VALIDATION
    validation_errors: list[str] = field(default_factory=list)

    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # 上下文 (用于调试和通知)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def is_option(self) -> bool:
        """是否期权订单"""
        return self.asset_class == AssetClass.OPTION

    @property
    def is_valid(self) -> bool:
        """是否通过验证"""
        return self.status == OrderStatus.APPROVED

    @property
    def is_terminal(self) -> bool:
        """是否终态"""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.ERROR,
            OrderStatus.VALIDATION_FAILED,
        )

    def update_status(self, new_status: OrderStatus) -> None:
        """更新状态"""
        self.status = new_status
        self.updated_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "order_id": self.order_id,
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "underlying": self.underlying,
            "option_type": self.option_type,
            "strike": self.strike,
            "expiry": self.expiry,
            "trading_class": self.trading_class,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "contract_multiplier": self.contract_multiplier,
            "currency": self.currency,
            "broker": self.broker,
            "account_type": self.account_type,
            "status": self.status.value,
            "validation_errors": self.validation_errors,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderRequest":
        """从字典创建"""
        return cls(
            order_id=data["order_id"],
            decision_id=data["decision_id"],
            symbol=data["symbol"],
            asset_class=AssetClass(data["asset_class"]),
            underlying=data.get("underlying"),
            option_type=data.get("option_type"),
            strike=data.get("strike"),
            expiry=data.get("expiry"),
            trading_class=data.get("trading_class"),
            side=OrderSide(data["side"]),
            order_type=OrderType(data["order_type"]),
            quantity=data["quantity"],
            limit_price=data.get("limit_price"),
            stop_price=data.get("stop_price"),
            time_in_force=data.get("time_in_force", "DAY"),
            contract_multiplier=data.get("contract_multiplier", 100),
            currency=data.get("currency", "USD"),
            broker=data.get("broker", ""),
            account_type=data.get("account_type", "paper"),
            status=OrderStatus(data["status"]),
            validation_errors=data.get("validation_errors", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            context=data.get("context", {}),
        )


@dataclass
class OrderFill:
    """成交记录"""

    fill_id: str
    order_id: str
    filled_quantity: int
    fill_price: float
    commission: float = 0.0
    fill_time: datetime = field(default_factory=datetime.now)
    broker_fill_id: str | None = None
    broker_order_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "filled_quantity": self.filled_quantity,
            "fill_price": self.fill_price,
            "commission": self.commission,
            "fill_time": self.fill_time.isoformat(),
            "broker_fill_id": self.broker_fill_id,
            "broker_order_id": self.broker_order_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderFill":
        """从字典创建"""
        return cls(
            fill_id=data["fill_id"],
            order_id=data["order_id"],
            filled_quantity=data["filled_quantity"],
            fill_price=data["fill_price"],
            commission=data.get("commission", 0.0),
            fill_time=datetime.fromisoformat(data["fill_time"]),
            broker_fill_id=data.get("broker_fill_id"),
            broker_order_id=data.get("broker_order_id"),
        )


@dataclass
class OrderRecord:
    """完整订单记录

    包含订单、成交、状态历史等完整信息。
    """

    order: OrderRequest
    fills: list[OrderFill] = field(default_factory=list)
    total_filled_quantity: int = 0
    average_fill_price: float | None = None
    total_commission: float = 0.0

    # 状态历史: (status, timestamp, message)
    status_history: list[tuple[str, str, str]] = field(default_factory=list)

    # 券商信息
    broker_order_id: str | None = None
    broker_status: str | None = None

    # 完成状态
    is_complete: bool = False
    completion_time: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0

    def add_fill(self, fill: OrderFill) -> None:
        """添加成交记录"""
        self.fills.append(fill)
        self.total_filled_quantity += fill.filled_quantity
        self.total_commission += fill.commission

        # 更新平均成交价
        if self.total_filled_quantity > 0:
            total_value = sum(f.fill_price * f.filled_quantity for f in self.fills)
            self.average_fill_price = total_value / self.total_filled_quantity

        # 检查是否完全成交
        if self.total_filled_quantity >= self.order.quantity:
            self.is_complete = True
            self.completion_time = datetime.now()
            self.order.update_status(OrderStatus.FILLED)
            self.add_status_history(OrderStatus.FILLED, "Fully filled")

    def add_status_history(self, status: OrderStatus, message: str = "") -> None:
        """添加状态历史"""
        self.status_history.append(
            (status.value, datetime.now().isoformat(), message)
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "order": self.order.to_dict(),
            "fills": [f.to_dict() for f in self.fills],
            "total_filled_quantity": self.total_filled_quantity,
            "average_fill_price": self.average_fill_price,
            "total_commission": self.total_commission,
            "status_history": self.status_history,
            "broker_order_id": self.broker_order_id,
            "broker_status": self.broker_status,
            "is_complete": self.is_complete,
            "completion_time": (
                self.completion_time.isoformat() if self.completion_time else None
            ),
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderRecord":
        """从字典创建"""
        order = OrderRequest.from_dict(data["order"])
        fills = [OrderFill.from_dict(f) for f in data.get("fills", [])]
        completion_time = (
            datetime.fromisoformat(data["completion_time"])
            if data.get("completion_time")
            else None
        )
        return cls(
            order=order,
            fills=fills,
            total_filled_quantity=data.get("total_filled_quantity", 0),
            average_fill_price=data.get("average_fill_price"),
            total_commission=data.get("total_commission", 0.0),
            status_history=data.get("status_history", []),
            broker_order_id=data.get("broker_order_id"),
            broker_status=data.get("broker_status"),
            is_complete=data.get("is_complete", False),
            completion_time=completion_time,
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
        )


@dataclass
class RiskCheckResult:
    """风控检查结果"""

    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # 预测值
    projected_margin_utilization: float | None = None
    projected_cash_ratio: float | None = None
    projected_gross_leverage: float | None = None

    timestamp: datetime = field(default_factory=datetime.now)

    def add_check(
        self,
        name: str,
        passed: bool,
        message: str,
        current_value: float | None = None,
        threshold: float | None = None,
    ) -> None:
        """添加检查结果"""
        check = {
            "name": name,
            "passed": passed,
            "message": message,
            "current_value": current_value,
            "threshold": threshold,
        }
        self.checks.append(check)
        if not passed:
            self.failed_checks.append(f"{name}: {message}")
            self.passed = False

    def add_warning(self, message: str) -> None:
        """添加警告"""
        self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "passed": self.passed,
            "checks": self.checks,
            "failed_checks": self.failed_checks,
            "warnings": self.warnings,
            "projected_margin_utilization": self.projected_margin_utilization,
            "projected_cash_ratio": self.projected_cash_ratio,
            "projected_gross_leverage": self.projected_gross_leverage,
            "timestamp": self.timestamp.isoformat(),
        }
