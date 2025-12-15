"""QuantConnect-compatible stock data format."""

from datetime import datetime
from typing import Any

from src.data.formatters.qc_base import BaseCustomData
from src.data.models import KlineBar, StockQuote


class StockQuoteData(BaseCustomData):
    """Stock quote data in QuantConnect format.

    This class can be used with LEAN for custom data feeds.
    CSV format: timestamp,open,high,low,close,volume

    Usage with LEAN:
        self.AddData(StockQuoteData, "AAPL", Resolution.Daily)
    """

    # Additional properties for stock data
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __init__(self) -> None:
        """Initialize stock quote data."""
        super().__init__()
        self.open = 0.0
        self.high = 0.0
        self.low = 0.0
        self.close = 0.0
        self.volume = 0

    @classmethod
    def get_source_format(cls) -> str:
        """Return CSV format."""
        return "csv"

    def reader(self, line: str, date: datetime) -> "StockQuoteData | None":
        """Parse CSV line into StockQuoteData.

        Expected format: timestamp,open,high,low,close,volume
        Timestamp format: YYYYMMDD HH:MM or YYYY-MM-DD HH:MM:SS

        Args:
            line: CSV line to parse.
            date: Date for filtering (unused in this implementation).

        Returns:
            Parsed StockQuoteData or None if parsing fails.
        """
        try:
            parts = line.strip().split(",")
            if len(parts) < 6:
                return None

            # Skip header
            if parts[0].lower() in ("timestamp", "date", "time"):
                return None

            data = StockQuoteData()

            # Parse timestamp (support multiple formats)
            timestamp_str = parts[0].strip()
            for fmt in [
                "%Y%m%d %H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y%m%d",
            ]:
                try:
                    data.time = datetime.strptime(timestamp_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None

            data.open = float(parts[1])
            data.high = float(parts[2])
            data.low = float(parts[3])
            data.close = float(parts[4])
            data.volume = int(float(parts[5]))
            data.value = data.close  # QuantConnect uses 'value' as primary price

            return data

        except (ValueError, IndexError) as e:
            return None

    def to_csv_line(self) -> str:
        """Convert to CSV line format."""
        timestamp = self.time.strftime("%Y%m%d %H:%M")
        return f"{timestamp},{self.open},{self.high},{self.low},{self.close},{self.volume}"

    @classmethod
    def get_csv_header(cls) -> str:
        """Get CSV header."""
        return "timestamp,open,high,low,close,volume"

    @classmethod
    def from_kline(cls, kline: KlineBar) -> "StockQuoteData":
        """Create from KlineBar model.

        Args:
            kline: KlineBar instance.

        Returns:
            StockQuoteData instance.
        """
        data = cls()
        data.time = kline.timestamp
        data.symbol = kline.symbol
        data.open = kline.open
        data.high = kline.high
        data.low = kline.low
        data.close = kline.close
        data.volume = kline.volume
        data.value = kline.close
        return data

    @classmethod
    def from_quote(cls, quote: StockQuote) -> "StockQuoteData":
        """Create from StockQuote model.

        Args:
            quote: StockQuote instance.

        Returns:
            StockQuoteData instance.
        """
        data = cls()
        data.time = quote.timestamp
        data.symbol = quote.symbol
        data.open = quote.open or 0.0
        data.high = quote.high or 0.0
        data.low = quote.low or 0.0
        data.close = quote.close or 0.0
        data.volume = quote.volume or 0
        data.value = quote.close or 0.0
        return data

    def to_kline(self, symbol: str) -> KlineBar:
        """Convert to KlineBar model.

        Args:
            symbol: Stock symbol.

        Returns:
            KlineBar instance.
        """
        from src.data.models.stock import KlineType

        return KlineBar(
            symbol=symbol,
            timestamp=self.time,
            ktype=KlineType.DAY,  # Default to daily
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            source="quantconnect",
        )
