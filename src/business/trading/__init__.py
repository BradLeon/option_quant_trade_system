"""
Trading Module - 自动化交易模块

实现信号到订单的闭环:
- Decision Engine: 信号接收、账户分析、仓位计算、冲突解决
- Order Manager: 订单生成、风控验证、执行跟踪、持久化
- Trading Provider: 统一的券商交易接口 (PAPER TRADING ONLY)

⚠️  CRITICAL: 本模块仅支持 Paper Trading (模拟账户)
"""

from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
    TradingDecision,
)
from src.business.trading.models.order import (
    AssetClass,
    OrderFill,
    OrderRecord,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskCheckResult,
)
from src.business.trading.models.trading import (
    AccountTypeError,
    CancelResult,
    OrderQueryResult,
    TradingAccountType,
    TradingProviderError,
    TradingResult,
)

__all__ = [
    # Decision models
    "DecisionType",
    "DecisionSource",
    "DecisionPriority",
    "AccountState",
    "PositionContext",
    "TradingDecision",
    # Order models
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "AssetClass",
    "OrderRequest",
    "OrderFill",
    "OrderRecord",
    "RiskCheckResult",
    # Trading models
    "TradingAccountType",
    "TradingProviderError",
    "AccountTypeError",
    "TradingResult",
    "OrderQueryResult",
    "CancelResult",
]
