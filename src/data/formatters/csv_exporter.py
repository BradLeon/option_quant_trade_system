"""CSV exporter for QuantConnect-compatible data files."""

import logging
from pathlib import Path
from typing import Any

from src.data.formatters.qc_base import export_to_csv
from src.data.formatters.qc_fundamental import FundamentalData
from src.data.formatters.qc_option import OptionQuoteData
from src.data.formatters.qc_stock import StockQuoteData
from src.data.models import Fundamental, KlineBar, OptionChain, OptionQuote, StockQuote

logger = logging.getLogger(__name__)


class CSVExporter:
    """Export market data to QuantConnect-compatible CSV format.

    The exported files can be used with LEAN for backtesting.

    Usage:
        exporter = CSVExporter(output_dir="data/export")
        exporter.export_klines("AAPL", klines)
        exporter.export_option_chain("AAPL", option_chain)
    """

    def __init__(self, output_dir: str | Path = "data/export") -> None:
        """Initialize CSV exporter.

        Args:
            output_dir: Directory for exported files.
        """
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def export_klines(
        self,
        symbol: str,
        klines: list[KlineBar],
        filename: str | None = None,
    ) -> Path:
        """Export K-line data to CSV.

        Args:
            symbol: Stock symbol.
            klines: List of KlineBar instances.
            filename: Optional custom filename.

        Returns:
            Path to exported file.
        """
        if not klines:
            logger.warning(f"No klines to export for {symbol}")
            return Path()

        qc_data = [StockQuoteData.from_kline(k) for k in klines]
        qc_data.sort(key=lambda x: x.time)

        filename = filename or f"{symbol.replace('.', '_')}_kline.csv"
        output_path = self._output_dir / filename

        export_to_csv(qc_data, output_path)
        return output_path

    def export_quotes(
        self,
        symbol: str,
        quotes: list[StockQuote],
        filename: str | None = None,
    ) -> Path:
        """Export stock quotes to CSV.

        Args:
            symbol: Stock symbol.
            quotes: List of StockQuote instances.
            filename: Optional custom filename.

        Returns:
            Path to exported file.
        """
        if not quotes:
            logger.warning(f"No quotes to export for {symbol}")
            return Path()

        qc_data = [StockQuoteData.from_quote(q) for q in quotes]
        qc_data.sort(key=lambda x: x.time)

        filename = filename or f"{symbol.replace('.', '_')}_quote.csv"
        output_path = self._output_dir / filename

        export_to_csv(qc_data, output_path)
        return output_path

    def export_option_chain(
        self,
        underlying: str,
        chain: OptionChain,
        filename: str | None = None,
    ) -> Path:
        """Export option chain to CSV.

        Args:
            underlying: Underlying stock symbol.
            chain: OptionChain instance.
            filename: Optional custom filename.

        Returns:
            Path to exported file.
        """
        all_options = chain.calls + chain.puts
        if not all_options:
            logger.warning(f"No options to export for {underlying}")
            return Path()

        qc_data = [OptionQuoteData.from_option_quote(opt) for opt in all_options]
        qc_data.sort(key=lambda x: (x.expiry, x.strike, x.option_type))

        filename = filename or f"{underlying.replace('.', '_')}_options.csv"
        output_path = self._output_dir / filename

        export_to_csv(qc_data, output_path)
        return output_path

    def export_option_quotes(
        self,
        quotes: list[OptionQuote],
        filename: str,
    ) -> Path:
        """Export option quotes to CSV.

        Args:
            quotes: List of OptionQuote instances.
            filename: Output filename.

        Returns:
            Path to exported file.
        """
        if not quotes:
            logger.warning("No option quotes to export")
            return Path()

        qc_data = [OptionQuoteData.from_option_quote(q) for q in quotes]
        qc_data.sort(key=lambda x: x.time)

        output_path = self._output_dir / filename
        export_to_csv(qc_data, output_path)
        return output_path

    def export_fundamentals(
        self,
        symbol: str,
        fundamentals: list[Fundamental],
        filename: str | None = None,
    ) -> Path:
        """Export fundamental data to CSV.

        Args:
            symbol: Stock symbol.
            fundamentals: List of Fundamental instances.
            filename: Optional custom filename.

        Returns:
            Path to exported file.
        """
        if not fundamentals:
            logger.warning(f"No fundamentals to export for {symbol}")
            return Path()

        qc_data = [FundamentalData.from_fundamental(f) for f in fundamentals]
        qc_data.sort(key=lambda x: x.time)

        filename = filename or f"{symbol.replace('.', '_')}_fundamental.csv"
        output_path = self._output_dir / filename

        export_to_csv(qc_data, output_path)
        return output_path

    def export_all(
        self,
        symbol: str,
        klines: list[KlineBar] | None = None,
        quotes: list[StockQuote] | None = None,
        option_chain: OptionChain | None = None,
        fundamentals: list[Fundamental] | None = None,
    ) -> dict[str, Path]:
        """Export all available data for a symbol.

        Args:
            symbol: Stock symbol.
            klines: Optional K-line data.
            quotes: Optional stock quotes.
            option_chain: Optional option chain.
            fundamentals: Optional fundamental data.

        Returns:
            Dictionary mapping data type to output path.
        """
        results = {}

        if klines:
            results["klines"] = self.export_klines(symbol, klines)

        if quotes:
            results["quotes"] = self.export_quotes(symbol, quotes)

        if option_chain:
            results["options"] = self.export_option_chain(symbol, option_chain)

        if fundamentals:
            results["fundamentals"] = self.export_fundamentals(symbol, fundamentals)

        return results
