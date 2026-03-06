"""
归因系统数据模型

定义持仓快照、组合快照、归因结果、切片统计、Regime 标签等数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# ============================================================
# 快照模型 (由 AttributionCollector 每日采集)
# ============================================================


@dataclass
class PositionSnapshot:
    """每日持仓快照

    记录单个持仓在某交易日结束时的完整状态。
    Greeks 为 position-level 值（已乘 quantity），与 PositionData 一致。
    """

    date: date
    position_id: str
    underlying: str
    symbol: str  # 期权合约标识
    option_type: str  # "put" / "call"
    strike: float
    expiration: date
    quantity: int  # 正=多头, 负=空头
    lot_size: int  # 每张合约股数 (通常 100)

    # 价格
    underlying_price: float
    option_mid_price: float

    # 波动率
    iv: float | None = None  # 隐含波动率 (decimal, e.g. 0.30)
    hv: float | None = None  # 20 日历史波动率
    iv_hv_ratio: float | None = None
    iv_rank: float | None = None  # 0-100
    iv_percentile: float | None = None  # 0-100

    # Greeks (position-level: raw_greek * qty 或 raw_greek * abs(qty))
    delta: float | None = None  # raw_delta * qty
    gamma: float | None = None  # raw_gamma * abs(qty)
    theta: float | None = None  # raw_theta * qty (daily)
    vega: float | None = None  # raw_vega * abs(qty) (per 1% IV)

    # 市值与盈亏
    market_value: float = 0.0
    unrealized_pnl: float = 0.0

    # 持仓属性
    moneyness_pct: float = 0.0  # OTM%
    dte: int = 0

    # 开仓信息 (不变)
    entry_price: float = 0.0
    entry_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "position_id": self.position_id,
            "underlying": self.underlying,
            "symbol": self.symbol,
            "option_type": self.option_type,
            "strike": self.strike,
            "expiration": self.expiration.isoformat(),
            "quantity": self.quantity,
            "lot_size": self.lot_size,
            "underlying_price": self.underlying_price,
            "option_mid_price": self.option_mid_price,
            "iv": self.iv,
            "hv": self.hv,
            "iv_hv_ratio": self.iv_hv_ratio,
            "iv_rank": self.iv_rank,
            "iv_percentile": self.iv_percentile,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "moneyness_pct": self.moneyness_pct,
            "dte": self.dte,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
        }


@dataclass
class PortfolioSnapshot:
    """每日组合快照

    记录整个组合在某交易日结束时的聚合指标。
    """

    date: date
    nlv: float
    cash: float
    margin_used: float
    position_count: int
    daily_pnl: float = 0.0

    # 组合 Greeks (绝对值)
    portfolio_delta: float = 0.0
    beta_weighted_delta: float | None = None
    portfolio_gamma: float = 0.0
    portfolio_theta: float = 0.0
    portfolio_vega: float = 0.0

    # NLV 归一化百分比
    beta_weighted_delta_pct: float | None = None
    gamma_pct: float | None = None
    theta_pct: float | None = None
    vega_pct: float | None = None

    # 质量与风险指标
    vega_weighted_iv_hv: float | None = None
    portfolio_tgr: float | None = None
    concentration_hhi: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "nlv": self.nlv,
            "cash": self.cash,
            "margin_used": self.margin_used,
            "position_count": self.position_count,
            "daily_pnl": self.daily_pnl,
            "portfolio_delta": self.portfolio_delta,
            "beta_weighted_delta": self.beta_weighted_delta,
            "portfolio_gamma": self.portfolio_gamma,
            "portfolio_theta": self.portfolio_theta,
            "portfolio_vega": self.portfolio_vega,
            "beta_weighted_delta_pct": self.beta_weighted_delta_pct,
            "gamma_pct": self.gamma_pct,
            "theta_pct": self.theta_pct,
            "vega_pct": self.vega_pct,
            "vega_weighted_iv_hv": self.vega_weighted_iv_hv,
            "portfolio_tgr": self.portfolio_tgr,
            "concentration_hhi": self.concentration_hhi,
        }


# ============================================================
# 归因结果模型 (由 PnLAttributionEngine 计算)
# ============================================================


@dataclass
class PositionDailyAttribution:
    """单持仓单日归因"""

    position_id: str
    underlying: str
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    theta_pnl: float = 0.0
    vega_pnl: float = 0.0
    residual: float = 0.0
    actual_pnl: float = 0.0
    underlying_move: float = 0.0  # ΔS
    underlying_move_pct: float = 0.0  # ΔS / S_prev
    iv_change: float = 0.0  # ΔIV (decimal)


@dataclass
class DailyAttribution:
    """每日组合级别归因"""

    date: date
    total_pnl: float = 0.0
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    theta_pnl: float = 0.0
    vega_pnl: float = 0.0
    residual: float = 0.0

    # 各因子占总 PnL 的百分比
    delta_pnl_pct: float = 0.0
    gamma_pnl_pct: float = 0.0
    theta_pnl_pct: float = 0.0
    vega_pnl_pct: float = 0.0

    # 上下文
    positions_count: int = 0

    # 逐持仓明细
    position_attributions: list[PositionDailyAttribution] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "total_pnl": self.total_pnl,
            "delta_pnl": self.delta_pnl,
            "gamma_pnl": self.gamma_pnl,
            "theta_pnl": self.theta_pnl,
            "vega_pnl": self.vega_pnl,
            "residual": self.residual,
            "delta_pnl_pct": self.delta_pnl_pct,
            "gamma_pnl_pct": self.gamma_pnl_pct,
            "theta_pnl_pct": self.theta_pnl_pct,
            "vega_pnl_pct": self.vega_pnl_pct,
            "positions_count": self.positions_count,
        }


@dataclass
class TradeAttribution:
    """单笔交易归因（从开仓到平仓的累计）"""

    trade_id: str  # = position_id
    symbol: str
    underlying: str
    option_type: str
    strike: float
    entry_date: date
    exit_date: date | None = None
    exit_reason: str | None = None
    exit_reason_type: str | None = None  # CloseReasonType.value
    holding_days: int = 0

    # 累计归因
    total_pnl: float = 0.0
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    theta_pnl: float = 0.0
    vega_pnl: float = 0.0
    residual: float = 0.0

    # 开/平仓上下文
    entry_iv: float | None = None
    exit_iv: float | None = None
    entry_underlying: float = 0.0
    exit_underlying: float = 0.0
    entry_iv_rank: float | None = None
    quantity: int = 0
    entry_price: float = 0.0  # 期权开仓价格 (per share)
    lot_size: int = 100  # 合约乘数

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "underlying": self.underlying,
            "option_type": self.option_type,
            "strike": self.strike,
            "entry_date": self.entry_date.isoformat(),
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_reason": self.exit_reason,
            "exit_reason_type": self.exit_reason_type,
            "holding_days": self.holding_days,
            "total_pnl": self.total_pnl,
            "delta_pnl": self.delta_pnl,
            "gamma_pnl": self.gamma_pnl,
            "theta_pnl": self.theta_pnl,
            "vega_pnl": self.vega_pnl,
            "residual": self.residual,
            "entry_iv": self.entry_iv,
            "exit_iv": self.exit_iv,
            "entry_underlying": self.entry_underlying,
            "exit_underlying": self.exit_underlying,
            "entry_iv_rank": self.entry_iv_rank,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "lot_size": self.lot_size,
        }


# ============================================================
# 切片归因模型 (由 SliceAttributionEngine 计算)
# ============================================================


@dataclass
class SliceStats:
    """切片归因统计"""

    label: str
    trade_count: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    pnl_contribution_pct: float = 0.0  # 占总 PnL 百分比

    # Greeks 归因分解
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    theta_pnl: float = 0.0
    vega_pnl: float = 0.0
    residual: float = 0.0

    # 其他统计
    avg_holding_days: float = 0.0
    max_win: float = 0.0
    max_loss: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "trade_count": self.trade_count,
            "total_pnl": self.total_pnl,
            "avg_pnl": self.avg_pnl,
            "win_rate": self.win_rate,
            "pnl_contribution_pct": self.pnl_contribution_pct,
            "delta_pnl": self.delta_pnl,
            "gamma_pnl": self.gamma_pnl,
            "theta_pnl": self.theta_pnl,
            "vega_pnl": self.vega_pnl,
            "residual": self.residual,
            "avg_holding_days": self.avg_holding_days,
            "max_win": self.max_win,
            "max_loss": self.max_loss,
        }


# ============================================================
# Regime 模型 (由 RegimeAnalyzer 计算)
# ============================================================


@dataclass
class DayRegime:
    """日级别市场 Regime 标签"""

    date: date
    vix_close: float = 0.0
    vix_level: str = "NORMAL"  # LOW / NORMAL / ELEVATED / HIGH
    vix_trend: str = "STABLE"  # RISING / FALLING / STABLE
    spy_trend: str = "NEUTRAL"  # BULLISH / BEARISH / NEUTRAL
    event_type: str = "NONE"  # FOMC / CPI / JOBS / NONE
    regime_label: str = ""  # 综合标签, e.g. "HIGH_VOL_BEARISH_FOMC"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "vix_close": self.vix_close,
            "vix_level": self.vix_level,
            "vix_trend": self.vix_trend,
            "spy_trend": self.spy_trend,
            "event_type": self.event_type,
            "regime_label": self.regime_label,
        }


@dataclass
class RegimeStats:
    """Regime 归因统计"""

    regime_label: str
    trading_days: int = 0
    total_pnl: float = 0.0
    avg_daily_pnl: float = 0.0
    win_rate: float = 0.0  # 盈利天数占比
    max_daily_loss: float = 0.0
    sharpe_ratio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime_label": self.regime_label,
            "trading_days": self.trading_days,
            "total_pnl": self.total_pnl,
            "avg_daily_pnl": self.avg_daily_pnl,
            "win_rate": self.win_rate,
            "max_daily_loss": self.max_daily_loss,
            "sharpe_ratio": self.sharpe_ratio,
        }


# ============================================================
# 策略诊断模型 (由 StrategyDiagnosis 计算)
# ============================================================


@dataclass
class TradeEntryQuality:
    """单笔交易入场质量"""

    trade_id: str
    underlying: str
    entry_iv: float | None = None
    realized_vol: float | None = None
    iv_rv_spread: float | None = None  # IV - RV
    vrp_captured: float | None = None  # (IV - RV) * Vega
    entry_iv_rank: float | None = None
    entry_iv_percentile: float | None = None


@dataclass
class EntryQualityReport:
    """入场质量分析报告"""

    trades: list[TradeEntryQuality] = field(default_factory=list)
    avg_entry_iv_rank: float | None = None
    high_iv_entry_pct: float = 0.0  # IV Rank > 50% 的开仓占比
    avg_iv_rv_spread: float | None = None  # 平均 IV - RV
    positive_vrp_pct: float = 0.0  # VRP > 0 的交易占比


@dataclass
class TradeExitQuality:
    """单笔交易出场质量"""

    trade_id: str
    underlying: str
    exit_reason: str
    actual_pnl: float = 0.0
    pnl_if_held_to_expiry: float | None = None
    exit_benefit: float | None = None  # actual - if_held (正=正确退出)
    was_good_exit: bool | None = None  # exit_benefit > 0
    entry_date: date | None = None
    expiration: date | None = None
    actual_ann_return: float | None = None  # 实际年化收益率
    held_ann_return: float | None = None  # 持有到期年化收益率
    verdict_reason: str = ""  # "benefit" / "freed_capital" / "better_ann_return" / ""


@dataclass
class ExitQualityReport:
    """出场质量分析报告"""

    trades: list[TradeExitQuality] = field(default_factory=list)
    good_exit_rate: float = 0.0
    avg_exit_benefit: float = 0.0
    total_saved_by_exit: float = 0.0  # 风控挽救的损失
    total_lost_by_exit: float = 0.0  # 风控损失的利润
    net_exit_value: float = 0.0  # saved - lost


@dataclass
class ReversalReport:
    """止损后反转率分析报告"""

    total_stop_loss_trades: int = 0
    reversal_count: int = 0  # 止损后持有到期反而盈利的笔数
    reversal_rate: float = 0.0
    avg_reversal_magnitude: float = 0.0  # 反转交易的平均额外收益

    # 按止损原因分组
    by_exit_reason: dict[str, dict[str, float]] = field(default_factory=dict)
