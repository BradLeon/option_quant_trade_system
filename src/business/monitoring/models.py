"""
Monitoring Models - 监控系统数据模型

定义监控系统的核心数据结构：
- MonitorStatus: 监控状态（红/黄/绿）
- Alert: 预警信息
- PositionData: 持仓数据
- MonitorResult: 监控结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from src.data.models.option import Greeks

if TYPE_CHECKING:
    from src.business.monitoring.suggestions import PositionSuggestion


class AlertLevel(str, Enum):
    """预警级别"""

    GREEN = "green"  # 正常/机会
    YELLOW = "yellow"  # 关注
    RED = "red"  # 风险


class AlertType(str, Enum):
    """预警类型"""

    # Portfolio 级
    DELTA_EXPOSURE = "delta_exposure"  # Delta 风险敞口
    GAMMA_EXPOSURE = "gamma_exposure"  # Gamma 风险敞口
    VEGA_EXPOSURE = "vega_exposure"  # Vega 风险敞口
    THETA_EXPOSURE = "theta_exposure"  # Theta 风险敞口
    TGR_LOW = "tgr_low"  # Theta/Gamma 比率过低
    CONCENTRATION = "concentration"  # 集中度过高

    # Position 级
    MONEYNESS = "moneyness"  # 虚值程度
    DELTA_CHANGE = "delta_change"  # Delta 变化
    GAMMA_NEAR_EXPIRY = "gamma_near_expiry"  # 临近到期 Gamma 风险
    IV_HV_CHANGE = "iv_hv_change"  # IV/HV 变化
    PREI_HIGH = "prei_high"  # PREI 过高
    DTE_WARNING = "dte_warning"  # 临近到期
    PROFIT_TARGET = "profit_target"  # 达到止盈
    STOP_LOSS = "stop_loss"  # 达到止损

    # Capital 级
    SHARPE_LOW = "sharpe_low"  # Sharpe 过低
    KELLY_USAGE = "kelly_usage"  # Kelly 使用率
    MARGIN_WARNING = "margin_warning"  # 保证金预警
    DRAWDOWN = "drawdown"  # 回撤预警


class MonitorStatus(str, Enum):
    """监控状态"""

    GREEN = "green"  # 正常
    YELLOW = "yellow"  # 关注
    RED = "red"  # 风险


@dataclass
class Alert:
    """预警信息"""

    alert_type: AlertType
    level: AlertLevel
    message: str
    timestamp: datetime = field(default_factory=datetime.now)

    # 相关标的/持仓
    symbol: Optional[str] = None
    position_id: Optional[str] = None

    # 当前值和阈值
    current_value: Optional[float] = None
    threshold_value: Optional[float] = None

    # 建议操作
    suggested_action: Optional[str] = None

    # 额外数据
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionData:
    """持仓数据（统一支持期权和股票）

    设计原则：
    - 纯数据容器，不包含计算逻辑（遵循 Decision #0）
    - 期权专用字段（strike, expiry等）股票持仓为 None
    - 标的分析字段（技术面、波动率）期权和股票都可以有
    - 期权的标的分析基于 underlying，股票基于自身
    - 所有派生值由 DataBridge 调用 engine 层算子计算后填充
    """

    # === 基础信息 ===
    position_id: str
    symbol: str  # 持仓代码
    asset_type: str = "option"  # "option" / "stock"
    quantity: float = 0
    entry_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    currency: str = "USD"
    broker: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    # === 期权专用字段（股票为 None）===
    underlying: Optional[str] = None  # 底层标的
    option_type: Optional[str] = None  # "put" / "call"
    strike: Optional[float] = None
    expiry: Optional[str] = None  # YYYYMMDD
    dte: Optional[int] = None
    contract_multiplier: int = 1
    moneyness: Optional[float] = None  # 由 DataBridge 计算: (S-K)/K

    # === Greeks（期权必须，股票 delta=quantity）===
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None

    # === Beta（用于 beta_weighted_delta 计算）===
    beta: Optional[float] = None

    # === 标的价格（期权为 underlying 价格，股票为自身价格）===
    underlying_price: Optional[float] = None

    # === 波动率数据（由 DataBridge 调用 engine 层算子填充）===
    hv: Optional[float] = None  # 来自 StockVolatility.hv
    iv_rank: Optional[float] = None  # 来自 VolatilityScore.iv_rank
    iv_percentile: Optional[float] = None  # 来自 VolatilityScore.iv_percentile
    iv_hv_ratio: Optional[float] = None  # 来自 VolatilityScore.iv_hv_ratio
    volatility_score: Optional[float] = None  # 来自 evaluate_volatility().score
    volatility_rating: Optional[str] = None  # 来自 evaluate_volatility().rating

    # === 技术面分析（由 DataBridge 调用 calc_technical_score 填充）===
    trend_signal: Optional[str] = None  # 来自 TechnicalScore.trend_signal
    ma_alignment: Optional[str] = None  # 来自 TechnicalScore.ma_alignment
    rsi: Optional[float] = None  # 来自 TechnicalScore.rsi
    rsi_zone: Optional[str] = None  # 来自 TechnicalScore.rsi_zone
    adx: Optional[float] = None  # 来自 TechnicalScore.adx
    support: Optional[float] = None  # 来自 TechnicalScore.support
    resistance: Optional[float] = None  # 来自 TechnicalScore.resistance

    # === 基本面分析（由 DataBridge 调用 evaluate_fundamentals 填充）===
    pe_ratio: Optional[float] = None  # 来自 Fundamental.pe_ratio
    fundamental_score: Optional[float] = None  # 来自 FundamentalScore.score
    analyst_rating: Optional[str] = None  # 来自 FundamentalScore.rating

    # === 技术信号（由 DataBridge 调用 calc_technical_signal 填充）===
    market_regime: Optional[str] = None  # ranging, trending_up, trending_down
    tech_trend_strength: Optional[str] = None  # very_weak, weak, emerging, moderate, strong
    sell_put_signal: Optional[str] = None  # none, weak, moderate, strong
    sell_call_signal: Optional[str] = None  # none, weak, moderate, strong
    is_dangerous_period: Optional[bool] = None

    # === 策略指标（由 DataBridge 调用 strategy.calc_metrics() 填充）===
    strategy_type: Optional[str] = None  # "short_put" / "covered_call" 等
    prei: Optional[float] = None  # 来自 StrategyMetrics.prei
    tgr: Optional[float] = None  # 来自 StrategyMetrics.tgr
    sas: Optional[float] = None  # 来自 StrategyMetrics.sas
    roc: Optional[float] = None  # 来自 StrategyMetrics.roc
    expected_roc: Optional[float] = None  # 来自 StrategyMetrics.expected_roc
    sharpe: Optional[float] = None  # 来自 StrategyMetrics.sharpe_ratio
    kelly: Optional[float] = None  # 来自 StrategyMetrics.kelly_fraction
    win_probability: Optional[float] = None  # 来自 StrategyMetrics.win_probability

    # === 核心策略指标（用于详细展示）===
    expected_return: Optional[float] = None  # 来自 StrategyMetrics.expected_return
    max_profit: Optional[float] = None  # 来自 StrategyMetrics.max_profit
    max_loss: Optional[float] = None  # 来自 StrategyMetrics.max_loss
    breakeven: Optional[float | list[float]] = None  # 来自 StrategyMetrics.breakeven
    return_std: Optional[float] = None  # 来自 StrategyMetrics.return_std

    # === 资金相关指标 ===
    margin: Optional[float] = None  # 保证金需求
    capital_at_risk: Optional[float] = None  # 风险资本

    # === 便捷属性（仅做类型判断，无计算逻辑）===
    @property
    def is_option(self) -> bool:
        """是否为期权持仓"""
        return self.asset_type == "option"

    @property
    def is_stock(self) -> bool:
        """是否为股票持仓"""
        return self.asset_type == "stock"

    @property
    def greeks(self) -> Greeks:
        """返回 Greeks 对象供 engine 层函数使用.

        使 PositionData 与 Position 接口兼容，可以直接传给
        calc_portfolio_metrics 等 engine 层函数。
        """
        return Greeks(
            delta=self.delta,
            gamma=self.gamma,
            theta=self.theta,
            vega=self.vega,
        )


# Re-export from engine layer (Decision #0: calculation models belong in engine)
from src.engine.models.capital import CapitalMetrics
from src.engine.models.portfolio import PortfolioMetrics

# Make re-exports available for backward compatibility
__all_metrics__ = ["PortfolioMetrics", "CapitalMetrics"]


@dataclass
class MonitorResult:
    """监控结果"""

    # 整体状态
    status: MonitorStatus
    timestamp: datetime = field(default_factory=datetime.now)

    # 预警列表
    alerts: list[Alert] = field(default_factory=list)

    # 持仓数据
    positions: list[PositionData] = field(default_factory=list)

    # 调整建议列表
    suggestions: list[PositionSuggestion] = field(default_factory=list)

    # 组合指标
    portfolio_metrics: Optional[PortfolioMetrics] = None

    # 资金指标
    capital_metrics: Optional[CapitalMetrics] = None

    # 市场情绪
    market_sentiment: Optional[dict[str, Any]] = None

    # 统计信息
    total_positions: int = 0
    positions_at_risk: int = 0
    positions_opportunity: int = 0

    @property
    def red_alerts(self) -> list[Alert]:
        """红色预警"""
        return [a for a in self.alerts if a.level == AlertLevel.RED]

    @property
    def yellow_alerts(self) -> list[Alert]:
        """黄色预警"""
        return [a for a in self.alerts if a.level == AlertLevel.YELLOW]

    @property
    def green_alerts(self) -> list[Alert]:
        """绿色预警（机会）"""
        return [a for a in self.alerts if a.level == AlertLevel.GREEN]

    @property
    def immediate_suggestions(self) -> list[PositionSuggestion]:
        """需要立即处理的建议"""
        from src.business.monitoring.suggestions import UrgencyLevel

        return [s for s in self.suggestions if s.urgency == UrgencyLevel.IMMEDIATE]

    @property
    def summary(self) -> dict:
        """监控摘要"""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "total_positions": self.total_positions,
            "red_alerts": len(self.red_alerts),
            "yellow_alerts": len(self.yellow_alerts),
            "green_alerts": len(self.green_alerts),
            "positions_at_risk": self.positions_at_risk,
            "positions_opportunity": self.positions_opportunity,
            "suggestions_count": len(self.suggestions),
            "immediate_actions": len(self.immediate_suggestions),
        }
