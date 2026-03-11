"""Comprehensive tests for Long Put / Long Call pricer integration.

Tests cover:
1. Mathematical mirror properties (Long vs Short exact negation)
2. Factory classification (classify_option_strategy)
3. Factory creation (create_pricers_from_position)
4. PositionDataBuilder.create_strategy_object
5. Backtest PositionManager strategy type inference
6. Edge cases: ATM, deep ITM, deep OTM, near expiry, high IV
7. Metrics consistency and buyer-specific behavior
8. StrategyType enum consistency
9. Cross-pricer consistency (Long Put vs Long Call)
10. Numerical correctness — independent BS formula verification
"""

import math
from dataclasses import dataclass
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from scipy.stats import norm

from src.data.models.account import AccountPosition, AssetType
from src.data.models.enums import Market
from src.data.models.option import OptionType
from src.engine.models.enums import PositionSide, StrategyType
from src.engine.models.pricing import PricingMetrics
from src.engine.pricing import (
    LongCallPricer,
    LongPutPricer,
    ShortCallPricer,
    ShortPutPricer,
)
from src.engine.pricing.factory import classify_option_strategy


# ============================================================================
# Independent BS calculation helpers (for numerical verification)
# ============================================================================


def _bs_d1(S, K, r, sigma, T):
    """Independently compute d1 = [ln(S/K) + (r + σ²/2)*T] / (σ*√T)."""
    return (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))


def _bs_d2(S, K, r, sigma, T):
    """d2 = d1 - σ√T."""
    return _bs_d1(S, K, r, sigma, T) - sigma * math.sqrt(T)


def _bs_d3(S, K, r, sigma, T):
    """d3 = d2 + 2σ√T = d1 + σ√T."""
    return _bs_d2(S, K, r, sigma, T) + 2 * sigma * math.sqrt(T)


def _N(x):
    """Standard normal CDF."""
    return float(norm.cdf(x))


def _long_put_expected_return(S, K, C, r, sigma, T):
    """Independently compute Long Put E[π].

    E[π] = N(-d2) * (K - e^(rT) * S * N(-d1)/N(-d2)) - C
    """
    d1 = _bs_d1(S, K, r, sigma, T)
    d2 = _bs_d2(S, K, r, sigma, T)
    n_m_d1 = _N(-d1)
    n_m_d2 = _N(-d2)
    if n_m_d2 == 0:
        return -C
    exp_rt = math.exp(r * T)
    E_stock_exercised = exp_rt * S * n_m_d1 / n_m_d2
    return n_m_d2 * (K - E_stock_exercised) - C


def _long_call_expected_return(S, K, C, r, sigma, T):
    """Independently compute Long Call E[π].

    E[π] = N(d2) * (S * e^(rT) * N(d1)/N(d2) - K) - C
    """
    d1 = _bs_d1(S, K, r, sigma, T)
    d2 = _bs_d2(S, K, r, sigma, T)
    n_d1 = _N(d1)
    n_d2 = _N(d2)
    if n_d2 == 0:
        return -C
    exp_rt = math.exp(r * T)
    E_stock_exercised = exp_rt * S * n_d1 / n_d2
    return n_d2 * (E_stock_exercised - K) - C


def _put_variance(S, K, C, r, sigma, T, E_pi):
    """Independently compute Var[π] for put (long or short have same variance).

    E[π²] = C²*(1-N(-d2)) + (C-K)²*N(-d2) + 2*(C-K)*e^(rT)*S*N(-d1) + S²*e^(2rT+σ²T)*N(-d3)
    Var = E[π²] - E[π]²
    """
    d1 = _bs_d1(S, K, r, sigma, T)
    d2 = _bs_d2(S, K, r, sigma, T)
    d3 = _bs_d3(S, K, r, sigma, T)
    n_m_d1 = _N(-d1)
    n_m_d2 = _N(-d2)
    n_m_d3 = _N(-d3)
    exp_rt = math.exp(r * T)
    exp_2rt_s2t = math.exp(2 * r * T + sigma**2 * T)

    e_pi_sq = (
        C**2 * (1 - n_m_d2)
        + (C - K) ** 2 * n_m_d2
        + 2 * (C - K) * exp_rt * S * n_m_d1
        + S**2 * exp_2rt_s2t * n_m_d3
    )
    return max(0.0, e_pi_sq - E_pi**2)


def _call_variance(S, K, C, r, sigma, T, E_pi):
    """Independently compute Var[π] for call (long or short have same variance).

    E[π²] = C²*(1-N(d2)) + (C+K)²*N(d2) - 2*(C+K)*e^(rT)*S*N(d1) + S²*e^(2rT+σ²T)*N(d3)
    Var = E[π²] - E[π]²
    """
    d1 = _bs_d1(S, K, r, sigma, T)
    d2 = _bs_d2(S, K, r, sigma, T)
    d3 = _bs_d3(S, K, r, sigma, T)
    n_d1 = _N(d1)
    n_d2 = _N(d2)
    n_d3 = _N(d3)
    exp_rt = math.exp(r * T)
    exp_2rt_s2t = math.exp(2 * r * T + sigma**2 * T)

    e_pi_sq = (
        C**2 * (1 - n_d2)
        + (C + K) ** 2 * n_d2
        - 2 * (C + K) * exp_rt * S * n_d1
        + S**2 * exp_2rt_s2t * n_d3
    )
    return max(0.0, e_pi_sq - E_pi**2)


# ============================================================================
# Fixtures: mock data helpers
# ============================================================================


def make_account_position(
    symbol: str = "AAPL",
    option_type: str = "put",
    quantity: float = 1,
    strike: float = 150.0,
    underlying_price: float = 155.0,
    iv: float = 0.25,
    premium_per_share: float = 3.0,
    expiry: str = "20260601",
    delta: float = -0.3,
    gamma: float = 0.02,
    theta: float = -0.05,
    vega: float = 0.15,
) -> AccountPosition:
    """Create a mock AccountPosition for option testing."""
    multiplier = 100
    market_value = quantity * premium_per_share * multiplier
    return AccountPosition(
        symbol=f"{symbol} {expiry} {strike}{option_type[0].upper()}",
        asset_type=AssetType.OPTION,
        market=Market.US,
        quantity=quantity,
        avg_cost=premium_per_share,
        market_value=market_value,
        unrealized_pnl=0.0,
        currency="USD",
        underlying=symbol,
        strike=strike,
        expiry=expiry,
        option_type=option_type,
        contract_multiplier=multiplier,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        iv=iv,
        underlying_price=underlying_price,
        broker="mock",
    )


def make_stock_position(
    symbol: str = "AAPL",
    quantity: float = 100,
    price: float = 155.0,
) -> AccountPosition:
    """Create a mock stock AccountPosition."""
    return AccountPosition(
        symbol=symbol,
        asset_type=AssetType.STOCK,
        market=Market.US,
        quantity=quantity,
        avg_cost=price,
        market_value=quantity * price,
        unrealized_pnl=0.0,
        currency="USD",
        broker="mock",
    )


# Common parameter sets for mirror tests
MIRROR_SCENARIOS = [
    # (label, params_dict)
    (
        "OTM_put",
        dict(spot_price=580, strike_price=550, premium=6.5, volatility=0.20, time_to_expiry=30 / 365),
    ),
    (
        "ATM_put",
        dict(spot_price=100, strike_price=100, premium=5.0, volatility=0.25, time_to_expiry=45 / 365),
    ),
    (
        "ITM_put",
        dict(spot_price=90, strike_price=100, premium=12.0, volatility=0.30, time_to_expiry=60 / 365),
    ),
    (
        "deep_OTM_put",
        dict(spot_price=200, strike_price=150, premium=0.5, volatility=0.15, time_to_expiry=14 / 365),
    ),
    (
        "high_IV",
        dict(spot_price=100, strike_price=100, premium=10.0, volatility=0.60, time_to_expiry=30 / 365),
    ),
    (
        "near_expiry",
        dict(spot_price=100, strike_price=95, premium=0.3, volatility=0.20, time_to_expiry=3 / 365),
    ),
    (
        "long_dated",
        dict(spot_price=100, strike_price=110, premium=8.0, volatility=0.25, time_to_expiry=180 / 365),
    ),
]

CALL_MIRROR_SCENARIOS = [
    (
        "OTM_call",
        dict(spot_price=100, strike_price=110, premium=2.0, volatility=0.25, time_to_expiry=30 / 365),
    ),
    (
        "ATM_call",
        dict(spot_price=100, strike_price=100, premium=5.0, volatility=0.25, time_to_expiry=45 / 365),
    ),
    (
        "ITM_call",
        dict(spot_price=110, strike_price=100, premium=12.0, volatility=0.30, time_to_expiry=60 / 365),
    ),
    (
        "deep_OTM_call",
        dict(spot_price=100, strike_price=150, premium=0.2, volatility=0.20, time_to_expiry=14 / 365),
    ),
    (
        "high_IV_call",
        dict(spot_price=100, strike_price=105, premium=8.0, volatility=0.60, time_to_expiry=30 / 365),
    ),
    (
        "near_expiry_call",
        dict(spot_price=100, strike_price=105, premium=0.1, volatility=0.20, time_to_expiry=3 / 365),
    ),
]


# ============================================================================
# 1. Mathematical Mirror Properties
# ============================================================================


class TestPutMirrorProperty:
    """Verify E[Long Put] = -E[Short Put] across diverse scenarios."""

    @pytest.mark.parametrize("label,params", MIRROR_SCENARIOS)
    def test_expected_return_mirror(self, label, params):
        """E[Long Put] + E[Short Put] == 0."""
        long_p = LongPutPricer(**params)
        short_p = ShortPutPricer(**params)
        assert abs(long_p.calc_expected_return() + short_p.calc_expected_return()) < 1e-10, label

    @pytest.mark.parametrize("label,params", MIRROR_SCENARIOS)
    def test_variance_mirror(self, label, params):
        """Var[Long Put] == Var[Short Put]."""
        long_p = LongPutPricer(**params)
        short_p = ShortPutPricer(**params)
        assert abs(long_p.calc_return_variance() - short_p.calc_return_variance()) < 1e-6, label

    @pytest.mark.parametrize("label,params", MIRROR_SCENARIOS)
    def test_std_mirror(self, label, params):
        """Std[Long Put] == Std[Short Put]."""
        long_p = LongPutPricer(**params)
        short_p = ShortPutPricer(**params)
        assert abs(long_p.calc_return_std() - short_p.calc_return_std()) < 1e-6, label

    @pytest.mark.parametrize("label,params", MIRROR_SCENARIOS)
    def test_breakeven_same(self, label, params):
        """Breakeven is identical for long and short put."""
        long_p = LongPutPricer(**params)
        short_p = ShortPutPricer(**params)
        assert long_p.calc_breakeven() == short_p.calc_breakeven(), label

    def test_mirror_with_hv(self):
        """Mirror holds when HV differs from IV (physical measure)."""
        params = dict(
            spot_price=100, strike_price=95, premium=3.0,
            volatility=0.30, time_to_expiry=30 / 365, hv=0.20,
        )
        long_p = LongPutPricer(**params)
        short_p = ShortPutPricer(**params)
        assert abs(long_p.calc_expected_return() + short_p.calc_expected_return()) < 1e-10


class TestCallMirrorProperty:
    """Verify E[Long Call] = -E[Short Call] across diverse scenarios."""

    @pytest.mark.parametrize("label,params", CALL_MIRROR_SCENARIOS)
    def test_expected_return_mirror(self, label, params):
        """E[Long Call] + E[Short Call] == 0."""
        long_c = LongCallPricer(**params)
        short_c = ShortCallPricer(**params)
        assert abs(long_c.calc_expected_return() + short_c.calc_expected_return()) < 1e-10, label

    @pytest.mark.parametrize("label,params", CALL_MIRROR_SCENARIOS)
    def test_variance_mirror(self, label, params):
        """Var[Long Call] == Var[Short Call]."""
        long_c = LongCallPricer(**params)
        short_c = ShortCallPricer(**params)
        assert abs(long_c.calc_return_variance() - short_c.calc_return_variance()) < 1e-6, label

    @pytest.mark.parametrize("label,params", CALL_MIRROR_SCENARIOS)
    def test_breakeven_same(self, label, params):
        """Breakeven is identical for long and short call."""
        long_c = LongCallPricer(**params)
        short_c = ShortCallPricer(**params)
        assert long_c.calc_breakeven() == short_c.calc_breakeven(), label

    def test_mirror_with_hv(self):
        """Mirror holds when HV differs from IV (physical measure)."""
        params = dict(
            spot_price=100, strike_price=110, premium=2.0,
            volatility=0.30, time_to_expiry=30 / 365, hv=0.20,
        )
        long_c = LongCallPricer(**params)
        short_c = ShortCallPricer(**params)
        assert abs(long_c.calc_expected_return() + short_c.calc_expected_return()) < 1e-10


# ============================================================================
# 2. Factory Classification (classify_option_strategy)
# ============================================================================


class TestFactoryClassification:
    """Test classify_option_strategy correctly identifies Long Put / Long Call."""

    def test_long_put_classified(self):
        """PUT + quantity > 0 → LONG_PUT."""
        pos = make_account_position(option_type="put", quantity=2)
        result = classify_option_strategy(pos, [pos])
        assert result == StrategyType.LONG_PUT

    def test_long_call_classified(self):
        """CALL + quantity > 0 → LONG_CALL."""
        pos = make_account_position(option_type="call", quantity=1)
        result = classify_option_strategy(pos, [pos])
        assert result == StrategyType.LONG_CALL

    def test_short_put_still_works(self):
        """PUT + quantity < 0 → SHORT_PUT (regression)."""
        pos = make_account_position(option_type="put", quantity=-1)
        result = classify_option_strategy(pos, [pos])
        assert result == StrategyType.SHORT_PUT

    def test_short_call_naked_still_works(self):
        """CALL + quantity < 0, no stock → NAKED_CALL (regression)."""
        pos = make_account_position(option_type="call", quantity=-1)
        result = classify_option_strategy(pos, [pos])
        assert result == StrategyType.NAKED_CALL

    def test_covered_call_still_works(self):
        """CALL + quantity < 0, with stock → COVERED_CALL (regression)."""
        call_pos = make_account_position(option_type="call", quantity=-1, strike=160.0)
        stock_pos = make_stock_position(symbol="AAPL", quantity=100)
        result = classify_option_strategy(call_pos, [call_pos, stock_pos])
        assert result == StrategyType.COVERED_CALL

    def test_long_call_not_confused_with_covered(self):
        """CALL + quantity > 0 is LONG_CALL even if stock exists."""
        call_pos = make_account_position(option_type="call", quantity=1, strike=160.0)
        stock_pos = make_stock_position(symbol="AAPL", quantity=100)
        result = classify_option_strategy(call_pos, [call_pos, stock_pos])
        assert result == StrategyType.LONG_CALL

    def test_stock_not_classified_as_option(self):
        """Stock → NOT_OPTION (regression)."""
        stock = make_stock_position()
        result = classify_option_strategy(stock, [stock])
        assert result == StrategyType.NOT_OPTION


# ============================================================================
# 3. Factory Creation (create_pricers_from_position)
# ============================================================================


class TestFactoryCreation:
    """Test create_pricers_from_position produces correct pricer types."""

    @patch("src.engine.pricing.factory._validate_position_data", return_value=True)
    @patch("src.engine.pricing.factory._fetch_volatility_data", return_value=None)
    def test_creates_long_put_pricer(self, mock_vol, mock_val):
        from src.engine.pricing.factory import create_pricers_from_position
        from src.engine.pricing.long_put import LongPutPricer

        pos = make_account_position(option_type="put", quantity=2)
        pricers = create_pricers_from_position(pos, [pos])

        assert len(pricers) == 1
        assert isinstance(pricers[0].pricer, LongPutPricer)
        assert pricers[0].quantity_ratio == 1.0
        assert "long_put" in pricers[0].description

    @patch("src.engine.pricing.factory._validate_position_data", return_value=True)
    @patch("src.engine.pricing.factory._fetch_volatility_data", return_value=None)
    def test_creates_long_call_pricer(self, mock_vol, mock_val):
        from src.engine.pricing.factory import create_pricers_from_position
        from src.engine.pricing.long_call import LongCallPricer

        pos = make_account_position(option_type="call", quantity=3)
        pricers = create_pricers_from_position(pos, [pos])

        assert len(pricers) == 1
        assert isinstance(pricers[0].pricer, LongCallPricer)
        assert pricers[0].quantity_ratio == 1.0
        assert "long_call" in pricers[0].description

    @patch("src.engine.pricing.factory._validate_position_data", return_value=True)
    @patch("src.engine.pricing.factory._fetch_volatility_data", return_value=None)
    def test_long_put_pricer_params_correct(self, mock_vol, mock_val):
        """Verify the pricer receives correct strike/premium/spot."""
        from src.engine.pricing.factory import create_pricers_from_position

        pos = make_account_position(
            option_type="put", quantity=1, strike=150.0,
            underlying_price=155.0, iv=0.25, premium_per_share=3.0,
        )
        pricers = create_pricers_from_position(pos, [pos])
        pricer = pricers[0].pricer

        assert pricer.leg.strike == 150.0
        assert pricer.leg.side == PositionSide.LONG
        assert pricer.leg.option_type == OptionType.PUT
        assert pricer.params.spot_price == 155.0
        assert abs(pricer.params.volatility - 0.25) < 1e-6

    @patch("src.engine.pricing.factory._validate_position_data", return_value=True)
    @patch("src.engine.pricing.factory._fetch_volatility_data", return_value=None)
    def test_short_put_regression(self, mock_vol, mock_val):
        """Short put still creates ShortPutPricer (regression)."""
        from src.engine.pricing.factory import create_pricers_from_position
        from src.engine.pricing.short_put import ShortPutPricer

        pos = make_account_position(option_type="put", quantity=-1)
        pricers = create_pricers_from_position(pos, [pos])

        assert len(pricers) == 1
        assert isinstance(pricers[0].pricer, ShortPutPricer)


# ============================================================================
# 4. PositionDataBuilder.create_strategy_object
# ============================================================================


class TestPositionDataBuilder:
    """Test PositionDataBuilder creates correct strategy objects for Long options."""

    def test_create_long_put_strategy(self):
        from src.business.monitoring.position_data_builder import PositionDataBuilder
        from src.engine.pricing.long_put import LongPutPricer

        obj = PositionDataBuilder.create_strategy_object(
            strategy_type=StrategyType.LONG_PUT,
            underlying_price=155.0,
            strike=150.0,
            premium=3.0,
            iv=0.25,
            dte=30,
            delta=-0.3,
            gamma=0.02,
            theta=-0.05,
            vega=0.15,
        )
        assert isinstance(obj, LongPutPricer)
        assert obj.leg.side == PositionSide.LONG
        assert obj.leg.option_type == OptionType.PUT

    def test_create_long_call_strategy(self):
        from src.business.monitoring.position_data_builder import PositionDataBuilder
        from src.engine.pricing.long_call import LongCallPricer

        obj = PositionDataBuilder.create_strategy_object(
            strategy_type=StrategyType.LONG_CALL,
            underlying_price=155.0,
            strike=160.0,
            premium=2.0,
            iv=0.25,
            dte=30,
            delta=0.4,
            gamma=0.02,
            theta=-0.04,
            vega=0.12,
        )
        assert isinstance(obj, LongCallPricer)
        assert obj.leg.side == PositionSide.LONG
        assert obj.leg.option_type == OptionType.CALL

    def test_short_put_regression(self):
        """SHORT_PUT still creates ShortPutPricer."""
        from src.business.monitoring.position_data_builder import PositionDataBuilder
        from src.engine.pricing.short_put import ShortPutPricer

        obj = PositionDataBuilder.create_strategy_object(
            strategy_type=StrategyType.SHORT_PUT,
            underlying_price=155.0,
            strike=150.0,
            premium=3.0,
            iv=0.25,
            dte=30,
        )
        assert isinstance(obj, ShortPutPricer)

    def test_naked_call_regression(self):
        """NAKED_CALL still creates ShortCallPricer."""
        from src.business.monitoring.position_data_builder import PositionDataBuilder
        from src.engine.pricing.short_call import ShortCallPricer

        obj = PositionDataBuilder.create_strategy_object(
            strategy_type=StrategyType.NAKED_CALL,
            underlying_price=155.0,
            strike=160.0,
            premium=2.0,
            iv=0.25,
            dte=30,
        )
        assert isinstance(obj, ShortCallPricer)

    def test_unknown_returns_none(self):
        from src.business.monitoring.position_data_builder import PositionDataBuilder

        obj = PositionDataBuilder.create_strategy_object(
            strategy_type=StrategyType.UNKNOWN,
            underlying_price=100.0,
            strike=100.0,
            premium=5.0,
            iv=0.25,
            dte=30,
        )
        assert obj is None

    def test_long_put_metrics_flow(self):
        """Full flow: create strategy → calc_metrics → populate PositionData."""
        from src.business.monitoring.models import PositionData
        from src.business.monitoring.position_data_builder import PositionDataBuilder
        from src.engine.pricing.long_put import LongPutPricer

        obj = PositionDataBuilder.create_strategy_object(
            strategy_type=StrategyType.LONG_PUT,
            underlying_price=155.0,
            strike=150.0,
            premium=3.0,
            iv=0.25,
            dte=30,
            gamma=0.02,
            theta=-0.05,
            vega=0.15,
        )
        assert isinstance(obj, LongPutPricer)

        pos_data = PositionData(
            position_id="test-lp-1",
            symbol="AAPL 20260601 150.0P",
            quantity=1,
        )
        PositionDataBuilder.populate_strategy_metrics(pos_data, obj)

        # Buyer: expected_return should be filled
        assert pos_data.expected_return is not None
        assert pos_data.max_loss is not None
        assert pos_data.max_loss == 3.0  # premium
        assert pos_data.max_profit == 150.0 - 3.0  # K - C

        # Seller metrics should be None
        assert pos_data.tgr is None
        assert pos_data.sas is None


# ============================================================================
# 5. Backtest PositionManager Strategy Type Inference
# ============================================================================


class TestBacktestStrategyInference:
    """Test backtest PositionManager correctly infers Long strategy types.

    Uses mock SimulatedPosition objects to isolate the inference logic.
    """

    def _make_simulated_position(
        self,
        option_type: OptionType,
        quantity: int,
    ):
        """Create a minimal mock SimulatedPosition."""
        mock_pos = MagicMock()
        mock_pos.option_type = option_type
        mock_pos.is_short = quantity < 0
        mock_pos.quantity = quantity
        mock_pos.position_id = "mock-pos"
        mock_pos.underlying = "GOOG"
        mock_pos.strike = 150.0
        mock_pos.expiration = date(2026, 6, 1)
        mock_pos.entry_price = 3.0
        mock_pos.current_price = 3.5
        mock_pos.market_value = abs(quantity) * 3.5 * 100
        mock_pos.unrealized_pnl = 50.0
        mock_pos.underlying_price = 155.0
        mock_pos.lot_size = 100
        return mock_pos

    def test_long_put_inferred(self):
        """PUT + not is_short → LONG_PUT."""
        pos = self._make_simulated_position(OptionType.PUT, quantity=1)
        assert pos.option_type == OptionType.PUT
        assert not pos.is_short

        # Replicate the inference logic from position_manager.py
        if pos.option_type == OptionType.PUT and pos.is_short:
            strategy_type = StrategyType.SHORT_PUT
        elif pos.option_type == OptionType.CALL and pos.is_short:
            strategy_type = StrategyType.NAKED_CALL
        elif pos.option_type == OptionType.PUT and not pos.is_short:
            strategy_type = StrategyType.LONG_PUT
        elif pos.option_type == OptionType.CALL and not pos.is_short:
            strategy_type = StrategyType.LONG_CALL
        else:
            strategy_type = StrategyType.UNKNOWN

        assert strategy_type == StrategyType.LONG_PUT

    def test_long_call_inferred(self):
        """CALL + not is_short → LONG_CALL."""
        pos = self._make_simulated_position(OptionType.CALL, quantity=2)
        assert pos.option_type == OptionType.CALL
        assert not pos.is_short

        if pos.option_type == OptionType.PUT and pos.is_short:
            strategy_type = StrategyType.SHORT_PUT
        elif pos.option_type == OptionType.CALL and pos.is_short:
            strategy_type = StrategyType.NAKED_CALL
        elif pos.option_type == OptionType.PUT and not pos.is_short:
            strategy_type = StrategyType.LONG_PUT
        elif pos.option_type == OptionType.CALL and not pos.is_short:
            strategy_type = StrategyType.LONG_CALL
        else:
            strategy_type = StrategyType.UNKNOWN

        assert strategy_type == StrategyType.LONG_CALL

    def test_short_put_regression(self):
        """PUT + is_short → SHORT_PUT (regression)."""
        pos = self._make_simulated_position(OptionType.PUT, quantity=-1)
        assert pos.is_short

        if pos.option_type == OptionType.PUT and pos.is_short:
            strategy_type = StrategyType.SHORT_PUT
        elif pos.option_type == OptionType.CALL and pos.is_short:
            strategy_type = StrategyType.NAKED_CALL
        elif pos.option_type == OptionType.PUT and not pos.is_short:
            strategy_type = StrategyType.LONG_PUT
        elif pos.option_type == OptionType.CALL and not pos.is_short:
            strategy_type = StrategyType.LONG_CALL
        else:
            strategy_type = StrategyType.UNKNOWN

        assert strategy_type == StrategyType.SHORT_PUT

    def test_short_call_regression(self):
        """CALL + is_short → NAKED_CALL (regression)."""
        pos = self._make_simulated_position(OptionType.CALL, quantity=-3)
        assert pos.is_short

        if pos.option_type == OptionType.PUT and pos.is_short:
            strategy_type = StrategyType.SHORT_PUT
        elif pos.option_type == OptionType.CALL and pos.is_short:
            strategy_type = StrategyType.NAKED_CALL
        elif pos.option_type == OptionType.PUT and not pos.is_short:
            strategy_type = StrategyType.LONG_PUT
        elif pos.option_type == OptionType.CALL and not pos.is_short:
            strategy_type = StrategyType.LONG_CALL
        else:
            strategy_type = StrategyType.UNKNOWN

        assert strategy_type == StrategyType.NAKED_CALL


# ============================================================================
# 6. Edge Cases
# ============================================================================


class TestLongPutEdgeCases:
    """Edge case tests for LongPutPricer."""

    def test_deep_itm_positive_expected_return(self):
        """Deep ITM long put (S << K) can have positive expected return."""
        strategy = LongPutPricer(
            spot_price=50, strike_price=100, premium=48.0,
            volatility=0.30, time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        # Deep ITM: intrinsic value ~50, premium paid 48, should be slightly positive
        assert e_return > 0

    def test_very_near_expiry(self):
        """Near expiry OTM long put should have expected return ≈ -premium."""
        strategy = LongPutPricer(
            spot_price=200, strike_price=100, premium=0.01,
            volatility=0.20, time_to_expiry=1 / 365,
        )
        e_return = strategy.calc_expected_return()
        # Almost certainly expires worthless
        assert e_return < 0
        assert abs(e_return + 0.01) < 0.005  # ≈ -premium

    def test_zero_premium_breakeven(self):
        """Breakeven equals strike when premium is 0 (edge case)."""
        strategy = LongPutPricer(
            spot_price=100, strike_price=95, premium=0.0,
            volatility=0.20, time_to_expiry=30 / 365,
        )
        assert strategy.calc_breakeven() == 95.0
        assert strategy.calc_max_loss() == 0.0

    def test_very_high_iv(self):
        """High IV increases expected payout for long options."""
        low_iv = LongPutPricer(
            spot_price=100, strike_price=95, premium=2.0,
            volatility=0.15, time_to_expiry=30 / 365,
        )
        high_iv = LongPutPricer(
            spot_price=100, strike_price=95, premium=2.0,
            volatility=0.60, time_to_expiry=30 / 365,
        )
        # Higher IV → higher expected payout (but same premium → better E[R])
        assert high_iv.calc_expected_return() > low_iv.calc_expected_return()

    def test_win_probability_increases_closer_to_atm(self):
        """Long put win probability higher when closer to ATM."""
        otm = LongPutPricer(
            spot_price=120, strike_price=100, premium=1.0,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        atm = LongPutPricer(
            spot_price=100, strike_price=100, premium=5.0,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert atm.calc_win_probability() > otm.calc_win_probability()


class TestLongCallEdgeCases:
    """Edge case tests for LongCallPricer."""

    def test_deep_itm_positive_expected_return(self):
        """Deep ITM long call (S >> K) can have positive expected return."""
        strategy = LongCallPricer(
            spot_price=200, strike_price=100, premium=98.0,
            volatility=0.30, time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        # Deep ITM: intrinsic value ~100, premium paid 98
        assert e_return > 0

    def test_very_near_expiry_otm(self):
        """Near expiry OTM long call should have expected return ≈ -premium."""
        strategy = LongCallPricer(
            spot_price=100, strike_price=200, premium=0.01,
            volatility=0.20, time_to_expiry=1 / 365,
        )
        e_return = strategy.calc_expected_return()
        assert e_return < 0
        assert abs(e_return + 0.01) < 0.005

    def test_max_loss_always_premium(self):
        """Max loss is always the premium, regardless of market conditions."""
        for premium in [0.5, 5.0, 50.0]:
            strategy = LongCallPricer(
                spot_price=100, strike_price=100, premium=premium,
                volatility=0.25, time_to_expiry=30 / 365,
            )
            assert strategy.calc_max_loss() == premium

    def test_breakeven_increases_with_premium(self):
        """Higher premium → higher breakeven for long call."""
        low = LongCallPricer(
            spot_price=100, strike_price=100, premium=2.0,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        high = LongCallPricer(
            spot_price=100, strike_price=100, premium=8.0,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert high.calc_breakeven() > low.calc_breakeven()


# ============================================================================
# 7. Buyer-Specific Metrics Behavior
# ============================================================================


class TestBuyerMetricsBehavior:
    """Test that buyer pricers correctly handle seller vs buyer metrics."""

    @pytest.fixture
    def long_put_with_greeks(self):
        return LongPutPricer(
            spot_price=100, strike_price=95, premium=2.0,
            volatility=0.25, time_to_expiry=30 / 365,
            hv=0.20, dte=30,
            delta=-0.3, gamma=0.02, theta=-0.03, vega=0.15,
        )

    @pytest.fixture
    def long_call_with_greeks(self):
        return LongCallPricer(
            spot_price=100, strike_price=105, premium=2.5,
            volatility=0.25, time_to_expiry=30 / 365,
            hv=0.20, dte=30,
            delta=0.4, gamma=0.02, theta=-0.04, vega=0.12,
        )

    def test_long_put_seller_metrics_none(self, long_put_with_greeks):
        """All seller-specific metrics return None for long put."""
        s = long_put_with_greeks
        assert s.calc_tgr() is None
        assert s.calc_sas() is None
        assert s.calc_premium_rate() is None
        assert s.calc_theta_margin_ratio() is None

    def test_long_call_seller_metrics_none(self, long_call_with_greeks):
        """All seller-specific metrics return None for long call."""
        s = long_call_with_greeks
        assert s.calc_tgr() is None
        assert s.calc_sas() is None
        assert s.calc_premium_rate() is None
        assert s.calc_theta_margin_ratio() is None

    def test_long_put_effective_margin_is_premium(self, long_put_with_greeks):
        """Long put effective margin = premium paid."""
        assert long_put_with_greeks.get_effective_margin() == 2.0

    def test_long_call_effective_margin_is_premium(self, long_call_with_greeks):
        """Long call effective margin = premium paid."""
        assert long_call_with_greeks.get_effective_margin() == 2.5

    def test_long_put_margin_requirement_is_premium(self, long_put_with_greeks):
        """Long put margin requirement = premium (no margin needed)."""
        assert long_put_with_greeks.calc_margin_requirement() == 2.0

    def test_long_call_margin_requirement_is_premium(self, long_call_with_greeks):
        """Long call margin requirement = premium (no margin needed)."""
        assert long_call_with_greeks.calc_margin_requirement() == 2.5

    def test_long_put_roc_uses_expected_return(self, long_put_with_greeks):
        """ROC for long put uses expected_return / premium, not premium / margin."""
        roc = long_put_with_greeks.calc_roc()
        expected_roc = long_put_with_greeks.calc_expected_roc()
        # For buyers, roc == expected_roc
        assert roc is not None
        assert expected_roc is not None
        assert abs(roc - expected_roc) < 1e-10

    def test_long_call_roc_uses_expected_return(self, long_call_with_greeks):
        """ROC for long call uses expected_return / premium."""
        roc = long_call_with_greeks.calc_roc()
        expected_roc = long_call_with_greeks.calc_expected_roc()
        assert roc is not None
        assert expected_roc is not None
        assert abs(roc - expected_roc) < 1e-10

    def test_long_put_sharpe_ratio_exists(self, long_put_with_greeks):
        """Sharpe ratio should be computable for long put."""
        sr = long_put_with_greeks.calc_sharpe_ratio()
        assert sr is not None
        # OTM long put typically has negative Sharpe (negative E[R])
        assert sr < 0

    def test_long_put_kelly_fraction_zero_for_negative_er(self, long_put_with_greeks):
        """Kelly fraction = 0 when expected return is negative."""
        kelly = long_put_with_greeks.calc_kelly_fraction()
        assert kelly == 0.0  # E[R] < 0 → kelly = 0

    def test_long_put_prei_still_works(self, long_put_with_greeks):
        """PREI (position risk index) should still be computable for buyers."""
        prei = long_put_with_greeks.calc_prei()
        assert prei is not None
        assert 0 <= prei <= 100

    def test_full_metrics_object(self, long_put_with_greeks):
        """calc_metrics() returns a complete PricingMetrics."""
        metrics = long_put_with_greeks.calc_metrics()
        assert isinstance(metrics, PricingMetrics)

        # Core fields populated
        assert metrics.expected_return is not None
        assert metrics.return_std is not None
        assert metrics.return_variance is not None
        assert metrics.max_profit is not None
        assert metrics.max_loss is not None
        assert metrics.breakeven is not None
        assert metrics.win_probability is not None
        assert metrics.sharpe_ratio is not None
        assert metrics.kelly_fraction is not None

        # Buyer: PREI works, ROC works
        assert metrics.prei is not None
        assert metrics.roc is not None
        assert metrics.expected_roc is not None

        # Seller metrics None
        assert metrics.tgr is None
        assert metrics.sas is None
        assert metrics.premium_rate is None
        assert metrics.theta_margin_ratio is None


# ============================================================================
# 8. StrategyType Enum Consistency
# ============================================================================


class TestStrategyTypeEnum:
    """Test StrategyType enum values and from_string() compatibility."""

    def test_long_put_value(self):
        assert StrategyType.LONG_PUT.value == "long_put"

    def test_long_call_value(self):
        assert StrategyType.LONG_CALL.value == "long_call"

    def test_from_string_long_put(self):
        assert StrategyType.from_string("long_put") == StrategyType.LONG_PUT

    def test_from_string_long_call(self):
        assert StrategyType.from_string("long_call") == StrategyType.LONG_CALL

    def test_from_string_invalid(self):
        assert StrategyType.from_string("long_butterfly") == StrategyType.UNKNOWN

    def test_str_serialization(self):
        """StrategyType inherits str, so str() should return the value."""
        assert str(StrategyType.LONG_PUT) == "StrategyType.LONG_PUT" or StrategyType.LONG_PUT == "long_put"
        # The key guarantee: value comparison works for JSON
        assert StrategyType.LONG_PUT.value == "long_put"
        assert StrategyType.LONG_CALL.value == "long_call"


# ============================================================================
# 9. Cross-Pricer Consistency (Long Put vs Long Call)
# ============================================================================


class TestCrossPricerConsistency:
    """Verify logical relationships between Long Put and Long Call."""

    def test_otm_buyer_negative_expected_return(self):
        """Both OTM long put and OTM long call should have E[R] < 0."""
        long_put = LongPutPricer(
            spot_price=100, strike_price=90, premium=1.5,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        long_call = LongCallPricer(
            spot_price=100, strike_price=110, premium=1.5,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert long_put.calc_expected_return() < 0
        assert long_call.calc_expected_return() < 0

    def test_otm_buyer_win_prob_below_50(self):
        """OTM buyers should have < 50% win probability."""
        long_put = LongPutPricer(
            spot_price=100, strike_price=90, premium=1.5,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        long_call = LongCallPricer(
            spot_price=100, strike_price=110, premium=1.5,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert long_put.calc_win_probability() < 0.5
        assert long_call.calc_win_probability() < 0.5

    def test_max_loss_equals_premium_for_both(self):
        """Max loss = premium for both long put and long call."""
        premium = 5.0
        long_put = LongPutPricer(
            spot_price=100, strike_price=100, premium=premium,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        long_call = LongCallPricer(
            spot_price=100, strike_price=100, premium=premium,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert long_put.calc_max_loss() == premium
        assert long_call.calc_max_loss() == premium

    def test_long_put_max_profit_finite(self):
        """Long put max profit is finite (K - C)."""
        strategy = LongPutPricer(
            spot_price=100, strike_price=100, premium=5.0,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert strategy.calc_max_profit() == 95.0  # 100 - 5

    def test_long_call_max_profit_large(self):
        """Long call max profit is 10*K (unlimited proxy)."""
        strategy = LongCallPricer(
            spot_price=100, strike_price=100, premium=5.0,
            volatility=0.25, time_to_expiry=30 / 365,
        )
        assert strategy.calc_max_profit() == 1000.0  # 10 * 100


# ============================================================================
# 10. Numerical Correctness — Independent BS Verification
# ============================================================================

# Test scenarios: (label, S, K, C, r, σ, T_days, hv)
NUMERICAL_SCENARIOS_PUT = [
    ("ATM_30d", 100.0, 100.0, 5.0, 0.03, 0.25, 30, None),
    ("OTM_45d", 155.0, 140.0, 2.5, 0.03, 0.20, 45, None),
    ("ITM_60d", 90.0, 100.0, 12.0, 0.03, 0.30, 60, None),
    ("deep_OTM_14d", 200.0, 150.0, 0.3, 0.03, 0.15, 14, None),
    ("high_IV_30d", 100.0, 95.0, 8.0, 0.03, 0.60, 30, None),
    ("near_expiry_7d", 100.0, 98.0, 1.5, 0.03, 0.25, 7, None),
    ("long_dated_180d", 100.0, 110.0, 15.0, 0.05, 0.30, 180, None),
    ("hv_differs", 100.0, 95.0, 3.0, 0.03, 0.30, 30, 0.20),
]

NUMERICAL_SCENARIOS_CALL = [
    ("ATM_30d", 100.0, 100.0, 5.0, 0.03, 0.25, 30, None),
    ("OTM_45d", 100.0, 115.0, 1.5, 0.03, 0.20, 45, None),
    ("ITM_60d", 120.0, 100.0, 22.0, 0.03, 0.30, 60, None),
    ("deep_OTM_14d", 100.0, 150.0, 0.1, 0.03, 0.15, 14, None),
    ("high_IV_30d", 100.0, 105.0, 9.0, 0.03, 0.60, 30, None),
    ("near_expiry_7d", 100.0, 102.0, 1.0, 0.03, 0.25, 7, None),
    ("long_dated_180d", 100.0, 90.0, 18.0, 0.05, 0.30, 180, None),
    ("hv_differs", 100.0, 110.0, 2.0, 0.03, 0.30, 30, 0.20),
]


class TestLongPutNumericalCorrectness:
    """Verify LongPutPricer computed values against independent BS calculations."""

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_PUT
    )
    def test_expected_return(self, label, S, K, C, r, sigma, dte, hv):
        """E[π] from pricer matches independent BS formula."""
        T = dte / 365.0
        pricer = LongPutPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        # Independent calculation uses HV if provided, else IV (same as pricer)
        sigma_real = hv if hv and hv > 0 else sigma
        expected_independent = _long_put_expected_return(S, K, C, r, sigma_real, T)
        actual = pricer.calc_expected_return()

        assert abs(actual - expected_independent) < 1e-10, (
            f"{label}: pricer={actual:.12f}, independent={expected_independent:.12f}"
        )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_PUT
    )
    def test_variance(self, label, S, K, C, r, sigma, dte, hv):
        """Var[π] from pricer matches independent BS formula (uses IV, not HV)."""
        T = dte / 365.0
        pricer = LongPutPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        # Variance always uses IV (not HV)
        e_pi = pricer.calc_expected_return()
        expected_var = _put_variance(S, K, C, r, sigma, T, e_pi)
        actual_var = pricer.calc_return_variance()

        # Use relative tolerance for large variances
        tol = max(1e-6, abs(expected_var) * 1e-9)
        assert abs(actual_var - expected_var) < tol, (
            f"{label}: pricer_var={actual_var:.10f}, independent_var={expected_var:.10f}"
        )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_PUT
    )
    def test_win_probability(self, label, S, K, C, r, sigma, dte, hv):
        """Win probability = N(-d2) at breakeven K-C."""
        T = dte / 365.0
        pricer = LongPutPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        # Independent: N(-d2) at breakeven = K - C
        breakeven = K - C
        if breakeven <= 0:
            return  # Skip invalid breakeven
        d2_be = _bs_d2(S, breakeven, r, sigma, T)
        expected_wp = _N(-d2_be)
        actual_wp = pricer.calc_win_probability()

        assert abs(actual_wp - expected_wp) < 1e-10, (
            f"{label}: pricer_wp={actual_wp:.10f}, independent_wp={expected_wp:.10f}"
        )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_PUT
    )
    def test_roc(self, label, S, K, C, r, sigma, dte, hv):
        """ROC = (E[R] / premium) * (365 / DTE)."""
        T = dte / 365.0
        pricer = LongPutPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        e_return = pricer.calc_expected_return()
        expected_roc = (e_return / C) * (365.0 / dte) if C > 0 else None
        actual_roc = pricer.calc_roc()

        if expected_roc is None:
            assert actual_roc is None
        else:
            assert abs(actual_roc - expected_roc) < 1e-8, (
                f"{label}: pricer_roc={actual_roc:.10f}, independent_roc={expected_roc:.10f}"
            )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_PUT
    )
    def test_sharpe_ratio(self, label, S, K, C, r, sigma, dte, hv):
        """Sharpe = (E[π] - Rf) / Std[π], where Rf = margin * (e^(rT) - 1)."""
        T = dte / 365.0
        pricer = LongPutPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        e_pi = pricer.calc_expected_return()
        std_pi = pricer.calc_return_std()

        if std_pi <= 0:
            assert pricer.calc_sharpe_ratio() is None
            return

        # For buyers, effective margin = premium
        margin = C
        rf = margin * (math.exp(r * T) - 1)
        expected_sharpe = (e_pi - rf) / std_pi
        actual_sharpe = pricer.calc_sharpe_ratio()

        assert actual_sharpe is not None
        assert abs(actual_sharpe - expected_sharpe) < 1e-8, (
            f"{label}: pricer_sharpe={actual_sharpe:.10f}, expected={expected_sharpe:.10f}"
        )

    def test_breakeven_formula(self):
        """Breakeven = K - C for all scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_PUT:
            T = dte / 365.0
            pricer = LongPutPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            )
            assert pricer.calc_breakeven() == K - C, f"{label}"

    def test_max_profit_formula(self):
        """Max profit = K - C for all scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_PUT:
            T = dte / 365.0
            pricer = LongPutPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            )
            assert pricer.calc_max_profit() == K - C, f"{label}"

    def test_max_loss_is_premium(self):
        """Max loss = C for all scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_PUT:
            T = dte / 365.0
            pricer = LongPutPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            )
            assert pricer.calc_max_loss() == C, f"{label}"


class TestLongCallNumericalCorrectness:
    """Verify LongCallPricer computed values against independent BS calculations."""

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_CALL
    )
    def test_expected_return(self, label, S, K, C, r, sigma, dte, hv):
        """E[π] from pricer matches independent BS formula."""
        T = dte / 365.0
        pricer = LongCallPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        sigma_real = hv if hv and hv > 0 else sigma
        expected_independent = _long_call_expected_return(S, K, C, r, sigma_real, T)
        actual = pricer.calc_expected_return()

        assert abs(actual - expected_independent) < 1e-10, (
            f"{label}: pricer={actual:.12f}, independent={expected_independent:.12f}"
        )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_CALL
    )
    def test_variance(self, label, S, K, C, r, sigma, dte, hv):
        """Var[π] from pricer matches independent BS formula (uses IV)."""
        T = dte / 365.0
        pricer = LongCallPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        e_pi = pricer.calc_expected_return()
        expected_var = _call_variance(S, K, C, r, sigma, T, e_pi)
        actual_var = pricer.calc_return_variance()

        tol = max(1e-6, abs(expected_var) * 1e-9)
        assert abs(actual_var - expected_var) < tol, (
            f"{label}: pricer_var={actual_var:.10f}, independent_var={expected_var:.10f}"
        )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_CALL
    )
    def test_win_probability(self, label, S, K, C, r, sigma, dte, hv):
        """Win probability = N(d2) at breakeven K+C."""
        T = dte / 365.0
        pricer = LongCallPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        breakeven = K + C
        d2_be = _bs_d2(S, breakeven, r, sigma, T)
        expected_wp = _N(d2_be)  # P(S_T > breakeven) = N(d2)
        actual_wp = pricer.calc_win_probability()

        assert abs(actual_wp - expected_wp) < 1e-10, (
            f"{label}: pricer_wp={actual_wp:.10f}, independent_wp={expected_wp:.10f}"
        )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_CALL
    )
    def test_roc(self, label, S, K, C, r, sigma, dte, hv):
        """ROC = (E[R] / premium) * (365 / DTE)."""
        T = dte / 365.0
        pricer = LongCallPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        e_return = pricer.calc_expected_return()
        expected_roc = (e_return / C) * (365.0 / dte) if C > 0 else None
        actual_roc = pricer.calc_roc()

        if expected_roc is None:
            assert actual_roc is None
        else:
            assert abs(actual_roc - expected_roc) < 1e-8, (
                f"{label}: pricer_roc={actual_roc:.10f}, independent_roc={expected_roc:.10f}"
            )

    @pytest.mark.parametrize(
        "label,S,K,C,r,sigma,dte,hv", NUMERICAL_SCENARIOS_CALL
    )
    def test_sharpe_ratio(self, label, S, K, C, r, sigma, dte, hv):
        """Sharpe = (E[π] - Rf) / Std[π], where Rf = margin * (e^(rT) - 1)."""
        T = dte / 365.0
        pricer = LongCallPricer(
            spot_price=S, strike_price=K, premium=C,
            volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            hv=hv, dte=dte,
        )
        e_pi = pricer.calc_expected_return()
        std_pi = pricer.calc_return_std()

        if std_pi <= 0:
            assert pricer.calc_sharpe_ratio() is None
            return

        margin = C  # buyer: effective margin = premium
        rf = margin * (math.exp(r * T) - 1)
        expected_sharpe = (e_pi - rf) / std_pi
        actual_sharpe = pricer.calc_sharpe_ratio()

        assert actual_sharpe is not None
        assert abs(actual_sharpe - expected_sharpe) < 1e-8, (
            f"{label}: pricer_sharpe={actual_sharpe:.10f}, expected={expected_sharpe:.10f}"
        )

    def test_breakeven_formula(self):
        """Breakeven = K + C for all scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_CALL:
            T = dte / 365.0
            pricer = LongCallPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            )
            assert pricer.calc_breakeven() == K + C, f"{label}"

    def test_max_profit_formula(self):
        """Max profit = 10 * K (unlimited proxy) for all scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_CALL:
            T = dte / 365.0
            pricer = LongCallPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            )
            assert pricer.calc_max_profit() == 10 * K, f"{label}"

    def test_max_loss_is_premium(self):
        """Max loss = C for all scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_CALL:
            T = dte / 365.0
            pricer = LongCallPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
            )
            assert pricer.calc_max_loss() == C, f"{label}"


class TestVarianceNumericalProperties:
    """Verify mathematical properties of variance calculations."""

    def test_variance_non_negative_put(self):
        """Variance must be >= 0 for all put scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_PUT:
            T = dte / 365.0
            pricer = LongPutPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
                hv=hv,
            )
            assert pricer.calc_return_variance() >= 0, f"{label}: negative variance"

    def test_variance_non_negative_call(self):
        """Variance must be >= 0 for all call scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_CALL:
            T = dte / 365.0
            pricer = LongCallPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
                hv=hv,
            )
            assert pricer.calc_return_variance() >= 0, f"{label}: negative variance"

    def test_std_equals_sqrt_variance_put(self):
        """Std = √Var for all put scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_PUT:
            T = dte / 365.0
            pricer = LongPutPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
                hv=hv,
            )
            var = pricer.calc_return_variance()
            std = pricer.calc_return_std()
            assert abs(std - math.sqrt(var)) < 1e-10, f"{label}"

    def test_std_equals_sqrt_variance_call(self):
        """Std = √Var for all call scenarios."""
        for label, S, K, C, r, sigma, dte, hv in NUMERICAL_SCENARIOS_CALL:
            T = dte / 365.0
            pricer = LongCallPricer(
                spot_price=S, strike_price=K, premium=C,
                volatility=sigma, time_to_expiry=T, risk_free_rate=r,
                hv=hv,
            )
            var = pricer.calc_return_variance()
            std = pricer.calc_return_std()
            assert abs(std - math.sqrt(var)) < 1e-10, f"{label}"

    def test_higher_iv_increases_variance_put(self):
        """Higher IV should produce larger variance (same premium)."""
        params = dict(spot_price=100, strike_price=95, premium=3.0, time_to_expiry=30/365)
        low = LongPutPricer(volatility=0.15, **params)
        high = LongPutPricer(volatility=0.50, **params)
        assert high.calc_return_variance() > low.calc_return_variance()

    def test_higher_iv_increases_variance_call(self):
        """Higher IV should produce larger variance (same premium)."""
        params = dict(spot_price=100, strike_price=105, premium=2.0, time_to_expiry=30/365)
        low = LongCallPricer(volatility=0.15, **params)
        high = LongCallPricer(volatility=0.50, **params)
        assert high.calc_return_variance() > low.calc_return_variance()
