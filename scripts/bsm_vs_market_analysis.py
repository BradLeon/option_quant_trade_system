#!/usr/bin/env python3
"""BSM Theoretical Pricing vs Real Market Option Price Deviation Analysis.

Compares Black-Scholes theoretical prices (using market IV) against actual market
mid-prices from ThetaData historical option chains (SPY/QQQ, 2023-06 ~ 2026-02).

Purpose: Quantify BSM pricing accuracy to evaluate feasibility of using BSM-generated
synthetic option data for extending backtest periods before 2023.

Output: reports/bsm_accuracy/ — summary stats CSV + visualization PNGs.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest.data.duckdb_provider import DuckDBProvider
from src.data.models.option import OptionQuote, OptionType
from src.engine.bs.core import calc_bs_price
from src.engine.bs.greeks import calc_bs_greeks
from src.engine.models import BSParams

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
DATA_DIR = Path("/Volumes/ORICO/option_quant")
OUTPUT_DIR = PROJECT_ROOT / "reports" / "bsm_accuracy"
SYMBOLS = ["SPY", "QQQ"]
DATE_RANGE = (date(2023, 7, 1), date(2026, 2, 1))
SAMPLE_DAYS_PER_MONTH = 2  # sample 2 trading days per month
DEFAULT_RISK_FREE_RATE = 0.05  # fallback if TNX unavailable


def get_trading_days(symbol: str, start: date, end: date) -> list[date]:
    """Extract trading days from stock_daily parquet for the given symbol."""
    import duckdb

    try:
        conn = duckdb.connect(":memory:")
        rows = conn.execute(
            f"""
            SELECT DISTINCT date FROM read_parquet('{DATA_DIR}/stock_daily.parquet')
            WHERE symbol = ? AND date >= ? AND date <= ?
            ORDER BY date
            """,
            [symbol, start, end],
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Failed to get trading days: {e}")
        return []


def sample_trading_days(trading_days: list[date], per_month: int = 2) -> list[date]:
    """Sample ~per_month trading days from each calendar month."""
    by_month: dict[tuple[int, int], list[date]] = {}
    for d in trading_days:
        key = (d.year, d.month)
        by_month.setdefault(key, []).append(d)

    sampled = []
    for key in sorted(by_month):
        days = by_month[key]
        if len(days) <= per_month:
            sampled.extend(days)
        else:
            # Pick evenly spaced days
            indices = np.linspace(0, len(days) - 1, per_month, dtype=int)
            sampled.extend(days[i] for i in indices)
    return sampled


def get_risk_free_rate(provider: DuckDBProvider, as_of: date) -> float:
    """Get TNX rate for date, fallback to default.

    TNX index level = 10x the actual yield (e.g., TNX=45.73 → 4.573%).
    So we divide by 1000 to convert to decimal rate.
    """
    try:
        macro = provider.get_macro_data("^TNX", as_of - timedelta(days=10), as_of)
        if macro:
            # TNX is quoted at 10x yield: 45.73 → 4.573% → 0.04573
            return macro[-1].value / 1000.0
    except Exception:
        pass
    return DEFAULT_RISK_FREE_RATE


def compute_dte(expiry: date, as_of: date) -> int:
    """Compute days to expiry relative to as_of_date (not today)."""
    return (expiry - as_of).days


def classify_moneyness(spot: float, strike: float, is_call: bool) -> str:
    """Classify option as ITM/ATM/OTM based on moneyness ratio."""
    ratio = spot / strike
    if is_call:
        if ratio > 1.02:
            return "ITM"
        elif ratio < 0.98:
            return "OTM"
        else:
            return "ATM"
    else:  # put
        if ratio < 0.98:
            return "ITM"
        elif ratio > 1.02:
            return "OTM"
        else:
            return "ATM"


def classify_dte(dte: int) -> str:
    if dte < 30:
        return "Short (<30d)"
    elif dte <= 90:
        return "Medium (30-90d)"
    else:
        return "Long (>90d)"


def classify_iv(iv: float) -> str:
    if iv < 0.15:
        return "Low (<15%)"
    elif iv <= 0.30:
        return "Medium (15-30%)"
    else:
        return "High (>30%)"


def process_option_quote(
    quote: OptionQuote,
    spot_price: float,
    risk_free_rate: float,
    as_of: date,
    symbol: str,
) -> dict | None:
    """Process a single option quote: compute BSM price/Greeks and compare to market."""
    # Filter: need IV and bid/ask for meaningful comparison
    if quote.iv is None or quote.iv <= 0:
        return None
    if quote.bid is None or quote.ask is None:
        return None
    if quote.bid <= 0 or quote.ask <= 0:
        return None

    mid = (quote.bid + quote.ask) / 2.0
    if mid <= 0.05:  # skip near-zero options
        return None

    is_call = quote.contract.option_type == OptionType.CALL
    strike = quote.contract.strike_price
    expiry = quote.contract.expiry_date
    dte = compute_dte(expiry, as_of)

    if dte <= 0:  # expired
        return None
    if dte > 365:  # skip LEAPS > 1yr for cleaner analysis
        return None

    time_to_expiry = dte / 365.0

    params = BSParams(
        spot_price=spot_price,
        strike_price=strike,
        risk_free_rate=risk_free_rate,
        volatility=quote.iv,
        time_to_expiry=time_to_expiry,
        is_call=is_call,
    )

    bsm_price = calc_bs_price(params)
    if bsm_price is None or bsm_price <= 0:
        return None

    bsm_greeks = calc_bs_greeks(params)

    abs_error = mid - bsm_price
    pct_error = abs_error / mid * 100  # percentage of market price

    moneyness = classify_moneyness(spot_price, strike, is_call)
    dte_bucket = classify_dte(dte)
    iv_bucket = classify_iv(quote.iv)

    row = {
        "date": as_of,
        "symbol": symbol,
        "option_type": "call" if is_call else "put",
        "strike": strike,
        "expiry": expiry,
        "dte": dte,
        "dte_bucket": dte_bucket,
        "moneyness_ratio": spot_price / strike,
        "moneyness": moneyness,
        "iv": quote.iv,
        "iv_bucket": iv_bucket,
        "spot_price": spot_price,
        "market_bid": quote.bid,
        "market_ask": quote.ask,
        "market_mid": mid,
        "bsm_price": bsm_price,
        "abs_error": abs_error,
        "pct_error": pct_error,
        "abs_pct_error": abs(pct_error),
        # Greeks comparison
        "market_delta": quote.greeks.delta if quote.greeks else None,
        "market_gamma": quote.greeks.gamma if quote.greeks else None,
        "market_theta": quote.greeks.theta if quote.greeks else None,
        "market_vega": quote.greeks.vega if quote.greeks else None,
        "bsm_delta": bsm_greeks.get("delta"),
        "bsm_gamma": bsm_greeks.get("gamma"),
        "bsm_theta": bsm_greeks.get("theta"),
        "bsm_vega": bsm_greeks.get("vega"),
    }
    return row


def collect_data(provider: DuckDBProvider) -> pd.DataFrame:
    """Main data collection loop: sample dates, get chains, compute deviations."""
    all_rows = []

    # Get trading days from first symbol
    trading_days = get_trading_days(SYMBOLS[0], DATE_RANGE[0], DATE_RANGE[1])
    if not trading_days:
        logger.error("No trading days found!")
        return pd.DataFrame()

    sampled_days = sample_trading_days(trading_days, SAMPLE_DAYS_PER_MONTH)
    logger.info(f"Sampled {len(sampled_days)} trading days from {len(trading_days)} total")

    for i, day in enumerate(sampled_days):
        logger.info(f"[{i+1}/{len(sampled_days)}] Processing {day}")
        provider.set_as_of_date(day)
        rfr = get_risk_free_rate(provider, day)

        for symbol in SYMBOLS:
            stock_quote = provider.get_stock_quote(symbol)
            if stock_quote is None or stock_quote.close is None:
                logger.warning(f"  No stock data for {symbol} on {day}")
                continue
            spot = stock_quote.close

            chain = provider.get_option_chain(symbol)
            if chain is None:
                logger.warning(f"  No option chain for {symbol} on {day}")
                continue

            count = 0
            for quote in chain.calls + chain.puts:
                row = process_option_quote(quote, spot, rfr, day, symbol)
                if row:
                    all_rows.append(row)
                    count += 1

            logger.info(f"  {symbol}: {count} valid options (spot={spot:.2f}, rfr={rfr:.4f})")

    df = pd.DataFrame(all_rows)
    logger.info(f"Total records: {len(df)}")
    return df


# ── Statistics ─────────────────────────────────────────────────────────────

def compute_summary_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Compute summary statistics by grouping dimensions."""
    results = []

    def add_group(name: str, subset: pd.DataFrame):
        if len(subset) == 0:
            return
        ape = subset["abs_pct_error"]
        ae = subset["abs_error"].abs()
        results.append({
            "group": name,
            "count": len(subset),
            "mae_dollars": ae.mean(),
            "median_ae_dollars": ae.median(),
            "mape_pct": ape.mean(),
            "median_ape_pct": ape.median(),
            "mean_error_dollars": subset["abs_error"].mean(),
            "std_error_dollars": subset["abs_error"].std(),
            "r_squared": subset[["market_mid", "bsm_price"]].corr().iloc[0, 1] ** 2
            if len(subset) > 1 else None,
        })

    # Overall
    add_group("ALL", df)

    # By symbol
    for sym in df["symbol"].unique():
        add_group(f"Symbol: {sym}", df[df["symbol"] == sym])

    # By option type
    for otype in ["call", "put"]:
        add_group(f"Type: {otype}", df[df["option_type"] == otype])

    # By moneyness
    for m in ["ITM", "ATM", "OTM"]:
        add_group(f"Moneyness: {m}", df[df["moneyness"] == m])

    # By DTE bucket
    for b in df["dte_bucket"].unique():
        add_group(f"DTE: {b}", df[df["dte_bucket"] == b])

    # By IV bucket
    for b in df["iv_bucket"].unique():
        add_group(f"IV: {b}", df[df["iv_bucket"] == b])

    # Cross: moneyness x option_type
    for m in ["ITM", "ATM", "OTM"]:
        for otype in ["call", "put"]:
            subset = df[(df["moneyness"] == m) & (df["option_type"] == otype)]
            add_group(f"{m} {otype}", subset)

    return pd.DataFrame(results)


def compute_greeks_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Greeks deviation statistics."""
    results = []
    for greek in ["delta", "gamma", "theta", "vega"]:
        mkt_col = f"market_{greek}"
        bsm_col = f"bsm_{greek}"
        valid = df[[mkt_col, bsm_col]].dropna()
        if len(valid) == 0:
            continue
        diff = valid[mkt_col] - valid[bsm_col]
        results.append({
            "greek": greek,
            "count": len(valid),
            "mae": diff.abs().mean(),
            "median_ae": diff.abs().median(),
            "mean_error": diff.mean(),
            "std_error": diff.std(),
            "r_squared": valid.corr().iloc[0, 1] ** 2 if len(valid) > 1 else None,
        })
    return pd.DataFrame(results)


# ── Visualization ──────────────────────────────────────────────────────────

def plot_scatter_bsm_vs_market(df: pd.DataFrame, output_dir: Path):
    """Scatter plot: BSM price vs Market mid price."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, otype in zip(axes, ["call", "put"]):
        subset = df[df["option_type"] == otype]
        # Cap at $50 for readability
        subset = subset[(subset["market_mid"] <= 50) & (subset["bsm_price"] <= 50)]
        ax.scatter(subset["market_mid"], subset["bsm_price"], alpha=0.1, s=3, c="steelblue")
        lim = max(subset["market_mid"].max(), subset["bsm_price"].max()) * 1.05
        ax.plot([0, lim], [0, lim], "r--", lw=1, label="y=x (perfect)")
        ax.set_xlabel("Market Mid Price ($)")
        ax.set_ylabel("BSM Theoretical Price ($)")
        ax.set_title(f"{otype.upper()} Options")
        ax.legend()
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        ax.set_aspect("equal")

    fig.suptitle("BSM Theoretical Price vs Market Mid Price", fontsize=14)
    fig.tight_layout()
    fig.savefig(output_dir / "scatter_bsm_vs_market.png", dpi=150)
    plt.close(fig)
    logger.info("Saved scatter_bsm_vs_market.png")


def plot_error_distribution(df: pd.DataFrame, output_dir: Path):
    """Histogram of percentage errors."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    for ax, moneyness in zip(axes, ["ITM", "ATM", "OTM"]):
        subset = df[df["moneyness"] == moneyness]
        errors = subset["pct_error"].clip(-50, 50)
        ax.hist(errors, bins=80, color="steelblue", edgecolor="none", alpha=0.7)
        ax.axvline(0, color="red", ls="--", lw=1)
        ax.set_xlabel("Price Error (%)")
        ax.set_ylabel("Frequency")
        ax.set_title(f"{moneyness} (n={len(subset):,})")
        # Add stats text
        mae = subset["abs_pct_error"].mean()
        median = subset["abs_pct_error"].median()
        ax.text(0.95, 0.95, f"MAPE={mae:.2f}%\nMedian={median:.2f}%",
                transform=ax.transAxes, ha="right", va="top",
                fontsize=9, bbox=dict(boxstyle="round", fc="wheat", alpha=0.8))

    fig.suptitle("BSM Pricing Error Distribution by Moneyness", fontsize=14)
    fig.tight_layout()
    fig.savefig(output_dir / "error_distribution.png", dpi=150)
    plt.close(fig)
    logger.info("Saved error_distribution.png")


def plot_error_by_moneyness(df: pd.DataFrame, output_dir: Path):
    """Box plot of absolute percentage errors by moneyness."""
    fig, ax = plt.subplots(figsize=(10, 6))

    order = ["ITM", "ATM", "OTM"]
    data = [df[df["moneyness"] == m]["pct_error"].clip(-30, 30) for m in order]
    bp = ax.boxplot(data, labels=order, patch_artist=True, showfliers=False)
    colors = ["#66c2a5", "#fc8d62", "#8da0cb"]
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
    ax.axhline(0, color="red", ls="--", lw=0.8)
    ax.set_xlabel("Moneyness")
    ax.set_ylabel("Price Error (%)")
    ax.set_title("BSM Pricing Error by Moneyness")
    fig.tight_layout()
    fig.savefig(output_dir / "error_by_moneyness.png", dpi=150)
    plt.close(fig)
    logger.info("Saved error_by_moneyness.png")


def plot_error_by_dte(df: pd.DataFrame, output_dir: Path):
    """Box plot of errors by DTE bucket."""
    fig, ax = plt.subplots(figsize=(10, 6))

    order = ["Short (<30d)", "Medium (30-90d)", "Long (>90d)"]
    data = [df[df["dte_bucket"] == b]["pct_error"].clip(-30, 30) for b in order]
    bp = ax.boxplot(data, labels=order, patch_artist=True, showfliers=False)
    colors = ["#e78ac3", "#a6d854", "#ffd92f"]
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
    ax.axhline(0, color="red", ls="--", lw=0.8)
    ax.set_xlabel("Days to Expiry")
    ax.set_ylabel("Price Error (%)")
    ax.set_title("BSM Pricing Error by DTE Bucket")
    fig.tight_layout()
    fig.savefig(output_dir / "error_by_dte.png", dpi=150)
    plt.close(fig)
    logger.info("Saved error_by_dte.png")


def plot_error_time_trend(df: pd.DataFrame, output_dir: Path):
    """MAPE over time — does error vary with market regime?"""
    daily = df.groupby("date").agg(
        mape=("abs_pct_error", "mean"),
        count=("abs_pct_error", "count"),
    ).reset_index()

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(daily["date"], daily["mape"], "o-", ms=3, lw=1, color="steelblue")
    ax.set_xlabel("Date")
    ax.set_ylabel("MAPE (%)")
    ax.set_title("BSM Pricing MAPE Over Time (sampled days)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "error_time_trend.png", dpi=150)
    plt.close(fig)
    logger.info("Saved error_time_trend.png")


def plot_greeks_scatter(df: pd.DataFrame, output_dir: Path):
    """Scatter plots: BSM Greeks vs Market Greeks for delta and theta."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, greek in zip(axes, ["delta", "theta"]):
        mkt = f"market_{greek}"
        bsm = f"bsm_{greek}"
        valid = df[[mkt, bsm]].dropna()
        if len(valid) == 0:
            continue
        ax.scatter(valid[mkt], valid[bsm], alpha=0.05, s=2, c="steelblue")
        lo = min(valid[mkt].min(), valid[bsm].min())
        hi = max(valid[mkt].max(), valid[bsm].max())
        ax.plot([lo, hi], [lo, hi], "r--", lw=1, label="y=x")
        ax.set_xlabel(f"Market {greek.title()}")
        ax.set_ylabel(f"BSM {greek.title()}")
        ax.set_title(f"{greek.title()}: BSM vs Market")
        ax.legend()
        r2 = valid.corr().iloc[0, 1] ** 2
        ax.text(0.05, 0.95, f"R²={r2:.4f}", transform=ax.transAxes, va="top",
                fontsize=10, bbox=dict(boxstyle="round", fc="wheat", alpha=0.8))

    fig.suptitle("Greeks Comparison: BSM vs Market (ThetaData)", fontsize=14)
    fig.tight_layout()
    fig.savefig(output_dir / "greeks_comparison.png", dpi=150)
    plt.close(fig)
    logger.info("Saved greeks_comparison.png")


def plot_error_by_iv(df: pd.DataFrame, output_dir: Path):
    """Box plot of errors by IV bucket."""
    fig, ax = plt.subplots(figsize=(10, 6))

    order = ["Low (<15%)", "Medium (15-30%)", "High (>30%)"]
    data = [df[df["iv_bucket"] == b]["pct_error"].clip(-30, 30) for b in order]
    bp = ax.boxplot(data, labels=order, patch_artist=True, showfliers=False)
    colors = ["#b3de69", "#fb8072", "#80b1d3"]
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
    ax.axhline(0, color="red", ls="--", lw=0.8)
    ax.set_xlabel("IV Level")
    ax.set_ylabel("Price Error (%)")
    ax.set_title("BSM Pricing Error by IV Level")
    fig.tight_layout()
    fig.savefig(output_dir / "error_by_iv.png", dpi=150)
    plt.close(fig)
    logger.info("Saved error_by_iv.png")


# ── Feasibility Conclusion ────────────────────────────────────────────────

def print_feasibility_verdict(summary: pd.DataFrame, greeks_stats: pd.DataFrame):
    """Print feasibility assessment based on predefined thresholds."""
    print("\n" + "=" * 70)
    print("  BSM SYNTHETIC DATA FEASIBILITY ASSESSMENT")
    print("=" * 70)

    thresholds = {
        "MAPE (ATM)": {"good": 5, "caution": 15, "col": "Moneyness: ATM"},
        "MAPE (OTM)": {"good": 10, "caution": 20, "col": "Moneyness: OTM"},
    }

    for label, cfg in thresholds.items():
        row = summary[summary["group"] == cfg["col"]]
        if row.empty:
            print(f"  {label}: NO DATA")
            continue
        val = row.iloc[0]["mape_pct"]
        if val < cfg["good"]:
            verdict = "✓ FEASIBLE"
        elif val < cfg["caution"]:
            verdict = "⚠ CAUTION"
        else:
            verdict = "✗ NOT RECOMMENDED"
        print(f"  {label}: {val:.2f}%  → {verdict}  (threshold: <{cfg['good']}% good, <{cfg['caution']}% caution)")

    # R² overall
    all_row = summary[summary["group"] == "ALL"]
    if not all_row.empty:
        r2 = all_row.iloc[0]["r_squared"]
        if r2 is not None:
            if r2 > 0.95:
                verdict = "✓ FEASIBLE"
            elif r2 > 0.85:
                verdict = "⚠ CAUTION"
            else:
                verdict = "✗ NOT RECOMMENDED"
            print(f"  R² (overall): {r2:.4f}  → {verdict}  (threshold: >0.95 good, >0.85 caution)")

    # Greeks: delta MAE
    if not greeks_stats.empty:
        delta_row = greeks_stats[greeks_stats["greek"] == "delta"]
        if not delta_row.empty:
            mae = delta_row.iloc[0]["mae"]
            if mae < 0.03:
                verdict = "✓ FEASIBLE"
            elif mae < 0.10:
                verdict = "⚠ CAUTION"
            else:
                verdict = "✗ NOT RECOMMENDED"
            print(f"  Delta MAE: {mae:.4f}  → {verdict}  (threshold: <0.03 good, <0.10 caution)")

    print("=" * 70 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Data dir: {DATA_DIR}")
    logger.info(f"Output dir: {OUTPUT_DIR}")
    logger.info(f"Symbols: {SYMBOLS}")
    logger.info(f"Date range: {DATE_RANGE[0]} to {DATE_RANGE[1]}")

    provider = DuckDBProvider(data_dir=str(DATA_DIR), as_of_date=DATE_RANGE[0])

    # ── Collect data ──
    logger.info("Collecting BSM vs market data...")
    df = collect_data(provider)
    if df.empty:
        logger.error("No data collected. Check data directory and date range.")
        return

    # Save raw data
    df.to_csv(OUTPUT_DIR / "raw_data.csv", index=False)
    logger.info(f"Saved raw_data.csv ({len(df):,} records)")

    # ── Summary statistics ──
    summary = compute_summary_stats(df)
    summary.to_csv(OUTPUT_DIR / "summary_stats.csv", index=False)
    logger.info("Saved summary_stats.csv")
    print("\n── Summary Statistics ──")
    print(summary.to_string(index=False, float_format="%.4f"))

    greeks_stats = compute_greeks_stats(df)
    greeks_stats.to_csv(OUTPUT_DIR / "greeks_stats.csv", index=False)
    logger.info("Saved greeks_stats.csv")
    print("\n── Greeks Deviation ──")
    print(greeks_stats.to_string(index=False, float_format="%.6f"))

    # ── Visualization ──
    logger.info("Generating plots...")
    plot_scatter_bsm_vs_market(df, OUTPUT_DIR)
    plot_error_distribution(df, OUTPUT_DIR)
    plot_error_by_moneyness(df, OUTPUT_DIR)
    plot_error_by_dte(df, OUTPUT_DIR)
    plot_error_by_iv(df, OUTPUT_DIR)
    plot_error_time_trend(df, OUTPUT_DIR)
    plot_greeks_scatter(df, OUTPUT_DIR)

    # ── Feasibility verdict ──
    print_feasibility_verdict(summary, greeks_stats)

    logger.info(f"Done! All outputs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
