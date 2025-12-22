"""
Monitoring Models - 监控系统数据模型

定义监控系统的核心数据结构：
- MonitorStatus: 监控状态（红/黄/绿）
- Alert: 预警信息
- PositionData: 持仓数据
- MonitorResult: 监控结果
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


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
    """持仓数据（用于监控）"""

    position_id: str
    symbol: str
    underlying: str
    option_type: str  # "put" or "call"
    strike: float
    expiry: str  # YYYY-MM-DD
    quantity: int
    entry_price: float
    current_price: float
    timestamp: datetime = field(default_factory=datetime.now)

    # 标的价格
    underlying_price: Optional[float] = None

    # Greeks
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None

    # 波动率
    iv: Optional[float] = None
    hv: Optional[float] = None

    # 到期信息
    dte: int = 0

    # 盈亏
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None

    # 策略指标
    prei: Optional[float] = None
    tgr: Optional[float] = None

    @property
    def moneyness(self) -> Optional[float]:
        """计算虚值程度 (S-K)/K"""
        if self.underlying_price and self.strike:
            return (self.underlying_price - self.strike) / self.strike
        return None

    @property
    def iv_hv_ratio(self) -> Optional[float]:
        """IV/HV 比率"""
        if self.iv and self.hv and self.hv > 0:
            return self.iv / self.hv
        return None


@dataclass
class PortfolioMetrics:
    """组合级指标"""

    # Beta 加权 Delta
    beta_weighted_delta: Optional[float] = None

    # 组合 Greeks
    total_delta: Optional[float] = None
    total_gamma: Optional[float] = None
    total_theta: Optional[float] = None
    total_vega: Optional[float] = None

    # Theta/Gamma 比率
    portfolio_tgr: Optional[float] = None

    # 集中度
    max_symbol_weight: Optional[float] = None
    correlation_exposure: Optional[float] = None

    # 时间戳
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CapitalMetrics:
    """资金级指标"""

    # 账户权益
    total_equity: Optional[float] = None
    cash_balance: Optional[float] = None

    # 保证金
    maintenance_margin: Optional[float] = None
    margin_usage: Optional[float] = None

    # 收益指标
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    sharpe_ratio: Optional[float] = None

    # Kelly 使用率
    total_position_value: Optional[float] = None
    kelly_capacity: Optional[float] = None
    kelly_usage: Optional[float] = None

    # 回撤
    peak_equity: Optional[float] = None
    current_drawdown: Optional[float] = None

    # 时间戳
    timestamp: datetime = field(default_factory=datetime.now)


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

    # 组合指标
    portfolio_metrics: Optional[PortfolioMetrics] = None

    # 资金指标
    capital_metrics: Optional[CapitalMetrics] = None

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
        }
