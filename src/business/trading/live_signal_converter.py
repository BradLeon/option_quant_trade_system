"""Live Signal Converter — Convert V2 Signal to TradingDecision.

Bridges the gap between the strategy layer (Signal) and the live
trading execution layer (TradingDecision → OrderManager → IBKR).

Analogous to backtest's SignalConverter (Signal → TradeSignal),
but targets live trading models.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from src.strategy.models import Signal, SignalType
from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
    TradingDecision,
)

logger = logging.getLogger(__name__)


class LiveSignalConverter:
    """Convert V2 strategy Signals into live TradingDecisions.

    Handles all signal types (ENTRY, EXIT, ROLL, REBALANCE) and maps
    Instrument fields to TradingDecision contract fields.
    """

    _SIGNAL_TO_DECISION: dict[SignalType, DecisionType] = {
        SignalType.ENTRY: DecisionType.OPEN,
        SignalType.EXIT: DecisionType.CLOSE,
        SignalType.ROLL: DecisionType.ROLL,
        SignalType.REBALANCE: DecisionType.ADJUST,
    }

    _SIGNAL_TO_SOURCE: dict[SignalType, DecisionSource] = {
        SignalType.ENTRY: DecisionSource.SCREEN_SIGNAL,
        SignalType.EXIT: DecisionSource.MONITOR_ALERT,
        SignalType.ROLL: DecisionSource.MONITOR_ALERT,
        SignalType.REBALANCE: DecisionSource.MONITOR_ALERT,
    }

    def convert(
        self,
        signals: list[Signal],
        account_state: AccountState,
        position_map: dict[str, PositionContext] | None = None,
    ) -> list[TradingDecision]:
        """Convert V2 Signals to TradingDecisions.

        Args:
            signals: Strategy output signals
            account_state: Current account state (for decision context)
            position_map: Map of position_id → PositionContext (for EXIT/ROLL)

        Returns:
            List of TradingDecision ready for TradingPipeline.execute_decisions()
        """
        decisions: list[TradingDecision] = []
        position_map = position_map or {}

        for signal in signals:
            try:
                decision = self._convert_single(signal, account_state, position_map)
                decisions.append(decision)
            except Exception as e:
                logger.error(
                    f"Failed to convert signal {signal.type.value} "
                    f"{signal.instrument}: {e}"
                )

        return decisions

    def _convert_single(
        self,
        signal: Signal,
        account_state: AccountState,
        position_map: dict[str, PositionContext],
    ) -> TradingDecision:
        """Convert a single Signal to TradingDecision."""
        instrument = signal.instrument

        # Resolve position context for EXIT/ROLL signals
        pos_context = None
        con_id = None
        if signal.position_id and signal.position_id in position_map:
            pos_context = position_map[signal.position_id]
            con_id = pos_context.con_id

        decision = TradingDecision(
            decision_id=f"live_{uuid4().hex[:8]}",
            decision_type=self._SIGNAL_TO_DECISION[signal.type],
            source=self._SIGNAL_TO_SOURCE[signal.type],
            priority=self._map_priority(signal),
            # Contract info from Instrument
            symbol=instrument.symbol,
            underlying=instrument.underlying,
            option_type=(
                instrument.right.value if instrument.right else None
            ),
            strike=instrument.strike,
            expiry=(
                instrument.expiry.isoformat() if instrument.expiry else None
            ),
            con_id=con_id,
            # Trade params
            quantity=signal.target_quantity,
            limit_price=signal.quote_price,
            # Context
            account_state=account_state,
            position_context=pos_context,
            position_id=signal.position_id,
            reason=signal.reason,
            broker="ibkr",
            contract_multiplier=instrument.lot_size,
            # ROLL params
            roll_to_expiry=(
                signal.roll_to.expiry.isoformat()
                if signal.roll_to and signal.roll_to.expiry
                else None
            ),
            roll_to_strike=(
                signal.roll_to.strike if signal.roll_to else None
            ),
        )

        # Auto-approve (risk guards already filtered)
        decision.approve(notes="Auto-approved by LiveStrategyExecutor")
        return decision

    def _map_priority(self, signal: Signal) -> DecisionPriority:
        """Map signal priority to decision priority.

        EXIT signals are CRITICAL (reduce risk), others are NORMAL.
        """
        if signal.type == SignalType.EXIT:
            return DecisionPriority.HIGH
        if signal.type == SignalType.ROLL:
            return DecisionPriority.HIGH
        if signal.priority > 50:
            return DecisionPriority.HIGH
        return DecisionPriority.NORMAL
