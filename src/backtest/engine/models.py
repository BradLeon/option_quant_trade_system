"""Legacy data models used by the backtest engine's trade execution layer.

MarketContext and TradeSignal are V1 models consumed by BacktestExecutor
and SignalConverter. V2 strategies produce Signal objects; SignalConverter
bridges them to TradeSignal for the TradeSimulator.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Optional

from src.data.models.option import OptionQuote

if TYPE_CHECKING:
    from src.backtest.engine.account_simulator import SimulatedPosition
    from src.backtest.engine.trade_simulator import TradeAction


@dataclass
class MarketContext:
    """市场环境上下文 — 向回测引擎传递当天大盘指标。"""

    current_date: date
    underlying_prices: dict[str, float] = field(default_factory=dict)
    vix_value: Optional[float] = None
    market_trend: Optional[str] = None


@dataclass
class TradeSignal:
    """V1 交易指令 — BacktestExecutor / TradeSimulator 消费。

    V2 策略产出 Signal，经 SignalConverter 桥接为 TradeSignal。
    """

    action: "TradeAction"
    symbol: str
    quantity: int
    reason: str
    alert_type: Optional[str] = None
    position_id: Optional[str] = None
    related_position: Optional["SimulatedPosition"] = None
    quote: Optional[OptionQuote] = None
    roll_to_expiry: Optional[str] = None
    roll_to_strike: Optional[float] = None
    priority: str = "normal"
