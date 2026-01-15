"""Test paper trading accounts for IBKR and Futu.

Run with: python tests/data/test_paper_account.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from test_account import (
    test_ibkr_paper_account,
    test_futu_paper_account,
    test_currency_conversion,
    test_consolidated_portfolio_paper,
    test_exposure_by_market_paper,
)

if __name__ == "__main__":
    print("=" * 80)
    print("Paper Account Test Suite")
    print("=" * 80)

    # 1. Currency conversion test (not account-specific)
    try:
        test_currency_conversion()
    except Exception as e:
        print(f"\n✗ Currency conversion test failed: {e}")
        import traceback
        traceback.print_exc()

    # 2. Individual broker tests
    try:
        test_futu_paper_account()
    except Exception as e:
        print(f"\n✗ Futu Paper test failed: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_ibkr_paper_account()
    except Exception as e:
        print(f"\n✗ IBKR Paper test failed: {e}")
        import traceback
        traceback.print_exc()

    # 3. Consolidated portfolio test (requires both brokers)
    try:
        test_consolidated_portfolio_paper()
    except Exception as e:
        print(f"\n✗ Consolidated portfolio (paper) test failed: {e}")
        import traceback
        traceback.print_exc()

    # 4. Exposure by market test
    try:
        test_exposure_by_market_paper()
    except Exception as e:
        print(f"\n✗ Exposure by market (paper) test failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("Paper account tests completed!")
    print("=" * 80)
