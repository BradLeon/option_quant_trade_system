"""Tests for contract utility functions.

Tests for:
- src/engine/contract/liquidity.py
- src/engine/contract/metrics.py
"""

import pytest

from src.engine.contract.liquidity import (
    calc_bid_ask_spread,
    calc_bid_ask_spread_ratio,
    calc_option_chain_open_interest,
    calc_option_chain_volume,
    is_liquid,
    liquidity_score,
)
from src.engine.contract.metrics import (
    calc_annual_return,
    calc_break_even,
    calc_expected_move,
    calc_max_loss,
    calc_moneyness,
    calc_otm_percent,
    calc_theta_gamma_ratio,
    calc_theta_premium_ratio,
)


# ====================
# Liquidity Tests
# ====================


class TestCalcBidAskSpread:
    """Tests for calc_bid_ask_spread function."""

    def test_normal_spread(self):
        """Test normal bid/ask spread calculation."""
        # Mid price = 2.0, spread = 0.2, spread% = 10%
        result = calc_bid_ask_spread(1.90, 2.10)
        assert result == pytest.approx(10.0)

    def test_tight_spread(self):
        """Test tight spread calculation."""
        # Mid price = 2.0, spread = 0.1, spread% = 5%
        result = calc_bid_ask_spread(1.95, 2.05)
        assert result == pytest.approx(5.0)

    def test_zero_spread(self):
        """Test zero spread (bid equals ask)."""
        result = calc_bid_ask_spread(2.0, 2.0)
        assert result == pytest.approx(0.0)

    def test_none_bid(self):
        """Test with None bid."""
        result = calc_bid_ask_spread(None, 2.0)
        assert result is None

    def test_none_ask(self):
        """Test with None ask."""
        result = calc_bid_ask_spread(1.9, None)
        assert result is None

    def test_negative_bid(self):
        """Test with negative bid."""
        result = calc_bid_ask_spread(-1.0, 2.0)
        assert result is None

    def test_ask_less_than_bid(self):
        """Test with ask less than bid (invalid)."""
        result = calc_bid_ask_spread(2.1, 1.9)
        assert result is None


class TestCalcBidAskSpreadRatio:
    """Tests for calc_bid_ask_spread_ratio function."""

    def test_normal_ratio(self):
        """Test normal spread ratio calculation."""
        result = calc_bid_ask_spread_ratio(1.90, 2.10)
        assert result == pytest.approx(0.10)

    def test_tight_ratio(self):
        """Test tight spread ratio."""
        result = calc_bid_ask_spread_ratio(1.95, 2.05)
        assert result == pytest.approx(0.05)


class TestCalcOptionChainVolume:
    """Tests for calc_option_chain_volume function."""

    def test_normal_volume(self):
        """Test total volume calculation."""

        class MockQuote:
            def __init__(self, volume):
                self.volume = volume

        quotes = [MockQuote(100), MockQuote(200), MockQuote(50)]
        result = calc_option_chain_volume(quotes)
        assert result == 350

    def test_with_zero_volume(self):
        """Test volume with zero volume contracts."""

        class MockQuote:
            def __init__(self, volume):
                self.volume = volume

        quotes = [MockQuote(100), MockQuote(0), MockQuote(50)]
        result = calc_option_chain_volume(quotes, include_zero_volume=False)
        assert result == 150

    def test_include_zero_volume(self):
        """Test including zero volume contracts."""

        class MockQuote:
            def __init__(self, volume):
                self.volume = volume

        quotes = [MockQuote(100), MockQuote(0), MockQuote(50)]
        result = calc_option_chain_volume(quotes, include_zero_volume=True)
        assert result == 150  # 0 doesn't add but also doesn't skip

    def test_empty_chain(self):
        """Test empty option chain."""
        result = calc_option_chain_volume([])
        assert result == 0


class TestCalcOptionChainOpenInterest:
    """Tests for calc_option_chain_open_interest function."""

    def test_normal_oi(self):
        """Test total open interest calculation."""

        class MockQuote:
            def __init__(self, oi):
                self.open_interest = oi

        quotes = [MockQuote(500), MockQuote(1000), MockQuote(250)]
        result = calc_option_chain_open_interest(quotes)
        assert result == 1750


class TestIsLiquid:
    """Tests for is_liquid function."""

    def test_liquid_contract(self):
        """Test liquid contract passes all checks."""
        result = is_liquid(
            bid=1.95,
            ask=2.05,
            open_interest=500,
            volume=50,
            max_spread_percent=10.0,
            min_open_interest=100,
            min_volume=10,
        )
        assert result is True

    def test_wide_spread_fails(self):
        """Test wide spread fails liquidity check."""
        result = is_liquid(
            bid=1.80,
            ask=2.20,  # 20% spread
            open_interest=500,
            volume=50,
            max_spread_percent=10.0,
            min_open_interest=100,
            min_volume=10,
        )
        assert result is False

    def test_low_oi_fails(self):
        """Test low open interest fails liquidity check."""
        result = is_liquid(
            bid=1.95,
            ask=2.05,
            open_interest=50,  # Below min
            volume=50,
            max_spread_percent=10.0,
            min_open_interest=100,
            min_volume=10,
        )
        assert result is False

    def test_low_volume_fails(self):
        """Test low volume fails liquidity check."""
        result = is_liquid(
            bid=1.95,
            ask=2.05,
            open_interest=500,
            volume=5,  # Below min
            max_spread_percent=10.0,
            min_open_interest=100,
            min_volume=10,
        )
        assert result is False


class TestLiquidityScore:
    """Tests for liquidity_score function."""

    def test_high_liquidity(self):
        """Test high liquidity score."""
        score = liquidity_score(
            bid=1.98,
            ask=2.02,  # 2% spread
            open_interest=2000,
            volume=200,
        )
        # Should be high score
        assert score > 70

    def test_low_liquidity(self):
        """Test low liquidity score."""
        score = liquidity_score(
            bid=1.80,
            ask=2.20,  # 20% spread
            open_interest=10,
            volume=2,
        )
        # Should be low score
        assert score < 30


# ====================
# Metrics Tests
# ====================


class TestCalcOtmPercent:
    """Tests for calc_otm_percent function."""

    def test_put_otm(self):
        """Test put option OTM calculation."""
        # Spot 100, strike 95, put is 5% OTM
        result = calc_otm_percent(100, 95, "put")
        assert result == pytest.approx(5.0)

    def test_call_otm(self):
        """Test call option OTM calculation."""
        # Spot 100, strike 105, call is 5% OTM
        result = calc_otm_percent(100, 105, "call")
        assert result == pytest.approx(5.0)

    def test_put_itm(self):
        """Test put option ITM returns 0."""
        # Spot 100, strike 105, put is ITM
        result = calc_otm_percent(100, 105, "put")
        assert result == 0.0

    def test_call_itm(self):
        """Test call option ITM returns 0."""
        # Spot 100, strike 95, call is ITM
        result = calc_otm_percent(100, 95, "call")
        assert result == 0.0

    def test_atm(self):
        """Test at-the-money returns 0."""
        result = calc_otm_percent(100, 100, "put")
        assert result == 0.0

    def test_invalid_option_type(self):
        """Test invalid option type returns None."""
        result = calc_otm_percent(100, 95, "invalid")
        assert result is None

    def test_none_spot(self):
        """Test None spot returns None."""
        result = calc_otm_percent(None, 95, "put")
        assert result is None


class TestCalcMoneyness:
    """Tests for calc_moneyness function."""

    def test_positive_moneyness(self):
        """Test positive moneyness (spot above strike)."""
        result = calc_moneyness(105, 100)
        assert result == pytest.approx(0.05)

    def test_negative_moneyness(self):
        """Test negative moneyness (spot below strike)."""
        result = calc_moneyness(95, 100)
        assert result == pytest.approx(-0.05)

    def test_atm_moneyness(self):
        """Test ATM moneyness."""
        result = calc_moneyness(100, 100)
        assert result == 0.0

    def test_zero_strike(self):
        """Test zero strike returns None."""
        result = calc_moneyness(100, 0)
        assert result is None


class TestCalcThetaPremiumRatio:
    """Tests for calc_theta_premium_ratio function."""

    def test_normal_ratio(self):
        """Test normal theta/premium ratio."""
        # Theta -0.05, premium 1.00 = 5% daily decay
        result = calc_theta_premium_ratio(-0.05, 1.00)
        assert result == pytest.approx(0.05)

    def test_positive_theta(self):
        """Test positive theta (short option perspective)."""
        result = calc_theta_premium_ratio(0.05, 1.00)
        assert result == pytest.approx(0.05)

    def test_none_theta(self):
        """Test None theta returns None."""
        result = calc_theta_premium_ratio(None, 1.00)
        assert result is None

    def test_zero_premium(self):
        """Test zero premium returns None."""
        result = calc_theta_premium_ratio(-0.05, 0)
        assert result is None


class TestCalcThetaGammaRatio:
    """Tests for calc_theta_gamma_ratio function."""

    def test_normal_tgr(self):
        """Test normal TGR calculation."""
        result = calc_theta_gamma_ratio(-0.03, 0.05)
        assert result == pytest.approx(0.6)

    def test_zero_gamma(self):
        """Test zero gamma returns None."""
        result = calc_theta_gamma_ratio(-0.03, 0)
        assert result is None


class TestCalcAnnualReturn:
    """Tests for calc_annual_return function."""

    def test_normal_return(self):
        """Test annual return calculation."""
        # 1.00 premium on 20.00 margin over 30 days
        result = calc_annual_return(1.00, 20.00, 30)
        # 5% * (365/30) = 60.8%
        assert result == pytest.approx(0.608, rel=0.01)

    def test_zero_margin(self):
        """Test zero margin returns None."""
        result = calc_annual_return(1.00, 0, 30)
        assert result is None

    def test_zero_dte(self):
        """Test zero DTE returns None."""
        result = calc_annual_return(1.00, 20.00, 0)
        assert result is None


class TestCalcBreakEven:
    """Tests for calc_break_even function."""

    def test_put_break_even(self):
        """Test put break-even calculation."""
        result = calc_break_even(100, 2, "put")
        assert result == 98.0

    def test_call_break_even(self):
        """Test call break-even calculation."""
        result = calc_break_even(100, 2, "call")
        assert result == 102.0

    def test_invalid_type(self):
        """Test invalid option type returns None."""
        result = calc_break_even(100, 2, "invalid")
        assert result is None


class TestCalcMaxLoss:
    """Tests for calc_max_loss function."""

    def test_put_max_loss(self):
        """Test put max loss (stock to zero)."""
        result = calc_max_loss(100, 2, "put")
        assert result == 98.0

    def test_call_max_loss(self):
        """Test call max loss estimate."""
        result = calc_max_loss(100, 2, "call", underlying_price=100)
        assert result == 98.0

    def test_call_no_underlying(self):
        """Test call without underlying returns None."""
        result = calc_max_loss(100, 2, "call")
        assert result is None


class TestCalcExpectedMove:
    """Tests for calc_expected_move function."""

    def test_normal_move(self):
        """Test expected move calculation."""
        # Spot 100, IV 30%, 30 days
        result = calc_expected_move(100, 0.30, 30)
        # 100 * 0.30 * sqrt(30/365) ≈ 8.59
        assert result == pytest.approx(8.59, rel=0.01)

    def test_zero_iv(self):
        """Test zero IV returns None."""
        result = calc_expected_move(100, 0, 30)
        assert result is None

    def test_zero_dte(self):
        """Test zero DTE returns None."""
        result = calc_expected_move(100, 0.30, 0)
        assert result is None
