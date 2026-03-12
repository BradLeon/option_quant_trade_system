"""Bull Put Spread Strategy — defined-risk credit spread using V2 framework.

Demonstrates multi-leg combo support:
- Sells OTM put spread when SMA trend is bullish
- Defined risk: max_loss = |strike_diff| × lot_size × quantity
- Reduced margin vs naked short put
- Auto-exits at DTE threshold or profit target

This strategy issues ENTRY signals with ComboInstrument metadata,
which the executor can route through TradeSimulator.execute_combo()
and AccountSimulator.add_combo_position().
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.backtest.strategy.models import (
    ComboInstrument,
    ComboLeg,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    Signal,
    SignalType,
)
from src.backtest.strategy.protocol import BacktestStrategy
from src.backtest.strategy.signals.sma import SmaComparison, SmaComputer

logger = logging.getLogger(__name__)


@dataclass
class BullPutSpreadConfig:
    """Configuration for Bull Put Spread strategy."""

    name: str = "bull_put_spread"

    # SMA trend filter
    sma_period: int = 200
    decision_frequency: int = 3  # Check every N trading days

    # Spread construction
    short_put_delta: float = 0.30  # Target delta for short put (OTM)
    spread_width: float = 5.0  # Strike distance between legs ($)
    target_dte_min: int = 30  # Min days to expiration
    target_dte_max: int = 60  # Max days to expiration

    # Position sizing
    max_spreads: int = 10  # Max concurrent spread positions
    capital_per_spread_pct: float = 0.05  # % of NLV per spread

    # Exit rules
    profit_target_pct: float = 0.50  # Close at 50% of max profit
    dte_exit: int = 10  # Close when DTE drops below this


class BullPutSpreadStrategy(BacktestStrategy):
    """Bull put credit spread with SMA trend filter.

    Entry: When SMA is bullish and position count below max_spreads,
           sell a put spread (short higher put + long lower put).
    Exit:  When profit target reached (50% of credit) or DTE < threshold.
    """

    def __init__(self, config: BullPutSpreadConfig | None = None) -> None:
        super().__init__()
        self._config = config or BullPutSpreadConfig()
        self._sma = SmaComputer(
            period=self._config.sma_period,
            comparison=SmaComparison.PRICE_VS_SMA,
        )

    @property
    def name(self) -> str:
        return self._config.name

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Close spreads at profit target or DTE exit."""
        signals: list[Signal] = []

        short_puts = [p for p in portfolio.get_option_positions()
                      if p.instrument.right == OptionRight.PUT and p.quantity < 0]
        if not short_puts:
            self.log("exit_scan", "skip", reason="无Spread持仓")
            return signals

        # Build index of long legs for pairing
        long_puts = {
            (pos.instrument.underlying, pos.instrument.expiry, pos.instrument.strike): pos
            for pos in portfolio.get_option_positions()
            if pos.instrument.right == OptionRight.PUT and pos.quantity > 0
        }

        for pos in portfolio.get_option_positions():
            # Only manage short put legs (the ones that generated the spread)
            if pos.instrument.right != OptionRight.PUT:
                continue
            if pos.quantity >= 0:
                continue  # Skip long legs

            should_close = False
            reason = ""

            # DTE exit
            if pos.dte is not None and pos.dte <= self._config.dte_exit:
                should_close = True
                reason = f"DTE exit: {pos.dte} days remaining"

            # Profit target: if unrealized PnL > 50% of entry credit
            if not should_close:
                entry_credit = pos.entry_price * abs(pos.quantity) * pos.lot_size
                if entry_credit > 0:
                    profit_pct = pos.unrealized_pnl / entry_credit
                    if profit_pct >= self._config.profit_target_pct:
                        should_close = True
                        reason = f"Profit target: {profit_pct:.0%} of max"

            if not should_close:
                self.log(f"exit_scan:{pos.instrument.symbol}", "skip",
                         dte=pos.dte, dte_exit=self._config.dte_exit,
                         pnl=pos.unrealized_pnl,
                         profit_target=self._config.profit_target_pct,
                         reason="未触发退出条件")

            if should_close:
                self.log(f"exit_scan:{pos.instrument.symbol}", "pass",
                         reason=reason, dte=pos.dte)
                # Close short leg
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,  # buy back
                    reason=reason,
                    position_id=pos.position_id,
                    priority=10,
                    metadata={"alert_type": "spread_close"},
                ))

                # Also close the matching long leg
                for key, long_pos in long_puts.items():
                    if (key[0] == pos.instrument.underlying and
                            key[1] == pos.instrument.expiry):
                        signals.append(Signal(
                            type=SignalType.EXIT,
                            instrument=long_pos.instrument,
                            target_quantity=-long_pos.quantity,  # sell
                            reason=f"Close long leg: {reason}",
                            position_id=long_pos.position_id,
                            priority=10,
                            metadata={"alert_type": "spread_close"},
                        ))
                        break

        return signals

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Open new spread when SMA is bullish and capacity available."""
        if not self._is_decision_day(self._config.decision_frequency):
            self.log("entry_signal", "skip",
                     reason=f"非决策日 (day={self._trading_day_count} freq={self._config.decision_frequency})")
            return []

        # Check SMA trend
        sma_result = self._sma.compute(market, data_provider)
        if not sma_result.get("invested", False):
            self.log("entry_signal:sma", "fail",
                     close=sma_result.get("close", 0), sma=sma_result.get("sma", 0),
                     reason="SMA看空，不开仓")
            return []

        # Check position capacity (count short put legs)
        current_spreads = sum(
            1 for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.PUT and p.quantity < 0
        )
        if current_spreads >= self._config.max_spreads:
            self.log("entry_signal", "skip",
                     current=current_spreads, max=self._config.max_spreads,
                     reason="已达最大Spread数量")
            return []

        self.log("entry_signal:sma", "pass",
                 close=sma_result.get("close", 0), sma=sma_result.get("sma", 0),
                 current_spreads=current_spreads, max_spreads=self._config.max_spreads)

        # Find suitable put options for the spread
        underlying = list(market.prices.keys())[0] if market.prices else None
        if not underlying:
            return []

        underlying_price = market.get_price(underlying)

        # Get option chain from data provider
        chain = data_provider.get_option_chain(
            underlying,
            expiry_min_days=self._config.target_dte_min,
            expiry_max_days=self._config.target_dte_max,
        )
        if not chain or not chain.puts:
            self.log(f"option_chain:{underlying}", "fail",
                     reason="无PUT合约",
                     dte_range=f"[{self._config.target_dte_min}-{self._config.target_dte_max}]")
            return []

        # Find target expiry from available expirations
        target_expiry = None
        for exp in sorted(chain.expiry_dates):
            dte = (exp - market.date).days
            if self._config.target_dte_min <= dte <= self._config.target_dte_max:
                target_expiry = exp
                break
        if target_expiry is None:
            return []

        # Filter puts for this expiry (only those with valid prices)
        expiry_puts = [
            p for p in chain.puts
            if p.contract.expiry_date == target_expiry
            and (p.mid_price or p.close or p.last_price) is not None
            and (p.mid_price or p.close or p.last_price or 0) > 0.05
        ]
        if not expiry_puts:
            return []

        # Target short put strike (~3-5% OTM based on delta target)
        target_short_strike = underlying_price * 0.95
        target_long_strike = target_short_strike - self._config.spread_width

        if target_long_strike <= 0:
            return []

        # Find closest matching puts by strike from available data
        short_put = self._find_closest_put(expiry_puts, target_short_strike)
        long_put = self._find_closest_put(expiry_puts, target_long_strike)

        if short_put is None or long_put is None:
            return []

        short_price = short_put.mid_price or short_put.close or short_put.last_price
        long_price = long_put.mid_price or long_put.close or long_put.last_price

        if short_price is None or long_price is None:
            return []
        if short_price <= long_price:
            return []  # No credit — skip

        # Use actual strikes from matched contracts
        actual_short_strike = short_put.contract.strike_price
        actual_long_strike = long_put.contract.strike_price
        net_credit = short_price - long_price

        # Position sizing: how many spreads can we afford?
        spread_width = actual_short_strike - actual_long_strike
        if spread_width <= 0:
            return []
        max_loss_per_spread = spread_width * 100 - net_credit * 100
        if max_loss_per_spread <= 0:
            return []

        budget = portfolio.nlv * self._config.capital_per_spread_pct
        num_spreads = min(
            max(1, math.floor(budget / max_loss_per_spread)),
            self._config.max_spreads - current_spreads,
        )

        # Build combo instrument
        short_instrument = Instrument(
            type=InstrumentType.OPTION,
            underlying=underlying,
            right=OptionRight.PUT,
            strike=actual_short_strike,
            expiry=target_expiry,
        )
        long_instrument = Instrument(
            type=InstrumentType.OPTION,
            underlying=underlying,
            right=OptionRight.PUT,
            strike=actual_long_strike,
            expiry=target_expiry,
        )

        combo = ComboInstrument(
            name=f"{underlying} Bull Put {actual_short_strike:.0f}/{actual_long_strike:.0f}",
            underlying=underlying,
            legs=[
                ComboLeg(instrument=short_instrument, ratio=-1),
                ComboLeg(instrument=long_instrument, ratio=+1),
            ],
        )

        # Generate entry signal for the short leg (primary signal)
        signals = [
            Signal(
                type=SignalType.ENTRY,
                instrument=short_instrument,
                target_quantity=-num_spreads,
                reason=(
                    f"Bull Put Spread {actual_short_strike:.0f}/{actual_long_strike:.0f} "
                    f"x{num_spreads} @ ${net_credit:.2f} credit"
                ),
                priority=0,
                quote_price=short_price,
                metadata={
                    "combo": combo,
                    "long_leg": long_instrument,
                    "long_price": long_price,
                    "net_credit": net_credit,
                    "max_loss_per_spread": max_loss_per_spread,
                },
            ),
        ]

        self._last_signal_detail = {
            "combo_name": combo.name,
            "short_strike": actual_short_strike,
            "long_strike": actual_long_strike,
            "net_credit": net_credit,
            "num_spreads": num_spreads,
        }

        self.log(f"contract_select:{underlying}", "pass",
                 short_strike=actual_short_strike, long_strike=actual_long_strike,
                 net_credit=net_credit, num_spreads=num_spreads,
                 max_loss=max_loss_per_spread, spread_width=spread_width)

        return signals

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _round_strike(price: float, step: float = 5.0) -> float:
        """Round down to nearest strike step."""
        return math.floor(price / step) * step

    @staticmethod
    def _find_closest_put(puts: list, target_strike: float):
        """Find the put option closest to the target strike."""
        best = None
        best_diff = float("inf")
        for p in puts:
            diff = abs(p.contract.strike_price - target_strike)
            if diff < best_diff:
                best_diff = diff
                best = p
        return best
