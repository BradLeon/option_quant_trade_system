"""
Decision Models - 决策引擎数据模型

定义:
- DecisionType: 决策类型 (OPEN, CLOSE, ROLL, etc.)
- DecisionSource: 决策来源 (SCREEN_SIGNAL, MONITOR_ALERT)
- DecisionPriority: 优先级 (CRITICAL, HIGH, NORMAL, LOW)
- AccountState: 账户状态快照
- PositionContext: 持仓上下文
- TradingDecision: 交易决策
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from src.engine.models.enums import StrategyType


class DecisionType(str, Enum):
    """决策类型"""

    OPEN = "open"  # 开仓
    CLOSE = "close"  # 平仓
    ROLL = "roll"  # 展期
    HEDGE = "hedge"  # 对冲
    ADJUST = "adjust"  # 调整
    HOLD = "hold"  # 持有 (不操作)


class DecisionSource(str, Enum):
    """决策来源"""

    SCREEN_SIGNAL = "screen_signal"  # From Screen system
    MONITOR_ALERT = "monitor_alert"  # From Monitor system
    MANUAL = "manual"  # Manual override


class DecisionPriority(str, Enum):
    """决策优先级"""

    CRITICAL = "critical"  # 止损/追保 - 立即执行
    HIGH = "high"  # 分钟级响应
    NORMAL = "normal"  # 当日处理
    LOW = "low"  # 择时执行


@dataclass
class AccountState:
    """账户状态快照

    从 AccountAggregator 获取的账户状态，用于决策和风控。
    """

    broker: str
    account_type: str  # MUST be "paper"
    total_equity: float  # NLV (Net Liquidation Value)
    cash_balance: float
    available_margin: float
    used_margin: float  # Maint Margin

    # 核心风控四大支柱指标
    margin_utilization: float  # Maint Margin / NLV (< 70% for opening)
    cash_ratio: float  # Cash / NLV (> 10% for opening)
    gross_leverage: float  # Total Notional / NLV (< 4.0x)

    # 持仓统计
    total_position_count: int = 0
    option_position_count: int = 0
    stock_position_count: int = 0

    # 标的暴露
    exposure_by_underlying: dict[str, float] = field(default_factory=dict)

    timestamp: datetime = field(default_factory=datetime.now)

    def can_open_position(
        self,
        max_margin_utilization: float = 0.70,
        min_cash_ratio: float = 0.10,
        max_gross_leverage: float = 4.0,
    ) -> tuple[bool, list[str]]:
        """检查是否可以开新仓

        Note: 推荐使用 AccountStateAnalyzer.can_open_position() 进行完整的风控检查，
              该方法会使用配置文件中的阈值，并支持更多检查项（如持仓数量限制）。

        Args:
            max_margin_utilization: 最大保证金使用率 (默认 70%)
            min_cash_ratio: 最小现金比例 (默认 10%)
            max_gross_leverage: 最大杠杆 (默认 4.0x)

        Returns:
            (can_open, rejection_reasons)
        """
        reasons = []

        if self.margin_utilization >= max_margin_utilization:
            reasons.append(
                f"Margin utilization too high: {self.margin_utilization:.1%} >= {max_margin_utilization:.0%}"
            )

        if self.cash_ratio < min_cash_ratio:
            reasons.append(f"Insufficient cash buffer: {self.cash_ratio:.1%} < {min_cash_ratio:.0%}")

        if self.gross_leverage >= max_gross_leverage:
            reasons.append(f"Leverage limit exceeded: {self.gross_leverage:.1f}x >= {max_gross_leverage:.1f}x")

        return (len(reasons) == 0, reasons)


@dataclass
class PositionContext:
    """持仓上下文

    从 AccountAggregator 获取的持仓信息，用于平仓/调整决策。
    """

    position_id: str
    symbol: str
    underlying: str | None = None
    option_type: str | None = None  # "put" / "call"
    strike: float | None = None
    expiry: str | None = None  # YYYYMMDD or YYYY-MM-DD
    trading_class: str | None = None
    dte: int | None = None

    quantity: float = 0.0
    avg_cost: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    # Greeks
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    strategy_type: StrategyType | None = None
    related_position_ids: list[str] = field(default_factory=list)

    @property
    def is_option(self) -> bool:
        """是否期权持仓"""
        return self.option_type is not None


@dataclass
class TradingDecision:
    """交易决策

    Decision Engine 的输出，包含完整的交易上下文。
    """

    decision_id: str
    decision_type: DecisionType
    source: DecisionSource
    priority: DecisionPriority

    # 交易标的
    symbol: str
    underlying: str | None = None
    option_type: str | None = None  # "put" / "call"
    strike: float | None = None
    expiry: str | None = None  # YYYY-MM-DD
    trading_class: str | None = None

    # 交易参数
    quantity: int = 0  # 正=买, 负=卖
    recommended_position_size: float | None = None  # 原始计算值
    limit_price: float | None = None
    price_type: str = "mid"  # "bid", "ask", "mid", "market"

    # 上下文
    account_state: AccountState | None = None
    position_context: PositionContext | None = None

    # 原因和触发
    reason: str = ""
    trigger_alerts: list[str] = field(default_factory=list)

    # 评分
    confidence_score: float | None = None
    expected_impact: dict[str, Any] = field(default_factory=dict)

    # 状态
    timestamp: datetime = field(default_factory=datetime.now)
    is_approved: bool = False
    approval_notes: str = ""

    # 目标券商
    broker: str = ""  # "ibkr" or "futu"

    # 合约参数
    contract_multiplier: int = 100  # 合约乘数 (US=100, HK 视标的而定)
    currency: str = "USD"  # 交易币种

    def approve(self, notes: str = "") -> None:
        """批准决策"""
        self.is_approved = True
        self.approval_notes = notes

    def reject(self, reason: str) -> None:
        """拒绝决策"""
        self.is_approved = False
        self.approval_notes = f"Rejected: {reason}"

    @property
    def is_opening(self) -> bool:
        """是否开仓决策"""
        return self.decision_type == DecisionType.OPEN

    @property
    def is_closing(self) -> bool:
        """是否平仓决策"""
        return self.decision_type in (DecisionType.CLOSE, DecisionType.ROLL)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典 (用于 JSON 序列化)"""
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "source": self.source.value,
            "priority": self.priority.value,
            "symbol": self.symbol,
            "underlying": self.underlying,
            "option_type": self.option_type,
            "strike": self.strike,
            "expiry": self.expiry,
            "trading_class": self.trading_class,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "price_type": self.price_type,
            "reason": self.reason,
            "trigger_alerts": self.trigger_alerts,
            "confidence_score": self.confidence_score,
            "timestamp": self.timestamp.isoformat(),
            "is_approved": self.is_approved,
            "approval_notes": self.approval_notes,
            "broker": self.broker,
        }
