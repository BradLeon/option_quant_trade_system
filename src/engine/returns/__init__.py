"""Returns and risk calculation module."""

from src.engine.returns.basic import (
    calc_annualized_return,
    calc_expected_return,
    calc_expected_std,
    calc_win_rate,
)
from src.engine.returns.kelly import calc_kelly, calc_kelly_from_trades
from src.engine.returns.option_expected import (
    StrategyType,
    calc_covered_call_metrics,
    calc_option_expected_return,
    calc_option_kelly_fraction,
    calc_option_return_std,
    calc_option_sharpe_ratio,
    calc_option_sharpe_ratio_annualized,
    calc_option_win_probability,
    calc_short_put_metrics,
    calc_short_strangle_metrics,
)
from src.engine.returns.risk import (
    calc_calmar_ratio,
    calc_max_drawdown,
    calc_sharpe_ratio,
)

__all__ = [
    # Basic returns
    "calc_annualized_return",
    "calc_win_rate",
    "calc_expected_return",
    "calc_expected_std",
    # Risk metrics
    "calc_sharpe_ratio",
    "calc_max_drawdown",
    "calc_calmar_ratio",
    # Kelly
    "calc_kelly",
    "calc_kelly_from_trades",
    # Option expected returns (strategy-agnostic interface)
    "StrategyType",
    "calc_short_put_metrics",
    "calc_covered_call_metrics",
    "calc_short_strangle_metrics",
    "calc_option_expected_return",
    "calc_option_return_std",
    "calc_option_sharpe_ratio",
    "calc_option_sharpe_ratio_annualized",
    "calc_option_kelly_fraction",
    "calc_option_win_probability",
]
