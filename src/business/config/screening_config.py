"""
Screening Configuration - 筛选配置管理

加载和管理开仓筛选系统的配置参数。

## 系统概述

筛选系统采用 **三层漏斗架构**：

| 层级 | 名称 | 核心问题 | 过滤对象 |
|------|------|----------|----------|
| **Layer 1** | 市场过滤 | 现在是卖期权的好时机吗？ | 市场环境 |
| **Layer 2** | 标的过滤 | 这个标的适合卖期权吗？ | 股票池中的每个标的 |
| **Layer 3** | 合约过滤 | 选择哪个 Strike 和到期日？ | 每个标的的期权合约 |

## 指标优先级体系

| 优先级 | 含义 | 处理方式 | 示例 |
|--------|------|----------|------|
| **P0** | 致命条件 | 不满足 = 立即排除 | Expected ROC < 10% |
| **P1** | 核心条件 | 不满足 = 强烈建议不开仓 | IV Rank < 30%, VIX 极端 |
| **P2** | 重要条件 | 不满足 = 警告，需其他条件补偿 | RSI 超买超卖, Annual ROC |
| **P3** | 参考条件 | 不满足 = 可接受，记录风险 | Sharpe Ratio, Volume |

## Layer 1: 市场过滤器 (MarketFilterConfig)

| 指标 | 优先级 | 条件 | 说明 |
|------|--------|------|------|
| 宏观事件 | P1 | FOMC/CPI/NFP 前2天 | 事件前暂停新开仓 |
| VIX 水平 | P1 | 15~999 (无上限) | VIX > 30 是卖方黄金时刻 |
| VIX 期限结构 | P1 | VIX/VIX3M < 0.9 | >1.0 反向结构=近期风险 |
| VIX Percentile | P2 | 20%~80% | 50%-80% 最佳 |
| SPY/盈富 趋势 | P2 | 符合策略方向 | Short Put 要求看涨/震荡 |

## Layer 2: 标的过滤器 (UnderlyingFilterConfig)

| 指标 | 优先级 | 条件 | 说明 |
|------|--------|------|------|
| **IV Rank** | **P1** | > 30% | 阻塞条件，卖方必须卖"贵"的东西 |
| IV/HV Ratio | P1 | 0.8~2.0 | 隐含波动率相对历史波动率 |
| 财报日期 | P1 | > 7天 | 避免财报博弈 |
| RSI | P2 | 25~85 (策略差异) | Short Put 允许更低 RSI |
| ADX | P2 | < 45 | 避免强趋势行情 |

## Layer 3: 合约过滤器 (ContractFilterConfig)

| 指标 | 优先级 | 条件 | 说明 |
|------|--------|------|------|
| Annual Expected ROC | P0 | > 10% | 年化期望收益率必须为正 |
| TGR | P1 | > 0.5 | Theta/Gamma 比率（标准化） |
| DTE | P1 | 7~45 天 | 港股到期日稀疏，范围宽松 |
| |Delta| | P1 | 0.05~0.35 | 最优 0.20~0.30 |
| Bid-Ask Spread | P1 | < 10% | 流动性指标 |
| Open Interest | P1 | > 100 | 持仓量 |
| Annual ROC | P2 | > 15% | 年化收益率 |
| Win Probability | P3 | > 65% | 理论胜率 |

## 配置文件层次

```
config/screening/
├── stock_pools.yaml       # 股票池定义
├── short_put.yaml         # Short Put 策略配置（覆盖默认值）
└── covered_call.yaml      # Covered Call 策略配置（覆盖默认值）

src/business/config/
└── screening_config.py    # 默认值和数据类定义（本文件）
```

**配置优先级**: YAML 文件 > screening_config.py 默认值
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from src.engine.models.enums import StrategyType


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

    enabled: bool = True  # 是否启用技术面检查（False 时跳过所有 RSI/ADX/SMA 检查）

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
    """标的过滤器配置

    趋势覆盖 (trend_override):
        根据市场趋势自动调整 min_iv_rank。
        YAML 示例:
            trend_override:
              bullish:  { min_iv_rank: 15 }
              bearish:  { min_iv_rank: 40 }
        strong_bullish / strong_bearish 自动回退到 bullish / bearish。
    """

    iv_rank_enabled: bool = True  # 是否启用 IV Rank 检查 (P1)
    min_iv_rank: float = 30.0  # P1: IV Rank 阻塞条件，卖方必须卖"贵"的东西
    iv_hv_enabled: bool = True  # 是否启用 IV/HV 比率检查 (P1)
    max_iv_hv_ratio: float = 2.0
    min_iv_hv_ratio: float = 0.8
    trend_override: dict[str, dict[str, float]] = field(default_factory=dict)
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    fundamental: FundamentalConfig = field(default_factory=FundamentalConfig)
    event_calendar: EventCalendarConfig = field(default_factory=EventCalendarConfig)

    # -- 趋势 fallback 映射 --
    _TREND_FALLBACK: dict[str, str] = field(
        default_factory=lambda: {
            "strong_bullish": "bullish",
            "strong_bearish": "bearish",
        },
        init=False,
        repr=False,
    )

    def get_min_iv_rank(self, trend: str | None = None) -> float:
        """返回考虑趋势覆盖后的有效 min_iv_rank。

        Args:
            trend: TrendStatus.value，如 "bullish" / "strong_bearish" / None

        Returns:
            有效的 min_iv_rank 阈值
        """
        if trend is None or not self.trend_override:
            return self.min_iv_rank

        override = self.trend_override.get(trend)
        if override is None:
            fallback_key = self._TREND_FALLBACK.get(trend)
            if fallback_key:
                override = self.trend_override.get(fallback_key)

        if override is not None:
            return override.get("min_iv_rank", self.min_iv_rank)
        return self.min_iv_rank


@dataclass
class LiquidityConfig:
    """流动性配置"""

    # P1: 目标合约 Bid-Ask Spread
    max_bid_ask_spread: float = 0.10
    # P1: Open Interest
    min_open_interest: int = 0
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

    每个指标都有独立的 enabled 开关，设为 False 时跳过该检查。
    """

    # P0: 期望收益率必须足够高
    expected_roc_enabled: bool = True
    min_expected_roc: float = 0.10
    # P1: Theta/Gamma 比率（标准化公式：|Theta| / (|Gamma| × S² × σ_daily) × 100）
    tgr_enabled: bool = True
    min_tgr: float = 0.5
    # P2: 年化收益率
    annual_roc_enabled: bool = True
    min_annual_roc: float = 0.15
    # P3: 年化夏普比率（参考条件，卖方收益非正态分布）
    sharpe_enabled: bool = True
    min_sharpe_ratio: float = 0.5
    # P3: 胜率
    win_probability_enabled: bool = True
    min_win_probability: float = 0.65
    # P3: 费率（参考条件，已被 Annual ROC 包含）
    premium_rate_enabled: bool = True
    min_premium_rate: float = 0.01
    # P3: Theta/Premium 比率 (每天)
    theta_premium_enabled: bool = True
    min_theta_premium_ratio: float = 0.01
    # P3: Kelly 仓位上限
    kelly_enabled: bool = True
    max_kelly_fraction: float = 0.25
    # P2: 策略吸引力评分
    min_sas: float = 50.0
    # P2: 风险暴露指数 (越低越好)
    max_prei: float = 75.0


@dataclass
class ContractFilterConfig:
    """合约过滤器配置

    统一配置适用于 short_put 和 covered_call 策略。
    """

    # P1: DTE 范围（港股期权到期日稀疏，使用宽范围）
    dte_range: tuple[int, int] = (10, 50)
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
    sort_by: str = "tgr"
    sort_order: str = "desc"


@dataclass
class ScreeningConfig:
    """筛选配置

    支持多交易方向配置:
    - strategy_types: 支持的策略类型列表（如 ["short_put", "covered_call"]）
    - directional_overrides: 方向特定的参数覆盖
    """

    market_filter: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    underlying_filter: UnderlyingFilterConfig = field(
        default_factory=UnderlyingFilterConfig
    )
    contract_filter: ContractFilterConfig = field(default_factory=ContractFilterConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # 新增：支持的策略类型列表
    strategy_types: list[str] = field(default_factory=lambda: ["short_put"])

    # 新增：方向特定参数覆盖
    directional_overrides: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
    ) -> "ScreeningConfig":
        """从 YAML 文件加载配置

        Args:
            path: YAML 文件路径

        Returns:
            ScreeningConfig 实例
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ScreeningConfig":
        """从字典创建配置

        Args:
            data: 配置字典

        Returns:
            ScreeningConfig 实例

        YAML 结构示例:
            market_filter:
              ...
            underlying_filter:
              ...
            contract_filter:
              ...
        """
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
            if "macro_events" in mf:
                me = mf["macro_events"]
                config.market_filter.macro_events = MacroEventConfig(
                    enabled=me.get("enabled", True),
                    blackout_days=me.get("blackout_days", 2),
                    blackout_events=me.get("blackout_events", ["FOMC", "CPI", "NFP"]),
                )

        if "underlying_filter" in data:
            uf = data["underlying_filter"]
            tech = uf.get("technical", {})
            fund = uf.get("fundamental", {})
            config.underlying_filter = UnderlyingFilterConfig(
                iv_rank_enabled=uf.get("iv_rank_enabled", True),
                min_iv_rank=uf.get("min_iv_rank", 50),
                iv_hv_enabled=uf.get("iv_hv_enabled", True),
                max_iv_hv_ratio=uf.get("max_iv_hv_ratio", 2.0),
                min_iv_hv_ratio=uf.get("min_iv_hv_ratio", 0.8),
                trend_override=uf.get("trend_override", {}),
                technical=TechnicalConfig(
                    enabled=tech.get("enabled", True),
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
                    expected_roc_enabled=met.get("expected_roc_enabled", True),
                    min_expected_roc=met.get("min_expected_roc", 0.10),
                    tgr_enabled=met.get("tgr_enabled", True),
                    min_tgr=met.get("min_tgr", 0.5),
                    annual_roc_enabled=met.get("annual_roc_enabled", True),
                    min_annual_roc=met.get("min_annual_roc", 0.15),
                    sharpe_enabled=met.get("sharpe_enabled", True),
                    min_sharpe_ratio=met.get("min_sharpe_ratio", 0.5),
                    win_probability_enabled=met.get("win_probability_enabled", True),
                    min_win_probability=met.get("min_win_probability", 0.65),
                    premium_rate_enabled=met.get("premium_rate_enabled", True),
                    min_premium_rate=met.get("min_premium_rate", 0.01),
                    theta_premium_enabled=met.get("theta_premium_enabled", True),
                    min_theta_premium_ratio=met.get("min_theta_premium_ratio", 0.01),
                    kelly_enabled=met.get("kelly_enabled", True),
                    max_kelly_fraction=met.get("max_kelly_fraction", 0.25),
                    min_sas=met.get("min_sas", 50),
                    max_prei=met.get("max_prei", 75),
                ),
            )

        if "output" in data:
            out = data["output"]
            config.output = OutputConfig(
                max_opportunities=out.get("max_opportunities", 10),
                sort_by=out.get("sort_by", "tgr"),
                sort_order=out.get("sort_order", "desc"),
            )

        # 解析 strategy_types
        if "strategy_types" in data:
            config.strategy_types = data["strategy_types"]

        # 解析 directional_overrides
        if "directional_overrides" in data:
            config.directional_overrides = data["directional_overrides"]

        return config

    def get_market_filter(
        self, strategy_type: "StrategyType"
    ) -> MarketFilterConfig:
        """获取指定策略类型的市场环境筛选参数

        Args:
            strategy_type: 策略类型 (SHORT_PUT / COVERED_CALL)

        Returns:
            合并后的 MarketFilterConfig
        """
        import copy

        direction = strategy_type.value

        # 检查是否有方向特定覆盖
        if direction in self.directional_overrides:
            overrides = self.directional_overrides[direction]
            if "market_filter" in overrides:
                # 深拷贝基础配置，避免修改原配置
                merged = copy.deepcopy(self.market_filter)
                mf_override = overrides["market_filter"]

                # 合并 US Market
                if "us_market" in mf_override:
                    if "trend_required" in mf_override["us_market"]:
                        merged.us_market.trend_required = mf_override["us_market"]["trend_required"]
                    if "vix_range" in mf_override["us_market"]:
                        merged.us_market.vix_range = tuple(mf_override["us_market"]["vix_range"])

                # 合并 HK Market
                if "hk_market" in mf_override:
                    if "trend_required" in mf_override["hk_market"]:
                        merged.hk_market.trend_required = mf_override["hk_market"]["trend_required"]

                return merged

        return self.market_filter

    def get_contract_filter(
        self, strategy_type: "StrategyType"
    ) -> ContractFilterConfig:
        """获取指定策略类型的合约筛选参数

        支持方向特定参数覆盖，如:
        - directional_overrides.covered_call.contract_filter.delta_range

        Args:
            strategy_type: 策略类型 (SHORT_PUT / COVERED_CALL)

        Returns:
            合并后的 ContractFilterConfig
        """
        from src.engine.models.enums import StrategyType
        import copy

        direction = strategy_type.value

        # 检查是否有方向特定覆盖
        if direction in self.directional_overrides:
            overrides = self.directional_overrides[direction]
            if "contract_filter" in overrides:
                # 深拷贝基础配置，避免修改原配置
                merged = copy.deepcopy(self.contract_filter)
                cf_override = overrides["contract_filter"]

                # 合并各字段
                if "delta_range" in cf_override:
                    merged.delta_range = tuple(cf_override["delta_range"])
                if "optimal_delta_range" in cf_override:
                    merged.optimal_delta_range = tuple(cf_override["optimal_delta_range"])
                if "dte_range" in cf_override:
                    merged.dte_range = tuple(cf_override["dte_range"])
                if "optimal_dte_range" in cf_override:
                    merged.optimal_dte_range = tuple(cf_override["optimal_dte_range"])
                if "otm_range" in cf_override:
                    merged.otm_range = tuple(cf_override["otm_range"])

                # 合并 liquidity
                if "liquidity" in cf_override:
                    liq = cf_override["liquidity"]
                    if "max_bid_ask_spread" in liq:
                        merged.liquidity.max_bid_ask_spread = liq["max_bid_ask_spread"]
                    if "min_open_interest" in liq:
                        merged.liquidity.min_open_interest = liq["min_open_interest"]
                    if "min_volume" in liq:
                        merged.liquidity.min_volume = liq["min_volume"]

                # 合并 metrics
                if "metrics" in cf_override:
                    met = cf_override["metrics"]
                    for key in [
                        "expected_roc_enabled", "min_expected_roc",
                        "tgr_enabled", "min_tgr",
                        "annual_roc_enabled", "min_annual_roc",
                        "sharpe_enabled", "min_sharpe_ratio",
                        "win_probability_enabled", "min_win_probability",
                        "premium_rate_enabled", "min_premium_rate",
                        "theta_premium_enabled", "min_theta_premium_ratio",
                        "kelly_enabled", "max_kelly_fraction",
                        "min_sas", "max_prei",
                    ]:
                        if key in met:
                            setattr(merged.metrics, key, met[key])

                return merged

        return self.contract_filter

    def get_underlying_filter(
        self, strategy_type: "StrategyType"
    ) -> UnderlyingFilterConfig:
        """获取指定策略类型的标的分析参数

        支持方向特定参数覆盖，如:
        - directional_overrides.covered_call.underlying_filter.trend_override

        Args:
            strategy_type: 策略类型 (SHORT_PUT / COVERED_CALL)

        Returns:
            合并后的 UnderlyingFilterConfig
        """
        from src.engine.models.enums import StrategyType
        import copy

        direction = strategy_type.value

        # 检查是否有方向特定覆盖
        if direction in self.directional_overrides:
            overrides = self.directional_overrides[direction]
            if "underlying_filter" in overrides:
                # 深拷贝基础配置，避免修改原配置
                merged = copy.deepcopy(self.underlying_filter)
                uf_override = overrides["underlying_filter"]

                # 合并基础字段
                if "iv_rank_enabled" in uf_override:
                    merged.iv_rank_enabled = uf_override["iv_rank_enabled"]
                if "min_iv_rank" in uf_override:
                    merged.min_iv_rank = uf_override["min_iv_rank"]
                if "iv_hv_enabled" in uf_override:
                    merged.iv_hv_enabled = uf_override["iv_hv_enabled"]
                if "max_iv_hv_ratio" in uf_override:
                    merged.max_iv_hv_ratio = uf_override["max_iv_hv_ratio"]
                if "min_iv_hv_ratio" in uf_override:
                    merged.min_iv_hv_ratio = uf_override["min_iv_hv_ratio"]
                if "trend_override" in uf_override:
                    # 合并 trend_override（不是替换）
                    merged.trend_override = {**merged.trend_override, **uf_override["trend_override"]}
                if "technical" in uf_override:
                    tech = uf_override["technical"]
                    if "enabled" in tech:
                        merged.technical.enabled = tech["enabled"]
                    if "min_rsi" in tech:
                        merged.technical.min_rsi = tech["min_rsi"]
                    if "max_rsi" in tech:
                        merged.technical.max_rsi = tech["max_rsi"]
                    if "max_adx" in tech:
                        merged.technical.max_adx = tech["max_adx"]

                return merged

        return self.underlying_filter

    @classmethod
    def load(
        cls,
        strategy_name: str = "short_put",
    ) -> "ScreeningConfig":
        """加载指定策略的配置

        Args:
            strategy_name: 具体的策略名称 (如 short_put_v9)

        Returns:
            ScreeningConfig 实例
        """
        config_dir = Path(__file__).parent.parent.parent.parent / "config" / "screening"
        config_file = config_dir / f"{strategy_name}.yaml"
        if config_file.exists():
            return cls.from_yaml(config_file)
        return cls()

