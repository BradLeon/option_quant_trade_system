"""Tests for Black-Scholes model calculations."""

import math

import pytest

from src.engine.bs import (
    calc_bs_call_price,
    calc_bs_put_price,
    calc_call_exercise_prob,
    calc_call_itm_prob,
    calc_d1,
    calc_d2,
    calc_d3,
    calc_n,
    calc_put_exercise_prob,
    calc_put_itm_prob,
)


class TestBSCore:
    """Tests for B-S core calculations."""

    def test_calc_d1_basic(self):
        """Test d1 calculation.

        d1 = [ln(S/K) + (r + σ²/2)×T] / (σ×√T)

        S=100, K=100, r=0.05, σ=0.20, T=1.0
        d1 = [ln(1) + (0.05 + 0.02)×1] / (0.20×1) = 0.07/0.20 = 0.35
        """
        d1 = calc_d1(100, 100, 0.05, 0.20, 1.0)
        assert d1 is not None
        assert abs(d1 - 0.35) < 0.01

    def test_calc_d1_otm_call(self):
        """Test d1 for OTM call (S < K)."""
        d1 = calc_d1(90, 100, 0.05, 0.20, 1.0)
        assert d1 is not None
        # d1 should be smaller (more negative) for OTM call
        assert d1 < 0.35

    def test_calc_d1_itm_call(self):
        """Test d1 for ITM call (S > K)."""
        d1 = calc_d1(110, 100, 0.05, 0.20, 1.0)
        assert d1 is not None
        # d1 should be larger for ITM call
        assert d1 > 0.35

    def test_calc_d1_zero_time(self):
        """Test d1 with zero time returns None."""
        d1 = calc_d1(100, 100, 0.05, 0.20, 0)
        assert d1 is None

    def test_calc_d1_zero_volatility(self):
        """Test d1 with zero volatility returns None."""
        d1 = calc_d1(100, 100, 0.05, 0, 1.0)
        assert d1 is None

    def test_calc_d2_basic(self):
        """Test d2 calculation.

        d2 = d1 - σ×√T
        With d1=0.35, σ=0.20, T=1.0:
        d2 = 0.35 - 0.20×1 = 0.15
        """
        d1 = 0.35
        d2 = calc_d2(d1, 0.20, 1.0)
        assert d2 is not None
        assert abs(d2 - 0.15) < 0.01

    def test_calc_d3_basic(self):
        """Test d3 calculation.

        d3 = d2 + 2σ√T
        With d2=0.15, σ=0.20, T=1.0:
        d3 = 0.15 + 2×0.20×1 = 0.55
        """
        d2 = 0.15
        d3 = calc_d3(d2, 0.20, 1.0)
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

    def test_calc_bs_call_price(self):
        """Test B-S call price calculation.

        Using textbook example: S=100, K=100, r=5%, σ=20%, T=1
        Expected call price ≈ 10.45
        """
        price = calc_bs_call_price(100, 100, 0.05, 0.20, 1.0)
        assert price is not None
        assert 10 < price < 11

    def test_calc_bs_put_price(self):
        """Test B-S put price calculation.

        Using put-call parity: P = C - S + K×e^(-rT)
        """
        call_price = calc_bs_call_price(100, 100, 0.05, 0.20, 1.0)
        put_price = calc_bs_put_price(100, 100, 0.05, 0.20, 1.0)
        assert put_price is not None

        # Put-call parity check
        parity = call_price - put_price - 100 + 100 * math.exp(-0.05 * 1.0)
        assert abs(parity) < 0.01

    def test_calc_bs_price_otm_put(self):
        """Test B-S put price for OTM put (S > K)."""
        put_price = calc_bs_put_price(110, 100, 0.05, 0.20, 0.5)
        assert put_price is not None
        # OTM put should have lower price
        atm_put = calc_bs_put_price(100, 100, 0.05, 0.20, 0.5)
        assert put_price < atm_put


class TestBSProbability:
    """Tests for B-S probability calculations."""

    def test_calc_put_exercise_prob(self):
        """Test put exercise probability = N(-d2).

        For ATM option, exercise prob should be around 0.5.
        """
        prob = calc_put_exercise_prob(100, 100, 0.05, 0.20, 1.0)
        assert prob is not None
        assert 0.4 < prob < 0.6

    def test_calc_put_exercise_prob_otm(self):
        """Test put exercise probability for OTM put (S > K)."""
        prob = calc_put_exercise_prob(120, 100, 0.05, 0.20, 0.5)
        assert prob is not None
        # OTM put has low exercise probability
        assert prob < 0.3

    def test_calc_put_exercise_prob_itm(self):
        """Test put exercise probability for ITM put (S < K)."""
        prob = calc_put_exercise_prob(80, 100, 0.05, 0.20, 0.5)
        assert prob is not None
        # ITM put has high exercise probability
        assert prob > 0.7

    def test_calc_call_exercise_prob(self):
        """Test call exercise probability = N(d2)."""
        prob = calc_call_exercise_prob(100, 100, 0.05, 0.20, 1.0)
        assert prob is not None
        assert 0.4 < prob < 0.6

    def test_calc_call_exercise_prob_otm(self):
        """Test call exercise probability for OTM call (S < K)."""
        prob = calc_call_exercise_prob(80, 100, 0.05, 0.20, 0.5)
        assert prob is not None
        # OTM call has low exercise probability
        assert prob < 0.3

    def test_calc_call_exercise_prob_itm(self):
        """Test call exercise probability for ITM call (S > K)."""
        prob = calc_call_exercise_prob(120, 100, 0.05, 0.20, 0.5)
        assert prob is not None
        # ITM call has high exercise probability
        assert prob > 0.7

    def test_exercise_prob_sum(self):
        """Test that put and call exercise probs don't sum to 1.

        This is expected because they use N(-d2) and N(d2) respectively,
        but the strike prices are the same so they do sum to 1.
        """
        put_prob = calc_put_exercise_prob(100, 100, 0.05, 0.20, 1.0)
        call_prob = calc_call_exercise_prob(100, 100, 0.05, 0.20, 1.0)
        assert abs(put_prob + call_prob - 1.0) < 0.001

    def test_calc_put_itm_prob(self):
        """Test put ITM probability = N(-d1)."""
        prob = calc_put_itm_prob(100, 100, 0.05, 0.20, 1.0)
        assert prob is not None
        assert 0.3 < prob < 0.5

    def test_calc_call_itm_prob(self):
        """Test call ITM probability = N(d1)."""
        prob = calc_call_itm_prob(100, 100, 0.05, 0.20, 1.0)
        assert prob is not None
        assert 0.5 < prob < 0.7


class TestBSEdgeCases:
    """Tests for B-S edge cases."""

    def test_very_short_expiry(self):
        """Test with very short time to expiry (1 day)."""
        t = 1 / 365
        d1 = calc_d1(100, 100, 0.05, 0.20, t)
        assert d1 is not None

        call_price = calc_bs_call_price(100, 100, 0.05, 0.20, t)
        assert call_price is not None
        # ATM option with 1 day should have very small premium
        assert call_price < 2

    def test_high_volatility(self):
        """Test with high volatility."""
        call_price = calc_bs_call_price(100, 100, 0.05, 0.50, 1.0)
        low_vol_price = calc_bs_call_price(100, 100, 0.05, 0.20, 1.0)
        # Higher volatility should mean higher option price
        assert call_price > low_vol_price

    def test_deep_itm_option(self):
        """Test deep ITM option."""
        # Deep ITM call (S >> K)
        call_price = calc_bs_call_price(150, 100, 0.05, 0.20, 0.5)
        # Should be close to intrinsic value
        intrinsic = 150 - 100
        assert call_price >= intrinsic
        assert call_price < intrinsic + 10

    def test_deep_otm_option(self):
        """Test deep OTM option."""
        # Deep OTM call (S << K)
        call_price = calc_bs_call_price(50, 100, 0.05, 0.20, 0.5)
        # Should be very close to 0
        assert call_price < 0.1
