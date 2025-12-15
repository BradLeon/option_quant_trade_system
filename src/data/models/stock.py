"""Stock data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class KlineType(Enum):
    """K-line time period types."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    MIN_1 = "1min"
    MIN_5 = "5min"
    MIN_15 = "15min"
    MIN_30 = "30min"
    MIN_60 = "60min"


@dataclass
class StockQuote:
    """Stock quote data model.

    Represents real-time or delayed stock quote data.
    """

    symbol: str
    timestamp: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    turnover: float | None = None
    prev_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "turnover": self.turnover,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StockQuote":
        """Create instance from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(
            symbol=data["symbol"],
            timestamp=timestamp,
            open=data.get("open"),
            high=data.get("high"),
            low=data.get("low"),
            close=data.get("close"),
            volume=data.get("volume"),
            turnover=data.get("turnover"),
            prev_close=data.get("prev_close"),
            change=data.get("change"),
            change_percent=data.get("change_percent"),
            source=data.get("source", "unknown"),
        )


@dataclass
class KlineBar:
    """K-line (candlestick) bar data model.

    Represents OHLCV data for a specific time period.
    """

    symbol: str
    timestamp: datetime
    ktype: KlineType
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "ktype": self.ktype.value,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "turnover": self.turnover,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KlineBar":
        """Create instance from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        ktype = data.get("ktype")
        if isinstance(ktype, str):
            ktype = KlineType(ktype)

        return cls(
            symbol=data["symbol"],
            timestamp=timestamp,
            ktype=ktype,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            volume=data["volume"],
            turnover=data.get("turnover"),
            source=data.get("source", "unknown"),
        )

    def to_csv_row(self) -> str:
        """Convert to CSV row format for QuantConnect."""
        # Format: timestamp,open,high,low,close,volume
        ts = self.timestamp.strftime("%Y%m%d %H:%M")
        return f"{ts},{self.open},{self.high},{self.low},{self.close},{self.volume}"
