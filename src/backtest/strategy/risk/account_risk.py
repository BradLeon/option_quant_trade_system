"""Account-Level Risk Guard.

Enforces account-level constraints:
- Max positions count
- Max margin utilization
- Min cash reserve
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.backtest.strategy.models import (
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)

logger = logging.getLogger(__name__)


@dataclass
class AccountRiskConfig:
    """Account risk guard configuration."""
    max_positions: int = 20
    max_margin_utilization: float = 0.70
    min_cash_reserve_pct: float = 0.05  # Keep 5% cash minimum


class AccountRiskGuard:
    """Filters ENTRY signals that would violate account-level constraints.

    EXIT/ROLL signals are always passed through (reducing risk is always OK).
    """

    def __init__(self, config: AccountRiskConfig | None = None) -> None:
        self._config = config or AccountRiskConfig()

    def check(
        self,
        signals: list[Signal],
        portfolio: PortfolioState,
        market: MarketSnapshot,
    ) -> list[Signal]:
        approved: list[Signal] = []
        entry_count = 0

        for signal in signals:
            # Always allow exits and rolls
            if signal.type in (SignalType.EXIT, SignalType.ROLL):
                approved.append(signal)
                continue

            # Check position count limit for entries
            current_count = portfolio.position_count + entry_count
            if current_count >= self._config.max_positions:
                logger.debug(
                    f"AccountRisk: blocked {signal.instrument.symbol} — "
                    f"max positions ({self._config.max_positions}) reached"
                )
                continue

            # Check margin utilization
            if portfolio.nlv > 0:
                margin_util = portfolio.margin_used / portfolio.nlv
                if margin_util >= self._config.max_margin_utilization:
                    logger.debug(
                        f"AccountRisk: blocked {signal.instrument.symbol} — "
                        f"margin utilization {margin_util:.1%} >= {self._config.max_margin_utilization:.1%}"
                    )
                    continue

            # Check cash reserve
            if portfolio.nlv > 0:
                cash_pct = portfolio.cash / portfolio.nlv
                if cash_pct < self._config.min_cash_reserve_pct and signal.type == SignalType.ENTRY:
                    logger.debug(
                        f"AccountRisk: blocked {signal.instrument.symbol} — "
                        f"cash {cash_pct:.1%} < min reserve {self._config.min_cash_reserve_pct:.1%}"
                    )
                    continue

            approved.append(signal)
            if signal.type == SignalType.ENTRY:
                entry_count += 1

        if len(approved) < len(signals):
            logger.info(
                f"AccountRisk: {len(signals) - len(approved)} signals filtered "
                f"({len(approved)} approved)"
            )

        return approved
