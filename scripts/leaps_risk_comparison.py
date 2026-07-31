"""LEAPS Risk Improvement A/B Comparison — run 6 strategy variants and compare.

Variants:
  - baseline:          Original spy_leaps_only_vol_target (no changes)
  - V1 theta_guard:    Roll earlier at DTE=90 (vs 60)
  - V2 vega_guard:     Reduce 50% when VIX spikes > 30% above SMA20
  - V3a rebal_down:    Rebalance only reduces, never adds on dips
  - V3b stop_loss:     Exit positions with > 30% unrealized loss
  - V3c dd_deleverage: Halve max leverage on 10% portfolio drawdown

    所有变体继承 MomentumMixedStrategy，仅 override compute_exit_signals() 或 _rebalance_signals()。

     ┌─────────────────┬───────────────────────────┬──────────────────────────────────────────────────────────┐
     │      变体       │          策略名           │                          改动点                          │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ 基准            │ leaps_baseline            │ 原始策略，无改动                                         │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V1: Theta 监控  │ leaps_theta_guard         │ DTE < roll_dte + 30 时提前 roll（roll_dte=90 而非 60）   │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V2: Vega 保护   │ leaps_vega_guard          │ 当 VIX 上升超 30%（vs 20日均值）时减仓 50%               │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V3a: 单向再平衡 │ leaps_rebal_down_only     │ 再平衡仅减仓，不加仓（下跌不补仓）                       │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V3b: 持仓止损   │ leaps_stop_loss           │ 单持仓浮亏 > 30% 触发 EXIT                               │
     ├─────────────────┼───────────────────────────┼──────────────────────────────────────────────────────────┤
     │ V3c: 回撤降杠杆 │ leaps_drawdown_deleverage │ Portfolio drawdown > 10% 时 max_exposure 从 3.0 降到 1.5 │
     └─────────────────┴───────────────────────────┴──────────────────────────────────────────────────────────┘

     ---
     
Usage:
    uv run python scripts/leaps_risk_comparison.py
"""

import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.pipeline import BacktestPipeline

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Show INFO only for our comparison script
logger = logging.getLogger("leaps_comparison")
logger.setLevel(logging.INFO)

# ── Config ──

STRATEGIES = [
    ("leaps_baseline", "Baseline (original)"),
    ("leaps_theta_guard", "V1: Theta Guard (roll@90)"),
    ("leaps_vega_guard", "V2: Vega Guard (VIX spike)"),
    ("leaps_rebal_down_only", "V3a: Rebal Down Only"),
    ("leaps_stop_loss", "V3b: Stop Loss (-30%)"),
    ("leaps_dd_deleverage", "V3c: DD Deleverage"),
]

SYMBOLS = ["QQQ"]
BENCHMARK = "QQQ"
# Need extra lookback for SMA200 calculation (~300 trading days before start)
DATA_START_DATE = date(2015, 1, 1)
START_DATE = date(2016, 6, 1)
END_DATE = date(2026, 3, 1)
INITIAL_CAPITAL = 1_000_000
DATA_DIR = "data/backtest"


# ── Data Preparation ──

def ensure_stock_data(symbols: list[str], start: date, end: date, data_dir: str):
    """Download stock OHLCV data via yfinance and save as stock_daily.parquet."""
    out_path = Path(data_dir) / "stock_daily.parquet"

    # Check if data already covers the range
    if out_path.exists():
        existing = pd.read_parquet(out_path)
        for sym in symbols:
            sym_data = existing[existing["symbol"] == sym]
            if len(sym_data) > 0:
                min_date = pd.Timestamp(sym_data["date"].min()).date()
                max_date = pd.Timestamp(sym_data["date"].max()).date()
                if min_date <= start and max_date >= end - timedelta(days=5):
                    logger.info(f"Stock data for {sym} already exists ({min_date} ~ {max_date})")
                    continue
        # If all symbols are covered, return
        all_covered = True
        for sym in symbols:
            sym_data = existing[existing["symbol"] == sym]
            if len(sym_data) == 0:
                all_covered = False
                break
            min_date = pd.Timestamp(sym_data["date"].min()).date()
            max_date = pd.Timestamp(sym_data["date"].max()).date()
            if min_date > start or max_date < end - timedelta(days=5):
                all_covered = False
                break
        if all_covered:
            return

    import yfinance as yf

    logger.info(f"Downloading stock data for {symbols} ({start} ~ {end})...")

    all_records = []
    for sym in symbols:
        ticker = yf.Ticker(sym)
        df = ticker.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
        if df.empty:
            logger.warning(f"No data for {sym}")
            continue
        for idx, row in df.iterrows():
            dt = idx.date() if hasattr(idx, "date") else idx
            all_records.append({
                "symbol": sym,
                "date": dt,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
                "count": 0,
                "bid": float(row["Close"]),  # Approximation
                "ask": float(row["Close"]),
            })

    if not all_records:
        raise RuntimeError(f"Failed to download stock data for {symbols}")

    new_df = pd.DataFrame(all_records)
    new_df["date"] = pd.to_datetime(new_df["date"]).dt.date

    # Merge with existing if present
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        old_df = pd.read_parquet(out_path)
        old_df["date"] = pd.to_datetime(old_df["date"]).dt.date
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
    else:
        combined = new_df

    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)
    table = pa.Table.from_pandas(combined, preserve_index=False)
    pq.write_table(table, out_path)
    logger.info(f"Saved {len(combined)} stock records to {out_path}")


def ensure_macro_data(start: date, end: date, data_dir: str):
    """Download VIX, VIX3M, TNX macro data via yfinance."""
    out_path = Path(data_dir) / "macro_daily.parquet"

    if out_path.exists():
        existing = pd.read_parquet(out_path)
        indicators = existing["indicator"].unique() if "indicator" in existing.columns else []
        if "^VIX" in indicators and "^TNX" in indicators:
            vix_data = existing[existing["indicator"] == "^VIX"]
            if len(vix_data) > 100:
                logger.info("Macro data already exists")
                return

    import yfinance as yf

    logger.info("Downloading macro data (VIX, VIX3M, TNX)...")

    macro_map = {
        "^VIX": "^VIX",
        "^VIX3M": "^VIX3M",
        "^TNX": "^TNX",
    }

    all_records = []
    for indicator, ticker_sym in macro_map.items():
        try:
            ticker = yf.Ticker(ticker_sym)
            df = ticker.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
            if df.empty:
                logger.warning(f"No macro data for {indicator}")
                continue
            for idx, row in df.iterrows():
                dt = idx.date() if hasattr(idx, "date") else idx
                all_records.append({
                    "indicator": indicator,
                    "date": dt,
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(row["Close"]),
                    "volume": int(row.get("Volume", 0)),
                })
        except Exception as e:
            logger.warning(f"Failed to download {indicator}: {e}")

    if not all_records:
        logger.warning("No macro data downloaded — VIX will default to 20.0")
        return

    new_df = pd.DataFrame(all_records)
    new_df["date"] = pd.to_datetime(new_df["date"]).dt.date

    Path(data_dir).mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        old_df = pd.read_parquet(out_path)
        old_df["date"] = pd.to_datetime(old_df["date"]).dt.date
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["indicator", "date"], keep="last")
    else:
        combined = new_df

    combined = combined.sort_values(["indicator", "date"]).reset_index(drop=True)
    table = pa.Table.from_pandas(combined, preserve_index=False)
    pq.write_table(table, out_path)
    logger.info(f"Saved {len(combined)} macro records to {out_path}")


# ── Backtest Runner ──

def run_single_backtest(strategy_name: str, label: str) -> dict:
    """Run a single backtest and return key metrics."""
    logger.info(f"Running {label} ({strategy_name})...")
    t0 = time.time()

    config = BacktestConfig(
        name=strategy_name,
        start_date=START_DATE,
        end_date=END_DATE,
        symbols=SYMBOLS,
        initial_capital=INITIAL_CAPITAL,
        strategy_version=strategy_name,
        use_synthetic_fallback=True,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
    )

    pipeline = BacktestPipeline(config)
    try:
        result = pipeline.run(skip_data_check=True, generate_report=False)
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        import traceback
        traceback.print_exc()
        return {
            "strategy": strategy_name,
            "label": label,
            "error": str(e),
        }

    elapsed = time.time() - t0
    metrics = result.metrics
    br = result.backtest_result

    # Benchmark comparison
    bench = result.benchmark_result
    bench_return = bench.benchmark_total_return if bench else None

    row = {
        "strategy": strategy_name,
        "label": label,
        "total_return_pct": metrics.total_return_pct,
        "annualized_return": metrics.annualized_return,
        "max_drawdown": metrics.max_drawdown,
        "sharpe_ratio": metrics.sharpe_ratio,
        "sortino_ratio": metrics.sortino_ratio,
        "calmar_ratio": metrics.calmar_ratio,
        "volatility": metrics.volatility,
        "total_trades": br.total_trades,
        "win_rate": br.win_rate,
        "profit_factor": br.profit_factor,
        "total_commission": br.total_commission,
        "total_slippage": br.total_slippage,
        "final_nlv": br.final_nlv,
        "trading_days": br.trading_days,
        "benchmark_return": bench_return,
        "elapsed_seconds": round(elapsed, 1),
    }

    logger.info(
        f"  Done: return={metrics.total_return_pct:+.1%} "
        f"maxDD={metrics.max_drawdown or 0:.1%} "
        f"sharpe={metrics.sharpe_ratio or 0:.2f} "
        f"trades={br.total_trades} "
        f"({elapsed:.1f}s)"
    )
    return row


# ── Display ──

def format_pct(v, width=8):
    if v is None:
        return "N/A".rjust(width)
    return f"{v:+.1%}".rjust(width)


def format_float(v, width=8, decimals=2):
    if v is None:
        return "N/A".rjust(width)
    return f"{v:.{decimals}f}".rjust(width)


def print_comparison_table(results: list[dict]):
    """Print formatted comparison table to terminal."""
    print()
    print("=" * 100)
    print("LEAPS Risk Improvement Comparison")
    print(f"Period: {START_DATE} ~ {END_DATE}")
    print(f"Symbol: {', '.join(SYMBOLS)} | Capital: ${INITIAL_CAPITAL:,.0f} | Benchmark: {BENCHMARK} Buy&Hold")
    print("=" * 110)

    # Show benchmark return if available
    bench_ret = next((r.get("benchmark_return") for r in results if r.get("benchmark_return") is not None), None)
    if bench_ret is not None:
        print(f"Benchmark ({BENCHMARK} Buy&Hold): {bench_ret:+.1%}")
    print()

    # Header
    header = (
        f"{'Strategy':<30} {'Return':>8} {'Ann.Ret':>8} {'MaxDD':>8} "
        f"{'Sharpe':>8} {'Calmar':>8} {'Vol':>8} {'Trades':>7} {'WinRate':>8}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        if "error" in r:
            print(f"{r['label']:<30} ERROR: {r['error']}")
            continue
        line = (
            f"{r['label']:<30} "
            f"{format_pct(r['total_return_pct'])} "
            f"{format_pct(r['annualized_return'])} "
            f"{format_pct(r['max_drawdown'])} "
            f"{format_float(r['sharpe_ratio'])} "
            f"{format_float(r['calmar_ratio'])} "
            f"{format_pct(r['volatility'])} "
            f"{r['total_trades']:>7} "
            f"{format_pct(r['win_rate'])}"
        )
        print(line)

    print()


def analyze_results(results: list[dict]):
    """Print analysis summary."""
    valid = [r for r in results if "error" not in r and r.get("trading_days", 0) > 0]
    if not valid:
        print("No valid results to analyze.")
        return

    print("=" * 100)
    print("Analysis")
    print("=" * 100)

    # Best by each metric
    best_return = max(valid, key=lambda r: r["total_return_pct"] or -999)
    best_dd = min(valid, key=lambda r: abs(r["max_drawdown"] or 999))
    best_sharpe = max(valid, key=lambda r: r["sharpe_ratio"] or -999)
    best_calmar = max(valid, key=lambda r: r["calmar_ratio"] or -999)

    baseline = next((r for r in valid if r["strategy"] == "leaps_baseline"), None)

    print(f"\nBest Return:        {best_return['label']} ({format_pct(best_return['total_return_pct'], 0)})")
    print(f"Lowest MaxDD:       {best_dd['label']} ({format_pct(best_dd['max_drawdown'], 0)})")
    print(f"Best Sharpe:        {best_sharpe['label']} ({format_float(best_sharpe['sharpe_ratio'], 0)})")
    print(f"Best Calmar:        {best_calmar['label']} ({format_float(best_calmar['calmar_ratio'], 0)})")

    if baseline:
        print(f"\n--- vs Baseline ---")
        bl_ret = baseline["total_return_pct"] or 0
        bl_dd = abs(baseline["max_drawdown"] or 0)
        bl_sharpe = baseline["sharpe_ratio"] or 0

        for r in valid:
            if r["strategy"] == "leaps_baseline":
                continue
            ret_diff = (r["total_return_pct"] or 0) - bl_ret
            dd_diff = abs(r["max_drawdown"] or 0) - bl_dd
            sharpe_diff = (r["sharpe_ratio"] or 0) - bl_sharpe
            print(
                f"  {r['label']:<28} "
                f"Return: {ret_diff:+.1%}  "
                f"MaxDD: {dd_diff:+.1%}  "
                f"Sharpe: {sharpe_diff:+.2f}"
            )

    print()


# ── Main ──

def main():
    # Step 0: Ensure data is available
    logger.info("Step 0: Ensuring stock + macro data...")
    ensure_stock_data(SYMBOLS, DATA_START_DATE, END_DATE, DATA_DIR)
    ensure_macro_data(DATA_START_DATE, END_DATE, DATA_DIR)

    # Step 1: Run backtests
    results = []
    total_t0 = time.time()

    for strategy_name, label in STRATEGIES:
        row = run_single_backtest(strategy_name, label)
        results.append(row)

    total_elapsed = time.time() - total_t0
    logger.info(f"All backtests completed in {total_elapsed:.0f}s")

    # Step 2: Print results
    print_comparison_table(results)
    analyze_results(results)

    # Step 3: Save JSON
    output_path = Path(__file__).parent / "leaps_risk_comparison_results.json"
    with open(output_path, "w") as f:
        json.dump(
            {
                "config": {
                    "symbols": SYMBOLS,
                    "start_date": START_DATE.isoformat(),
                    "end_date": END_DATE.isoformat(),
                    "initial_capital": INITIAL_CAPITAL,
                },
                "results": results,
                "total_elapsed_seconds": round(total_elapsed, 1),
            },
            f,
            indent=2,
            default=str,
        )
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
