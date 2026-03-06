"""Tests for SyntheticLeapsProvider — B-S synthetic LEAPS option chain."""

import math
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.backtest.data.synthetic_leaps_provider import SyntheticLeapsProvider
from src.data.models import MacroData, StockQuote
from src.data.models.option import OptionType


# --- Fixtures ---


@pytest.fixture
def mock_base_provider():
    """Create a mock DuckDBProvider with stock/macro data."""
    provider = MagicMock()
    provider.name = "duckdb"
    provider.is_available = True
    provider._as_of_date = date(2024, 6, 15)

    # Stock quote: SPY at $500
    provider.get_stock_quote.return_value = StockQuote(
        symbol="SPY",
        timestamp=datetime(2024, 6, 15),
        open=498.0,
        high=502.0,
        low=497.0,
        close=500.0,
        volume=50_000_000,
        source="duckdb",
    )

    # VIX at 20
    provider.get_macro_data.side_effect = _mock_macro_data
    return provider


def _mock_macro_data(indicator: str, start_date: date, end_date: date):
    """Return mock macro data based on indicator."""
    if indicator == "^VIX":
        return [
            MacroData(indicator="^VIX", date=end_date, value=20.0, source="mock")
        ]
    elif indicator == "^TNX":
        return [
            MacroData(indicator="^TNX", date=end_date, value=4.5, source="mock")
        ]
    return []


@pytest.fixture
def provider(mock_base_provider):
    """Create SyntheticLeapsProvider wrapping mock base."""
    return SyntheticLeapsProvider(mock_base_provider, dividend_yield=0.013)


# --- IV Estimation Tests ---


class TestIVEstimation:
    """Test IV estimation from VIX."""

    def test_atm_short_dated(self, provider):
        """ATM, short DTE: IV should be close to VIX."""
        iv = provider._estimate_iv(vix=0.20, dte=30, moneyness=1.0)
        # Short DTE, ATM: should be close to VIX but slightly reduced
        assert 0.17 < iv < 0.21

    def test_atm_long_dated(self, provider):
        """ATM, long DTE: IV should be lower than VIX (term structure)."""
        iv_30 = provider._estimate_iv(vix=0.20, dte=30, moneyness=1.0)
        iv_365 = provider._estimate_iv(vix=0.20, dte=365, moneyness=1.0)
        # Long-dated IV < short-dated IV (term structure decay)
        assert iv_365 < iv_30

    def test_deep_itm_skew(self, provider):
        """Deep ITM call (low moneyness) should have higher IV than ATM."""
        iv_atm = provider._estimate_iv(vix=0.20, dte=365, moneyness=1.0)
        iv_itm = provider._estimate_iv(vix=0.20, dte=365, moneyness=0.85)
        # ITM call → put-call parity → OTM put equivalent, skew pushes IV up
        assert iv_itm > iv_atm

    def test_otm_has_lower_iv(self, provider):
        """OTM call (high moneyness) should have slightly lower IV."""
        iv_atm = provider._estimate_iv(vix=0.20, dte=365, moneyness=1.0)
        iv_otm = provider._estimate_iv(vix=0.20, dte=365, moneyness=1.10)
        # OTM call: negative skew → lower IV
        assert iv_otm < iv_atm

    def test_term_structure_convergence(self, provider):
        """Term structure decay should converge (not diverge) for very long DTE."""
        iv_1y = provider._estimate_iv(vix=0.20, dte=365, moneyness=1.0)
        iv_2y = provider._estimate_iv(vix=0.20, dte=730, moneyness=1.0)
        # 2Y IV should be only slightly lower than 1Y (asymptotic decay)
        diff = iv_1y - iv_2y
        assert 0 < diff < 0.02  # Less than 2% further decay

    def test_high_vix_scales(self, provider):
        """Higher VIX should produce proportionally higher IV."""
        iv_low = provider._estimate_iv(vix=0.15, dte=365, moneyness=0.85)
        iv_high = provider._estimate_iv(vix=0.30, dte=365, moneyness=0.85)
        assert iv_high > iv_low
        # Should roughly double (proportional to VIX)
        assert 1.8 < (iv_high / iv_low) < 2.2


# --- Expiry Generation Tests ---


class TestExpiryGeneration:
    """Test monthly 3rd Friday expiry generation."""

    def test_third_friday_calculation(self):
        """Verify 3rd Friday is correct."""
        # June 2024: 3rd Friday is June 21
        assert SyntheticLeapsProvider._third_friday(2024, 6) == date(2024, 6, 21)
        # January 2025: 3rd Friday is January 17
        assert SyntheticLeapsProvider._third_friday(2025, 1) == date(2025, 1, 17)
        # December 2024: 3rd Friday is December 20
        assert SyntheticLeapsProvider._third_friday(2024, 12) == date(2024, 12, 20)

    def test_generate_monthly_expiries(self, provider):
        """Generate expiries within a date range."""
        as_of = date(2024, 6, 15)
        expiry_start = date(2024, 12, 1)
        expiry_end = date(2025, 6, 30)

        expiries = provider._generate_monthly_expiries(as_of, expiry_start, expiry_end)

        # Should have ~7 months of expiries (Dec 2024 through Jun 2025)
        assert len(expiries) >= 6
        assert len(expiries) <= 8

        # All should be after as_of and within range
        for exp in expiries:
            assert exp > as_of
            assert expiry_start <= exp <= expiry_end

        # All should be Fridays (weekday=4)
        for exp in expiries:
            assert exp.weekday() == 4, f"{exp} is not a Friday"

    def test_empty_range(self, provider):
        """No expiries when range is before as_of_date."""
        as_of = date(2024, 6, 15)
        expiries = provider._generate_monthly_expiries(
            as_of, date(2024, 1, 1), date(2024, 3, 1)
        )
        assert expiries == []


# --- Strike Grid Tests ---


class TestStrikeGrid:
    """Test strike price grid generation."""

    def test_strike_grid_500(self, provider):
        """spot=500 → strikes from ~350 to ~575 with $5 increments."""
        strikes = provider._generate_strike_grid(500.0)
        assert len(strikes) >= 8
        assert min(strikes) >= 300
        assert max(strikes) <= 600
        # All should be multiples of $5 (spot >= 200)
        for s in strikes:
            assert s % 5 == 0, f"Strike {s} not a multiple of $5"

    def test_strike_grid_30(self, provider):
        """spot=30 → strikes with $1 increments."""
        strikes = provider._generate_strike_grid(30.0)
        for s in strikes:
            assert s % 1 == 0, f"Strike {s} not a multiple of $1"

    def test_strike_grid_100(self, provider):
        """spot=100 → strikes with $2.5 increments."""
        strikes = provider._generate_strike_grid(100.0)
        for s in strikes:
            assert s % 2.5 == 0, f"Strike {s} not a multiple of $2.5"

    def test_strikes_are_sorted(self, provider):
        """Strikes should be sorted ascending."""
        strikes = provider._generate_strike_grid(500.0)
        assert strikes == sorted(strikes)

    def test_no_duplicate_strikes(self, provider):
        """No duplicate strikes after rounding."""
        strikes = provider._generate_strike_grid(500.0)
        assert len(strikes) == len(set(strikes))


# --- Synthetic Chain Generation Tests ---


class TestSyntheticChain:
    """Test full synthetic option chain generation."""

    def test_chain_structure(self, provider):
        """Synthetic chain has correct structure."""
        chain = provider.get_option_chain(
            "SPY",
            expiry_min_days=180,
            expiry_max_days=400,
        )

        assert chain is not None
        assert chain.underlying == "SPY"
        assert chain.source == "synthetic_bs"
        assert len(chain.calls) > 0
        assert len(chain.puts) == 0  # LEAPS only generates calls
        assert len(chain.expiry_dates) > 0

    def test_quote_fields(self, provider):
        """Each OptionQuote has all required fields populated."""
        chain = provider.get_option_chain(
            "SPY",
            expiry_min_days=180,
            expiry_max_days=400,
        )

        for quote in chain.calls:
            assert quote.contract.underlying == "SPY"
            assert quote.contract.option_type == OptionType.CALL
            assert quote.contract.strike_price > 0
            assert quote.contract.expiry_date > date(2024, 6, 15)
            assert quote.contract.lot_size == 100

            assert quote.last_price is not None and quote.last_price > 0
            assert quote.bid is not None and quote.bid > 0
            assert quote.ask is not None and quote.ask > 0
            assert quote.bid <= quote.ask
            assert quote.iv is not None and quote.iv > 0

            # Greeks should be populated
            assert quote.greeks.delta is not None
            assert quote.greeks.gamma is not None
            assert quote.greeks.theta is not None
            assert quote.greeks.vega is not None

    def test_deep_itm_leaps_call(self, provider):
        """Deep ITM LEAPS call: delta ≈ 0.8-0.9, price >> 0."""
        chain = provider.get_option_chain(
            "SPY",
            expiry_min_days=300,
            expiry_max_days=400,
        )

        # Find a deep ITM call (strike ≈ 85% of spot=500 → ~425)
        deep_itm = [
            q for q in chain.calls
            if q.contract.strike_price <= 430
        ]
        assert len(deep_itm) > 0

        for q in deep_itm:
            assert q.greeks.delta > 0.7, f"Delta={q.greeks.delta} too low for deep ITM"
            assert q.last_price > 50, f"Price={q.last_price} too low for deep ITM LEAPS"

    def test_otm_call_low_delta(self, provider):
        """OTM LEAPS call should have low delta."""
        chain = provider.get_option_chain(
            "SPY",
            expiry_min_days=300,
            expiry_max_days=400,
        )

        otm = [q for q in chain.calls if q.contract.strike_price >= 550]
        assert len(otm) > 0
        for q in otm:
            assert q.greeks.delta < 0.5, f"Delta={q.greeks.delta} too high for OTM"

    def test_no_stock_quote_returns_none(self, mock_base_provider):
        """If no stock quote available, returns None."""
        mock_base_provider.get_stock_quote.return_value = None
        provider = SyntheticLeapsProvider(mock_base_provider)
        chain = provider.get_option_chain("SPY", expiry_min_days=180, expiry_max_days=400)
        assert chain is None


# --- Dividend Adjustment Tests ---


class TestDividendAdjustment:
    """Test dividend yield impact on pricing."""

    def test_dividend_lowers_call_price(self, mock_base_provider):
        """Higher dividend yield → lower call price."""
        p_no_div = SyntheticLeapsProvider(mock_base_provider, dividend_yield=0.0)
        p_with_div = SyntheticLeapsProvider(mock_base_provider, dividend_yield=0.03)

        chain_no_div = p_no_div.get_option_chain("SPY", expiry_min_days=300, expiry_max_days=400)
        chain_with_div = p_with_div.get_option_chain("SPY", expiry_min_days=300, expiry_max_days=400)

        # Match by strike/expiry and compare prices
        prices_no_div = {
            (q.contract.strike_price, q.contract.expiry_date): q.last_price
            for q in chain_no_div.calls
        }

        for q in chain_with_div.calls:
            key = (q.contract.strike_price, q.contract.expiry_date)
            if key in prices_no_div:
                assert q.last_price < prices_no_div[key], (
                    f"Dividend should lower call price: "
                    f"strike={key[0]}, no_div={prices_no_div[key]:.2f}, "
                    f"with_div={q.last_price:.2f}"
                )


# --- Delegation Tests ---


class TestDelegation:
    """Test that non-option-chain methods delegate to base provider."""

    def test_set_as_of_date(self, provider, mock_base_provider):
        provider.set_as_of_date(date(2024, 7, 1))
        mock_base_provider.set_as_of_date.assert_called_once_with(date(2024, 7, 1))

    def test_get_stock_quote(self, provider, mock_base_provider):
        provider.get_stock_quote("AAPL")
        mock_base_provider.get_stock_quote.assert_called_with("AAPL")

    def test_get_history_kline(self, provider, mock_base_provider):
        from src.data.models.stock import KlineType
        provider.get_history_kline("SPY", KlineType.DAY, date(2024, 1, 1), date(2024, 6, 1))
        mock_base_provider.get_history_kline.assert_called_once()

    def test_get_macro_data(self, provider, mock_base_provider):
        provider.get_macro_data("^VIX", date(2024, 1, 1), date(2024, 6, 1))
        mock_base_provider.get_macro_data.assert_called_with(
            "^VIX", date(2024, 1, 1), date(2024, 6, 1)
        )

    def test_get_trading_days(self, provider, mock_base_provider):
        mock_base_provider.get_trading_days.return_value = [date(2024, 6, 14), date(2024, 6, 15)]
        result = provider.get_trading_days(date(2024, 6, 14), date(2024, 6, 15))
        mock_base_provider.get_trading_days.assert_called_once()

    def test_name_property(self, provider):
        assert "synthetic_leaps" in provider.name
        assert "duckdb" in provider.name

    def test_is_available(self, provider):
        assert provider.is_available is True


# --- Spread Estimation Tests ---


class TestSpreadEstimation:
    """Test bid-ask spread estimation."""

    def test_atm_tighter_than_otm(self, provider):
        spread_atm = provider._estimate_spread(price=20.0, moneyness=1.0, dte=365)
        spread_otm = provider._estimate_spread(price=5.0, moneyness=1.10, dte=365)
        # OTM spread as % of price should be wider
        assert (spread_otm / 5.0) > (spread_atm / 20.0)

    def test_longer_dte_wider_spread(self, provider):
        spread_short = provider._estimate_spread(price=20.0, moneyness=1.0, dte=30)
        spread_long = provider._estimate_spread(price=20.0, moneyness=1.0, dte=365)
        assert spread_long > spread_short

    def test_minimum_spread(self, provider):
        spread = provider._estimate_spread(price=0.10, moneyness=1.0, dte=30)
        assert spread >= 0.05


# --- VIX/TNX Fallback Tests ---


class TestMacroFallbacks:
    """Test fallback behavior when macro data is missing."""

    def test_missing_vix_uses_default(self, mock_base_provider):
        mock_base_provider.get_macro_data.return_value = []
        provider = SyntheticLeapsProvider(mock_base_provider)
        vix = provider._get_vix(date(2024, 6, 15))
        assert vix == 0.20  # default

    def test_missing_tnx_uses_default(self, mock_base_provider):
        mock_base_provider.get_macro_data.side_effect = None
        mock_base_provider.get_macro_data.return_value = []
        provider = SyntheticLeapsProvider(mock_base_provider)
        rate = provider._get_risk_free_rate(date(2024, 6, 15))
        assert rate == 0.04  # default


# --- Caching Tests ---


class TestCaching:
    """Test that per-day caching avoids redundant B-S computation."""

    def test_multiple_calls_same_day_reuse_cache(self, provider, mock_base_provider):
        """Multiple get_option_chain calls on same day should hit cache."""
        # First call — triggers generation
        chain1 = provider.get_option_chain("SPY", expiry_min_days=180, expiry_max_days=400)
        # Second call with different expiry range — should reuse cached full chain
        chain2 = provider.get_option_chain("SPY", expiry_min_days=300, expiry_max_days=400)

        assert chain1 is not None
        assert chain2 is not None
        # Second call should have fewer contracts (narrower range)
        assert len(chain2.calls) <= len(chain1.calls)

        # get_stock_quote should only be called once (for the first build)
        # (Plus once from the macro mock setup side-effect, so check it's cached)
        stock_call_count = mock_base_provider.get_stock_quote.call_count
        assert stock_call_count == 1, f"Expected 1 stock quote call, got {stock_call_count}"

    def test_cache_cleared_on_date_change(self, provider, mock_base_provider):
        """set_as_of_date should clear the chain cache."""
        # Build cache
        provider.get_option_chain("SPY", expiry_min_days=180, expiry_max_days=400)
        assert len(provider._chain_cache) == 1

        # Change date
        provider.set_as_of_date(date(2024, 6, 16))
        assert len(provider._chain_cache) == 0

    def test_vix_tnx_cached_per_date(self, provider):
        """VIX/TNX lookups should be cached per date."""
        d = date(2024, 6, 15)
        v1 = provider._get_vix(d)
        v2 = provider._get_vix(d)
        assert v1 == v2
        assert d in provider._vix_cache
