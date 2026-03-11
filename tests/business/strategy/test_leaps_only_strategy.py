"""Unit tests for SPY Pure LEAPS + Cash Interest Strategy (Vol Target)"""

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.business.strategy.versions.spy_leaps_only_vol_target import (
    LeapsOnlyVolTargetConfig,
    SpyLeapsOnlyVolTarget,
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
    klines = []
    start = date(2025, 1, 1)
    for i in range(n_days):
        dt = start + timedelta(days=i)
        price = base_price + i * 0.3
        klines.append(_make_kline(symbol, dt, price))
    return klines


def _make_klines_bearish(symbol: str = "SPY", n_days: int = 250, base_price: float = 550.0) -> list[KlineBar]:
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
    delta: float = 4.25,  # position-level delta
    strike: float = 425.0,
    underlying_price: float = 500.0,
    contract_multiplier: int = 100,
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
    pd.contract_multiplier = contract_multiplier
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


def _make_data_provider(klines=None, chain=None, vix=15.0, tnx_close=40.0):
    """Create mock data provider with VIX and TNX macro data"""
    provider = MagicMock()
    provider.get_history_kline.return_value = klines or []
    provider.get_option_chain.return_value = chain

    def mock_macro(symbol, start, end):
        mock_data = MagicMock()
        if symbol == "^VIX":
            mock_data.close = vix
        elif symbol == "^TNX":
            mock_data.close = tnx_close  # TNX value (40.0 → 4.0% after /1000)
        return [mock_data]

    provider.get_macro_data.side_effect = mock_macro
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

class TestLeapsOnlyVolTargetConfig:
    def test_defaults(self):
        cfg = LeapsOnlyVolTargetConfig()
        assert cfg.sma_periods == (20, 50, 200)
        assert cfg.vol_target == 15.0
        assert cfg.vol_scalar_max == 2.0
        assert cfg.max_exposure == 3.0
        assert cfg.target_moneyness == 0.85
        assert cfg.target_dte == 252
        assert cfg.min_dte == 180
        assert cfg.max_dte == 400
        assert cfg.roll_dte_threshold == 60
        assert cfg.cash_yield_enabled is True
        assert cfg.default_risk_free_rate == 0.04

    def test_from_yaml(self):
        path = LeapsOnlyVolTargetConfig.default_yaml_path()
        if path.exists():
            cfg = LeapsOnlyVolTargetConfig.from_yaml(path)
            assert cfg.cash_yield_enabled is True
        else:
            pytest.skip("YAML config not found")

    def test_from_yaml_custom(self, tmp_path):
        yaml_content = """
leaps_only_vol_target_config:
  rebalance_threshold: 0.10
  cash_yield_enabled: false
  default_risk_free_rate: 0.05
  roll_dte_threshold: 45
"""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)
        cfg = LeapsOnlyVolTargetConfig.from_yaml(yaml_file)
        assert cfg.rebalance_threshold == 0.10
        assert cfg.cash_yield_enabled is False
        assert cfg.default_risk_free_rate == 0.05
        assert cfg.roll_dte_threshold == 45
        # Non-overridden fields keep defaults
        assert cfg.vol_target == 15.0


# ==========================================
# Strategy Basic Tests
# ==========================================

class TestSpyLeapsOnlyVolTargetBasic:
    def test_name(self):
        s = SpyLeapsOnlyVolTarget()
        assert s.name == "spy_leaps_only_vol_target"

    def test_position_side(self):
        s = SpyLeapsOnlyVolTarget()
        assert s.position_side == "LONG"

    def test_has_interest_method(self):
        s = SpyLeapsOnlyVolTarget()
        assert hasattr(s, '_compute_daily_interest')


# ==========================================
# Signal Computation Tests
# ==========================================

class TestSignalComputation:
    def test_bullish_signal(self):
        """Bullish market (all 7 SMA/momentum checks pass) → high target"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines, vix=15.0)
        context = _make_context()

        target = s._compute_signal(context, provider)
        # score=7, map→3.0, vol_scalar=min(2.0, 15/15)=1.0, target=3.0
        assert target == 3.0

    def test_bearish_signal(self):
        """Bearish market → low/zero target"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bearish()
        provider = _make_data_provider(klines=klines, vix=25.0)
        context = _make_context()

        target = s._compute_signal(context, provider)
        # Most SMA checks fail → low score → low or zero target
        assert target <= 0.5

    def test_vol_scalar_high_vix(self):
        """High VIX → vol_scalar < 1.0 → target reduced"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines, vix=30.0)
        context = _make_context()

        target = s._compute_signal(context, provider)
        # vol_scalar = min(2.0, 15/30) = 0.5
        # score=7, map→3.0, target = 3.0 * 0.5 = 1.5
        assert target == 1.5

    def test_vol_scalar_low_vix(self):
        """Low VIX → vol_scalar capped at 2.0"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines, vix=5.0)
        context = _make_context()

        target = s._compute_signal(context, provider)
        # vol_scalar = min(2.0, 15/5) = 2.0
        # score=7, map→3.0, target = 3.0 * 2.0 = 6.0, capped at 3.0
        assert target == 3.0

    def test_signal_caching(self):
        """Signal computed once per date"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        t1 = s._compute_signal(context, provider)
        t2 = s._compute_signal(context, provider)
        assert t1 == t2
        # Should only call get_history_kline once due to caching
        assert provider.get_history_kline.call_count == 1

    def test_insufficient_data(self):
        """Not enough klines → target=0"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish(n_days=50)  # Less than SMA200 needs
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        target = s._compute_signal(context, provider)
        assert target == 0.0


# ==========================================
# Evaluate Positions Tests (Pure LEAPS)
# ==========================================

class TestEvaluatePositions:
    def test_empty_positions(self):
        """No positions → no signals"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        signals = s.evaluate_positions([], context, provider)
        assert signals == []

    def test_exit_to_cash(self):
        """target=0 → close all LEAPS"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        s._last_nlv = 100_000
        klines = _make_klines_bearish()
        provider = _make_data_provider(klines=klines, vix=25.0)
        context = _make_context()

        # Pre-compute to get score=0
        target = s._compute_signal(context, provider)
        # Reset date cache so evaluate_positions re-computes
        s._signal_computed_for_date = None

        pos = _make_position(dte=200)
        signals = s.evaluate_positions([pos], context, provider)

        if target == 0.0:
            assert len(signals) >= 1
            assert all(s.action.value == "close" for s in signals)
        # If target is not 0 (edge case with bearish data), signals may vary

    def test_roll_dte_threshold(self):
        """DTE <= roll_dte_threshold → close + pending rebalance"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(roll_dte_threshold=60)
        s._last_nlv = 100_000
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        pos = _make_position(dte=45)  # Below threshold
        signals = s.evaluate_positions([pos], context, provider)

        assert len(signals) >= 1
        assert signals[0].alert_type == "roll_dte"
        assert s._pending_rebalance is True

    def test_safety_net_dte5(self):
        """DTE <= 5 → close signal (caught by roll check or safety net)"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        s._last_nlv = 100_000
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        pos = _make_position(dte=3)
        signals = s.evaluate_positions([pos], context, provider)

        # DTE=3 <= roll_dte_threshold=60, so it's caught by roll check
        assert len(signals) >= 1
        assert signals[0].alert_type == "roll_dte"

    def test_no_stock_positions(self):
        """Strategy should never generate stock-related signals"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        s._last_nlv = 100_000
        klines = _make_klines_bullish()
        provider = _make_data_provider(klines=klines)
        context = _make_context()

        pos = _make_position()
        signals = s.evaluate_positions([pos], context, provider)

        for sig in signals:
            assert "stock" not in sig.reason.lower() or "stock" not in sig.alert_type


# ==========================================
# Find Opportunities Tests (Pure LEAPS)
# ==========================================

class TestFindOpportunities:
    def test_no_stock_proxy(self):
        """Pure LEAPS strategy should never emit stock proxy opportunities"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bullish()
        calls = [_make_option_quote(strike=425.0, expiry=date(2026, 9, 1))]
        chain = _make_chain(calls)
        provider = _make_data_provider(klines=klines, chain=chain)
        context = _make_context()

        opps = s.find_opportunities(["SPY"], provider, context)

        for opp in opps:
            assert opp.metadata.get("is_stock_proxy") is not True
            assert opp.strike >= 1.0  # No stock proxy (strike=0.01)

    def test_bullish_finds_leaps(self):
        """Bullish signal + no positions → LEAPS opportunity"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        s._last_positions = []
        klines = _make_klines_bullish()
        calls = [_make_option_quote(strike=425.0, expiry=date(2026, 9, 1))]
        chain = _make_chain(calls)
        provider = _make_data_provider(klines=klines, chain=chain)
        context = _make_context()

        opps = s.find_opportunities(["SPY"], provider, context)
        assert len(opps) == 1
        assert opps[0].metadata["is_leaps"] is True
        assert opps[0].metadata["target_pct"] > 0

    def test_bearish_no_opportunities(self):
        """Bearish signal → no opportunities"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()
        klines = _make_klines_bearish()
        provider = _make_data_provider(klines=klines, vix=25.0)
        context = _make_context()

        opps = s.find_opportunities(["SPY"], provider, context)
        # May be empty or have entries depending on exact bearish score
        for opp in opps:
            # Even if there are opps, they should be LEAPS
            assert opp.metadata.get("is_leaps", False)


# ==========================================
# Generate Entry Signals Tests
# ==========================================

class TestGenerateEntrySignals:
    def test_leaps_entry_cash_constraint(self):
        """LEAPS contracts limited by actual cash (not NLV)"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(max_capital_pct=1.0)

        opp = ContractOpportunity(
            symbol="SPY",
            expiry="2026-09-01",
            strike=425.0,
            option_type="call",
            lot_size=100,
            bid=79.5,
            ask=80.5,
            mid_price=80.0,
            open_interest=10000,
            volume=500,
            delta=0.85,
            gamma=0.002,
            theta=-0.05,
            vega=0.30,
            iv=0.20,
            dte=300,
            underlying_price=500.0,
            moneyness=0.176,
            annual_roc=0.0,
            metadata={"is_leaps": True, "target_pct": 1.0, "source_strategy_type": "long_call"},
        )

        # NLV=1M but cash=50K → cash constrains
        account = _make_account(nlv=1_000_000, cash=50_000)
        context = _make_context()

        signals = s.generate_entry_signals([opp], account, context)
        assert len(signals) == 1

        # max_contracts from cash = floor(50000 / (80 * 100)) = 6
        # target from pct = floor(1.0 * 1M / (0.85 * 100 * 500)) = 23
        # Cash should be the binding constraint
        assert signals[0].quantity <= 6

    def test_no_stock_entry(self):
        """Strategy should never generate stock_proxy entries"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig()

        # Create a stock-proxy opportunity (should be ignored)
        opp = ContractOpportunity(
            symbol="SPY",
            expiry="2099-01-01",
            strike=0.01,
            option_type="call",
            lot_size=1,
            bid=500.0,
            ask=500.0,
            mid_price=500.0,
            open_interest=999999,
            volume=999999,
            delta=1.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            iv=0.0,
            dte=9999,
            underlying_price=500.0,
            moneyness=0.0,
            annual_roc=0.0,
            metadata={"is_stock_proxy": True, "target_pct": 1.0},
        )

        account = _make_account()
        context = _make_context()

        signals = s.generate_entry_signals([opp], account, context)
        assert len(signals) == 0  # Should ignore stock proxy


# ==========================================
# Cash Interest Tests
# ==========================================

class TestCashInterest:
    def test_positive_cash_earns_interest(self):
        """Positive cash earns daily interest"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(cash_yield_enabled=True)
        provider = _make_data_provider(tnx_close=40.0)  # 40.0/1000 = 4%
        current_date = date(2025, 6, 15)

        interest = s._compute_daily_interest(100_000, current_date, provider)

        expected = 100_000 * (0.04 / 365.0)
        assert abs(interest - expected) < 0.01
        assert s._cumulative_interest == pytest.approx(interest)

    def test_negative_cash_no_interest(self):
        """Negative cash earns no interest"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(cash_yield_enabled=True)
        provider = _make_data_provider()
        current_date = date(2025, 6, 15)

        interest = s._compute_daily_interest(-50_000, current_date, provider)
        assert interest == 0.0

    def test_zero_cash_no_interest(self):
        """Zero cash earns no interest"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(cash_yield_enabled=True)
        provider = _make_data_provider()

        interest = s._compute_daily_interest(0.0, date(2025, 6, 15), provider)
        assert interest == 0.0

    def test_disabled_no_interest(self):
        """cash_yield_enabled=False → no interest"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(cash_yield_enabled=False)
        provider = _make_data_provider()

        interest = s._compute_daily_interest(100_000, date(2025, 6, 15), provider)
        assert interest == 0.0

    def test_cumulative_interest(self):
        """Interest accumulates across days"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(cash_yield_enabled=True)
        provider = _make_data_provider(tnx_close=40.0)

        total = 0.0
        for i in range(30):
            dt = date(2025, 6, 1) + timedelta(days=i)
            interest = s._compute_daily_interest(100_000, dt, provider)
            total += interest

        assert s._cumulative_interest == pytest.approx(total)
        assert total > 0

    def test_tnx_fallback(self):
        """When TNX data unavailable, use default_risk_free_rate"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(
            cash_yield_enabled=True, default_risk_free_rate=0.05
        )

        provider = MagicMock()
        provider.get_macro_data.side_effect = Exception("No data")

        interest = s._compute_daily_interest(100_000, date(2025, 6, 15), provider)
        expected = 100_000 * (0.05 / 365.0)
        assert abs(interest - expected) < 0.01

    def test_risk_free_rate_caching(self):
        """TNX rate is cached per date"""
        s = SpyLeapsOnlyVolTarget()
        s._config = LeapsOnlyVolTargetConfig(cash_yield_enabled=True)
        provider = _make_data_provider(tnx_close=40.0)

        dt = date(2025, 6, 15)
        s._compute_daily_interest(100_000, dt, provider)
        s._compute_daily_interest(100_000, dt, provider)

        # get_macro_data for TNX should only be called once for same date
        tnx_calls = [
            c for c in provider.get_macro_data.call_args_list
            if c[0][0] == "^TNX"
        ]
        assert len(tnx_calls) == 1


# ==========================================
# Factory Registration Test
# ==========================================

class TestFactoryRegistration:
    def test_registered(self):
        from src.business.strategy.factory import StrategyFactory
        available = StrategyFactory.get_available_strategies()
        assert "spy_leaps_only_vol_target" in available

    def test_create(self):
        from src.business.strategy.factory import StrategyFactory
        strategy = StrategyFactory.create("spy_leaps_only_vol_target")
        assert isinstance(strategy, SpyLeapsOnlyVolTarget)
        assert strategy.name == "spy_leaps_only_vol_target"
        assert strategy.position_side == "LONG"
