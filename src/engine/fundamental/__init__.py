"""Fundamental analysis module."""

from src.engine.fundamental.metrics import (
    evaluate_fundamentals,
    get_analyst_rating,
    get_pe,
    get_profit_margin,
    get_revenue_growth,
)

__all__ = [
    "get_pe",
    "get_revenue_growth",
    "get_profit_margin",
    "get_analyst_rating",
    "evaluate_fundamentals",
]
