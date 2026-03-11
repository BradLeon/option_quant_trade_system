"""SMA LEAPS Timing Strategy — replaces LongLeapsCallSmaTiming.

Old strategy (~600 lines) → new implementation (~130 lines).

Uses SmaComputer for timing signal + LEAPS Call for leveraged exposure.
Roll is triggered when DTE drops below threshold.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
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
from src.backtest.strategy.signals.sma import SmaComparison, SmaComputer

logger = logging.getLogger(__name__)

# Contract selection weights
_W_DTE = 1.0
_W_STRIKE = 2.0


@dataclass
class SmaLeapsConfig:
    """Configuration for SMA LEAPS Timing strategy."""

    name: str = "sma_leaps"
    sma_period: int = 200
    comparison: SmaComparison = SmaComparison.PRICE_VS_SMA
    decision_frequency: int = 5

    # LEAPS contract parameters
    target_moneyness: float = 0.85  # Strike = Spot * 0.85 (15% ITM)
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    roll_dte_threshold: int = 60

    # Leverage
    target_leverage: float = 3.0
    max_capital_pct: float = 0.95


class SmaLeapsStrategy(BacktestStrategy):
    """SMA-timed LEAPS Call strategy.

    Replaces LongLeapsCallSmaTiming with cleaner code:
    - SMA bullish: hold deep ITM LEAPS Calls at target leverage
    - SMA bearish: exit all, hold cash
    - Auto roll: close when DTE <= threshold, reopen new contract

    Replaces LongLeapsCallSmaTiming (598 lines) → ~130 lines.
    """

    def __init__(self, config: SmaLeapsConfig | None = None) -> None:
        super().__init__()
        self._config = config or SmaLeapsConfig()
        self._sma = SmaComputer(period=self._config.sma_period, comparison=self._config.comparison)
        self._last_nlv: float = 0.0
        self._pending_roll: bool = False

    @property
    def name(self) -> str:
        return self._config.name

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        self._last_nlv = portfolio.nlv
        self._pending_roll = False

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        leaps = [p for p in portfolio.positions if p.is_option]
        if not leaps:
            return []

        signals: list[Signal] = []

        # 1. SMA check
        result = self._sma.compute(market, data_provider)
        self._last_signal_detail = result

        if not result["invested"]:
            # SMA bearish → exit all
            for pos in leaps:
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason="SMA exit: below SMA, moving to cash",
                    position_id=pos.position_id,
                    priority=10,
                    metadata={"alert_type": "sma_exit"},
                ))
            return signals

        # 2. DTE roll check
        cfg = self._config
        for pos in leaps:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_roll = True
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"LEAPS roll: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                    position_id=pos.position_id,
                    priority=5,
                    metadata={"alert_type": "roll_dte"},
                ))

        # 3. DTE <= 5 safety net
        for pos in leaps:
            if pos.dte is not None and pos.dte <= 5:
                already = any(s.position_id == pos.position_id for s in signals)
                if not already:
                    self._pending_roll = True
                    signals.append(Signal(
                        type=SignalType.EXIT,
                        instrument=pos.instrument,
                        target_quantity=-pos.quantity,
                        reason=f"Safety net: DTE={pos.dte} <= 5",
                        position_id=pos.position_id,
                        priority=10,
                        metadata={"alert_type": "roll_dte"},
                    ))

        return signals

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        cfg = self._config

        # Need entry if: pending roll, or no positions + SMA bullish + decision day
        leaps = [p for p in portfolio.positions if p.is_option]
        need_entry = False
        if self._pending_roll:
            need_entry = True
        elif not leaps:
            result = self._sma.compute(market, data_provider)
            if result["invested"] and self._is_decision_day(cfg.decision_frequency):
                need_entry = True

        if not need_entry:
            return []

        # Find LEAPS opportunities
        symbols = list(market.prices.keys())
        signals: list[Signal] = []

        for symbol in symbols:
            spot = market.get_price_or_zero(symbol)
            if spot <= 0:
                continue

            best = self._find_best_leaps(symbol, spot, market.date, data_provider)
            if not best:
                continue

            contract = best.contract
            greeks = best.greeks
            delta = greeks.delta if greeks else 0.0
            mid = best.last_price
            if best.bid is not None and best.ask is not None and best.ask > 0:
                mid = (best.bid + best.ask) / 2
            if not delta or delta <= 0 or not mid or mid <= 0:
                continue

            lot_size = contract.lot_size or 100
            nlv = self._last_nlv
            if nlv <= 0:
                continue

            # contracts = target_leverage * NLV / (delta * lot_size * spot)
            contracts = math.floor(cfg.target_leverage * nlv / (delta * lot_size * spot))

            # Cash constraint
            available = cfg.max_capital_pct * (nlv if self._pending_roll else portfolio.cash)
            if mid * lot_size > 0:
                max_contracts = math.floor(available / (mid * lot_size))
                contracts = min(contracts, max_contracts)

            if contracts <= 0:
                continue

            dte = (contract.expiry_date - market.date).days
            instrument = Instrument(
                type=InstrumentType.OPTION,
                underlying=symbol,
                right=OptionRight.CALL,
                strike=contract.strike_price,
                expiry=contract.expiry_date,
                lot_size=lot_size,
            )

            signals.append(Signal(
                type=SignalType.ENTRY,
                instrument=instrument,
                target_quantity=contracts,
                reason=(
                    f"LEAPS entry: {contracts}x K={contract.strike_price:.0f} "
                    f"DTE={dte} delta={delta:.2f}"
                ),
                quote_price=mid,
                greeks={"delta": delta, "gamma": greeks.gamma if greeks else 0,
                        "theta": greeks.theta if greeks else 0, "vega": greeks.vega if greeks else 0,
                        "iv": best.iv or 0},
            ))

        return signals

    def _find_best_leaps(
        self, symbol: str, spot: float, current_date: date, data_provider: Any
    ) -> Optional[Any]:
        """Select best-matching LEAPS Call from option chain."""
        cfg = self._config
        target_strike = spot * cfg.target_moneyness

        chain = data_provider.get_option_chain(
            underlying=symbol,
            expiry_min_days=cfg.min_dte,
            expiry_max_days=cfg.max_dte,
        )
        if not chain or not chain.calls:
            return None

        best_score = -float("inf")
        best = None

        for call in chain.calls:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days
            if dte < cfg.min_dte or dte > cfg.max_dte:
                continue

            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if mid is None or mid <= 0:
                continue

            delta = call.greeks.delta if call.greeks else None
            if delta is None or delta <= 0:
                continue

            dte_dev = abs(dte - cfg.target_dte) / cfg.target_dte if cfg.target_dte > 0 else 0
            strike_dev = abs(contract.strike_price - target_strike) / target_strike if target_strike > 0 else 0
            score = -_W_DTE * dte_dev - _W_STRIKE * strike_dev

            if score > best_score:
                best_score = score
                best = call

        return best
