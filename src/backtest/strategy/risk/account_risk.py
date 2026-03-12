"""Account-Level Risk Guard.

Enforces account-level constraints:
- Max positions count
- Max margin utilization
- Cash/margin reserve check (asset-type aware):
  - Option entries: use NLV-based available margin (stock collateral allowed, Reg-T)
  - Stock entries: use raw cash (no leverage)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.backtest.strategy.models import (
    InstrumentType,
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
    min_cash_reserve_pct: float = 0.05  # Stock entries: keep 5% cash minimum
    min_available_margin: float = 10_000  # Option entries: min NLV-based available margin


class AccountRiskGuard:
    """Filters ENTRY signals that would violate account-level constraints.

    EXIT/ROLL signals are always passed through (reducing risk is always OK).

    Cash check is asset-type aware:
    - Option entries use NLV-based available margin (stock collateral counts,
      matching Reg-T margin lending in real brokerages like IBKR).
    - Stock entries use raw cash (no leverage allowed).
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

            # Asset-type aware capital check
            if portfolio.nlv > 0 and signal.type == SignalType.ENTRY:
                if signal.instrument.is_option:
                    # Option entries: NLV-based available margin (stock collateral allowed)
                    available = (
                        portfolio.nlv * self._config.max_margin_utilization
                        - portfolio.margin_used
                    )
                    if available < self._config.min_available_margin:
                        logger.debug(
                            f"AccountRisk: blocked {signal.instrument.symbol} — "
                            f"available margin ${available:,.0f} < "
                            f"min ${self._config.min_available_margin:,.0f}"
                        )
                        continue
                else:
                    # Stock entries: raw cash only (no leverage)
                    cash_pct = portfolio.cash / portfolio.nlv
                    if cash_pct < self._config.min_cash_reserve_pct:
                        logger.debug(
                            f"AccountRisk: blocked {signal.instrument.symbol} — "
                            f"cash {cash_pct:.1%} < min reserve "
                            f"{self._config.min_cash_reserve_pct:.1%}"
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
