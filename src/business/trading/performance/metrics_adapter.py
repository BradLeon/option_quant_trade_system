"""Metrics Adapter — Convert LiveDailySnapshot[] to BacktestMetrics.

Bridges the gap between live trading snapshots and the backtest metrics engine.
Only portfolio-level metrics are computed (NLV curve); trade-level metrics
(win rate, profit factor, etc.) require round-trip trade matching and are
left for a future iteration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.backtest.analysis.metrics import BacktestMetrics
from src.business.trading.models.snapshot import LiveDailySnapshot


@dataclass
class _SnapshotProxy:
    """Minimal proxy that satisfies BacktestMetrics._calc_* methods.

    These methods only need `.date` and `.nlv` attributes.
    """

    date: date
    nlv: float
    withdrawal_amount: float = 0.0


def compute_live_metrics(
    snapshots: list[LiveDailySnapshot],
    config_name: str,
    initial_capital: float,
    risk_free_rate: float = 0.04,
) -> BacktestMetrics:
    """Compute BacktestMetrics from live daily snapshots.

    Only portfolio-level metrics are populated. Trade-level fields
    (total_trades, win_rate, profit_factor, etc.) remain at defaults.

    Args:
        snapshots: Chronologically sorted LiveDailySnapshot list (>=2 items).
        config_name: Strategy name for display.
        initial_capital: Starting NLV (typically snapshots[0].nlv).
        risk_free_rate: Annualized risk-free rate for Sharpe/Sortino.

    Returns:
        BacktestMetrics with portfolio-level metrics populated.
    """
    from src.engine.portfolio.returns import (
        calc_annualized_return,
        calc_calmar_ratio,
        calc_cvar,
        calc_max_drawdown,
        calc_sharpe_ratio,
        calc_sortino_ratio,
        calc_var,
    )

    # Build proxy snapshots for reuse of BacktestMetrics static methods
    proxies = [_SnapshotProxy(date=s.date, nlv=s.nlv) for s in snapshots]

    # Daily returns
    daily_returns = BacktestMetrics._calc_daily_returns(proxies)  # type: ignore[arg-type]
    equity_curve = [s.nlv for s in proxies]

    final_nlv = snapshots[-1].nlv
    total_return = final_nlv - initial_capital
    total_return_pct = total_return / initial_capital if initial_capital > 0 else 0.0

    # Risk-free daily rate
    rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1

    # Compute metrics
    annualized_return = calc_annualized_return(daily_returns) if daily_returns else None
    max_dd = calc_max_drawdown(equity_curve) if equity_curve else None
    volatility = BacktestMetrics._calc_annual_volatility(daily_returns) if daily_returns else None
    downside_vol = BacktestMetrics._calc_downside_volatility(daily_returns) if daily_returns else None
    var_95 = calc_var(daily_returns, 0.95) if daily_returns else None
    cvar_95 = calc_cvar(daily_returns, 0.95) if daily_returns else None
    sharpe = calc_sharpe_ratio(daily_returns, rf_daily) if daily_returns else None
    sortino = calc_sortino_ratio(daily_returns, rf_daily) if daily_returns else None
    calmar = calc_calmar_ratio(annualized_return, max_dd) if annualized_return and max_dd else None

    # Monthly returns + drawdown periods
    monthly_returns = BacktestMetrics._calc_monthly_returns(proxies)  # type: ignore[arg-type]
    drawdown_periods = BacktestMetrics._calc_drawdown_periods(proxies)  # type: ignore[arg-type]
    max_dd_duration = (
        max(p.duration_days for p in drawdown_periods) if drawdown_periods else None
    )

    trading_days = len(snapshots)

    return BacktestMetrics(
        config_name=config_name,
        start_date=snapshots[0].date,
        end_date=snapshots[-1].date,
        trading_days=trading_days,
        initial_capital=initial_capital,
        final_nlv=final_nlv,
        total_return=total_return,
        total_return_pct=total_return_pct,
        annualized_return=annualized_return,
        max_drawdown=max_dd,
        max_drawdown_duration=max_dd_duration,
        volatility=volatility,
        downside_volatility=downside_vol,
        var_95=var_95,
        cvar_95=cvar_95,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        monthly_returns=monthly_returns,
        drawdown_periods=drawdown_periods,
    )
