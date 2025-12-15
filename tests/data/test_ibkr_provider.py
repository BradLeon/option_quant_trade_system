"""Tests for IBKR TWS API provider."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.data.models.option import Greeks, OptionContract, OptionType
from src.data.models.stock import KlineType


# Mock ib_async before importing IBKRProvider
@pytest.fixture(autouse=True)
def mock_ib_async():
    """Mock ib_async module."""
    with patch.dict("sys.modules", {"ib_async": MagicMock()}):
        yield


class TestIBKRProviderInit:
    """Tests for IBKRProvider initialization."""

    def test_default_init(self):
        """Test default initialization."""
        import os
        # Remove environment variables to test true defaults
        env_backup = {}
        for key in ["IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID"]:
            if key in os.environ:
                env_backup[key] = os.environ.pop(key)
        try:
            # Mock load_dotenv to prevent loading .env file
            with patch("src.data.providers.ibkr_provider.load_dotenv"):
                with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
                    from src.data.providers.ibkr_provider import IBKRProvider

                    provider = IBKRProvider()
                    assert provider.name == "ibkr"
                    assert provider._host == "127.0.0.1"
                    assert provider._port == 7497
                    assert provider._client_id == 1
        finally:
            # Restore environment variables
            os.environ.update(env_backup)

    def test_custom_init(self):
        """Test initialization with custom parameters."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider(host="192.168.1.1", port=7496, client_id=2)
            assert provider._host == "192.168.1.1"
            assert provider._port == 7496
            assert provider._client_id == 2

    def test_is_available_false_when_not_connected(self):
        """Test is_available returns False when not connected."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            assert provider.is_available is False


class TestIBKRProviderNormalize:
    """Tests for symbol normalization."""

    def test_normalize_simple_symbol(self):
        """Test normalizing simple symbol."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            assert provider.normalize_symbol("aapl") == "AAPL"
            assert provider.normalize_symbol("MSFT") == "MSFT"

    def test_normalize_symbol_with_prefix(self):
        """Test normalizing symbol with market prefix."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            assert provider.normalize_symbol("US.AAPL") == "AAPL"
            assert provider.normalize_symbol("us.msft") == "MSFT"


class TestIBKRProviderWithMock:
    """Tests for IBKRProvider with mocked IB connection."""

    @pytest.fixture
    def mock_ib(self):
        """Create mock IB instance."""
        mock = MagicMock()
        mock.isConnected.return_value = True
        return mock

    @pytest.fixture
    def provider_with_mock(self, mock_ib):
        """Create provider with mocked IB."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            with patch("src.data.providers.ibkr_provider.IB", return_value=mock_ib):
                from src.data.providers.ibkr_provider import IBKRProvider

                provider = IBKRProvider()
                provider._ib = mock_ib
                provider._connected = True
                return provider

    def test_get_stock_quote(self, provider_with_mock, mock_ib):
        """Test getting stock quote."""
        # Setup mock ticker
        mock_ticker = MagicMock()
        mock_ticker.last = 150.0
        mock_ticker.open = 148.0
        mock_ticker.high = 152.0
        mock_ticker.low = 147.0
        mock_ticker.close = 149.0
        mock_ticker.volume = 1000000
        mock_ticker.bid = 149.9
        mock_ticker.ask = 150.1

        mock_ib.qualifyContracts.return_value = [MagicMock()]
        mock_ib.reqMktData.return_value = mock_ticker
        mock_ib.sleep.return_value = None
        mock_ib.cancelMktData.return_value = None

        quote = provider_with_mock.get_stock_quote("AAPL")

        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.close == 150.0
        assert quote.volume == 1000000
        assert quote.source == "ibkr"
        # bid/ask stored as private attributes
        assert quote._bid == 149.9
        assert quote._ask == 150.1

    def test_get_stock_quotes_multiple(self, provider_with_mock, mock_ib):
        """Test getting multiple stock quotes."""
        mock_ticker1 = MagicMock()
        mock_ticker1.last = 150.0
        mock_ticker1.open = 148.0
        mock_ticker1.high = 152.0
        mock_ticker1.low = 147.0
        mock_ticker1.close = 149.0
        mock_ticker1.volume = 1000000
        mock_ticker1.bid = 149.9
        mock_ticker1.ask = 150.1

        mock_ticker2 = MagicMock()
        mock_ticker2.last = 300.0
        mock_ticker2.open = 298.0
        mock_ticker2.high = 305.0
        mock_ticker2.low = 297.0
        mock_ticker2.close = 299.0
        mock_ticker2.volume = 500000
        mock_ticker2.bid = 299.9
        mock_ticker2.ask = 300.1

        mock_ib.qualifyContracts.return_value = [MagicMock()]
        mock_ib.reqMktData.side_effect = [mock_ticker1, mock_ticker2]
        mock_ib.sleep.return_value = None
        mock_ib.cancelMktData.return_value = None

        quotes = provider_with_mock.get_stock_quotes(["AAPL", "MSFT"])

        assert len(quotes) == 2
        assert quotes[0].symbol == "AAPL"
        assert quotes[1].symbol == "MSFT"

    def test_get_history_kline(self, provider_with_mock, mock_ib):
        """Test getting historical K-line data."""
        mock_bar1 = MagicMock()
        mock_bar1.date = datetime(2024, 1, 15)
        mock_bar1.open = 148.0
        mock_bar1.high = 152.0
        mock_bar1.low = 147.0
        mock_bar1.close = 150.0
        mock_bar1.volume = 1000000

        mock_bar2 = MagicMock()
        mock_bar2.date = datetime(2024, 1, 16)
        mock_bar2.open = 150.0
        mock_bar2.high = 155.0
        mock_bar2.low = 149.0
        mock_bar2.close = 154.0
        mock_bar2.volume = 1200000

        mock_ib.qualifyContracts.return_value = [MagicMock()]
        mock_ib.reqHistoricalData.return_value = [mock_bar1, mock_bar2]

        klines = provider_with_mock.get_history_kline(
            "AAPL",
            KlineType.DAY,
            date(2024, 1, 15),
            date(2024, 1, 16),
        )

        assert len(klines) == 2
        assert klines[0].symbol == "AAPL"
        assert klines[0].close == 150.0
        assert klines[1].close == 154.0
        assert klines[0].ktype == KlineType.DAY

    def test_get_option_chain(self, provider_with_mock, mock_ib):
        """Test getting option chain with configurable filters."""
        # Mock stock contract
        mock_stock = MagicMock()
        mock_stock.symbol = "AAPL"
        mock_stock.secType = "STK"
        mock_stock.conId = 12345

        # Mock option chain
        mock_chain = MagicMock()
        mock_chain.exchange = "SMART"
        mock_chain.expirations = ["20240120", "20240217", "20240315"]
        mock_chain.strikes = [140.0, 145.0, 150.0, 155.0, 160.0]

        # Mock ticker for underlying price
        mock_ticker = MagicMock()
        mock_ticker.last = 150.0
        mock_ticker.close = 150.0

        mock_ib.qualifyContracts.return_value = [mock_stock]
        mock_ib.reqSecDefOptParams.return_value = [mock_chain]
        mock_ib.reqMktData.return_value = mock_ticker
        mock_ib.sleep.return_value = None
        mock_ib.cancelMktData.return_value = None

        # Disable default expiry_min_days/expiry_max_days to use explicit date range
        chain = provider_with_mock.get_option_chain(
            "AAPL",
            expiry_start=date(2024, 1, 1),
            expiry_end=date(2024, 3, 31),
            expiry_min_days=None,  # Disable default
            expiry_max_days=None,  # Disable default
            strike_range_pct=0.10,
        )

        assert chain is not None
        assert chain.underlying == "AAPL"
        assert len(chain.expiry_dates) > 0
        assert len(chain.calls) > 0
        assert len(chain.puts) > 0

    def test_get_option_chain_with_strike_filter(self, provider_with_mock, mock_ib):
        """Test getting option chain with strike price filter."""
        mock_stock = MagicMock()
        mock_stock.symbol = "AAPL"
        mock_stock.secType = "STK"
        mock_stock.conId = 12345

        mock_chain = MagicMock()
        mock_chain.exchange = "SMART"
        mock_chain.expirations = ["20240120"]
        mock_chain.strikes = [140.0, 145.0, 150.0, 155.0, 160.0]

        mock_ticker = MagicMock()
        mock_ticker.last = 150.0
        mock_ticker.close = 150.0

        mock_ib.qualifyContracts.return_value = [mock_stock]
        mock_ib.reqSecDefOptParams.return_value = [mock_chain]
        mock_ib.reqMktData.return_value = mock_ticker
        mock_ib.sleep.return_value = None
        mock_ib.cancelMktData.return_value = None

        # Test strike_min/max filter with explicit date range
        chain = provider_with_mock.get_option_chain(
            "AAPL",
            expiry_start=date(2024, 1, 1),
            expiry_end=date(2024, 3, 31),
            expiry_min_days=None,  # Disable default
            expiry_max_days=None,  # Disable default
            strike_range_pct=None,  # Disable percentage range
            strike_min=145.0,
            strike_max=155.0,
        )

        assert chain is not None
        # Should only include strikes 145, 150, 155
        for call in chain.calls:
            assert 145.0 <= call.contract.strike_price <= 155.0
        for put in chain.puts:
            assert 145.0 <= put.contract.strike_price <= 155.0

    def test_get_option_quote_with_greeks(self, provider_with_mock, mock_ib):
        """Test getting option quote with Greeks."""
        mock_greeks = MagicMock()
        mock_greeks.delta = 0.55
        mock_greeks.gamma = 0.05
        mock_greeks.theta = -0.02
        mock_greeks.vega = 0.15
        mock_greeks.impliedVol = 0.25

        mock_ticker = MagicMock()
        mock_ticker.last = 5.50
        mock_ticker.bid = 5.40
        mock_ticker.ask = 5.60
        mock_ticker.volume = 1000
        mock_ticker.modelGreeks = mock_greeks

        mock_ib.qualifyContracts.return_value = [MagicMock()]
        mock_ib.reqMktData.return_value = mock_ticker
        mock_ib.sleep.return_value = None

        quote = provider_with_mock.get_option_quote("AAPL20240120C00150000")

        assert quote is not None
        assert quote.contract.underlying == "AAPL"
        assert quote.contract.option_type == OptionType.CALL
        assert quote.contract.strike_price == 150.0
        assert quote.last_price == 5.50
        assert quote.greeks is not None
        assert quote.greeks.delta == 0.55
        assert quote.iv == 0.25


class TestIBKRProviderParseOptionSymbol:
    """Tests for option symbol parsing."""

    def test_parse_option_symbol_standard(self):
        """Test parsing standard option symbol."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            contract = provider._parse_option_symbol("AAPL20240120C00150000")

            assert contract is not None
            assert contract.underlying == "AAPL"
            assert contract.option_type == OptionType.CALL
            assert contract.strike_price == 150.0
            assert contract.expiry_date == date(2024, 1, 20)

    def test_parse_option_symbol_put(self):
        """Test parsing put option symbol."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            contract = provider._parse_option_symbol("MSFT20240215P00400000")

            assert contract is not None
            assert contract.underlying == "MSFT"
            assert contract.option_type == OptionType.PUT
            assert contract.strike_price == 400.0
            assert contract.expiry_date == date(2024, 2, 15)

    def test_parse_option_symbol_fractional_strike(self):
        """Test parsing option symbol with fractional strike."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            contract = provider._parse_option_symbol("SPY20240119C00475500")

            assert contract is not None
            assert contract.strike_price == 475.5


class TestIBKRProviderConnectionManagement:
    """Tests for connection management."""

    def test_health_check_when_disconnected(self):
        """Test health check returns False when disconnected."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            assert provider.health_check() is False

    def test_health_check_when_connected(self):
        """Test health check returns True when connected."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider()
            provider._connected = True
            provider._ib = MagicMock()
            provider._ib.reqCurrentTime.return_value = datetime.now()

            assert provider.health_check() is True

    def test_context_manager(self):
        """Test context manager calls connect and disconnect."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            with patch("src.data.providers.ibkr_provider.IB") as mock_ib_class:
                mock_ib = MagicMock()
                mock_ib_class.return_value = mock_ib

                from src.data.providers.ibkr_provider import IBKRProvider

                with IBKRProvider() as provider:
                    assert provider._connected is True

                mock_ib.disconnect.assert_called_once()


class TestKlineTypeMapping:
    """Tests for K-line type mapping."""

    def test_kline_type_map_exists(self):
        """Test all K-line types have mappings."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import KLINE_TYPE_MAP

            assert KlineType.DAY in KLINE_TYPE_MAP
            assert KlineType.MIN_1 in KLINE_TYPE_MAP
            assert KlineType.MIN_5 in KLINE_TYPE_MAP
            assert KlineType.WEEK in KLINE_TYPE_MAP

    def test_kline_type_map_values(self):
        """Test K-line type map has correct IBKR values."""
        with patch("src.data.providers.ibkr_provider.IBKR_AVAILABLE", True):
            from src.data.providers.ibkr_provider import KLINE_TYPE_MAP

            assert KLINE_TYPE_MAP[KlineType.DAY] == "1 day"
            assert KLINE_TYPE_MAP[KlineType.MIN_1] == "1 min"
            assert KLINE_TYPE_MAP[KlineType.WEEK] == "1 week"
