"""Momentum + Vol Target Signal Computer.

Extracted from _momentum_vol_mixin.py. Provides:
- 7-point momentum score (5 SMA + 2 momentum lookback)
- Position map: score → raw target exposure %
- Vol Target: vol_scalar = min(max_scalar, vol_target / VIX)
- Final target_pct = raw * vol_scalar, capped at max_exposure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.backtest.strategy.models import MarketSnapshot

logger = logging.getLogger(__name__)

# Default position map: momentum score → target exposure %
DEFAULT_POSITION_MAP: dict[int, float] = {
    0: 0.0,
    1: 0.0,
    2: 0.5,
    3: 1.0,
    4: 1.5,
    5: 2.0,
    6: 2.5,
    7: 3.0,
}


@dataclass
class MomentumConfig:
    """Configuration for MomentumVolTargetComputer."""

    sma_periods: tuple[int, ...] = (20, 50, 200)
    momentum_lookback_short: int = 20
    momentum_lookback_long: int = 60
    position_map: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_POSITION_MAP))

    vol_target: float = 15.0
    vol_scalar_max: float = 2.0
    max_exposure: float = 3.0


class MomentumVolTargetComputer:
    """7-point momentum scoring + Vol Target risk adjustment.

    Reused by MomentumMixedStrategy (stock+leaps and leaps-only variants).
    """

    def __init__(self, config: Optional[MomentumConfig] = None) -> None:
        self._config = config or MomentumConfig()

        # Cache
        self._cached_date: Optional[date] = None
        self._cached_result: dict = {}

    def compute(self, market: MarketSnapshot, data_provider: Any) -> dict:
        """Compute momentum + vol target signal.

        Returns:
            {
                "target_pct": float,           # Risk-adjusted target exposure (0 to max_exposure)
                "momentum_score": int,          # Raw 7-point score (0..7)
                "raw_target": float,            # Position map value before vol adjustment
                "vol_scalar": float,            # Vol target multiplier
                "vix": float,                   # Current VIX value
                "close": float,                 # Latest close price
                "sma20": float, "sma50": float, "sma200": float,
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
        cfg = self._config
        empty = {
            "target_pct": 0.0, "momentum_score": 0, "raw_target": 0.0,
            "vol_scalar": 0.0, "vix": 0.0, "close": 0.0,
            "sma20": 0.0, "sma50": 0.0, "sma200": 0.0, "symbol": "",
        }

        symbols = list(market.prices.keys())
        if not symbols:
            return empty

        symbol = symbols[0]

        # Fetch price series
        prices = self._fetch_prices(symbol, market.date, data_provider)
        max_sma = max(cfg.sma_periods)
        if prices is None or len(prices) < max_sma:
            logger.debug(
                f"Momentum: insufficient data for {symbol} "
                f"({len(prices) if prices else 0} < {max_sma})"
            )
            return {**empty, "symbol": symbol}

        # Compute SMA values
        from src.engine.position.technical.moving_average import calc_sma_series

        sma_values: dict[int, Optional[float]] = {}
        for period in cfg.sma_periods:
            series = calc_sma_series(prices, period)
            sma_values[period] = series[-1] if series and series[-1] is not None else None

        sma20 = sma_values.get(20)
        sma50 = sma_values.get(50)
        sma200 = sma_values.get(200)

        if sma20 is None or sma50 is None or sma200 is None:
            return {**empty, "symbol": symbol, "close": prices[-1]}

        close = prices[-1]

        # === 7-point momentum score ===
        score = 0
        if close > sma20:
            score += 1
        if close > sma50:
            score += 1
        if close > sma200:
            score += 1
        if sma20 > sma50:
            score += 1
        if sma50 > sma200:
            score += 1
        if len(prices) > cfg.momentum_lookback_short and close > prices[-1 - cfg.momentum_lookback_short]:
            score += 1
        if len(prices) > cfg.momentum_lookback_long and close > prices[-1 - cfg.momentum_lookback_long]:
            score += 1

        raw_target = cfg.position_map.get(score, 0.0)
        if raw_target == 0.0:
            return {
                "target_pct": 0.0, "momentum_score": score, "raw_target": 0.0,
                "vol_scalar": 0.0, "vix": 0.0, "close": close,
                "sma20": sma20, "sma50": sma50, "sma200": sma200, "symbol": symbol,
            }

        # === Vol Target risk adjustment ===
        vix = self._get_vix(market, data_provider)
        vol_scalar = min(cfg.vol_scalar_max, cfg.vol_target / vix) if vix > 0 else 1.0
        target_pct = raw_target * vol_scalar
        target_pct = max(0.0, min(cfg.max_exposure, target_pct))

        logger.debug(
            f"Momentum signal: {symbol} score={score} raw={raw_target:.1f} "
            f"vix={vix:.1f} vol_scalar={vol_scalar:.2f} → target={target_pct:.2f}"
        )

        return {
            "target_pct": target_pct,
            "momentum_score": score,
            "raw_target": raw_target,
            "vol_scalar": vol_scalar,
            "vix": vix,
            "close": close,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "symbol": symbol,
        }

    def _fetch_prices(
        self, symbol: str, as_of_date: date, data_provider: Any
    ) -> Optional[list[float]]:
        from src.data.models.stock import KlineType

        cfg = self._config
        max_sma = max(cfg.sma_periods)
        lookback_days = max(max_sma, cfg.momentum_lookback_long) * 2 + 50
        lookback_start = as_of_date - timedelta(days=lookback_days)

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
    def _get_vix(market: MarketSnapshot, data_provider: Any) -> float:
        """Get current VIX, defaulting to 20.0 if unavailable."""
        if market.vix is not None and market.vix > 0:
            return market.vix
        try:
            lookback = market.date - timedelta(days=10)
            vix_data = data_provider.get_macro_data("^VIX", lookback, market.date)
            if vix_data and len(vix_data) > 0:
                return vix_data[-1].close
        except Exception:
            pass
        return 20.0
