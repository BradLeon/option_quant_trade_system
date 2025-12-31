"""
Monitoring Configuration - 监控配置管理

加载和管理持仓监控系统的配置参数

## Portfolio 级阈值配置参考

| 指标                | 绿色（正常）  | 黄色（关注）   | 红色（风险）      | 说明                  | RED 建议操作                          |
|---------------------|---------------|----------------|-------------------|-----------------------|---------------------------------------|
| Beta Weighted Delta | (-100, 100)   | (-200, 200)    | >300 或 <-300     | SPY 等效股数          | 减少多/空头 Delta 暴露或对冲          |
| Portfolio Theta     | ≥0            | (-50, 0)       | <-100             | 日 theta 收入（美元） | 减少买方头寸或增加卖方头寸            |
| Portfolio Vega      | (-500, 500)   | (-1000, 1000)  | >1500 或 <-1500   | IV 变化 1% 的损益     | 减少 Vega 暴露 / Vega 空头过大        |
| Portfolio Gamma     | (-30, 0)      | (-50, -30)     | <-50              | Gamma 空头风险        | Gamma 空头风险高，大幅波动时亏损加速  |
| TGR                 | ≥0.15         | (0.05, 0.15)   | <0.05             | Theta/Gamma 效率      | 时间衰减效率不足，考虑调整持仓        |
| HHI                 | <0.25         | (0.25, 0.5)    | >0.5              | 集中度指数            | 分散持仓，降低单一标的风险            |

## Position 级阈值配置参考

| 指标       | 绿色（正常） | 黄色（关注）  | 红色（风险） | 说明              |
|------------|--------------|---------------|--------------|-------------------|
| Moneyness  | >0.05        | (0, 0.05)     | <0 (ITM)     | (S-K)/K 虚值程度  |
| PREI       | <40          | (40, 75)      | >75          | 风险暴露指数      |
| DTE        | >7           | (3, 7)        | ≤3           | 到期天数          |
| P&L        | -            | -             | <-200%       | 止损线            |

## Capital 级阈值配置参考

| 指标         | 绿色（正常） | 黄色（关注）  | 红色（风险） | 说明           |
|--------------|--------------|---------------|--------------|----------------|
| Sharpe Ratio | ≥1.5         | (1.0, 1.5)    | <1.0         | 风险调整收益   |
| Kelly Usage  | (0.5, 1.0)   | <0.5 或 >1.0  | >1.0         | 仓位/最优仓位  |
| Margin Usage | <0.6         | (0.6, 0.8)    | >0.9         | 保证金使用率   |
| Drawdown     | <0.10        | (0.10, 0.15)  | >0.15        | 回撤比例       |
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# TODO, 好好检查这里的阈值的合理性。

@dataclass
class ThresholdRange:
    """阈值范围 - 支持配置化消息

    Attributes:
        green: 绿色（正常）范围
        yellow: 黄色（关注）范围
        red_above: 红色上限阈值
        red_below: 红色下限阈值
        hysteresis: 滞后值（防止频繁切换）
        alert_type: AlertType 枚举名（用于创建 Alert）
        red_above_message: 超上限消息模板（支持 {value}, {threshold}）
        red_below_message: 超下限消息模板
        yellow_message: 黄色预警消息模板
        red_above_action: 超上限建议操作
        red_below_action: 超下限建议操作
        yellow_action: 黄色预警建议操作
    """

    # 阈值定义
    green: tuple[float, float] | None = None
    yellow: tuple[float, float] | None = None
    red_above: float | None = None
    red_below: float | None = None
    hysteresis: float = 0.0

    # 配置化消息
    alert_type: str = ""
    red_above_message: str = ""
    red_below_message: str = ""
    yellow_message: str = ""
    red_above_action: str = ""
    red_below_action: str = ""
    yellow_action: str = ""


@dataclass
class PortfolioThresholds:
    """组合级阈值 - 统一使用 ThresholdRange"""

    beta_weighted_delta: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-100, 100),
            yellow=(-200, 200),
            red_above=300,
            red_below=-300,
            hysteresis=20,
            alert_type="DELTA_EXPOSURE",
            red_above_message="Beta 加权 Delta 过高: {value:.0f} > {threshold}",
            red_below_message="Beta 加权 Delta 过低: {value:.0f} < {threshold}",
            yellow_message="Beta 加权 Delta 偏离中性: {value:.0f}",
            red_above_action="减少多头 Delta 暴露或对冲",
            red_below_action="减少空头 Delta 暴露或对冲",
            yellow_action="关注 Delta 暴露变化",
        )
    )

    portfolio_theta: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, float("inf")),
            yellow=(-50, 0),
            red_below=-100,
            hysteresis=10,
            alert_type="THETA_EXPOSURE",
            red_below_message="组合 Theta 为负: {value:.0f}，时间衰减不利",
            yellow_message="组合 Theta 偏低: {value:.0f}",
            red_below_action="减少买方头寸或增加卖方头寸",
            yellow_action="关注时间衰减效率",
        )
    )

    portfolio_vega: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-500, 500),
            yellow=(-1000, 1000),
            red_above=1500,
            red_below=-1500,
            hysteresis=100,
            alert_type="VEGA_EXPOSURE",
            red_above_message="组合 Vega 暴露过高: {value:.0f} > {threshold}",
            red_below_message="组合 Vega 暴露过低: {value:.0f} < {threshold}",
            yellow_message="组合 Vega 暴露偏大: {value:.0f}",
            red_above_action="减少 Vega 暴露，考虑平仓部分头寸",
            red_below_action="Vega 空头过大，波动率上升风险高",
            yellow_action="关注波动率风险",
        )
    )

    portfolio_gamma: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-30, 0),
            yellow=(-50, -30),
            red_below=-50,
            hysteresis=5,
            alert_type="GAMMA_EXPOSURE",
            red_below_message="组合 Gamma 空头过大: {value:.0f} < {threshold}",
            yellow_message="组合 Gamma 空头偏大: {value:.0f}",
            red_below_action="Gamma 空头风险高，大幅波动时亏损加速",
            yellow_action="关注 Gamma 风险",
        )
    )

    portfolio_tgr: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.15, float("inf")),
            yellow=(0.05, 0.15),
            red_below=0.05,
            hysteresis=0.01,
            alert_type="TGR_LOW",
            red_below_message="组合 TGR 过低: {value:.3f} < {threshold}",
            yellow_message="组合 TGR 偏低: {value:.3f}",
            red_below_action="时间衰减效率不足，考虑调整持仓",
            yellow_action="关注时间衰减效率",
        )
    )

    concentration_hhi: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 0.25),
            yellow=(0.25, 0.5),
            red_above=0.5,
            hysteresis=0.05,
            alert_type="CONCENTRATION",
            red_above_message="持仓集中度过高 (HHI={value:.2f} > {threshold})",
            yellow_message="持仓集中度偏高 (HHI={value:.2f})",
            red_above_action="分散持仓，降低单一标的风险",
            yellow_action="关注集中度变化",
        )
    )

    # === 新增：NLV 归一化百分比阈值 ===
    # 这些阈值用于账户大小无关的风险评估

    beta_weighted_delta_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-0.20, 0.20),  # ±20%
            yellow=(-0.50, 0.50),  # ±20~50%
            red_above=0.50,
            red_below=-0.50,
            hysteresis=0.02,
            alert_type="DELTA_EXPOSURE",
            red_above_message="BWD/NLV 过高: {value:.1%} > {threshold:.0%}，方向性杠杆过大",
            red_below_message="BWD/NLV 过低: {value:.1%} < {threshold:.0%}，方向性杠杆过大",
            yellow_message="BWD/NLV 偏离中性: {value:.1%}",
            red_above_action="Delta 对冲：交易 SPY/QQQ 期货或 ETF 进行反向对冲，或平掉贡献 Delta 最大的单边头寸",
            red_below_action="Delta 对冲：交易 SPY/QQQ 期货或 ETF 进行反向对冲，或平掉贡献 Delta 最大的单边头寸",
            yellow_action="关注方向性敞口",
        )
    )

    gamma_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-0.001, float("inf")),  # > -0.1%
            yellow=(-0.003, -0.001),  # -0.1% ~ -0.3%
            red_below=-0.005,  # < -0.5%
            hysteresis=0.0005,
            alert_type="GAMMA_EXPOSURE",
            red_below_message="Gamma/NLV 空头过大: {value:.2%} < {threshold:.2%}，暴跌时 Delta 敞口恶化加速",
            yellow_message="Gamma/NLV 空头偏大: {value:.2%}",
            red_below_action="切断左尾：买入近月深虚值 Put 保护 Gamma，或平掉临期（DTE < 7）的 Short ATM 头寸",
            yellow_action="关注 Gamma 风险",
        )
    )

    vega_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-0.003, 0.003),  # ±0.3%
            yellow=(-0.006, 0.006),  # ±0.3~0.6%
            red_below=-0.005,  # < -0.5% (做空方向)
            # 注意：只有做空方向（负值）才触发红色预警
            # 做多方向（正值）通常比较宽容，因为崩盘时 Long Vega 是对冲
            hysteresis=0.0005,
            alert_type="VEGA_EXPOSURE",
            red_below_message="Vega/NLV 空头过大: {value:.2%} < {threshold:.2%}，崩盘时遭遇股价亏+IV亏双杀",
            yellow_message="Vega/NLV 偏大: {value:.2%}",
            red_below_action="IV 对冲/降仓：买入 VIX Call 或 SPY Put，或平掉 Vega 贡献最大的 Short Leg",
            yellow_action="关注波动率风险",
        )
    )

    theta_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.0005, 0.0015),  # 0.05% ~ 0.15%
            yellow=(0.0015, 0.0025),  # 0.15% ~ 0.25%
            red_above=0.0030,  # > 0.30%
            red_below=0.0,  # < 0%
            hysteresis=0.0002,
            alert_type="THETA_EXPOSURE",
            red_above_message="Theta/NLV 过高: {value:.2%} > {threshold:.2%}，卖得太满，Gamma 风险失控",
            red_below_message="Theta/NLV 为负: {value:.2%}，买方策略时间衰减不利",
            yellow_message="Theta/NLV 偏高: {value:.2%}",
            red_above_action="降低风险暴露：平仓部分 Short 头寸，Theta 过高意味着 Gamma 风险过大",
            red_below_action="检查策略逻辑：如非特意做买方策略，需调整持仓结构",
            yellow_action="关注时间衰减效率",
        )
    )

    vega_weighted_iv_hv: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(1.0, float("inf")),  # > 1.0
            yellow=(0.8, 1.2),  # 0.8 ~ 1.2
            red_below=0.8,  # < 0.8
            hysteresis=0.05,
            alert_type="IV_HV_QUALITY",
            red_below_message='Vega加权 IV/HV 过低: {value:.2f} < {threshold}，持仓在"贱卖"期权',
            yellow_message="Vega加权 IV/HV 偏低: {value:.2f}",
            red_below_action="停止做空/熔断：禁止开设新的 Short Vega 仓位，仅允许做 Debit 策略或持有现金",
            yellow_action="关注期权定价质量",
        )
    )

    # 保留旧字段用于向后兼容（deprecated）
    tgr_green_above: float = 0.15
    tgr_yellow_range: tuple[float, float] = (0.05, 0.15)
    tgr_red_below: float = 0.05
    max_concentration: float = 0.5


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

    @staticmethod
    def _parse_threshold_range(data: dict[str, Any], default: ThresholdRange) -> ThresholdRange:
        """从字典解析 ThresholdRange

        Args:
            data: YAML 中的阈值配置
            default: 默认的 ThresholdRange

        Returns:
            解析后的 ThresholdRange
        """
        green = data.get("green")
        yellow = data.get("yellow")

        # 处理 .inf (YAML 中表示无穷大)
        def parse_range(val: list | None) -> tuple[float, float] | None:
            if val is None:
                return None
            low, high = val
            if high == ".inf" or high == float("inf"):
                high = float("inf")
            if low == "-.inf" or low == float("-inf"):
                low = float("-inf")
            return (float(low), float(high))

        return ThresholdRange(
            green=parse_range(green) if green else default.green,
            yellow=parse_range(yellow) if yellow else default.yellow,
            red_above=data.get("red_above", default.red_above),
            red_below=data.get("red_below", default.red_below),
            hysteresis=data.get("hysteresis", default.hysteresis),
            alert_type=data.get("alert_type", default.alert_type),
            red_above_message=data.get("red_above_message", default.red_above_message),
            red_below_message=data.get("red_below_message", default.red_below_message),
            yellow_message=data.get("yellow_message", default.yellow_message),
            red_above_action=data.get("red_above_action", default.red_above_action),
            red_below_action=data.get("red_below_action", default.red_below_action),
            yellow_action=data.get("yellow_action", default.yellow_action),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitoringConfig":
        """从字典创建配置"""
        config = cls()

        if "portfolio_level" in data:
            pl = data["portfolio_level"]

            # 使用统一的 ThresholdRange 解析
            if "beta_weighted_delta" in pl:
                config.portfolio.beta_weighted_delta = cls._parse_threshold_range(
                    pl["beta_weighted_delta"],
                    PortfolioThresholds().beta_weighted_delta,
                )

            if "portfolio_theta" in pl:
                config.portfolio.portfolio_theta = cls._parse_threshold_range(
                    pl["portfolio_theta"],
                    PortfolioThresholds().portfolio_theta,
                )

            if "portfolio_vega" in pl:
                config.portfolio.portfolio_vega = cls._parse_threshold_range(
                    pl["portfolio_vega"],
                    PortfolioThresholds().portfolio_vega,
                )

            if "portfolio_gamma" in pl:
                config.portfolio.portfolio_gamma = cls._parse_threshold_range(
                    pl["portfolio_gamma"],
                    PortfolioThresholds().portfolio_gamma,
                )

            if "portfolio_tgr" in pl:
                config.portfolio.portfolio_tgr = cls._parse_threshold_range(
                    pl["portfolio_tgr"],
                    PortfolioThresholds().portfolio_tgr,
                )

            if "concentration_hhi" in pl:
                config.portfolio.concentration_hhi = cls._parse_threshold_range(
                    pl["concentration_hhi"],
                    PortfolioThresholds().concentration_hhi,
                )

            # 向后兼容：旧格式 TGR
            if "tgr" in pl:
                tgr = pl["tgr"]
                config.portfolio.tgr_green_above = tgr.get("green_above", 0.15)
                config.portfolio.tgr_yellow_range = tuple(
                    tgr.get("yellow_range", [0.05, 0.15])
                )
                config.portfolio.tgr_red_below = tgr.get("red_below", 0.05)

            # 向后兼容：旧格式 concentration
            if "correlation" in pl:
                config.portfolio.max_concentration = pl["correlation"].get(
                    "max_concentration", 0.5
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
