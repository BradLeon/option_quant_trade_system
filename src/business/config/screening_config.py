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
    vix_range: tuple[float, float] = (15.0, 28.0)
    vix_percentile_range: tuple[float, float] = (0.3, 0.8)
    vix3m_symbol: str = "^VIX3M"
    term_structure_threshold: float = 0.9
    trend_indices: list[TrendIndexConfig] = field(default_factory=list)
    trend_required: str = "bullish_or_neutral"
    pcr_symbol: str = "SPY"
    pcr_range: tuple[float, float] = (0.8, 1.2)

    def __post_init__(self) -> None:
        if not self.trend_indices:
            self.trend_indices = [
                TrendIndexConfig(symbol="SPY", weight=0.6),
                TrendIndexConfig(symbol="QQQ", weight=0.4),
            ]


@dataclass
class HKMarketConfig:
    """港股市场配置"""

    volatility_source: str = "2800.HK"
    iv_calculation: str = "atm_weighted"
    iv_range: tuple[float, float] = (18.0, 32.0)
    iv_percentile_range: tuple[float, float] = (0.3, 0.8)
    trend_indices: list[TrendIndexConfig] = field(default_factory=list)
    trend_required: str = "bullish_or_neutral"

    def __post_init__(self) -> None:
        if not self.trend_indices:
            self.trend_indices = [
                TrendIndexConfig(symbol="2800.HK", weight=0.5),
                TrendIndexConfig(symbol="3033.HK", weight=0.5),
            ]


@dataclass
class MarketFilterConfig:
    """市场过滤器配置"""

    us_market: USMarketConfig = field(default_factory=USMarketConfig)
    hk_market: HKMarketConfig = field(default_factory=HKMarketConfig)


@dataclass
class TechnicalConfig:
    """技术面配置"""

    min_rsi: float = 30.0
    max_rsi: float = 70.0
    rsi_stabilizing_range: tuple[float, float] = (30.0, 45.0)
    bb_percent_b_range: tuple[float, float] = (0.1, 0.3)
    max_adx: float = 45.0
    min_sma_alignment: str = "neutral"


@dataclass
class FundamentalConfig:
    """基本面配置"""

    enabled: bool = False
    max_pe_percentile: float = 0.7
    min_recommendation: str = "hold"


@dataclass
class UnderlyingFilterConfig:
    """标的过滤器配置"""

    min_iv_rank: float = 50.0
    max_iv_hv_ratio: float = 2.0
    min_iv_hv_ratio: float = 0.8
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    fundamental: FundamentalConfig = field(default_factory=FundamentalConfig)


@dataclass
class LiquidityConfig:
    """流动性配置"""

    max_bid_ask_spread: float = 0.10
    min_open_interest: int = 100
    min_volume: int = 10


@dataclass
class MetricsConfig:
    """指标配置"""

    min_sharpe_ratio: float = 1.0
    min_sas: float = 50.0
    max_prei: float = 75.0
    min_tgr: float = 0.05
    max_kelly_fraction: float = 0.25


@dataclass
class ContractFilterConfig:
    """合约过滤器配置"""

    dte_range: tuple[int, int] = (25, 45)
    optimal_dte_range: tuple[int, int] = (30, 35)
    delta_range: tuple[float, float] = (-0.35, -0.15)
    optimal_delta_range: tuple[float, float] = (-0.25, -0.20)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)


@dataclass
class OutputConfig:
    """输出配置"""

    max_opportunities: int = 10
    sort_by: str = "sas"
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
                    pcr_symbol=us.get("pcr_symbol", "SPY"),
                    pcr_range=tuple(us.get("pcr_range", [0.8, 1.2])),
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
                delta_range=tuple(cf.get("delta_range", [-0.35, -0.15])),
                optimal_delta_range=tuple(cf.get("optimal_delta_range", [-0.25, -0.20])),
                liquidity=LiquidityConfig(
                    max_bid_ask_spread=liq.get("max_bid_ask_spread", 0.10),
                    min_open_interest=liq.get("min_open_interest", 100),
                    min_volume=liq.get("min_volume", 10),
                ),
                metrics=MetricsConfig(
                    min_sharpe_ratio=met.get("min_sharpe_ratio", 1.0),
                    min_sas=met.get("min_sas", 50),
                    max_prei=met.get("max_prei", 75),
                    min_tgr=met.get("min_tgr", 0.05),
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
