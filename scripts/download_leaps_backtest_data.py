#!/usr/bin/env python3
"""Download 10-year stock/macro data for LEAPS backtest via IBKR TWS API.

Since synthetic LEAPS option chains are generated via B-S model,
we only need:
1. Stock daily OHLCV data → stock_daily.parquet
2. Macro indicators (VIX, VIX3M, TNX, etc.) → macro_daily.parquet

No option chain data download is needed — SyntheticLeapsProvider generates
it on the fly during backtest execution.

Prerequisites:
  - TWS running and logged in
  - API enabled (Edit → Global Configuration → API → Settings)
  - Default port: 7497 (paper) or 7496 (live)

Usage:
    # Download SPY 10-year data (paper trading port)
    uv run python scripts/download_leaps_backtest_data.py

    # Custom symbols and date range
    uv run python scripts/download_leaps_backtest_data.py \
        --symbols SPY QQQ AAPL \
        --start 2016-01-01 --end 2026-03-01

    # Live trading port
    uv run python scripts/download_leaps_backtest_data.py --port 7496

    # Custom data directory
    uv run python scripts/download_leaps_backtest_data.py \
        --data-dir /Volumes/ORICO/option_quant
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_SYMBOLS = ["SPY"]
DEFAULT_START = "2016-01-01"
DEFAULT_END = "2026-03-01"
DEFAULT_DATA_DIR = "/Volumes/ORICO/option_quant"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7497
DEFAULT_CLIENT_ID = 98  # Avoid conflict with other scripts

# Macro indicators: (IBKR contract type, symbol, exchange, whatToShow)
MACRO_INDICATORS = [
    ("Index", "VIX", "CBOE", "TRADES", "^VIX"),
    ("Index", "VIX3M", "CBOE", "TRADES", "^VIX3M"),
    ("Index", "VIX9D", "CBOE", "TRADES", "^VIX9D"),
    # TNX = 10Y Treasury — IBKR provides it as an index
    ("Index", "TNX", "CBOE", "TRADES", "^TNX"),
    ("Index", "TYX", "CBOE", "TRADES", "^TYX"),
    ("Index", "IRX", "CBOE", "TRADES", "^IRX"),
    ("Index", "FVX", "CBOE", "TRADES", "^FVX"),
    # Major indices
    ("Index", "SPX", "CBOE", "TRADES", "^GSPC"),
]

# How many years to pull per segment (IBKR max ~1Y per request for daily)
YEARS_PER_SEGMENT = 10  # Up to 10Y for stocks


async def download_stock_data_ibkr(
    ib,
    symbols: list[str],
    start: date,
    end: date,
    data_dir: Path,
) -> int:
    """Download stock daily OHLCV via IBKR TWS, save as stock_daily.parquet.

    IBKR returns max ~1 year of daily bars per request, so we paginate
    backwards from end_date.

    Returns:
        Total number of new records.
    """
    from ib_async import Stock, util

    logger.info(f"Downloading stock data for {symbols} ({start} ~ {end})")
    total_years = (end - start).days / 365.0
    segments = max(1, int(total_years) + 1)

    all_records = []

    for sym in symbols:
        logger.info(f"  Fetching {sym} ({segments} segments)...")
        contract = Stock(sym, "ARCA", "USD")
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            logger.warning(f"  Failed to qualify contract for {sym}")
            continue
        contract = qualified[0]

        bars_list = []
        end_dt = ""  # Empty = current time

        for i in range(segments):
            logger.info(f"    Segment {i + 1}/{segments}...")
            try:
                bars = await ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime=end_dt,
                    durationStr="1 Y",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                )
            except Exception as e:
                logger.warning(f"    Segment {i + 1} failed: {e}")
                break

            if not bars:
                logger.info(f"    No more data at segment {i + 1}")
                break

            bars_list = list(bars) + bars_list
            earliest = bars[0].date
            if isinstance(earliest, str):
                end_dt = earliest
            else:
                end_dt = earliest.strftime("%Y%m%d %H:%M:%S")

            await asyncio.sleep(2)  # Avoid pacing violation

        if not bars_list:
            logger.warning(f"  No data for {sym}")
            continue

        df = util.df(bars_list)
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates(subset="date").sort_values("date")
        # Filter to target range
        df = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)]

        for _, row in df.iterrows():
            all_records.append({
                "symbol": sym,
                "date": row["date"].date() if hasattr(row["date"], "date") else row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "count": int(row.get("barCount", 0)),
                "bid": float(row["close"]),  # EOD: bid ≈ close
                "ask": float(row["close"]),
            })

        logger.info(f"  {sym}: {len(df)} records ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")

    if not all_records:
        logger.warning("No stock data downloaded")
        return 0

    return _save_stock_parquet(all_records, data_dir)


async def download_macro_data_ibkr(
    ib,
    start: date,
    end: date,
    data_dir: Path,
) -> int:
    """Download macro indicators via IBKR TWS, save as macro_daily.parquet.

    Returns:
        Total number of new records.
    """
    from ib_async import Index, util

    logger.info(f"Downloading macro data ({start} ~ {end})")
    total_years = (end - start).days / 365.0
    segments = max(1, int(total_years) + 1)

    all_records = []

    for contract_type, symbol, exchange, what_to_show, indicator_name in MACRO_INDICATORS:
        logger.info(f"  Fetching {indicator_name} ({symbol}@{exchange})...")

        contract = Index(symbol, exchange, "USD")
        try:
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                logger.warning(f"  Failed to qualify {symbol}")
                continue
            contract = qualified[0]
        except Exception as e:
            logger.warning(f"  Failed to qualify {symbol}: {e}")
            continue

        bars_list = []
        end_dt = ""

        for i in range(segments):
            try:
                bars = await ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime=end_dt,
                    durationStr="1 Y",
                    barSizeSetting="1 day",
                    whatToShow=what_to_show,
                    useRTH=True,
                    formatDate=1,
                )
            except Exception as e:
                logger.warning(f"    Segment {i + 1} error for {symbol}: {e}")
                break

            if not bars:
                break

            bars_list = list(bars) + bars_list
            earliest = bars[0].date
            if isinstance(earliest, str):
                end_dt = earliest
            else:
                end_dt = earliest.strftime("%Y%m%d %H:%M:%S")

            await asyncio.sleep(2)

        if not bars_list:
            logger.warning(f"  No data for {indicator_name}")
            continue

        df = util.df(bars_list)
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates(subset="date").sort_values("date")
        df = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)]

        for _, row in df.iterrows():
            all_records.append({
                "indicator": indicator_name,
                "date": row["date"].date() if hasattr(row["date"], "date") else row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume", 0)) if row.get("volume") else 0,
            })

        logger.info(f"  {indicator_name}: {len(df)} records")

    if not all_records:
        logger.warning("No macro data downloaded")
        return 0

    return _save_macro_parquet(all_records, data_dir)


def _save_stock_parquet(records: list[dict], data_dir: Path) -> int:
    """Save stock records to stock_daily.parquet with append + dedup."""
    new_df = pd.DataFrame(records)
    new_df["date"] = pd.to_datetime(new_df["date"])

    out_path = data_dir / "stock_daily.parquet"
    data_dir.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logger.info(f"Merging with existing {out_path}")
        old_df = pd.read_parquet(out_path)
        old_df["date"] = pd.to_datetime(old_df["date"])
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
    else:
        combined = new_df

    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)
    combined["date"] = combined["date"].dt.date

    table = pa.Table.from_pandas(combined, preserve_index=False)
    pq.write_table(table, out_path)

    logger.info(f"Saved {len(combined)} total records to {out_path}")
    return len(records)


def _save_macro_parquet(records: list[dict], data_dir: Path) -> int:
    """Save macro records to macro_daily.parquet with append + dedup."""
    new_df = pd.DataFrame(records)
    new_df["date"] = pd.to_datetime(new_df["date"])

    out_path = data_dir / "macro_daily.parquet"
    data_dir.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logger.info(f"Merging with existing {out_path}")
        old_df = pd.read_parquet(out_path)
        old_df["date"] = pd.to_datetime(old_df["date"])
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["indicator", "date"], keep="last")
    else:
        combined = new_df

    combined = combined.sort_values(["indicator", "date"]).reset_index(drop=True)
    combined["date"] = combined["date"].dt.date

    table = pa.Table.from_pandas(combined, preserve_index=False)
    pq.write_table(table, out_path)

    logger.info(f"Saved {len(combined)} total records to {out_path}")
    return len(records)


async def async_main(args):
    """Async entry point — connect to IBKR and download data."""
    from ib_async import IB

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    data_dir = Path(args.data_dir)

    logger.info("=" * 60)
    logger.info("LEAPS Backtest Data Download (IBKR TWS)")
    logger.info("=" * 60)
    logger.info(f"Symbols: {args.symbols}")
    logger.info(f"Period:  {start} ~ {end}")
    logger.info(f"Data dir: {data_dir}")
    logger.info(f"TWS: {args.host}:{args.port} (clientId={args.client_id})")
    logger.info("=" * 60)

    # Connect to TWS
    ib = IB()
    try:
        await ib.connectAsync(args.host, args.port, clientId=args.client_id)
        logger.info("Connected to TWS")
    except Exception as e:
        logger.error(f"Failed to connect to TWS: {e}")
        logger.error("Please ensure:")
        logger.error("  1. TWS is running and logged in")
        logger.error("  2. API is enabled (Edit > Global Configuration > API > Settings)")
        logger.error(f"  3. Port {args.port} is correct (7497=paper, 7496=live)")
        sys.exit(1)

    total_records = 0

    try:
        # Step 1: Stock data
        if not args.skip_stock:
            logger.info("\n[1/2] Downloading stock data via IBKR...")
            stock_count = await download_stock_data_ibkr(ib, args.symbols, start, end, data_dir)
            total_records += stock_count
        else:
            logger.info("\n[1/2] Skipping stock data")

        # Step 2: Macro data
        if not args.skip_macro:
            logger.info("\n[2/2] Downloading macro data via IBKR...")
            macro_count = await download_macro_data_ibkr(ib, start, end, data_dir)
            total_records += macro_count
        else:
            logger.info("\n[2/2] Skipping macro data")

    finally:
        ib.disconnect()
        logger.info("Disconnected from TWS")

    logger.info("\n" + "=" * 60)
    logger.info(f"Download complete: {total_records} total records")
    logger.info("=" * 60)
    logger.info("\nNext: run LEAPS backtest with synthetic option chains:")
    logger.info(
        f'  uv run backtest run -n "LEAPS_10Y" '
        f"-s {start.isoformat()} -e {end.isoformat()} "
        f'-S {" -S ".join(args.symbols)} '
        f"--strategy long_call "
        f"--strategy-version long_leaps_call_sma_timing "
        f"--skip-download"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Download 10-year stock/macro data for LEAPS backtest (IBKR TWS)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help=f"Stock symbols to download (default: {DEFAULT_SYMBOLS})",
    )
    parser.add_argument(
        "--start",
        default=DEFAULT_START,
        help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})",
    )
    parser.add_argument(
        "--end",
        default=DEFAULT_END,
        help=f"End date YYYY-MM-DD (default: {DEFAULT_END})",
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"TWS host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TWS port (default: {DEFAULT_PORT}, live: 7496)",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=DEFAULT_CLIENT_ID,
        help=f"TWS client ID (default: {DEFAULT_CLIENT_ID})",
    )
    parser.add_argument(
        "--skip-stock",
        action="store_true",
        help="Skip stock data download",
    )
    parser.add_argument(
        "--skip-macro",
        action="store_true",
        help="Skip macro data download",
    )
    args = parser.parse_args()

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
