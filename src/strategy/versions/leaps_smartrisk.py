"""LEAPS + SmartRisk 3-Tier 风控策略

在 momentum_mixed_v2 基础上叠加 3 层风控，每层覆盖不同的市场风险:

  Tier 1: Panic Circuit Breaker — VIX/VIX3M 期限结构 + VIX 5日飙升
  Tier 2: Bear Market Limiter  — SMA200 下行斜率 + 价格破位
  Tier 3: Volatility Targeting  — min(2, 15/VIX)（保留 V2 原有逻辑）
  保留:   Vega Guard           — VIX 脉冲式飙升减仓 50%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、3-Tier 风控架构
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────────────────────────────────┐
│ L0  动量信号: 7 分评分 → position_map → raw_target (0-3x)  │
├─────────────────────────────────────────────────────────────┤
│ Tier 1: Panic Circuit Breaker                               │
│   VIX/VIX3M ≥ 1.15 → target=0 (严重恐慌，全退出)          │
│   VIX/VIX3M ∈ [1.05, 1.15) → cap 1.0x (温和恐慌)          │
│   VIX 5日涨幅 > 10点 → cap 1.0x (闪崩)                    │
├─────────────────────────────────────────────────────────────┤
│ Tier 2: Bear Market Limiter                                 │
│   SMA200 下行 (SMA200 < SMA200_20d_ago) → cap 1.0x         │
│   价格 < SMA200 → 在 Tier 2 cap 基础上再 × 0.5             │
├─────────────────────────────────────────────────────────────┤
│ Tier 3: Vol Target (保留 V2 原有逻辑)                       │
│   已在 MomentumVolTargetComputer 中计算                     │
│   vol_scalar = min(2.0, 15.0/VIX)                          │
├─────────────────────────────────────────────────────────────┤
│ Vega Guard (保留自 V2):                                     │
│   VIX > 1.3 × SMA20(VIX) → 减仓 50%                       │
└─────────────────────────────────────────────────────────────┘

信号处理顺序:
  raw_target (L0) → Vol Target (Tier 3, 已在 momentum.compute 中)
  → Panic (Tier 1) → Bear Limiter (Tier 2)
  → Vega Guard (独立 EXIT 信号)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、与 V2 / VIXTerm 的差异
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────┬───────────────┬──────────────────┬──────────────────┐
│ 维度             │ V2            │ VIXTerm          │ SmartRisk(本版)  │
├──────────────────┼───────────────┼──────────────────┼──────────────────┤
│ Vol Target       │ ✓             │ ✗ (禁用)         │ ✓ (保留)         │
│ VIX Term         │ ✗             │ ✓                │ ✓ (Tier 1)       │
│ VIX 5d Spike     │ ✗             │ ✗                │ ✓ (Tier 1)       │
│ SMA200 Bear      │ ✗             │ ✗ (Rate代替)     │ ✓ (Tier 2)       │
│ Vega Guard       │ ✓             │ ✓                │ ✓                │
│ 正常市场杠杆     │ 受 Vol Target │ 不受限(pass)     │ 受 Vol Target    │
│ 2022 慢熊保护    │ 弱(VIX缩仓)  │ 弱(Rate失败)     │ 强(SMA200斜率)   │
│ 2020 恐慌保护    │ Vega Guard    │ VIXTerm+Vega     │ Panic+Vega       │
│ 现金管理         │ 被动利息      │ SHV Sweep        │ SHV Sweep        │
└──────────────────┴───────────────┴──────────────────┴──────────────────┘

核心理念: SmartRisk = V2 的 Vol Target 基础 + VIXTerm 的恐慌检测
         + 新增的 SMA200 熊市检测，三层叠加而非替代

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、使用方式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLI:
  uv run backtest run -n "SMARTRISK" -s 2015-01-01 -e 2025-12-31 -S SPY \\
    --strategy-version leaps_smartrisk --skip-download

Registry 名称: "leaps_smartrisk"
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
class PanicBreakerConfig:
    """Tier 1: Panic Circuit Breaker — VIX term structure + 5d spike.

    Calibrated against real VIX/VIX3M distribution (2014-2026):
      P90=0.985, P95=1.019, P99=1.164
    """

    # VIX/VIX3M term structure thresholds
    severe_backwardation: float = 1.15   # ~P99 → target = 0
    mild_backwardation: float = 1.05     # ~P95 → cap at mild_cap

    mild_cap: float = 1.0               # Max leverage during mild backwardation

    # VIX 5-day spike
    vix_5d_spike_pts: float = 10.0      # VIX jumps >10 pts in 5 days → cap
    vix_spike_cap: float = 1.0          # Cap when 5d spike triggers


@dataclass
class BearLimiterConfig:
    """Tier 2: Bear Market Limiter — SMA200 slope + price vs SMA200.

    SMA200 declining = structural bear market (2022 rate hikes, 2018Q4).
    More robust than TNX rate momentum because it responds to actual
    price damage, not just the cause.
    """

    enabled: bool = True
    sma200_lookback: int = 20           # Compare SMA200 now vs N days ago

    declining_cap: float = 1.0          # SMA200 declining → max leverage
    below_sma200_factor: float = 0.5    # Price < SMA200 → multiply cap by this


@dataclass
class LeapsSmartRiskConfig:
    """Configuration for LEAPS + SmartRisk 3-Tier strategy."""

    name: str = "leaps_smartrisk"

    # 3-Tier risk filters
    panic: PanicBreakerConfig = field(default_factory=PanicBreakerConfig)
    bear: BearLimiterConfig = field(default_factory=BearLimiterConfig)

    # Momentum config — Vol Target ENABLED (Tier 3, default V2 behavior)
    momentum: MomentumConfig = field(default_factory=MomentumConfig)

    # LEAPS contract parameters (same as V2)
    target_delta: float = 0.70
    min_delta: float = 0.50
    max_delta: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 550
    max_capital_pct: float = 0.95

    # Theta Guard (same as V2)
    roll_dte_threshold: int = 90

    # Vega Guard (same as V2)
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
class LeapsSmartRiskStrategy(MomentumMixedV2Strategy):
    """LEAPS momentum + SmartRisk 3-Tier risk management.

    Inherits MomentumMixedV2Strategy (Vol Target + Vega Guard intact),
    adds two additional risk layers:
    - Tier 1: Panic Circuit Breaker (VIX term structure + 5d spike)
    - Tier 2: Bear Market Limiter (SMA200 slope + price position)
    """

    def __init__(self, config: LeapsSmartRiskConfig | None = None) -> None:
        sr_cfg = config or LeapsSmartRiskConfig()
        self._panic_config = sr_cfg.panic
        self._bear_config = sr_cfg.bear
        self._vix3m_cache: dict[date, float] = {}
        # Note: self._vix_history is inherited from parent as list[float] (used by Vega Guard)
        self._sma200_history: list[tuple[date, float]] = []  # for slope detection

        # Build V2 config — Vol Target stays enabled (default MomentumConfig)
        v2_config = MomentumMixedV2Config(
            name=sr_cfg.name,
            momentum=sr_cfg.momentum,
            use_stock_component=False,
            cash_interest_enabled=False,
            target_delta=sr_cfg.target_delta,
            min_delta=sr_cfg.min_delta,
            max_delta=sr_cfg.max_delta,
            target_dte=sr_cfg.target_dte,
            min_dte=sr_cfg.min_dte,
            max_dte=sr_cfg.max_dte,
            max_capital_pct=sr_cfg.max_capital_pct,
            roll_dte_threshold=sr_cfg.roll_dte_threshold,
            decision_frequency=sr_cfg.decision_frequency,
            rebalance_threshold=sr_cfg.rebalance_threshold,
            min_rebalance_interval=sr_cfg.min_rebalance_interval,
            # Vega Guard enabled
            vega_guard_enabled=sr_cfg.vega_guard_enabled,
            vega_guard_vix_spike_threshold=sr_cfg.vega_guard_vix_spike_threshold,
            vega_guard_reduce_fraction=sr_cfg.vega_guard_reduce_fraction,
            vega_guard_vix_lookback=sr_cfg.vega_guard_vix_lookback,
            cash_sweep_config=sr_cfg.cash_sweep_config,
        )
        super().__init__(v2_config)

    @property
    def name(self) -> str:
        return self._config.name

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: Any, data_provider: Any
    ) -> list:
        self._apply_smartrisk_filters(market, data_provider)
        return super().compute_exit_signals(market, portfolio, data_provider)

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: Any, data_provider: Any
    ) -> list:
        self._apply_smartrisk_filters(market, data_provider)
        return super().compute_entry_signals(market, portfolio, data_provider)

    # ============================================================
    # SmartRisk 3-Tier Filters
    # ============================================================
    def _apply_smartrisk_filters(
        self, market: MarketSnapshot, data_provider: Any
    ) -> None:
        """Apply Tier 1 (Panic) + Tier 2 (Bear) filters on top of Vol Target."""
        result = self._momentum.compute(market, data_provider)

        if result.get("_smartrisk_filtered"):
            return

        # target_pct already includes Vol Target scaling (Tier 3)
        current_target = result.get("target_pct", 0.0)
        if current_target <= 0:
            result["_smartrisk_filtered"] = True
            return

        adjusted = current_target
        vix = result.get("vix", 20.0)

        # --- Tier 1: Panic Circuit Breaker ---
        panic_regime = "normal"

        # 1a. VIX term structure
        vix3m = self._get_vix3m(market, data_provider)
        ratio = vix / vix3m if vix3m > 0 else 1.0

        pcfg = self._panic_config
        if ratio >= pcfg.severe_backwardation:
            adjusted = 0.0
            panic_regime = "severe_backwardation"
        elif ratio >= pcfg.mild_backwardation:
            adjusted = min(pcfg.mild_cap, adjusted)
            panic_regime = "mild_backwardation"

        # 1b. VIX 5-day spike (uses parent's _vix_history: list[float])
        # Note: _vix_history may not include today's VIX yet (populated in parent's
        # compute_exit_signals which runs after this filter). Use current vix directly.
        if adjusted > 0:
            vix_5d_change = self._get_vix_5d_change(vix)
            if vix_5d_change is not None and vix_5d_change > pcfg.vix_5d_spike_pts:
                adjusted = min(pcfg.vix_spike_cap, adjusted)
                if panic_regime == "normal":
                    panic_regime = "vix_5d_spike"

        # --- Tier 2: Bear Market Limiter ---
        bear_regime = "normal"
        if self._bear_config.enabled and adjusted > 0:
            bear_cap, bear_regime = self._compute_bear_cap(market, data_provider)
            if bear_cap is not None:
                adjusted = min(adjusted, bear_cap)

        # Cap at max_exposure
        adjusted = min(adjusted, self._config.momentum.max_exposure)

        # Update cached result
        result["target_pct"] = adjusted
        result["vix3m"] = vix3m
        result["vixterm_ratio"] = ratio
        result["panic_regime"] = panic_regime
        result["bear_regime"] = bear_regime
        result["_smartrisk_filtered"] = True

        if adjusted != current_target:
            self.log("smartrisk_filter", "pass",
                     vol_target_pct=current_target, adjusted=adjusted,
                     vix=vix, vix3m=vix3m, ratio=f"{ratio:.3f}",
                     panic=panic_regime, bear=bear_regime)

    def _compute_bear_cap(
        self, market: MarketSnapshot, data_provider: Any
    ) -> tuple[float | None, str]:
        """Tier 2: Bear Market Limiter based on SMA200 slope.

        Returns (cap, regime) where cap=None means no constraint.
        """
        bcfg = self._bear_config

        # Get SMA200 and close from momentum's cached data
        result = self._momentum.compute(market, data_provider)
        sma200 = result.get("sma200")
        close = result.get("close")

        if sma200 is None or sma200 <= 0:
            return None, "no_data"

        # Record SMA200 for slope detection
        self._record_sma200(market.date, sma200)

        # Check SMA200 slope (declining = bear market)
        sma200_past = self._get_sma200_n_ago(bcfg.sma200_lookback)

        cap = None
        regime = "normal"

        if sma200_past is not None and sma200 < sma200_past:
            # SMA200 declining → structural bear, no leverage
            cap = bcfg.declining_cap
            regime = "sma200_declining"

            # Price below SMA200 → further reduce
            if close is not None and close < sma200:
                cap = bcfg.declining_cap * bcfg.below_sma200_factor
                regime = "below_sma200"

        return cap, regime

    def _record_sma200(self, dt: date, sma200: float) -> None:
        """Record daily SMA200 for slope detection."""
        if self._sma200_history and self._sma200_history[-1][0] >= dt:
            return
        self._sma200_history.append((dt, sma200))
        # Keep last 60 entries (enough for 20-day lookback with margin)
        if len(self._sma200_history) > 60:
            self._sma200_history = self._sma200_history[-60:]

    def _get_sma200_n_ago(self, n: int) -> float | None:
        """Get SMA200 from N trading days ago."""
        if len(self._sma200_history) <= n:
            return None
        return self._sma200_history[-(n + 1)][1]

    # ============================================================
    # VIX 5-day spike (reuses parent's _vix_history: list[float])
    # ============================================================
    def _get_vix_5d_change(self, current_vix: float) -> float | None:
        """Get VIX change over last 5 trading days.

        Parent's _vix_history may not include today's value yet,
        so we compare current_vix against history[-5].
        """
        if len(self._vix_history) < 5:
            return None
        return current_vix - self._vix_history[-5]

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
