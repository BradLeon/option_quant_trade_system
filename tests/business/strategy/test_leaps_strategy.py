"""Unit tests for Long LEAPS Call + SMA Timing Strategy"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.business.strategy.versions.long_leaps_call_sma_timing import (
    LeapsCallConfig,
    LongLeapsCallSmaTiming,
)
from src.business.strategy.models import MarketContext, TradeSignal
from src.business.monitoring.models import PositionData
from src.business.screening.models import ContractOpportunity
from src.data.models.option import OptionChain, OptionQuote, OptionContract, OptionType, Greeks
from src.data.models.stock import KlineBar, KlineType


# ==========================================
# Fixtures
# ==========================================

def _make_kline(symbol: str, dt: date, close: float) -> KlineBar:
    """Helper to create a KlineBar"""
    return KlineBar(
        symbol=symbol,
        timestamp=datetime.combine(dt, datetime.min.time()),
        ktype=KlineType.DAY,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=1_000_000,
    )


def _make_klines_bullish(symbol: str = "SPY", n_days: int = 250, base_price: float = 450.0) -> list[KlineBar]:
    """Generate bullish klines: price trending up, above SMA200"""
    klines = []
    start = date(2025, 1, 1)
    for i in range(n_days):
        dt = start + timedelta(days=i)
        # Gradual uptrend from base_price
        price = base_price + i * 0.3
        klines.append(_make_kline(symbol, dt, price))
    return klines


def _make_klines_bearish(symbol: str = "SPY", n_days: int = 250, base_price: float = 550.0) -> list[KlineBar]:
    """Generate bearish klines: price trending down, below SMA200"""
    klines = []
    start = date(2025, 1, 1)
    for i in range(n_days):
        dt = start + timedelta(days=i)
        price = base_price - i * 0.3
        klines.append(_make_kline(symbol, dt, price))
    return klines


def _make_context(
    current_date: date = date(2025, 9, 10),
    prices: dict | None = None,
    vix: float = 15.0,
) -> MarketContext:
    return MarketContext(
        current_date=current_date,
        underlying_prices=prices or {"SPY": 500.0},
        vix_value=vix,
    )


def _make_position(
    symbol: str = "SPY",
    position_id: str = "pos_1",
    quantity: int = 5,
    option_type: str = "call",
    dte: int = 120,
    delta: float = 4.25,  # position-level delta (=0.85 * 5 contracts)
    strike: float = 425.0,
    underlying_price: float = 500.0,
) -> PositionData:
    pd = PositionData(
        position_id=position_id,
        symbol=symbol,
        quantity=quantity,
        option_type=option_type,
        dte=dte,
        delta=delta,
        strike=strike,
        underlying_price=underlying_price,
    )
    return pd


def _make_option_quote(
    underlying: str = "SPY",
    strike: float = 425.0,
    expiry: date = date(2026, 9, 1),
    delta: float = 0.85,
    mid: float = 80.0,
    lot_size: int = 100,
) -> OptionQuote:
    contract = OptionContract(
        symbol=underlying,
        underlying=underlying,
        option_type=OptionType.CALL,
        strike_price=strike,
        expiry_date=expiry,
        lot_size=lot_size,
    )
    greeks = Greeks(delta=delta, gamma=0.002, theta=-0.05, vega=0.30)
    return OptionQuote(
        contract=contract,
        timestamp=datetime.now(),
        bid=mid - 0.5,
        ask=mid + 0.5,
        last_price=mid,
        iv=0.20,
        volume=500,
        open_interest=10000,
        greeks=greeks,
    )


def _make_chain(calls: list[OptionQuote]) -> OptionChain:
    return OptionChain(
        underlying="SPY",
        timestamp=datetime.now(),
        expiry_dates=list({c.contract.expiry_date for c in calls}),
        calls=calls,
        puts=[],
    )


def _make_data_provider(klines=None, chain=None):
    provider = MagicMock()
    provider.get_history_kline.return_value = klines or []
    provider.get_option_chain.return_value = chain
    return provider


def _make_account(nlv: float = 100_000, cash: float = 100_000):
    account = MagicMock()
    account.nlv = nlv
    account.cash = cash
    account.margin_used = 0
    account.available_margin = cash
    account.position_count = 0
    return account


# ==========================================
# Config Tests
# ==========================================

class TestLeapsCallConfig:
    def test_defaults(self):
        cfg = LeapsCallConfig()
        assert cfg.sma_period == 200
        assert cfg.decision_frequency == 5
        assert cfg.target_moneyness == 0.85
        assert cfg.target_dte == 252
        assert cfg.min_dte == 180
        assert cfg.max_dte == 400
        assert cfg.target_leverage == 3.0
        assert cfg.leverage_drift_threshold == 0.5
        assert cfg.max_capital_pct == 0.95
        assert cfg.roll_dte_threshold == 60

    def test_from_yaml(self):
        path = LeapsCallConfig.default_yaml_path()
        if path.exists():
            cfg = LeapsCallConfig.from_yaml(path)
            assert cfg.sma_period == 200
            assert cfg.target_leverage == 3.0
        else:
            pytest.skip("YAML config not found")

    def test_from_yaml_custom(self, tmp_path):
        yaml_content = """
leaps_config:
  sma_period: 100
  target_leverage: 2.5
  roll_dte_threshold: 45
  target_moneyness: 0.80
"""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)
        cfg = LeapsCallConfig.from_yaml(yaml_file)
        assert cfg.sma_period == 100
        assert cfg.target_leverage == 2.5
        assert cfg.roll_dte_threshold == 45
        assert cfg.target_moneyness == 0.80
        # Non-overridden fields keep defaults
        assert cfg.decision_frequency == 5
        assert cfg.min_dte == 180


# ==========================================
# Strategy Properties Tests
# ==========================================

class TestStrategyProperties:
    def test_name(self):
        strategy = LongLeapsCallSmaTiming()
        assert strategy.name == "long_leaps_call_sma_timing"

    def test_position_side(self):
        strategy = LongLeapsCallSmaTiming()
        assert strategy.position_side == "LONG"

    def test_factory_registration(self):
        from src.business.strategy.factory import StrategyFactory
        strategy = StrategyFactory.create("long_leaps_call_sma_timing")
        assert isinstance(strategy, LongLeapsCallSmaTiming)
        assert strategy.position_side == "LONG"


# ==========================================
# SMA Signal Tests
# ==========================================

class TestSmaSignal:
    def test_bullish(self):
        """Price above SMA200 → invested"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context(current_date=date(2025, 9, 10), prices={"SPY": 525.0})

        result = strategy._compute_sma_signal(context, provider)
        assert result is True
        assert strategy._signal_invested is True

    def test_bearish(self):
        """Price below SMA200 → cash"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bearish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context(current_date=date(2025, 9, 10), prices={"SPY": 475.0})

        result = strategy._compute_sma_signal(context, provider)
        assert result is False
        assert strategy._signal_invested is False

    def test_insufficient_data(self):
        """< 200 bars → default to CASH"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bullish(n_days=100)  # not enough
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        result = strategy._compute_sma_signal(context, provider)
        assert result is False

    def test_caching(self):
        """Same date should not re-compute"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        strategy._compute_sma_signal(context, provider)
        assert provider.get_history_kline.call_count == 1

        strategy._compute_sma_signal(context, provider)
        assert provider.get_history_kline.call_count == 1  # cached

    def test_no_symbols(self):
        """No underlying prices → CASH"""
        strategy = LongLeapsCallSmaTiming()
        provider = _make_data_provider()
        context = _make_context(prices={})

        result = strategy._compute_sma_signal(context, provider)
        assert result is False


# ==========================================
# evaluate_positions Tests
# ==========================================

class TestEvaluatePositions:
    def test_sma_exit(self):
        """SMA bearish → close all LEAPS"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bearish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context(prices={"SPY": 475.0})

        positions = [_make_position()]
        signals = strategy.evaluate_positions(positions, context, provider)

        assert len(signals) == 1
        assert signals[0].action.value == "close"
        assert "SMA exit" in signals[0].reason
        assert strategy._pending_exit_to_cash is True

    def test_roll_trigger(self):
        """DTE <= 60 → roll signal"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        positions = [_make_position(dte=55)]
        signals = strategy.evaluate_positions(positions, context, provider)

        assert len(signals) == 1
        assert "Roll trigger" in signals[0].reason
        assert strategy._pending_roll is True

    def test_safety_net_dte5(self):
        """DTE <= 5 → force close even if not caught by roll threshold"""
        strategy = LongLeapsCallSmaTiming()
        strategy._leaps_config = LeapsCallConfig(roll_dte_threshold=3)  # Lower threshold
        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        positions = [_make_position(dte=4)]
        signals = strategy.evaluate_positions(positions, context, provider)

        assert len(signals) >= 1
        assert any("Safety net" in s.reason or "Roll trigger" in s.reason for s in signals)

    def test_no_positions(self):
        """No LEAPS positions → empty signals"""
        strategy = LongLeapsCallSmaTiming()
        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        signals = strategy.evaluate_positions([], context, provider)
        assert len(signals) == 0

    def test_leverage_rebalance_disabled(self):
        """Leverage drift rebalance is currently disabled — no signals emitted"""
        strategy = LongLeapsCallSmaTiming()
        strategy._last_nlv = 100_000
        strategy._trading_day_count = 4  # Next call will be day 5 → decision day (5%5==0)
        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        # Position-level delta = 8.5 means ~8.5*500/100000 = 4.25 leverage (far from 3.0)
        positions = [_make_position(delta=8.5)]
        signals = strategy.evaluate_positions(positions, context, provider)

        assert len(signals) == 0
        assert strategy._pending_rebalance is False


# ==========================================
# find_opportunities Tests
# ==========================================

class TestFindOpportunities:
    def test_entry_on_bullish_no_positions(self):
        """SMA bullish + no positions + decision day → entry opportunity"""
        strategy = LongLeapsCallSmaTiming()
        strategy._trading_day_count = 5  # decision day (5%5==0)
        strategy._last_positions = []  # no positions
        strategy._last_eval_date = date(2025, 9, 10)  # matches context.current_date

        klines = _make_klines_bullish(n_days=250)
        calls = [_make_option_quote(strike=425.0, expiry=date(2026, 9, 1), delta=0.85, mid=80.0)]
        chain = _make_chain(calls)
        provider = _make_data_provider(klines=klines, chain=chain)
        context = _make_context()

        opps = strategy.find_opportunities(["SPY"], provider, context)
        assert len(opps) == 1
        assert opps[0].option_type == "call"
        assert opps[0].strike == 425.0

    def test_cash_mode(self):
        """SMA bearish → no opportunities"""
        strategy = LongLeapsCallSmaTiming()
        strategy._last_positions = []
        strategy._trading_day_count = 5
        strategy._last_eval_date = date(2025, 9, 10)

        klines = _make_klines_bearish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context(prices={"SPY": 475.0})

        opps = strategy.find_opportunities(["SPY"], provider, context)
        assert len(opps) == 0

    def test_after_roll(self):
        """pending_roll → find replacement contract"""
        strategy = LongLeapsCallSmaTiming()
        strategy._pending_roll = True
        strategy._last_positions = []
        strategy._last_eval_date = date(2025, 9, 10)  # evaluate_positions was called (set pending_roll)

        klines = _make_klines_bullish(n_days=250)
        calls = [_make_option_quote(strike=425.0, expiry=date(2026, 9, 1), delta=0.85, mid=80.0)]
        chain = _make_chain(calls)
        provider = _make_data_provider(klines=klines, chain=chain)
        context = _make_context()

        opps = strategy.find_opportunities(["SPY"], provider, context)
        assert len(opps) == 1

    def test_no_chain(self):
        """No option chain available → empty"""
        strategy = LongLeapsCallSmaTiming()
        strategy._pending_roll = True
        strategy._last_positions = []
        strategy._last_eval_date = date(2025, 9, 10)

        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines, chain=None)
        context = _make_context()

        opps = strategy.find_opportunities(["SPY"], provider, context)
        assert len(opps) == 0

    def test_non_decision_day_with_positions(self):
        """Non-decision day with positions → no new entry"""
        strategy = LongLeapsCallSmaTiming()
        strategy._trading_day_count = 3  # not decision day
        strategy._last_positions = [_make_position()]

        klines = _make_klines_bullish(n_days=250)
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        opps = strategy.find_opportunities(["SPY"], provider, context)
        assert len(opps) == 0


# ==========================================
# generate_entry_signals Tests
# ==========================================

class TestGenerateEntrySignals:
    def test_leverage_sizing(self):
        """SPY=$500, delta=0.85, NLV=$100k, 3x → expected contracts"""
        strategy = LongLeapsCallSmaTiming()
        account = _make_account(nlv=100_000, cash=100_000)
        context = _make_context()

        opp = ContractOpportunity(
            symbol="SPY",
            expiry="2026-09-01",
            strike=425.0,
            option_type="call",
            lot_size=100,
            mid_price=80.0,
            bid=79.5,
            ask=80.5,
            delta=0.85,
            gamma=0.002,
            theta=-0.05,
            vega=0.30,
            iv=0.20,
            dte=356,
            underlying_price=500.0,
            annual_roc=0.0,
        )

        signals = strategy.generate_entry_signals([opp], account, context)
        assert len(signals) == 1

        # contracts = floor(3.0 * 100000 / (0.85 * 100 * 500)) = floor(7.06) = 7
        expected_contracts = math.floor(3.0 * 100_000 / (0.85 * 100 * 500))
        assert signals[0].quantity == expected_contracts
        assert signals[0].quantity > 0  # BUY
        assert signals[0].action.value == "open"

    def test_capital_constraint(self):
        """Low cash → contracts limited by max_capital_pct"""
        strategy = LongLeapsCallSmaTiming()
        account = _make_account(nlv=100_000, cash=20_000)  # Only $20k cash
        context = _make_context()

        opp = ContractOpportunity(
            symbol="SPY",
            expiry="2026-09-01",
            strike=425.0,
            option_type="call",
            lot_size=100,
            mid_price=80.0,
            bid=79.5,
            ask=80.5,
            delta=0.85,
            gamma=0.002,
            theta=-0.05,
            vega=0.30,
            iv=0.20,
            dte=356,
            underlying_price=500.0,
            annual_roc=0.0,
        )

        signals = strategy.generate_entry_signals([opp], account, context)
        assert len(signals) == 1

        # Capital constraint: floor(0.95 * 20000 / (80 * 100)) = floor(2.375) = 2
        max_by_cash = math.floor(0.95 * 20_000 / (80.0 * 100))
        assert signals[0].quantity <= max_by_cash

    def test_empty_candidates(self):
        """No candidates → no signals"""
        strategy = LongLeapsCallSmaTiming()
        account = _make_account()
        context = _make_context()
        signals = strategy.generate_entry_signals([], account, context)
        assert len(signals) == 0

    def test_zero_nlv(self):
        """NLV=0 → no signals"""
        strategy = LongLeapsCallSmaTiming()
        account = _make_account(nlv=0, cash=0)
        context = _make_context()

        opp = ContractOpportunity(
            symbol="SPY", expiry="2026-09-01", strike=425.0, option_type="call",
            mid_price=80.0, delta=0.85, dte=356, underlying_price=500.0, annual_roc=0.0,
        )
        signals = strategy.generate_entry_signals([opp], account, context)
        assert len(signals) == 0


# ==========================================
# Contract Selection Tests
# ==========================================

class TestContractSelection:
    def test_select_best(self):
        """Choose contract closest to target strike and DTE"""
        strategy = LongLeapsCallSmaTiming()

        calls = [
            _make_option_quote(strike=400.0, expiry=date(2026, 9, 1), delta=0.90, mid=105.0),
            _make_option_quote(strike=425.0, expiry=date(2026, 9, 1), delta=0.85, mid=80.0),
            _make_option_quote(strike=450.0, expiry=date(2026, 9, 1), delta=0.75, mid=60.0),
        ]

        target_strike = 500.0 * 0.85  # = 425
        best = strategy._select_best_contract(calls, target_strike, 252, date(2025, 9, 10))

        assert best is not None
        # 425 is the exact target strike, should win
        assert best.contract.strike_price == 425.0

    def test_filter_low_delta(self):
        """Contracts with delta <= 0 are filtered out"""
        strategy = LongLeapsCallSmaTiming()

        calls = [
            _make_option_quote(strike=550.0, expiry=date(2026, 9, 1), delta=0.0, mid=5.0),
            _make_option_quote(strike=425.0, expiry=date(2026, 9, 1), delta=0.85, mid=80.0),
        ]

        best = strategy._select_best_contract(calls, 425.0, 252, date(2025, 9, 10))
        assert best is not None
        assert best.contract.strike_price == 425.0

    def test_filter_dte_range(self):
        """Contracts outside min_dte/max_dte are filtered"""
        strategy = LongLeapsCallSmaTiming()

        calls = [
            _make_option_quote(strike=425.0, expiry=date(2025, 11, 1), delta=0.85, mid=30.0),  # DTE ~52 (< 180)
            _make_option_quote(strike=425.0, expiry=date(2026, 9, 1), delta=0.85, mid=80.0),    # DTE ~356
        ]

        best = strategy._select_best_contract(calls, 425.0, 252, date(2025, 9, 10))
        assert best is not None
        assert best.contract.expiry_date == date(2026, 9, 1)


# ==========================================
# Decision Frequency Tests
# ==========================================

class TestDecisionFrequency:
    def test_decision_day(self):
        strategy = LongLeapsCallSmaTiming()
        strategy._trading_day_count = 10
        assert strategy._is_decision_day() is True  # 10 % 5 == 0

    def test_non_decision_day(self):
        strategy = LongLeapsCallSmaTiming()
        strategy._trading_day_count = 7
        assert strategy._is_decision_day() is False  # 7 % 5 != 0
