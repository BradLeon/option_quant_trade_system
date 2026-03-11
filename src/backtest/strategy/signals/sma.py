"""SMA Signal Computer — reusable SMA-based timing signal.

Extracted from SpyBuyAndHoldSmaTiming and SpySma200Freq5Timing.
Supports two comparison modes:
- price_vs_sma: close > SMA(period) → invested
- sma_cross: SMA(short_period) > SMA(long_period) → invested
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from enum import Enum
from typing import Any, Optional

from src.backtest.strategy.models import MarketSnapshot

logger = logging.getLogger(__name__)


class SmaComparison(str, Enum):
    """SMA signal comparison mode."""
    PRICE_VS_SMA = "price_vs_sma"  # close > SMA(period)
    SMA_CROSS = "sma_cross"         # SMA(short) > SMA(long)


class SmaComputer:
    """Computes SMA-based invested/cash signal.

    Args:
        period: Main SMA period (default 200).
        comparison: How to generate the signal.
        short_period: Short SMA period (only used in SMA_CROSS mode, default 50).
    """

    def __init__(
        self,
        period: int = 200,
        comparison: SmaComparison = SmaComparison.PRICE_VS_SMA,
        short_period: int = 50,
    ) -> None:
        self._period = period
        self._comparison = comparison
        self._short_period = short_period

        # Cache
        self._cached_date: Optional[date] = None
        self._cached_result: dict = {}

    @property
    def period(self) -> int:
        return self._period

    def compute(self, market: MarketSnapshot, data_provider: Any) -> dict:
        """Compute SMA signal.

        Returns:
            {
                "invested": bool,      # True = bullish signal
                "close": float,        # Last close price
                "sma_long": float,     # SMA(period) value
                "sma_short": float,    # SMA(short_period), only in SMA_CROSS mode
                "symbol": str,
            }
        """
        if self._cached_date == market.date:
            return self._cached_result

        result = self._compute_impl(market, data_provider)
        self._cached_date = market.date
        self._cached_result = result
        return result

    def _compute_impl(self, market: MarketSnapshot, data_provider: Any) -> dict:
        """Internal computation — no caching."""
        empty = {"invested": False, "close": 0.0, "sma_long": 0.0, "sma_short": 0.0, "symbol": ""}

        symbols = list(market.prices.keys())
        if not symbols:
            return empty

        symbol = symbols[0]
        prices = self._fetch_prices(symbol, market.date, data_provider)
        if prices is None or len(prices) < self._period:
            logger.debug(
                f"SMA: insufficient data for {symbol} "
                f"({len(prices) if prices else 0} < {self._period})"
            )
            return {**empty, "symbol": symbol}

        from src.engine.position.technical.moving_average import calc_sma

        close = prices[-1]
        sma_long = calc_sma(prices, self._period)
        if sma_long is None:
            return {**empty, "symbol": symbol, "close": close}

        if self._comparison == SmaComparison.PRICE_VS_SMA:
            invested = close > sma_long
            return {
                "invested": invested,
                "close": close,
                "sma_long": sma_long,
                "sma_short": 0.0,
                "symbol": symbol,
            }
        else:  # SMA_CROSS
            sma_short = calc_sma(prices, self._short_period)
            if sma_short is None:
                return {**empty, "symbol": symbol, "close": close, "sma_long": sma_long}
            invested = sma_short > sma_long
            return {
                "invested": invested,
                "close": close,
                "sma_long": sma_long,
                "sma_short": sma_short,
                "symbol": symbol,
            }

    def _fetch_prices(
        self, symbol: str, as_of_date: date, data_provider: Any
    ) -> Optional[list[float]]:
        """Fetch price series from data provider."""
        from src.data.models.stock import KlineType

        lookback_start = as_of_date - timedelta(days=self._period * 2)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=as_of_date,
        )
        if not klines:
            return None
        return [k.close for k in klines]
