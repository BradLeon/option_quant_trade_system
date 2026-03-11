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
    decision_frequency: int = 5  # Check every N trading days

    # Spread construction
    short_put_delta: float = 0.30  # Target delta for short put (OTM)
    spread_width: float = 10.0  # Strike distance between legs ($)
    target_dte_min: int = 30  # Min days to expiration
    target_dte_max: int = 60  # Max days to expiration

    # Position sizing
    max_spreads: int = 5  # Max concurrent spread positions
    capital_per_spread_pct: float = 0.10  # % of NLV per spread

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

        for pos in portfolio.get_option_positions():
            # Only manage short put legs (the ones that generated the spread)
            if pos.instrument.right != OptionRight.PUT:
                continue
            if pos.quantity >= 0:
                continue  # Skip long legs

            # DTE exit
            if pos.dte is not None and pos.dte <= self._config.dte_exit:
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,  # buy back
                    reason=f"DTE exit: {pos.dte} days remaining",
                    position_id=pos.position_id,
                    priority=10,
                    metadata={"alert_type": "dte_warning"},
                ))
                continue

            # Profit target: if unrealized PnL > 50% of entry credit
            entry_credit = pos.entry_price * abs(pos.quantity) * pos.lot_size
            if entry_credit > 0:
                profit_pct = pos.unrealized_pnl / entry_credit
                if profit_pct >= self._config.profit_target_pct:
                    signals.append(Signal(
                        type=SignalType.EXIT,
                        instrument=pos.instrument,
                        target_quantity=-pos.quantity,
                        reason=f"Profit target: {profit_pct:.0%} of max",
                        position_id=pos.position_id,
                        priority=5,
                        metadata={"alert_type": "profit_target"},
                    ))

        return signals

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Open new spread when SMA is bullish and capacity available."""
        if not self._is_decision_day(self._config.decision_frequency):
            return []

        # Check SMA trend
        sma_result = self._sma.compute(market, data_provider)
        if not sma_result.get("invested", False):
            return []

        # Check position capacity (count short put legs)
        current_spreads = sum(
            1 for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.PUT and p.quantity < 0
        )
        if current_spreads >= self._config.max_spreads:
            return []

        # Find suitable put options for the spread
        underlying = list(market.prices.keys())[0] if market.prices else None
        if not underlying:
            return []

        underlying_price = market.get_price(underlying)

        # Target short put strike (approximately delta=0.30 → ~5% OTM for puts)
        short_strike = self._round_strike(underlying_price * 0.95)
        long_strike = short_strike - self._config.spread_width

        if long_strike <= 0:
            return []

        # Find option expiration in the target DTE range
        target_expiry = self._find_target_expiry(
            market.date, data_provider, underlying,
            self._config.target_dte_min, self._config.target_dte_max,
        )
        if target_expiry is None:
            return []

        # Get option prices from data provider
        short_price = self._get_option_price(
            data_provider, underlying, target_expiry, short_strike, "put"
        )
        long_price = self._get_option_price(
            data_provider, underlying, target_expiry, long_strike, "put"
        )

        if short_price is None or long_price is None:
            return []
        if short_price <= long_price:
            return []  # No credit — skip

        net_credit = short_price - long_price

        # Position sizing: how many spreads can we afford?
        max_loss_per_spread = (short_strike - long_strike) * 100 - net_credit * 100
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
            name=f"{underlying} Bull Put {short_strike:.0f}/{long_strike:.0f}",
            underlying=underlying,
            legs=[
                ComboLeg(instrument=short_instrument, ratio=-1),
                ComboLeg(instrument=long_instrument, ratio=+1),
            ],
        )

        # Generate entry signal for the short leg (primary signal)
        # The combo metadata enables the executor to handle both legs together
        signals = [
            Signal(
                type=SignalType.ENTRY,
                instrument=short_instrument,
                target_quantity=-num_spreads,
                reason=(
                    f"Bull Put Spread {short_strike:.0f}/{long_strike:.0f} "
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
            "short_strike": short_strike,
            "long_strike": long_strike,
            "net_credit": net_credit,
            "num_spreads": num_spreads,
        }

        return signals

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _round_strike(price: float, step: float = 5.0) -> float:
        """Round down to nearest strike step."""
        return math.floor(price / step) * step

    @staticmethod
    def _find_target_expiry(
        current_date: date,
        data_provider: Any,
        underlying: str,
        min_dte: int,
        max_dte: int,
    ) -> Optional[date]:
        """Find an option expiration within the target DTE range."""
        try:
            expirations = data_provider.get_option_expirations(underlying)
            if not expirations:
                return None
            for exp in sorted(expirations):
                if isinstance(exp, str):
                    exp = date.fromisoformat(exp)
                dte = (exp - current_date).days
                if min_dte <= dte <= max_dte:
                    return exp
        except Exception:
            pass

        # Fallback: synthetic expiry at target_dte_min + 15 days (third Friday heuristic)
        target = current_date + timedelta(days=(min_dte + max_dte) // 2)
        # Snap to Friday
        days_to_friday = (4 - target.weekday()) % 7
        return target + timedelta(days=days_to_friday)

    @staticmethod
    def _get_option_price(
        data_provider: Any,
        underlying: str,
        expiry: date,
        strike: float,
        right: str,
    ) -> Optional[float]:
        """Get option mid price from data provider."""
        try:
            quote = data_provider.get_option_quote(
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                option_type=right,
            )
            if quote and hasattr(quote, "mid_price"):
                return quote.mid_price
            if quote and hasattr(quote, "last_price"):
                return quote.last_price
        except Exception:
            pass
        return None
