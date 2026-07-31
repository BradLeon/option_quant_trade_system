#!/usr/bin/env python3
"""
Bull Put Spread Strategy — A/B Comparison Backtest

Runs multiple bull_put_spread variants + naked short_put baseline,
all with $100K capital and $1,500/month withdrawal on SPY.

Usage:
    uv run python scripts/income_strategy_comparison.py
    uv run python scripts/income_strategy_comparison.py --skip-download
"""

import sys
from datetime import date
from pathlib import Path

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.pipeline import BacktestPipeline
from src.engine.models.enums import StrategyType


# ── Configuration ──────────────────────────────────────────────────────────

DATA_DIR = "/Volumes/ORICO/option_quant"
START_DATE = date(2024, 1, 1)
END_DATE = date(2026, 3, 1)
SYMBOLS = ["SPY"]
INITIAL_CAPITAL = 100_000
MONTHLY_WITHDRAWAL = 1_500.0
REPORT_DIR = "reports/income_comparison"

# Strategy variants to compare
VARIANTS = [
    # (name, strategy_version, description)
    ("BPS_BASE", "bull_put_spread", "Base: 10 spreads, $5 width, 50% PT"),
    ("BPS_MORE", "bull_put_spread_more", "More: 8 spreads, $10 width, 50% PT"),
    ("BPS_TIGHT", "bull_put_spread_tight", "Tight exit: 65% profit target"),
    ("BPS_WIDE", "bull_put_spread_wide", "Wide: $15 spread width"),
    ("BPS_CONSERV", "bull_put_spread_conservative", "Conservative: 3×$5, δ0.20, 30-45 DTE"),
    # Naked short put comparison
    ("NAKED_PUT", "short_options_without_expire_itm_stock_trade", "Naked short put (no assignment)"),
]


def run_comparison(skip_download: bool = False) -> None:
    """Run all variants and print comparison table."""
    results = []

    for name, strategy_version, description in VARIANTS:
        print(f"\n{'='*60}")
        print(f"Running: {name} — {description}")
        print(f"{'='*60}")

        # Determine strategy_types based on variant
        if "short_options" in strategy_version:
            strategy_types = [StrategyType.SHORT_PUT, StrategyType.COVERED_CALL]
        else:
            # V2 strategies don't need strategy_types from config
            strategy_types = [StrategyType.SHORT_PUT]

        config = BacktestConfig(
            name=name,
            description=description,
            start_date=START_DATE,
            end_date=END_DATE,
            symbols=SYMBOLS,
            data_dir=DATA_DIR,
            initial_capital=INITIAL_CAPITAL,
            monthly_withdrawal=MONTHLY_WITHDRAWAL,
            strategy_types=strategy_types,
            strategy_version=strategy_version,
            max_positions=20,
            skip_market_check=True,
            benchmark_symbol="SPY",
        )

        pipeline = BacktestPipeline(config)
        try:
            result = pipeline.run(
                skip_data_check=skip_download,
                generate_report=True,
                report_dir=str(Path(REPORT_DIR) / name.lower()),
            )
            results.append((name, description, result))
            print(f"  Final NLV: ${result.backtest_result.final_nlv:,.0f}")
            print(f"  Total Return: {result.backtest_result.total_return_pct:.2%}")
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append((name, description, None))

    # ── Print comparison table ──
    print(f"\n\n{'='*100}")
    print("INCOME STRATEGY COMPARISON RESULTS")
    print(f"Period: {START_DATE} → {END_DATE} | Capital: ${INITIAL_CAPITAL:,} | Withdrawal: ${MONTHLY_WITHDRAWAL:,}/mo")
    print(f"{'='*100}")
    print(
        f"{'Variant':<20} {'Final NLV':>12} {'Total Ret':>10} {'Ann Ret':>10} "
        f"{'Max DD':>10} {'Sharpe':>8} {'Win Rate':>10} {'Trades':>8} "
        f"{'W-Adj Ret':>10} {'Coverage':>10}"
    )
    print("-" * 120)

    for name, description, result in results:
        if result is None:
            print(f"{name:<20} {'FAILED':>12}")
            continue

        metrics = result.metrics
        final_nlv = result.backtest_result.final_nlv
        total_ret = result.backtest_result.total_return_pct
        ann_ret = metrics.annualized_return if metrics.annualized_return else 0
        max_dd = metrics.max_drawdown if metrics.max_drawdown else 0
        sharpe = metrics.sharpe_ratio if metrics.sharpe_ratio else 0
        win_rate = metrics.win_rate if metrics.win_rate else 0
        trades = metrics.total_trades
        w_adj_ret = metrics.withdrawal_adjusted_return_pct if metrics.withdrawal_adjusted_return_pct else 0
        coverage = metrics.income_coverage_ratio if metrics.income_coverage_ratio else 0

        print(
            f"{name:<20} ${final_nlv:>10,.0f} {total_ret:>9.2%} {ann_ret:>9.2%} "
            f"{max_dd:>9.2%} {sharpe:>7.2f} {win_rate:>9.1%} {trades:>7d} "
            f"{w_adj_ret:>9.2%} {coverage:>9.2f}x"
        )

    print(f"{'='*100}")
    print("\nMetric definitions:")
    print("  W-Adj Ret  = (Final NLV + Total Withdrawals - Initial) / Initial")
    print("  Coverage   = Realized PnL / Total Withdrawals (>1.0x = income exceeds withdrawals)")
    print(f"  Total withdrawals per variant: ~${MONTHLY_WITHDRAWAL * ((END_DATE - START_DATE).days / 30):,.0f}")


if __name__ == "__main__":
    skip = "--skip-download" in sys.argv
    run_comparison(skip_download=skip)
