"""Shared Strategy Data Models

Core data models for the strategy abstraction layer, shared by both
backtest (BacktestExecutor) and live trading (LiveStrategyExecutor):

- Instrument: Unified financial instrument identifier (stock, option, combo)
- Signal: Strategy output — describes what to do, not how
- MarketSnapshot / PortfolioState: Read-only views for strategy consumption
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


# ============================================================
# Instrument — 金融工具统一标识
# ============================================================

class InstrumentType(str, Enum):
    STOCK = "stock"
    OPTION = "option"
    COMBO = "combo"


class OptionRight(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True)
class Instrument:
    """Immutable financial instrument identifier.

    Usable as dict key / set member thanks to frozen=True.
    Eliminates the "stock proxy" hack — stocks are first-class citizens.
    """

    type: InstrumentType
    underlying: str
    right: Optional[OptionRight] = None
    strike: Optional[float] = None
    expiry: Optional[date] = None
    lot_size: int = 100

    @property
    def is_stock(self) -> bool:
        return self.type == InstrumentType.STOCK

    @property
    def is_option(self) -> bool:
        return self.type == InstrumentType.OPTION

    @property
    def is_combo(self) -> bool:
        return self.type == InstrumentType.COMBO

    @property
    def symbol(self) -> str:
        """Human-readable identifier."""
        if self.is_stock:
            return self.underlying
        if self.is_option:
            right_str = self.right.value[0].upper() if self.right else "?"
            strike_str = f"{self.strike:.0f}" if self.strike else "?"
            exp_str = self.expiry.strftime("%y%m%d") if self.expiry else "?"
            return f"{self.underlying}_{exp_str}_{right_str}_{strike_str}"
        return f"COMBO:{self.underlying}"

    def __repr__(self) -> str:
        return f"Instrument({self.symbol})"


@dataclass
class ComboLeg:
    """Single leg of a combo instrument."""
    instrument: Instrument
    ratio: int  # +1 buy, -1 sell


@dataclass
class ComboInstrument:
    """Multi-leg option combo (spreads, straddles, etc.)."""
    name: str
    underlying: str
    legs: list[ComboLeg] = field(default_factory=list)


# ============================================================
# Signal — 策略唯一输出
# ============================================================

class SignalType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    REBALANCE = "rebalance"
    ROLL = "roll"


class AlertType(str, Enum):
    """Structured alert type for exit/roll/rebalance signals.

    Used by TradeSimulator to map signals to CloseReasonType.
    Each strategy sets this on exit signals to enable accurate PnL attribution.
    """

    # 止盈
    PROFIT_TARGET = "profit_target"
    DTE_PROFITABLE = "dte_profitable"

    # Delta / OTM 止损
    DELTA_CHANGE = "delta_change"
    OTM_PCT = "otm_pct"
    MONEYNESS = "moneyness"

    # 通用止损
    STOP_LOSS = "stop_loss"
    PNL_TARGET = "pnl_target"
    GAMMA_RISK = "gamma_risk"
    GAMMA_RISK_PCT = "gamma_risk_pct"
    GAMMA_NEAR_EXPIRY = "gamma_near_expiry"

    # Theta / TGR / ROC 时间退出
    POSITION_TGR = "position_tgr"
    TGR_LOW = "tgr_low"
    EXPECTED_ROC_LOW = "expected_roc_low"
    ROC_LOW = "roc_low"

    # DTE 到期
    DTE_WARNING = "dte_warning"

    # 胜率 / IV-HV
    WIN_PROB_LOW = "win_prob_low"
    POSITION_IV_HV = "position_iv_hv"
    IV_HV_CHANGE = "iv_hv_change"

    # Portfolio 级风控
    DELTA_EXPOSURE = "delta_exposure"
    GAMMA_EXPOSURE = "gamma_exposure"
    VEGA_EXPOSURE = "vega_exposure"
    THETA_EXPOSURE = "theta_exposure"
    CONCENTRATION = "concentration"

    # Capital 级风控
    MARGIN_UTILIZATION = "margin_utilization"
    CASH_RATIO = "cash_ratio"
    GROSS_LEVERAGE = "gross_leverage"
    STRESS_TEST_LOSS = "stress_test_loss"

    # LEAPS 策略
    ROLL_DTE = "roll_dte"
    SMA_EXIT = "sma_exit"
    LEVERAGE_REBALANCE = "leverage_rebalance"
    VEGA_GUARD = "vega_guard"
    VOLTGT_EXIT = "voltgt_exit"
    REBALANCE = "rebalance"

    # Spread 策略
    SPREAD_CLOSE = "spread_close"

    # Short options
    SHORT_PUT_EXIT = "short_put_exit"


@dataclass
class Signal:
    """Strategy output: describes *what* to trade, not *how*.

    Strategies return a list of Signals. The executor + converter
    handles the translation to executable orders.
    """

    type: SignalType
    instrument: Instrument
    target_quantity: int  # positive=buy, negative=sell
    reason: str

    # EXIT / REBALANCE / ROLL — must identify existing position
    position_id: Optional[str] = None

    # ROLL — the new instrument to roll into
    roll_to: Optional[Instrument] = None

    # Priority: higher = executed first; EXIT > ROLL > REBALANCE > ENTRY
    priority: int = 0

    # Structured alert type (for CloseReasonType mapping in TradeSimulator)
    alert_type: Optional[AlertType] = None

    # Strategy-specific metadata (e.g. signal scores, debug info)
    metadata: dict = field(default_factory=dict)

    # Quote price at signal generation time (for position sizing reference)
    quote_price: Optional[float] = None

    # Greeks snapshot (optional, for strategies that compute their own Greeks)
    greeks: Optional[dict] = None


# ============================================================
# MarketSnapshot — 只读市场视图
# ============================================================

@dataclass
class MarketSnapshot:
    """Read-only market data snapshot for a single day.

    Strategies receive this instead of accessing data_provider directly
    for basic price/macro data. Complex queries still go through data_provider.
    """

    date: date
    prices: dict[str, float] = field(default_factory=dict)  # symbol → close
    vix: Optional[float] = None
    risk_free_rate: Optional[float] = None

    def get_price(self, symbol: str) -> float:
        """Get price for symbol, raises KeyError if missing."""
        price = self.prices.get(symbol)
        if price is None or price <= 0:
            raise KeyError(f"No valid price for {symbol} on {self.date}")
        return price

    def get_price_or_zero(self, symbol: str) -> float:
        """Get price for symbol, returns 0.0 if missing."""
        return self.prices.get(symbol, 0.0)


# ============================================================
# PortfolioState — 只读组合快照
# ============================================================

@dataclass
class PositionView:
    """Read-only view of a single position."""

    position_id: str
    instrument: Instrument
    quantity: int
    entry_price: float
    entry_date: date
    current_price: float
    underlying_price: float
    unrealized_pnl: float

    # Greeks (optional — may not be available for all instruments)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    dte: Optional[int] = None

    # Lot size for this position
    lot_size: int = 100

    @property
    def is_stock(self) -> bool:
        return self.instrument.is_stock

    @property
    def is_option(self) -> bool:
        return self.instrument.is_option

    @property
    def is_cash_equivalent(self) -> bool:
        from src.strategy.cash_sweep import CASH_EQUIVALENT_SYMBOLS
        return self.is_stock and self.instrument.underlying in CASH_EQUIVALENT_SYMBOLS

    @property
    def market_value(self) -> float:
        return self.current_price * abs(self.quantity) * self.lot_size


@dataclass
class PortfolioState:
    """Read-only portfolio snapshot."""

    date: date
    nlv: float
    cash: float
    margin_used: float
    positions: list[PositionView] = field(default_factory=list)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def get_positions_by_underlying(self, underlying: str) -> list[PositionView]:
        return [p for p in self.positions if p.instrument.underlying == underlying]

    def get_stock_positions(self) -> list[PositionView]:
        return [p for p in self.positions if p.is_stock]

    def get_option_positions(self) -> list[PositionView]:
        return [p for p in self.positions if p.is_option]

    def get_cash_equivalent_positions(self) -> list[PositionView]:
        return [p for p in self.positions if p.is_cash_equivalent]

    @property
    def cash_equivalent_value(self) -> float:
        return sum(p.market_value for p in self.get_cash_equivalent_positions())

    @property
    def margin_utilization(self) -> float:
        """Margin used / NLV. Used by RiskGuard and OrderValidator."""
        return self.margin_used / self.nlv if self.nlv > 0 else 0.0

    @property
    def cash_ratio(self) -> float:
        """Cash / NLV. Used by RiskGuard and OrderValidator."""
        return self.cash / self.nlv if self.nlv > 0 else 0.0
