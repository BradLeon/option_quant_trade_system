"""
Monitoring Configuration - 监控配置管理

加载和管理持仓监控系统的配置参数
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ThresholdRange:
    """阈值范围"""

    green: tuple[float, float] | None = None
    yellow: tuple[float, float] | None = None
    red_above: float | None = None
    red_below: float | None = None
    hysteresis: float = 0.0


@dataclass
class PortfolioThresholds:
    """组合级阈值"""

    beta_weighted_delta: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-100, 100),
            yellow=(-200, 200),
            red_above=300,
            red_below=-300,
            hysteresis=20,
        )
    )
    portfolio_vega: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-500, 500),
            yellow=(-1000, 1000),
            red_above=1500,
            red_below=-1500,
            hysteresis=100,
        )
    )
    portfolio_gamma: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-30, 0),
            yellow=(-50, 0),
            red_below=-50,
            hysteresis=5,
        )
    )
    tgr_green_above: float = 0.15
    tgr_yellow_range: tuple[float, float] = (0.05, 0.15)
    tgr_red_below: float = 0.05
    max_concentration: float = 1.5


@dataclass
class PositionThresholds:
    """持仓级阈值"""

    moneyness_green_above: float = 0.05
    moneyness_yellow_range: tuple[float, float] = (0.0, 0.05)
    moneyness_red_below: float = 0.0

    delta_red_above: float = 0.5
    delta_change_warning: float = 0.1

    gamma_green_below: float = 0.03
    gamma_yellow_range: tuple[float, float] = (0.03, 0.05)
    gamma_red_above: float = 0.05
    gamma_near_expiry_multiplier: float = 1.5

    iv_hv_favorable_above: float = 1.5
    iv_hv_unfavorable_below: float = 0.8

    prei_green_below: float = 40.0
    prei_yellow_range: tuple[float, float] = (40.0, 75.0)
    prei_red_above: float = 75.0

    dte_warning_days: int = 7
    dte_urgent_days: int = 3

    take_profit_pct: float = 0.50
    stop_loss_pct: float = -2.00


@dataclass
class CapitalThresholds:
    """资金级阈值"""

    sharpe_green_above: float = 1.5
    sharpe_yellow_range: tuple[float, float] = (1.0, 1.5)
    sharpe_red_below: float = 1.0

    kelly_usage_green_range: tuple[float, float] = (0.5, 1.0)
    kelly_usage_opportunity_below: float = 0.5
    kelly_usage_red_above: float = 1.0

    margin_green_below: float = 0.6
    margin_yellow_range: tuple[float, float] = (0.6, 0.8)
    margin_warning_above: float = 0.8
    margin_red_above: float = 0.9

    max_drawdown_warning_pct: float = 0.10
    max_drawdown_red_pct: float = 0.15


@dataclass
class DynamicAdjustment:
    """动态调整配置"""

    # 高波动率环境 (VIX > 28)
    high_vol_gamma_multiplier: float = 0.6
    high_vol_delta_multiplier: float = 0.8
    high_vol_kelly_multiplier: float = 0.5

    # 趋势环境 (ADX > 25)
    trending_counter_multiplier: float = 0.7
    trending_with_multiplier: float = 1.2

    # 震荡环境 (ADX < 20)
    ranging_gamma_multiplier: float = 1.3
    ranging_tgr_multiplier: float = 1.2


@dataclass
class MonitoringConfig:
    """监控配置"""

    portfolio: PortfolioThresholds = field(default_factory=PortfolioThresholds)
    position: PositionThresholds = field(default_factory=PositionThresholds)
    capital: CapitalThresholds = field(default_factory=CapitalThresholds)
    dynamic: DynamicAdjustment = field(default_factory=DynamicAdjustment)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MonitoringConfig":
        """从 YAML 文件加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitoringConfig":
        """从字典创建配置"""
        config = cls()

        if "portfolio_level" in data:
            pl = data["portfolio_level"]
            if "beta_weighted_delta" in pl:
                bwd = pl["beta_weighted_delta"]
                config.portfolio.beta_weighted_delta = ThresholdRange(
                    green=tuple(bwd.get("green", [-100, 100])),
                    yellow=tuple(bwd.get("yellow", [-200, 200])),
                    red_above=bwd.get("red_above", 300),
                    red_below=bwd.get("red_below", -300),
                    hysteresis=bwd.get("hysteresis", 20),
                )
            if "tgr" in pl:
                tgr = pl["tgr"]
                config.portfolio.tgr_green_above = tgr.get("green_above", 0.15)
                config.portfolio.tgr_yellow_range = tuple(
                    tgr.get("yellow_range", [0.05, 0.15])
                )
                config.portfolio.tgr_red_below = tgr.get("red_below", 0.05)
            if "correlation" in pl:
                config.portfolio.max_concentration = pl["correlation"].get(
                    "max_concentration", 1.5
                )

        if "position_level" in data:
            ps = data["position_level"]
            if "moneyness" in ps:
                m = ps["moneyness"]
                config.position.moneyness_green_above = m.get("green_above", 0.05)
                config.position.moneyness_yellow_range = tuple(
                    m.get("yellow_range", [0.0, 0.05])
                )
                config.position.moneyness_red_below = m.get("red_below", 0.0)
            if "delta" in ps:
                d = ps["delta"]
                config.position.delta_red_above = d.get("put_red_above", 0.5)
                config.position.delta_change_warning = d.get("change_warning", 0.1)
            if "gamma" in ps:
                g = ps["gamma"]
                config.position.gamma_green_below = g.get("green_below", 0.03)
                config.position.gamma_yellow_range = tuple(
                    g.get("yellow_range", [0.03, 0.05])
                )
                config.position.gamma_red_above = g.get("red_above", 0.05)
                config.position.gamma_near_expiry_multiplier = g.get(
                    "near_expiry_multiplier", 1.5
                )
            if "prei" in ps:
                p = ps["prei"]
                config.position.prei_green_below = p.get("green_below", 40)
                config.position.prei_yellow_range = tuple(
                    p.get("yellow_range", [40, 75])
                )
                config.position.prei_red_above = p.get("red_above", 75)
            if "dte" in ps:
                config.position.dte_warning_days = ps["dte"].get("warning_days", 7)
                config.position.dte_urgent_days = ps["dte"].get("urgent_days", 3)
            if "pnl" in ps:
                config.position.take_profit_pct = ps["pnl"].get("take_profit_pct", 0.5)
                config.position.stop_loss_pct = ps["pnl"].get("stop_loss_pct", -2.0)

        if "capital_level" in data:
            cl = data["capital_level"]
            if "sharpe_ratio" in cl:
                s = cl["sharpe_ratio"]
                config.capital.sharpe_green_above = s.get("green_above", 1.5)
                config.capital.sharpe_yellow_range = tuple(
                    s.get("yellow_range", [1.0, 1.5])
                )
                config.capital.sharpe_red_below = s.get("red_below", 1.0)
            if "kelly_usage" in cl:
                k = cl["kelly_usage"]
                config.capital.kelly_usage_green_range = tuple(
                    k.get("green_range", [0.5, 1.0])
                )
                config.capital.kelly_usage_opportunity_below = k.get(
                    "opportunity_below", 0.5
                )
                config.capital.kelly_usage_red_above = k.get("red_above", 1.0)
            if "margin_usage" in cl:
                m = cl["margin_usage"]
                config.capital.margin_green_below = m.get("green_below", 0.6)
                config.capital.margin_yellow_range = tuple(
                    m.get("yellow_range", [0.6, 0.8])
                )
                config.capital.margin_warning_above = m.get("warning_above", 0.8)
                config.capital.margin_red_above = m.get("red_above", 0.9)
            if "max_drawdown" in cl:
                md = cl["max_drawdown"]
                config.capital.max_drawdown_warning_pct = md.get("warning_pct", 0.10)
                config.capital.max_drawdown_red_pct = md.get("red_pct", 0.15)

        if "dynamic_adjustment" in data:
            da = data["dynamic_adjustment"]
            if "high_volatility" in da:
                hv = da["high_volatility"]
                config.dynamic.high_vol_gamma_multiplier = hv.get(
                    "gamma_multiplier", 0.6
                )
                config.dynamic.high_vol_delta_multiplier = hv.get(
                    "delta_multiplier", 0.8
                )
                config.dynamic.high_vol_kelly_multiplier = hv.get(
                    "kelly_multiplier", 0.5
                )
            if "trending" in da:
                t = da["trending"]
                config.dynamic.trending_counter_multiplier = t.get(
                    "counter_trend_multiplier", 0.7
                )
                config.dynamic.trending_with_multiplier = t.get(
                    "with_trend_multiplier", 1.2
                )
            if "ranging" in da:
                r = da["ranging"]
                config.dynamic.ranging_gamma_multiplier = r.get("gamma_multiplier", 1.3)
                config.dynamic.ranging_tgr_multiplier = r.get("tgr_multiplier", 1.2)

        return config

    @classmethod
    def load(cls) -> "MonitoringConfig":
        """加载默认配置"""
        config_dir = (
            Path(__file__).parent.parent.parent.parent / "config" / "monitoring"
        )
        config_file = config_dir / "thresholds.yaml"
        if config_file.exists():
            return cls.from_yaml(config_file)
        return cls()
