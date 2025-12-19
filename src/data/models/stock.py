"""Stock data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass
class StockVolatility:
    """Stock-level volatility metrics.

    Contains aggregate volatility data for a stock, including:
    - IV: Implied Volatility (30-day, from option prices)
    - HV: Historical Volatility (30-day, from price history)
    - IV Rank: Where current IV falls in 52-week range (0-100)
    - IV Percentile: % of days IV was lower than current (0-100)
    - PCR: Put/Call Ratio (total put volume / call volume)

    All volatility values are in decimal form (e.g., 0.25 = 25%).
    """

    symbol: str
    timestamp: datetime
    iv: float | None = None  # 30-day Implied Volatility
    hv: float | None = None  # 30-day Historical Volatility
    iv_rank: float | None = None  # IV Rank (0-100)
    iv_percentile: float | None = None  # IV Percentile (0-100)
    pcr: float | None = None  # Put/Call Ratio
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "iv": self.iv,
            "hv": self.hv,
            "iv_rank": self.iv_rank,
            "iv_percentile": self.iv_percentile,
            "pcr": self.pcr,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StockVolatility":
        """Create instance from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(
            symbol=data["symbol"],
            timestamp=timestamp,
            iv=data.get("iv"),
            hv=data.get("hv"),
            iv_rank=data.get("iv_rank"),
            iv_percentile=data.get("iv_percentile"),
            pcr=data.get("pcr"),
            source=data.get("source", "unknown"),
        )

    @property
    def iv_hv_ratio(self) -> float | None:
        """Calculate IV/HV ratio."""
        if self.iv is None or self.hv is None or self.hv == 0:
            return None
        return self.iv / self.hv


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
