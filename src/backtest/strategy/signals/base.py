"""Signal Computer Protocol — composable signal calculation components."""

from __future__ import annotations

from typing import Any, Protocol

from src.backtest.strategy.models import MarketSnapshot


class SignalComputer(Protocol):
    """Protocol for composable signal computation.

    Each computer calculates structured signal data (dict) from market data.
    Results are cached by date to avoid redundant computation.
    """

    def compute(self, market: MarketSnapshot, data_provider: Any) -> dict:
        """Compute signal data for the given market date.

        Returns:
            Structured signal dict. Keys/shape depend on the specific computer.
        """
        ...
