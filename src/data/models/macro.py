"""Macro economic data models."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


class MacroIndicator(Enum):
    """Common macro economic indicators."""

    # Volatility
    VIX = "^VIX"  # CBOE Volatility Index

    # Interest Rates
    TNX = "^TNX"  # 10-Year Treasury Note Yield
    FVX = "^FVX"  # 5-Year Treasury Note Yield
    TYX = "^TYX"  # 30-Year Treasury Bond Yield
    IRX = "^IRX"  # 13-Week Treasury Bill

    # Major Indices
    SPX = "^GSPC"  # S&P 500
    DJI = "^DJI"  # Dow Jones Industrial Average
    IXIC = "^IXIC"  # NASDAQ Composite
    RUT = "^RUT"  # Russell 2000

    # ETF Proxies
    SPY = "SPY"  # S&P 500 ETF
    QQQ = "QQQ"  # NASDAQ-100 ETF
    IWM = "IWM"  # Russell 2000 ETF
    TLT = "TLT"  # 20+ Year Treasury Bond ETF

    # Sector Indices
    XLF = "XLF"  # Financial Select Sector
    XLK = "XLK"  # Technology Select Sector
    XLE = "XLE"  # Energy Select Sector

    # International
    EEM = "EEM"  # Emerging Markets ETF
    FXI = "FXI"  # China Large-Cap ETF


@dataclass
class MacroData:
    """Macro economic data point.

    Represents a single data point for a macro indicator.
    """

    indicator: str  # Indicator symbol (e.g., ^VIX)
    date: date
    value: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "indicator": self.indicator,
            "date": self.date.isoformat(),
            "value": self.value,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MacroData":
        """Create instance from dictionary."""
        data_date = data.get("date")
        if isinstance(data_date, str):
            data_date = date.fromisoformat(data_date)

        return cls(
            indicator=data["indicator"],
            date=data_date,
            value=data["value"],
            open=data.get("open"),
            high=data.get("high"),
            low=data.get("low"),
            close=data.get("close"),
            volume=data.get("volume"),
            source=data.get("source", "unknown"),
        )

    @classmethod
    def from_kline(
        cls,
        indicator: str,
        data_date: date,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int | None = None,
        source: str = "unknown",
    ) -> "MacroData":
        """Create from K-line data, using close as value."""
        return cls(
            indicator=indicator,
            date=data_date,
            value=close,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
        )
