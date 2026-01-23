"""
Decision Configuration - 决策引擎配置

加载和管理决策引擎的配置参数。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DecisionConfig:
    """决策引擎配置"""

    # Kelly 仓位计算
    kelly_fraction: float = 0.25  # 使用 1/4 Kelly

    # 账户级别限制
    max_margin_utilization: float = 0.70  # 70%
    min_cash_ratio: float = 0.05  # 10%
    max_gross_leverage: float = 4.0  # 4x

    # 持仓级别限制
    max_contracts_per_underlying: int = 10
    max_notional_pct_per_underlying: float = 0.05  # 5% of NLV
    max_total_option_positions: int = 20

    # 冲突解决
    close_before_open: bool = True  # 平仓优先于开仓
    single_action_per_underlying: bool = True  # 同一标的只允许一个动作

    # 默认券商
    default_broker: str = "ibkr"

    # 价格类型
    default_price_type: str = "mid"  # bid, ask, mid, market

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "DecisionConfig":
        """从 YAML 文件加载配置

        Args:
            config_path: 配置文件路径，默认为 config/trading/decision.yaml

        Returns:
            DecisionConfig 实例
        """
        if config_path is None:
            config_path = Path("config/trading/decision.yaml")
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionConfig":
        """从字典创建配置"""
        return cls(
            kelly_fraction=data.get("kelly_fraction", 0.25),
            max_margin_utilization=data.get("max_margin_utilization", 0.70),
            min_cash_ratio=data.get("min_cash_ratio", 0.10),
            max_gross_leverage=data.get("max_gross_leverage", 4.0),
            max_contracts_per_underlying=data.get("max_contracts_per_underlying", 10),
            max_notional_pct_per_underlying=data.get(
                "max_notional_pct_per_underlying", 0.05
            ),
            max_total_option_positions=data.get("max_total_option_positions", 20),
            close_before_open=data.get("close_before_open", True),
            single_action_per_underlying=data.get("single_action_per_underlying", True),
            default_broker=data.get("default_broker", "ibkr"),
            default_price_type=data.get("default_price_type", "mid"),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "kelly_fraction": self.kelly_fraction,
            "max_margin_utilization": self.max_margin_utilization,
            "min_cash_ratio": self.min_cash_ratio,
            "max_gross_leverage": self.max_gross_leverage,
            "max_contracts_per_underlying": self.max_contracts_per_underlying,
            "max_notional_pct_per_underlying": self.max_notional_pct_per_underlying,
            "max_total_option_positions": self.max_total_option_positions,
            "close_before_open": self.close_before_open,
            "single_action_per_underlying": self.single_action_per_underlying,
            "default_broker": self.default_broker,
            "default_price_type": self.default_price_type,
        }
