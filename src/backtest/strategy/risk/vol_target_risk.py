"""Volatility Target Risk Guard.

Adjusts ENTRY signal quantities based on VIX regime:
- High VIX → reduce position sizes
- Low VIX → allow full sizes

This guard acts as a portfolio-level overlay, not a per-strategy concern.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from src.backtest.strategy.models import (
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)

logger = logging.getLogger(__name__)


@dataclass
class VolTargetRiskConfig:
    """Vol target risk guard configuration."""
    vol_target: float = 15.0      # Target portfolio vol
    vol_scalar_max: float = 2.0   # Max scaling factor
    vix_threshold: float = 30.0   # Above this, reduce entries aggressively


class VolTargetRiskGuard:
    """Scales ENTRY signal quantities based on VIX regime.

    Does NOT modify EXIT/ROLL signals.
    """

    def __init__(self, config: VolTargetRiskConfig | None = None) -> None:
        self._config = config or VolTargetRiskConfig()

    def check(
        self,
        signals: list[Signal],
        portfolio: PortfolioState,
        market: MarketSnapshot,
    ) -> list[Signal]:
        vix = market.vix
        if vix is None or vix <= 0:
            return signals  # No VIX data, pass through

        cfg = self._config
        vol_scalar = min(cfg.vol_scalar_max, cfg.vol_target / vix)

        # Only scale if VIX is elevated
        if vol_scalar >= 1.0:
            return signals

        approved: list[Signal] = []
        for signal in signals:
            if signal.type != SignalType.ENTRY:
                approved.append(signal)
                continue

            # Scale down entry quantity
            original_qty = signal.target_quantity
            scaled_qty = int(math.copysign(
                max(1, abs(original_qty) * vol_scalar),
                original_qty
            )) if original_qty != 0 else 0

            if scaled_qty == 0:
                logger.debug(
                    f"VolTargetRisk: blocked {signal.instrument.symbol} — "
                    f"VIX={vix:.1f} scaled qty to 0"
                )
                continue

            if scaled_qty != original_qty:
                # Create new signal with adjusted quantity
                adjusted = Signal(
                    type=signal.type,
                    instrument=signal.instrument,
                    target_quantity=scaled_qty,
                    reason=f"{signal.reason} [vol-scaled: {original_qty}→{scaled_qty}, VIX={vix:.1f}]",
                    position_id=signal.position_id,
                    roll_to=signal.roll_to,
                    priority=signal.priority,
                    metadata={**signal.metadata, "vol_scalar": vol_scalar, "original_qty": original_qty},
                    quote_price=signal.quote_price,
                    greeks=signal.greeks,
                )
                approved.append(adjusted)
            else:
                approved.append(signal)

        return approved
