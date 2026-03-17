"""Tests for SignalOrderBuilder — Signal → OrderRequest conversion."""

from datetime import date

import pytest

from src.business.trading.models.order import (
    AssetClass,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.business.trading.signal_order_builder import SignalOrderBuilder
from src.strategy.models import (
    Instrument,
    InstrumentType,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)


@pytest.fixture
def builder():
    return SignalOrderBuilder()


@pytest.fixture
def put_instrument():
    return Instrument(
        type=InstrumentType.OPTION,
        underlying="QQQ",
        right=OptionRight.PUT,
        strike=450.0,
        expiry=date(2026, 6, 19),
        lot_size=100,
    )


@pytest.fixture
def call_instrument():
    return Instrument(
        type=InstrumentType.OPTION,
        underlying="QQQ",
        right=OptionRight.CALL,
        strike=500.0,
        expiry=date(2026, 9, 18),
        lot_size=100,
    )


@pytest.fixture
def stock_instrument():
    return Instrument(
        type=InstrumentType.STOCK,
        underlying="QQQ",
    )


@pytest.fixture
def empty_portfolio():
    return PortfolioState(
        date=date(2026, 3, 17),
        nlv=100_000.0,
        cash=50_000.0,
        margin_used=10_000.0,
        positions=[],
    )


@pytest.fixture
def portfolio_with_position(put_instrument):
    return PortfolioState(
        date=date(2026, 3, 17),
        nlv=100_000.0,
        cash=50_000.0,
        margin_used=10_000.0,
        positions=[
            PositionView(
                position_id="pos_001",
                instrument=put_instrument,
                quantity=-2,
                entry_price=5.50,
                entry_date=date(2026, 1, 15),
                current_price=3.20,
                underlying_price=460.0,
                unrealized_pnl=460.0,
                delta=-0.30,
                theta=0.05,
                dte=94,
            ),
        ],
    )


# ── ENTRY ──


class TestEntrySignal:
    def test_sell_put_entry(self, builder, put_instrument, empty_portfolio):
        signal = Signal(
            type=SignalType.ENTRY,
            instrument=put_instrument,
            target_quantity=-2,
            reason="short put entry",
            quote_price=5.50,
        )
        orders = builder.build([signal], empty_portfolio)

        assert len(orders) == 1
        order = orders[0]
        assert order.symbol == put_instrument.symbol
        assert order.underlying == "QQQ"
        assert order.asset_class == AssetClass.OPTION
        assert order.side == OrderSide.SELL
        assert order.quantity == 2
        assert order.limit_price == 5.50
        assert order.order_type == OrderType.LIMIT
        assert order.option_type == "put"
        assert order.strike == 450.0
        assert order.expiry == "2026-06-19"
        assert order.contract_multiplier == 100
        assert order.decision_type == "open"
        assert order.account_type == "paper"
        assert order.status == OrderStatus.PENDING_VALIDATION
        assert order.context["reason"] == "short put entry"

    def test_buy_call_entry(self, builder, call_instrument, empty_portfolio):
        signal = Signal(
            type=SignalType.ENTRY,
            instrument=call_instrument,
            target_quantity=3,
            reason="LEAPS call entry",
            quote_price=25.0,
        )
        orders = builder.build([signal], empty_portfolio)

        assert len(orders) == 1
        order = orders[0]
        assert order.side == OrderSide.BUY
        assert order.quantity == 3
        assert order.option_type == "call"
        assert order.strike == 500.0

    def test_stock_entry(self, builder, stock_instrument, empty_portfolio):
        signal = Signal(
            type=SignalType.ENTRY,
            instrument=stock_instrument,
            target_quantity=100,
            reason="buy stock",
            quote_price=460.0,
        )
        orders = builder.build([signal], empty_portfolio)

        assert len(orders) == 1
        order = orders[0]
        assert order.asset_class == AssetClass.STOCK
        assert order.side == OrderSide.BUY
        assert order.quantity == 100
        assert order.option_type is None
        assert order.strike is None

    def test_market_order_when_no_price(self, builder, put_instrument, empty_portfolio):
        signal = Signal(
            type=SignalType.ENTRY,
            instrument=put_instrument,
            target_quantity=-1,
            reason="no price",
            quote_price=None,
        )
        orders = builder.build([signal], empty_portfolio)
        assert orders[0].order_type == OrderType.MARKET
        assert orders[0].limit_price is None


# ── EXIT ──


class TestExitSignal:
    def test_buy_to_close_put(self, builder, put_instrument, portfolio_with_position):
        signal = Signal(
            type=SignalType.EXIT,
            instrument=put_instrument,
            target_quantity=2,  # positive = BUY to close
            reason="take profit",
            position_id="pos_001",
            quote_price=3.20,
        )
        orders = builder.build([signal], portfolio_with_position)

        assert len(orders) == 1
        order = orders[0]
        assert order.side == OrderSide.BUY
        assert order.quantity == 2
        assert order.decision_type == "close"
        assert order.limit_price == 3.20

    def test_exit_without_position_id(self, builder, put_instrument, empty_portfolio):
        signal = Signal(
            type=SignalType.EXIT,
            instrument=put_instrument,
            target_quantity=1,
            reason="close",
        )
        orders = builder.build([signal], empty_portfolio)
        assert len(orders) == 1
        assert orders[0].con_id is None


# ── ROLL ──


class TestRollSignal:
    def test_roll_produces_two_orders(
        self, builder, put_instrument, call_instrument, portfolio_with_position
    ):
        signal = Signal(
            type=SignalType.ROLL,
            instrument=put_instrument,
            target_quantity=-2,
            reason="roll to next expiry",
            position_id="pos_001",
            roll_to=call_instrument,
            quote_price=4.00,
        )
        orders = builder.build([signal], portfolio_with_position)

        assert len(orders) == 2
        close_order, open_order = orders

        # Close order: BUY to close, MARKET
        assert close_order.side == OrderSide.BUY
        assert close_order.quantity == 2
        assert close_order.order_type == OrderType.MARKET
        assert close_order.decision_type == "roll"
        assert close_order.context["roll_pair"] == "close"

        # Open order: SELL to open new, LIMIT
        assert open_order.side == OrderSide.SELL
        assert open_order.quantity == 2
        assert open_order.order_type == OrderType.LIMIT
        assert open_order.limit_price == 4.00
        assert open_order.decision_type == "roll"
        assert open_order.context["roll_pair"] == "open"
        assert open_order.strike == 500.0  # call_instrument

        # Same decision_id
        assert close_order.decision_id == open_order.decision_id

    def test_roll_without_roll_to_raises(
        self, builder, put_instrument, portfolio_with_position
    ):
        signal = Signal(
            type=SignalType.ROLL,
            instrument=put_instrument,
            target_quantity=-2,
            reason="missing roll_to",
            position_id="pos_001",
            roll_to=None,
        )
        # Error is caught internally, returns empty list
        orders = builder.build([signal], portfolio_with_position)
        assert len(orders) == 0


# ── REBALANCE ──


class TestRebalanceSignal:
    def test_rebalance_order(self, builder, put_instrument, portfolio_with_position):
        signal = Signal(
            type=SignalType.REBALANCE,
            instrument=put_instrument,
            target_quantity=1,
            reason="reduce position",
            position_id="pos_001",
            quote_price=3.50,
        )
        orders = builder.build([signal], portfolio_with_position)

        assert len(orders) == 1
        order = orders[0]
        assert order.decision_type == "adjust"
        assert order.side == OrderSide.BUY
        assert order.quantity == 1


# ── Multiple signals ──


class TestMultipleSignals:
    def test_mixed_signals(
        self, builder, put_instrument, call_instrument, portfolio_with_position
    ):
        signals = [
            Signal(
                type=SignalType.EXIT,
                instrument=put_instrument,
                target_quantity=2,
                reason="close",
                position_id="pos_001",
                quote_price=3.20,
            ),
            Signal(
                type=SignalType.ENTRY,
                instrument=call_instrument,
                target_quantity=-1,
                reason="new short call",
                quote_price=8.00,
            ),
        ]
        orders = builder.build(signals, portfolio_with_position)
        assert len(orders) == 2
        assert orders[0].decision_type == "close"
        assert orders[1].decision_type == "open"

    def test_bad_signal_skipped(self, builder, put_instrument, empty_portfolio):
        """A signal that raises an error is skipped, others proceed."""
        signals = [
            Signal(
                type=SignalType.ROLL,
                instrument=put_instrument,
                target_quantity=-1,
                reason="missing roll_to",
                roll_to=None,  # will fail
            ),
            Signal(
                type=SignalType.ENTRY,
                instrument=put_instrument,
                target_quantity=-1,
                reason="valid entry",
                quote_price=5.0,
            ),
        ]
        orders = builder.build(signals, empty_portfolio)
        assert len(orders) == 1  # only the valid entry


# ── Order ID / Decision ID ──


class TestIdGeneration:
    def test_unique_order_ids(self, builder, put_instrument, empty_portfolio):
        signals = [
            Signal(
                type=SignalType.ENTRY,
                instrument=put_instrument,
                target_quantity=-1,
                reason=f"entry {i}",
                quote_price=5.0,
            )
            for i in range(3)
        ]
        orders = builder.build(signals, empty_portfolio)
        order_ids = [o.order_id for o in orders]
        assert len(set(order_ids)) == 3

    def test_order_id_format(self, builder, put_instrument, empty_portfolio):
        signal = Signal(
            type=SignalType.ENTRY,
            instrument=put_instrument,
            target_quantity=-1,
            reason="test",
            quote_price=5.0,
        )
        orders = builder.build([signal], empty_portfolio)
        assert orders[0].order_id.startswith("ORD-")
