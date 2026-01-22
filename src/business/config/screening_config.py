"""
Screening Configuration - 筛选配置管理

加载和管理开仓筛选系统的配置参数
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TrendIndexConfig:
    """趋势指数配置"""

    symbol: str
    weight: float = 1.0


@dataclass
class USMarketConfig:
    """美股市场配置"""

    vix_symbol: str = "^VIX"
    vix_range: tuple[float, float] = (15.0, 999.0)  # 移除上限，VIX > 30 是卖方黄金时刻
    vix_percentile_range: tuple[float, float] = (0.2, 0.8)
    vix3m_symbol: str = "^VIX3M"
    term_structure_threshold: float = 0.9
    trend_indices: list[TrendIndexConfig] = field(default_factory=list)
    trend_required: str = "bullish_or_neutral"
    # PCR 已删除: 0.8-1.2 是常态震荡无过滤价值，数据质量不稳定

    def __post_init__(self) -> None:
        if not self.trend_indices:
            self.trend_indices = [
                TrendIndexConfig(symbol="SPY", weight=0.6),
                TrendIndexConfig(symbol="QQQ", weight=0.4),
            ]


@dataclass
class HKMarketConfig:
    """港股市场配置"""

    # VHSI (恒生波动率指数) 配置 - 通过 Yahoo Finance 获取
    vhsi_symbol: str = "^HSIL"  # Yahoo Finance 代码
    vhsi_range: tuple[float, float] = (18.0, 999.0)  # 移除上限，高波是卖方黄金时刻
    vhsi_percentile_range: tuple[float, float] = (0.2, 0.8)  # VHSI 分布较窄，放宽低位阈值

    # 备选: 2800.HK IV (需要 IBKR 连接)
    volatility_source: str = "2800.HK"
    iv_calculation: str = "atm_weighted"
    iv_range: tuple[float, float] = (18.0, 32.0)
    iv_percentile_range: tuple[float, float] = (0.3, 0.8)

    # 趋势指数配置
    trend_indices: list[TrendIndexConfig] = field(default_factory=list)
    trend_required: str = "bullish_or_neutral"

    # 宏观事件检查 (FOMC 对全球市场有影响)
    check_us_macro_events: bool = True

    def __post_init__(self) -> None:
        if not self.trend_indices:
            self.trend_indices = [
                TrendIndexConfig(symbol="2800.HK", weight=0.5),
                TrendIndexConfig(symbol="3033.HK", weight=0.5),
            ]


@dataclass
class MacroEventConfig:
    """宏观事件配置"""

    enabled: bool = True
    blackout_days: int = 2  # 事件前禁止开仓天数
    blackout_events: list[str] = field(
        default_factory=lambda: ["FOMC", "CPI", "NFP"]
    )  # 需要回避的事件类型


@dataclass
class MarketFilterConfig:
    """市场过滤器配置"""

    us_market: USMarketConfig = field(default_factory=USMarketConfig)
    hk_market: HKMarketConfig = field(default_factory=HKMarketConfig)
    macro_events: MacroEventConfig = field(default_factory=MacroEventConfig)


@dataclass
class TechnicalConfig:
    """技术面配置"""

    # RSI 策略区分阈值
    # Short Put: 允许更深超卖（RSI 25 是底部反弹信号）
    short_put_rsi_min: float = 25.0
    short_put_rsi_max: float = 70.0
    # Covered Call: 允许更高超买（RSI 85 以下动能仍可持续）
    covered_call_rsi_min: float = 30.0
    covered_call_rsi_max: float = 85.0

    # 兼容旧配置
    min_rsi: float = 25.0  # 使用最宽范围
    max_rsi: float = 85.0  # 使用最宽范围
    rsi_stabilizing_range: tuple[float, float] = (30.0, 45.0)
    bb_percent_b_range: tuple[float, float] = (0.1, 0.3)
    max_adx: float = 45.0
    min_sma_alignment: str = "neutral"


@dataclass
class FundamentalConfig:
    """基本面配置"""

    enabled: bool = True  # 默认启用基本面检查
    max_pe_percentile: float = 0.7
    min_recommendation: str = "hold"


@dataclass
class EventCalendarConfig:
    """事件日历配置"""

    enabled: bool = True
    min_days_to_earnings: int = 7  # 距财报最小天数
    min_days_to_ex_dividend: int = 7  # 距除息日最小天数（仅 Covered Call）
    allow_earnings_if_before_expiry: bool = True  # 允许合约在财报前到期


@dataclass
class UnderlyingFilterConfig:
    """标的过滤器配置"""

    min_iv_rank: float = 30.0  # P1: IV Rank 阻塞条件，卖方必须卖"贵"的东西
    max_iv_hv_ratio: float = 2.0
    min_iv_hv_ratio: float = 0.8
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    fundamental: FundamentalConfig = field(default_factory=FundamentalConfig)
    event_calendar: EventCalendarConfig = field(default_factory=EventCalendarConfig)


@dataclass
class LiquidityConfig:
    """流动性配置"""

    # P1: 目标合约 Bid-Ask Spread
    max_bid_ask_spread: float = 0.10
    # P1: Open Interest
    min_open_interest: int = 100
    # P3: Volume Today
    min_volume: int = 10


@dataclass
class MetricsConfig:
    """指标配置

    优先级说明：
    - P0: Expected ROC（致命条件）
    - P1: TGR（核心条件）
    - P2: Annual ROC（重要条件）
    - P3: Sharpe Ratio, Premium Rate, Win Probability, Theta/Premium, Kelly（参考条件）
          Sharpe/PremRate 降级原因：卖方收益非正态分布，费率已被 AnnROC 包含
    """

    # P3: 年化夏普比率（参考条件，卖方收益非正态分布）
    min_sharpe_ratio: float = 0.5
    # P2: 策略吸引力评分
    min_sas: float = 50.0
    # P2: 风险暴露指数 (越低越好)
    max_prei: float = 75.0
    # P1: Theta/Gamma 比率（标准化公式：|Theta| / (|Gamma| × S² × σ_daily) × 100）
    min_tgr: float = 0.5
    # P3: Kelly 仓位上限
    max_kelly_fraction: float = 0.25
    # P0: 期望收益率必须足够高
    min_expected_roc: float = 0.10
    # P2: 年化收益率
    min_annual_roc: float = 0.15
    # P3: 胜率
    min_win_probability: float = 0.65
    # P3: Theta/Premium 比率 (每天)
    min_theta_premium_ratio: float = 0.01
    # P3: 费率（参考条件，已被 Annual ROC 包含）
    min_premium_rate: float = 0.01


@dataclass
class ContractFilterConfig:
    """合约过滤器配置

    统一配置适用于 short_put 和 covered_call 策略。
    """

    # P1: DTE 范围（港股期权到期日稀疏，使用宽范围）
    dte_range: tuple[int, int] = (7, 45)
    optimal_dte_range: tuple[int, int] = (25, 45)
    # P1: |Delta| 范围（绝对值，覆盖两种策略）
    delta_range: tuple[float, float] = (0.05, 0.35)
    optimal_delta_range: tuple[float, float] = (0.20, 0.30)
    # P2: OTM 百分比范围
    otm_range: tuple[float, float] = (0.07, 0.30)
    # 流动性配置
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    # 指标配置
    metrics: MetricsConfig = field(default_factory=MetricsConfig)


@dataclass
class OutputConfig:
    """输出配置"""

    max_opportunities: int = 10
    sort_by: str = "expected_roc"
    sort_order: str = "desc"


@dataclass
class ScreeningConfig:
    """筛选配置"""

    market_filter: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    underlying_filter: UnderlyingFilterConfig = field(
        default_factory=UnderlyingFilterConfig
    )
    contract_filter: ContractFilterConfig = field(default_factory=ContractFilterConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ScreeningConfig":
        """从 YAML 文件加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreeningConfig":
        """从字典创建配置"""
        config = cls()

        if "market_filter" in data:
            mf = data["market_filter"]
            if "us_market" in mf:
                us = mf["us_market"]
                config.market_filter.us_market = USMarketConfig(
                    vix_symbol=us.get("vix_symbol", "^VIX"),
                    vix_range=tuple(us.get("vix_range", [15, 28])),
                    vix_percentile_range=tuple(us.get("vix_percentile_range", [0.3, 0.8])),
                    vix3m_symbol=us.get("vix3m_symbol", "^VIX3M"),
                    term_structure_threshold=us.get("term_structure_threshold", 0.9),
                    trend_indices=[
                        TrendIndexConfig(**idx) for idx in us.get("trend_indices", [])
                    ],
                    trend_required=us.get("trend_required", "bullish_or_neutral"),
                )
            if "hk_market" in mf:
                hk = mf["hk_market"]
                config.market_filter.hk_market = HKMarketConfig(
                    volatility_source=hk.get("volatility_source", "2800.HK"),
                    iv_calculation=hk.get("iv_calculation", "atm_weighted"),
                    iv_range=tuple(hk.get("iv_range", [18, 32])),
                    iv_percentile_range=tuple(hk.get("iv_percentile_range", [0.3, 0.8])),
                    trend_indices=[
                        TrendIndexConfig(**idx) for idx in hk.get("trend_indices", [])
                    ],
                    trend_required=hk.get("trend_required", "bullish_or_neutral"),
                )

        if "underlying_filter" in data:
            uf = data["underlying_filter"]
            tech = uf.get("technical", {})
            fund = uf.get("fundamental", {})
            config.underlying_filter = UnderlyingFilterConfig(
                min_iv_rank=uf.get("min_iv_rank", 50),
                max_iv_hv_ratio=uf.get("max_iv_hv_ratio", 2.0),
                min_iv_hv_ratio=uf.get("min_iv_hv_ratio", 0.8),
                technical=TechnicalConfig(
                    min_rsi=tech.get("min_rsi", 30),
                    max_rsi=tech.get("max_rsi", 70),
                    rsi_stabilizing_range=tuple(tech.get("rsi_stabilizing_range", [30, 45])),
                    bb_percent_b_range=tuple(tech.get("bb_percent_b_range", [0.1, 0.3])),
                    max_adx=tech.get("max_adx", 45),
                    min_sma_alignment=tech.get("min_sma_alignment", "neutral"),
                ),
                fundamental=FundamentalConfig(
                    enabled=fund.get("enabled", False),
                    max_pe_percentile=fund.get("max_pe_percentile", 0.7),
                    min_recommendation=fund.get("min_recommendation", "hold"),
                ),
            )

        if "contract_filter" in data:
            cf = data["contract_filter"]
            liq = cf.get("liquidity", {})
            met = cf.get("metrics", {})
            config.contract_filter = ContractFilterConfig(
                dte_range=tuple(cf.get("dte_range", [25, 45])),
                optimal_dte_range=tuple(cf.get("optimal_dte_range", [30, 35])),
                delta_range=tuple(cf.get("delta_range", [0.15, 0.35])),
                optimal_delta_range=tuple(cf.get("optimal_delta_range", [0.20, 0.25])),
                liquidity=LiquidityConfig(
                    max_bid_ask_spread=liq.get("max_bid_ask_spread", 0.10),
                    min_open_interest=liq.get("min_open_interest", 100),
                    min_volume=liq.get("min_volume", 10),
                ),
                metrics=MetricsConfig(
                    min_sharpe_ratio=met.get("min_sharpe_ratio", 1.0),
                    min_sas=met.get("min_sas", 50),
                    max_prei=met.get("max_prei", 75),
                    min_tgr=met.get("min_tgr", 1.0),
                    max_kelly_fraction=met.get("max_kelly_fraction", 0.25),
                ),
            )

        if "output" in data:
            out = data["output"]
            config.output = OutputConfig(
                max_opportunities=out.get("max_opportunities", 10),
                sort_by=out.get("sort_by", "sas"),
                sort_order=out.get("sort_order", "desc"),
            )

        return config

    @classmethod
    def load(cls, strategy: str = "short_put") -> "ScreeningConfig":
        """加载指定策略的配置"""
        config_dir = Path(__file__).parent.parent.parent.parent / "config" / "screening"
        config_file = config_dir / f"{strategy}.yaml"
        if config_file.exists():
            return cls.from_yaml(config_file)
        return cls()
