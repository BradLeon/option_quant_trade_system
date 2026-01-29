"""
Decision Configuration - 决策引擎配置

只包含决策逻辑特有的配置。
风控参数统一使用 RiskConfig。
"""

import os
from dataclasses import dataclass, field
from typing import Any

from src.business.trading.config.risk_config import RiskConfig


def _env_str(key: str, default: str) -> str:
    """从环境变量获取 str"""
    return os.getenv(key, default)


def _env_bool(key: str, default: bool) -> bool:
    """从环境变量获取 bool"""
    val = os.getenv(key)
    if val is not None:
        return val.lower() in ("true", "1", "yes")
    return default


@dataclass
class DecisionConfig:
    """决策引擎配置

    组合 RiskConfig + 决策逻辑特有配置。
    风控参数通过 risk 属性访问。

    Usage:
        config = DecisionConfig.load()
        # 访问风控参数
        max_margin = config.risk.max_margin_utilization
        # 访问决策配置
        broker = config.default_broker
    """

    # =========================================================================
    # 风控配置 (委托给 RiskConfig)
    # =========================================================================

    risk: RiskConfig = field(default_factory=RiskConfig.load)

    # =========================================================================
    # 决策逻辑配置
    # =========================================================================

    # 冲突解决策略
    close_before_open: bool = True  # 平仓优先于开仓
    single_action_per_underlying: bool = True  # 同一标的只允许一个动作

    # 默认券商
    default_broker: str = "ibkr"  # ibkr or futu

    # 价格类型
    default_price_type: str = "mid"  # bid, ask, mid, market

    # =========================================================================
    # 风控参数的便捷访问 (向后兼容)
    # =========================================================================

    @property
    def kelly_fraction(self) -> float:
        return self.risk.kelly_fraction

    @property
    def max_margin_utilization(self) -> float:
        return self.risk.max_margin_utilization

    @property
    def min_cash_ratio(self) -> float:
        return self.risk.min_cash_ratio

    @property
    def max_gross_leverage(self) -> float:
        return self.risk.max_gross_leverage

    @property
    def max_projected_margin_utilization(self) -> float:
        return self.risk.max_projected_margin_utilization

    @property
    def max_contracts_per_underlying(self) -> int:
        return self.risk.max_contracts_per_underlying

    @property
    def max_notional_pct_per_underlying(self) -> float:
        return self.risk.max_notional_pct_per_underlying

    @property
    def max_total_option_positions(self) -> int:
        return self.risk.max_total_option_positions

    @property
    def margin_rate_stock_option(self) -> float:
        return self.risk.margin_rate_stock_option

    @property
    def margin_rate_index_option(self) -> float:
        return self.risk.margin_rate_index_option

    @property
    def margin_rate_minimum(self) -> float:
        return self.risk.margin_rate_minimum

    @property
    def margin_safety_buffer(self) -> float:
        return self.risk.margin_safety_buffer

    @classmethod
    def load(cls) -> "DecisionConfig":
        """加载配置

        优先级: 环境变量 > 默认值
        """
        return cls(
            risk=RiskConfig.load(),
            close_before_open=_env_bool("DECISION_CLOSE_BEFORE_OPEN", True),
            single_action_per_underlying=_env_bool(
                "DECISION_SINGLE_ACTION_PER_UNDERLYING", True
            ),
            default_broker=_env_str("DECISION_DEFAULT_BROKER", "ibkr"),
            default_price_type=_env_str("DECISION_DEFAULT_PRICE_TYPE", "mid"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionConfig":
        """从字典创建配置 (用于测试)"""
        # 如果包含风控参数，传递给 RiskConfig
        risk = RiskConfig.from_dict(data)

        return cls(
            risk=risk,
            close_before_open=data.get("close_before_open", True),
            single_action_per_underlying=data.get("single_action_per_underlying", True),
            default_broker=data.get("default_broker", "ibkr"),
            default_price_type=data.get("default_price_type", "mid"),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        result = self.risk.to_dict()
        result.update({
            "close_before_open": self.close_before_open,
            "single_action_per_underlying": self.single_action_per_underlying,
            "default_broker": self.default_broker,
            "default_price_type": self.default_price_type,
        })
        return result
