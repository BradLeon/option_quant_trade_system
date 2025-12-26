"""Debug script to inspect IBKR option contract format.

Run with: python tests/debug_ibkr_option_contract.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.models import AccountType, AssetType
from src.data.providers import IBKRProvider


def main():
    print("=" * 80)
    print("IBKR Option Contract Debug")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.REAL) as ibkr:
        # Get positions
        positions = ibkr._ib.positions()

        print(f"\nFound {len(positions)} positions")

        for pos in positions:
            contract = pos.contract

            # Only show options
            if contract.secType != "OPT":
                continue

            print("\n" + "-" * 60)
            print(f"Option Contract Details:")
            print(f"  symbol: {contract.symbol}")
            print(f"  secType: {contract.secType}")
            print(f"  exchange: {contract.exchange}")
            print(f"  primaryExchange: {getattr(contract, 'primaryExchange', 'N/A')}")
            print(f"  currency: {contract.currency}")
            print(f"  conId: {contract.conId}")
            print(f"  lastTradeDateOrContractMonth: {contract.lastTradeDateOrContractMonth}")
            print(f"  strike: {contract.strike}")
            print(f"  right: {contract.right}")
            print(f"  multiplier: {contract.multiplier}")
            print(f"  tradingClass: {getattr(contract, 'tradingClass', 'N/A')}")
            print(f"  localSymbol: {getattr(contract, 'localSymbol', 'N/A')}")

            # Full contract repr
            print(f"\n  Full contract: {contract}")


if __name__ == "__main__":
    main()
