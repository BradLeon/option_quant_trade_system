"""
Tests for Macro Data Downloader and DuckDBProvider integration.

Tests MacroDownloader for downloading VIX/TNX data and
DuckDBProvider.get_macro_data() for querying.
"""

import pytest
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class TestMacroDownloader:
    """Test MacroDownloader functionality."""

    def test_downloader_initialization(self):
        """Test downloader initialization."""
        from src.backtest.data.macro_downloader import MacroDownloader

        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = MacroDownloader(data_dir=tmpdir)

            assert downloader._data_dir == Path(tmpdir)
            assert downloader._rate_limit == 1.0

    def test_get_parquet_path(self):
        """Test parquet path generation."""
        from src.backtest.data.macro_downloader import MacroDownloader

        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = MacroDownloader(data_dir=tmpdir)

            path = downloader._get_parquet_path()

            assert path == Path(tmpdir) / "macro_daily.parquet"

    def test_default_indicators(self):
        """Test default macro indicators list."""
        from src.backtest.data.macro_downloader import DEFAULT_MACRO_INDICATORS

        assert "^VIX" in DEFAULT_MACRO_INDICATORS
        assert "^VIX3M" in DEFAULT_MACRO_INDICATORS
        assert "^TNX" in DEFAULT_MACRO_INDICATORS
        assert "SPY" in DEFAULT_MACRO_INDICATORS

    def test_download_single_indicator_with_mock(self):
        """Test downloading a single indicator with mocked yfinance."""
        from unittest.mock import MagicMock, patch
        from src.backtest.data.macro_downloader import MacroDownloader
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = MacroDownloader(data_dir=tmpdir, rate_limit=0.1)

            # Mock yfinance response
            mock_hist = pd.DataFrame({
                "Open": [450.0, 451.0],
                "High": [455.0, 456.0],
                "Low": [449.0, 450.0],
                "Close": [454.0, 455.0],
                "Volume": [1000000, 1100000],
                "Adj Close": [454.0, 455.0],
            }, index=pd.to_datetime(["2024-01-02", "2024-01-03"]))

            with patch("yfinance.Ticker") as mock_ticker:
                mock_ticker.return_value.history.return_value = mock_hist

                results = downloader.download_indicators(
                    indicators=["SPY"],
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 1, 5),
                )

            assert "SPY" in results
            assert results["SPY"] == 2

            # Verify parquet file exists
            parquet_path = downloader._get_parquet_path()
            assert parquet_path.exists()

    def test_get_available_indicators_with_mock_data(self):
        """Test getting available indicators from mock data."""
        from src.backtest.data.macro_downloader import MacroDownloader

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create mock data directly
            macro_data = {
                "indicator": ["SPY", "SPY", "^VIX", "^VIX"],
                "date": [date(2024, 1, 2), date(2024, 1, 3)] * 2,
                "open": [450.0, 451.0, 13.0, 14.0],
                "high": [455.0, 456.0, 14.0, 15.0],
                "low": [449.0, 450.0, 12.5, 13.5],
                "close": [454.0, 455.0, 13.5, 14.5],
                "volume": [1000000, 1100000, None, None],
                "adj_close": [454.0, 455.0, None, None],
            }

            table = pa.Table.from_pydict(macro_data)
            parquet_path = Path(tmpdir) / "macro_daily.parquet"
            pq.write_table(table, parquet_path)

            downloader = MacroDownloader(data_dir=tmpdir)

            # Check available indicators
            available = downloader.get_available_indicators()

            assert "SPY" in available
            assert "^VIX" in available
            assert len(available) == 2

    def test_get_date_range_with_mock_data(self):
        """Test getting date range from mock data."""
        from src.backtest.data.macro_downloader import MacroDownloader

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create mock data directly
            macro_data = {
                "indicator": ["SPY", "SPY", "SPY"],
                "date": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
                "open": [450.0, 451.0, 452.0],
                "high": [455.0, 456.0, 457.0],
                "low": [449.0, 450.0, 451.0],
                "close": [454.0, 455.0, 456.0],
                "volume": [1000000, 1100000, 1200000],
                "adj_close": [454.0, 455.0, 456.0],
            }

            table = pa.Table.from_pydict(macro_data)
            parquet_path = Path(tmpdir) / "macro_daily.parquet"
            pq.write_table(table, parquet_path)

            downloader = MacroDownloader(data_dir=tmpdir)

            # Check date range
            date_range = downloader.get_date_range("SPY")

            assert date_range is not None
            assert date_range[0] == date(2024, 1, 2)
            assert date_range[1] == date(2024, 1, 4)


class TestDuckDBProviderMacroData:
    """Test DuckDBProvider macro data functionality."""

    @pytest.fixture
    def temp_data_with_macro(self, tmp_path: Path):
        """Create temp directory with mock macro data."""
        # Create mock macro data
        macro_data = {
            "indicator": ["^VIX", "^VIX", "^VIX", "^TNX", "^TNX", "^TNX"],
            "date": [
                date(2024, 1, 2),
                date(2024, 1, 3),
                date(2024, 1, 4),
                date(2024, 1, 2),
                date(2024, 1, 3),
                date(2024, 1, 4),
            ],
            "open": [13.5, 14.0, 13.8, 3.9, 4.0, 4.1],
            "high": [14.0, 14.5, 14.2, 4.0, 4.1, 4.2],
            "low": [13.0, 13.5, 13.3, 3.8, 3.9, 4.0],
            "close": [13.8, 14.2, 13.5, 3.95, 4.05, 4.15],
            "volume": [None, None, None, None, None, None],
            "adj_close": [13.8, 14.2, 13.5, 3.95, 4.05, 4.15],
        }

        table = pa.Table.from_pydict(macro_data)
        parquet_path = tmp_path / "macro_daily.parquet"
        pq.write_table(table, parquet_path)

        # Also create empty stock/option dirs for other tests
        (tmp_path / "stock_daily.parquet").touch()

        return tmp_path

    def test_get_macro_data(self, temp_data_with_macro: Path):
        """Test get_macro_data returns correct data."""
        from src.backtest.data.duckdb_provider import DuckDBProvider

        provider = DuckDBProvider(
            data_dir=temp_data_with_macro,
            as_of_date=date(2024, 1, 10),
        )

        # Get VIX data
        vix_data = provider.get_macro_data(
            "^VIX",
            date(2024, 1, 1),
            date(2024, 1, 10),
        )

        assert len(vix_data) == 3
        assert vix_data[0].indicator == "^VIX"
        assert vix_data[0].date == date(2024, 1, 2)
        assert vix_data[0].value == 13.8  # close value

    def test_get_macro_data_respects_as_of_date(self, temp_data_with_macro: Path):
        """Test that get_macro_data respects as_of_date."""
        from src.backtest.data.duckdb_provider import DuckDBProvider

        provider = DuckDBProvider(
            data_dir=temp_data_with_macro,
            as_of_date=date(2024, 1, 3),  # Only see data up to Jan 3
        )

        vix_data = provider.get_macro_data(
            "^VIX",
            date(2024, 1, 1),
            date(2024, 1, 10),
        )

        # Should only return 2 records (Jan 2 and Jan 3)
        assert len(vix_data) == 2
        assert vix_data[-1].date == date(2024, 1, 3)

    def test_get_macro_data_different_indicator(self, temp_data_with_macro: Path):
        """Test get_macro_data for different indicators."""
        from src.backtest.data.duckdb_provider import DuckDBProvider

        provider = DuckDBProvider(
            data_dir=temp_data_with_macro,
            as_of_date=date(2024, 1, 10),
        )

        # Get TNX data
        tnx_data = provider.get_macro_data(
            "^TNX",
            date(2024, 1, 1),
            date(2024, 1, 10),
        )

        assert len(tnx_data) == 3
        assert tnx_data[0].indicator == "^TNX"
        assert tnx_data[0].value == 3.95

    def test_get_macro_data_no_data(self, temp_data_with_macro: Path):
        """Test get_macro_data returns empty list when no data."""
        from src.backtest.data.duckdb_provider import DuckDBProvider

        provider = DuckDBProvider(
            data_dir=temp_data_with_macro,
            as_of_date=date(2024, 1, 10),
        )

        # Get non-existent indicator
        data = provider.get_macro_data(
            "^NONEXISTENT",
            date(2024, 1, 1),
            date(2024, 1, 10),
        )

        assert len(data) == 0

    def test_get_available_macro_indicators(self, temp_data_with_macro: Path):
        """Test get_available_macro_indicators."""
        from src.backtest.data.duckdb_provider import DuckDBProvider

        provider = DuckDBProvider(
            data_dir=temp_data_with_macro,
            as_of_date=date(2024, 1, 10),
        )

        indicators = provider.get_available_macro_indicators()

        assert "^VIX" in indicators
        assert "^TNX" in indicators
        assert len(indicators) == 2


class TestMacroDataIntegration:
    """Integration tests for macro data flow."""

    def test_download_and_query_flow_with_mock(self):
        """Test full flow: download -> query with mocked yfinance."""
        from unittest.mock import patch
        from src.backtest.data.macro_downloader import MacroDownloader
        from src.backtest.data.duckdb_provider import DuckDBProvider
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir)

            # 1. Download macro data with mock
            downloader = MacroDownloader(data_dir=data_path, rate_limit=0.1)

            # Mock yfinance response
            mock_hist = pd.DataFrame({
                "Open": [450.0, 451.0, 452.0],
                "High": [455.0, 456.0, 457.0],
                "Low": [449.0, 450.0, 451.0],
                "Close": [454.0, 455.0, 456.0],
                "Volume": [1000000, 1100000, 1200000],
                "Adj Close": [454.0, 455.0, 456.0],
            }, index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))

            with patch("yfinance.Ticker") as mock_ticker:
                mock_ticker.return_value.history.return_value = mock_hist

                results = downloader.download_indicators(
                    indicators=["SPY"],
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 1, 5),
                )

            assert results["SPY"] == 3

            # 2. Query via DuckDBProvider
            provider = DuckDBProvider(
                data_dir=data_path,
                as_of_date=date(2024, 1, 10),
            )

            macro_data = provider.get_macro_data(
                "SPY",
                date(2024, 1, 1),
                date(2024, 1, 10),
            )

            assert len(macro_data) == 3
            assert macro_data[0].indicator == "SPY"
            assert macro_data[0].value == 454.0  # close price
            assert macro_data[0].date == date(2024, 1, 2)

    @pytest.mark.skipif(
        True,  # Skip by default, can be enabled for manual testing
        reason="Requires network access to yfinance"
    )
    def test_download_and_query_flow_live(self):
        """Test full flow with live yfinance data (manual test)."""
        from src.backtest.data.macro_downloader import MacroDownloader
        from src.backtest.data.duckdb_provider import DuckDBProvider

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir)

            # 1. Download macro data
            downloader = MacroDownloader(data_dir=data_path, rate_limit=2.0)

            end_date = date.today() - timedelta(days=1)
            start_date = end_date - timedelta(days=30)

            results = downloader.download_indicators(
                indicators=["SPY"],
                start_date=start_date,
                end_date=end_date,
            )

            assert results["SPY"] > 0

            # 2. Query via DuckDBProvider
            provider = DuckDBProvider(
                data_dir=data_path,
                as_of_date=end_date,
            )

            macro_data = provider.get_macro_data(
                "SPY",
                start_date,
                end_date,
            )

            assert len(macro_data) > 0
            assert macro_data[0].indicator == "SPY"
            assert macro_data[0].value > 0
