"""Cross-Asset Signal Computer — multi-asset trend & volatility signals.

Computes per-asset trend (price vs SMA) and rolling volatility for
the All-Weather strategy's trend filter and inverse-vol weighting.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.strategy.models import MarketSnapshot

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetConfig:
    """Configuration for cross-asset signal computation."""

    sma_period: int = 200
    vol_lookback: int = 60
    use_inverse_vol: bool = True
    # Symbols to exclude from trend/vol computation (e.g. cash ETF)
    exclude_symbols: frozenset[str] = field(
        default_factory=lambda: frozenset({"SHV", "BIL", "SGOV", "SCHO"})
    )


class CrossAssetSignalComputer:
    """Computes trend signals and rolling volatility for each asset.

    For each non-cash symbol in market.prices:
    - Fetches historical prices from data_provider
    - Computes SMA for trend determination
    - Computes annualized rolling volatility

    Results are cached by date.
    """

    def __init__(self, config: CrossAssetConfig | None = None) -> None:
        self._config = config or CrossAssetConfig()
        self._cached_date: Optional[date] = None
        self._cached_result: dict = {}

    def compute(self, market: MarketSnapshot, data_provider: Any) -> dict:
        """Compute cross-asset signals.

        Returns:
            {
                "trends": {"SPY": True, "TLT": False, ...},
                "vols": {"SPY": 0.18, "TLT": 0.12, ...},
                "sma_values": {"SPY": 450.0, ...},
                "prices": {"SPY": 460.0, ...},
            }
        """
        if self._cached_date == market.date:
            return self._cached_result

        result = self._compute_impl(market, data_provider)
        self._cached_date = market.date
        self._cached_result = result
        return result

    def _compute_impl(self, market: MarketSnapshot, data_provider: Any) -> dict:
        cfg = self._config
        trends: dict[str, bool] = {}
        vols: dict[str, float] = {}
        sma_values: dict[str, float] = {}
        prices: dict[str, float] = {}

        for symbol, price in market.prices.items():
            if symbol in cfg.exclude_symbols or price <= 0:
                continue

            prices[symbol] = price
            close_series = self._fetch_prices(symbol, market.date, data_provider)

            if close_series is None or len(close_series) < cfg.sma_period:
                # Insufficient data: assume no trend, use fallback vol
                trends[symbol] = False
                vols[symbol] = 0.20  # 20% fallback
                continue

            # SMA trend
            from src.engine.position.technical.moving_average import calc_sma

            sma = calc_sma(close_series, cfg.sma_period)
            if sma is not None:
                sma_values[symbol] = sma
                trends[symbol] = close_series[-1] > sma
            else:
                trends[symbol] = False

            # Rolling volatility (annualized)
            vol = self._calc_rolling_vol(close_series, cfg.vol_lookback)
            vols[symbol] = vol if vol is not None else 0.20

        return {
            "trends": trends,
            "vols": vols,
            "sma_values": sma_values,
            "prices": prices,
        }

    def _fetch_prices(
        self, symbol: str, as_of_date: date, data_provider: Any
    ) -> Optional[list[float]]:
        """Fetch historical close prices from data provider."""
        from src.data.models.stock import KlineType

        lookback_start = as_of_date - timedelta(days=self._config.sma_period * 2)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=as_of_date,
        )
        if not klines:
            return None
        return [k.close for k in klines]

    @staticmethod
    def _calc_rolling_vol(prices: list[float], lookback: int) -> Optional[float]:
        """Calculate annualized rolling volatility from log returns."""
        if len(prices) < lookback + 1:
            return None

        recent = prices[-(lookback + 1):]
        log_returns = []
        for i in range(1, len(recent)):
            if recent[i - 1] > 0 and recent[i] > 0:
                log_returns.append(math.log(recent[i] / recent[i - 1]))

        if len(log_returns) < 10:
            return None

        mean = sum(log_returns) / len(log_returns)
        variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
        return math.sqrt(variance * 252)
