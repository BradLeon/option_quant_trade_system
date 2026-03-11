"""Shared Mixin: 7-point momentum scoring + Vol Target + LEAPS contract selection.

Extracted from SpyLeapsOnlyVolTarget and SpyMomentumLevVolTarget to eliminate
~250 lines of identical code between the two strategies.

Provides:
- _compute_signal: 7-point momentum score + vol_scalar risk adjustment
- _get_vix: VIX data retrieval with fallback
- _is_leaps: LEAPS position identification
- _select_best_contract: Best-match LEAPS contract selection
- _is_decision_day / _rebalance_cooldown_ok: Trading frequency controls
- _resolve_spot: Underlying price resolution from position or context
- _compute_leaps_target_contracts: Target LEAPS contracts from target_pct
"""

import logging
import math
from datetime import date, timedelta
from typing import Any, List, Optional

from src.business.monitoring.models import PositionData
from src.business.strategy.models import MarketContext

logger = logging.getLogger(__name__)

# Contract selection weights
W_DTE = 1.0
W_STRIKE = 2.0

# Default position map: momentum score → target exposure %
DEFAULT_POSITION_MAP = {
    0: 0.0,
    1: 0.0,
    2: 0.5,
    3: 1.0,
    4: 1.5,
    5: 2.0,
    6: 2.5,
    7: 3.0,
}


class MomentumVolTargetMixin:
    """7-point momentum scoring + Vol Target shared logic.

    Requires host class to provide:
    - self._ensure_config_loaded(): returns config with sma_periods, momentum_lookback_*,
      position_map, vol_target, vol_scalar_max, max_exposure, min_dte, max_dte,
      target_dte, decision_frequency, min_rebalance_interval
    - self._signal_computed_for_date, self._current_target_pct, self._last_signal_detail
    - self._trading_day_count, self._last_rebalance_day, self._last_nlv
    """

    _signal_log_prefix: str = "MomVol"

    # --- Signal computation ---

    def _compute_signal(self, context: MarketContext, data_provider: Any) -> float:
        """Compute risk-adjusted target position pct, cached by date."""
        if self._signal_computed_for_date == context.current_date:
            return self._current_target_pct

        cfg = self._ensure_config_loaded()

        symbols = list(context.underlying_prices.keys())
        if not symbols:
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        symbol = symbols[0]

        from src.data.models.stock import KlineType
        from src.engine.position.technical.moving_average import calc_sma_series

        max_sma = max(cfg.sma_periods)
        lookback_days = max(max_sma, cfg.momentum_lookback_long) * 2 + 50
        lookback_start = context.current_date - timedelta(days=lookback_days)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=context.current_date,
        )

        if not klines or len(klines) < max_sma:
            logger.info(
                f"{self._signal_log_prefix}: insufficient price data "
                f"({len(klines) if klines else 0} < {max_sma})"
            )
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        prices = [k.close for k in klines]

        sma_values = {}
        for period in cfg.sma_periods:
            series = calc_sma_series(prices, period)
            sma_values[period] = series[-1] if series and series[-1] is not None else None

        sma20 = sma_values.get(20)
        sma50 = sma_values.get(50)
        sma200 = sma_values.get(200)

        if sma20 is None or sma50 is None or sma200 is None:
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

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

        target_pct = cfg.position_map.get(score, 0.0)
        if target_pct == 0.0:
            self._last_signal_detail = {
                "momentum_score": score, "sma20": sma20, "sma50": sma50,
                "sma200": sma200, "close": close, "vix": 0.0,
                "vol_scalar": 0.0, "raw_target": 0.0, "target_pct": 0.0,
            }
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        # === Vol Target risk adjustment ===
        vix = self._get_vix(context, data_provider)
        vol_scalar = min(cfg.vol_scalar_max, cfg.vol_target / vix) if vix > 0 else 1.0
        target_pct = target_pct * vol_scalar
        target_pct = max(0.0, min(cfg.max_exposure, target_pct))

        logger.debug(
            f"{self._signal_log_prefix} signal: {symbol} score={score} "
            f"raw_map={cfg.position_map.get(score, 0)} "
            f"vix={vix:.1f} vol_scalar={vol_scalar:.2f} → target_pct={target_pct:.2f}"
        )

        self._last_signal_detail = {
            "momentum_score": score,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "close": close,
            "vix": vix,
            "vol_scalar": vol_scalar,
            "raw_target": cfg.position_map.get(score, 0.0),
            "target_pct": target_pct,
        }

        self._current_target_pct = target_pct
        self._signal_computed_for_date = context.current_date
        return target_pct

    def _get_vix(self, context: MarketContext, data_provider: Any) -> float:
        """Get current VIX, default 20.0 if unavailable."""
        try:
            lookback = context.current_date - timedelta(days=10)
            vix_data = data_provider.get_macro_data("^VIX", lookback, context.current_date)
            if vix_data and len(vix_data) > 0:
                return vix_data[-1].close
        except Exception:
            pass
        return 20.0

    # --- Position identification ---

    @staticmethod
    def _is_leaps(pos: PositionData) -> bool:
        return (
            pos.option_type is not None
            and pos.option_type.lower() == "call"
            and pos.strike is not None
            and pos.strike >= 1.0
            and (pos.quantity or 0) > 0
        )

    # --- Contract selection ---

    def _select_best_contract(
        self,
        calls: list,
        target_strike: float,
        target_dte: int,
        current_date: date,
    ) -> Optional[Any]:
        """Select best-matching LEAPS Call from option chain."""
        cfg = self._ensure_config_loaded()
        best_score = -float("inf")
        best = None

        for call in calls:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days

            if dte < cfg.min_dte or dte > cfg.max_dte:
                continue

            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if mid is None or mid <= 0:
                continue

            delta = call.greeks.delta if call.greeks else None
            if delta is None or delta <= 0:
                continue

            dte_dev = abs(dte - target_dte) / target_dte if target_dte > 0 else 0
            strike_dev = abs(contract.strike_price - target_strike) / target_strike if target_strike > 0 else 0
            score = -W_DTE * dte_dev - W_STRIKE * strike_dev

            if score > best_score:
                best_score = score
                best = call

        return best

    # --- Utility methods ---

    def _is_decision_day(self) -> bool:
        cfg = self._ensure_config_loaded()
        return self._trading_day_count % cfg.decision_frequency == 0

    def _rebalance_cooldown_ok(self) -> bool:
        cfg = self._ensure_config_loaded()
        return (self._trading_day_count - self._last_rebalance_day) >= cfg.min_rebalance_interval

    def _resolve_spot(self, pos: PositionData, context: MarketContext) -> float:
        """Resolve underlying spot price from position or context."""
        spot = pos.underlying_price
        if spot is None:
            symbol = pos.symbol.split("_")[0] if "_" in pos.symbol else pos.symbol
            spot = context.underlying_prices.get(symbol, 0)
        return spot

    def _compute_leaps_target_contracts(
        self,
        target_pct: float,
        rep_pos: PositionData,
        context: MarketContext,
        default_delta: float = 0.8,
    ) -> int:
        """Compute target LEAPS contracts from target_pct using representative position.

        Returns 0 when delta/spot/nlv are invalid (computation not meaningful).
        """
        rep_delta = rep_pos.delta or default_delta
        rep_multiplier = rep_pos.contract_multiplier or 100
        rep_spot = self._resolve_spot(rep_pos, context)

        if rep_delta <= 0 or rep_spot <= 0 or self._last_nlv <= 0:
            return 0

        return math.floor(target_pct * self._last_nlv / (rep_delta * rep_multiplier * rep_spot))
