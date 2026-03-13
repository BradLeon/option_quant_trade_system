"""Account-Level Risk Guard.

Enforces account-level constraints:
- Max positions count
- Max margin utilization
- Cash/margin reserve check (asset-type aware):
  - Option entries: use NLV-based available margin (stock collateral allowed, Reg-T)
  - Stock entries: use raw cash (no leverage)

Accepts either AccountRiskConfig (legacy) or RiskConfig (unified).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.backtest.strategy.models import (
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)

logger = logging.getLogger(__name__)


@dataclass
class AccountRiskConfig:
    """Account risk guard configuration (legacy, prefer RiskConfig)."""
    max_positions: int = 20
    max_margin_utilization: float = 0.70
    min_cash_reserve_pct: float = 0.05  # Stock entries: keep 5% cash minimum
    min_available_margin: float = 10_000  # Option entries: min NLV-based available margin


def _extract_config(config: Any) -> AccountRiskConfig:
    """Extract AccountRiskConfig from RiskConfig or AccountRiskConfig."""
    if config is None:
        return AccountRiskConfig()
    if isinstance(config, AccountRiskConfig):
        return config
    # Assume RiskConfig — duck-type field extraction
    return AccountRiskConfig(
        max_positions=getattr(config, "max_positions", 20),
        max_margin_utilization=getattr(config, "max_margin_utilization", 0.70),
        min_cash_reserve_pct=getattr(config, "min_cash_reserve_pct", 0.05),
        min_available_margin=getattr(config, "min_available_margin", 10_000),
    )


class AccountRiskGuard:
    """Filters ENTRY signals that would violate account-level constraints.

    EXIT/ROLL signals are always passed through (reducing risk is always OK).

    Accepts either AccountRiskConfig or RiskConfig for initialization.
    """

    def __init__(self, config: AccountRiskConfig | Any | None = None) -> None:
        self._config = _extract_config(config)

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

            # Cash equivalent entries bypass position count and margin checks
            if signal.metadata.get("is_cash_equivalent", False):
                approved.append(signal)
                entry_count += 1
                continue

            # Check position count limit for entries
            current_count = sum(
                1 for p in portfolio.positions if not p.is_cash_equivalent
            ) + entry_count
            if current_count >= self._config.max_positions:
                logger.warning(
                    f"AccountRisk: blocked {signal.instrument.symbol} — "
                    f"max positions ({self._config.max_positions}) reached"
                )
                continue

            # Check margin utilization
            if portfolio.nlv > 0:
                margin_util = portfolio.margin_used / portfolio.nlv
                if margin_util >= self._config.max_margin_utilization:
                    logger.warning(
                        f"AccountRisk: blocked {signal.instrument.symbol} — "
                        f"margin utilization {margin_util:.1%} >= "
                        f"{self._config.max_margin_utilization:.1%}"
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
                        logger.warning(
                            f"AccountRisk: blocked {signal.instrument.symbol} — "
                            f"available margin ${available:,.0f} < "
                            f"min ${self._config.min_available_margin:,.0f}"
                        )
                        continue
                else:
                    # Stock entries: raw cash only (no leverage)
                    cash_pct = portfolio.cash / portfolio.nlv
                    if cash_pct < self._config.min_cash_reserve_pct:
                        logger.warning(
                            f"AccountRisk: blocked {signal.instrument.symbol} — "
                            f"cash {cash_pct:.1%} < min reserve "
                            f"{self._config.min_cash_reserve_pct:.1%}"
                        )
                        continue

            approved.append(signal)
            if signal.type == SignalType.ENTRY:
                entry_count += 1

        if len(approved) < len(signals):
            logger.warning(
                f"AccountRisk: {len(signals) - len(approved)} signals filtered "
                f"({len(approved)} approved)"
            )

        return approved
