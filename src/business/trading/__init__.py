"""Trading Module - V2 交易模块

Signal → RiskGuard chain → SignalOrderBuilder → OrderRequest
  → OrderValidator → TradingProvider → OrderRecord

⚠️  CRITICAL: 本模块仅支持 Paper Trading (模拟账户)
"""

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

# Backward compat — decision models still importable from here
from src.business.trading.models.decision import (  # noqa: F401
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
    TradingDecision,
)

__all__ = [
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
    # Backward compat — decision models
    "DecisionType",
    "DecisionSource",
    "DecisionPriority",
    "AccountState",
    "PositionContext",
    "TradingDecision",
]
