"""Backtest Strategy Abstraction Layer (V2)

Strategy framework for backtesting. Core models and protocols are shared
with live trading via src/strategy/. This package adds backtest-specific
features (BacktestStrategy, SignalConverter, Registry).

Usage:
    from src.backtest.strategy import BacktestStrategyRegistry

    strategy = BacktestStrategyRegistry.create("sma_stock")
    signals = strategy.generate_signals(market, portfolio, data_provider)
"""

from src.backtest.strategy.models import (
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
from src.backtest.strategy.protocol import BacktestStrategy, StrategyProtocol
from src.backtest.strategy.registry import BacktestStrategyRegistry
from src.backtest.strategy.signal_converter import SignalConverter

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
    "BacktestStrategy",
    # Registry
    "BacktestStrategyRegistry",
    # Converter
    "SignalConverter",
]
