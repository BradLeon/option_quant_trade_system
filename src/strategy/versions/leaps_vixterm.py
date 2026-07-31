"""LEAPS + VIX Term Structure + Rate Momentum 择时策略

在 momentum_mixed_v2 (LEAPS-only + Theta Guard + Vega Guard + Cash Sweep) 上，
叠加两层宏观择时指标:

  Layer 1: VIX/VIX3M 期限结构 — 替代 Vol Target (15/VIX)
  Layer 2: 利率动量 — 捕获渐进式加息周期（2022 型慢熊）
  保留:   Vega Guard — VIX 脉冲式飙升的快速响应

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、三层风控架构
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────┐
│ L0  动量信号: 7 分评分 → position_map → raw_target (0-3x)  │
├─────────────────────────────────────────────────────────────┤
│ L1  VIX 期限结构 (替代 Vol Target):                        │
│     VIX/VIX3M ≥ 1.10 → target=0 (恐慌退出)               │
│     VIX/VIX3M ∈ [1.02, 1.10) → cap 1.0x (去杠杆)         │
│     VIX/VIX3M ∈ [0.98, 1.02) → cap 1.5x (谨慎)           │
│     VIX/VIX3M < 0.98 → pass-through (正常)                │
├─────────────────────────────────────────────────────────────┤
│ L2  利率动量 (新增，捕获渐进式紧缩):                      │
│     TNX 60日变化 > +100bps → cap 1.0x (急速加息)          │
│     TNX 60日变化 > +50bps  → cap 1.5x (温和加息)          │
│     TNX < SMA50(TNX) 且 60d变化 < -30bps → pass (宽松)     │
│     其余 → 不额外限制                                      │
├─────────────────────────────────────────────────────────────┤
│ L3  Vega Guard (保留自 V2):                                │
│     VIX > 1.3 × SMA20(VIX) → 减仓 50%                    │
│     适用场景: VIX 脉冲飙升但期限结构未反转                 │
└─────────────────────────────────────────────────────────────┘

信号处理顺序:
  raw_target (L0) → VIXTerm cap (L1) → RateMomentum cap (L2)
  → Vega Guard (L3, 独立于 target, 直接生成 EXIT 信号)

三层各自覆盖不同的市场风险:
  L1 VIXTerm → 恐慌/危机 (2020 COVID, 2018Q4, 2025 Tariff)
  L2 Rate    → 渐进式紧缩 (2022 加息周期, 2015 缩表)
  L3 Vega    → VIX 脉冲飙升 (局部事件, 闪崩)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、利率动量指标 (Rate Momentum)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用 10 年期国债收益率 (TNX) 的变化速度衡量货币政策紧缩程度:

  rate_change_60d = TNX_today - TNX_60days_ago  (单位: 百分点)
  tnx_above_sma50 = TNX_today > SMA50(TNX)      (趋势确认)

  急速加息 (rate_change_60d > 1.0 且 above_sma50):
    2022-03 ~ 2022-10: TNX 从 1.5% 升至 4.3%，60d 变化 > 150bps
    → cap leverage at 1.0x

  温和加息 (rate_change_60d > 0.8 且 above_sma50):
    ~P95 分位, 2015 加息初期, 2022-01 加息预期升温
    → cap leverage at 1.5x

  宽松/降息 (tnx < sma50 且 rate_change_60d < -0.3):
    → pass-through, 不限制

用 TNX 而非联邦基金利率的原因:
  - TNX 是市场预期利率（前瞻性），联邦基金利率是滞后政策利率
  - TNX 在 yfinance 中有每日数据，无需额外数据源
  - TNX 对加息/降息的反应速度远快于实际政策变化

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、与 V2 / 前版 VIXTerm 的差异
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────┬───────────────┬────────────────┬──────────────────┐
│ 维度             │ V2            │ VIXTerm v1     │ VIXTerm v2(本版) │
├──────────────────┼───────────────┼────────────────┼──────────────────┤
│ Vol Target       │ min(2, 15/VIX)│ ✗ (禁用)       │ ✗ (禁用)         │
│ VIX Term         │ ✗             │ ✓              │ ✓                │
│ Vega Guard       │ ✓             │ ✗ (禁用)       │ ✓ (恢复)         │
│ Rate Momentum    │ ✗             │ ✗              │ ✓ (新增)         │
│ 2022 慢熊保护    │ 弱 (VIX缩仓)  │ 弱             │ 强 (利率动量)    │
│ 2020 恐慌保护    │ Vega Guard    │ VIXTerm        │ VIXTerm+Vega     │
│ 现金管理         │ 被动利息      │ SHV Sweep      │ SHV Sweep        │
└──────────────────┴───────────────┴────────────────┴──────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、使用方式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLI:
  uv run backtest run -n "VIXTERM" -s 2015-01-01 -e 2025-12-31 -S SPY \\
    --strategy-version leaps_vixterm --skip-download

Registry 名称: "leaps_vixterm"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.strategy.cash_sweep import CashSweepConfig
from src.strategy.signals.momentum import MomentumConfig
from src.strategy.models import MarketSnapshot
from src.strategy.versions.momentum_mixed_v2 import (
    MomentumMixedV2Config,
    MomentumMixedV2Strategy,
)

logger = logging.getLogger(__name__)


# ============================================================
# Config
# ============================================================
@dataclass
class VIXTermConfig:
    """VIX/VIX3M term structure filter thresholds.

    Calibrated against real VIX/VIX3M distribution (2014-2026):
      P90=0.985, P95=1.019, P99=1.164
      88.9% contango (<0.98), 6.1% near-flat, 3.1% mild, 1.8% severe
    """

    severe_backwardation: float = 1.15   # ~P99 → target = 0 (true panic only)
    mild_backwardation: float = 1.05     # ~P95-P99 → cap at no_leverage_cap
    near_flat: float = 1.00              # rare flat zone → cap at flat_cap

    no_leverage_cap: float = 1.0         # Mild backwardation → max 1.0x
    flat_cap: float = 2.0               # Near-flat → max 2.0x (moderate cap)


@dataclass
class RateMomentumConfig:
    """Interest rate momentum filter thresholds.

    Uses TNX (10-Year Treasury yield) as the rate proxy.

    Calibrated against real TNX 60-day change distribution (2014-2026):
      P90=0.589pp, P95=0.769pp, P99=1.100pp
      >0.5pp = 12.2% of days (too frequent), >0.8pp = 5.4%, >1.0pp = 1.7%
    """

    enabled: bool = True
    lookback_days: int = 60              # Rate change lookback window
    sma_period: int = 50                 # SMA period for trend confirmation

    # Thresholds (in percentage points, e.g., 1.0 = 100bps)
    aggressive_hike_bps: float = 1.0     # ~P99 >100bps/60d → cap at aggressive_cap
    moderate_hike_bps: float = 0.8       # ~P95 >80bps/60d  → cap at moderate_cap

    aggressive_cap: float = 1.0          # Max leverage during aggressive hikes
    moderate_cap: float = 1.5            # Max leverage during moderate hikes


@dataclass
class LeapsVIXTermConfig:
    """Configuration for LEAPS + VIX Term Structure + Rate Momentum strategy."""

    name: str = "leaps_vixterm"

    # Risk filters
    vixterm: VIXTermConfig = field(default_factory=VIXTermConfig)
    rate_momentum: RateMomentumConfig = field(default_factory=lambda: RateMomentumConfig(enabled=False))

    # Momentum config — disable vol target scaling (VIXTerm replaces it)
    momentum: MomentumConfig = field(default_factory=lambda: MomentumConfig(
        vol_target=999.0,       # Effectively disable vol scaling
        vol_scalar_max=1.0,     # raw_target passes through unchanged
    ))

    # LEAPS contract parameters (same as V2)
    target_delta: float = 0.70
    min_delta: float = 0.50
    max_delta: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    max_capital_pct: float = 0.95

    # Theta Guard (same as V2)
    roll_dte_threshold: int = 90

    # Vega Guard (restored from V2)
    vega_guard_enabled: bool = True
    vega_guard_vix_spike_threshold: float = 1.30
    vega_guard_reduce_fraction: float = 0.50
    vega_guard_vix_lookback: int = 20

    # Decision & rebalance (same as V2)
    decision_frequency: int = 1
    rebalance_threshold: float = 0.25
    min_rebalance_interval: int = 5

    # Cash sweep (SHV)
    cash_sweep_config: CashSweepConfig = field(default_factory=lambda: CashSweepConfig(
        enabled=True,
        instrument_symbol="SHV",
    ))


# ============================================================
# Strategy
# ============================================================
class LeapsVIXTermStrategy(MomentumMixedV2Strategy):
    """LEAPS momentum + VIX term structure + rate momentum + Vega Guard.

    Inherits MomentumMixedV2Strategy, replacing Vol Target with:
    - L1: VIX/VIX3M term structure caps (panic/crisis detection)
    - L2: TNX rate momentum caps (gradual tightening detection)
    Keeps:
    - L3: Vega Guard (VIX spike reduce 50%)
    """

    def __init__(self, config: LeapsVIXTermConfig | None = None) -> None:
        vixterm_cfg = config or LeapsVIXTermConfig()
        self._vixterm_config = vixterm_cfg.vixterm
        self._rate_config = vixterm_cfg.rate_momentum
        self._vix3m_cache: dict[date, float] = {}
        self._tnx_series: list[tuple[date, float]] = []  # (date, value) pairs

        # Build V2 config
        v2_config = MomentumMixedV2Config(
            name=vixterm_cfg.name,
            momentum=vixterm_cfg.momentum,
            use_stock_component=False,
            cash_interest_enabled=False,
            target_delta=vixterm_cfg.target_delta,
            min_delta=vixterm_cfg.min_delta,
            max_delta=vixterm_cfg.max_delta,
            target_dte=vixterm_cfg.target_dte,
            min_dte=vixterm_cfg.min_dte,
            max_dte=vixterm_cfg.max_dte,
            max_capital_pct=vixterm_cfg.max_capital_pct,
            roll_dte_threshold=vixterm_cfg.roll_dte_threshold,
            decision_frequency=vixterm_cfg.decision_frequency,
            rebalance_threshold=vixterm_cfg.rebalance_threshold,
            min_rebalance_interval=vixterm_cfg.min_rebalance_interval,
            # Vega Guard restored
            vega_guard_enabled=vixterm_cfg.vega_guard_enabled,
            vega_guard_vix_spike_threshold=vixterm_cfg.vega_guard_vix_spike_threshold,
            vega_guard_reduce_fraction=vixterm_cfg.vega_guard_reduce_fraction,
            vega_guard_vix_lookback=vixterm_cfg.vega_guard_vix_lookback,
            cash_sweep_config=vixterm_cfg.cash_sweep_config,
        )
        super().__init__(v2_config)

    @property
    def name(self) -> str:
        return self._config.name

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: Any, data_provider: Any
    ) -> list:
        self._apply_macro_filters(market, data_provider)
        return super().compute_exit_signals(market, portfolio, data_provider)

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: Any, data_provider: Any
    ) -> list:
        self._apply_macro_filters(market, data_provider)
        return super().compute_entry_signals(market, portfolio, data_provider)

    # ============================================================
    # Macro Filters
    # ============================================================
    def _apply_macro_filters(
        self, market: MarketSnapshot, data_provider: Any
    ) -> None:
        """Apply VIXTerm + Rate Momentum filters to cached momentum result."""
        result = self._momentum.compute(market, data_provider)

        if result.get("_macro_filtered"):
            return

        raw_target = result.get("raw_target", 0.0)
        if raw_target <= 0:
            result["_macro_filtered"] = True
            return

        # --- L1: VIX Term Structure ---
        adjusted = raw_target
        vix = result.get("vix", 20.0)
        vix3m = self._get_vix3m(market, data_provider)
        ratio = vix / vix3m if vix3m > 0 else 1.0

        cfg = self._vixterm_config
        if ratio >= cfg.severe_backwardation:
            adjusted = 0.0
            regime = "severe_backwardation"
        elif ratio >= cfg.mild_backwardation:
            adjusted = min(cfg.no_leverage_cap, adjusted)
            regime = "mild_backwardation"
        elif ratio >= cfg.near_flat:
            adjusted = min(cfg.flat_cap, adjusted)
            regime = "near_flat"
        else:
            regime = "contango"

        # --- L2: Rate Momentum ---
        rate_regime = "neutral"
        if self._rate_config.enabled and adjusted > 0:
            rate_cap, rate_regime = self._compute_rate_cap(market, data_provider)
            if rate_cap is not None:
                adjusted = min(adjusted, rate_cap)

        # Cap at max_exposure
        adjusted = min(adjusted, self._config.momentum.max_exposure)

        # Update cached result
        result["target_pct"] = adjusted
        result["vix3m"] = vix3m
        result["vixterm_ratio"] = ratio
        result["vixterm_regime"] = regime
        result["rate_regime"] = rate_regime
        result["_macro_filtered"] = True

        if adjusted != raw_target:
            self.log("macro_filter", "pass",
                     raw_target=raw_target, adjusted=adjusted,
                     vix=vix, vix3m=vix3m, ratio=f"{ratio:.3f}",
                     vixterm=regime, rate=rate_regime)

    def _compute_rate_cap(
        self, market: MarketSnapshot, data_provider: Any
    ) -> tuple[float | None, str]:
        """Compute leverage cap based on TNX rate momentum.

        Returns (cap, regime) where cap=None means no constraint.
        """
        cfg = self._rate_config

        # Build TNX series if empty or stale
        self._ensure_tnx_series(market, data_provider)
        if len(self._tnx_series) < cfg.lookback_days:
            return None, "insufficient_data"

        # Current TNX
        tnx_now = self._tnx_series[-1][1]

        # TNX N days ago
        target_idx = len(self._tnx_series) - cfg.lookback_days
        if target_idx < 0:
            return None, "insufficient_data"
        tnx_past = self._tnx_series[target_idx][1]

        # Rate change in percentage points (e.g., 1.5% → 4.5% = +3.0)
        rate_change = tnx_now - tnx_past

        # SMA trend confirmation
        sma_window = min(cfg.sma_period, len(self._tnx_series))
        tnx_sma = sum(v for _, v in self._tnx_series[-sma_window:]) / sma_window
        above_sma = tnx_now > tnx_sma

        # Rate hike detection (only when TNX is trending up)
        if above_sma and rate_change > cfg.aggressive_hike_bps:
            return cfg.aggressive_cap, "aggressive_hike"
        if above_sma and rate_change > cfg.moderate_hike_bps:
            return cfg.moderate_cap, "moderate_hike"

        return None, "neutral"

    def _ensure_tnx_series(
        self, market: MarketSnapshot, data_provider: Any
    ) -> None:
        """Load TNX history into _tnx_series if needed."""
        # Only reload if we don't have data up to current date
        if self._tnx_series and self._tnx_series[-1][0] >= market.date:
            return

        cfg = self._rate_config
        lookback = max(cfg.lookback_days, cfg.sma_period) + 30
        start = market.date - timedelta(days=int(lookback * 1.5))

        try:
            tnx_data = data_provider.get_macro_data("^TNX", start, market.date)
            if tnx_data:
                self._tnx_series = [
                    (d.date, d.close) for d in tnx_data
                    if d.close is not None and d.close > 0
                ]
        except Exception:
            pass

    # ============================================================
    # VIX3M Helper
    # ============================================================
    def _get_vix3m(self, market: MarketSnapshot, data_provider: Any) -> float:
        if market.date in self._vix3m_cache:
            return self._vix3m_cache[market.date]

        vix3m = 20.0
        try:
            lookback = market.date - timedelta(days=10)
            vix3m_data = data_provider.get_macro_data("^VIX3M", lookback, market.date)
            if vix3m_data and len(vix3m_data) > 0:
                vix3m = vix3m_data[-1].value
        except Exception:
            pass

        self._vix3m_cache[market.date] = vix3m
        return vix3m

    def on_day_end(
        self, market: MarketSnapshot, portfolio: Any, data_provider: Any,
    ) -> dict:
        detail = dict(self._last_signal_detail)
        if "vixterm_ratio" not in detail:
            vix3m = self._get_vix3m(market, data_provider)
            vix = detail.get("vix", 20.0)
            detail["vix3m"] = vix3m
            detail["vixterm_ratio"] = vix / vix3m if vix3m > 0 else 1.0
        return detail
