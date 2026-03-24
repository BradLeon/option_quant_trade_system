"""Leverage Rotation Strategy (LRS) — 论文 "Leverage for the Long Run" 完整实现.

参考: Gayed (2016) "A Systematic Approach to Managing Risk and Magnifying Returns"

核心思想:
  - Close > SMA200 → LEAPS Call 杠杆做多（替代论文中的 2x/3x 杠杆 ETF）
  - Close < SMA200 → 全部转为短期国债 ETF (SHV)
  - 无分档、无 vol_target — 纯二元信号

相比论文的改进:
  - 使用 LEAPS Call 替代日度再平衡的杠杆 ETF，天然凸性（gamma）
  - 闲置资金自动 sweep 进 SHV 赚取无风险利率
  - DTE 低于阈值时自动 roll 到远月合约
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from src.strategy.cash_sweep import CashSweepConfig, CashSweepMixin
from src.strategy.leaps_selector import LeapsContractSelector, LeapsSelectionConfig
from src.strategy.models import (
    AlertType,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    Signal,
    SignalType,
)
from src.strategy.protocol import BacktestStrategy
from src.strategy.signals.sma import SmaComparison, SmaComputer

logger = logging.getLogger(__name__)


@dataclass
class LeverageRotationConfig:
    """Configuration for Leverage Rotation Strategy."""

    name: str = "leverage_rotation"

    # SMA signal
    sma_period: int = 200
    comparison: SmaComparison = SmaComparison.PRICE_VS_SMA

    # LEAPS contract parameters
    target_delta: float = 0.70
    min_delta: float = 0.50
    max_delta: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    roll_dte_threshold: int = 60

    # Leverage — 论文默认 3x (LEAPS 天然杠杆)
    target_leverage: float = 3.0
    max_capital_pct: float = 0.95

    # Decision frequency (论文: 每日检查; 可调)
    decision_frequency: int = 1

    # Cash sweep (bearish 期间把现金投入 SHV)
    cash_sweep_config: CashSweepConfig = field(default_factory=lambda: CashSweepConfig(
        enabled=True,
        instrument_symbol="SHV",
        min_cash_buffer_pct=0.02,
        sweep_threshold=5_000,
        min_trade_size=10,
        cooldown_days=3,
        require_strategy_position=False,  # bearish 无持仓时也买 SHV
        max_value_pct=0.50,
    ))


class LeverageRotationStrategy(BacktestStrategy, CashSweepMixin):
    """Leverage Rotation Strategy — 二元 SMA200 + LEAPS + SHV Cash Sweep.

    论文 LRS 的 LEAPS 实现版:
    - SMA200 看多 → 持有 deep ITM LEAPS Call (目标杠杆)
    - SMA200 看空 → 全部平仓，闲置资金 sweep 进 SHV
    - DTE 低于阈值 → 自动 roll 到远月合约
    """

    def __init__(self, config: LeverageRotationConfig | None = None, **kwargs) -> None:
        super().__init__()
        self._config = config or LeverageRotationConfig(**kwargs)
        self._sma = SmaComputer(
            period=self._config.sma_period,
            comparison=self._config.comparison,
        )
        self._last_nlv: float = 0.0
        self._pending_roll: bool = False

        # Cash sweep mixin
        self._cash_sweep_config = self._config.cash_sweep_config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def requires_synthetic_data(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # generate_signals override: inject cash sweep
    # ------------------------------------------------------------------

    def generate_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        signals = super().generate_signals(market, portfolio, data_provider)

        if not self._cash_sweep_config.enabled:
            return signals

        # Determine cash needs (pending LEAPS entries)
        entry_signals = [s for s in signals if s.type == SignalType.ENTRY and not s.metadata.get("is_cash_equivalent")]
        cash_needed = sum(
            (s.quote_price or 0) * (s.instrument.lot_size or 100) * abs(s.target_quantity)
            for s in entry_signals
        )

        # Sweep exits: sell SHV to free cash for LEAPS
        sweep_exits = self.compute_cash_sweep_exits(market, portfolio, cash_needed)
        if sweep_exits:
            self.log("cash_sweep:exit", "pass", count=len(sweep_exits), cash_needed=cash_needed)

        # Sweep entries: idle cash → SHV
        from src.strategy.cash_sweep import CASH_EQUIVALENT_SYMBOLS
        has_strategy_pos = any(
            p for p in portfolio.positions
            if p.instrument.underlying not in CASH_EQUIVALENT_SYMBOLS
        )
        sweep_entries = self.compute_cash_sweep_entries(
            market, portfolio, cash_reserved=cash_needed,
            has_strategy_position=has_strategy_pos,
            trading_day=self._trading_day_count,
        )
        if sweep_entries:
            self.log("cash_sweep:entry", "pass", count=len(sweep_entries), cash_reserved=cash_needed)

        # Order: exits first → sweep exits → strategy entries → sweep entries
        exit_signals = [s for s in signals if s.type == SignalType.EXIT]
        non_exit = [s for s in signals if s.type != SignalType.EXIT]
        return exit_signals + sweep_exits + non_exit + sweep_entries

    # ------------------------------------------------------------------
    # Template methods
    # ------------------------------------------------------------------

    def on_day_start(self, market: MarketSnapshot, portfolio: PortfolioState) -> None:
        self._last_nlv = portfolio.nlv
        self._pending_roll = False

    def compute_exit_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        leaps = [p for p in portfolio.positions if p.is_option]
        if not leaps:
            return []

        signals: list[Signal] = []

        # 1. SMA check
        result = self._sma.compute(market, data_provider)
        self._last_signal_detail = result

        sma_val = result.get("sma_long", 0)
        close = result.get("close", 0)

        if not result["invested"]:
            self.log("exit:sma_bearish", "pass",
                     close=f"{close:.2f}", sma200=f"{sma_val:.2f}",
                     action=f"退出全部 {len(leaps)} 个 LEAPS → T-Bills")
            for pos in leaps:
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"LRS exit: Close {close:.2f} < SMA200 {sma_val:.2f}",
                    position_id=pos.position_id,
                    priority=10,
                    alert_type=AlertType.SMA_EXIT,
                ))
            return signals

        # 2. DTE roll check
        cfg = self._config
        for pos in leaps:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_roll = True
                self.log("exit:roll", "pass",
                         symbol=pos.instrument.symbol, dte=pos.dte,
                         threshold=cfg.roll_dte_threshold)
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-pos.quantity,
                    reason=f"LRS roll: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                    position_id=pos.position_id,
                    priority=5,
                    alert_type=AlertType.ROLL_DTE,
                ))

        # 3. DTE <= 5 safety net
        for pos in leaps:
            if pos.dte is not None and pos.dte <= 5:
                already = any(s.position_id == pos.position_id for s in signals)
                if not already:
                    self._pending_roll = True
                    signals.append(Signal(
                        type=SignalType.EXIT,
                        instrument=pos.instrument,
                        target_quantity=-pos.quantity,
                        reason=f"LRS safety: DTE={pos.dte} <= 5",
                        position_id=pos.position_id,
                        priority=10,
                        alert_type=AlertType.ROLL_DTE,
                    ))

        return signals

    def compute_entry_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        cfg = self._config

        leaps = [p for p in portfolio.positions if p.is_option]
        need_entry = False
        entry_reason = ""

        if self._pending_roll:
            need_entry = True
            entry_reason = "pending_roll"
        elif not leaps:
            result = self._sma.compute(market, data_provider)
            self._last_signal_detail = result
            if result["invested"] and self._is_decision_day(cfg.decision_frequency):
                need_entry = True
                entry_reason = (
                    f"LRS bullish: Close {result['close']:.2f} > "
                    f"SMA200 {result['sma_long']:.2f}"
                )
            elif not result["invested"]:
                entry_reason = f"LRS bearish: Close < SMA200"
            else:
                entry_reason = f"非决策日 (day={self._trading_day_count} freq={cfg.decision_frequency})"
        else:
            entry_reason = f"已有 LEAPS 持仓 ({len(leaps)} 个)"

        if not need_entry:
            self.log("entry:check", "skip", reason=entry_reason)
            return []

        self.log("entry:check", "info", reason=entry_reason,
                 nlv=self._last_nlv, cash=portfolio.cash,
                 target_leverage=cfg.target_leverage)

        # Find LEAPS
        from src.strategy.cash_sweep import CASH_EQUIVALENT_SYMBOLS
        symbols = [s for s in market.prices.keys() if s not in CASH_EQUIVALENT_SYMBOLS]
        signals: list[Signal] = []

        for symbol in symbols:
            spot = market.get_price_or_zero(symbol)
            if spot <= 0:
                continue

            best = self._find_best_leaps(symbol, spot, market.date, data_provider)
            if not best:
                continue

            contract = best.contract
            greeks = best.greeks
            delta = greeks.delta if greeks else 0.0
            mid = best.last_price
            if best.bid is not None and best.ask is not None and best.ask > 0:
                mid = (best.bid + best.ask) / 2
            if not delta or delta <= 0 or not mid or mid <= 0:
                continue

            lot_size = contract.lot_size or 100
            nlv = self._last_nlv
            if nlv <= 0:
                continue

            # contracts = target_leverage * NLV / (delta * lot_size * spot)
            contracts = math.floor(cfg.target_leverage * nlv / (delta * lot_size * spot))

            # Cash constraint
            # When cash sweep is active, idle cash is in SHV — use NLV for sizing
            # because SHV sell signals execute before LEAPS buy on the same day.
            use_nlv = self._pending_roll or self._cash_sweep_config.enabled
            available = cfg.max_capital_pct * (nlv if use_nlv else portfolio.cash)
            if mid * lot_size > 0:
                max_contracts = math.floor(available / (mid * lot_size))
                contracts = min(contracts, max_contracts)

            if contracts <= 0:
                continue

            dte = (contract.expiry_date - market.date).days

            self.log("contract_select", "pass",
                     symbol=symbol, strike=contract.strike_price, dte=dte,
                     delta=f"{delta:.2f}", mid=f"{mid:.2f}", contracts=contracts)

            instrument = Instrument(
                type=InstrumentType.OPTION,
                underlying=symbol,
                right=OptionRight.CALL,
                strike=contract.strike_price,
                expiry=contract.expiry_date,
                lot_size=lot_size,
            )

            signals.append(Signal(
                type=SignalType.ENTRY,
                instrument=instrument,
                target_quantity=contracts,
                reason=(
                    f"LRS entry: {contracts}x K={contract.strike_price:.0f} "
                    f"DTE={dte} delta={delta:.2f} leverage={cfg.target_leverage}x"
                ),
                quote_price=mid,
                greeks={
                    "delta": delta,
                    "gamma": greeks.gamma if greeks else 0,
                    "theta": greeks.theta if greeks else 0,
                    "vega": greeks.vega if greeks else 0,
                    "iv": best.iv or 0,
                },
            ))

        return signals

    def _find_best_leaps(
        self, symbol: str, spot: float, current_date: date, data_provider: Any
    ) -> Optional[Any]:
        cfg = self._config
        selector = LeapsContractSelector()
        sel_config = LeapsSelectionConfig(
            target_dte=cfg.target_dte, min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            target_delta=cfg.target_delta, min_delta=cfg.min_delta, max_delta=cfg.max_delta,
        )
        return selector.select(
            symbol, spot, current_date, data_provider, sel_config, log_fn=self.log,
        )
