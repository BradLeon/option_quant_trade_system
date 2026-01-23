"""Engine layer enumerations.

Centralized location for all enums used in the engine layer.
"""

from enum import Enum


class TrendSignal(Enum):
    """Market trend signal."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class RatingSignal(Enum):
    """Analyst rating signal."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class VixZone(Enum):
    """VIX volatility zones."""

    LOW = "low"  # VIX < 15: Market complacency
    NORMAL = "normal"  # VIX 15-20: Normal conditions
    ELEVATED = "elevated"  # VIX 20-25: Increased uncertainty
    HIGH = "high"  # VIX 25-35: Fear/panic
    EXTREME = "extreme"  # VIX > 35: Extreme fear


class PositionSide(Enum):
    """Position side enumeration."""

    LONG = "long"  # Buy
    SHORT = "short"  # Sell


class TermStructure(Enum):
    """VIX term structure state.

    Term structure = VIX / VIX3M ratio:
    - CONTANGO: VIX < VIX3M (normal market, short-term vol lower)
    - FLAT: VIX ≈ VIX3M (transition state)
    - BACKWARDATION: VIX > VIX3M (stressed market, short-term vol higher)
    """

    CONTANGO = "contango"
    FLAT = "flat"
    BACKWARDATION = "backwardation"


class MarketType(Enum):
    """Market type for sentiment analysis."""

    US = "us"
    HK = "hk"


class StrategyType(str, Enum):
    """期权策略类型枚举

    继承 str 确保 JSON 序列化兼容性：
    - StrategyType.SHORT_PUT.value == "short_put"
    - str(StrategyType.SHORT_PUT) == "short_put"

    策略类型说明:
    - SHORT_PUT: 裸卖 Put（核心策略）
    - COVERED_CALL: 备兑 Call（核心策略）
    - PARTIAL_COVERED_CALL: 部分备兑 Call
    - NAKED_CALL: 裸卖 Call
    - SHORT_STRANGLE: 宽跨式（同时卖 Put 和 Call）
    - UNKNOWN: 未知策略
    - NOT_OPTION: 非期权持仓
    """

    SHORT_PUT = "short_put"
    COVERED_CALL = "covered_call"
    PARTIAL_COVERED_CALL = "partial_covered_call"
    NAKED_CALL = "naked_call"
    SHORT_STRANGLE = "short_strangle"
    UNKNOWN = "unknown"
    NOT_OPTION = "not_option"

    @classmethod
    def from_string(cls, value: str | None) -> "StrategyType":
        """从字符串安全转换

        Args:
            value: 策略类型字符串

        Returns:
            对应的 StrategyType 枚举值，无效值返回 UNKNOWN
        """
        if not value:
            return cls.UNKNOWN
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN
