"""Short Put Strategy — native V2 implementation.

Sells short puts with systematic entry/exit rules.
Two variants controlled by ShortPutConfig:
- allow_assignment=True: accepts ITM stock assignment at expiration
- allow_assignment=False: closes before expiration if ITM

Entry: SMA trend filter + option chain filtering (delta, DTE, spread, IV/HV)
       No per-underlying concurrent limit (different expiries can stack).
       Fixed qty=1 per position (matches V1 Kelly formula output).
Exit:  Profit target, delta/TGR thresholds, optional win-prob check.
       No DTE-based force close (V1 lets options expire naturally).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from src.backtest.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)
from src.backtest.strategy.protocol import BacktestStrategy
from src.backtest.strategy.signals.sma import SmaComparison, SmaComputer

logger = logging.getLogger(__name__)

# Keep old names importable for backward compatibility
ShortOptionsConfig = None  # replaced by ShortPutConfig
ShortOptionsStrategy = None  # replaced by ShortPutStrategy


@dataclass
class ShortPutConfig:
    """Configuration for short put strategy.

    Matches V1 behavior:
    - allow_assignment=True  → "with_expire_itm_stock_trade" (win_prob disabled)
    - allow_assignment=False → "without_expire_itm_stock_trade" (win_prob enabled)
    """

    name: str = "short_put_with_assignment"
    allow_assignment: bool = True
    decision_frequency: int = 1

    # === Contract screening (from screening YAML) ===
    min_dte: int = 21
    max_dte: int = 45
    min_abs_delta: float = 0.15
    max_abs_delta: float = 0.35
    max_bid_ask_spread: float = 0.30
    min_open_interest: int = 0

    # === Underlying screening ===
    min_iv_hv_ratio: float = 0.8
    max_iv_hv_ratio: float = 3.0
    technical_enabled: bool = True  # with=True, without=False
    min_rsi: float = 30.0
    max_rsi: float = 70.0
    max_adx: float = 45.0

    # === Market environment ===
    trend_sma_period: int = 200

    # === Exit rules (from monitoring YAML + get_monitoring_overrides) ===
    take_profit_pnl: float = 0.70
    take_profit_min_dte: int = 14
    max_delta_exit: float = 0.65
    min_tgr_exit: float = 0.1
    win_probability_enabled: bool = False  # with=False, without=True
    min_win_prob: float = 0.50

    # === Position management ===
    max_new_positions_per_day: int = 1
    # No max_contracts_per_position — fixed qty=1 (matches V1 Kelly output)
    # No max_capital_pct / margin_rate — global AccountRiskGuard handles limits


class ShortPutStrategy(BacktestStrategy):
    """Native V2 short put strategy matching V1 behavior.

    Entry: SMA bullish -> scan option chain -> filter by delta/DTE/spread ->
           rank by expected ROC -> qty=1.
           No per-underlying concurrent limit (V1 allows stacking different expiries).
    Exit:  Profit target / delta too high / TGR too low /
           win probability too low (optional) / ITM at expiry (no-assignment only).
    """

    def __init__(self, config: ShortPutConfig | None = None) -> None:
        super().__init__()
        self._config = config or ShortPutConfig()
        self._sma = SmaComputer(
            period=self._config.trend_sma_period,
            comparison=SmaComparison.PRICE_VS_SMA,
        )
        self._entries_today = 0

    @property
    def name(self) -> str:
        return self._config.name

    # ------------------------------------------------------------------
    # Exit signals
    # ------------------------------------------------------------------

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Generate exit signals for existing short option positions."""
        signals: list[Signal] = []
        cfg = self._config

        for pos in portfolio.get_option_positions():
            # Only manage short positions
            if pos.quantity >= 0:
                continue

            should_close = False
            reason = ""

            # Rule 1: DTE <= 0 and ITM — force close (no-assignment variant only)
            if not cfg.allow_assignment and pos.dte is not None and pos.dte <= 0:
                if self._is_itm(pos):
                    should_close = True
                    reason = f"ITM at expiry (no-assignment mode), DTE={pos.dte}"

            # Rule 2: Early profit taking — PnL >= threshold and DTE > min
            if not should_close:
                pnl_pct = self._calc_pnl_pct(pos)
                if (
                    pnl_pct is not None
                    and pnl_pct >= cfg.take_profit_pnl
                    and pos.dte is not None
                    and pos.dte > cfg.take_profit_min_dte
                ):
                    should_close = True
                    reason = f"Take profit: PnL={pnl_pct:.0%} (target {cfg.take_profit_pnl:.0%})"

            # Rule 3: Delta too high (deep ITM)
            if not should_close and pos.delta is not None:
                if abs(pos.delta) > cfg.max_delta_exit:
                    should_close = True
                    reason = f"Delta too high: |{pos.delta:.2f}| > {cfg.max_delta_exit}"

            # Rule 4: TGR too low
            if not should_close:
                tgr = self._calc_tgr(pos)
                if tgr is not None and tgr < cfg.min_tgr_exit:
                    should_close = True
                    reason = f"TGR too low: {tgr:.2f} < {cfg.min_tgr_exit}"

            # Rule 5: Win probability too low (only when enabled — disabled for assignment variant)
            if not should_close and cfg.win_probability_enabled and pos.delta is not None:
                win_prob = 1.0 - abs(pos.delta)
                if win_prob < cfg.min_win_prob:
                    should_close = True
                    reason = f"Win prob too low: {win_prob:.0%} < {cfg.min_win_prob:.0%}"

            if should_close:
                signals.append(
                    Signal(
                        type=SignalType.EXIT,
                        instrument=pos.instrument,
                        target_quantity=-pos.quantity,  # buy back
                        reason=reason,
                        position_id=pos.position_id,
                        priority=10,
                        metadata={"alert_type": "short_put_exit"},
                    )
                )

        return signals

    # ------------------------------------------------------------------
    # Entry signals
    # ------------------------------------------------------------------

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Scan for new short put opportunities.

        V1-compatible: no per-underlying concurrent limit (different expiries
        can stack), fixed qty=1 per position.
        """
        cfg = self._config
        self._entries_today = 0

        if not self._is_decision_day(cfg.decision_frequency):
            return []

        # SMA trend filter
        sma_result = self._sma.compute(market, data_provider)
        if not sma_result.get("invested", False):
            return []

        signals: list[Signal] = []

        for symbol in market.prices:
            if self._entries_today >= cfg.max_new_positions_per_day:
                break

            underlying_price = market.get_price_or_zero(symbol)
            if underlying_price <= 0:
                continue

            # Technical filter (optional)
            if cfg.technical_enabled:
                if not self._check_technicals(symbol, market.date, data_provider):
                    continue

            # Get option chain
            chain = data_provider.get_option_chain(
                symbol,
                expiry_min_days=cfg.min_dte,
                expiry_max_days=cfg.max_dte,
            )
            if not chain or not chain.puts:
                continue

            # Find best candidate
            best = self._select_best_contract(
                chain, underlying_price, symbol, market.date, data_provider
            )
            if best is None:
                continue

            quote, margin_per_contract, expected_roc = best

            # Fixed qty=1 — matches V1 Kelly formula output
            contracts = 1

            price = quote.mid_price or quote.close or quote.last_price or 0
            strike = quote.contract.strike_price
            expiry = quote.contract.expiry_date
            dte = (expiry - market.date).days

            instrument = Instrument(
                type=InstrumentType.OPTION,
                underlying=symbol,
                right=OptionRight.PUT,
                strike=strike,
                expiry=expiry,
            )

            greeks_dict = None
            if quote.greeks:
                greeks_dict = {
                    "delta": quote.greeks.delta,
                    "gamma": quote.greeks.gamma,
                    "theta": quote.greeks.theta,
                    "vega": quote.greeks.vega,
                }

            signals.append(
                Signal(
                    type=SignalType.ENTRY,
                    instrument=instrument,
                    target_quantity=-contracts,  # sell
                    reason=(
                        f"Short Put {symbol} {strike:.0f} "
                        f"DTE={dte} delta={quote.greeks.delta:.2f} "
                        f"@ ${price:.2f} x{contracts} "
                        f"ROC={expected_roc:.1f}%"
                        if quote.greeks and quote.greeks.delta
                        else f"Short Put {symbol} {strike:.0f} DTE={dte} @ ${price:.2f} x{contracts}"
                    ),
                    priority=0,
                    quote_price=price,
                    greeks=greeks_dict,
                    metadata={
                        "expected_roc": expected_roc,
                        "margin_per_contract": margin_per_contract,
                    },
                )
            )
            self._entries_today += 1

        self._last_signal_detail = {
            "sma_invested": sma_result.get("invested", False),
            "entries_today": self._entries_today,
        }

        return signals

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_itm(self, pos: PositionView) -> bool:
        """Check if short put is ITM (underlying < strike)."""
        if pos.instrument.right == OptionRight.PUT:
            return pos.underlying_price < (pos.instrument.strike or 0)
        elif pos.instrument.right == OptionRight.CALL:
            return pos.underlying_price > (pos.instrument.strike or float("inf"))
        return False

    def _calc_pnl_pct(self, pos: PositionView) -> Optional[float]:
        """Calculate PnL as percentage of entry credit received."""
        if pos.entry_price == 0 or pos.quantity == 0:
            return None
        total_credit = abs(pos.entry_price) * pos.lot_size * abs(pos.quantity)
        if total_credit <= 0:
            return None
        return pos.unrealized_pnl / total_credit

    def _calc_tgr(self, pos: PositionView) -> Optional[float]:
        """Calculate Theta/Gamma Ratio (per-share Greeks)."""
        if pos.theta is None or pos.gamma is None:
            return None
        if abs(pos.gamma) < 1e-10:
            return None
        return abs(pos.theta) / abs(pos.gamma)

    def _check_technicals(
        self, symbol: str, as_of_date: date, data_provider: Any
    ) -> bool:
        """Check RSI and ADX filters for the underlying."""
        cfg = self._config
        try:
            from src.data.models.stock import KlineType

            lookback_start = as_of_date - timedelta(days=60)
            klines = data_provider.get_history_kline(
                symbol=symbol,
                ktype=KlineType.DAY,
                start_date=lookback_start,
                end_date=as_of_date,
            )
            if not klines or len(klines) < 20:
                return True  # Insufficient data — skip filter

            closes = [k.close for k in klines]
            highs = [k.high for k in klines]
            lows = [k.low for k in klines]

            from src.engine.position.technical.rsi import calc_rsi

            rsi = calc_rsi(closes, period=14)
            if rsi is not None:
                if rsi < cfg.min_rsi or rsi > cfg.max_rsi:
                    return False

            from src.engine.position.technical.adx import calc_adx

            adx_result = calc_adx(highs, lows, closes, period=14)
            if adx_result is not None:
                if adx_result.adx > cfg.max_adx:
                    return False

            return True
        except Exception:
            return True  # On error, skip filter

    def _select_best_contract(
        self,
        chain: Any,
        underlying_price: float,
        symbol: str,
        current_date: date,
        data_provider: Any,
    ) -> Optional[tuple[Any, float, float]]:
        """Select the best put from the option chain.

        Returns (quote, margin_per_contract, expected_roc) or None.
        """
        cfg = self._config
        candidates = []

        # Get HV for IV/HV ratio check — pass symbol string, not character list
        hv = self._get_hv(symbol, current_date, data_provider)

        for quote in chain.puts:
            contract = quote.contract
            expiry = contract.expiry_date
            if expiry is None:
                continue
            dte = (expiry - current_date).days
            if dte < cfg.min_dte or dte > cfg.max_dte:
                continue

            # Price check
            price = quote.mid_price or quote.close or quote.last_price
            if price is None or price <= 0.05:
                continue

            # Delta check
            delta = quote.greeks.delta if quote.greeks else None
            if delta is None:
                continue
            abs_delta = abs(delta)
            if abs_delta < cfg.min_abs_delta or abs_delta > cfg.max_abs_delta:
                continue

            # Bid-ask spread check
            if quote.bid is not None and quote.ask is not None and price > 0:
                spread_ratio = (quote.ask - quote.bid) / price
                if spread_ratio > cfg.max_bid_ask_spread:
                    continue

            # Open interest check
            oi = getattr(quote, "open_interest", None) or 0
            if oi < cfg.min_open_interest:
                continue

            # IV/HV ratio check
            iv = quote.iv or (quote.greeks.iv if quote.greeks and hasattr(quote.greeks, "iv") else None)
            if iv is not None and hv is not None and hv > 0:
                iv_hv = iv / hv
                if iv_hv < cfg.min_iv_hv_ratio or iv_hv > cfg.max_iv_hv_ratio:
                    continue

            # Calculate margin (for ROC ranking only, not sizing)
            strike = contract.strike_price
            lot_size = contract.lot_size or 100
            try:
                from src.data.models.margin import calc_reg_t_margin_short_put

                margin_per_share = calc_reg_t_margin_short_put(
                    underlying_price=underlying_price,
                    strike=strike,
                    premium=price,
                )
                margin_per_contract = margin_per_share * lot_size
            except Exception:
                margin_per_contract = strike * lot_size * 0.20

            # Expected ROC for ranking — probability-weighted (matches V1 ShortPutPricer)
            margin_per_share = margin_per_contract / lot_size if lot_size > 0 else 0
            expected_roc = self._calc_expected_roc(
                premium=price,
                strike=strike,
                spot=underlying_price,
                dte=dte,
                iv=iv,
                hv=hv,
                margin_per_share=margin_per_share,
            )

            candidates.append((quote, margin_per_contract, expected_roc))

        if not candidates:
            return None

        # Sort by expected ROC descending
        candidates.sort(key=lambda x: x[2], reverse=True)
        best_quote, best_margin, best_roc = candidates[0]
        return (best_quote, best_margin, best_roc)

    def _get_hv(
        self, symbol: str, as_of_date: date, data_provider: Any
    ) -> Optional[float]:
        """Get historical volatility for IV/HV comparison."""
        try:
            from src.data.models.stock import KlineType

            lookback_start = as_of_date - timedelta(days=60)
            klines = data_provider.get_history_kline(
                symbol=symbol,
                ktype=KlineType.DAY,
                start_date=lookback_start,
                end_date=as_of_date,
            )
            if not klines or len(klines) < 21:
                return None
            closes = [k.close for k in klines]
            returns = [
                math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i - 1] > 0
            ]
            if len(returns) < 20:
                return None
            recent = returns[-20:]
            mean = sum(recent) / len(recent)
            variance = sum((r - mean) ** 2 for r in recent) / (len(recent) - 1)
            return math.sqrt(variance) * math.sqrt(252)
        except Exception:
            return None

    def _calc_expected_roc(
        self,
        premium: float,
        strike: float,
        spot: float,
        dte: int,
        iv: float | None,
        hv: float | None,
        margin_per_share: float,
    ) -> float:
        """Calculate expected ROC using V1's probability-weighted formula.

        Replicates ShortPutPricer.calc_expected_return() / margin * 365/DTE.
        Uses HV-based d1/d2 for real-world exercise probability, capturing
        the volatility risk premium (IV > HV) that option sellers earn.

        E[π] = C - N(-d2_hv) * (K - e^(rT) * S * N(-d1_hv) / N(-d2_hv))
        Expected ROC = E[π] / margin * (365 / DTE)
        """
        if margin_per_share <= 0 or dte <= 0:
            return 0.0

        # Use HV for real-world measure; fall back to IV
        sigma = hv if hv and hv > 0 else (iv if iv and iv > 0 else None)
        if sigma is None or sigma <= 0 or spot <= 0 or strike <= 0:
            # Fallback to simple ROC when no vol data
            return (premium / margin_per_share) * (365 / dte)

        from scipy.stats import norm as sp_norm

        t = dte / 365.0
        r = 0.05  # risk-free rate assumption

        sqrt_t = math.sqrt(t)
        sigma_sqrt_t = sigma * sqrt_t

        d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * t) / sigma_sqrt_t
        d2 = d1 - sigma_sqrt_t

        n_minus_d1 = sp_norm.cdf(-d1)
        n_minus_d2 = sp_norm.cdf(-d2)

        if n_minus_d2 < 1e-10:
            # No exercise probability — expected return = full premium
            expected_return = premium
        else:
            exp_rt = math.exp(r * t)
            expected_stock_if_exercised = exp_rt * spot * n_minus_d1 / n_minus_d2
            expected_return = premium - n_minus_d2 * (strike - expected_stock_if_exercised)

        return (expected_return / margin_per_share) * (365 / dte)


# Backward compatibility aliases
ShortOptionsConfig = ShortPutConfig
ShortOptionsStrategy = ShortPutStrategy
