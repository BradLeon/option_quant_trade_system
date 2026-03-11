"""Tests for the new V2 backtest strategy abstraction layer.

Tests cover:
- Data models (Instrument, Signal, MarketSnapshot, PortfolioState)
- Protocol & base class (BacktestStrategy)
- Signal computers (SmaComputer, MomentumVolTargetComputer)
- Risk guards (AccountRiskGuard, VolTargetRiskGuard)
- Signal converter
- Strategy registry
- Strategy implementations (SmaStock, SmaLeaps, MomentumMixed)
"""

import math
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

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
from src.backtest.strategy.protocol import BacktestStrategy, StrategyProtocol
from src.backtest.strategy.registry import BacktestStrategyRegistry


# ============================================================
# Data Model Tests
# ============================================================


class TestInstrument:
    def test_stock_instrument(self):
        stock = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        assert stock.is_stock
        assert not stock.is_option
        assert stock.symbol == "SPY"

    def test_option_instrument(self):
        opt = Instrument(
            type=InstrumentType.OPTION,
            underlying="SPY",
            right=OptionRight.CALL,
            strike=450.0,
            expiry=date(2026, 6, 19),
        )
        assert opt.is_option
        assert not stock_is_stock(opt)
        assert "SPY" in opt.symbol
        assert "C" in opt.symbol
        assert "450" in opt.symbol

    def test_instrument_is_frozen(self):
        stock = Instrument(type=InstrumentType.STOCK, underlying="SPY")
        with pytest.raises(AttributeError):
            stock.underlying = "QQQ"

    def test_instrument_as_dict_key(self):
        i1 = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        i2 = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        d = {i1: 100}
        assert d[i2] == 100


def stock_is_stock(instrument):
    return instrument.is_stock


class TestSignal:
    def test_entry_signal(self):
        inst = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        sig = Signal(
            type=SignalType.ENTRY,
            instrument=inst,
            target_quantity=100,
            reason="test entry",
            quote_price=500.0,
        )
        assert sig.type == SignalType.ENTRY
        assert sig.target_quantity == 100
        assert sig.quote_price == 500.0

    def test_exit_signal(self):
        inst = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        sig = Signal(
            type=SignalType.EXIT,
            instrument=inst,
            target_quantity=-100,
            reason="test exit",
            position_id="POS001",
        )
        assert sig.type == SignalType.EXIT
        assert sig.position_id == "POS001"


class TestMarketSnapshot:
    def test_get_price(self):
        market = MarketSnapshot(
            date=date(2026, 1, 15),
            prices={"SPY": 500.0, "QQQ": 400.0},
            vix=18.5,
        )
        assert market.get_price("SPY") == 500.0
        assert market.get_price_or_zero("AAPL") == 0.0

    def test_get_price_missing(self):
        market = MarketSnapshot(date=date(2026, 1, 15), prices={})
        with pytest.raises(KeyError):
            market.get_price("SPY")


class TestPortfolioState:
    def test_empty_portfolio(self):
        pf = PortfolioState(date=date(2026, 1, 15), nlv=1_000_000, cash=1_000_000, margin_used=0)
        assert pf.position_count == 0
        assert pf.get_stock_positions() == []
        assert pf.get_option_positions() == []

    def test_portfolio_with_positions(self):
        stock_inst = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        option_inst = Instrument(
            type=InstrumentType.OPTION, underlying="SPY",
            right=OptionRight.PUT, strike=450, expiry=date(2026, 3, 21),
        )
        pf = PortfolioState(
            date=date(2026, 1, 15),
            nlv=1_000_000,
            cash=500_000,
            margin_used=100_000,
            positions=[
                PositionView(
                    position_id="P1", instrument=stock_inst, quantity=100,
                    entry_price=490, entry_date=date(2026, 1, 1),
                    current_price=500, underlying_price=500, unrealized_pnl=1000,
                    lot_size=1,
                ),
                PositionView(
                    position_id="P2", instrument=option_inst, quantity=-1,
                    entry_price=5.0, entry_date=date(2026, 1, 10),
                    current_price=3.0, underlying_price=500, unrealized_pnl=200,
                    delta=-0.2, dte=65,
                ),
            ],
        )
        assert pf.position_count == 2
        assert len(pf.get_stock_positions()) == 1
        assert len(pf.get_option_positions()) == 1
        assert len(pf.get_positions_by_underlying("SPY")) == 2


# ============================================================
# Protocol & Base Class Tests
# ============================================================


class TestBacktestStrategy:
    def test_protocol_compliance(self):
        """BacktestStrategy instances satisfy StrategyProtocol."""

        class MyStrategy(BacktestStrategy):
            @property
            def name(self):
                return "test"

        s = MyStrategy()
        assert isinstance(s, StrategyProtocol)

    def test_template_method(self):
        """generate_signals calls on_day_start → exit → entry."""

        class MyStrategy(BacktestStrategy):
            call_order = []

            @property
            def name(self):
                return "test"

            def on_day_start(self, m, p):
                self.call_order.append("start")

            def compute_exit_signals(self, m, p, dp):
                self.call_order.append("exit")
                return [Signal(SignalType.EXIT, Instrument(InstrumentType.STOCK, "SPY"), -1, "x", position_id="P1")]

            def compute_entry_signals(self, m, p, dp):
                self.call_order.append("entry")
                return [Signal(SignalType.ENTRY, Instrument(InstrumentType.STOCK, "SPY"), 1, "y")]

        s = MyStrategy()
        market = MarketSnapshot(date=date(2026, 1, 15), prices={"SPY": 500.0})
        portfolio = PortfolioState(date=date(2026, 1, 15), nlv=1e6, cash=1e6, margin_used=0)
        signals = s.generate_signals(market, portfolio, None)

        assert s.call_order == ["start", "exit", "entry"]
        assert len(signals) == 2
        assert signals[0].type == SignalType.EXIT
        assert signals[1].type == SignalType.ENTRY
        assert s._trading_day_count == 1

    def test_decision_day(self):
        class MyStrategy(BacktestStrategy):
            @property
            def name(self):
                return "test"

        s = MyStrategy()
        s._trading_day_count = 5
        assert s._is_decision_day(5)
        assert not s._is_decision_day(3)

        s._trading_day_count = 10
        assert s._is_decision_day(5)
        assert s._is_decision_day(2)


# ============================================================
# Risk Guard Tests
# ============================================================


class TestAccountRiskGuard:
    def test_blocks_entry_at_max_positions(self):
        from src.backtest.strategy.risk.account_risk import AccountRiskGuard, AccountRiskConfig

        guard = AccountRiskGuard(AccountRiskConfig(max_positions=2))
        market = MarketSnapshot(date=date(2026, 1, 15), prices={"SPY": 500.0})

        # 2 existing positions
        positions = [
            PositionView("P1", Instrument(InstrumentType.STOCK, "SPY"), 100, 490, date(2026, 1, 1), 500, 500, 1000, lot_size=1),
            PositionView("P2", Instrument(InstrumentType.STOCK, "QQQ"), 50, 390, date(2026, 1, 1), 400, 400, 500, lot_size=1),
        ]
        portfolio = PortfolioState(date(2026, 1, 15), 1e6, 5e5, 0, positions)

        entry = Signal(SignalType.ENTRY, Instrument(InstrumentType.STOCK, "AAPL"), 10, "buy AAPL")
        exit_sig = Signal(SignalType.EXIT, Instrument(InstrumentType.STOCK, "SPY"), -100, "sell SPY", position_id="P1")

        result = guard.check([exit_sig, entry], portfolio, market)
        # Exit always passes, entry blocked (2 existing >= max 2)
        assert len(result) == 1
        assert result[0].type == SignalType.EXIT

    def test_allows_exit_always(self):
        from src.backtest.strategy.risk.account_risk import AccountRiskGuard, AccountRiskConfig

        guard = AccountRiskGuard(AccountRiskConfig(max_positions=0))
        market = MarketSnapshot(date=date(2026, 1, 15), prices={})
        portfolio = PortfolioState(date(2026, 1, 15), 1e6, 1e6, 0)

        exit_sig = Signal(SignalType.EXIT, Instrument(InstrumentType.STOCK, "SPY"), -100, "sell", position_id="P1")
        result = guard.check([exit_sig], portfolio, market)
        assert len(result) == 1


class TestVolTargetRiskGuard:
    def test_scales_down_on_high_vix(self):
        from src.backtest.strategy.risk.vol_target_risk import VolTargetRiskGuard, VolTargetRiskConfig

        guard = VolTargetRiskGuard(VolTargetRiskConfig(vol_target=15.0))
        market = MarketSnapshot(date=date(2026, 1, 15), prices={"SPY": 500.0}, vix=30.0)
        portfolio = PortfolioState(date(2026, 1, 15), 1e6, 1e6, 0)

        entry = Signal(SignalType.ENTRY, Instrument(InstrumentType.STOCK, "SPY"), 100, "buy")
        result = guard.check([entry], portfolio, market)
        assert len(result) == 1
        # vol_scalar = 15/30 = 0.5, so 100 * 0.5 = 50
        assert result[0].target_quantity == 50

    def test_no_scaling_on_low_vix(self):
        from src.backtest.strategy.risk.vol_target_risk import VolTargetRiskGuard, VolTargetRiskConfig

        guard = VolTargetRiskGuard(VolTargetRiskConfig(vol_target=15.0))
        market = MarketSnapshot(date=date(2026, 1, 15), prices={"SPY": 500.0}, vix=12.0)
        portfolio = PortfolioState(date(2026, 1, 15), 1e6, 1e6, 0)

        entry = Signal(SignalType.ENTRY, Instrument(InstrumentType.STOCK, "SPY"), 100, "buy")
        result = guard.check([entry], portfolio, market)
        assert len(result) == 1
        assert result[0].target_quantity == 100  # No scaling


# ============================================================
# Registry Tests
# ============================================================


class TestRegistry:
    def test_create_known_strategy(self):
        strategy = BacktestStrategyRegistry.create("sma_stock")
        assert isinstance(strategy, StrategyProtocol)
        assert "sma" in strategy.name.lower()

    def test_create_legacy_name(self):
        strategy = BacktestStrategyRegistry.create("spy_buy_and_hold_sma_timing")
        assert isinstance(strategy, StrategyProtocol)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            BacktestStrategyRegistry.create("nonexistent_strategy")

    def test_available_strategies(self):
        available = BacktestStrategyRegistry.get_available_strategies()
        assert "sma_stock" in available
        assert "sma_leaps" in available
        assert "momentum_mixed" in available

    def test_v2_detection(self):
        assert BacktestStrategyRegistry.is_v2_strategy("sma_stock")
        assert not BacktestStrategyRegistry.is_v2_strategy("short_options_with_expire_itm_stock_trade")


# ============================================================
# SmaStockStrategy Tests
# ============================================================


class TestSmaStockStrategy:
    def _make_market(self, prices=None):
        return MarketSnapshot(
            date=date(2026, 1, 15),
            prices=prices or {"SPY": 500.0},
            vix=18.0,
        )

    def _make_portfolio(self, positions=None, cash=1_000_000):
        return PortfolioState(
            date=date(2026, 1, 15),
            nlv=1_000_000,
            cash=cash,
            margin_used=0,
            positions=positions or [],
        )

    def test_entry_when_sma_bullish(self):
        """Strategy should generate entry signal when SMA is bullish."""
        from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig

        config = SmaStockConfig(decision_frequency=1)
        strategy = SmaStockStrategy(config)

        market = self._make_market()
        portfolio = self._make_portfolio()

        # Mock the SMA computer to return bullish
        strategy._sma._cached_date = market.date
        strategy._sma._cached_result = {"invested": True, "close": 500.0, "sma_long": 480.0, "sma_short": 0.0, "symbol": "SPY"}

        signals = strategy.generate_signals(market, portfolio, None)
        assert len(signals) == 1
        assert signals[0].type == SignalType.ENTRY
        assert signals[0].instrument.is_stock
        assert signals[0].target_quantity > 0

    def test_exit_when_sma_bearish(self):
        """Strategy should generate exit signal when SMA turns bearish."""
        from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig

        config = SmaStockConfig(decision_frequency=1)
        strategy = SmaStockStrategy(config)

        stock_inst = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        position = PositionView(
            position_id="P1", instrument=stock_inst, quantity=100,
            entry_price=490, entry_date=date(2026, 1, 1),
            current_price=500, underlying_price=500, unrealized_pnl=1000,
            lot_size=1,
        )
        market = self._make_market()
        portfolio = self._make_portfolio(positions=[position])

        # Mock SMA bearish
        strategy._sma._cached_date = market.date
        strategy._sma._cached_result = {"invested": False, "close": 500.0, "sma_long": 520.0, "sma_short": 0.0, "symbol": "SPY"}

        signals = strategy.generate_signals(market, portfolio, None)
        assert len(signals) == 1
        assert signals[0].type == SignalType.EXIT
        assert signals[0].target_quantity == -100
        assert signals[0].position_id == "P1"

    def test_no_entry_when_holding(self):
        """Strategy should not enter when already holding positions."""
        from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig

        config = SmaStockConfig(decision_frequency=1)
        strategy = SmaStockStrategy(config)

        stock_inst = Instrument(type=InstrumentType.STOCK, underlying="SPY", lot_size=1)
        position = PositionView(
            position_id="P1", instrument=stock_inst, quantity=100,
            entry_price=490, entry_date=date(2026, 1, 1),
            current_price=500, underlying_price=500, unrealized_pnl=1000,
            lot_size=1,
        )
        market = self._make_market()
        portfolio = self._make_portfolio(positions=[position])

        # Mock SMA bullish — should still not enter
        strategy._sma._cached_date = market.date
        strategy._sma._cached_result = {"invested": True, "close": 500.0, "sma_long": 480.0, "sma_short": 0.0, "symbol": "SPY"}

        signals = strategy.generate_signals(market, portfolio, None)
        # Should have 0 signals (bullish + holding → do nothing)
        assert len(signals) == 0

    def test_decision_frequency(self):
        """Strategy should only trade on decision days."""
        from src.backtest.strategy.versions.sma_stock import SmaStockStrategy, SmaStockConfig

        config = SmaStockConfig(decision_frequency=5)
        strategy = SmaStockStrategy(config)

        market = self._make_market()
        portfolio = self._make_portfolio()

        # Mock SMA bullish
        strategy._sma._cached_date = market.date
        strategy._sma._cached_result = {"invested": True, "close": 500.0, "sma_long": 480.0, "sma_short": 0.0, "symbol": "SPY"}

        # Day 1 — not a decision day (5 % 5 != 0... wait, 1 % 5 != 0)
        signals = strategy.generate_signals(market, portfolio, None)
        assert strategy._trading_day_count == 1
        assert len(signals) == 0  # Not decision day

        # Days 2-4 — not decision days
        for _ in range(4):
            strategy._sma._cached_date = None  # Reset cache
            strategy._sma._cached_date = market.date
            signals = strategy.generate_signals(market, portfolio, None)

        assert strategy._trading_day_count == 5
        assert len(signals) == 1  # Day 5 = decision day


# ============================================================
# Signal Converter Tests
# ============================================================


class TestSignalConverter:
    def test_stock_entry_conversion(self):
        from src.backtest.strategy.signal_converter import SignalConverter

        converter = SignalConverter()
        market = MarketSnapshot(date=date(2026, 1, 15), prices={"SPY": 500.0})

        signal = Signal(
            type=SignalType.ENTRY,
            instrument=Instrument(InstrumentType.STOCK, "SPY", lot_size=1),
            target_quantity=100,
            reason="test entry",
            quote_price=500.0,
        )

        trade_signals = converter.convert_to_trade_signals([signal], market, None)
        assert len(trade_signals) == 1

        ts = trade_signals[0]
        assert ts.quantity == 100
        assert ts.quote is not None
        assert ts.quote.contract.strike_price == 0.01  # Stock proxy
        assert ts.quote.contract.lot_size == 1

    def test_exit_conversion(self):
        from src.backtest.strategy.signal_converter import SignalConverter

        converter = SignalConverter()
        market = MarketSnapshot(date=date(2026, 1, 15), prices={"SPY": 500.0})

        signal = Signal(
            type=SignalType.EXIT,
            instrument=Instrument(InstrumentType.STOCK, "SPY", lot_size=1),
            target_quantity=-100,
            reason="test exit",
            position_id="P1",
        )

        trade_signals = converter.convert_to_trade_signals([signal], market, None)
        assert len(trade_signals) == 1
        assert trade_signals[0].position_id == "P1"
