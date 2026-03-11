"""Signal Converter — bridges high-level Signals to engine execution parameters.

Converts backtest strategy Signals (which describe *what* to trade) into
the old TradeSignal format that BacktestExecutor can execute via its
existing _execute_open_signal / _execute_close_signal methods.

This is the key integration point between the new strategy abstraction
and the existing engine layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from src.backtest.strategy.models import (
    Instrument,
    InstrumentType,
    OptionRight,
    Signal,
    SignalType,
    MarketSnapshot,
)

logger = logging.getLogger(__name__)


class SignalConverter:
    """Converts new-style Signal → old-style TradeSignal for engine execution.

    The converter handles:
    - Stock instruments → stock proxy OptionQuote (for backward compat) OR
      native stock TradeSignal
    - Option instruments → OptionQuote with full contract details
    - ROLL signals → decomposed into CLOSE + OPEN pair
    """

    def convert_to_trade_signals(
        self,
        signals: list[Signal],
        market: MarketSnapshot,
        data_provider: Any,
    ) -> list:
        """Convert a batch of Signals to TradeSignals.

        Returns list of old-style TradeSignal objects compatible with
        BacktestExecutor._execute_open_signal / _execute_close_signal.
        """
        from src.business.strategy.models import TradeSignal
        from src.backtest.engine.trade_simulator import TradeAction

        trade_signals: list[TradeSignal] = []

        for signal in signals:
            if signal.type == SignalType.ROLL:
                # Decompose ROLL into CLOSE + OPEN
                close_sig = self._make_close_signal(signal, market)
                if close_sig:
                    trade_signals.append(close_sig)
                if signal.roll_to:
                    open_sig = self._make_open_signal(
                        Signal(
                            type=SignalType.ENTRY,
                            instrument=signal.roll_to,
                            target_quantity=abs(signal.target_quantity),
                            reason=f"Roll into: {signal.reason}",
                            metadata=signal.metadata,
                            quote_price=signal.metadata.get("roll_to_price"),
                            greeks=signal.metadata.get("roll_to_greeks"),
                        ),
                        market,
                        data_provider,
                    )
                    if open_sig:
                        trade_signals.append(open_sig)
            elif signal.type == SignalType.EXIT:
                close_sig = self._make_close_signal(signal, market)
                if close_sig:
                    trade_signals.append(close_sig)
            elif signal.type in (SignalType.ENTRY, SignalType.REBALANCE):
                open_sig = self._make_open_signal(signal, market, data_provider)
                if open_sig:
                    trade_signals.append(open_sig)

        return trade_signals

    def _make_close_signal(
        self,
        signal: Signal,
        market: MarketSnapshot,
    ) -> Optional[Any]:
        """Convert EXIT/ROLL Signal to a close TradeSignal."""
        from src.business.strategy.models import TradeSignal
        from src.backtest.engine.trade_simulator import TradeAction

        alert_type = signal.metadata.get("alert_type")
        if signal.type == SignalType.ROLL:
            alert_type = alert_type or "roll_dte"

        return TradeSignal(
            action=TradeAction.CLOSE,
            symbol=signal.instrument.symbol,
            quantity=signal.target_quantity,  # negative for closing longs
            reason=signal.reason,
            alert_type=alert_type,
            position_id=signal.position_id,
            priority="high" if signal.priority > 0 else "normal",
        )

    def _make_open_signal(
        self,
        signal: Signal,
        market: MarketSnapshot,
        data_provider: Any,
    ) -> Optional[Any]:
        """Convert ENTRY Signal to an open TradeSignal with OptionQuote."""
        from src.business.strategy.models import TradeSignal
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionContract, OptionQuote, OptionType, Greeks

        instrument = signal.instrument

        if instrument.is_stock:
            return self._make_stock_open_signal(signal, market)

        if instrument.is_option:
            return self._make_option_open_signal(signal, market, data_provider)

        logger.warning(f"Unsupported instrument type: {instrument.type}")
        return None

    def _make_stock_open_signal(
        self,
        signal: Signal,
        market: MarketSnapshot,
    ) -> Optional[Any]:
        """Create a stock open signal using stock proxy pattern."""
        from src.business.strategy.models import TradeSignal
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionContract, OptionQuote, OptionType, Greeks

        instrument = signal.instrument
        price = signal.quote_price or market.get_price_or_zero(instrument.underlying)
        if price <= 0:
            return None

        # Stock proxy: strike=0.01, lot_size=1, expiry far future
        far_expiry = market.date + timedelta(days=9999)
        option_contract = OptionContract(
            symbol=f"{instrument.underlying}_{far_expiry.strftime('%y%m%d')}_C_0",
            underlying=instrument.underlying,
            option_type=OptionType.CALL,
            strike_price=0.01,
            expiry_date=far_expiry,
            lot_size=1,
        )

        greeks = Greeks(delta=1.0, gamma=0.0, theta=0.0, vega=0.0)

        quote = OptionQuote(
            contract=option_contract,
            timestamp=datetime.combine(market.date, datetime.min.time()),
            bid=price,
            ask=price,
            last_price=price,
            iv=0.0,
            volume=99999,
            open_interest=99999,
            greeks=greeks,
        )

        return TradeSignal(
            action=TradeAction.OPEN,
            symbol=option_contract.symbol,
            quantity=signal.target_quantity,
            reason=signal.reason,
            priority="normal",
            quote=quote,
        )

    def _make_option_open_signal(
        self,
        signal: Signal,
        market: MarketSnapshot,
        data_provider: Any,
    ) -> Optional[Any]:
        """Create an option open signal with OptionQuote."""
        from src.business.strategy.models import TradeSignal
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionContract, OptionQuote, OptionType, Greeks

        instrument = signal.instrument
        if not instrument.expiry or not instrument.strike or not instrument.right:
            logger.warning(f"Incomplete option instrument: {instrument}")
            return None

        price = signal.quote_price
        if price is None or price <= 0:
            logger.warning(f"No quote price for option signal: {instrument}")
            return None

        option_type = OptionType.CALL if instrument.right == OptionRight.CALL else OptionType.PUT
        lot_size = instrument.lot_size

        option_contract = OptionContract(
            symbol=instrument.underlying,
            underlying=instrument.underlying,
            option_type=option_type,
            strike_price=instrument.strike,
            expiry_date=instrument.expiry,
            lot_size=lot_size,
        )

        # Build Greeks from signal metadata
        greeks_dict = signal.greeks or {}
        greeks = Greeks(
            delta=greeks_dict.get("delta", 0.0),
            gamma=greeks_dict.get("gamma", 0.0),
            theta=greeks_dict.get("theta", 0.0),
            vega=greeks_dict.get("vega", 0.0),
        )

        quote = OptionQuote(
            contract=option_contract,
            timestamp=datetime.combine(market.date, datetime.min.time()),
            bid=price,
            ask=price,
            last_price=price,
            iv=greeks_dict.get("iv", 0.0),
            volume=0,
            open_interest=0,
            greeks=greeks,
        )

        return TradeSignal(
            action=TradeAction.OPEN,
            symbol=instrument.underlying,
            quantity=signal.target_quantity,
            reason=signal.reason,
            priority="normal",
            quote=quote,
        )
