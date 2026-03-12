"""Backtest Strategy Protocol & Base Class

StrategyProtocol and Strategy base class are defined in the shared layer
(src/strategy/protocol.py). This file provides BacktestStrategy, which
extends Strategy with backtest-specific features.
"""

from __future__ import annotations

from typing import Any

from src.strategy.models import (  # noqa: F401
    MarketSnapshot,
    PortfolioState,
    Signal,
)
from src.strategy.protocol import Strategy, StrategyProtocol  # noqa: F401


class BacktestStrategy(Strategy):
    """Backtest-specific strategy base class.

    Extends Strategy with backtest-only features:
    - requires_synthetic_data: whether LEAPS synthetic data is needed

    All template-method hooks (on_day_start, compute_exit_signals, etc.)
    are inherited from Strategy.
    """

    @property
    def requires_synthetic_data(self) -> bool:
        """Whether this strategy needs SyntheticLeapsProvider for historical LEAPS data.

        Override to return True in strategies that use get_option_chain()
        for LEAPS options (DTE > 180 days). Without synthetic data,
        backtests before ThetaData coverage (2023-06) will have no option data.
        """
        return False
