"""Tests for QuantConnect format converters."""

from datetime import date, datetime
from pathlib import Path
import tempfile

import pytest

from src.data.formatters.csv_exporter import CSVExporter
from src.data.formatters.qc_fundamental import FundamentalData
from src.data.formatters.qc_option import OptionQuoteData
from src.data.formatters.qc_stock import StockQuoteData
from src.data.models import Fundamental, KlineBar, OptionQuote
from src.data.models.option import Greeks, OptionContract, OptionType
from src.data.models.stock import KlineType


class TestStockQuoteData:
    """Tests for StockQuoteData formatter."""

    def test_from_kline(self):
        """Test creating from KlineBar."""
        kline = KlineBar(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 15, 9, 30),
            ktype=KlineType.DAY,
            open=180.0,
            high=182.5,
            low=179.0,
            close=181.0,
            volume=1000000,
        )

        data = StockQuoteData.from_kline(kline)

        assert data.symbol == "AAPL"
        assert data.open == 180.0
        assert data.close == 181.0
        assert data.value == 181.0

    def test_to_csv_line(self):
        """Test converting to CSV line."""
        data = StockQuoteData()
        data.time = datetime(2024, 1, 15, 9, 30)
        data.open = 180.0
        data.high = 182.5
        data.low = 179.0
        data.close = 181.0
        data.volume = 1000000

        line = data.to_csv_line()

        assert "20240115 09:30" in line
        assert "180.0" in line
        assert "181.0" in line

    def test_reader(self):
        """Test reading from CSV line."""
        line = "20240115 09:30,180.0,182.5,179.0,181.0,1000000"

        data = StockQuoteData()
        result = data.reader(line, datetime.now())

        assert result is not None
        assert result.open == 180.0
        assert result.close == 181.0
        assert result.volume == 1000000

    def test_header(self):
        """Test CSV header."""
        header = StockQuoteData.get_csv_header()
        assert "timestamp" in header
        assert "open" in header
        assert "close" in header


class TestOptionQuoteData:
    """Tests for OptionQuoteData formatter."""

    def test_from_option_quote(self):
        """Test creating from OptionQuote."""
        contract = OptionContract(
            symbol="AAPL230120C00150000",
            underlying="AAPL",
            option_type=OptionType.CALL,
            strike_price=150.0,
            expiry_date=date(2024, 1, 20),
        )
        greeks = Greeks(delta=0.5, gamma=0.05, theta=-0.1, vega=0.2)
        quote = OptionQuote(
            contract=contract,
            timestamp=datetime(2024, 1, 15),
            last_price=5.0,
            bid=4.9,
            ask=5.1,
            iv=0.25,
            greeks=greeks,
        )

        data = OptionQuoteData.from_option_quote(quote)

        assert data.underlying == "AAPL"
        assert data.option_type == "call"
        assert data.strike == 150.0
        assert data.delta == 0.5

    def test_to_csv_line(self):
        """Test converting to CSV line."""
        data = OptionQuoteData()
        data.time = datetime(2024, 1, 15)
        data.underlying = "AAPL"
        data.option_type = "call"
        data.strike = 150.0
        data.expiry = date(2024, 1, 20)
        data.last_price = 5.0
        data.bid = 4.9
        data.ask = 5.1
        data.option_volume = 1000
        data.open_interest = 5000
        data.iv = 0.25
        data.delta = 0.5
        data.gamma = 0.05
        data.theta = -0.1
        data.vega = 0.2

        line = data.to_csv_line()

        assert "AAPL" in line
        assert "call" in line
        assert "150.0" in line


class TestFundamentalData:
    """Tests for FundamentalData formatter."""

    def test_from_fundamental(self):
        """Test creating from Fundamental."""
        fundamental = Fundamental(
            symbol="AAPL",
            date=date(2024, 1, 15),
            market_cap=3000000000000,
            pe_ratio=28.5,
            eps=6.35,
            roe=0.45,
        )

        data = FundamentalData.from_fundamental(fundamental)

        assert data.market_cap == 3000000000000
        assert data.pe_ratio == 28.5
        assert data.roe == 0.45

    def test_to_fundamental(self):
        """Test converting to Fundamental."""
        data = FundamentalData()
        data.time = datetime(2024, 1, 15)
        data.market_cap = 3000000000000
        data.pe_ratio = 28.5

        fundamental = data.to_fundamental("AAPL")

        assert fundamental.symbol == "AAPL"
        assert fundamental.market_cap == 3000000000000


class TestCSVExporter:
    """Tests for CSV exporter."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for exports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_export_klines(self, temp_dir):
        """Test exporting K-line data."""
        exporter = CSVExporter(output_dir=temp_dir)

        klines = [
            KlineBar(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 15),
                ktype=KlineType.DAY,
                open=180.0,
                high=182.5,
                low=179.0,
                close=181.0,
                volume=1000000,
            ),
            KlineBar(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 16),
                ktype=KlineType.DAY,
                open=181.0,
                high=183.0,
                low=180.0,
                close=182.0,
                volume=1100000,
            ),
        ]

        output_path = exporter.export_klines("AAPL", klines)

        assert output_path.exists()
        content = output_path.read_text()
        assert "timestamp" in content
        assert "180.0" in content

    def test_export_empty_data(self, temp_dir):
        """Test exporting empty data."""
        exporter = CSVExporter(output_dir=temp_dir)

        output_path = exporter.export_klines("AAPL", [])

        assert output_path == Path()
