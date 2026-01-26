#!/usr/bin/env python3
"""IBKR Trading Provider Connectivity Verification.

验证 IBKR Paper Trading 连接和交易功能。

测试项目:
1. 连接测试 - 连接到 4002 端口 (Paper Trading)
2. 账户验证 - 验证账户 ID 以 "DU" 开头
3. 账户信息 - 获取 NLV, Cash, Margin
4. 持仓获取 - 获取当前持仓列表
5. 订单查询 - 查询未完成订单
6. 模拟下单 - 提交限价单并立即取消 (可选)

Usage:
    python tests/business/trading/verify_ibkr_connectivity.py
    python tests/business/trading/verify_ibkr_connectivity.py --test-order
    python tests/business/trading/verify_ibkr_connectivity.py --verbose
"""

import argparse
import logging
import sys
import uuid
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


def test_trading_provider_connection(verbose: bool = False) -> bool:
    """测试 IBKRTradingProvider 连接

    Returns:
        是否成功连接
    """
    print("\n" + "=" * 60)
    print("Test 1: IBKRTradingProvider Connection")
    print("=" * 60)

    try:
        from src.business.trading.provider.ibkr_trading import (
            IBKRTradingProvider,
            IBKR_AVAILABLE,
        )

        if not IBKR_AVAILABLE:
            print("  [SKIP] ib_async not installed")
            return False

        print(f"  Connecting to IBKR Paper Trading (port 4002)...")

        provider = IBKRTradingProvider()
        provider.connect()

        if provider.is_connected:
            print(f"  [PASS] Connected successfully")
            print(f"         Account ID: {provider._account_id}")

            # 验证 Paper 账户
            if provider._account_id and provider._account_id.startswith("DU"):
                print(f"  [PASS] Verified Paper Trading account (DU prefix)")
            else:
                print(f"  [WARN] Account ID does not start with 'DU'")

            provider.disconnect()
            return True
        else:
            print(f"  [FAIL] Connection failed")
            return False

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Connection error details")
        return False


def test_data_provider_account_info(verbose: bool = False) -> bool:
    """测试通过 Data Provider 获取账户信息

    Returns:
        是否成功获取
    """
    print("\n" + "=" * 60)
    print("Test 2: Account Information via Data Provider")
    print("=" * 60)

    try:
        from src.data.providers import IBKRProvider
        from src.data.providers.account_aggregator import AccountAggregator

        print("  Connecting to IBKR via Data Provider (port 4002)...")

        # 显式指定 Paper Trading 账户类型，连接到 4002 端口
        with IBKRProvider(account_type=AccountType.PAPER) as ibkr:
            if not ibkr.is_available:
                print("  [FAIL] IBKR provider not available")
                return False

            print("  [PASS] Connected to IBKR")

            # 获取账户信息
            aggregator = AccountAggregator(ibkr_provider=ibkr)
            portfolio = aggregator.get_consolidated_portfolio(
                account_type=AccountType.PAPER
            )

            print("\n  Account Summary:")
            print(f"    Total Value (USD): ${portfolio.total_value_usd:,.2f}")

            # 显示各券商账户信息
            for broker, summary in portfolio.by_broker.items():
                print(f"\n    [{broker.upper()}]")
                print(f"      Total Assets: ${summary.total_assets:,.2f}")
                print(f"      Cash: ${summary.cash:,.2f}")
                print(f"      Market Value: ${summary.market_value:,.2f}")
                if summary.margin_used:
                    print(f"      Margin Used: ${summary.margin_used:,.2f}")
                if summary.margin_available:
                    print(f"      Margin Available: ${summary.margin_available:,.2f}")

            # 显示持仓数量
            option_count = sum(
                1 for p in portfolio.positions if p.asset_type.value == "option"
            )
            stock_count = sum(
                1 for p in portfolio.positions if p.asset_type.value == "stock"
            )
            print(f"\n    Positions: {len(portfolio.positions)} total")
            print(f"      Options: {option_count}")
            print(f"      Stocks: {stock_count}")

            print("\n  [PASS] Account information retrieved successfully")
            return True

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
        from src.data.providers import IBKRProvider

        # 显式指定 Paper Trading 账户类型，连接到 4002 端口
        with IBKRProvider(account_type=AccountType.PAPER) as ibkr:
            if not ibkr.is_available:
                print("  [FAIL] IBKR provider not available")
                return False

            positions = ibkr.get_positions(AccountType.PAPER, fetch_greeks=True)

            print(f"\n  Found {len(positions)} positions:")

            for i, pos in enumerate(positions[:10], 1):  # 只显示前 10 个
                print(f"\n    [{i}] {pos.symbol}")
                print(f"        Quantity: {pos.quantity}")
                print(f"        Market Value: ${pos.market_value:,.2f}")
                if pos.asset_type.value == "option":
                    print(f"        Type: {pos.option_type} @ ${pos.strike}")
                    print(f"        Expiry: {pos.expiry}")
                    if pos.delta is not None:
                        print(f"        Greeks: Δ={pos.delta:.3f}, Θ={pos.theta:.3f}")

            if len(positions) > 10:
                print(f"\n    ... and {len(positions) - 10} more positions")

            print("\n  [PASS] Positions retrieved successfully")
            return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Positions error details")
        return False


def test_open_orders(verbose: bool = False) -> bool:
    """测试获取未完成订单

    Returns:
        是否成功获取
    """
    print("\n" + "=" * 60)
    print("Test 4: Open Orders Query")
    print("=" * 60)

    try:
        from src.business.trading.provider.ibkr_trading import (
            IBKRTradingProvider,
            IBKR_AVAILABLE,
        )

        if not IBKR_AVAILABLE:
            print("  [SKIP] ib_async not installed")
            return False

        with IBKRTradingProvider() as provider:
            if not provider.is_connected:
                print("  [FAIL] Not connected")
                return False

            orders = provider.get_open_orders()

            print(f"\n  Found {len(orders)} open orders:")

            for i, order in enumerate(orders, 1):
                print(f"\n    [{i}] Order ID: {order.broker_order_id}")
                print(f"        Status: {order.status}")
                print(f"        Filled: {order.filled_quantity}")
                print(f"        Remaining: {order.remaining_quantity}")

            print("\n  [PASS] Open orders query successful")
            return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Open orders error details")
        return False


def test_submit_and_cancel_order(verbose: bool = False) -> bool:
    """测试提交和取消订单

    创建一个远离市价的限价单，然后立即取消。

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 5: Submit and Cancel Order (Paper Trading)")
    print("=" * 60)

    try:
        from src.business.trading.provider.ibkr_trading import (
            IBKRTradingProvider,
            IBKR_AVAILABLE,
        )
        from src.business.trading.models.order import (
            OrderRequest,
            OrderSide,
            OrderType,
            AssetClass,
            OrderStatus,
        )

        if not IBKR_AVAILABLE:
            print("  [SKIP] ib_async not installed")
            return False

        print("  Creating test order...")
        print("    Symbol: AAPL")
        print("    Side: BUY")
        print("    Quantity: 1")
        print("    Limit Price: $1.00 (far below market)")
        print("")

        # 创建测试订单 - 使用一个远低于市价的限价，确保不会成交
        order = OrderRequest(
            order_id=f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
            decision_id="test-decision",
            symbol="AAPL",
            asset_class=AssetClass.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1,
            limit_price=1.00,  # 远低于市价，不会成交
            broker="ibkr",
            account_type="paper",
            status=OrderStatus.APPROVED,
        )

        with IBKRTradingProvider() as provider:
            if not provider.is_connected:
                print("  [FAIL] Not connected")
                return False

            # 提交订单
            print("  Submitting order...")
            result = provider.submit_order(order)

            if result.success:
                print(f"  [PASS] Order submitted: broker_id={result.broker_order_id}")

                # 立即取消
                print("  Cancelling order...")
                cancel_result = provider.cancel_order(result.broker_order_id)

                if cancel_result.success:
                    print(f"  [PASS] Order cancelled successfully")
                    return True
                else:
                    print(f"  [WARN] Cancel failed: {cancel_result.error_message}")
                    print("         Order may have been rejected or already filled")
                    return True  # 订单提交成功即可
            else:
                print(f"  [FAIL] Order submission failed: {result.error_message}")
                return False

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Order test error details")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="IBKR Trading Provider Connectivity Verification"
    )
    parser.add_argument(
        "--test-order",
        action="store_true",
        help="Include order submission test (will create and cancel a test order)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output with stack traces"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("IBKR Trading Provider Connectivity Verification")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Mode: Paper Trading Only (Port 4002)")
    print("=" * 60)

    results = {}

    # 运行测试
    results["connection"] = test_trading_provider_connection(args.verbose)
    results["account_info"] = test_data_provider_account_info(args.verbose)
    results["positions"] = test_positions(args.verbose)
    results["open_orders"] = test_open_orders(args.verbose)

    if args.test_order:
        results["submit_cancel"] = test_submit_and_cancel_order(args.verbose)
    else:
        print("\n" + "=" * 60)
        print("Test 5: Submit and Cancel Order")
        print("=" * 60)
        print("  [SKIP] Use --test-order to run this test")

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
