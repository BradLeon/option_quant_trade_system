"""
Risk Configuration - 风控配置

加载和管理风控的配置参数。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RiskConfig:
    """风控配置

    定义多层风控的阈值参数。
    """

    # === Account-Level Limits (Layer 1) ===
    # 用于决策引擎判断是否可以开仓

    max_margin_utilization: float = 0.70  # 70%
    min_cash_ratio: float = 0.10  # 10%
    max_gross_leverage: float = 4.0  # 4x
    max_stress_test_loss: float = 0.20  # 20%

    # === Position-Level Limits (Layer 2) ===
    # 用于决策引擎限制单标的暴露

    max_contracts_per_underlying: int = 10
    max_notional_pct_per_underlying: float = 0.05  # 5% of NLV
    max_total_option_positions: int = 20
    max_concentration_pct: float = 0.20  # 20% in single underlying

    # === Order-Level Limits (Layer 3) ===
    # 用于订单管理器验证订单

    max_projected_margin_utilization: float = 0.80  # 80% after order
    max_price_deviation_pct: float = 0.05  # 5% from mid
    max_order_value_pct: float = 0.10  # 10% of NLV per order

    # === 保证金估算参数 ===
    # 基于 IBKR Reg T 规则
    # 参考: https://www.interactivebrokers.com/en/trading/margin-options.php
    # Naked short option: Premium + Max((X% * Underlying - OTM), (10% * Strike))
    margin_rate_stock_option: float = 0.20  # 股票期权: 20% of underlying
    margin_rate_index_option: float = 0.15  # 指数期权: 15% of underlying
    margin_rate_minimum: float = 0.10  # 最低保证金率: 10% of strike

    # === Emergency Thresholds ===
    # 紧急平仓触发阈值

    emergency_margin_utilization: float = 0.85  # 85%
    emergency_cash_ratio: float = 0.05  # 5%

    # === Kelly Fraction ===
    kelly_fraction: float = 0.25  # 1/4 Kelly

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "RiskConfig":
        """从 YAML 文件加载配置"""
        if config_path is None:
            config_path = Path("config/trading/risk.yaml")
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskConfig":
        """从字典创建配置"""
        # 支持嵌套结构和扁平结构
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
                "max_total_option_positions", 20
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
                "max_margin_utilization": self.max_margin_utilization,
                "min_cash_ratio": self.min_cash_ratio,
                "max_gross_leverage": self.max_gross_leverage,
                "max_stress_test_loss": self.max_stress_test_loss,
                "max_contracts_per_underlying": self.max_contracts_per_underlying,
                "max_notional_pct_per_underlying": self.max_notional_pct_per_underlying,
                "max_total_option_positions": self.max_total_option_positions,
                "max_concentration_pct": self.max_concentration_pct,
                "max_projected_margin_utilization": self.max_projected_margin_utilization,
                "max_price_deviation_pct": self.max_price_deviation_pct,
                "max_order_value_pct": self.max_order_value_pct,
                "margin_rate_stock_option": self.margin_rate_stock_option,
                "margin_rate_index_option": self.margin_rate_index_option,
                "margin_rate_minimum": self.margin_rate_minimum,
                "emergency_margin_utilization": self.emergency_margin_utilization,
                "emergency_cash_ratio": self.emergency_cash_ratio,
                "kelly_fraction": self.kelly_fraction,
            }
        }
