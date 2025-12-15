"""Fundamental data models."""

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Fundamental:
    """Stock fundamental data model.

    Contains financial metrics and valuation data.
    """

    symbol: str
    date: date
    market_cap: float | None = None
    pe_ratio: float | None = None  # Price-to-Earnings ratio
    pb_ratio: float | None = None  # Price-to-Book ratio
    ps_ratio: float | None = None  # Price-to-Sales ratio
    dividend_yield: float | None = None
    eps: float | None = None  # Earnings per share
    revenue: float | None = None
    profit: float | None = None  # Net income
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    roe: float | None = None  # Return on equity
    roa: float | None = None  # Return on assets
    beta: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    avg_volume: int | None = None
    shares_outstanding: int | None = None
    # Growth metrics
    revenue_growth: float | None = None  # Revenue growth rate (YoY)
    earnings_growth: float | None = None  # Earnings growth rate (YoY)
    # Analyst ratings
    recommendation: str | None = None  # Analyst recommendation (buy/hold/sell)
    recommendation_mean: float | None = None  # Mean recommendation (1=Strong Buy, 5=Sell)
    analyst_count: int | None = None  # Number of analyst opinions
    target_price: float | None = None  # Mean target price
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "symbol": self.symbol,
            "date": self.date.isoformat(),
            "market_cap": self.market_cap,
            "pe_ratio": self.pe_ratio,
            "pb_ratio": self.pb_ratio,
            "ps_ratio": self.ps_ratio,
            "dividend_yield": self.dividend_yield,
            "eps": self.eps,
            "revenue": self.revenue,
            "profit": self.profit,
            "debt_to_equity": self.debt_to_equity,
            "current_ratio": self.current_ratio,
            "roe": self.roe,
            "revenue_growth": self.revenue_growth,
            "earnings_growth": self.earnings_growth,
            "recommendation": self.recommendation,
            "recommendation_mean": self.recommendation_mean,
            "analyst_count": self.analyst_count,
            "target_price": self.target_price,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Fundamental":
        """Create instance from dictionary."""
        data_date = data.get("date")
        if isinstance(data_date, str):
            data_date = date.fromisoformat(data_date)

        return cls(
            symbol=data["symbol"],
            date=data_date,
            market_cap=data.get("market_cap"),
            pe_ratio=data.get("pe_ratio"),
            pb_ratio=data.get("pb_ratio"),
            ps_ratio=data.get("ps_ratio"),
            dividend_yield=data.get("dividend_yield"),
            eps=data.get("eps"),
            revenue=data.get("revenue"),
            profit=data.get("profit"),
            gross_margin=data.get("gross_margin"),
            operating_margin=data.get("operating_margin"),
            profit_margin=data.get("profit_margin"),
            debt_to_equity=data.get("debt_to_equity"),
            current_ratio=data.get("current_ratio"),
            quick_ratio=data.get("quick_ratio"),
            roe=data.get("roe"),
            roa=data.get("roa"),
            beta=data.get("beta"),
            fifty_two_week_high=data.get("fifty_two_week_high"),
            fifty_two_week_low=data.get("fifty_two_week_low"),
            avg_volume=data.get("avg_volume"),
            shares_outstanding=data.get("shares_outstanding"),
            revenue_growth=data.get("revenue_growth"),
            earnings_growth=data.get("earnings_growth"),
            recommendation=data.get("recommendation"),
            recommendation_mean=data.get("recommendation_mean"),
            analyst_count=data.get("analyst_count"),
            target_price=data.get("target_price"),
            source=data.get("source", "unknown"),
        )

    @property
    def peg_ratio(self) -> float | None:
        """Calculate PEG ratio (PE / EPS growth rate).

        Note: Requires EPS growth rate which is not stored.
        Returns None as placeholder.
        """
        return None

    @property
    def enterprise_value(self) -> float | None:
        """Calculate approximate enterprise value.

        EV = Market Cap + Total Debt - Cash
        Note: Simplified calculation, actual requires debt and cash data.
        """
        return self.market_cap  # Simplified
