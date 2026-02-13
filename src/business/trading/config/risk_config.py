"""
Risk Configuration - 风控配置

所有风控参数的唯一配置源。

配置层级:
- Layer 1: Account-Level (账户级别) - 决定是否可以开仓
- Layer 2: Position-Level (持仓级别) - 限制单标的暴露
- Layer 3: Order-Level (订单级别) - 验证单笔订单
- Emergency: 紧急平仓触发阈值

配置模式:
- LIVE: 使用 YAML 主配置（fallback 到 dataclass 默认值）
- BACKTEST: 自动合并 YAML backtest_overrides 节

配置文件: config/trading/risk.yaml
"""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from src.business.config.config_mode import ConfigMode
from src.business.config.config_utils import merge_overrides


@dataclass
class RiskConfig:
    """风控配置

    所有风控参数的唯一配置源。

    配置来源 (优先级高→低):
    1. BacktestConfig.risk_overrides (per-run 自定义覆盖)
    2. YAML backtest_overrides 节 (BACKTEST 模式自动合并)
    3. YAML 主配置节 (LIVE 基准值)
    4. dataclass 默认值 (代码 fallback)

    示例:
        # Live 模式 (从 YAML 加载)
        config = RiskConfig.load()

        # Backtest 模式 (YAML + backtest_overrides 合并)
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

    @classmethod
    def _apply_dict(cls, config: "RiskConfig", data: dict[str, Any]) -> "RiskConfig":
        """将字典中的值覆盖到 config 实例上（内部方法）"""
        risk_limits = data.get("risk_limits", data)
        valid_fields = {f.name for f in fields(cls) if not f.name.startswith("_")}
        for key, value in risk_limits.items():
            if key in valid_fields:
                setattr(config, key, value)
        return config

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        mode: ConfigMode = ConfigMode.LIVE,
    ) -> "RiskConfig":
        """从 YAML 文件加载配置

        Args:
            path: YAML 文件路径
            mode: 配置模式 (LIVE 或 BACKTEST)

        Returns:
            RiskConfig 实例
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # BACKTEST 模式：合并 YAML 中的 backtest_overrides
        if mode == ConfigMode.BACKTEST and "backtest_overrides" in data:
            data = merge_overrides(data, data["backtest_overrides"])

        return cls._apply_dict(cls(), data)

    @classmethod
    def load(cls, mode: ConfigMode = ConfigMode.LIVE) -> "RiskConfig":
        """加载配置

        优先从 YAML 加载，如果 YAML 不存在则使用 dataclass 默认值。

        Args:
            mode: 配置模式 (LIVE 或 BACKTEST)

        Returns:
            RiskConfig 实例
        """
        config_dir = Path(__file__).parent.parent.parent.parent.parent / "config" / "trading"
        config_file = config_dir / "risk.yaml"
        if config_file.exists():
            return cls.from_yaml(config_file, mode=mode)
        return cls()

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        mode: ConfigMode = ConfigMode.LIVE,
    ) -> "RiskConfig":
        """从字典创建配置

        支持两种场景：
        1. 完整 YAML 格式（含 backtest_overrides）→ 直接解析
        2. 部分覆盖字典（如 BacktestConfig.risk_overrides）→ 先加载 YAML 基线再叠加

        Args:
            data: 配置字典 (支持嵌套 risk_limits 或扁平结构)
            mode: 配置模式

        Returns:
            RiskConfig 实例
        """
        # 完整 YAML 格式：含 backtest_overrides，直接解析
        if "backtest_overrides" in data:
            if mode == ConfigMode.BACKTEST:
                data = merge_overrides(data, data["backtest_overrides"])
            return cls._apply_dict(cls(), data)

        # 部分覆盖字典：先加载 YAML 基线（含 mode 处理），再叠加
        base = cls.load(mode)
        return cls._apply_dict(base, data)

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
