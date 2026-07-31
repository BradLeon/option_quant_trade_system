"""All-Weather Multi-Asset Allocation Strategy.

Trend-following + inverse-volatility weighting across a diversified ETF universe.

Core logic:
  - Each asset's trend is independently evaluated (price > SMA200 → hold, else → cash)
  - Active assets are weighted by inverse volatility (lower vol → higher weight)
  - Monthly rebalancing, with 5% drift threshold for interim rebalances
  - Cash (SHV) absorbs weight from assets with bearish trends

Asset universe (Bridgewater All-Weather inspired):
  SPY (US equity), TLT (long bonds), GLD (gold), DBC (commodities),
  TIP (TIPS), HYG (high yield), EEM (emerging markets), SHV (cash)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from src.strategy.models import (
    AlertType,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalType,
)
from src.strategy.protocol import BacktestStrategy
from src.strategy.signals.cross_asset import CrossAssetConfig, CrossAssetSignalComputer

logger = logging.getLogger(__name__)


@dataclass
class AllWeatherConfig:
    """Configuration for All-Weather Multi-Asset Allocation strategy."""

    name: str = "all_weather"

    # Asset weights (excluding cash; sum should be <= 1.0)
    asset_weights: dict[str, float] = field(default_factory=lambda: {
        "SPY": 0.25,
        "TLT": 0.25,
        "GLD": 0.15,
        "DBC": 0.10,
        "TIP": 0.10,
        "HYG": 0.10,
        "EEM": 0.05,
    })
    cash_symbol: str = "SHV"

    # Trend filter
    sma_period: int = 200
    use_trend_filter: bool = True

    # Weighting
    use_inverse_vol: bool = True
    vol_lookback: int = 60

    # Rebalancing
    rebalance_frequency: int = 21  # ~monthly (trading days)
    drift_threshold: float = 0.05  # 5% drift triggers interim rebalance
    capital_allocation: float = 0.98  # Deploy up to 98% of NLV

    # Minimum trade threshold (% of NLV; skip trades smaller than this)
    min_trade_pct: float = 0.01


class AllWeatherStrategy(BacktestStrategy):
    """All-Weather Multi-Asset Allocation Strategy.

    Trend-following + inverse-vol weighting over a diversified ETF universe.
    Exits → then entries each rebalance cycle, with SHV as the cash parking vehicle.
    """

    def __init__(self, config: AllWeatherConfig | None = None) -> None:
        super().__init__()
        self._config = config or AllWeatherConfig()
        self._cross_asset = CrossAssetSignalComputer(
            CrossAssetConfig(
                sma_period=self._config.sma_period,
                vol_lookback=self._config.vol_lookback,
                use_inverse_vol=self._config.use_inverse_vol,
            )
        )
        self._last_rebalance_day: int = 0
        self._target_weights: dict[str, float] = {}

    @property
    def name(self) -> str:
        return self._config.name

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        self._target_weights = {}

    def compute_exit_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        if not self._should_rebalance(market, portfolio):
            return []

        # Compute target weights
        signals_data = self._cross_asset.compute(market, data_provider)
        self._target_weights = self._compute_target_weights(signals_data)
        self._last_signal_detail = {
            "target_weights": self._target_weights,
            "trends": signals_data.get("trends", {}),
            "vols": signals_data.get("vols", {}),
        }

        self.log("rebalance:weights", "info",
                 targets=self._target_weights,
                 trends=signals_data.get("trends", {}))

        # Generate EXIT signals for over-weight or trend-off assets
        signals: list[Signal] = []
        cfg = self._config
        nlv = portfolio.nlv

        for pos in portfolio.positions:
            symbol = pos.instrument.underlying
            target_w = self._target_weights.get(symbol, 0.0)
            target_value = nlv * target_w
            current_value = pos.current_price * abs(pos.quantity) * pos.instrument.lot_size
            diff = target_value - current_value

            if diff >= -nlv * cfg.min_trade_pct:
                continue  # Not significantly over-weight

            price = market.get_price_or_zero(symbol)
            if price <= 0:
                continue

            shares_to_sell = min(abs(pos.quantity), math.ceil(abs(diff) / price))
            if shares_to_sell <= 0:
                continue

            signals.append(Signal(
                type=SignalType.EXIT,
                instrument=pos.instrument,
                target_quantity=-shares_to_sell,
                reason=f"AW rebal: {symbol} sell {shares_to_sell}sh "
                       f"(target={target_w:.1%}, diff=${diff:,.0f})",
                position_id=pos.position_id,
                priority=10,
                alert_type=AlertType.REBALANCE,
            ))

        return signals

    def compute_entry_signals(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> list[Signal]:
        if not self._target_weights:
            # Not a rebalance day, or compute_exit_signals wasn't called
            return []

        self._last_rebalance_day = self._trading_day_count
        cfg = self._config
        nlv = portfolio.nlv
        signals: list[Signal] = []

        for symbol, target_w in self._target_weights.items():
            target_value = nlv * target_w
            current_value = self._get_current_value(symbol, portfolio, market)
            diff = target_value - current_value

            if diff <= nlv * cfg.min_trade_pct:
                continue  # Not significantly under-weight

            price = market.get_price_or_zero(symbol)
            if price <= 0:
                continue

            shares = math.floor(diff / price)
            if shares <= 0:
                continue

            instrument = Instrument(
                type=InstrumentType.STOCK,
                underlying=symbol,
                lot_size=1,
            )

            signals.append(Signal(
                type=SignalType.ENTRY,
                instrument=instrument,
                target_quantity=shares,
                reason=f"AW rebal: {symbol} buy {shares}sh "
                       f"(target={target_w:.1%}, diff=${diff:,.0f})",
                quote_price=price,
                priority=0,
            ))

        return signals

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _should_rebalance(
        self, market: MarketSnapshot, portfolio: PortfolioState
    ) -> bool:
        """Check if rebalancing is needed (periodic or drift-triggered)."""
        cfg = self._config

        # First trading day: always rebalance
        if self._trading_day_count <= 1:
            self.log("rebalance:check", "pass", reason="初始建仓")
            return True

        # Periodic rebalance
        if self._rebalance_cooldown_ok(self._last_rebalance_day, cfg.rebalance_frequency):
            self.log("rebalance:check", "pass",
                     reason=f"月度再平衡 (day={self._trading_day_count})")
            return True

        # Drift check
        if self._check_drift(market, portfolio):
            self.log("rebalance:check", "pass",
                     reason=f"漂移超过 {cfg.drift_threshold:.0%}")
            return True

        self.log("rebalance:check", "skip",
                 reason=f"未到再平衡日 (last={self._last_rebalance_day}, "
                        f"freq={cfg.rebalance_frequency})")
        return False

    def _check_drift(
        self, market: MarketSnapshot, portfolio: PortfolioState
    ) -> bool:
        """Check if any asset has drifted beyond threshold."""
        if not portfolio.positions or portfolio.nlv <= 0:
            return False

        cfg = self._config
        for symbol in cfg.asset_weights:
            target_w = cfg.asset_weights[symbol]
            current_value = self._get_current_value(symbol, portfolio, market)
            current_w = current_value / portfolio.nlv
            if abs(current_w - target_w) > cfg.drift_threshold:
                return True

        return False

    def _compute_target_weights(self, signals_data: dict) -> dict[str, float]:
        """Compute target allocation weights based on trends and volatilities."""
        trends = signals_data.get("trends", {})
        vols = signals_data.get("vols", {})
        cfg = self._config

        # 1. Filter out assets with bearish trend
        if cfg.use_trend_filter:
            active = {s: w for s, w in cfg.asset_weights.items()
                      if trends.get(s, False)}
        else:
            active = dict(cfg.asset_weights)

        # 2. Inverse-vol weighting among active assets
        if cfg.use_inverse_vol and active:
            inv_vols = {}
            for s in active:
                v = vols.get(s, 0)
                if v > 0.01:
                    inv_vols[s] = 1.0 / v

            if inv_vols:
                total_iv = sum(inv_vols.values())
                active_total = sum(active.values())
                for s in inv_vols:
                    active[s] = active_total * inv_vols[s] / total_iv

        # 3. Remaining weight goes to cash
        cash_weight = cfg.capital_allocation - sum(active.values())
        active[cfg.cash_symbol] = max(0.0, cash_weight)

        return active

    @staticmethod
    def _get_current_value(
        symbol: str, portfolio: PortfolioState, market: MarketSnapshot
    ) -> float:
        """Get current market value of a symbol in the portfolio."""
        value = 0.0
        for pos in portfolio.positions:
            if pos.instrument.underlying == symbol:
                price = market.get_price_or_zero(symbol)
                value += price * abs(pos.quantity) * pos.instrument.lot_size
        return value
