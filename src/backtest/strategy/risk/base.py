"""Risk Guard Protocol — Re-export from shared layer.

The RiskGuard protocol has been promoted to src/strategy/risk.py for use
by both backtest and live trading. This file re-exports for backward compatibility.
"""

from src.strategy.risk import RiskGuard  # noqa: F401

__all__ = ["RiskGuard"]
