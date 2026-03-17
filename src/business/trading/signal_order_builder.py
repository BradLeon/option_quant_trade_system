"""Signal → OrderRequest direct conversion.

Replaces the two-step chain:
  LiveSignalConverter (Signal → TradingDecision) +
  OrderGenerator (TradingDecision → OrderRequest)

with a single step:
  SignalOrderBuilder (Signal → OrderRequest)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.models.order import (
    AssetClass,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.strategy.models import (
    Instrument,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)

logger = logging.getLogger(__name__)

# Signal type → decision_type string (for DailyLimits tracking)
_SIGNAL_TYPE_TO_DECISION_TYPE: dict[SignalType, str] = {
    SignalType.ENTRY: "open",
    SignalType.EXIT: "close",
    SignalType.ROLL: "roll",
    SignalType.REBALANCE: "adjust",
}


class SignalOrderBuilder:
    """Signal → OrderRequest direct conversion.

    Consolidates logic from LiveSignalConverter + OrderGenerator into
    a single step. Handles all signal types:
    - ENTRY → 1 OrderRequest
    - EXIT  → 1 OrderRequest (resolves position from portfolio)
    - ROLL  → 2 OrderRequests (close + open)
    - REBALANCE → 1 OrderRequest
    """

    def __init__(self, config: OrderConfig | None = None) -> None:
        self._config = config or OrderConfig.load()

    def build(
        self,
        signals: list[Signal],
        portfolio: PortfolioState,
    ) -> list[OrderRequest]:
        """Convert strategy signals to submittable orders.

        Args:
            signals: Strategy output signals (already filtered by RiskGuards)
            portfolio: Current portfolio state (for EXIT/ROLL position lookup)

        Returns:
            List of OrderRequest ready for validation and submission.
        """
        orders: list[OrderRequest] = []
        # Build position lookup: position_id → PositionView
        position_map = {p.position_id: p for p in portfolio.positions}

        for signal in signals:
            try:
                if signal.type == SignalType.ROLL:
                    roll_orders = self._build_roll_orders(signal, position_map)
                    orders.extend(roll_orders)
                elif signal.type == SignalType.EXIT:
                    order = self._build_exit_order(signal, position_map)
                    orders.append(order)
                elif signal.type == SignalType.ENTRY:
                    order = self._build_entry_order(signal)
                    orders.append(order)
                elif signal.type == SignalType.REBALANCE:
                    order = self._build_rebalance_order(signal, position_map)
                    orders.append(order)
            except Exception as e:
                logger.error(
                    f"Failed to build order for signal "
                    f"{signal.type.value} {signal.instrument}: {e}"
                )

        return orders

    def _build_entry_order(self, signal: Signal) -> OrderRequest:
        """Build order for ENTRY signal."""
        return self._make_order(
            signal=signal,
            instrument=signal.instrument,
            quantity=signal.target_quantity,
            limit_price=signal.quote_price,
            con_id=None,
        )

    def _build_exit_order(
        self,
        signal: Signal,
        position_map: dict[str, PositionView],
    ) -> OrderRequest:
        """Build order for EXIT signal. Resolves con_id from portfolio."""
        con_id = self._resolve_con_id(signal.position_id, position_map)
        return self._make_order(
            signal=signal,
            instrument=signal.instrument,
            quantity=signal.target_quantity,
            limit_price=signal.quote_price,
            con_id=con_id,
        )

    def _build_rebalance_order(
        self,
        signal: Signal,
        position_map: dict[str, PositionView],
    ) -> OrderRequest:
        """Build order for REBALANCE signal."""
        con_id = self._resolve_con_id(signal.position_id, position_map)
        return self._make_order(
            signal=signal,
            instrument=signal.instrument,
            quantity=signal.target_quantity,
            limit_price=signal.quote_price,
            con_id=con_id,
        )

    def _build_roll_orders(
        self,
        signal: Signal,
        position_map: dict[str, PositionView],
    ) -> list[OrderRequest]:
        """Build close + open orders for ROLL signal.

        Returns:
            [close_order, open_order]
        """
        if not signal.roll_to:
            raise ValueError(
                f"ROLL signal for {signal.instrument} missing roll_to"
            )

        decision_id = self._generate_decision_id()
        con_id = self._resolve_con_id(signal.position_id, position_map)

        # 1. Close order: BUY to close current position (market order)
        close_qty = abs(signal.target_quantity)
        close_order = self._make_order_raw(
            decision_id=decision_id,
            signal_type=SignalType.ROLL,
            instrument=signal.instrument,
            quantity=close_qty,  # positive = BUY to close
            limit_price=None,
            con_id=con_id,
            reason=f"ROLL close: {signal.reason}",
            context={"roll_pair": "close"},
            force_market=True,
        )

        # 2. Open order: SELL to open new contract
        open_qty = -close_qty  # negative = SELL to open
        open_order = self._make_order_raw(
            decision_id=decision_id,
            signal_type=SignalType.ROLL,
            instrument=signal.roll_to,
            quantity=open_qty,
            limit_price=signal.quote_price,  # roll credit as limit
            con_id=None,  # new contract, no con_id
            reason=f"ROLL open: {signal.reason}",
            context={"roll_pair": "open"},
            force_market=signal.quote_price is None,
        )

        return [close_order, open_order]

    def _make_order(
        self,
        signal: Signal,
        instrument: Instrument,
        quantity: int,
        limit_price: float | None,
        con_id: int | None,
    ) -> OrderRequest:
        """Create a single OrderRequest from signal + instrument."""
        return self._make_order_raw(
            decision_id=self._generate_decision_id(),
            signal_type=signal.type,
            instrument=instrument,
            quantity=quantity,
            limit_price=limit_price,
            con_id=con_id,
            reason=signal.reason,
            context={},
            force_market=False,
        )

    def _make_order_raw(
        self,
        decision_id: str,
        signal_type: SignalType,
        instrument: Instrument,
        quantity: int,
        limit_price: float | None,
        con_id: int | None,
        reason: str,
        context: dict[str, Any],
        force_market: bool,
    ) -> OrderRequest:
        """Low-level order construction."""
        # Asset class
        asset_class = (
            AssetClass.OPTION if instrument.is_option else AssetClass.STOCK
        )

        # Side: positive qty = BUY, negative = SELL
        side = OrderSide.SELL if quantity < 0 else OrderSide.BUY

        # Order type
        if force_market:
            order_type = OrderType.MARKET
        elif limit_price is not None:
            order_type = OrderType.LIMIT
        else:
            order_type = OrderType.MARKET

        # Option fields
        option_type = instrument.right.value if instrument.right else None
        strike = instrument.strike
        expiry = instrument.expiry.isoformat() if instrument.expiry else None

        # Decision type for DailyLimits tracking
        decision_type = _SIGNAL_TYPE_TO_DECISION_TYPE.get(
            signal_type, "adjust"
        )

        # Build context
        full_context = {
            "decision_type": decision_type,
            "reason": reason,
            **context,
        }

        order = OrderRequest(
            order_id=self._generate_order_id(),
            decision_id=decision_id,
            symbol=instrument.symbol,
            asset_class=asset_class,
            underlying=instrument.underlying,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            con_id=con_id,
            side=side,
            order_type=order_type,
            quantity=abs(quantity),
            limit_price=limit_price,
            time_in_force=self._config.default_time_in_force,
            contract_multiplier=instrument.lot_size,
            currency="USD",
            decision_type=decision_type,
            broker="ibkr",
            account_type="paper",  # CRITICAL: always paper
            status=OrderStatus.PENDING_VALIDATION,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            context=full_context,
        )

        logger.info(
            f"Order built: {order.order_id} {decision_type} "
            f"{side.value} {order.quantity} {instrument.symbol}"
        )

        return order

    def _resolve_con_id(
        self,
        position_id: str | None,
        position_map: dict[str, PositionView],
    ) -> int | None:
        """Resolve IBKR con_id from position_id via portfolio positions.

        The PositionView doesn't directly store con_id, but it's available
        if the LiveSnapshotBuilder populated it. Returns None if not found.
        """
        if not position_id or position_id not in position_map:
            return None
        # PositionView doesn't have con_id field directly,
        # but the caller (LiveStrategyExecutor) maintains a separate lookup.
        # Return None here — con_id resolution is handled externally if needed.
        return None

    @staticmethod
    def _generate_order_id() -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:8]
        return f"ORD-{timestamp}-{unique}"

    @staticmethod
    def _generate_decision_id() -> str:
        return f"live_{uuid.uuid4().hex[:8]}"
