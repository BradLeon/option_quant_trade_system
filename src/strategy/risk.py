"""Risk Guard Protocol — pluggable risk middleware.

Shared by both backtest and live trading executors.
"""

from __future__ import annotations

from typing import Protocol

from src.strategy.models import MarketSnapshot, PortfolioState, Signal


class RiskGuard(Protocol):
    """Risk guard: filters or modifies signals between strategy and execution.

    The executor calls guards in sequence:
        for guard in risk_chain:
            signals = guard.check(signals, portfolio, market)
    """

    def check(
        self,
        signals: list[Signal],
        portfolio: PortfolioState,
        market: MarketSnapshot,
    ) -> list[Signal]:
        """Filter/modify signals. Returns approved signals."""
        ...
