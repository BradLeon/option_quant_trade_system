"""QuantConnect-compatible option data format."""

from datetime import date, datetime
from typing import Any

from src.data.formatters.qc_base import BaseCustomData
from src.data.models import OptionQuote
from src.data.models.option import Greeks, OptionContract, OptionType


class OptionQuoteData(BaseCustomData):
    """Option quote data in QuantConnect format.

    This class can be used with LEAN for custom option data feeds.
    CSV format: timestamp,underlying,type,strike,expiry,last,bid,ask,volume,oi,iv,delta,gamma,theta,vega

    Usage with LEAN:
        self.AddData(OptionQuoteData, "AAPL_OPTIONS", Resolution.Minute)
    """

    # Additional properties for option data
    underlying: str
    option_type: str  # 'call' or 'put'
    strike: float
    expiry: date
    last_price: float
    bid: float
    ask: float
    option_volume: int
    open_interest: int
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float

    def __init__(self) -> None:
        """Initialize option quote data."""
        super().__init__()
        self.underlying = ""
        self.option_type = "call"
        self.strike = 0.0
        self.expiry = date.today()
        self.last_price = 0.0
        self.bid = 0.0
        self.ask = 0.0
        self.option_volume = 0
        self.open_interest = 0
        self.iv = 0.0
        self.delta = 0.0
        self.gamma = 0.0
        self.theta = 0.0
        self.vega = 0.0

    @classmethod
    def get_source_format(cls) -> str:
        """Return CSV format."""
        return "csv"

    def reader(self, line: str, date: datetime) -> "OptionQuoteData | None":
        """Parse CSV line into OptionQuoteData.

        Expected format: timestamp,underlying,type,strike,expiry,last,bid,ask,volume,oi,iv,delta,gamma,theta,vega

        Args:
            line: CSV line to parse.
            date: Date for filtering.

        Returns:
            Parsed OptionQuoteData or None if parsing fails.
        """
        try:
            parts = line.strip().split(",")
            if len(parts) < 15:
                return None

            # Skip header
            if parts[0].lower() in ("timestamp", "date", "time"):
                return None

            data = OptionQuoteData()

            # Parse timestamp
            timestamp_str = parts[0].strip()
            for fmt in ["%Y%m%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    data.time = datetime.strptime(timestamp_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None

            data.underlying = parts[1]
            data.option_type = parts[2].lower()
            data.strike = float(parts[3])
            data.expiry = datetime.strptime(parts[4], "%Y-%m-%d").date()
            data.last_price = float(parts[5]) if parts[5] else 0.0
            data.bid = float(parts[6]) if parts[6] else 0.0
            data.ask = float(parts[7]) if parts[7] else 0.0
            data.option_volume = int(float(parts[8])) if parts[8] else 0
            data.open_interest = int(float(parts[9])) if parts[9] else 0
            data.iv = float(parts[10]) if parts[10] else 0.0
            data.delta = float(parts[11]) if parts[11] else 0.0
            data.gamma = float(parts[12]) if parts[12] else 0.0
            data.theta = float(parts[13]) if parts[13] else 0.0
            data.vega = float(parts[14]) if parts[14] else 0.0

            # Set value to mid price or last price
            if data.bid and data.ask:
                data.value = (data.bid + data.ask) / 2
            else:
                data.value = data.last_price

            return data

        except (ValueError, IndexError):
            return None

    def to_csv_line(self) -> str:
        """Convert to CSV line format."""
        timestamp = self.time.strftime("%Y%m%d %H:%M")
        expiry_str = self.expiry.strftime("%Y-%m-%d")
        return (
            f"{timestamp},{self.underlying},{self.option_type},{self.strike},"
            f"{expiry_str},{self.last_price},{self.bid},{self.ask},"
            f"{self.option_volume},{self.open_interest},{self.iv},"
            f"{self.delta},{self.gamma},{self.theta},{self.vega}"
        )

    @classmethod
    def get_csv_header(cls) -> str:
        """Get CSV header."""
        return "timestamp,underlying,type,strike,expiry,last,bid,ask,volume,oi,iv,delta,gamma,theta,vega"

    @classmethod
    def from_option_quote(cls, quote: OptionQuote) -> "OptionQuoteData":
        """Create from OptionQuote model.

        Args:
            quote: OptionQuote instance.

        Returns:
            OptionQuoteData instance.
        """
        data = cls()
        data.time = quote.timestamp
        data.symbol = quote.contract.symbol
        data.underlying = quote.contract.underlying
        data.option_type = quote.contract.option_type.value
        data.strike = quote.contract.strike_price
        data.expiry = quote.contract.expiry_date
        data.last_price = quote.last_price or 0.0
        data.bid = quote.bid or 0.0
        data.ask = quote.ask or 0.0
        data.option_volume = quote.volume or 0
        data.open_interest = quote.open_interest or 0
        data.iv = quote.iv or 0.0
        data.delta = quote.greeks.delta or 0.0
        data.gamma = quote.greeks.gamma or 0.0
        data.theta = quote.greeks.theta or 0.0
        data.vega = quote.greeks.vega or 0.0

        # Set value to mid price or last
        if data.bid and data.ask:
            data.value = (data.bid + data.ask) / 2
        else:
            data.value = data.last_price

        return data

    def to_option_quote(self) -> OptionQuote:
        """Convert to OptionQuote model.

        Returns:
            OptionQuote instance.
        """
        contract = OptionContract(
            symbol=self.symbol,
            underlying=self.underlying,
            option_type=OptionType(self.option_type),
            strike_price=self.strike,
            expiry_date=self.expiry,
        )

        greeks = Greeks(
            delta=self.delta if self.delta else None,
            gamma=self.gamma if self.gamma else None,
            theta=self.theta if self.theta else None,
            vega=self.vega if self.vega else None,
        )

        return OptionQuote(
            contract=contract,
            timestamp=self.time,
            last_price=self.last_price if self.last_price else None,
            bid=self.bid if self.bid else None,
            ask=self.ask if self.ask else None,
            volume=self.option_volume if self.option_volume else None,
            open_interest=self.open_interest if self.open_interest else None,
            iv=self.iv if self.iv else None,
            greeks=greeks,
            source="quantconnect",
        )
