"""Option data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.data.models.margin import MarginRequirement


class OptionType(Enum):
    """Option type: Call or Put."""

    CALL = "call"
    PUT = "put"


@dataclass
class Greeks:
    """Option Greeks values."""

    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        """Convert to dictionary."""
        return {
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Greeks":
        """Create instance from dictionary."""
        return cls(
            delta=data.get("delta"),
            gamma=data.get("gamma"),
            theta=data.get("theta"),
            vega=data.get("vega"),
            rho=data.get("rho"),
        )


@dataclass
class OptionContract:
    """Option contract basic information."""

    symbol: str  # Option symbol (e.g., AAPL230120C00150000)
    underlying: str  # Underlying symbol (e.g., AAPL)
    option_type: OptionType
    strike_price: float
    expiry_date: date
    lot_size: int = 100  # Shares per contract
    trading_class: str | None = None  # IBKR trading class (e.g., "TCH" for HK 700)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "option_type": self.option_type.value,
            "strike_price": self.strike_price,
            "expiry_date": self.expiry_date.isoformat(),
            "lot_size": self.lot_size,
        }
        if self.trading_class:
            result["trading_class"] = self.trading_class
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OptionContract":
        """Create instance from dictionary."""
        expiry = data.get("expiry_date")
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)

        option_type = data.get("option_type")
        if isinstance(option_type, str):
            option_type = OptionType(option_type)

        return cls(
            symbol=data["symbol"],
            underlying=data["underlying"],
            option_type=option_type,
            strike_price=data["strike_price"],
            expiry_date=expiry,
            lot_size=data.get("lot_size", 100),
            trading_class=data.get("trading_class"),
        )

    @property
    def days_to_expiry(self) -> int:
        """Calculate days until expiration."""
        return (self.expiry_date - date.today()).days


@dataclass
class OptionQuote:
    """Option quote data with Greeks.

    Represents real-time or delayed option quote data.
    """

    contract: OptionContract
    timestamp: datetime
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    volume: int | None = None
    open_interest: int | None = None
    iv: float | None = None  # Implied volatility
    greeks: Greeks = field(default_factory=Greeks)
    source: str = "unknown"
    margin: MarginRequirement | None = None  # Margin requirement for short position

    # 用于回测的 OHLC 价格字段 (从 EOD 数据填充)
    open: float | None = None  # 开盘价
    high: float | None = None  # 最高价
    low: float | None = None  # 最低价
    close: float | None = None  # 收盘价 (通常等于 last_price)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        result = {
            "symbol": self.contract.symbol,
            "underlying": self.contract.underlying,
            "option_type": self.contract.option_type.value,
            "strike_price": self.contract.strike_price,
            "expiry_date": self.contract.expiry_date.isoformat(),
            "timestamp": self.timestamp.isoformat(),
            "last_price": self.last_price,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "iv": self.iv,
            "delta": self.greeks.delta,
            "gamma": self.greeks.gamma,
            "theta": self.greeks.theta,
            "vega": self.greeks.vega,
            "rho": self.greeks.rho,
            "source": self.source,
        }
        if self.margin:
            result["margin"] = self.margin.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OptionQuote":
        """Create instance from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        contract = OptionContract(
            symbol=data["symbol"],
            underlying=data["underlying"],
            option_type=OptionType(data["option_type"]),
            strike_price=data["strike_price"],
            expiry_date=(
                date.fromisoformat(data["expiry_date"])
                if isinstance(data["expiry_date"], str)
                else data["expiry_date"]
            ),
        )

        greeks = Greeks(
            delta=data.get("delta"),
            gamma=data.get("gamma"),
            theta=data.get("theta"),
            vega=data.get("vega"),
            rho=data.get("rho"),
        )

        # Parse margin if present
        margin = None
        if "margin" in data and data["margin"]:
            from src.data.models.margin import MarginRequirement
            margin = MarginRequirement.from_dict(data["margin"])

        return cls(
            contract=contract,
            timestamp=timestamp,
            last_price=data.get("last_price"),
            bid=data.get("bid"),
            ask=data.get("ask"),
            volume=data.get("volume"),
            open_interest=data.get("open_interest"),
            iv=data.get("iv"),
            greeks=greeks,
            source=data.get("source", "unknown"),
            margin=margin,
        )

    @property
    def mid_price(self) -> float | None:
        """Calculate mid price from bid and ask."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last_price


@dataclass
class OptionChain:
    """Option chain for an underlying asset.

    Contains all available option contracts for a symbol.
    """

    underlying: str
    timestamp: datetime
    expiry_dates: list[date] = field(default_factory=list)
    calls: list[OptionQuote] = field(default_factory=list)
    puts: list[OptionQuote] = field(default_factory=list)
    source: str = "unknown"

    def filter_by_expiry(self, expiry: date) -> "OptionChain":
        """Filter options by expiry date."""
        return OptionChain(
            underlying=self.underlying,
            timestamp=self.timestamp,
            expiry_dates=[expiry] if expiry in self.expiry_dates else [],
            calls=[c for c in self.calls if c.contract.expiry_date == expiry],
            puts=[p for p in self.puts if p.contract.expiry_date == expiry],
            source=self.source,
        )

    def filter_by_delta_range(
        self, min_delta: float, max_delta: float
    ) -> "OptionChain":
        """Filter options by delta range."""
        return OptionChain(
            underlying=self.underlying,
            timestamp=self.timestamp,
            expiry_dates=self.expiry_dates,
            calls=[
                c
                for c in self.calls
                if c.greeks.delta is not None
                and min_delta <= c.greeks.delta <= max_delta
            ],
            puts=[
                p
                for p in self.puts
                if p.greeks.delta is not None
                and min_delta <= abs(p.greeks.delta) <= max_delta
            ],
            source=self.source,
        )

    def get_atm_options(self, spot_price: float) -> tuple[OptionQuote | None, OptionQuote | None]:
        """Get at-the-money call and put options.

        Returns the call and put with strike price closest to spot price.
        """
        atm_call = None
        atm_put = None
        min_call_diff = float("inf")
        min_put_diff = float("inf")

        for call in self.calls:
            diff = abs(call.contract.strike_price - spot_price)
            if diff < min_call_diff:
                min_call_diff = diff
                atm_call = call

        for put in self.puts:
            diff = abs(put.contract.strike_price - spot_price)
            if diff < min_put_diff:
                min_put_diff = diff
                atm_put = put

        return atm_call, atm_put
