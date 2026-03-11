"""Momentum + Vol Target Mixed Strategy — replaces SpyMomentumLev + SpyLeapsOnly.

Two old strategies (~1600 lines combined including mixin) → one parameterized (~200 lines).

Config:
- SpyMomentumLevVolTarget → MomentumMixedConfig(use_stock_component=True)
- SpyLeapsOnlyVolTarget   → MomentumMixedConfig(use_stock_component=False, cash_interest_enabled=True)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.backtest.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)
from src.backtest.strategy.protocol import BacktestStrategy
from src.backtest.strategy.signals.momentum import (
    MomentumConfig,
    MomentumVolTargetComputer,
)

logger = logging.getLogger(__name__)

# Contract selection weights
_W_DTE = 1.0
_W_STRIKE = 2.0


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

    # LEAPS contract parameters
    target_moneyness: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    roll_dte_threshold: int = 60
    max_capital_pct: float = 0.95

    # Cash interest (LeapsOnly feature)
    cash_interest_enabled: bool = False
    default_risk_free_rate: float = 0.04


class MomentumMixedStrategy(BacktestStrategy):
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
        self._last_rebalance_day: int = -9999

        # Cross-method coordination
        self._pending_rebalance: bool = False
        self._pending_leaps_topup: int = 0
        self._pending_stock_topup_pct: float = 0.0

        # Cash interest tracking (for LeapsOnly mode)
        self._cumulative_interest: float = 0.0
        self._tnx_cache: dict[date, float] = {}

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def requires_synthetic_data(self) -> bool:
        return True

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        self._last_nlv = portfolio.nlv
        self._pending_rebalance = False
        self._pending_leaps_topup = 0
        self._pending_stock_topup_pct = 0.0

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        cfg = self._config
        stock_pos = portfolio.get_stock_positions()
        leaps_pos = [p for p in portfolio.get_option_positions()
                     if p.instrument.right == OptionRight.CALL and p.quantity > 0]

        if not stock_pos and not leaps_pos:
            return []

        result = self._momentum.compute(market, data_provider)
        self._last_signal_detail = result
        target_pct = result["target_pct"]

        current_pct = self._compute_current_exposure(stock_pos, leaps_pos, market)
        self._last_signal_detail["current_pct"] = current_pct

        signals: list[Signal] = []

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
                    metadata={"alert_type": "voltgt_exit"},
                ))
            for pos in stock_pos:
                signals.append(Signal(
                    type=SignalType.EXIT, instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"Exit: target=0 (score={score}) vix={vix:.1f}",
                    position_id=pos.position_id, priority=10,
                    metadata={"alert_type": "voltgt_exit"},
                ))
            return signals

        # b) LEAPS DTE roll
        for pos in leaps_pos:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_rebalance = True
                signals.append(Signal(
                    type=SignalType.EXIT, instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"LEAPS roll: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                    position_id=pos.position_id, priority=5,
                    metadata={"alert_type": "roll_dte"},
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
                        metadata={"alert_type": "roll_dte"},
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
            return signals

        # c) Rebalance check
        delta_pct = target_pct - current_pct
        if abs(delta_pct) <= cfg.rebalance_threshold:
            return []
        if not self._rebalance_cooldown_ok(self._last_rebalance_day, cfg.min_rebalance_interval):
            return []

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

        # Determine if entry needed
        stock_pos = portfolio.get_stock_positions()
        leaps_pos = [p for p in portfolio.get_option_positions()
                     if p.instrument.right == OptionRight.CALL and p.quantity > 0]

        need_entry = False
        if self._pending_rebalance or self._pending_stock_topup_pct > 0:
            need_entry = True
        elif target_pct > 0 and not stock_pos and not leaps_pos:
            if self._is_decision_day(cfg.decision_frequency):
                need_entry = True

        if not need_entry or target_pct <= 0:
            return []

        signals: list[Signal] = []
        symbols = list(market.prices.keys())

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
                        metadata={"alert_type": "rebalance"},
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
                                metadata={"alert_type": "rebalance"},
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
        """Find and size a LEAPS Call entry."""
        cfg = self._config
        target_strike = spot * cfg.target_moneyness

        chain = data_provider.get_option_chain(
            underlying=symbol,
            expiry_min_days=cfg.min_dte,
            expiry_max_days=cfg.max_dte,
        )
        if not chain or not chain.calls:
            return None

        # Select best contract
        best = None
        best_score = -float("inf")
        for call in chain.calls:
            contract = call.contract
            dte = (contract.expiry_date - market.date).days
            if dte < cfg.min_dte or dte > cfg.max_dte:
                continue
            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if not mid or mid <= 0:
                continue
            delta = call.greeks.delta if call.greeks else None
            if not delta or delta <= 0:
                continue
            dte_dev = abs(dte - cfg.target_dte) / cfg.target_dte if cfg.target_dte > 0 else 0
            strike_dev = abs(contract.strike_price - target_strike) / target_strike if target_strike > 0 else 0
            score = -_W_DTE * dte_dev - _W_STRIKE * strike_dev
            if score > best_score:
                best_score = score
                best = call

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

        # Size: use pending topup or compute from pct
        if self._pending_leaps_topup > 0:
            contracts = self._pending_leaps_topup
            self._pending_leaps_topup = 0
        else:
            contracts = math.floor(leaps_pct * self._last_nlv / (delta * lot_size * spot))

        # Cash constraint
        if cfg.use_stock_component:
            budget = cfg.max_capital_pct * self._last_nlv
        else:
            # LeapsOnly mode: constrain by actual cash
            budget = cfg.max_capital_pct * self._last_nlv  # simplified; real cash tracked by executor
        if mid * lot_size > 0:
            max_contracts = math.floor(budget / (mid * lot_size))
            contracts = min(contracts, max_contracts)

        if contracts <= 0:
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
