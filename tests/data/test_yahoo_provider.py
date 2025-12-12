"""Tests for Yahoo Finance provider."""

from datetime import date, timedelta

import pytest

from src.data.models.stock import KlineType
from src.data.providers.yahoo_provider import YahooProvider


class TestYahooProvider:
    """Tests for Yahoo Finance provider."""

    @pytest.fixture
    def provider(self):
        """Create Yahoo provider instance."""
        return YahooProvider(rate_limit=0.1)

    def test_is_available(self, provider):
        """Test that Yahoo provider is always available."""
        assert provider.is_available is True

    def test_name(self, provider):
        """Test provider name."""
        assert provider.name == "yahoo"

    def test_normalize_symbol(self, provider):
        """Test symbol normalization."""
        # US symbols
        assert provider.normalize_symbol("AAPL") == "AAPL"
        assert provider.normalize_symbol("US.AAPL") == "AAPL"

        # HK symbols
        assert provider.normalize_symbol("HK.00700") == "00700.HK"

    @pytest.mark.integration
    def test_get_stock_quote(self, provider):
        """Test getting stock quote (requires internet)."""
        quote = provider.get_stock_quote("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.close is not None
        assert quote.close > 0

    @pytest.mark.integration
    def test_get_history_kline(self, provider):
        """Test getting historical K-line data (requires internet)."""
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        klines = provider.get_history_kline(
            "AAPL",
            KlineType.DAY,
            start_date,
            end_date,
        )

        assert len(klines) > 0
        assert klines[0].symbol == "AAPL"
        assert klines[0].open > 0

    @pytest.mark.integration
    def test_get_fundamental(self, provider):
        """Test getting fundamental data (requires internet)."""
        fundamental = provider.get_fundamental("AAPL")

        assert fundamental is not None
        assert fundamental.symbol == "AAPL"
        assert fundamental.market_cap is not None
        assert fundamental.market_cap > 0

    @pytest.mark.integration
    def test_get_macro_data(self, provider):
        """Test getting macro data (requires internet)."""
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        macro_data = provider.get_macro_data("^VIX", start_date, end_date)

        assert len(macro_data) > 0
        assert macro_data[0].indicator == "^VIX"

    @pytest.mark.integration
    def test_get_option_chain(self, provider):
        """Test getting option chain (requires internet)."""
        chain = provider.get_option_chain("AAPL")

        assert chain is not None
        assert chain.underlying == "AAPL"
        assert len(chain.expiry_dates) > 0
        assert len(chain.calls) > 0 or len(chain.puts) > 0
