"""Shared Strategy Abstraction Layer

Execution-agnostic strategy framework used by both backtest and live trading:
- StrategyProtocol: minimal contract (generate_signals)
- Strategy: template base class (on_day_start, compute_exit/entry_signals)
- Signal, Instrument, MarketSnapshot, PortfolioState: core data models
- RiskGuard: pluggable risk middleware protocol

Usage:
    from src.strategy import StrategyProtocol, Signal, MarketSnapshot
"""

from src.strategy.models import (
    ComboInstrument,
    ComboLeg,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)
from src.strategy.execution_log import ExecutionLog
from src.strategy.protocol import Strategy, StrategyProtocol
from src.strategy.risk import RiskGuard

__all__ = [
    # Core models
    "Instrument",
    "InstrumentType",
    "OptionRight",
    "Signal",
    "SignalType",
    "MarketSnapshot",
    "PortfolioState",
    "PositionView",
    "ComboInstrument",
    "ComboLeg",
    # Protocol & base
    "StrategyProtocol",
    "Strategy",
    # Execution log
    "ExecutionLog",
    # Risk
    "RiskGuard",
]
