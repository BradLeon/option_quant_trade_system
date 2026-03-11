"""SMA200 Stock-Only Backtest Diagnostic

Purpose: Validate SMA200 timing signal using pure stock trades (no options),
isolating signal quality from LEAPS pricing effects.

Variants compared:
  1. Buy & Hold
  2. SMA200 Daily — trade on close vs SMA200 each day
  3. SMA200 Freq=5 — only allow position changes every 5 trading days
  4. SMA200 Lagged — use *previous day* close vs SMA200 (no look-ahead)

Data: /Volumes/ORICO/option_quant/stock_daily.parquet (SPY 2016–2026)
"""

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

# Add project root to path for engine imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.position.technical.moving_average import calc_sma

# ============================================================
# Config
# ============================================================
STOCK_PARQUET = Path("/Volumes/ORICO/option_quant/stock_daily.parquet")
SYMBOL = "SPY"
SMA_PERIOD = 200
DECISION_FREQ = 5
START_DATE = date(2016, 1, 4)
END_DATE = date(2026, 2, 27)
INITIAL_CAPITAL = 1_000_000.0


# ============================================================
# Data Loading
# ============================================================
def load_spy_prices() -> list[tuple[date, float]]:
    """Load SPY daily close from parquet, sorted by date."""
    table = pq.read_table(
        STOCK_PARQUET,
        filters=[("symbol", "=", SYMBOL)],
        columns=["date", "close"],
    )
    dates = table.column("date").to_pylist()
    closes = table.column("close").to_pylist()
    pairs = sorted(zip(dates, closes), key=lambda x: x[0])
    # Filter date range
    pairs = [(d, c) for d, c in pairs if START_DATE <= d <= END_DATE]
    return pairs


# ============================================================
# Strategy Results
# ============================================================
@dataclass
class BacktestResult:
    name: str
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    num_trades: int = 0
    # Trade log
    trades: list[dict] = field(default_factory=list)
    # Equity curve
    equity_curve: list[float] = field(default_factory=list)


def calc_metrics(
    name: str,
    equity_curve: list[float],
    trades: list[dict],
    years: float,
) -> BacktestResult:
    """Calculate standard performance metrics from equity curve."""
    result = BacktestResult(name=name)
    result.equity_curve = equity_curve
    result.trades = trades
    result.num_trades = len(trades)

    if not equity_curve or equity_curve[0] <= 0:
        return result

    # Total return
    result.total_return = (equity_curve[-1] / equity_curve[0] - 1) * 100

    # Annualized return
    if years > 0:
        result.annualized_return = (
            (equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1
        ) * 100

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd
    result.max_drawdown = -max_dd * 100

    # Sharpe (daily returns, annualized)
    if len(equity_curve) > 1:
        daily_rets = np.diff(equity_curve) / np.array(equity_curve[:-1])
        if np.std(daily_rets) > 0:
            result.sharpe = (np.mean(daily_rets) / np.std(daily_rets)) * np.sqrt(252)

    return result


# ============================================================
# Backtest Variants
# ============================================================
def run_buy_and_hold(prices: list[tuple[date, float]]) -> BacktestResult:
    """Buy on day 1, hold until end."""
    equity = []
    shares = INITIAL_CAPITAL / prices[0][1]
    for _, close in prices:
        equity.append(shares * close)
    years = (prices[-1][0] - prices[0][0]).days / 365.25
    return calc_metrics(
        "Buy & Hold",
        equity,
        [{"date": prices[0][0], "action": "BUY", "price": prices[0][1]}],
        years,
    )


def run_sma_daily(prices: list[tuple[date, float]]) -> BacktestResult:
    """Trade every day: in market if close > SMA200, else cash."""
    equity = []
    trades = []
    cash = INITIAL_CAPITAL
    shares = 0.0
    invested = False
    close_history: list[float] = []

    for dt, close in prices:
        close_history.append(close)

        sma = calc_sma(close_history, SMA_PERIOD) if len(close_history) >= SMA_PERIOD else None

        if sma is not None:
            should_invest = close > sma

            if should_invest and not invested:
                # BUY at close
                shares = cash / close
                cash = 0.0
                invested = True
                trades.append({"date": dt, "action": "BUY", "price": close, "sma": sma})
            elif not should_invest and invested:
                # SELL at close
                cash = shares * close
                pnl = cash - INITIAL_CAPITAL if not trades else None
                shares = 0.0
                invested = False
                trades.append({"date": dt, "action": "SELL", "price": close, "sma": sma})

        # Record equity
        equity.append(cash + shares * close)

    years = (prices[-1][0] - prices[0][0]).days / 365.25
    return calc_metrics("SMA200 Daily", equity, trades, years)


def run_sma_freq(prices: list[tuple[date, float]], freq: int = DECISION_FREQ) -> BacktestResult:
    """Only allow position changes every `freq` trading days."""
    equity = []
    trades = []
    cash = INITIAL_CAPITAL
    shares = 0.0
    invested = False
    close_history: list[float] = []
    day_count = 0

    for dt, close in prices:
        close_history.append(close)
        day_count += 1

        is_decision_day = (day_count % freq == 0)
        sma = calc_sma(close_history, SMA_PERIOD) if len(close_history) >= SMA_PERIOD else None

        if sma is not None and is_decision_day:
            should_invest = close > sma

            if should_invest and not invested:
                shares = cash / close
                cash = 0.0
                invested = True
                trades.append({"date": dt, "action": "BUY", "price": close, "sma": sma})
            elif not should_invest and invested:
                cash = shares * close
                shares = 0.0
                invested = False
                trades.append({"date": dt, "action": "SELL", "price": close, "sma": sma})

        equity.append(cash + shares * close)

    years = (prices[-1][0] - prices[0][0]).days / 365.25
    return calc_metrics(f"SMA200 Freq={freq}", equity, trades, years)


def run_sma_lagged(prices: list[tuple[date, float]]) -> BacktestResult:
    """Use *previous day* close vs SMA200 — no look-ahead at all."""
    equity = []
    trades = []
    cash = INITIAL_CAPITAL
    shares = 0.0
    invested = False
    close_history: list[float] = []

    for dt, close in prices:
        close_history.append(close)

        if len(close_history) >= SMA_PERIOD + 1:
            # SMA computed on all data up to yesterday (exclude today's close)
            prev_close = close_history[-2]
            sma = calc_sma(close_history[:-1], SMA_PERIOD)

            if sma is not None:
                should_invest = prev_close > sma

                if should_invest and not invested:
                    # Signal from yesterday, execute at today's close
                    shares = cash / close
                    cash = 0.0
                    invested = True
                    trades.append({
                        "date": dt, "action": "BUY", "price": close,
                        "signal_price": prev_close, "sma": sma,
                    })
                elif not should_invest and invested:
                    cash = shares * close
                    shares = 0.0
                    invested = False
                    trades.append({
                        "date": dt, "action": "SELL", "price": close,
                        "signal_price": prev_close, "sma": sma,
                    })

        equity.append(cash + shares * close)

    years = (prices[-1][0] - prices[0][0]).days / 365.25
    return calc_metrics("SMA200 Lagged", equity, trades, years)


# ============================================================
# Output
# ============================================================
def print_comparison(results: list[BacktestResult]) -> None:
    """Print comparison table."""
    print("\n" + "=" * 85)
    print("SMA200 Stock-Only Backtest — Signal Quality Diagnostic")
    print(f"Symbol: {SYMBOL}  |  Period: {START_DATE} → {END_DATE}  |  Capital: ${INITIAL_CAPITAL:,.0f}")
    print("=" * 85)

    header = f"{'Variant':<20} {'Return':>9} {'Ann.Ret':>9} {'MaxDD':>9} {'Sharpe':>8} {'Trades':>7} {'Final$':>12}"
    print(header)
    print("-" * 85)

    for r in results:
        final_val = r.equity_curve[-1] if r.equity_curve else 0
        print(
            f"{r.name:<20} {r.total_return:>+8.1f}% {r.annualized_return:>+8.1f}% "
            f"{r.max_drawdown:>+8.1f}% {r.sharpe:>8.2f} {r.num_trades:>7} "
            f"${final_val:>11,.0f}"
        )

    print("=" * 85)


def print_trade_log(result: BacktestResult, max_rows: int = 50) -> None:
    """Print trade log for a variant."""
    print(f"\n--- Trade Log: {result.name} ({len(result.trades)} trades) ---")
    for i, t in enumerate(result.trades[:max_rows]):
        extra = ""
        if "sma" in t:
            extra += f" SMA={t['sma']:.2f}"
        if "signal_price" in t:
            extra += f" sig_price={t['signal_price']:.2f}"
        print(f"  {i+1:3d}. {t['date']}  {t['action']:4s}  @ ${t['price']:.2f}{extra}")
    if len(result.trades) > max_rows:
        print(f"  ... ({len(result.trades) - max_rows} more)")


def print_round_trip_pnl(result: BacktestResult) -> None:
    """Analyze round-trip P&L (buy → sell pairs)."""
    trades = result.trades
    print(f"\n--- Round-Trip P&L: {result.name} ---")

    wins = 0
    losses = 0
    total_pnl = 0.0
    buy_price = None

    for t in trades:
        if t["action"] == "BUY":
            buy_price = t["price"]
        elif t["action"] == "SELL" and buy_price is not None:
            pnl_pct = (t["price"] / buy_price - 1) * 100
            total_pnl += pnl_pct
            status = "WIN " if pnl_pct > 0 else "LOSS"
            if pnl_pct > 0:
                wins += 1
            else:
                losses += 1
            print(
                f"  {t['date']}  SELL @ ${t['price']:.2f}  "
                f"(bought @ ${buy_price:.2f})  → {status} {pnl_pct:+.2f}%"
            )
            buy_price = None

    total_trips = wins + losses
    if total_trips > 0:
        print(f"\n  Summary: {wins}W / {losses}L  |  Win rate: {wins/total_trips*100:.0f}%  |  Cumulative round-trip: {total_pnl:+.1f}%")


def print_diagnosis(results: list[BacktestResult]) -> None:
    """Print diagnostic conclusions."""
    bh = results[0]
    daily = results[1]
    freq5 = results[2]
    lagged = results[3]

    print("\n" + "=" * 85)
    print("DIAGNOSTIC CONCLUSIONS")
    print("=" * 85)

    # 1. Is SMA200 signal profitable on stocks?
    if daily.total_return > 0:
        print(f"[OK] SMA200 Daily is profitable ({daily.total_return:+.1f}%)")
        if daily.total_return < bh.total_return:
            gap = bh.total_return - daily.total_return
            print(f"     BUT underperforms Buy & Hold by {gap:.1f}pp — strategy drag exists")
            print(f"     → LEAPS losses are AMPLIFIED by option pricing, but SMA signal itself has drag")
        else:
            print(f"     AND outperforms Buy & Hold — SMA signal is net positive")
            print(f"     → LEAPS losses come entirely from option pricing issues")
    else:
        print(f"[PROBLEM] SMA200 Daily is UNPROFITABLE ({daily.total_return:+.1f}%)")
        print(f"     → SMA200 signal itself loses money in this period!")
        print(f"     → Even perfect option pricing cannot save this strategy")

    # 2. Look-ahead bias
    diff_la = abs(daily.total_return - lagged.total_return)
    if diff_la < 5:
        print(f"\n[OK] Look-ahead negligible: Daily={daily.total_return:+.1f}% vs Lagged={lagged.total_return:+.1f}% (diff={diff_la:.1f}pp)")
    else:
        print(f"\n[WARNING] Look-ahead matters: Daily={daily.total_return:+.1f}% vs Lagged={lagged.total_return:+.1f}% (diff={diff_la:.1f}pp)")

    # 3. Decision frequency effect
    diff_freq = daily.total_return - freq5.total_return
    if abs(diff_freq) < 5:
        print(f"[OK] Freq=5 impact small: Daily={daily.total_return:+.1f}% vs Freq5={freq5.total_return:+.1f}% (diff={diff_freq:+.1f}pp)")
    else:
        print(f"[NOTE] Freq=5 impact: Daily={daily.total_return:+.1f}% vs Freq5={freq5.total_return:+.1f}% (diff={diff_freq:+.1f}pp)")

    # 4. Max DD comparison
    print(f"\n  MaxDD comparison: B&H={bh.max_drawdown:+.1f}% | Daily={daily.max_drawdown:+.1f}% | Freq5={freq5.max_drawdown:+.1f}% | Lagged={lagged.max_drawdown:+.1f}%")

    print("=" * 85)


# ============================================================
# Main
# ============================================================
def main():
    print("Loading SPY daily prices...")
    prices = load_spy_prices()
    print(f"  Loaded {len(prices)} trading days: {prices[0][0]} → {prices[-1][0]}")
    print(f"  Price range: ${prices[0][1]:.2f} → ${prices[-1][1]:.2f}")

    # Run all variants
    results = [
        run_buy_and_hold(prices),
        run_sma_daily(prices),
        run_sma_freq(prices),
        run_sma_lagged(prices),
    ]

    # Output
    print_comparison(results)

    for r in results[1:]:  # Skip buy & hold
        print_trade_log(r)
        print_round_trip_pnl(r)

    print_diagnosis(results)


if __name__ == "__main__":
    main()
