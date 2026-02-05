"""
Risk Configuration - 风控配置

所有风控参数的唯一配置源。

配置层级:
- Layer 1: Account-Level (账户级别) - 决定是否可以开仓
- Layer 2: Position-Level (持仓级别) - 限制单标的暴露
- Layer 3: Order-Level (订单级别) - 验证单笔订单
- Emergency: 紧急平仓触发阈值
"""

import os
from dataclasses import dataclass
from typing import Any


def _env_float(key: str, default: float) -> float:
    """从环境变量获取 float，支持覆盖默认值"""
    val = os.getenv(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _env_int(key: str, default: int) -> int:
    """从环境变量获取 int，支持覆盖默认值"""
    val = os.getenv(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


@dataclass
class RiskConfig:
    """风控配置

    所有风控参数的唯一配置源。
    支持通过环境变量覆盖默认值 (前缀: RISK_)

    示例:
        export RISK_MAX_MARGIN_UTILIZATION=0.60
        export RISK_KELLY_FRACTION=0.20
    """

    # =========================================================================
    # Layer 1: Account-Level Limits (账户级别限制)
    # 用于 DecisionEngine 判断是否可以开仓
    # =========================================================================

    max_margin_utilization: float = 0.70  # 70% - 超过则禁止开仓
    min_cash_ratio: float = 0.10  # 10% - 低于则禁止开仓
    max_gross_leverage: float = 4.0  # 4x - 超过则禁止开仓
    max_stress_test_loss: float = 0.20  # 20% - 压力测试最大损失

    # =========================================================================
    # Layer 2: Position-Level Limits (持仓级别限制)
    # 用于 DecisionEngine/PositionSizer 限制单标的暴露
    # =========================================================================

    max_contracts_per_underlying: int = 10  # 单标的最大合约数
    max_notional_pct_per_underlying: float = 0.10  # 5% of NLV - 单标的最大名义价值占比
    max_total_option_positions: int = 100  # 期权持仓总数上限
    max_concentration_pct: float = 0.20  # 20% - 单标的最大集中度

    # =========================================================================
    # Layer 3: Order-Level Limits (订单级别限制)
    # 用于 RiskChecker/OrderManager 验证订单
    # =========================================================================

    max_projected_margin_utilization: float = 0.80  # 80% - 开仓后预计保证金使用率上限
    max_price_deviation_pct: float = 0.05  # 5% - 价格偏离中间价上限
    max_order_value_pct: float = 0.10  # 10% of NLV - 单笔订单最大价值占比

    # =========================================================================
    # Margin Estimation (保证金估算参数)
    # 基于 IBKR Reg T 规则
    # Naked short option: Premium + Max((X% * Underlying - OTM), (10% * Strike))
    # =========================================================================

    margin_rate_stock_option: float = 0.20  # 股票期权: 20% of underlying
    margin_rate_index_option: float = 0.15  # 指数期权: 15% of underlying
    margin_rate_minimum: float = 0.10  # 最低保证金率: 10% of strike
    margin_safety_buffer: float = 0.80  # 只使用 80% 可用保证金

    # =========================================================================
    # Emergency Thresholds (紧急平仓触发阈值)
    # =========================================================================

    emergency_margin_utilization: float = 0.85  # 85% - 触发紧急平仓
    emergency_cash_ratio: float = 0.05  # 5% - 触发紧急平仓

    # =========================================================================
    # Kelly Criterion (凯利公式参数)
    # =========================================================================

    kelly_fraction: float = 0.25  # 1/4 Kelly - 保守策略

    @classmethod
    def load(cls) -> "RiskConfig":
        """加载配置

        优先级: 环境变量 > 默认值
        """
        return cls(
            # Layer 1
            max_margin_utilization=_env_float(
                "RISK_MAX_MARGIN_UTILIZATION", 0.70
            ),
            min_cash_ratio=_env_float("RISK_MIN_CASH_RATIO", 0.10),
            max_gross_leverage=_env_float("RISK_MAX_GROSS_LEVERAGE", 4.0),
            max_stress_test_loss=_env_float("RISK_MAX_STRESS_TEST_LOSS", 0.20),
            # Layer 2
            max_contracts_per_underlying=_env_int(
                "RISK_MAX_CONTRACTS_PER_UNDERLYING", 10
            ),
            max_notional_pct_per_underlying=_env_float(
                "RISK_MAX_NOTIONAL_PCT_PER_UNDERLYING", 0.05
            ),
            max_total_option_positions=_env_int(
                "RISK_MAX_TOTAL_OPTION_POSITIONS", 20
            ),
            max_concentration_pct=_env_float("RISK_MAX_CONCENTRATION_PCT", 0.20),
            # Layer 3
            max_projected_margin_utilization=_env_float(
                "RISK_MAX_PROJECTED_MARGIN_UTILIZATION", 0.80
            ),
            max_price_deviation_pct=_env_float(
                "RISK_MAX_PRICE_DEVIATION_PCT", 0.05
            ),
            max_order_value_pct=_env_float("RISK_MAX_ORDER_VALUE_PCT", 0.10),
            # Margin
            margin_rate_stock_option=_env_float(
                "RISK_MARGIN_RATE_STOCK_OPTION", 0.20
            ),
            margin_rate_index_option=_env_float(
                "RISK_MARGIN_RATE_INDEX_OPTION", 0.15
            ),
            margin_rate_minimum=_env_float("RISK_MARGIN_RATE_MINIMUM", 0.10),
            margin_safety_buffer=_env_float("RISK_MARGIN_SAFETY_BUFFER", 0.80),
            # Emergency
            emergency_margin_utilization=_env_float(
                "RISK_EMERGENCY_MARGIN_UTILIZATION", 0.85
            ),
            emergency_cash_ratio=_env_float("RISK_EMERGENCY_CASH_RATIO", 0.05),
            # Kelly
            kelly_fraction=_env_float("RISK_KELLY_FRACTION", 0.25),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskConfig":
        """从字典创建配置 (用于测试)"""
        # 支持嵌套结构 (risk_limits) 和扁平结构
        risk_limits = data.get("risk_limits", data)

        return cls(
            max_margin_utilization=risk_limits.get("max_margin_utilization", 0.70),
            min_cash_ratio=risk_limits.get("min_cash_ratio", 0.10),
            max_gross_leverage=risk_limits.get("max_gross_leverage", 4.0),
            max_stress_test_loss=risk_limits.get("max_stress_test_loss", 0.20),
            max_contracts_per_underlying=risk_limits.get(
                "max_contracts_per_underlying", 10
            ),
            max_notional_pct_per_underlying=risk_limits.get(
                "max_notional_pct_per_underlying", 0.05
            ),
            max_total_option_positions=risk_limits.get(
                "max_total_option_positions", 100
            ),
            max_concentration_pct=risk_limits.get("max_concentration_pct", 0.20),
            max_projected_margin_utilization=risk_limits.get(
                "max_projected_margin_utilization", 0.80
            ),
            max_price_deviation_pct=risk_limits.get("max_price_deviation_pct", 0.05),
            max_order_value_pct=risk_limits.get("max_order_value_pct", 0.10),
            margin_rate_stock_option=risk_limits.get("margin_rate_stock_option", 0.20),
            margin_rate_index_option=risk_limits.get("margin_rate_index_option", 0.15),
            margin_rate_minimum=risk_limits.get("margin_rate_minimum", 0.10),
            margin_safety_buffer=risk_limits.get("margin_safety_buffer", 0.80),
            emergency_margin_utilization=risk_limits.get(
                "emergency_margin_utilization", 0.85
            ),
            emergency_cash_ratio=risk_limits.get("emergency_cash_ratio", 0.05),
            kelly_fraction=risk_limits.get("kelly_fraction", 0.25),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "risk_limits": {
                # Layer 1
                "max_margin_utilization": self.max_margin_utilization,
                "min_cash_ratio": self.min_cash_ratio,
                "max_gross_leverage": self.max_gross_leverage,
                "max_stress_test_loss": self.max_stress_test_loss,
                # Layer 2
                "max_contracts_per_underlying": self.max_contracts_per_underlying,
                "max_notional_pct_per_underlying": self.max_notional_pct_per_underlying,
                "max_total_option_positions": self.max_total_option_positions,
                "max_concentration_pct": self.max_concentration_pct,
                # Layer 3
                "max_projected_margin_utilization": self.max_projected_margin_utilization,
                "max_price_deviation_pct": self.max_price_deviation_pct,
                "max_order_value_pct": self.max_order_value_pct,
                # Margin
                "margin_rate_stock_option": self.margin_rate_stock_option,
                "margin_rate_index_option": self.margin_rate_index_option,
                "margin_rate_minimum": self.margin_rate_minimum,
                "margin_safety_buffer": self.margin_safety_buffer,
                # Emergency
                "emergency_margin_utilization": self.emergency_margin_utilization,
                "emergency_cash_ratio": self.emergency_cash_ratio,
                # Kelly
                "kelly_fraction": self.kelly_fraction,
            }
        }
