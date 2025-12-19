"""Tests for Black-Scholes model calculations."""

import math

import pytest

from src.engine.models import BSParams
from src.engine.bs import (
    calc_bs_call_price,
    calc_bs_put_price,
    calc_bs_price,
    calc_call_exercise_prob,
    calc_call_itm_prob,
    calc_d1,
    calc_d2,
    calc_d3,
    calc_n,
    calc_put_exercise_prob,
    calc_put_itm_prob,
    calc_bs_greeks,
    calc_bs_delta,
    calc_bs_gamma,
    calc_bs_theta,
    calc_bs_vega,
    calc_bs_rho,
)


class TestBSCore:
    """Tests for B-S core calculations."""

    @pytest.fixture
    def atm_params(self):
        """ATM option params: S=100, K=100, r=0.05, σ=0.20, T=1.0"""
        return BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=True,
        )

    def test_calc_d1_basic(self, atm_params):
        """Test d1 calculation.

        d1 = [ln(S/K) + (r + σ²/2)×T] / (σ×√T)

        S=100, K=100, r=0.05, σ=0.20, T=1.0
        d1 = [ln(1) + (0.05 + 0.02)×1] / (0.20×1) = 0.07/0.20 = 0.35
        """
        d1 = calc_d1(atm_params)
        assert d1 is not None
        assert abs(d1 - 0.35) < 0.01

    def test_calc_d1_otm_call(self):
        """Test d1 for OTM call (S < K)."""
        params = BSParams(
            spot_price=90.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=True,
        )
        d1 = calc_d1(params)
        assert d1 is not None
        # d1 should be smaller (more negative) for OTM call
        assert d1 < 0.35

    def test_calc_d1_itm_call(self):
        """Test d1 for ITM call (S > K)."""
        params = BSParams(
            spot_price=110.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=True,
        )
        d1 = calc_d1(params)
        assert d1 is not None
        # d1 should be larger for ITM call
        assert d1 > 0.35

    def test_calc_d1_zero_time(self):
        """Test d1 with zero time returns None."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0,
        )
        d1 = calc_d1(params)
        assert d1 is None

    def test_calc_d1_zero_volatility(self):
        """Test d1 with zero volatility returns None."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0,
            time_to_expiry=1.0,
        )
        d1 = calc_d1(params)
        assert d1 is None

    def test_calc_d2_basic(self, atm_params):
        """Test d2 calculation.

        d2 = d1 - σ×√T
        With d1=0.35, σ=0.20, T=1.0:
        d2 = 0.35 - 0.20×1 = 0.15
        """
        d1 = calc_d1(atm_params)
        d2 = calc_d2(atm_params, d1)
        assert d2 is not None
        assert abs(d2 - 0.15) < 0.01

    def test_calc_d3_basic(self, atm_params):
        """Test d3 calculation.

        d3 = d2 + 2σ√T
        With d2=0.15, σ=0.20, T=1.0:
        d3 = 0.15 + 2×0.20×1 = 0.55
        """
        d1 = calc_d1(atm_params)
        d2 = calc_d2(atm_params, d1)
        d3 = calc_d3(atm_params, d2)
        assert d3 is not None
        assert abs(d3 - 0.55) < 0.01

    def test_calc_n_standard_values(self):
        """Test N(d) for standard values."""
        # N(0) = 0.5
        assert abs(calc_n(0) - 0.5) < 0.001

        # N(1) ≈ 0.8413
        assert abs(calc_n(1) - 0.8413) < 0.001

        # N(-1) ≈ 0.1587
        assert abs(calc_n(-1) - 0.1587) < 0.001

        # N(2) ≈ 0.9772
        assert abs(calc_n(2) - 0.9772) < 0.001

    def test_calc_bs_call_price(self, atm_params):
        """Test B-S call price calculation.

        Using textbook example: S=100, K=100, r=5%, σ=20%, T=1
        Expected call price ≈ 10.45
        """
        price = calc_bs_call_price(atm_params)
        assert price is not None
        assert 10 < price < 11

    def test_calc_bs_put_price(self, atm_params):
        """Test B-S put price calculation.

        Using put-call parity: P = C - S + K×e^(-rT)
        """
        call_price = calc_bs_call_price(atm_params)
        put_params = atm_params.with_is_call(False)
        put_price = calc_bs_put_price(put_params)
        assert put_price is not None

        # Put-call parity check
        parity = call_price - put_price - 100 + 100 * math.exp(-0.05 * 1.0)
        assert abs(parity) < 0.01

    def test_calc_bs_price_otm_put(self):
        """Test B-S put price for OTM put (S > K)."""
        otm_put = BSParams(
            spot_price=110.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
            is_call=False,
        )
        atm_put = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
            is_call=False,
        )
        otm_price = calc_bs_put_price(otm_put)
        atm_price = calc_bs_put_price(atm_put)
        assert otm_price is not None
        # OTM put should have lower price
        assert otm_price < atm_price


class TestBSProbability:
    """Tests for B-S probability calculations."""

    @pytest.fixture
    def atm_params(self):
        """ATM option params."""
        return BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
        )

    def test_calc_put_exercise_prob(self, atm_params):
        """Test put exercise probability = N(-d2).

        For ATM option, exercise prob should be around 0.5.
        """
        prob = calc_put_exercise_prob(atm_params)
        assert prob is not None
        assert 0.4 < prob < 0.6

    def test_calc_put_exercise_prob_otm(self):
        """Test put exercise probability for OTM put (S > K)."""
        params = BSParams(
            spot_price=120.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
        )
        prob = calc_put_exercise_prob(params)
        assert prob is not None
        # OTM put has low exercise probability
        assert prob < 0.3

    def test_calc_put_exercise_prob_itm(self):
        """Test put exercise probability for ITM put (S < K)."""
        params = BSParams(
            spot_price=80.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
        )
        prob = calc_put_exercise_prob(params)
        assert prob is not None
        # ITM put has high exercise probability
        assert prob > 0.7

    def test_calc_call_exercise_prob(self, atm_params):
        """Test call exercise probability = N(d2)."""
        prob = calc_call_exercise_prob(atm_params)
        assert prob is not None
        assert 0.4 < prob < 0.6

    def test_calc_call_exercise_prob_otm(self):
        """Test call exercise probability for OTM call (S < K)."""
        params = BSParams(
            spot_price=80.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
        )
        prob = calc_call_exercise_prob(params)
        assert prob is not None
        # OTM call has low exercise probability
        assert prob < 0.3

    def test_calc_call_exercise_prob_itm(self):
        """Test call exercise probability for ITM call (S > K)."""
        params = BSParams(
            spot_price=120.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
        )
        prob = calc_call_exercise_prob(params)
        assert prob is not None
        # ITM call has high exercise probability
        assert prob > 0.7

    def test_exercise_prob_sum(self, atm_params):
        """Test that put and call exercise probs sum to 1.

        This is expected because they use N(-d2) and N(d2) respectively.
        """
        put_prob = calc_put_exercise_prob(atm_params)
        call_prob = calc_call_exercise_prob(atm_params)
        assert abs(put_prob + call_prob - 1.0) < 0.001

    def test_calc_put_itm_prob(self, atm_params):
        """Test put ITM probability = N(-d1)."""
        prob = calc_put_itm_prob(atm_params)
        assert prob is not None
        assert 0.3 < prob < 0.5

    def test_calc_call_itm_prob(self, atm_params):
        """Test call ITM probability = N(d1)."""
        prob = calc_call_itm_prob(atm_params)
        assert prob is not None
        assert 0.5 < prob < 0.7


class TestBSEdgeCases:
    """Tests for B-S edge cases."""

    def test_very_short_expiry(self):
        """Test with very short time to expiry (1 day)."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1 / 365,
            is_call=True,
        )
        d1 = calc_d1(params)
        assert d1 is not None

        call_price = calc_bs_call_price(params)
        assert call_price is not None
        # ATM option with 1 day should have very small premium
        assert call_price < 2

    def test_high_volatility(self):
        """Test with high volatility."""
        high_vol = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.50,
            time_to_expiry=1.0,
            is_call=True,
        )
        low_vol = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=True,
        )
        high_vol_price = calc_bs_call_price(high_vol)
        low_vol_price = calc_bs_call_price(low_vol)
        # Higher volatility should mean higher option price
        assert high_vol_price > low_vol_price

    def test_deep_itm_option(self):
        """Test deep ITM option."""
        # Deep ITM call (S >> K)
        params = BSParams(
            spot_price=150.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
            is_call=True,
        )
        call_price = calc_bs_call_price(params)
        # Should be close to intrinsic value
        intrinsic = 150 - 100
        assert call_price >= intrinsic
        assert call_price < intrinsic + 10

    def test_deep_otm_option(self):
        """Test deep OTM option."""
        # Deep OTM call (S << K)
        params = BSParams(
            spot_price=50.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.5,
            is_call=True,
        )
        call_price = calc_bs_call_price(params)
        # Should be very close to 0
        assert call_price < 0.1


class TestBSParamsFunctions:
    """Tests for BSParams-based B-S functions."""

    @pytest.fixture
    def call_params(self):
        """Create BSParams for a call option."""
        return BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=True,
        )

    @pytest.fixture
    def put_params(self):
        """Create BSParams for a put option."""
        return BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=False,
        )

    def test_calc_bs_price_call(self, call_params):
        """Test calc_bs_price for call option matches calc_bs_call_price."""
        price = calc_bs_price(call_params)
        expected = calc_bs_call_price(call_params)
        assert price == expected

    def test_calc_bs_price_put(self, put_params):
        """Test calc_bs_price for put option matches calc_bs_put_price."""
        price = calc_bs_price(put_params)
        expected = calc_bs_put_price(put_params)
        assert price == expected

    def test_calc_bs_greeks_call(self, call_params):
        """Test calc_bs_greeks returns all Greeks for call."""
        greeks = calc_bs_greeks(call_params)
        assert greeks["delta"] is not None
        assert greeks["gamma"] is not None
        assert greeks["theta"] is not None
        assert greeks["vega"] is not None
        assert greeks["rho"] is not None

        # Call delta should be positive
        assert greeks["delta"] > 0

    def test_calc_bs_greeks_put(self, put_params):
        """Test calc_bs_greeks returns all Greeks for put."""
        greeks = calc_bs_greeks(put_params)
        assert greeks["delta"] is not None
        # Put delta should be negative
        assert greeks["delta"] < 0

    def test_calc_bs_delta_call(self, call_params):
        """Test calc_bs_delta for call."""
        delta = calc_bs_delta(call_params)
        assert delta is not None
        # ATM call delta should be around 0.5-0.6
        assert 0.5 <= delta <= 0.65

    def test_calc_bs_delta_put(self, put_params):
        """Test calc_bs_delta for put."""
        delta = calc_bs_delta(put_params)
        assert delta is not None
        # ATM put delta should be around -0.35 to -0.5
        assert -0.55 <= delta <= -0.3

    def test_calc_bs_gamma(self, call_params):
        """Test calc_bs_gamma."""
        gamma = calc_bs_gamma(call_params)
        assert gamma is not None
        assert gamma > 0  # Gamma is always positive

    def test_calc_bs_theta(self, call_params):
        """Test calc_bs_theta."""
        theta = calc_bs_theta(call_params)
        assert theta is not None
        assert theta < 0  # Theta is typically negative (time decay)

    def test_calc_bs_vega(self, call_params):
        """Test calc_bs_vega."""
        vega = calc_bs_vega(call_params)
        assert vega is not None
        assert vega > 0  # Vega is always positive

    def test_calc_bs_rho_call(self, call_params):
        """Test calc_bs_rho for call."""
        rho = calc_bs_rho(call_params)
        assert rho is not None
        assert rho > 0  # Call rho is positive

    def test_calc_bs_rho_put(self, put_params):
        """Test calc_bs_rho for put."""
        rho = calc_bs_rho(put_params)
        assert rho is not None
        assert rho < 0  # Put rho is negative

    def test_with_spot_affects_price(self, call_params):
        """Test that with_spot correctly creates params with different spot."""
        original_price = calc_bs_price(call_params)
        new_params = call_params.with_spot(110.0)
        new_price = calc_bs_price(new_params)

        # Higher spot should mean higher call price
        assert new_price > original_price

    def test_with_volatility_affects_greeks(self, call_params):
        """Test that with_volatility correctly creates params with different vol."""
        new_params = call_params.with_volatility(0.30)
        assert new_params.volatility == 0.30

        # Both should calculate correctly
        vega1 = calc_bs_vega(call_params)
        vega2 = calc_bs_vega(new_params)
        assert vega1 is not None
        assert vega2 is not None
