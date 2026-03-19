"""动量 + 波动率目标 混合策略 (Momentum + Vol Target Mixed Strategy)

用一个参数化策略替代两个旧策略 (~1600 行 → ~200 行)：
- SpyMomentumLevVolTarget → MomentumMixedConfig(use_stock_component=True)
- SpyLeapsOnlyVolTarget   → MomentumMixedConfig(use_stock_component=False, cash_interest_enabled=True)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、信号系统 — 7 分动量评分 + 波动率目标调整
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每日计算 7 分制动量评分 (MomentumVolTargetComputer):
  +1  收盘价 > SMA20
  +1  收盘价 > SMA50
  +1  收盘价 > SMA200
  +1  SMA20 > SMA50
  +1  SMA50 > SMA200
  +1  收盘价 > 20日前收盘价
  +1  收盘价 > 60日前收盘价

评分 → 原始目标敞口 (position_map):
  0-1 分 → 0.0x (全现金)
  2 分   → 0.5x
  3 分   → 1.0x
  4 分   → 1.5x
  5 分   → 2.0x
  6 分   → 2.5x
  7 分   → 3.0x (最大杠杆)

波动率目标调整:
  vol_scalar = min(vol_scalar_max, vol_target / VIX)
  最终目标 = min(max_exposure, 原始目标 × vol_scalar)

  示例: VIX=15 → scalar=1.0; VIX=10 → scalar=1.5; VIX=30 → scalar=0.5

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、进场规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

触发条件 (满足任一):
  1. 无持仓 + 决策日 (每 decision_frequency 天) + target_pct > 0
  2. 有待执行的 roll 换仓 (pending_rebalance)
  3. 有待执行的再平衡加仓 (pending_leaps_topup / pending_stock_topup)

合约选择 (LeapsContractSelector, delta 驱动):
  - DTE 范围: min_dte=180 ~ max_dte=400, 目标 target_dte=252 (~1年)
  - Delta 范围: min_delta=0.50 ~ max_delta=0.85, 目标 target_delta=0.70
  - 多因子评分: delta权重=3.0, 流动性=2.0, 价差=1.5, DTE=0.5
  - 硬性过滤: OI ≥ 100, bid-ask spread ≤ 8%

仓位定量 (delta-adjusted 杠杆):
  contracts = floor(target_pct × NLV / (delta × lot_size × spot))
  现金约束: contracts = min(contracts, floor(0.95 × cash / (mid × lot_size)))

  示例: target=3.0, NLV=$1M, delta=0.70, spot=$500, lot_size=100
        → contracts = floor(3.0 × 1M / (0.70 × 100 × 500)) = 85 张

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、出场规则 (按优先级)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

P10 动量信号归零:
  评分 ≤ 1 → target_pct=0 → 全部清仓 (LEAPS 和股票)
  这是核心的趋势跟踪退出，类似 SMA200 跌破卖出

P10 安全网:
  DTE ≤ 5 → 强制平仓 (防止到期行权风险)

P5  DTE Roll 换仓:
  DTE ≤ roll_dte_threshold (默认60) → 平仓旧合约 + 设置 pending_rebalance
  → 下一步 compute_entry_signals 会自动买入新的 ~252 DTE 合约

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、仓位管理 — 再平衡
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

触发条件:
  |target_pct - current_pct| > rebalance_threshold (默认 0.25, 即 25%)
  且距上次再平衡 ≥ min_rebalance_interval (默认 5 天) — 冷却期

current_pct 的计算:
  股票部分: Σ(qty × spot) / NLV
  LEAPS部分: Σ(delta × qty × lot_size × spot) / NLV

再平衡方向:
  - 超配 (current > target): 卖出多余合约/股票
  - 欠配 (current < target): 设置 pending_topup → 在 entry 阶段买入

注意: 此策略在下跌时会加仓（欠配触发补仓），这是趋势策略的固有行为。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
五、现金利息 (仅 LEAPS-only 模式)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

启用条件: cash_interest_enabled=True (LEAPS-only 模式默认开启)
利率来源: ^TNX (10年期美债收益率)，回退值 4%
计算方式: 每日利息 = max(0, cash) × (rate / 365)
用途: LEAPS 只使用少量资金买合约，大量闲置现金赚取利息

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
六、两种组合模式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Stock+LEAPS 模式 (use_stock_component=True):
  - 股票仓位: min(1.0, target_pct) × NLV — 最多 1x 股票
  - LEAPS仓位: max(0, target_pct - 1.0) × NLV — 超出 1x 的部分用 LEAPS
  - 适合: 希望用股票做底仓 + LEAPS 做杠杆增强

LEAPS-only 模式 (use_stock_component=False):
  - 全部敞口通过 LEAPS Call 实现
  - 闲置现金赚取利息
  - 适合: 纯杠杆策略，资金效率最高
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.strategy.models import (
    AlertType,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)
from src.strategy.protocol import BacktestStrategy
from src.strategy.signals.momentum import (
    MomentumConfig,
    MomentumVolTargetComputer,
)
from src.strategy.cash_sweep import CashSweepConfig, CashSweepMixin
from src.strategy.leaps_selector import LeapsContractSelector, LeapsSelectionConfig

logger = logging.getLogger(__name__)


@dataclass
class MomentumMixedConfig:
    """Configuration for Momentum Mixed strategy."""

    name: str = "momentum_mixed"

    # Signal config (passed to MomentumVolTargetComputer)
    momentum: MomentumConfig = field(default_factory=MomentumConfig)

    # Composition
    use_stock_component: bool = True  # False → pure LEAPS (like LeapsOnly)

    # Decision & rebalance
    decision_frequency: int = 1
    rebalance_threshold: float = 0.25
    min_rebalance_interval: int = 5

    # LEAPS contract parameters (Delta-driven selection)
    target_delta: float = 0.70
    min_delta: float = 0.50
    max_delta: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    roll_dte_threshold: int = 60
    max_capital_pct: float = 0.95

    # Cash interest (LeapsOnly feature, passive — mutually exclusive with cash_sweep)
    cash_interest_enabled: bool = False
    default_risk_free_rate: float = 0.04

    # Cash sweep (active — buy/sell SHV ETF, replaces passive interest)
    cash_sweep_config: CashSweepConfig = field(default_factory=CashSweepConfig)


class MomentumMixedStrategy(BacktestStrategy, CashSweepMixin):
    """Momentum + Vol Target with configurable stock/LEAPS composition.

    Replaces:
    - SpyMomentumLevVolTarget (730 lines) — use_stock_component=True
    - SpyLeapsOnlyVolTarget (627 lines) — use_stock_component=False
    - _momentum_vol_mixin (269 lines) — extracted to MomentumVolTargetComputer
    Total: ~1626 lines → ~200 lines.
    """

    def __init__(self, config: MomentumMixedConfig | None = None) -> None:
        super().__init__()
        self._config = config or MomentumMixedConfig()
        self._momentum = MomentumVolTargetComputer(self._config.momentum)
        self._last_nlv: float = 0.0
        self._last_cash: float = 0.0
        self._last_rebalance_day: int = -9999

        # Cross-method coordination
        self._pending_rebalance: bool = False
        self._pending_leaps_topup: int = 0
        self._pending_stock_topup_pct: float = 0.0

        # Cash interest tracking (for LeapsOnly mode)
        self._cumulative_interest: float = 0.0
        self._tnx_cache: dict[date, float] = {}

        # Cash sweep mixin
        self._cash_sweep_config = self._config.cash_sweep_config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def requires_synthetic_data(self) -> bool:
        return True

    def generate_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Override to inject cash sweep signals after strategy signals."""
        signals = super().generate_signals(market, portfolio, data_provider)

        if not self._cash_sweep_config.enabled:
            return signals

        # Determine if strategy needs cash (pending entries/rolls)
        cash_needed = 0.0
        entry_signals = [s for s in signals if s.type == SignalType.ENTRY]
        for s in entry_signals:
            if s.metadata.get("is_cash_equivalent"):
                continue
            price = s.quote_price or market.get_price_or_zero(s.instrument.underlying)
            if price > 0:
                cash_needed += abs(s.target_quantity) * price * s.instrument.lot_size

        # Cash sweep exits (sell ETF to free up cash) — must come BEFORE entries
        sweep_exits = self.compute_cash_sweep_exits(market, portfolio, cash_needed)
        if sweep_exits:
            self.log("cash_sweep:exit", "pass", count=len(sweep_exits),
                     cash_needed=cash_needed)

        # Cash sweep entries (buy ETF with idle cash, after reserving for strategy entries)
        has_strategy_pos = any(
            p for p in portfolio.positions
            if not (p.instrument.is_stock and p.instrument.underlying in
                    ("SGOV", "SHV", "BIL", "SCHO"))
        )
        sweep_entries = self.compute_cash_sweep_entries(
            market, portfolio, cash_reserved=cash_needed,
            has_strategy_position=has_strategy_pos,
            trading_day=getattr(self, '_day_count', 0),
        )
        if sweep_entries:
            self.log("cash_sweep:entry", "pass", count=len(sweep_entries),
                     cash_reserved=cash_needed)

        # Reorder: exits first → sweep exits → strategy entries → sweep entries
        exit_signals = [s for s in signals if s.type == SignalType.EXIT]
        non_exit_signals = [s for s in signals if s.type != SignalType.EXIT]
        return exit_signals + sweep_exits + non_exit_signals + sweep_entries

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        self._last_nlv = portfolio.nlv
        self._last_cash = portfolio.cash
        self._last_cash_equiv_value = portfolio.cash_equivalent_value
        self._pending_rebalance = False
        self._pending_leaps_topup = 0
        self._pending_stock_topup_pct = 0.0

        stock_pos = portfolio.get_stock_positions()
        leaps_pos = [p for p in portfolio.get_option_positions()
                     if p.instrument.right == OptionRight.CALL and p.quantity > 0]
        self.log("day_start", "info",
                 nlv=portfolio.nlv, cash=portfolio.cash,
                 stock_positions=len(stock_pos), leaps_positions=len(leaps_pos),
                 mode="stock+LEAPS" if self._config.use_stock_component else "LEAPS-only")

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        cfg = self._config
        # Exclude cash-equivalent ETFs (SHV/SGOV) from strategy position lists
        stock_pos = [p for p in portfolio.get_stock_positions()
                     if not p.is_cash_equivalent]
        leaps_pos = [p for p in portfolio.get_option_positions()
                     if p.instrument.right == OptionRight.CALL and p.quantity > 0]

        if not stock_pos and not leaps_pos:
            self.log("exit_scan", "skip", reason="无持仓")
            return []

        result = self._momentum.compute(market, data_provider)
        self._last_signal_detail = result
        target_pct = result["target_pct"]
        data_available = result.get("data_available", True)

        current_pct = self._compute_current_exposure(stock_pos, leaps_pos, market)
        self._last_signal_detail["current_pct"] = current_pct

        self.log("exit_scan:momentum", "info",
                 target_pct=target_pct, current_pct=current_pct,
                 momentum_score=result.get("momentum_score", 0),
                 vix=result.get("vix", 0),
                 data_available=data_available,
                 positions=([f"Stock: {p.instrument.underlying} qty={p.quantity}" for p in stock_pos]
                            + [f"LEAPS: {p.instrument.symbol} qty={p.quantity} DTE={p.dte} delta={p.delta or 0:.2f}" for p in leaps_pos]))

        signals: list[Signal] = []

        # SAFETY: If momentum data is unavailable (price history fetch failed),
        # HOLD positions instead of closing them.
        if not data_available:
            self.log("exit_scan:data_unavailable", "warn",
                     action="HOLD — 数据不可用，保持现有持仓",
                     momentum_score=result.get("momentum_score", 0))
            return []

        # a) target == 0 → exit all (LEAPS first, then stock)
        if target_pct == 0.0:
            score = result.get("momentum_score", 0)
            vix = result.get("vix", 0)
            for pos in leaps_pos:
                signals.append(Signal(
                    type=SignalType.EXIT, instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"Exit: target=0 (score={score}) vix={vix:.1f}",
                    position_id=pos.position_id, priority=10,
                    alert_type=AlertType.VOLTGT_EXIT,
                ))
            for pos in stock_pos:
                signals.append(Signal(
                    type=SignalType.EXIT, instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"Exit: target=0 (score={score}) vix={vix:.1f}",
                    position_id=pos.position_id, priority=10,
                    alert_type=AlertType.VOLTGT_EXIT,
                ))
            self.log("exit_scan:voltgt_exit", "pass",
                     action="全部退出", count=len(signals),
                     momentum_score=score, vix=vix)
            return signals

        # b) LEAPS DTE roll check
        for pos in leaps_pos:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_rebalance = True
                signals.append(Signal(
                    type=SignalType.EXIT, instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"LEAPS roll: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                    position_id=pos.position_id, priority=5,
                    alert_type=AlertType.ROLL_DTE,
                ))

        # DTE <= 5 safety net
        for pos in leaps_pos:
            if pos.dte is not None and pos.dte <= 5:
                if not any(s.position_id == pos.position_id for s in signals):
                    self._pending_rebalance = True
                    signals.append(Signal(
                        type=SignalType.EXIT, instrument=pos.instrument,
                        target_quantity=-pos.quantity,
                        reason=f"Safety net: DTE={pos.dte} <= 5",
                        position_id=pos.position_id, priority=10,
                        alert_type=AlertType.ROLL_DTE,
                    ))

        if signals:
            # Plan roll topup
            closing_ids = {s.position_id for s in signals}
            surviving = [p for p in leaps_pos if p.position_id not in closing_ids]
            surviving_qty = sum(p.quantity for p in surviving)
            target_leaps_pct = target_pct if not cfg.use_stock_component else max(0.0, target_pct - 1.0)
            if target_leaps_pct > 0 and self._last_nlv > 0 and leaps_pos:
                target_contracts = self._compute_leaps_target(
                    target_leaps_pct, leaps_pos[0], market
                )
                self._pending_leaps_topup = max(0, target_contracts - surviving_qty)
            self.log("exit_scan:roll", "pass",
                     closing=len(signals), surviving=surviving_qty,
                     pending_topup=self._pending_leaps_topup,
                     roll_dte_threshold=cfg.roll_dte_threshold)
            return signals

        # c) Rebalance check
        delta_pct = target_pct - current_pct
        if abs(delta_pct) <= cfg.rebalance_threshold:
            self.log("exit_scan:rebalance", "skip",
                     delta_pct=delta_pct,
                     threshold=cfg.rebalance_threshold,
                     reason=f"|{delta_pct:.2f}| <= {cfg.rebalance_threshold}")
            return []
        if not self._rebalance_cooldown_ok(self._last_rebalance_day, cfg.min_rebalance_interval):
            self.log("exit_scan:rebalance", "skip",
                     reason=f"冷却期未满 (间隔要求={cfg.min_rebalance_interval}天)")
            return []

        self.log("exit_scan:rebalance", "info",
                 delta_pct=delta_pct, threshold=cfg.rebalance_threshold,
                 action="触发再平衡")

        signals.extend(self._rebalance_signals(
            stock_pos, leaps_pos, target_pct, current_pct, market
        ))

        if signals or self._pending_stock_topup_pct > 0 or self._pending_rebalance:
            self._last_rebalance_day = self._trading_day_count

        return signals

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        cfg = self._config
        result = self._momentum.compute(market, data_provider)
        target_pct = result["target_pct"]
        data_available = result.get("data_available", True)

        if not data_available:
            self.log("entry_signal:data_unavailable", "warn",
                     action="SKIP — 数据不可用，不开新仓")
            return []

        # Determine if entry needed (exclude cash-equivalent ETFs from position checks)
        stock_pos = [p for p in portfolio.get_stock_positions()
                     if not p.is_cash_equivalent]
        leaps_pos = [p for p in portfolio.get_option_positions()
                     if p.instrument.right == OptionRight.CALL and p.quantity > 0]

        need_entry = False
        entry_reason = ""
        if self._pending_rebalance or self._pending_stock_topup_pct > 0:
            need_entry = True
            entry_reason = f"pending_rebalance={self._pending_rebalance} pending_stock_topup={self._pending_stock_topup_pct:.2f}"
        elif target_pct > 0 and not stock_pos and not leaps_pos:
            if self._is_decision_day(cfg.decision_frequency):
                need_entry = True
                entry_reason = f"无持仓+决策日 (freq={cfg.decision_frequency})"
            else:
                entry_reason = f"无持仓但非决策日 (day={self._trading_day_count} freq={cfg.decision_frequency})"

        if not need_entry or target_pct <= 0:
            self.log("entry_signal:check", "skip",
                     target_pct=target_pct,
                     need_entry=need_entry,
                     reason=entry_reason or (f"target_pct={target_pct:.2f}<=0" if target_pct <= 0 else "无入场条件"))
            return []

        signals: list[Signal] = []
        from src.strategy.cash_sweep import CASH_EQUIVALENT_SYMBOLS
        symbols = [s for s in market.prices.keys() if s not in CASH_EQUIVALENT_SYMBOLS]

        # Compute stock/leaps target allocation
        if self._pending_stock_topup_pct > 0:
            stock_pct = self._pending_stock_topup_pct
        elif cfg.use_stock_component and not stock_pos:
            stock_pct = min(1.0, target_pct)
        else:
            stock_pct = 0.0

        if leaps_pos and self._pending_leaps_topup <= 0:
            leaps_pct = 0.0
        elif cfg.use_stock_component:
            leaps_pct = max(0.0, target_pct - 1.0)
        else:
            leaps_pct = target_pct

        self.log("entry_signal:allocation", "info",
                 target_pct=target_pct, stock_pct=stock_pct, leaps_pct=leaps_pct,
                 nlv=self._last_nlv, cash=self._last_cash,
                 reason=entry_reason)

        for symbol in symbols:
            spot = market.get_price_or_zero(symbol)
            if spot <= 0:
                continue

            # Stock component
            if stock_pct > 0 and cfg.use_stock_component:
                shares = math.floor(stock_pct * self._last_nlv / spot)
                if shares > 0:
                    signals.append(Signal(
                        type=SignalType.ENTRY,
                        instrument=Instrument(InstrumentType.STOCK, symbol, lot_size=1),
                        target_quantity=shares,
                        reason=f"Stock: {shares}sh @ {spot:.2f} target_pct={stock_pct:.2f}",
                        quote_price=spot,
                    ))

            # LEAPS component
            if leaps_pct > 0:
                leaps_signal = self._build_leaps_entry(
                    symbol, spot, leaps_pct, market, data_provider
                )
                if leaps_signal:
                    signals.append(leaps_signal)

        return signals

    # -- Cash Interest (called by executor via duck-typing) --

    def _compute_daily_interest(
        self, cash: float, current_date: date, data_provider: Any
    ) -> float:
        """Compute daily interest on positive cash balance."""
        cfg = self._config
        if self._cash_sweep_config.enabled:
            return 0.0  # Interest comes from actual ETF returns
        if not cfg.cash_interest_enabled or cash <= 0:
            return 0.0
        rate = self._get_risk_free_rate(current_date, data_provider)
        interest = cash * (rate / 365.0)
        self._cumulative_interest += interest
        return interest

    def _get_risk_free_rate(self, current_date: date, data_provider: Any) -> float:
        if current_date in self._tnx_cache:
            return self._tnx_cache[current_date]
        try:
            tnx_data = data_provider.get_macro_data(
                "^TNX", current_date - timedelta(days=7), current_date
            )
            if tnx_data:
                val = tnx_data[-1].close / 1000.0
                self._tnx_cache[current_date] = val
                return val
        except Exception:
            pass
        rate = self._config.default_risk_free_rate
        self._tnx_cache[current_date] = rate
        return rate

    # -- Internal helpers --

    def _compute_current_exposure(
        self,
        stock_pos: list[PositionView],
        leaps_pos: list[PositionView],
        market: MarketSnapshot,
    ) -> float:
        if self._last_nlv <= 0:
            return 0.0
        total = 0.0
        for pos in stock_pos:
            if pos.is_cash_equivalent:
                continue
            spot = market.get_price_or_zero(pos.instrument.underlying)
            total += pos.quantity * spot
        for pos in leaps_pos:
            delta = pos.delta or 0
            spot = market.get_price_or_zero(pos.instrument.underlying)
            total += delta * pos.quantity * pos.lot_size * spot
        return total / self._last_nlv

    def _compute_leaps_target(
        self, target_pct: float, rep: PositionView, market: MarketSnapshot
    ) -> int:
        delta = rep.delta or 0.8
        spot = market.get_price_or_zero(rep.instrument.underlying)
        lot_size = rep.lot_size
        if delta <= 0 or spot <= 0 or self._last_nlv <= 0:
            return 0
        return math.floor(target_pct * self._last_nlv / (delta * lot_size * spot))

    def _rebalance_signals(
        self,
        stock_pos: list[PositionView],
        leaps_pos: list[PositionView],
        target_pct: float,
        current_pct: float,
        market: MarketSnapshot,
    ) -> list[Signal]:
        """Generate rebalance signals (reduce or flag topup)."""
        cfg = self._config
        signals: list[Signal] = []

        # LEAPS rebalance
        target_leaps_pct = target_pct if not cfg.use_stock_component else max(0.0, target_pct - 1.0)
        if leaps_pos:
            total_current = sum(p.quantity for p in leaps_pos)
            rep = leaps_pos[0]
            target_contracts = self._compute_leaps_target(target_leaps_pct, rep, market)
            diff = target_contracts - total_current

            if diff <= -1:
                sell_qty = min(abs(diff), total_current)
                pos = max(leaps_pos, key=lambda p: p.quantity)
                sell_qty = min(sell_qty, pos.quantity)
                if sell_qty > 0:
                    signals.append(Signal(
                        type=SignalType.EXIT, instrument=pos.instrument,
                        target_quantity=-sell_qty,
                        reason=f"LEAPS reduce: {total_current}→{target_contracts}",
                        position_id=pos.position_id, priority=3,
                        alert_type=AlertType.REBALANCE,
                    ))
            elif diff >= 1:
                self._pending_leaps_topup = diff
                self._pending_rebalance = True
        elif target_leaps_pct > 0:
            self._pending_rebalance = True

        # Stock rebalance (only if use_stock_component)
        if cfg.use_stock_component:
            target_stock_pct = min(1.0, target_pct)
            stock_exposure = 0.0
            for pos in stock_pos:
                spot = market.get_price_or_zero(pos.instrument.underlying)
                stock_exposure += pos.quantity * spot
            current_stock_pct = stock_exposure / self._last_nlv if self._last_nlv > 0 else 0.0

            stock_delta = target_stock_pct - current_stock_pct
            if abs(stock_delta) > cfg.rebalance_threshold:
                if stock_delta < 0 and stock_pos:
                    pos = stock_pos[0]
                    spot = market.get_price_or_zero(pos.instrument.underlying)
                    if self._last_nlv > 0 and spot > 0:
                        shares_to_sell = min(
                            math.ceil(abs(stock_delta) * self._last_nlv / spot),
                            abs(pos.quantity),
                        )
                        if shares_to_sell > 0:
                            signals.append(Signal(
                                type=SignalType.EXIT, instrument=pos.instrument,
                                target_quantity=-shares_to_sell,
                                reason=f"Stock reduce: sell {shares_to_sell} shares",
                                position_id=pos.position_id, priority=3,
                                alert_type=AlertType.REBALANCE,
                            ))
                elif stock_delta > 0:
                    self._pending_stock_topup_pct = stock_delta
                    self._pending_rebalance = True

        return signals

    def _build_leaps_entry(
        self,
        symbol: str,
        spot: float,
        leaps_pct: float,
        market: MarketSnapshot,
        data_provider: Any,
    ) -> Optional[Signal]:
        """Find and size a LEAPS Call entry via LeapsContractSelector."""
        cfg = self._config

        # ── Contract selection (delegated to LeapsContractSelector) ──
        selector = LeapsContractSelector()
        sel_config = LeapsSelectionConfig(
            target_dte=cfg.target_dte, min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            target_delta=cfg.target_delta, min_delta=cfg.min_delta, max_delta=cfg.max_delta,
        )
        best = selector.select(
            symbol, spot, market.date, data_provider, sel_config, log_fn=self.log,
        )
        if not best:
            return None

        contract = best.contract
        greeks = best.greeks
        delta = greeks.delta if greeks else 0.0
        mid = best.last_price
        if best.bid is not None and best.ask is not None and best.ask > 0:
            mid = (best.bid + best.ask) / 2
        lot_size = contract.lot_size or 100

        if delta <= 0 or mid <= 0:
            return None

        # ── Sizing ──
        if self._pending_leaps_topup > 0:
            contracts = self._pending_leaps_topup
            self._pending_leaps_topup = 0
        else:
            contracts = math.floor(leaps_pct * self._last_nlv / (delta * lot_size * spot))

        # Cash constraint (include cash-equivalent ETF as available liquidity)
        if cfg.use_stock_component:
            budget = cfg.max_capital_pct * self._last_nlv
        else:
            available = self._last_cash + getattr(self, '_last_cash_equiv_value', 0.0)
            budget = cfg.max_capital_pct * available
        if mid * lot_size > 0:
            max_contracts = math.floor(budget / (mid * lot_size))
            contracts = min(contracts, max_contracts)

        if contracts <= 0:
            self.log(f"sizing:{symbol}", "fail",
                     reason="sizing=0",
                     budget=budget, mid=mid, lot_size=lot_size)
            return None

        dte = (contract.expiry_date - market.date).days
        instrument = Instrument(
            type=InstrumentType.OPTION,
            underlying=symbol,
            right=OptionRight.CALL,
            strike=contract.strike_price,
            expiry=contract.expiry_date,
            lot_size=lot_size,
        )

        return Signal(
            type=SignalType.ENTRY,
            instrument=instrument,
            target_quantity=contracts,
            reason=f"LEAPS: {contracts}x K={contract.strike_price:.0f} DTE={dte} delta={delta:.2f}",
            quote_price=mid,
            greeks={"delta": delta, "gamma": greeks.gamma if greeks else 0,
                    "theta": greeks.theta if greeks else 0, "vega": greeks.vega if greeks else 0,
                    "iv": best.iv or 0},
        )
