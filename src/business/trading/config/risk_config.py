"""
Risk Configuration - 风控配置

所有风控参数的唯一配置源。

配置层级:
- Layer 1: Account-Level (账户级别) - 决定是否可以开仓
- Layer 2: Position-Level (持仓级别) - 限制单标的暴露
- Layer 3: Order-Level (订单级别) - 验证单笔订单
- Emergency: 紧急平仓触发阈值

配置模式:
- LIVE: 使用严格的生产环境默认值
- BACKTEST: 应用 _BACKTEST_OVERRIDES 放宽某些参数
"""

from dataclasses import dataclass, fields
from typing import Any, ClassVar

from src.business.config.config_mode import ConfigMode


@dataclass
class RiskConfig:
    """风控配置

    所有风控参数的唯一配置源。

    配置来源 (优先级高→低):
    - LIVE 模式: dataclass 默认值
    - BACKTEST 模式: _BACKTEST_OVERRIDES > dataclass 默认值

    示例:
        # Live 模式 (严格默认值)
        config = RiskConfig.load()

        # Backtest 模式 (放宽参数)
        config = RiskConfig.load(mode=ConfigMode.BACKTEST)

        # 从字典加载 (可覆盖任意字段)
        config = RiskConfig.from_dict({"max_notional_pct_per_underlying": 0.70})
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

    # =========================================================================
    # Backtest Overrides (回测模式覆盖值)
    # 这些值在 BACKTEST 模式下会覆盖上面的默认值
    # =========================================================================

    _BACKTEST_OVERRIDES: ClassVar[dict[str, Any]] = {
        # 放宽单标的敞口限制，便于回测测试
        "max_notional_pct_per_underlying": 0.50,  # 50% (live: 5%)
    }

    @classmethod
    def load(cls, mode: ConfigMode = ConfigMode.LIVE) -> "RiskConfig":
        """加载配置

        Args:
            mode: 配置模式 (LIVE 或 BACKTEST)

        Returns:
            RiskConfig 实例
        """
        if mode == ConfigMode.LIVE:
            # Live 模式: 使用 dataclass 默认值 (严格)
            return cls()
        else:
            # Backtest 模式: 应用 backtest 覆盖
            return cls(**cls._BACKTEST_OVERRIDES)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        mode: ConfigMode = ConfigMode.LIVE,
    ) -> "RiskConfig":
        """从字典创建配置

        Args:
            data: 配置字典 (支持嵌套 risk_limits 或扁平结构)
            mode: 配置模式

        Returns:
            RiskConfig 实例
        """
        # 先获取基础配置
        base = cls.load(mode)

        # 支持嵌套结构 (risk_limits) 和扁平结构
        risk_limits = data.get("risk_limits", data)

        # 用字典中的值覆盖
        valid_fields = {f.name for f in fields(cls) if not f.name.startswith("_")}
        for key, value in risk_limits.items():
            if key in valid_fields:
                setattr(base, key, value)

        return base

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
