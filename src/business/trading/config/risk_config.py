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
from dataclasses import dataclass, fields
from typing import Any


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
    max_notional_pct_per_underlying: float = 0.05  # 5% of NLV - 单标的最大名义价值占比
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

    # 环境变量名映射 (字段名 -> 环境变量名)
    _ENV_PREFIX = "RISK_"

    @classmethod
    def load(cls) -> "RiskConfig":
        """加载配置

        优先级: 环境变量 > dataclass 字段默认值
        环境变量命名规则: RISK_ + 字段名大写，如 RISK_MAX_TOTAL_OPTION_POSITIONS
        """
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            env_key = f"{cls._ENV_PREFIX}{f.name.upper()}"
            val = os.getenv(env_key)
            if val is not None:
                try:
                    kwargs[f.name] = f.type(val) if callable(f.type) else float(val)
                except (ValueError, TypeError):
                    pass
        return cls(**kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskConfig":
        """从字典创建配置 (用于测试)

        只覆盖字典中存在的字段，缺失字段使用 dataclass 默认值。
        """
        # 支持嵌套结构 (risk_limits) 和扁平结构
        risk_limits = data.get("risk_limits", data)
        valid_fields = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in risk_limits.items() if k in valid_fields}
        return cls(**kwargs)

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
