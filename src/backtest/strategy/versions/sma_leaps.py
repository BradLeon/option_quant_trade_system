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

    @property
    def requires_synthetic_data(self) -> bool:
        return True

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        self._last_nlv = portfolio.nlv
        self._pending_roll = False
        leaps = [p for p in portfolio.positions if p.is_option]
        self.log("day_start", "info",
                 nlv=portfolio.nlv, cash=portfolio.cash,
                 leaps_positions=len(leaps))

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        leaps = [p for p in portfolio.positions if p.is_option]
        if not leaps:
            self.log("exit_scan", "skip", reason="无LEAPS持仓")
            return []

        signals: list[Signal] = []

        # 1. SMA check
        result = self._sma.compute(market, data_provider)
        self._last_signal_detail = result

        sma_val = result.get("sma", 0)
        close = result.get("close", 0)

        if not result["invested"]:
            self.log("exit_scan:sma", "pass",
                     signal="bearish", close=close, sma=sma_val,
                     action=f"退出全部 {len(leaps)} 个LEAPS",
                     positions=[f"{p.instrument.symbol} qty={p.quantity} DTE={p.dte}" for p in leaps])
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

        self.log("exit_scan:sma", "skip",
                 signal="bullish", close=close, sma=sma_val,
                 reason="SMA看多，检查DTE roll")

        # 2. DTE roll check
        cfg = self._config
        for pos in leaps:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_roll = True
                self.log(f"exit_scan:roll", "pass",
                         symbol=pos.instrument.symbol,
                         dte=pos.dte, threshold=cfg.roll_dte_threshold)
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"LEAPS roll: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                    position_id=pos.position_id,
                    priority=5,
                    metadata={"alert_type": "roll_dte"},
                ))
            else:
                self.log(f"exit_scan:dte_check", "skip",
                         symbol=pos.instrument.symbol,
                         dte=pos.dte, threshold=cfg.roll_dte_threshold,
                         reason="DTE充足")

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
        entry_reason = ""
        if self._pending_roll:
            need_entry = True
            entry_reason = "pending_roll"
        elif not leaps:
            result = self._sma.compute(market, data_provider)
            if result["invested"] and self._is_decision_day(cfg.decision_frequency):
                need_entry = True
                entry_reason = f"无持仓+SMA看多+决策日 (freq={cfg.decision_frequency})"
            elif not result["invested"]:
                entry_reason = "SMA看空"
            else:
                entry_reason = f"非决策日 (day={self._trading_day_count} freq={cfg.decision_frequency})"
        else:
            entry_reason = f"已有LEAPS持仓 ({len(leaps)}个)"

        if not need_entry:
            self.log("entry_signal:check", "skip", reason=entry_reason)
            return []

        self.log("entry_signal:check", "info",
                 reason=entry_reason, nlv=self._last_nlv, cash=portfolio.cash,
                 target_leverage=cfg.target_leverage)

        # Find LEAPS opportunities
        symbols = list(market.prices.keys())
        signals: list[Signal] = []

        for symbol in symbols:
            spot = market.get_price_or_zero(symbol)
            if spot <= 0:
                self.log(f"entry_signal:{symbol}", "fail", reason=f"价格无效 spot={spot}")
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
                self.log(f"entry_signal:{symbol}", "fail",
                         reason="合约无效", delta=delta, mid=mid)
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
                self.log(f"entry_signal:{symbol}", "fail",
                         reason="sizing=0", budget=available, mid=mid, lot_size=lot_size)
                continue

            dte = (contract.expiry_date - market.date).days

            self.log(f"contract_select:{symbol}", "pass",
                     strike=contract.strike_price, dte=dte,
                     delta=delta, mid=mid, contracts=contracts,
                     leverage=cfg.target_leverage, budget=available)

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
            self.log(f"option_chain:{symbol}", "fail",
                     reason="无CALL合约",
                     dte_range=f"[{cfg.min_dte}-{cfg.max_dte}]")
            return None

        # Step 1: Pre-filter by DTE (cheap, no market data needed)
        total = len(chain.calls)
        prefiltered = []
        reject_dte = 0
        for call in chain.calls:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days
            if dte < cfg.min_dte or dte > cfg.max_dte:
                reject_dte += 1
                continue
            prefiltered.append(call)

        # Narrow by strike proximity (keep top 30 closest to target)
        prefiltered.sort(key=lambda c: abs(c.contract.strike_price - target_strike))
        shortlisted = prefiltered[:30]

        if not shortlisted:
            self.log(f"contract_select:{symbol}", "fail",
                     total=total, passed=0,
                     rejected_by={"dte": reject_dte},
                     filters=f"DTE=[{cfg.min_dte}-{cfg.max_dte}] target_K={target_strike:.0f} moneyness={cfg.target_moneyness}")
            return None

        # Step 2: Fetch actual market data for shortlisted contracts
        has_quotes_batch = hasattr(data_provider, 'get_option_quotes_batch')
        if has_quotes_batch:
            contracts_to_fetch = [c.contract for c in shortlisted]
            quotes = data_provider.get_option_quotes_batch(
                contracts_to_fetch, min_volume=0,
            )
            self.log(f"option_quotes:{symbol}", "info",
                     prefiltered=len(prefiltered), shortlisted=len(shortlisted),
                     quotes_returned=len(quotes))
        else:
            quotes = shortlisted

        # Step 3: Select best contract from quotes with prices
        best_score = -float("inf")
        best = None
        reject = {"no_price": 0, "no_delta": 0}

        for call in quotes:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days

            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if mid is None or mid <= 0:
                reject["no_price"] += 1
                continue

            delta = call.greeks.delta if call.greeks else None
            if delta is None or delta <= 0:
                reject["no_delta"] += 1
                continue

            dte_dev = abs(dte - cfg.target_dte) / cfg.target_dte if cfg.target_dte > 0 else 0
            strike_dev = abs(contract.strike_price - target_strike) / target_strike if target_strike > 0 else 0
            score = -_W_DTE * dte_dev - _W_STRIKE * strike_dev

            if score > best_score:
                best_score = score
                best = call

        if not best:
            self.log(f"contract_select:{symbol}", "fail",
                     total=total, passed=0,
                     rejected_by={"dte": reject_dte, **{k: v for k, v in reject.items() if v > 0}},
                     filters=f"DTE=[{cfg.min_dte}-{cfg.max_dte}] target_K={target_strike:.0f} moneyness={cfg.target_moneyness}")
        else:
            self.log(f"option_chain:{symbol}", "pass",
                     total=total,
                     rejected_by={"dte": reject_dte, **{k: v for k, v in reject.items() if v > 0}},
                     target_strike=target_strike)

        return best
