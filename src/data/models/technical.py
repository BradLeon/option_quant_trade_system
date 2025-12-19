"""Technical analysis data models.

Input data models for technical indicator calculations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.data.models.stock import KlineBar


@dataclass
class TechnicalData:
    """Technical analysis input data.

    Contains OHLCV price data needed for technical indicator calculations.
    Can be constructed from a list of KlineBar or raw price arrays.

    Attributes:
        symbol: Stock symbol.
        timestamp: Latest data timestamp.
        opens: List of open prices (oldest to newest).
        highs: List of high prices.
        lows: List of low prices.
        closes: List of close prices.
        volumes: List of volumes.
        source: Data source identifier.
    """

    symbol: str
    timestamp: datetime
    opens: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    volumes: list[int] = field(default_factory=list)
    source: str = "unknown"

    def __len__(self) -> int:
        """Return number of data points."""
        return len(self.closes)

    @property
    def current_price(self) -> float | None:
        """Get the most recent close price."""
        return self.closes[-1] if self.closes else None

    @property
    def has_ohlc(self) -> bool:
        """Check if OHLC data is available."""
        return bool(self.opens and self.highs and self.lows and self.closes)

    @classmethod
    def from_klines(cls, bars: list[KlineBar]) -> "TechnicalData":
        """Create TechnicalData from a list of KlineBar.

        Args:
            bars: List of KlineBar sorted by timestamp (oldest first).

        Returns:
            TechnicalData instance with extracted OHLCV data.
        """
        if not bars:
            return cls(
                symbol="",
                timestamp=datetime.now(),
            )

        # Sort by timestamp to ensure correct order
        sorted_bars = sorted(bars, key=lambda x: x.timestamp)

        return cls(
            symbol=sorted_bars[-1].symbol,
            timestamp=sorted_bars[-1].timestamp,
            opens=[bar.open for bar in sorted_bars],
            highs=[bar.high for bar in sorted_bars],
            lows=[bar.low for bar in sorted_bars],
            closes=[bar.close for bar in sorted_bars],
            volumes=[bar.volume for bar in sorted_bars],
            source=sorted_bars[-1].source,
        )

    @classmethod
    def from_closes(
        cls,
        symbol: str,
        closes: list[float],
        timestamp: datetime | None = None,
    ) -> "TechnicalData":
        """Create TechnicalData from close prices only.

        Useful when only close prices are available (e.g., for MA/RSI).

        Args:
            symbol: Stock symbol.
            closes: List of close prices.
            timestamp: Data timestamp (defaults to now).

        Returns:
            TechnicalData instance with close prices only.
        """
        return cls(
            symbol=symbol,
            timestamp=timestamp or datetime.now(),
            closes=closes,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "opens": self.opens,
            "highs": self.highs,
            "lows": self.lows,
            "closes": self.closes,
            "volumes": self.volumes,
            "source": self.source,
        }

    def get_recent(self, n: int) -> "TechnicalData":
        """Get the most recent n data points.

        Args:
            n: Number of data points to retrieve.

        Returns:
            New TechnicalData with only the most recent n points.
        """
        return TechnicalData(
            symbol=self.symbol,
            timestamp=self.timestamp,
            opens=self.opens[-n:] if self.opens else [],
            highs=self.highs[-n:] if self.highs else [],
            lows=self.lows[-n:] if self.lows else [],
            closes=self.closes[-n:] if self.closes else [],
            volumes=self.volumes[-n:] if self.volumes else [],
            source=self.source,
        )
