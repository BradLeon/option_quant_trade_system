"""Short Put Spread Overlay — 在闲置保证金上卖 Bull Put Spread 赚取权利金

设计为叠加层 (overlay)，由主策略 (如 MomentumMixedV2) 调用，
不独立运行。与主策略使用同一标的（如 SPY/QQQ），形成天然
synthetic covered call 效果（long LEAPS call + short put）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、合约选择
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

默认模式: Bull Put Spread (定义风险)
  - Short leg: OTM Put, delta ∈ [0.15, 0.25], 目标 0.20
  - Long leg:  Short strike - spread_width ($5), 同到期日
  - DTE 范围: [30, 45] 天 (theta 衰减最快区间)

可选模式: Naked Short Put (use_spread=False)
  - 更高权利金收入，但无上限亏损
  - 保证金要求更高: max(20% × spot, 10% × strike) × 100

合约筛选流程:
  1. 获取标的 option chain，过滤 DTE 范围内的到期日
  2. 选最近月的到期日 (sorted, 取第一个)
  3. 按 delta 筛选: |delta| ∈ [min_delta, max_delta]
  4. 取 |delta| 最接近 target_delta 的 put 作为 short leg
  5. 在同到期日找 strike 最接近 (short_strike - spread_width) 的 put 作为 long leg
  6. 验证: short_price > long_price (有正 net credit)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、仓位控制
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

可用保证金:
  idle = cash + cash_equivalent_value - NLV × min_cash_reserve_pct (10%)
  available_margin = idle × max_margin_pct (50%)

Spread 数量:
  margin_per_spread = spread_width × 100 - net_credit × 100  (定义风险 = 最大亏损)
  num_spreads = min(floor(available_margin / margin_per_spread),
                    max_spreads - current_spreads)

VIX 缩放 (降低高波动环境下的仓位):
  VIX < 25  → size_factor = 1.0  (全仓)
  VIX ∈ [25, 30) → size_factor = 0.5  (半仓)
  VIX ∈ [30, 35) → size_factor = 0.25 (1/4 仓)
  VIX ≥ 35  → 不开新仓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、入场门控 (Gating)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

以下条件全部满足才开仓:
  G1. momentum_score > 0  — 主策略看多才卖 put
  G2. has_leaps_position   — 有 LEAPS 主仓位才叠加
  G3. VIX < vix_no_new (35) — 极高波动率不开新仓
  G4. 未在 VIX spike 冷却期内
  G5. current_spreads < max_spreads (10)
  G6. available_margin > 0

决策频率: 每 decision_frequency (3) 个交易日检查一次

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、退出规则 (按优先级)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

P9  VIX Spike 全部平仓:
  VIX 单日涨幅 > vix_spike_pct (20%) → 关闭所有 overlay + 冷却 vix_cooldown_days (5天)
  原因: VIX 飙升 = 恐慌抛售，short put 亏损概率骤升

P8  Momentum=0 全部平仓:
  主策略动量评分归零 → 关闭所有 overlay
  原因: 趋势反转，不再做多方向操作

P5  止盈:
  unrealized_pnl / entry_credit ≥ profit_target_pct (50%)
  原因: 收获大部分利润，释放保证金给下一轮

P5  DTE 退出:
  DTE ≤ dte_exit (7天) → 平仓
  原因: 临近到期 gamma 风险飙升，收益/风险比恶化

注意: spread 的两条腿 (short + long) 同时平仓。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from src.strategy.models import (
    AlertType,
    ComboInstrument,
    ComboLeg,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)

logger = logging.getLogger(__name__)


@dataclass
class ShortPutOverlayConfig:
    """Configuration for the short put spread overlay."""

    # Contract selection
    target_delta: float = 0.20
    min_delta: float = 0.15
    max_delta: float = 0.25
    target_dte_min: int = 30
    target_dte_max: int = 45
    spread_width: float = 5.0  # $ distance between strikes
    use_spread: bool = True  # True=bull put spread, False=naked put

    # Position sizing
    max_margin_pct: float = 0.50  # Max % of idle cash used for margin
    max_spreads: int = 10  # Max concurrent spread positions
    min_cash_reserve_pct: float = 0.10  # Keep 10% NLV as cash floor

    # VIX gating
    vix_half_size: float = 25.0  # VIX > 25 → half position
    vix_quarter_size: float = 30.0  # VIX > 30 → quarter position
    vix_no_new: float = 35.0  # VIX > 35 → no new spreads
    vix_spike_pct: float = 0.20  # VIX daily jump > 20% → close all
    vix_cooldown_days: int = 5  # Days to wait after VIX spike

    # Exit rules
    profit_target_pct: float = 0.50  # Close at 50% of max profit
    dte_exit: int = 7  # Close when DTE < 7

    # Linkage with primary strategy
    require_leaps_position: bool = True  # Only open when LEAPS exist
    require_positive_momentum: bool = True  # Only open when momentum > 0

    # Decision frequency
    decision_frequency: int = 3  # Check every N trading days


class ShortPutOverlay:
    """Generates bull put spread entry/exit signals on idle cash.

    Not a standalone strategy — meant to be called by a parent strategy
    that provides momentum context and portfolio state.
    """

    def __init__(self, config: ShortPutOverlayConfig | None = None) -> None:
        self._config = config or ShortPutOverlayConfig()
        self._prev_vix: float = 0.0
        self._cooldown_until: Optional[date] = None
        self._trading_day_count: int = 0

        # Logging callback (set by parent strategy)
        self._log_fn: Any = None

    def log(self, step: str, status: str, **detail) -> None:
        if self._log_fn:
            self._log_fn(f"overlay:{step}", status, **detail)

    def compute_exit_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        momentum_score: int,
        vix: float,
    ) -> list[Signal]:
        """Generate exit signals for existing overlay positions.

        Args:
            market: Current market snapshot
            portfolio: Current portfolio state
            momentum_score: From primary strategy's momentum computer
            vix: Current VIX level
        """
        cfg = self._config
        signals: list[Signal] = []

        # Find overlay short put positions
        short_puts = self._get_overlay_short_puts(portfolio)
        if not short_puts:
            return signals

        # VIX spike check — close ALL overlay positions
        if self._check_vix_spike(vix, market.date):
            for pos in short_puts:
                signals.append(self._make_exit_signal(
                    pos, f"VIX spike: {vix:.1f} (prev={self._prev_vix:.1f})",
                    priority=9,
                ))
                # Also close matching long leg
                long_exit = self._find_long_leg_exit(pos, portfolio)
                if long_exit:
                    signals.append(long_exit)
            self.log("vix_spike_exit", "pass",
                     vix=vix, prev_vix=self._prev_vix,
                     positions_closed=len(short_puts))
            return signals

        # Momentum zero — close ALL overlay positions
        if cfg.require_positive_momentum and momentum_score == 0:
            for pos in short_puts:
                signals.append(self._make_exit_signal(
                    pos, f"Momentum=0, close overlay",
                    priority=8,
                ))
                long_exit = self._find_long_leg_exit(pos, portfolio)
                if long_exit:
                    signals.append(long_exit)
            self.log("momentum_exit", "pass",
                     momentum_score=momentum_score,
                     positions_closed=len(short_puts))
            return signals

        # Per-position exit checks
        long_puts_index = self._build_long_puts_index(portfolio)

        for pos in short_puts:
            should_close = False
            reason = ""

            # DTE exit
            if pos.dte is not None and pos.dte <= cfg.dte_exit:
                should_close = True
                reason = f"DTE exit: {pos.dte} <= {cfg.dte_exit}"

            # Profit target
            if not should_close and pos.entry_price > 0:
                entry_credit = pos.entry_price * abs(pos.quantity) * pos.lot_size
                if entry_credit > 0:
                    profit_pct = pos.unrealized_pnl / entry_credit
                    if profit_pct >= cfg.profit_target_pct:
                        should_close = True
                        reason = f"Profit target: {profit_pct:.0%} >= {cfg.profit_target_pct:.0%}"

            if should_close:
                signals.append(self._make_exit_signal(pos, reason, priority=5))
                # Close matching long leg
                long_key = (pos.instrument.underlying, pos.instrument.expiry)
                for key, long_pos in long_puts_index.items():
                    if key[0] == long_key[0] and key[1] == long_key[1]:
                        signals.append(Signal(
                            type=SignalType.EXIT,
                            instrument=long_pos.instrument,
                            target_quantity=-long_pos.quantity,
                            reason=f"Close long leg: {reason}",
                            position_id=long_pos.position_id,
                            priority=5,
                            alert_type=AlertType.SPREAD_CLOSE,
                            metadata={"is_overlay": True},
                        ))
                        break
            else:
                self.log(f"exit_scan:{pos.instrument.symbol}", "skip",
                         dte=pos.dte, pnl=pos.unrealized_pnl)

        return signals

    def compute_entry_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
        momentum_score: int,
        vix: float,
        has_leaps_position: bool,
    ) -> list[Signal]:
        """Generate entry signals for new overlay positions.

        Args:
            market: Current market snapshot
            portfolio: Current portfolio state
            data_provider: For option chain data
            momentum_score: From primary strategy
            vix: Current VIX level
            has_leaps_position: Whether primary strategy has active LEAPS
        """
        self._trading_day_count += 1
        cfg = self._config

        # Update VIX tracking
        if vix > 0:
            self._prev_vix = vix

        # Decision frequency gate
        if self._trading_day_count % cfg.decision_frequency != 0:
            return []

        # Gating conditions
        if cfg.require_positive_momentum and momentum_score == 0:
            self.log("entry_gate", "fail", reason="momentum=0")
            return []

        if cfg.require_leaps_position and not has_leaps_position:
            self.log("entry_gate", "fail", reason="no LEAPS position")
            return []

        if vix >= cfg.vix_no_new:
            self.log("entry_gate", "fail", reason=f"VIX={vix:.1f} >= {cfg.vix_no_new}")
            return []

        if self._cooldown_until and market.date <= self._cooldown_until:
            self.log("entry_gate", "fail",
                     reason=f"cooldown until {self._cooldown_until}")
            return []

        # Position capacity check
        current_spreads = len(self._get_overlay_short_puts(portfolio))
        if current_spreads >= cfg.max_spreads:
            self.log("entry_gate", "fail",
                     reason=f"max spreads {current_spreads}/{cfg.max_spreads}")
            return []

        # Available margin for overlay
        available_margin = self._calc_available_margin(portfolio)
        if available_margin <= 0:
            self.log("entry_gate", "fail", reason="no available margin")
            return []

        # VIX-scaled sizing
        size_factor = self._vix_size_factor(vix)
        adjusted_margin = available_margin * size_factor

        # Get underlying (same as LEAPS)
        from src.strategy.cash_sweep import CASH_EQUIVALENT_SYMBOLS
        symbols = [s for s in market.prices.keys()
                   if s not in CASH_EQUIVALENT_SYMBOLS]
        if not symbols:
            return []
        underlying = symbols[0]

        # Select spread
        signal = self._build_spread_entry(
            underlying, market, data_provider,
            adjusted_margin, current_spreads, vix,
        )

        return [signal] if signal else []

    # -- Internal helpers --

    def _get_overlay_short_puts(self, portfolio: PortfolioState) -> list[PositionView]:
        """Find short put positions that belong to the overlay."""
        return [
            p for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.PUT and p.quantity < 0
        ]

    def _build_long_puts_index(
        self, portfolio: PortfolioState
    ) -> dict[tuple, PositionView]:
        """Index long puts by (underlying, expiry, strike) for pairing."""
        return {
            (p.instrument.underlying, p.instrument.expiry, p.instrument.strike): p
            for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.PUT and p.quantity > 0
        }

    def _find_long_leg_exit(
        self, short_pos: PositionView, portfolio: PortfolioState
    ) -> Optional[Signal]:
        """Find and create exit signal for the long leg matching a short put."""
        long_puts = self._build_long_puts_index(portfolio)
        for key, long_pos in long_puts.items():
            if (key[0] == short_pos.instrument.underlying and
                    key[1] == short_pos.instrument.expiry):
                return Signal(
                    type=SignalType.EXIT,
                    instrument=long_pos.instrument,
                    target_quantity=-long_pos.quantity,
                    reason="Close long leg (overlay exit)",
                    position_id=long_pos.position_id,
                    priority=9,
                    alert_type=AlertType.SPREAD_CLOSE,
                    metadata={"is_overlay": True},
                )
        return None

    def _check_vix_spike(self, vix: float, current_date: date) -> bool:
        """Check if VIX spiked > threshold from previous reading."""
        cfg = self._config
        if self._prev_vix <= 0 or vix <= 0:
            return False
        pct_change = (vix - self._prev_vix) / self._prev_vix
        if pct_change > cfg.vix_spike_pct:
            from datetime import timedelta
            self._cooldown_until = current_date + timedelta(days=cfg.vix_cooldown_days)
            return True
        return False

    def _vix_size_factor(self, vix: float) -> float:
        """Scale position size down based on VIX level."""
        cfg = self._config
        if vix >= cfg.vix_quarter_size:
            return 0.25
        if vix >= cfg.vix_half_size:
            return 0.50
        return 1.0

    def _calc_available_margin(self, portfolio: PortfolioState) -> float:
        """Calculate margin available for overlay spreads."""
        cfg = self._config
        nlv = portfolio.nlv
        cash = portfolio.cash
        cash_equiv = portfolio.cash_equivalent_value

        # Floor: keep min_cash_reserve_pct of NLV
        floor = nlv * cfg.min_cash_reserve_pct
        idle = cash + cash_equiv - floor
        if idle <= 0:
            return 0.0

        return idle * cfg.max_margin_pct

    def _build_spread_entry(
        self,
        underlying: str,
        market: MarketSnapshot,
        data_provider: Any,
        available_margin: float,
        current_spreads: int,
        vix: float,
    ) -> Optional[Signal]:
        """Build a bull put spread entry signal."""
        cfg = self._config
        spot = market.get_price_or_zero(underlying)
        if spot <= 0:
            return None

        # Get option chain
        chain = data_provider.get_option_chain(
            underlying,
            expiry_min_days=cfg.target_dte_min,
            expiry_max_days=cfg.target_dte_max,
        )
        if not chain or not chain.puts:
            self.log(f"chain:{underlying}", "fail", reason="no puts available")
            return None

        # Find target expiry
        target_expiry = None
        for exp in sorted(chain.expiry_dates):
            dte = (exp - market.date).days
            if cfg.target_dte_min <= dte <= cfg.target_dte_max:
                target_expiry = exp
                break
        if target_expiry is None:
            self.log(f"chain:{underlying}", "fail", reason="no expiry in DTE range")
            return None

        # Filter puts for this expiry
        expiry_puts = [
            p for p in chain.puts
            if p.contract.expiry_date == target_expiry
            and (p.mid_price or p.close or p.last_price or 0) > 0.05
        ]
        if not expiry_puts:
            return None

        # Select short put by delta
        short_put = self._select_by_delta(expiry_puts)
        if short_put is None:
            self.log(f"contract:{underlying}", "fail",
                     reason=f"no put with delta in [{cfg.min_delta}, {cfg.max_delta}]")
            return None

        short_strike = short_put.contract.strike_price
        short_price = short_put.mid_price or short_put.close or short_put.last_price
        if not short_price or short_price <= 0:
            return None

        if cfg.use_spread:
            return self._build_spread_signal(
                underlying, target_expiry, expiry_puts,
                short_put, short_strike, short_price,
                available_margin, current_spreads, vix,
            )
        else:
            return self._build_naked_put_signal(
                underlying, target_expiry,
                short_put, short_strike, short_price,
                available_margin, current_spreads, vix, spot,
            )

    def _build_spread_signal(
        self,
        underlying: str,
        target_expiry: date,
        expiry_puts: list,
        short_put: Any,
        short_strike: float,
        short_price: float,
        available_margin: float,
        current_spreads: int,
        vix: float,
    ) -> Optional[Signal]:
        """Build bull put spread signal with both legs."""
        cfg = self._config

        # Find long put
        long_target_strike = short_strike - cfg.spread_width
        if long_target_strike <= 0:
            return None

        long_put = self._find_closest_put(expiry_puts, long_target_strike)
        if long_put is None:
            return None

        long_strike = long_put.contract.strike_price
        long_price = long_put.mid_price or long_put.close or long_put.last_price
        if not long_price or long_price <= 0:
            return None

        if short_price <= long_price:
            return None  # No credit

        net_credit = short_price - long_price
        spread_width = short_strike - long_strike
        if spread_width <= 0:
            return None

        max_loss_per_spread = spread_width * 100 - net_credit * 100
        if max_loss_per_spread <= 0:
            return None

        # Size by available margin
        margin_per_spread = max_loss_per_spread  # Defined risk = max loss
        max_by_margin = math.floor(available_margin / margin_per_spread) if margin_per_spread > 0 else 0
        max_by_cap = cfg.max_spreads - current_spreads
        num_spreads = max(1, min(max_by_margin, max_by_cap))

        if num_spreads <= 0:
            return None

        # Build instruments
        short_instrument = Instrument(
            type=InstrumentType.OPTION,
            underlying=underlying,
            right=OptionRight.PUT,
            strike=short_strike,
            expiry=target_expiry,
        )
        long_instrument = Instrument(
            type=InstrumentType.OPTION,
            underlying=underlying,
            right=OptionRight.PUT,
            strike=long_strike,
            expiry=target_expiry,
        )

        combo = ComboInstrument(
            name=f"{underlying} Overlay BPS {short_strike:.0f}/{long_strike:.0f}",
            underlying=underlying,
            legs=[
                ComboLeg(instrument=short_instrument, ratio=-1),
                ComboLeg(instrument=long_instrument, ratio=+1),
            ],
        )

        short_greeks = {}
        if short_put.greeks:
            short_greeks = {
                "delta": short_put.greeks.delta,
                "gamma": short_put.greeks.gamma,
                "theta": short_put.greeks.theta,
                "vega": short_put.greeks.vega,
                "iv": short_put.iv or 0,
            }

        self.log(f"entry:{underlying}", "pass",
                 short_strike=short_strike, long_strike=long_strike,
                 net_credit=net_credit, num_spreads=num_spreads,
                 max_loss=max_loss_per_spread, vix=vix,
                 available_margin=available_margin)

        return Signal(
            type=SignalType.ENTRY,
            instrument=short_instrument,
            target_quantity=-num_spreads,
            reason=(
                f"Overlay BPS {short_strike:.0f}/{long_strike:.0f} "
                f"x{num_spreads} @ ${net_credit:.2f} credit"
            ),
            priority=-1,  # Lower than strategy entries
            quote_price=short_price,
            greeks=short_greeks if short_greeks else None,
            metadata={
                "combo": combo,
                "long_leg": long_instrument,
                "long_price": long_price,
                "net_credit": net_credit,
                "max_loss_per_spread": max_loss_per_spread,
                "is_overlay": True,
            },
        )

    def _build_naked_put_signal(
        self,
        underlying: str,
        target_expiry: date,
        short_put: Any,
        short_strike: float,
        short_price: float,
        available_margin: float,
        current_spreads: int,
        vix: float,
        spot: float,
    ) -> Optional[Signal]:
        """Build naked short put signal (higher margin, higher risk)."""
        cfg = self._config

        # Naked put margin ≈ max(20% × spot, 10% × strike) × 100
        margin_per_contract = max(0.20 * spot, 0.10 * short_strike) * 100
        if margin_per_contract <= 0:
            return None

        max_by_margin = math.floor(available_margin / margin_per_contract)
        max_by_cap = cfg.max_spreads - current_spreads
        num_contracts = max(1, min(max_by_margin, max_by_cap))

        if num_contracts <= 0:
            return None

        instrument = Instrument(
            type=InstrumentType.OPTION,
            underlying=underlying,
            right=OptionRight.PUT,
            strike=short_strike,
            expiry=target_expiry,
        )

        short_greeks = {}
        if short_put.greeks:
            short_greeks = {
                "delta": short_put.greeks.delta,
                "gamma": short_put.greeks.gamma,
                "theta": short_put.greeks.theta,
                "vega": short_put.greeks.vega,
                "iv": short_put.iv or 0,
            }

        self.log(f"entry:{underlying}", "pass",
                 strike=short_strike, qty=num_contracts,
                 price=short_price, vix=vix, mode="naked")

        return Signal(
            type=SignalType.ENTRY,
            instrument=instrument,
            target_quantity=-num_contracts,
            reason=(
                f"Overlay Naked Put {short_strike:.0f} "
                f"x{num_contracts} @ ${short_price:.2f}"
            ),
            priority=-1,
            quote_price=short_price,
            greeks=short_greeks if short_greeks else None,
            metadata={"is_overlay": True},
        )

    def _select_by_delta(self, puts: list) -> Optional[Any]:
        """Select put closest to target delta within [min, max] range."""
        cfg = self._config
        best = None
        best_diff = float("inf")
        for p in puts:
            delta = abs(p.greeks.delta) if p.greeks and p.greeks.delta else 0
            if delta < cfg.min_delta or delta > cfg.max_delta:
                continue
            diff = abs(delta - cfg.target_delta)
            if diff < best_diff:
                best_diff = diff
                best = p
        return best

    @staticmethod
    def _find_closest_put(puts: list, target_strike: float) -> Optional[Any]:
        """Find put option closest to target strike."""
        best = None
        best_diff = float("inf")
        for p in puts:
            diff = abs(p.contract.strike_price - target_strike)
            if diff < best_diff:
                best_diff = diff
                best = p
        return best

    def _make_exit_signal(
        self, pos: PositionView, reason: str, priority: int = 5,
    ) -> Signal:
        return Signal(
            type=SignalType.EXIT,
            instrument=pos.instrument,
            target_quantity=-pos.quantity,  # buy back
            reason=reason,
            position_id=pos.position_id,
            priority=priority,
            alert_type=AlertType.SPREAD_CLOSE,
            metadata={"is_overlay": True},
        )
