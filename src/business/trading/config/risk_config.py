"""
Risk Configuration - 风控配置

所有风控参数的唯一配置源。

三层风控 + 紧急平仓:
- Signal-Level: AccountRiskGuard — 信号入场前过滤
- Order-Level: RiskChecker — 订单提交前验证
- Daily Limits: DailyTradeTracker — 每日交易限额
- Emergency: 紧急平仓触发阈值 (预留)

配置文件: config/trading/base_option_strategy.yaml
"""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from src.business.config.config_utils import merge_overrides


@dataclass
class RiskConfig:
    """风控配置 — 唯一配置源。

    配置来源 (优先级高→低):
    1. {strategy_name}.yaml (如果存在)
    2. base_option_strategy.yaml (默认基准值)
    3. dataclass 默认值 (代码 fallback)

    示例:
        config = RiskConfig.load("short_put_v9")
        config = RiskConfig.from_dict({"max_positions": 10})
    """

    # =========================================================================
    # Signal-Level Limits (信号级限制)
    # 消费者: AccountRiskGuard — ENTRY 信号入场前过滤
    # =========================================================================

    max_positions: int = 20               # 最大持仓数
    max_margin_utilization: float = 0.70  # 70% - margin 超过则禁止入场
    min_cash_reserve_pct: float = 0.05    # 股票入场: 最低现金比例
    min_available_margin: float = 10_000  # 期权入场: 最低可用保证金

    # =========================================================================
    # Order-Level Limits (订单级别限制)
    # 消费者: RiskChecker — 订单提交前验证
    # =========================================================================

    max_projected_margin_utilization: float = 0.80  # 80% - 开仓后预估 margin 上限
    max_price_deviation_pct: float = 0.05           # 5% - 价格偏离中间价上限
    max_order_value_pct: float = 0.10               # 10% of NLV - 单笔订单最大价值占比

    # Margin Estimation (IBKR Reg T)
    margin_rate_stock_option: float = 0.20  # 股票期权: 20% of underlying
    margin_rate_index_option: float = 0.15  # 指数期权: 15% of underlying
    margin_rate_minimum: float = 0.10       # 最低保证金率: 10% of strike
    margin_safety_buffer: float = 0.80      # 只使用 80% 可用保证金

    # =========================================================================
    # Daily Limits (每日交易限额)
    # 消费者: DailyTradeTracker
    # =========================================================================

    daily_limits_enabled: bool = True
    daily_max_open_qty_per_underlying: int = 5
    daily_max_close_qty_per_underlying: int = 5
    daily_max_roll_qty_per_underlying: int = 5
    daily_max_value_pct_per_underlying: float = 10.0  # 单标的每日市值上限 (% of NLV)
    daily_max_total_value_pct: float = 25.0           # 全账户每日总市值上限 (% of NLV)

    # =========================================================================
    # Emergency Thresholds (紧急平仓触发阈值, 预留)
    # =========================================================================

    emergency_margin_utilization: float = 0.85  # 85% - 触发紧急平仓
    emergency_cash_ratio: float = 0.05          # 5% - 触发紧急平仓

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
    ) -> "RiskConfig":
        """从 YAML 文件加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls._apply_dict(cls(), data)

    @classmethod
    def load(cls, strategy_name: str | None = None) -> "RiskConfig":
        """加载配置

        优先加载 base_option_strategy.yaml，然后被具体的 {strategy_name}.yaml 覆盖。
        """
        config_dir = Path(__file__).parent.parent.parent.parent.parent / "config" / "trading"

        # 1. 尝试加载基础配置
        base_file = config_dir / "base_option_strategy.yaml"
        base_data = {}
        if base_file.exists():
            with open(base_file, "r", encoding="utf-8") as f:
                base_data = yaml.safe_load(f) or {}

        # 2. 尝试加载策略专属的覆盖配置
        if strategy_name:
            strategy_file = config_dir / f"{strategy_name}.yaml"
            if strategy_file.exists():
                with open(strategy_file, "r", encoding="utf-8") as f:
                    strategy_data = yaml.safe_load(f) or {}
                base_data = merge_overrides(base_data, strategy_data)

        # 3. 如果没找到专属和基础配置，兼容查一下历史的 risk.yaml
        if not base_data:
            legacy_file = config_dir / "risk.yaml"
            if legacy_file.exists():
                with open(legacy_file, "r", encoding="utf-8") as f:
                    base_data = yaml.safe_load(f) or {}

        # 4. 应用最终字典
        return cls._apply_dict(cls(), base_data)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "RiskConfig":
        """从字典创建配置 (用于测试与覆盖)"""
        return cls._apply_dict(cls(), data)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "risk_limits": {f.name: getattr(self, f.name) for f in fields(self)}
        }
