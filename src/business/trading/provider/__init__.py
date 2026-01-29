"""Trading Providers - 交易提供者

提供统一的券商交易接口。

⚠️  CRITICAL: 仅支持 Paper Trading (模拟账户)
"""

from src.business.trading.provider.base import TradingProvider

__all__ = [
    "TradingProvider",
]
