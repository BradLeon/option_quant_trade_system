#!/usr/bin/env python3
"""
Extract key metrics from JSON backtest report files and save to CSV.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import csv

REPORTS_DIR = Path("/sessions/eager-eloquent-babbage/mnt/option_quant_trade_system/reports")
OUTPUT_FILE = REPORTS_DIR / "summary_metrics.csv"

# Field mapping: CSV column name -> (json path as tuple or function)
FIELD_DEFINITIONS = {
    "filename": lambda report_data, filename: filename,
    "strategy_version": lambda report_data, filename: report_data.get("config", {}).get("strategy_version") or report_data.get("summary", {}).get("config_name", "N/A"),
    "symbols": lambda report_data, filename: ",".join(report_data.get("summary", {}).get("symbols", [])),
    "start_date": lambda report_data, filename: report_data.get("summary", {}).get("start_date", "N/A"),
    "end_date": lambda report_data, filename: report_data.get("summary", {}).get("end_date", "N/A"),
    "initial_capital": lambda report_data, filename: report_data.get("metrics", {}).get("initial_capital", "N/A"),
    "final_capital": lambda report_data, filename: report_data.get("metrics", {}).get("final_nlv", "N/A"),
    "total_return_pct": lambda report_data, filename: report_data.get("metrics", {}).get("total_return_pct", "N/A"),
    "annualized_return_pct": lambda report_data, filename: report_data.get("metrics", {}).get("annualized_return", "N/A"),
    "max_drawdown_pct": lambda report_data, filename: report_data.get("metrics", {}).get("max_drawdown", "N/A"),
    "sharpe_ratio": lambda report_data, filename: report_data.get("metrics", {}).get("sharpe_ratio", "N/A"),
    "win_rate_pct": lambda report_data, filename: report_data.get("metrics", {}).get("win_rate", "N/A"),
    "total_trades": lambda report_data, filename: report_data.get("metrics", {}).get("total_trades", "N/A"),
    "avg_trade_pnl": lambda report_data, filename: report_data.get("metrics", {}).get("expectancy", "N/A"),
    "volatility": lambda report_data, filename: report_data.get("metrics", {}).get("volatility", "N/A"),
}

def extract_metrics_from_report(filepath: Path) -> Optional[Dict[str, Any]]:
    """Extract metrics from a single JSON report file."""
    try:
        with open(filepath, 'r') as f:
            report_data = json.load(f)

        metrics = {}
        filename = filepath.name

        for column_name, extractor in FIELD_DEFINITIONS.items():
            try:
                value = extractor(report_data, filename)
                metrics[column_name] = value
            except Exception as e:
                print(f"Warning: Failed to extract {column_name} from {filename}: {e}")
                metrics[column_name] = "N/A"

        return metrics
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON from {filepath}: {e}")
        return None
    except Exception as e:
        print(f"Error: Failed to process {filepath}: {e}")
        return None

def main():
    """Main function to extract metrics from all reports and write to CSV."""

    # Find all JSON files in reports directory
    json_files = sorted(REPORTS_DIR.glob("*_report.json"))

    if not json_files:
        print(f"No JSON report files found in {REPORTS_DIR}")
        return

    print(f"Found {len(json_files)} report files")

    all_metrics = []

    for filepath in json_files:
        print(f"Processing {filepath.name}...", end=" ")
        metrics = extract_metrics_from_report(filepath)
        if metrics:
            all_metrics.append(metrics)
            print("OK")
        else:
            print("FAILED")

    if not all_metrics:
        print("No metrics extracted successfully")
        return

    # Write to CSV
    fieldnames = list(FIELD_DEFINITIONS.keys())

    try:
        with open(OUTPUT_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_metrics)

        print(f"\nSuccessfully wrote {len(all_metrics)} records to {OUTPUT_FILE}")

        # Print summary to console
        print("\n" + "="*80)
        print("SUMMARY METRICS")
        print("="*80)
        with open(OUTPUT_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                try:
                    # Safe float conversions with defaults
                    total_ret = float(row['total_return_pct']) if row['total_return_pct'] and row['total_return_pct'] != 'N/A' else 0
                    ann_ret = float(row['annualized_return_pct']) if row['annualized_return_pct'] and row['annualized_return_pct'] != 'N/A' else 0
                    max_dd = float(row['max_drawdown_pct']) if row['max_drawdown_pct'] and row['max_drawdown_pct'] != 'N/A' else 0
                    sharpe = row['sharpe_ratio']
                    vol = float(row['volatility']) if row['volatility'] and row['volatility'] != 'N/A' else 0
                    win_rate = float(row['win_rate_pct']) if row['win_rate_pct'] and row['win_rate_pct'] != 'N/A' else 0
                    avg_pnl = float(row['avg_trade_pnl']) if row['avg_trade_pnl'] and row['avg_trade_pnl'] != 'N/A' else 0

                    print(f"\n[{i}] {row['filename']}")
                    print(f"    Strategy: {row['strategy_version']}")
                    print(f"    Symbols: {row['symbols']}")
                    print(f"    Period: {row['start_date']} to {row['end_date']}")
                    print(f"    Capital: ${row['initial_capital']:>15} → ${row['final_capital']:>15}")
                    print(f"    Return: {total_ret*100:>6.2f}% | Ann. Return: {ann_ret*100:>6.2f}%")
                    print(f"    Sharpe: {sharpe:>8} | Max DD: {max_dd*100:>6.2f}% | Volatility: {vol*100:>6.2f}%")
                    print(f"    Win Rate: {win_rate*100:>5.1f}% | Total Trades: {row['total_trades']:>5} | Avg Trade PnL: ${avg_pnl:>10.2f}")
                except Exception as e:
                    print(f"\n[{i}] {row['filename']} - Error formatting: {e}")

    except Exception as e:
        print(f"Error writing to CSV: {e}")

if __name__ == "__main__":
    main()
