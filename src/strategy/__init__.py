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
    AlertType,
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
from src.strategy.protocol import BacktestStrategy, Strategy, StrategyProtocol
from src.strategy.registry import BacktestStrategyRegistry, StrategyRegistry
from src.strategy.risk import RiskGuard
from src.strategy.risk_guards.account_risk import AccountRiskConfig, AccountRiskGuard

__all__ = [
    # Core models
    "AlertType",
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
    "BacktestStrategy",
    # Registry
    "StrategyRegistry",
    "BacktestStrategyRegistry",
    # Execution log
    "ExecutionLog",
    # Risk
    "RiskGuard",
    "AccountRiskGuard",
    "AccountRiskConfig",
]
