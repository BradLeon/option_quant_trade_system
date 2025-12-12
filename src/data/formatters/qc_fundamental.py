"""QuantConnect-compatible fundamental data format."""

from datetime import date, datetime
from typing import Any

from src.data.formatters.qc_base import BaseCustomData
from src.data.models import Fundamental


class FundamentalData(BaseCustomData):
    """Fundamental data in QuantConnect format.

    This class can be used with LEAN for custom fundamental data feeds.
    CSV format: date,market_cap,pe_ratio,pb_ratio,dividend_yield,eps,revenue,profit,roe

    Usage with LEAN:
        self.AddData(FundamentalData, "AAPL_FUNDAMENTAL", Resolution.Daily)
    """

    # Additional properties for fundamental data
    market_cap: float
    pe_ratio: float
    pb_ratio: float
    dividend_yield: float
    eps: float
    revenue: float
    profit: float
    roe: float

    def __init__(self) -> None:
        """Initialize fundamental data."""
        super().__init__()
        self.market_cap = 0.0
        self.pe_ratio = 0.0
        self.pb_ratio = 0.0
        self.dividend_yield = 0.0
        self.eps = 0.0
        self.revenue = 0.0
        self.profit = 0.0
        self.roe = 0.0

    @classmethod
    def get_source_format(cls) -> str:
        """Return CSV format."""
        return "csv"

    def reader(self, line: str, date: datetime) -> "FundamentalData | None":
        """Parse CSV line into FundamentalData.

        Expected format: date,market_cap,pe_ratio,pb_ratio,dividend_yield,eps,revenue,profit,roe

        Args:
            line: CSV line to parse.
            date: Date for filtering.

        Returns:
            Parsed FundamentalData or None if parsing fails.
        """
        try:
            parts = line.strip().split(",")
            if len(parts) < 9:
                return None

            # Skip header
            if parts[0].lower() in ("date", "timestamp"):
                return None

            data = FundamentalData()

            # Parse date
            date_str = parts[0].strip()
            data.time = datetime.strptime(date_str, "%Y-%m-%d")

            data.market_cap = float(parts[1]) if parts[1] else 0.0
            data.pe_ratio = float(parts[2]) if parts[2] else 0.0
            data.pb_ratio = float(parts[3]) if parts[3] else 0.0
            data.dividend_yield = float(parts[4]) if parts[4] else 0.0
            data.eps = float(parts[5]) if parts[5] else 0.0
            data.revenue = float(parts[6]) if parts[6] else 0.0
            data.profit = float(parts[7]) if parts[7] else 0.0
            data.roe = float(parts[8]) if parts[8] else 0.0

            # Value is market cap for fundamental data
            data.value = data.market_cap

            return data

        except (ValueError, IndexError):
            return None

    def to_csv_line(self) -> str:
        """Convert to CSV line format."""
        date_str = self.time.strftime("%Y-%m-%d")
        return (
            f"{date_str},{self.market_cap},{self.pe_ratio},{self.pb_ratio},"
            f"{self.dividend_yield},{self.eps},{self.revenue},{self.profit},{self.roe}"
        )

    @classmethod
    def get_csv_header(cls) -> str:
        """Get CSV header."""
        return "date,market_cap,pe_ratio,pb_ratio,dividend_yield,eps,revenue,profit,roe"

    @classmethod
    def from_fundamental(cls, fundamental: Fundamental) -> "FundamentalData":
        """Create from Fundamental model.

        Args:
            fundamental: Fundamental instance.

        Returns:
            FundamentalData instance.
        """
        data = cls()
        data.time = datetime.combine(fundamental.date, datetime.min.time())
        data.symbol = fundamental.symbol
        data.market_cap = fundamental.market_cap or 0.0
        data.pe_ratio = fundamental.pe_ratio or 0.0
        data.pb_ratio = fundamental.pb_ratio or 0.0
        data.dividend_yield = fundamental.dividend_yield or 0.0
        data.eps = fundamental.eps or 0.0
        data.revenue = fundamental.revenue or 0.0
        data.profit = fundamental.profit or 0.0
        data.roe = fundamental.roe or 0.0
        data.value = data.market_cap
        return data

    def to_fundamental(self, symbol: str) -> Fundamental:
        """Convert to Fundamental model.

        Args:
            symbol: Stock symbol.

        Returns:
            Fundamental instance.
        """
        return Fundamental(
            symbol=symbol,
            date=self.time.date(),
            market_cap=self.market_cap if self.market_cap else None,
            pe_ratio=self.pe_ratio if self.pe_ratio else None,
            pb_ratio=self.pb_ratio if self.pb_ratio else None,
            dividend_yield=self.dividend_yield if self.dividend_yield else None,
            eps=self.eps if self.eps else None,
            revenue=self.revenue if self.revenue else None,
            profit=self.profit if self.profit else None,
            roe=self.roe if self.roe else None,
            source="quantconnect",
        )
