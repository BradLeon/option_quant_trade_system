#!/usr/bin/env python3
"""Futu Data Provider Connectivity Verification.

验证 Futu 数据提供者连接功能。

注意: 模拟账户交易只通过 IBKR 进行，Futu 仅用于数据获取。

测试项目:
1. 连接测试 - 连接到 OpenD (默认端口 11111)
2. 账户信息 - 获取账户资产 (仅查询)
3. 持仓获取 - 获取当前持仓列表
4. 行情获取 - 获取股票报价

Usage:
    python tests/business/trading/verify_futu_connectivity.py
    python tests/business/trading/verify_futu_connectivity.py --verbose
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data.models.account import AccountType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_data_provider_connection(verbose: bool = False) -> bool:
    """测试 FutuProvider (Data) 连接

    Returns:
        是否成功连接
    """
    print("\n" + "=" * 60)
    print("Test 1: FutuProvider (Data) Connection")
    print("=" * 60)

    try:
        from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE

        if not FUTU_AVAILABLE:
            print("  [SKIP] futu-api not installed")
            return False

        print(f"  Connecting to Futu OpenD (Quote Context)...")

        with FutuProvider() as futu:
            if futu.is_available:
                print(f"  [PASS] Connected to Futu Quote Context")
                print(f"         Provider: {futu.name}")
                return True
            else:
                print(f"  [FAIL] Provider not available")
                return False

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Data provider connection error")
        return False


def test_account_info(verbose: bool = False) -> bool:
    """测试获取账户信息 (仅查询，不用于交易)

    Returns:
        是否成功获取
    """
    print("\n" + "=" * 60)
    print("Test 2: Account Information (Read-Only)")
    print("=" * 60)

    try:
        from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE

        if not FUTU_AVAILABLE:
            print("  [SKIP] futu-api not installed")
            return False

        with FutuProvider() as futu:
            if not futu.is_available:
                print("  [FAIL] Futu provider not available")
                return False

            # 获取账户摘要
            summary = futu.get_account_summary(account_type=AccountType.PAPER)

            if summary:
                print("\n  Account Summary (Read-Only):")
                print(f"    Broker: {summary.broker}")
                print(f"    Account ID: {summary.account_id}")
                print(f"    Total Assets: ${summary.total_assets:,.2f}")
                print(f"    Cash: ${summary.cash:,.2f}")
                print(f"    Market Value: ${summary.market_value:,.2f}")
                print(f"    Unrealized P&L: ${summary.unrealized_pnl:,.2f}")

                if summary.margin_used:
                    print(f"    Margin Used: ${summary.margin_used:,.2f}")
                if summary.margin_available:
                    print(f"    Margin Available: ${summary.margin_available:,.2f}")

                print("\n  [PASS] Account information retrieved successfully")
                return True
            else:
                print("  [FAIL] Could not retrieve account summary")
                return False

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Account info error details")
        return False


def test_positions(verbose: bool = False) -> bool:
    """测试获取持仓

    Returns:
        是否成功获取
    """
    print("\n" + "=" * 60)
    print("Test 3: Positions Retrieval")
    print("=" * 60)

    try:
        from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE

        if not FUTU_AVAILABLE:
            print("  [SKIP] futu-api not installed")
            return False

        with FutuProvider() as futu:
            if not futu.is_available:
                print("  [FAIL] Futu provider not available")
                return False

            positions = futu.get_positions(
                account_type=AccountType.PAPER,
                fetch_greeks=True,
            )

            print(f"\n  Found {len(positions)} positions:")

            for i, pos in enumerate(positions[:10], 1):  # 只显示前 10 个
                print(f"\n    [{i}] {pos.symbol}")
                print(f"        Quantity: {pos.quantity}")
                print(f"        Market Value: ${pos.market_value:,.2f}")
                print(f"        Asset Type: {pos.asset_type.value}")

                if pos.asset_type.value == "option":
                    print(f"        Underlying: {pos.underlying}")
                    print(f"        Type: {pos.option_type} @ ${pos.strike}")
                    print(f"        Expiry: {pos.expiry}")
                    if pos.delta is not None:
                        print(f"        Greeks: Δ={pos.delta:.3f}", end="")
                        if pos.theta:
                            print(f", Θ={pos.theta:.3f}", end="")
                        if pos.iv:
                            print(f", IV={pos.iv:.1%}", end="")
                        print()

            if len(positions) > 10:
                print(f"\n    ... and {len(positions) - 10} more positions")

            print("\n  [PASS] Positions retrieved successfully")
            return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Positions error details")
        return False


def test_stock_quote(verbose: bool = False) -> bool:
    """测试获取股票行情

    Returns:
        是否成功获取
    """
    print("\n" + "=" * 60)
    print("Test 4: Stock Quote Retrieval")
    print("=" * 60)

    try:
        from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE

        if not FUTU_AVAILABLE:
            print("  [SKIP] futu-api not installed")
            return False

        with FutuProvider() as futu:
            if not futu.is_available:
                print("  [FAIL] Futu provider not available")
                return False

            # 测试港股报价 (港股交易时段更稳定)
            test_symbols = ["HK.00700", "HK.09988"]
            success_count = 0

            for symbol in test_symbols:
                print(f"\n  Fetching quote for {symbol}...")
                quote = futu.get_stock_quote(symbol)

                if quote and quote.close:
                    print(f"    [PASS] {symbol}")
                    print(f"           Price: ${quote.close:,.2f}")
                    if quote.change_percent:
                        print(f"           Change: {quote.change_percent:+.2f}%")
                    if quote.volume:
                        print(f"           Volume: {quote.volume:,}")
                    success_count += 1
                else:
                    print(f"    [WARN] Could not fetch quote for {symbol}")

            if success_count > 0:
                print("\n  [PASS] Stock quote retrieval successful")
                return True
            else:
                print("\n  [FAIL] No quotes retrieved")
                return False

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Stock quote error details")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Futu Data Provider Connectivity Verification"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output with stack traces"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("Futu Data Provider Connectivity Verification")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Note: Paper Trading uses IBKR only. Futu is for data access.")
    print("=" * 60)

    results = {}

    # 运行测试
    results["data_connection"] = test_data_provider_connection(args.verbose)
    results["account_info"] = test_account_info(args.verbose)
    results["positions"] = test_positions(args.verbose)
    results["stock_quote"] = test_stock_quote(args.verbose)

    # 汇总结果
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {test_name}")

    print(f"\n  Total: {passed}/{total} tests passed")
    print("=" * 60 + "\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
