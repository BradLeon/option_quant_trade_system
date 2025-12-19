"""Tests for Greeks extraction and B-S calculation fallback."""

import pytest
from datetime import date, datetime, timedelta

from src.data.models.option import Greeks, OptionContract, OptionQuote, OptionType
from src.engine.models import BSParams
from src.engine.position.greeks import (
    get_delta,
    get_gamma,
    get_greeks,
    get_rho,
    get_theta,
    get_vega,
)
from src.engine.bs.greeks import (
    calc_bs_delta,
    calc_bs_gamma,
    calc_bs_greeks,
    calc_bs_rho,
    calc_bs_theta,
    calc_bs_vega,
)


class TestBSGreeks:
    """Tests for Black-Scholes Greeks calculations."""

    def test_calc_bs_delta_call_atm(self):
        """Test call delta at-the-money is around 0.5."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=True,
        )
        delta = calc_bs_delta(params)
        assert delta is not None
        # ATM call delta should be slightly above 0.5 due to drift
        assert 0.5 <= delta <= 0.65

    def test_calc_bs_delta_put_atm(self):
        """Test put delta at-the-money is around -0.5."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=1.0,
            is_call=False,
        )
        delta = calc_bs_delta(params)
        assert delta is not None
        # ATM put delta should be around -0.35 to -0.5 (due to drift effect)
        assert -0.3 >= delta >= -0.55

    def test_calc_bs_delta_itm_call(self):
        """Test deep ITM call delta approaches 1."""
        params = BSParams(
            spot_price=150.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.1,
            is_call=True,
        )
        delta = calc_bs_delta(params)
        assert delta is not None
        assert delta > 0.95

    def test_calc_bs_delta_otm_put(self):
        """Test OTM put delta is small negative."""
        params = BSParams(
            spot_price=150.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.1,
            is_call=False,
        )
        delta = calc_bs_delta(params)
        assert delta is not None
        assert -0.1 < delta < 0

    def test_calc_bs_gamma_positive(self):
        """Test gamma is always positive."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
        )
        gamma = calc_bs_gamma(params)
        assert gamma is not None
        assert gamma > 0

    def test_calc_bs_gamma_atm_highest(self):
        """Test gamma is highest at-the-money."""
        atm = BSParams(spot_price=100.0, strike_price=100.0, risk_free_rate=0.05,
                       volatility=0.20, time_to_expiry=0.25)
        itm = BSParams(spot_price=100.0, strike_price=80.0, risk_free_rate=0.05,
                       volatility=0.20, time_to_expiry=0.25)
        otm = BSParams(spot_price=100.0, strike_price=120.0, risk_free_rate=0.05,
                       volatility=0.20, time_to_expiry=0.25)

        gamma_atm = calc_bs_gamma(atm)
        gamma_itm = calc_bs_gamma(itm)
        gamma_otm = calc_bs_gamma(otm)

        assert gamma_atm > gamma_itm
        assert gamma_atm > gamma_otm

    def test_calc_bs_theta_negative_for_long(self):
        """Test theta is typically negative for long options."""
        call_params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
            is_call=True,
        )
        put_params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
            is_call=False,
        )
        theta_call = calc_bs_theta(call_params)
        theta_put = calc_bs_theta(put_params)
        assert theta_call is not None
        assert theta_put is not None
        # Both should be negative (time decay)
        assert theta_call < 0
        assert theta_put < 0

    def test_calc_bs_vega_positive(self):
        """Test vega is always positive."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
        )
        vega = calc_bs_vega(params)
        assert vega is not None
        assert vega > 0

    def test_calc_bs_rho_call_positive(self):
        """Test call rho is positive."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
            is_call=True,
        )
        rho = calc_bs_rho(params)
        assert rho is not None
        assert rho > 0

    def test_calc_bs_rho_put_negative(self):
        """Test put rho is negative."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
            is_call=False,
        )
        rho = calc_bs_rho(params)
        assert rho is not None
        assert rho < 0

    def test_calc_bs_greeks_all(self):
        """Test calculating all Greeks at once."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.20,
            time_to_expiry=0.25,
            is_call=True,
        )
        greeks = calc_bs_greeks(params)
        assert greeks["delta"] is not None
        assert greeks["gamma"] is not None
        assert greeks["theta"] is not None
        assert greeks["vega"] is not None
        assert greeks["rho"] is not None

    def test_calc_bs_greeks_invalid_inputs(self):
        """Test Greeks return None for invalid inputs."""
        invalid_params = [
            BSParams(spot_price=0, strike_price=100, risk_free_rate=0.05, volatility=0.20, time_to_expiry=0.25),
            BSParams(spot_price=100, strike_price=0, risk_free_rate=0.05, volatility=0.20, time_to_expiry=0.25),
            BSParams(spot_price=100, strike_price=100, risk_free_rate=0.05, volatility=0, time_to_expiry=0.25),
            BSParams(spot_price=100, strike_price=100, risk_free_rate=0.05, volatility=0.20, time_to_expiry=0),
        ]
        for params in invalid_params:
            assert calc_bs_delta(params) is None


class TestGreeksExtraction:
    """Tests for Greeks extraction with fallback."""

    @pytest.fixture
    def call_contract(self):
        """Create a sample call option contract."""
        # Use future date (180 days from today)
        expiry = date.today() + timedelta(days=180)
        return OptionContract(
            symbol="AAPL230120C00150000",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=150.0,
            expiry_date=expiry,
        )

    @pytest.fixture
    def put_contract(self):
        """Create a sample put option contract."""
        # Use future date (180 days from today)
        expiry = date.today() + timedelta(days=180)
        return OptionContract(
            symbol="AAPL230120P00150000",
            underlying="AAPL",
            option_type=OptionType.PUT,
            strike_price=150.0,
            expiry_date=expiry,
        )

    def test_get_greeks_from_quote(self, call_contract):
        """Test extracting Greeks when available in quote."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            last_price=5.0,
            iv=0.25,
            greeks=Greeks(delta=0.55, gamma=0.02, theta=-0.05, vega=0.30, rho=0.10),
        )
        greeks = get_greeks(quote)
        assert greeks is not None
        assert greeks.delta == 0.55
        assert greeks.gamma == 0.02
        assert greeks.theta == -0.05

    def test_get_greeks_fallback_calculation(self, call_contract):
        """Test fallback calculation when Greeks not available."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            last_price=5.0,
            iv=0.25,
            greeks=Greeks(),  # Empty Greeks
        )
        greeks = get_greeks(quote, spot_price=150.0)
        assert greeks is not None
        assert greeks.delta is not None
        assert greeks.gamma is not None
        # ATM call delta should be around 0.5
        assert 0.4 <= greeks.delta <= 0.7

    def test_get_delta_from_quote(self, call_contract):
        """Test extracting delta when available."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            greeks=Greeks(delta=0.55),
        )
        delta = get_delta(quote)
        assert delta == 0.55

    def test_get_delta_fallback(self, call_contract):
        """Test delta fallback calculation."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        delta = get_delta(quote, spot_price=150.0)
        assert delta is not None
        assert 0.3 <= delta <= 0.7  # Reasonable range for ATM

    def test_get_gamma_fallback(self, call_contract):
        """Test gamma fallback calculation."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        gamma = get_gamma(quote, spot_price=150.0)
        assert gamma is not None
        assert gamma > 0

    def test_get_theta_fallback(self, call_contract):
        """Test theta fallback calculation."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        theta = get_theta(quote, spot_price=150.0)
        assert theta is not None
        # Theta is typically negative (daily time decay)
        assert theta < 0

    def test_get_vega_fallback(self, call_contract):
        """Test vega fallback calculation."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        vega = get_vega(quote, spot_price=150.0)
        assert vega is not None
        assert vega > 0

    def test_get_rho_fallback(self, call_contract):
        """Test rho fallback calculation."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        rho = get_rho(quote, spot_price=150.0)
        assert rho is not None
        # Call rho should be positive
        assert rho > 0

    def test_fallback_requires_spot_price(self, call_contract):
        """Test fallback returns None without spot price."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        # No spot_price provided
        greeks = get_greeks(quote)
        # Should return empty Greeks since fallback can't run
        assert greeks.delta is None

    def test_fallback_requires_iv(self, call_contract):
        """Test fallback returns None without IV."""
        quote = OptionQuote(
            contract=call_contract,
            timestamp=datetime.now(),
            iv=None,  # No IV
            greeks=Greeks(),
        )
        delta = get_delta(quote, spot_price=150.0)
        assert delta is None

    def test_put_delta_negative(self, put_contract):
        """Test put delta is negative."""
        quote = OptionQuote(
            contract=put_contract,
            timestamp=datetime.now(),
            iv=0.25,
            greeks=Greeks(),
        )
        delta = get_delta(quote, spot_price=150.0)
        assert delta is not None
        assert delta < 0  # Put delta should be negative

    def test_none_quote(self):
        """Test handling None quote."""
        assert get_greeks(None) is None
        assert get_delta(None) is None
        assert get_gamma(None) is None
        assert get_theta(None) is None
        assert get_vega(None) is None
        assert get_rho(None) is None
