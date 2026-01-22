"""
Screening Models - 筛选系统数据模型

定义筛选系统的核心数据结构：
- MarketStatus: 市场环境状态
- UnderlyingScore: 标的评分
- ContractOpportunity: 合约机会
- ScreeningResult: 筛选结果
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

from src.data.models.event import EconomicEvent


class MarketType(str, Enum):
    """市场类型"""

    US = "US"
    HK = "HK"


class TrendStatus(str, Enum):
    """趋势状态"""

    STRONG_BULLISH = "strong_bullish"  # 强多头
    BULLISH = "bullish"  # 多头
    NEUTRAL = "neutral"  # 中性
    BEARISH = "bearish"  # 空头
    STRONG_BEARISH = "strong_bearish"  # 强空头


class VolatilityStatus(str, Enum):
    """波动率状态"""

    LOW = "low"  # 偏低
    NORMAL = "normal"  # 正常
    HIGH = "high"  # 偏高
    EXTREME = "extreme"  # 极端


class FilterStatus(str, Enum):
    """过滤状态"""

    FAVORABLE = "favorable"  # 有利
    NEUTRAL = "neutral"  # 中性
    UNFAVORABLE = "unfavorable"  # 不利
    OPPORTUNITY = "opportunity"  # 机会


@dataclass
class IndexStatus:
    """指数状态"""

    symbol: str
    price: float
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    trend: TrendStatus = TrendStatus.NEUTRAL
    weight: float = 1.0


@dataclass
class VolatilityIndexStatus:
    """波动率指数状态"""

    symbol: str
    value: float
    percentile: Optional[float] = None  # 历史百分位
    status: VolatilityStatus = VolatilityStatus.NORMAL
    filter_status: FilterStatus = FilterStatus.NEUTRAL


@dataclass
class TermStructureStatus:
    """期限结构状态"""

    vix_value: float
    vix3m_value: float
    ratio: float  # VIX / VIX3M
    is_contango: bool  # 正向结构
    filter_status: FilterStatus = FilterStatus.NEUTRAL


@dataclass
class PCRStatus:
    """Put/Call Ratio 状态"""

    symbol: str
    value: float
    filter_status: FilterStatus = FilterStatus.NEUTRAL


@dataclass
class MacroEventStatus:
    """宏观事件状态"""

    is_in_blackout: bool = False
    upcoming_events: list[EconomicEvent] = field(default_factory=list)
    blackout_days: int = 2

    @property
    def event_names(self) -> list[str]:
        """获取即将发生的事件名称"""
        return [e.name for e in self.upcoming_events]


@dataclass
class MarketStatus:
    """市场环境状态"""

    market_type: MarketType
    is_favorable: bool
    timestamp: datetime = field(default_factory=datetime.now)

    # 波动率指数
    volatility_index: Optional[VolatilityIndexStatus] = None

    # 大盘趋势
    trend_indices: list[IndexStatus] = field(default_factory=list)
    overall_trend: TrendStatus = TrendStatus.NEUTRAL

    # 期限结构（仅美股）
    term_structure: Optional[TermStructureStatus] = None

    # PCR
    pcr: Optional[PCRStatus] = None

    # 宏观事件
    macro_events: Optional[MacroEventStatus] = None

    # 不利因素
    unfavorable_reasons: list[str] = field(default_factory=list)

    def get_trend_filter_status(self) -> FilterStatus:
        """获取趋势过滤状态"""
        if self.overall_trend in [TrendStatus.STRONG_BULLISH, TrendStatus.BULLISH]:
            return FilterStatus.FAVORABLE
        elif self.overall_trend == TrendStatus.NEUTRAL:
            return FilterStatus.NEUTRAL
        else:
            return FilterStatus.UNFAVORABLE


@dataclass
class TechnicalScore:
    """技术面评分"""

    rsi: Optional[float] = None
    rsi_zone: str = "neutral"  # oversold / stabilizing / neutral / exhausting / overbought
    bb_percent_b: Optional[float] = None
    adx: Optional[float] = None
    plus_di: Optional[float] = None  # +DI 多头方向指数
    minus_di: Optional[float] = None  # -DI 空头方向指数
    sma_alignment: str = "neutral"  # strong_bullish / bullish / neutral / bearish / strong_bearish
    support_distance: Optional[float] = None  # 距离支撑位的百分比

    @property
    def is_stabilizing(self) -> bool:
        """是否企稳（适合卖 Put）"""
        return self.rsi_zone in ["stabilizing", "oversold"]

    @property
    def is_exhausting(self) -> bool:
        """是否动能衰竭（适合卖 Call）"""
        return self.rsi_zone in ["exhausting", "overbought"]

    @property
    def is_downtrend(self) -> bool:
        """是否强下跌趋势（ADX >= 25 且 -DI > +DI）"""
        if self.adx is None or self.adx < 25:
            return False
        if self.plus_di is None or self.minus_di is None:
            return False
        return self.minus_di > self.plus_di

    @property
    def is_uptrend(self) -> bool:
        """是否强上涨趋势（ADX >= 25 且 +DI > -DI）"""
        if self.adx is None or self.adx < 25:
            return False
        if self.plus_di is None or self.minus_di is None:
            return False
        return self.plus_di > self.minus_di


@dataclass
class FundamentalScore:
    """基本面评分"""

    pe_ratio: Optional[float] = None
    pe_percentile: Optional[float] = None
    revenue_growth: Optional[float] = None
    recommendation: Optional[str] = None  # strong_buy / buy / hold / sell / strong_sell
    score: float = 0.0  # 综合评分 0-100


@dataclass
class UnderlyingScore:
    """标的评分"""

    symbol: str
    market_type: MarketType
    passed: bool
    timestamp: datetime = field(default_factory=datetime.now)

    # 当前价格
    current_price: Optional[float] = None

    # 波动率指标
    iv_rank: Optional[float] = None
    iv_hv_ratio: Optional[float] = None
    hv_20: Optional[float] = None  # 20日历史波动率
    current_iv: Optional[float] = None  # 当前隐含波动率

    # 技术面评分
    technical: Optional[TechnicalScore] = None

    # 基本面评分
    fundamental: Optional[FundamentalScore] = None

    # 事件日历
    earnings_date: Optional[date] = None  # 下一次财报日
    ex_dividend_date: Optional[date] = None  # 下一次除息日
    days_to_earnings: Optional[int] = None  # 距财报天数
    days_to_ex_dividend: Optional[int] = None  # 距除息日天数

    # 不合格原因 (P0/P1 阻塞条件)
    disqualify_reasons: list[str] = field(default_factory=list)

    # 警告信息 (P2/P3 不阻塞条件)
    warnings: list[str] = field(default_factory=list)

    @property
    def composite_score(self) -> float:
        """综合评分"""
        score = 0.0
        weights_sum = 0.0

        # IV Rank 权重 30%
        if self.iv_rank is not None:
            score += min(self.iv_rank, 100) * 0.3
            weights_sum += 0.3

        # IV/HV 权重 20%
        if self.iv_hv_ratio is not None:
            # IV/HV 在 1.0-1.5 之间最佳
            if 1.0 <= self.iv_hv_ratio <= 1.5:
                iv_hv_score = 100
            elif self.iv_hv_ratio < 1.0:
                iv_hv_score = max(0, self.iv_hv_ratio * 100)
            else:
                iv_hv_score = max(0, 100 - (self.iv_hv_ratio - 1.5) * 50)
            score += iv_hv_score * 0.2
            weights_sum += 0.2

        # 技术面权重 30%
        if self.technical and self.technical.rsi is not None:
            # RSI 在 30-45 之间最佳（对于卖 Put）
            if 30 <= self.technical.rsi <= 45:
                tech_score = 100
            elif self.technical.rsi < 30:
                tech_score = 70  # 超卖有风险
            elif self.technical.rsi > 70:
                tech_score = 30
            else:
                tech_score = 60
            score += tech_score * 0.3
            weights_sum += 0.3

        # 基本面权重 20%
        if self.fundamental and self.fundamental.score > 0:
            score += self.fundamental.score * 0.2
            weights_sum += 0.2

        return score / weights_sum if weights_sum > 0 else 0.0


@dataclass
class ContractOpportunity:
    """合约机会"""

    symbol: str
    expiry: str  # YYYY-MM-DD
    strike: float
    option_type: str  # "put" or "call"
    trading_class: Optional[str] = None  # IBKR trading class (e.g., "ALB" for 9988.HK)
    timestamp: datetime = field(default_factory=datetime.now)

    # 合约数据
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid_price: Optional[float] = None
    open_interest: Optional[int] = None
    volume: Optional[int] = None

    # Greeks
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None

    # 到期信息
    dte: int = 0

    # 策略指标
    expected_return: Optional[float] = None
    return_std: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sharpe_ratio_annual: Optional[float] = None  # 年化 Sharpe = SR × √(365/DTE)
    win_probability: Optional[float] = None
    sas: Optional[float] = None  # 策略吸引力评分
    prei: Optional[float] = None  # 风险暴露指数
    tgr: Optional[float] = None  # Theta/Gamma 比率
    kelly_fraction: Optional[float] = None  # Kelly 仓位

    # 标的信息
    underlying_price: Optional[float] = None
    moneyness: Optional[float] = None  # (S-K)/K
    otm_percent: Optional[float] = None  # OTM百分比
    theta_premium_ratio: Optional[float] = None  # Theta/Premium比率
    theta_margin_ratio: Optional[float] = None  # Theta/Margin比率（资金效率排序指标）

    # 期望收益指标
    expected_roc: Optional[float] = None  # 期望收益率
    annual_roc: Optional[float] = None  # 年化收益率
    premium_rate: Optional[float] = None  # 费率 = Premium / K

    # 优先级机制
    disqualify_reasons: list[str] = field(default_factory=list)  # P0/P1 阻塞原因
    warnings: list[str] = field(default_factory=list)  # P2/P3 警告信息
    passed: bool = True  # 是否通过所有 P0/P1 检查

    # 通过信息（仅 passed=True 时填充）
    pass_reasons: list[str] = field(default_factory=list)  # 通过原因（关键指标摘要）
    recommended_position: Optional[float] = None  # 推荐仓位（1/4 Kelly）

    @property
    def bid_ask_spread(self) -> Optional[float]:
        """Bid/Ask 价差比例"""
        if self.bid and self.ask and self.mid_price and self.mid_price > 0:
            return (self.ask - self.bid) / self.mid_price
        return None

    @property
    def is_liquid(self) -> bool:
        """是否流动性充足"""
        spread = self.bid_ask_spread
        if spread is None:
            return False
        return spread <= 0.10 and (self.open_interest or 0) >= 100


@dataclass
class ScreeningResult:
    """筛选结果"""

    passed: bool
    strategy_type: str  # "short_put" or "covered_call"
    timestamp: datetime = field(default_factory=datetime.now)

    # 市场状态
    market_status: Optional[MarketStatus] = None

    # 机会列表
    opportunities: list[ContractOpportunity] = field(default_factory=list)

    # 标的评分列表
    underlying_scores: list[UnderlyingScore] = field(default_factory=list)

    # 筛选摘要
    scanned_underlyings: int = 0
    passed_underlyings: int = 0
    total_contracts_evaluated: int = 0
    qualified_contracts: int = 0

    # 不通过原因（如市场不利）
    rejection_reason: Optional[str] = None

    # Double Confirmation 字段
    candidates: list[ContractOpportunity] = field(default_factory=list)  # Step1 候选
    confirmed: list[ContractOpportunity] = field(default_factory=list)  # 两步都通过

    @property
    def summary(self) -> dict:
        """筛选摘要"""
        return {
            "passed": self.passed,
            "strategy": self.strategy_type,
            "timestamp": self.timestamp.isoformat(),
            "scanned_underlyings": self.scanned_underlyings,
            "passed_underlyings": self.passed_underlyings,
            "qualified_contracts": self.qualified_contracts,
            "top_opportunities": len(self.opportunities),
            "rejection_reason": self.rejection_reason,
        }
