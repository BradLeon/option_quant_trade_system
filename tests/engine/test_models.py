"""Tests for engine layer data models."""

from datetime import date, datetime

import pytest

from src.data.models import MacroData, OptionContract, OptionQuote, StockQuote
from src.data.models.option import Greeks, OptionType
from src.engine.models import BSParams


class TestBSParams:
    """Tests for BSParams dataclass."""

    def test_basic_creation(self):
        """Test basic BSParams creation."""
        params = BSParams(
            spot_price=100.0,
            strike_price=105.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=True,
        )

        assert params.spot_price == 100.0
        assert params.strike_price == 105.0
        assert params.risk_free_rate == 0.05
        assert params.volatility == 0.25
        assert params.time_to_expiry == 0.5
        assert params.is_call is True

    def test_default_is_call(self):
        """Test that is_call defaults to True."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
        )

        assert params.is_call is True

    def test_put_option(self):
        """Test BSParams for put option."""
        params = BSParams(
            spot_price=100.0,
            strike_price=95.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=False,
        )

        assert params.is_call is False


class TestBSParamsFromOptionQuote:
    """Tests for BSParams.from_option_quote factory method."""

    @pytest.fixture
    def sample_call_quote(self) -> OptionQuote:
        """Create a sample call option quote."""
        contract = OptionContract(
            symbol="AAPL240119C00190000",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=190.0,
            expiry_date=date.today(),  # Today for predictable days_to_expiry
            lot_size=100,
        )
        return OptionQuote(
            contract=contract,
            timestamp=datetime.now(),
            last_price=5.50,
            bid=5.40,
            ask=5.60,
            iv=0.28,
            greeks=Greeks(delta=0.45, gamma=0.02, theta=-0.05, vega=0.15),
        )

    @pytest.fixture
    def sample_put_quote(self) -> OptionQuote:
        """Create a sample put option quote."""
        contract = OptionContract(
            symbol="AAPL240119P00180000",
            underlying="AAPL",
            option_type=OptionType.PUT,
            strike_price=180.0,
            expiry_date=date.today(),
            lot_size=100,
        )
        return OptionQuote(
            contract=contract,
            timestamp=datetime.now(),
            last_price=3.20,
            iv=0.30,
        )

    def test_from_call_quote(self, sample_call_quote: OptionQuote):
        """Test creating BSParams from a call option quote."""
        params = BSParams.from_option_quote(
            quote=sample_call_quote,
            spot_price=185.0,
            risk_free_rate=0.05,
        )

        assert params.spot_price == 185.0
        assert params.strike_price == 190.0
        assert params.risk_free_rate == 0.05
        assert params.volatility == 0.28
        assert params.is_call is True
        # time_to_expiry should be 0 since expiry_date is today
        assert params.time_to_expiry == 0.0

    def test_from_put_quote(self, sample_put_quote: OptionQuote):
        """Test creating BSParams from a put option quote."""
        params = BSParams.from_option_quote(
            quote=sample_put_quote,
            spot_price=185.0,
        )

        assert params.strike_price == 180.0
        assert params.volatility == 0.30
        assert params.is_call is False
        assert params.risk_free_rate == 0.05  # default

    def test_from_quote_missing_iv(self):
        """Test that from_option_quote raises error when IV is missing."""
        contract = OptionContract(
            symbol="TEST",
            underlying="TEST",
            option_type=OptionType.CALL,
            strike_price=100.0,
            expiry_date=date.today(),
        )
        quote = OptionQuote(
            contract=contract,
            timestamp=datetime.now(),
            iv=None,  # No IV
        )

        with pytest.raises(ValueError, match="iv is required"):
            BSParams.from_option_quote(quote, spot_price=100.0)


class TestBSParamsValidation:
    """Tests for BSParams validation."""

    def test_validate_valid_params(self):
        """Test validation passes for valid parameters."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
        )

        assert params.validate() is True

    def test_validate_invalid_spot_price(self):
        """Test validation fails for non-positive spot price."""
        params = BSParams(
            spot_price=0.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
        )

        with pytest.raises(ValueError, match="spot_price must be positive"):
            params.validate()

    def test_validate_invalid_strike_price(self):
        """Test validation fails for non-positive strike price."""
        params = BSParams(
            spot_price=100.0,
            strike_price=-10.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
        )

        with pytest.raises(ValueError, match="strike_price must be positive"):
            params.validate()

    def test_validate_invalid_volatility(self):
        """Test validation fails for non-positive volatility."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.0,
            time_to_expiry=0.5,
        )

        with pytest.raises(ValueError, match="volatility must be positive"):
            params.validate()

    def test_validate_invalid_time_to_expiry(self):
        """Test validation fails for non-positive time to expiry."""
        params = BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.0,
        )

        with pytest.raises(ValueError, match="time_to_expiry must be positive"):
            params.validate()


class TestBSParamsProperties:
    """Tests for BSParams computed properties."""

    def test_moneyness_itm_call(self):
        """Test moneyness for ITM call."""
        params = BSParams(
            spot_price=110.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=True,
        )

        assert params.moneyness == 1.1
        assert params.is_itm is True
        assert params.is_otm is False

    def test_moneyness_otm_call(self):
        """Test moneyness for OTM call."""
        params = BSParams(
            spot_price=90.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=True,
        )

        assert params.moneyness == 0.9
        assert params.is_itm is False
        assert params.is_otm is True

    def test_moneyness_itm_put(self):
        """Test moneyness for ITM put."""
        params = BSParams(
            spot_price=90.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=False,
        )

        assert params.moneyness == 0.9
        assert params.is_itm is True  # Put is ITM when S < K
        assert params.is_otm is False

    def test_moneyness_otm_put(self):
        """Test moneyness for OTM put."""
        params = BSParams(
            spot_price=110.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=False,
        )

        assert params.moneyness == 1.1
        assert params.is_itm is False  # Put is OTM when S > K
        assert params.is_otm is True


class TestBSParamsWithMethods:
    """Tests for BSParams.with_* methods."""

    @pytest.fixture
    def base_params(self) -> BSParams:
        """Create base BSParams for testing."""
        return BSParams(
            spot_price=100.0,
            strike_price=100.0,
            risk_free_rate=0.05,
            volatility=0.25,
            time_to_expiry=0.5,
            is_call=True,
        )

    def test_with_spot(self, base_params: BSParams):
        """Test with_spot creates new params with different spot."""
        new_params = base_params.with_spot(110.0)

        assert new_params.spot_price == 110.0
        # Other values unchanged
        assert new_params.strike_price == 100.0
        assert new_params.volatility == 0.25
        assert new_params.time_to_expiry == 0.5
        # Original unchanged
        assert base_params.spot_price == 100.0

    def test_with_volatility(self, base_params: BSParams):
        """Test with_volatility creates new params with different volatility."""
        new_params = base_params.with_volatility(0.35)

        assert new_params.volatility == 0.35
        # Other values unchanged
        assert new_params.spot_price == 100.0
        assert new_params.strike_price == 100.0
        # Original unchanged
        assert base_params.volatility == 0.25

    def test_with_time(self, base_params: BSParams):
        """Test with_time creates new params with different time to expiry."""
        new_params = base_params.with_time(0.25)

        assert new_params.time_to_expiry == 0.25
        # Other values unchanged
        assert new_params.spot_price == 100.0
        assert new_params.volatility == 0.25
        # Original unchanged
        assert base_params.time_to_expiry == 0.5

    def test_chained_with_methods(self, base_params: BSParams):
        """Test chaining with_* methods."""
        new_params = (
            base_params.with_spot(110.0).with_volatility(0.30).with_time(0.25)
        )

        assert new_params.spot_price == 110.0
        assert new_params.volatility == 0.30
        assert new_params.time_to_expiry == 0.25
        # Original unchanged
        assert base_params.spot_price == 100.0
        assert base_params.volatility == 0.25
        assert base_params.time_to_expiry == 0.5


class TestBSParamsFromMarketData:
    """Tests for BSParams.from_market_data factory method."""

    @pytest.fixture
    def sample_option_quote(self) -> OptionQuote:
        """Create a sample option quote."""
        contract = OptionContract(
            symbol="AAPL240119C00190000",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=190.0,
            expiry_date=date.today(),
            lot_size=100,
        )
        return OptionQuote(
            contract=contract,
            timestamp=datetime.now(),
            iv=0.28,
        )

    @pytest.fixture
    def sample_stock_quote(self) -> StockQuote:
        """Create a sample stock quote for AAPL."""
        return StockQuote(
            symbol="AAPL",
            timestamp=datetime.now(),
            open=184.0,
            high=186.5,
            low=183.5,
            close=185.0,  # This is the spot price
            volume=50000000,
        )

    @pytest.fixture
    def sample_treasury_rate(self) -> MacroData:
        """Create a sample 10Y treasury yield data (TNX)."""
        return MacroData(
            indicator="^TNX",
            date=date.today(),
            value=4.5,  # 4.5% yield
            source="yahoo",
        )

    def test_from_all_data_sources(
        self,
        sample_option_quote: OptionQuote,
        sample_stock_quote: StockQuote,
        sample_treasury_rate: MacroData,
    ):
        """Test creating BSParams from all data sources."""
        params = BSParams.from_market_data(
            option_quote=sample_option_quote,
            stock_quote=sample_stock_quote,
            treasury_rate=sample_treasury_rate,
        )

        assert params.spot_price == 185.0  # From stock_quote.close
        assert params.strike_price == 190.0  # From option_quote
        assert params.risk_free_rate == 0.045  # 4.5% / 100
        assert params.volatility == 0.28  # From option_quote.iv
        assert params.is_call is True

    def test_from_option_and_stock_only(
        self,
        sample_option_quote: OptionQuote,
        sample_stock_quote: StockQuote,
    ):
        """Test with option and stock quote, using default risk-free rate."""
        params = BSParams.from_market_data(
            option_quote=sample_option_quote,
            stock_quote=sample_stock_quote,
        )

        assert params.spot_price == 185.0
        assert params.risk_free_rate == 0.05  # Default

    def test_explicit_spot_overrides_stock_quote(
        self,
        sample_option_quote: OptionQuote,
        sample_stock_quote: StockQuote,
    ):
        """Test that explicit spot_price overrides stock_quote."""
        params = BSParams.from_market_data(
            option_quote=sample_option_quote,
            stock_quote=sample_stock_quote,
            spot_price=180.0,  # Override
        )

        assert params.spot_price == 180.0  # Not 185.0 from stock_quote

    def test_explicit_rate_overrides_treasury(
        self,
        sample_option_quote: OptionQuote,
        sample_stock_quote: StockQuote,
        sample_treasury_rate: MacroData,
    ):
        """Test that explicit risk_free_rate overrides treasury_rate."""
        params = BSParams.from_market_data(
            option_quote=sample_option_quote,
            stock_quote=sample_stock_quote,
            treasury_rate=sample_treasury_rate,
            risk_free_rate=0.03,  # Override
        )

        assert params.risk_free_rate == 0.03  # Not 0.045 from treasury

    def test_spot_from_explicit_only(
        self,
        sample_option_quote: OptionQuote,
    ):
        """Test with explicit spot_price, no stock_quote."""
        params = BSParams.from_market_data(
            option_quote=sample_option_quote,
            spot_price=185.0,
        )

        assert params.spot_price == 185.0

    def test_missing_spot_raises_error(
        self,
        sample_option_quote: OptionQuote,
    ):
        """Test that missing spot_price raises ValueError."""
        with pytest.raises(ValueError, match="spot_price must be provided"):
            BSParams.from_market_data(option_quote=sample_option_quote)

    def test_stock_quote_with_none_close(
        self,
        sample_option_quote: OptionQuote,
    ):
        """Test that stock_quote with None close requires explicit spot_price."""
        stock_quote = StockQuote(
            symbol="AAPL",
            timestamp=datetime.now(),
            close=None,  # No close price
        )

        with pytest.raises(ValueError, match="spot_price must be provided"):
            BSParams.from_market_data(
                option_quote=sample_option_quote,
                stock_quote=stock_quote,
            )

    def test_treasury_rate_conversion(
        self,
        sample_option_quote: OptionQuote,
    ):
        """Test that treasury rate is converted from percentage to decimal."""
        treasury = MacroData(
            indicator="^IRX",  # 13-week T-bill
            date=date.today(),
            value=5.25,  # 5.25%
        )

        params = BSParams.from_market_data(
            option_quote=sample_option_quote,
            spot_price=185.0,
            treasury_rate=treasury,
        )

        assert params.risk_free_rate == pytest.approx(0.0525)  # 5.25% as decimal
