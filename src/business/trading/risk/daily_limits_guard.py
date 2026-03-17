"""DailyLimitsGuard — signal-level daily limits enforcement.

Wraps DailyTradeTracker as a RiskGuard, moving daily limits from
order-level (inside TradingPipeline) to signal-level (RiskGuard chain).

Implements truncation: if a signal exceeds daily limits, its quantity
is reduced rather than the entire signal being rejected.
"""

from __future__ import annotations

import logging
from src.business.trading.daily_limits import DailyLimitsConfig, DailyTradeTracker
from src.business.trading.order.store import OrderStore
from src.strategy.models import (
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)

logger = logging.getLogger(__name__)

_SIGNAL_TYPE_TO_DECISION_TYPE: dict[SignalType, str] = {
    SignalType.ENTRY: "open",
    SignalType.EXIT: "close",
    SignalType.ROLL: "roll",
    SignalType.REBALANCE: "adjust",
}


class DailyLimitsGuard:
    """Signal-level daily limits — implements RiskGuard protocol.

    Truncates signal quantities or filters signals based on per-underlying
    and total account daily limits. Wraps DailyTradeTracker core logic.
    """

    def __init__(
        self,
        order_store: OrderStore | None = None,
        config: DailyLimitsConfig | None = None,
    ) -> None:
        config = config or DailyLimitsConfig.load()
        if order_store is None:
            from src.business.trading.config.order_config import OrderConfig
            order_store = OrderStore(OrderConfig.load())
        self._tracker = DailyTradeTracker(order_store, config)
        self._config = config

    def check(
        self,
        signals: list[Signal],
        portfolio: PortfolioState,
        market: MarketSnapshot,
    ) -> list[Signal]:
        """Filter/truncate signals based on daily limits.

        Returns approved signals (possibly with reduced quantities).
        """
        if not self._config.enabled:
            return signals

        nlv = portfolio.nlv
        if nlv <= 0:
            return signals

        approved: list[Signal] = []
        # Track within-batch accumulation
        batch_quantities: dict[str, int] = {}
        batch_values: dict[str, float] = {}

        for signal in signals:
            # Cash-equivalent signals (e.g. SGOV sweep) bypass daily limits
            if signal.metadata.get("is_cash_equivalent"):
                approved.append(signal)
                continue

            underlying = signal.instrument.underlying
            qty = abs(signal.target_quantity)
            price = signal.quote_price or 0.0
            lot_size = signal.instrument.lot_size
            value = qty * price * lot_size
            decision_type = _SIGNAL_TYPE_TO_DECISION_TYPE.get(
                signal.type, "adjust"
            )

            # Include batch accumulation
            check_qty = qty + batch_quantities.get(underlying, 0)
            check_val = value + batch_values.get(underlying, 0.0)

            allowed_qty, reason = self._tracker.check_limits(
                underlying=underlying,
                quantity=check_qty,
                value=check_val,
                nlv=nlv,
                decision_type=decision_type,
            )

            # Subtract batch usage to get this signal's allowance
            batch_used = batch_quantities.get(underlying, 0)
            this_allowed = max(0, allowed_qty - batch_used)

            if this_allowed <= 0:
                logger.info(
                    f"DailyLimitsGuard: filtered {signal.type.value} "
                    f"{signal.instrument.symbol} qty={qty}: {reason}"
                )
                continue

            if this_allowed < qty:
                # Truncate: create new signal with reduced quantity
                sign = 1 if signal.target_quantity > 0 else -1
                signal = _truncate_signal(signal, sign * this_allowed)
                logger.info(
                    f"DailyLimitsGuard: truncated {signal.instrument.symbol} "
                    f"{qty} → {this_allowed}"
                )

            approved.append(signal)

            # Update batch tracking
            actual_qty = abs(signal.target_quantity)
            actual_value = actual_qty * price * lot_size
            batch_quantities[underlying] = (
                batch_quantities.get(underlying, 0) + actual_qty
            )
            batch_values[underlying] = (
                batch_values.get(underlying, 0.0) + actual_value
            )

        return approved


def _truncate_signal(signal: Signal, new_quantity: int) -> Signal:
    """Create a copy of signal with adjusted target_quantity.

    Signal is not frozen, so we create a new instance manually.
    """
    return Signal(
        type=signal.type,
        instrument=signal.instrument,
        target_quantity=new_quantity,
        reason=signal.reason,
        position_id=signal.position_id,
        roll_to=signal.roll_to,
        priority=signal.priority,
        metadata={**signal.metadata, "truncated_from": signal.target_quantity},
        quote_price=signal.quote_price,
        greeks=signal.greeks,
    )
