#!/usr/bin/env python3
"""Debug script for historical IV data fetching."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ib_async import IB, Stock
import logging

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def test_historical_iv(symbol: str = "TSLA", duration: str = "1 Y"):
    """Test fetching historical IV data with different durations."""
    ib = IB()

    try:
        # Connect
        print(f"\n{'='*60}")
        print(f"Testing historical IV for {symbol} with duration={duration}")
        print(f"{'='*60}")

        ib.connect("127.0.0.1", 7496, clientId=99)
        print("Connected to TWS")

        # Create and qualify contract
        if symbol.endswith(".HK"):
            # Hong Kong stock
            sym = symbol.replace(".HK", "")
            if sym.startswith("0"):
                sym = sym.lstrip("0")
            contract = Stock(sym, "SEHK", "HKD")
        else:
            # US stock - use NASDAQ for better historical IV data availability
            contract = Stock(symbol, "NASDAQ", "USD")

        qualified = ib.qualifyContracts(contract)
        if not qualified:
            print(f"ERROR: Could not qualify contract for {symbol}")
            return

        print(f"Contract qualified: {qualified[0]}")

        # Test different durations
        durations_to_test = ["1 M", "3 M", "6 M", "1 Y"]

        for dur in durations_to_test:
            print(f"\n--- Testing duration: {dur} ---")
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=dur,
                    barSizeSetting="1 day",
                    whatToShow="OPTION_IMPLIED_VOLATILITY",
                    useRTH=True,
                    formatDate=1,
                    timeout=60,  # 60 second timeout
                )

                if bars:
                    print(f"SUCCESS: Got {len(bars)} bars")
                    if len(bars) > 0:
                        print(f"  First bar: {bars[0].date}, IV={bars[0].close:.4f}")
                        print(f"  Last bar: {bars[-1].date}, IV={bars[-1].close:.4f}")

                        # Calculate IV Rank
                        ivs = [b.close for b in bars if b.close == b.close and b.close > 0]
                        if ivs:
                            current_iv = ivs[-1]
                            iv_min = min(ivs)
                            iv_max = max(ivs)
                            iv_rank = (current_iv - iv_min) / (iv_max - iv_min) * 100 if iv_max > iv_min else 0
                            print(f"  Current IV: {current_iv:.4f}, Min: {iv_min:.4f}, Max: {iv_max:.4f}")
                            print(f"  Calculated IV Rank: {iv_rank:.1f}")
                else:
                    print(f"WARNING: No bars returned for duration {dur}")

            except Exception as e:
                print(f"ERROR with duration {dur}: {e}")

            # Small delay between requests to avoid rate limiting
            ib.sleep(1)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ib.disconnect()
        print("\nDisconnected")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "TSLA"
    test_historical_iv(symbol)
