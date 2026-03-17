"""LEAPS strategy variants for risk improvement A/B testing.

Five variants of spy_leaps_only_vol_target, each addressing a specific risk:
- V1 (Theta): Earlier roll at DTE=90 instead of 60
- V2 (Vega): Reduce position when VIX spikes > 30% above 20-day average
- V3a (Delta): Rebalance down only — never add on dips
- V3b (Delta): Stop loss at -30% per position
- V3c (Delta): Deleverage when portfolio drawdown > 10%

     ┌─────────────────┬───────────────────────────┬──────────────────────────────────────────────────────────┐
     │      变体       │          策略名           │                          改动点                          │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ 基准            │ leaps_baseline            │ 原始策略，无改动                                         │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V1: Theta 监控  │ leaps_theta_guard         │ DTE < roll_dte + 30 时提前 roll（roll_dte=90 而非 60）   │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V2: Vega 保护   │ leaps_vega_guard          │ 当 VIX 上升超 30%（vs 20日均值）时减仓 50%               │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V3a: 单向再平衡 │ leaps_rebal_down_only     │ 再平衡仅减仓，不加仓（下跌不补仓）                       │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V3b: 持仓止损   │ leaps_stop_loss           │ 单持仓浮亏 > 30% 触发 EXIT                               │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V3c: 回撤降杠杆 │ leaps_drawdown_deleverage │ Portfolio drawdown > 10% 时 max_exposure 从 3.0 降到 1.5 │
     └─────────────────┴───────────────────────────┴──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import math
from typing import Any

from src.strategy.models import (
    AlertType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)
from src.strategy.versions.momentum_mixed import (
    MomentumMixedConfig,
    MomentumMixedStrategy,
)


# ── V1: Theta Guard — roll earlier at DTE=90 ──


class LeapsThetaGuardStrategy(MomentumMixedStrategy):
    """Earlier LEAPS roll to reduce theta decay exposure.

    Changes roll_dte_threshold from 60 → 90, giving 30 extra days
    before theta acceleration kicks in.
    """

    def __init__(self, config: MomentumMixedConfig | None = None) -> None:
        cfg = config or MomentumMixedConfig()
        cfg.roll_dte_threshold = 90
        super().__init__(cfg)


# ── V2: Vega Guard — reduce on VIX spike ──


class LeapsVegaGuardStrategy(MomentumMixedStrategy):
    """Reduce LEAPS exposure when VIX spikes above 20-day average.

    When current VIX > 1.3 × VIX_SMA20, sell 50% of LEAPS positions.
    This protects against vol crush after a spike (long vega loses on IV drop).
    """

    VIX_SPIKE_THRESHOLD = 1.30  # 30% above SMA20
    REDUCE_FRACTION = 0.50  # sell half

    def __init__(self, config: MomentumMixedConfig | None = None) -> None:
        super().__init__(config)
        self._vix_history: list[float] = []

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        super().on_day_start(market, portfolio)
        if market.vix and market.vix > 0:
            self._vix_history.append(market.vix)

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        signals = super().compute_exit_signals(market, portfolio, data_provider)

        # Check VIX spike condition
        if len(self._vix_history) < 20 or not market.vix:
            return signals

        vix_sma20 = sum(self._vix_history[-20:]) / 20.0
        if market.vix <= self.VIX_SPIKE_THRESHOLD * vix_sma20:
            return signals

        # VIX spike detected — reduce LEAPS by 50%
        leaps_pos = [
            p for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.CALL and p.quantity > 0
        ]
        existing_exit_ids = {s.position_id for s in signals}

        for pos in leaps_pos:
            if pos.position_id in existing_exit_ids:
                continue
            sell_qty = max(1, math.floor(pos.quantity * self.REDUCE_FRACTION))
            sell_qty = min(sell_qty, pos.quantity)
            signals.append(Signal(
                type=SignalType.EXIT,
                instrument=pos.instrument,
                target_quantity=-sell_qty,
                reason=f"Vega guard: VIX={market.vix:.1f} > {self.VIX_SPIKE_THRESHOLD}×SMA20={vix_sma20:.1f}",
                position_id=pos.position_id,
                priority=8,
                alert_type=AlertType.VEGA_GUARD,
            ))

        if len(signals) > len(existing_exit_ids):
            self.log("exit_scan:vega_guard", "pass",
                     vix=market.vix, vix_sma20=vix_sma20,
                     threshold=self.VIX_SPIKE_THRESHOLD,
                     reduces=len(signals) - len(existing_exit_ids))

        return signals


# ── V3a: Rebalance Down Only — never topup on dips ──


class LeapsRebalDownOnlyStrategy(MomentumMixedStrategy):
    """Rebalance only reduces positions, never adds on declines.

    When current_pct < target_pct (underexposed), do nothing instead of
    buying more contracts. This prevents pro-cyclical behavior where
    declining positions trigger additional buys that amplify losses.
    """

    def _rebalance_signals(
        self,
        stock_pos: list[PositionView],
        leaps_pos: list[PositionView],
        target_pct: float,
        current_pct: float,
        market: MarketSnapshot,
    ) -> list[Signal]:
        # Only rebalance when overexposed (current > target)
        if current_pct < target_pct:
            self.log("rebalance:down_only", "skip",
                     current_pct=current_pct, target_pct=target_pct,
                     reason="下跌不补仓")
            return []
        # Overexposed — allow normal reduce logic
        return super()._rebalance_signals(
            stock_pos, leaps_pos, target_pct, current_pct, market
        )


# ── V3b: Stop Loss — exit on -30% per-position loss ──


class LeapsStopLossStrategy(MomentumMixedStrategy):
    """Exit LEAPS positions that have lost more than 30% of cost basis.

    Prevents holding deeply underwater positions waiting for SMA exit.
    """

    STOP_LOSS_PCT = -0.30

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        signals = super().compute_exit_signals(market, portfolio, data_provider)

        leaps_pos = [
            p for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.CALL and p.quantity > 0
        ]
        existing_exit_ids = {s.position_id for s in signals}

        for pos in leaps_pos:
            if pos.position_id in existing_exit_ids:
                continue
            cost_basis = pos.entry_price * pos.quantity * pos.lot_size
            if cost_basis <= 0:
                continue
            pnl_pct = pos.unrealized_pnl / cost_basis
            if pnl_pct < self.STOP_LOSS_PCT:
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"Stop loss: PnL={pnl_pct:.1%} < {self.STOP_LOSS_PCT:.0%}",
                    position_id=pos.position_id,
                    priority=9,
                    alert_type=AlertType.STOP_LOSS,
                ))
                self.log("exit_scan:stop_loss", "pass",
                         position_id=pos.position_id,
                         pnl_pct=pnl_pct,
                         cost_basis=cost_basis)

        return signals


# ── V3c: Drawdown Deleverage — reduce max_exposure on portfolio drawdown ──


class LeapsDrawdownDeleverageStrategy(MomentumMixedStrategy):
    """Reduce max leverage when portfolio drawdown exceeds threshold.

    When drawdown > 10%: cap effective max_exposure at 1.5 (half of normal 3.0).
    Recovery: when drawdown < 5%, restore normal max_exposure.
    This prevents compounding losses during sustained declines.
    """

    DD_TRIGGER = 0.10  # 10% drawdown triggers deleverage
    DD_RECOVER = 0.05  # 5% drawdown restores normal
    DELEVERAGED_MAX = 1.5  # half of normal 3.0

    def __init__(self, config: MomentumMixedConfig | None = None) -> None:
        super().__init__(config)
        self._peak_nlv: float = 0.0
        self._deleveraged: bool = False
        self._normal_max_exposure: float = self._config.momentum.max_exposure

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        super().on_day_start(market, portfolio)

        # Track drawdown
        if portfolio.nlv > self._peak_nlv:
            self._peak_nlv = portfolio.nlv
        if self._peak_nlv <= 0:
            return

        dd = (self._peak_nlv - portfolio.nlv) / self._peak_nlv

        if not self._deleveraged and dd >= self.DD_TRIGGER:
            self._deleveraged = True
            self._config.momentum.max_exposure = self.DELEVERAGED_MAX
            self.log("drawdown:deleverage", "pass",
                     drawdown=dd, new_max=self.DELEVERAGED_MAX)
        elif self._deleveraged and dd <= self.DD_RECOVER:
            self._deleveraged = False
            self._config.momentum.max_exposure = self._normal_max_exposure
            self.log("drawdown:restore", "pass",
                     drawdown=dd, restored_max=self._normal_max_exposure)
