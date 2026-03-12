"""SMA Stock Timing Strategy — replaces SpyBuyAndHold + SpySma200Freq5.

Two old strategies (~526 lines combined) unified into one parameterized strategy (~80 lines).

Config differences:
- SpyBuyAndHoldSmaTiming → SmaStockConfig(comparison=PRICE_VS_SMA, decision_frequency=1)
- SpySma200Freq5Timing   → SmaStockConfig(comparison=SMA_CROSS, decision_frequency=5, short_period=50)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from src.backtest.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)
from src.backtest.strategy.protocol import BacktestStrategy
from src.backtest.strategy.signals.sma import SmaComparison, SmaComputer

logger = logging.getLogger(__name__)


@dataclass
class SmaStockConfig:
    """Configuration for SMA Stock Timing strategy."""

    name: str = "sma_stock"
    symbols: list[str] | None = None  # None → use first symbol from market
    sma_period: int = 200
    short_period: int = 50  # Only used in SMA_CROSS mode
    comparison: SmaComparison = SmaComparison.PRICE_VS_SMA
    decision_frequency: int = 1  # Every N trading days
    capital_allocation: float = 0.95  # % of cash to deploy


class SmaStockStrategy(BacktestStrategy):
    """SMA-timed stock strategy: buy when SMA is bullish, sell when bearish.

    Replaces:
    - SpyBuyAndHoldSmaTiming (price > SMA200, freq=1)
    - SpySma200Freq5Timing (SMA50 > SMA200, freq=5)
    """

    def __init__(self, config: SmaStockConfig | None = None) -> None:
        super().__init__()
        self._config = config or SmaStockConfig()
        self._sma = SmaComputer(
            period=self._config.sma_period,
            comparison=self._config.comparison,
            short_period=self._config.short_period,
        )

    @property
    def name(self) -> str:
        return self._config.name

    def compute_exit_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        if not portfolio.positions:
            self.log("exit_scan", "skip", reason="无持仓")
            return []

        if not self._is_decision_day(self._config.decision_frequency):
            self.log("exit_scan", "skip",
                     reason=f"非决策日 (day={self._trading_day_count} freq={self._config.decision_frequency})")
            return []

        result = self._sma.compute(market, data_provider)
        self._last_signal_detail = result

        sma_val = result.get("sma", 0)
        close = result.get("close", 0)
        mode = "SMA_CROSS" if self._config.comparison == SmaComparison.SMA_CROSS else "PRICE_VS_SMA"

        if result["invested"]:
            self.log("exit_scan:sma", "skip",
                     signal="bullish", mode=mode,
                     close=close, sma=sma_val,
                     reason="SMA看多，继续持有")
            return []

        self.log("exit_scan:sma", "pass",
                 signal="bearish", mode=mode,
                 close=close, sma=sma_val,
                 action=f"退出全部 {len(portfolio.positions)} 个持仓")

        # SMA bearish → exit all positions
        signals = []
        for pos in portfolio.positions:
            signals.append(Signal(
                type=SignalType.EXIT,
                instrument=pos.instrument,
                target_quantity=-pos.quantity,
                reason=f"SMA exit: {'death cross' if self._config.comparison == SmaComparison.SMA_CROSS else 'below SMA'}",
                position_id=pos.position_id,
                priority=10,
                metadata={"alert_type": "sma_exit"},
            ))

        return signals

    def compute_entry_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        # Don't enter if already holding
        if portfolio.positions:
            self.log("entry_signal", "skip", reason="已有持仓")
            return []

        if not self._is_decision_day(self._config.decision_frequency):
            self.log("entry_signal", "skip",
                     reason=f"非决策日 (day={self._trading_day_count} freq={self._config.decision_frequency})")
            return []

        result = self._sma.compute(market, data_provider)
        self._last_signal_detail = result

        sma_val = result.get("sma", 0)
        close = result.get("close", 0)
        mode = "SMA_CROSS" if self._config.comparison == SmaComparison.SMA_CROSS else "PRICE_VS_SMA"

        if not result["invested"]:
            self.log("entry_signal:sma", "fail",
                     signal="bearish", mode=mode,
                     close=close, sma=sma_val,
                     reason="SMA看空，不入场")
            return []

        # SMA bullish → buy stock
        symbol = result.get("symbol") or (self._config.symbols[0] if self._config.symbols else None)
        if not symbol:
            self.log("entry_signal", "fail", reason="无标的")
            return []

        price = market.get_price_or_zero(symbol)
        if price <= 0:
            self.log(f"entry_signal:{symbol}", "fail", reason=f"价格无效 price={price}")
            return []

        shares = math.floor(self._config.capital_allocation * portfolio.cash / price)
        if shares <= 0:
            self.log(f"entry_signal:{symbol}", "fail",
                     reason="资金不足", cash=portfolio.cash, price=price,
                     allocation=self._config.capital_allocation)
            return []

        self.log(f"entry_signal:{symbol}", "pass",
                 mode=mode, close=close, sma=sma_val,
                 shares=shares, price=price,
                 cost=shares * price, cash=portfolio.cash)

        instrument = Instrument(type=InstrumentType.STOCK, underlying=symbol, lot_size=1)

        return [Signal(
            type=SignalType.ENTRY,
            instrument=instrument,
            target_quantity=shares,
            reason=f"SMA entry: {shares}sh @ {price:.2f}",
            quote_price=price,
        )]
