"""Tests for data models."""

from datetime import date, datetime

import pytest

from src.data.models import (
    Fundamental,
    KlineBar,
    MacroData,
    OptionChain,
    OptionQuote,
    StockQuote,
)
from src.data.models.option import Greeks, OptionContract, OptionType
from src.data.models.stock import KlineType


class TestStockQuote:
    """Tests for StockQuote model."""

    def test_create_stock_quote(self):
        """Test creating a stock quote."""
        quote = StockQuote(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 15, 10, 30),
            open=180.0,
            high=182.5,
            low=179.0,
            close=181.0,
            volume=1000000,
            source="test",
        )

        assert quote.symbol == "AAPL"
        assert quote.close == 181.0
        assert quote.volume == 1000000

    def test_to_dict(self):
        """Test converting to dictionary."""
        quote = StockQuote(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 15, 10, 30),
            close=181.0,
            volume=1000000,
            source="test",
        )

        data = quote.to_dict()
        assert data["symbol"] == "AAPL"
        assert data["close"] == 181.0

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "symbol": "AAPL",
            "timestamp": "2024-01-15T10:30:00",
            "close": 181.0,
            "volume": 1000000,
            "source": "test",
        }

        quote = StockQuote.from_dict(data)
        assert quote.symbol == "AAPL"
        assert quote.close == 181.0


class TestKlineBar:
    """Tests for KlineBar model."""

    def test_create_kline(self):
        """Test creating a kline bar."""
        bar = KlineBar(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 15),
            ktype=KlineType.DAY,
            open=180.0,
            high=182.5,
            low=179.0,
            close=181.0,
            volume=1000000,
        )

        assert bar.ktype == KlineType.DAY
        assert bar.open == 180.0

    def test_to_csv_row(self):
        """Test converting to CSV row."""
        bar = KlineBar(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 15, 9, 30),
            ktype=KlineType.DAY,
            open=180.0,
            high=182.5,
            low=179.0,
            close=181.0,
            volume=1000000,
        )

        csv_row = bar.to_csv_row()
        assert "20240115" in csv_row
        assert "180.0" in csv_row


class TestOptionModels:
    """Tests for option-related models."""

    def test_option_contract(self):
        """Test creating option contract."""
        contract = OptionContract(
            symbol="AAPL230120C00150000",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=150.0,
            expiry_date=date(2024, 1, 20),
        )

        assert contract.option_type == OptionType.CALL
        assert contract.strike_price == 150.0
        assert contract.days_to_expiry < 0  # Past date

    def test_greeks(self):
        """Test Greeks model."""
        greeks = Greeks(
            delta=0.5,
            gamma=0.05,
            theta=-0.1,
            vega=0.2,
        )

        data = greeks.to_dict()
        assert data["delta"] == 0.5
        assert data["theta"] == -0.1

    def test_option_quote(self):
        """Test option quote model."""
        contract = OptionContract(
            symbol="AAPL230120C00150000",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=150.0,
            expiry_date=date(2024, 1, 20),
        )

        greeks = Greeks(delta=0.5, gamma=0.05)

        quote = OptionQuote(
            contract=contract,
            timestamp=datetime(2024, 1, 15),
            last_price=5.0,
            bid=4.9,
            ask=5.1,
            iv=0.25,
            greeks=greeks,
        )

        assert quote.mid_price == 5.0
        assert quote.iv == 0.25

    def test_option_chain(self):
        """Test option chain model."""
        contract1 = OptionContract(
            symbol="AAPL1",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=150.0,
            expiry_date=date(2024, 1, 20),
        )
        contract2 = OptionContract(
            symbol="AAPL2",
            underlying="AAPL",
            option_type=OptionType.PUT,
            strike_price=150.0,
            expiry_date=date(2024, 1, 20),
        )

        call = OptionQuote(
            contract=contract1,
            timestamp=datetime.now(),
            greeks=Greeks(delta=0.5),
        )
        put = OptionQuote(
            contract=contract2,
            timestamp=datetime.now(),
            greeks=Greeks(delta=-0.5),
        )

        chain = OptionChain(
            underlying="AAPL",
            timestamp=datetime.now(),
            expiry_dates=[date(2024, 1, 20)],
            calls=[call],
            puts=[put],
        )

        assert len(chain.calls) == 1
        assert len(chain.puts) == 1


class TestFundamental:
    """Tests for Fundamental model."""

    def test_create_fundamental(self):
        """Test creating fundamental data."""
        fundamental = Fundamental(
            symbol="AAPL",
            date=date(2024, 1, 15),
            market_cap=3000000000000,
            pe_ratio=28.5,
            eps=6.35,
        )

        assert fundamental.market_cap == 3000000000000
        assert fundamental.pe_ratio == 28.5

    def test_to_dict(self):
        """Test converting to dictionary."""
        fundamental = Fundamental(
            symbol="AAPL",
            date=date(2024, 1, 15),
            market_cap=3000000000000,
        )

        data = fundamental.to_dict()
        assert data["symbol"] == "AAPL"
        assert data["market_cap"] == 3000000000000


class TestMacroData:
    """Tests for MacroData model."""

    def test_create_macro(self):
        """Test creating macro data."""
        macro = MacroData(
            indicator="^VIX",
            date=date(2024, 1, 15),
            value=15.5,
        )

        assert macro.indicator == "^VIX"
        assert macro.value == 15.5

    def test_from_kline(self):
        """Test creating from K-line data."""
        macro = MacroData.from_kline(
            indicator="^VIX",
            data_date=date(2024, 1, 15),
            open_=15.0,
            high=16.0,
            low=14.5,
            close=15.5,
        )

        assert macro.value == 15.5
        assert macro.high == 16.0
