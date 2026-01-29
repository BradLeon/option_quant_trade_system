#!/usr/bin/env python3
"""AccountStateAnalyzer Verification.

验证 AccountStateAnalyzer 使用真实账户数据的功能。

注意: 模拟账户交易只通过 IBKR 进行。

测试项目:
1. 从真实数据构建 AccountState - 从 AccountAggregator 获取数据转换
2. can_open_position 验证 - 使用真实账户状态测试开仓判断
3. 可用资金计算 - 验证 get_available_capital_for_opening
4. 账户健康摘要 - 验证 get_account_health_summary
5. 标的暴露检查 - 验证 check_underlying_exposure

Usage:
    python tests/business/trading/verify_account_analyzer.py
    python tests/business/trading/verify_account_analyzer.py --verbose
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data.models.account import AccountType, AssetType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_account_state_from_portfolio(portfolio, broker: str = "ibkr"):
    """从 ConsolidatedPortfolio 构建 AccountState

    Args:
        portfolio: AccountAggregator 返回的 ConsolidatedPortfolio
        broker: 目标券商

    Returns:
        AccountState 实例
    """
    from src.business.trading.models.decision import AccountState

    summary = portfolio.by_broker.get(broker)
    if not summary:
        raise ValueError(f"Broker {broker} not found in portfolio")

    # 计算核心风控指标 (使用 getattr 兼容不同字段名)
    nlv = getattr(summary, 'total_assets', 0) or 0
    cash = getattr(summary, 'cash', 0) or 0
    maint_margin = getattr(summary, 'margin_used', 0) or 0
    avail_margin = getattr(summary, 'margin_available', 0) or 0

    # Margin Utilization = Maint Margin / NLV
    margin_utilization = maint_margin / nlv if nlv > 0 else 0

    # Cash Ratio = Cash / NLV
    cash_ratio = cash / nlv if nlv > 0 else 0

    # Gross Leverage 需要计算总名义价值
    # 简化处理: 使用 market_value / NLV 作为近似
    market_value = summary.market_value or 0
    gross_leverage = abs(market_value) / nlv if nlv > 0 else 0

    # 统计持仓数量
    option_count = sum(
        1 for p in portfolio.positions
        if p.asset_type == AssetType.OPTION and p.broker == broker
    )
    stock_count = sum(
        1 for p in portfolio.positions
        if p.asset_type == AssetType.STOCK and p.broker == broker
    )
    total_count = option_count + stock_count

    # 计算标的暴露
    exposure_by_underlying: dict[str, float] = {}
    for pos in portfolio.positions:
        if pos.broker != broker:
            continue
        underlying = pos.underlying or pos.symbol
        notional = abs(pos.market_value)
        exposure_by_underlying[underlying] = (
            exposure_by_underlying.get(underlying, 0) + notional
        )

    return AccountState(
        broker=broker,
        account_type="paper",
        total_equity=nlv,
        cash_balance=cash,
        available_margin=avail_margin,
        used_margin=maint_margin,
        margin_utilization=margin_utilization,
        cash_ratio=cash_ratio,
        gross_leverage=gross_leverage,
        total_position_count=total_count,
        option_position_count=option_count,
        stock_position_count=stock_count,
        exposure_by_underlying=exposure_by_underlying,
        timestamp=datetime.now(),
    )


def test_build_account_state(verbose: bool = False) -> tuple[bool, any]:
    """测试从真实数据构建 AccountState

    Args:
        verbose: 是否详细输出

    Returns:
        (是否成功, AccountState 或 None)
    """
    print("\n" + "=" * 60)
    print("Test 1: Build AccountState from IBKR Data")
    print("=" * 60)

    try:
        from src.data.providers import IBKRProvider
        from src.data.providers.account_aggregator import AccountAggregator

        print(f"  Connecting to IBKR Paper Trading (port 4002)...")
        ibkr = IBKRProvider(account_type=AccountType.PAPER)
        ibkr.connect()

        if not ibkr.is_available:
            print("  [FAIL] IBKR not available")
            return False, None

        try:
            # 获取组合数据
            print(f"  Fetching portfolio data...")
            aggregator = AccountAggregator(ibkr_provider=ibkr)
            portfolio = aggregator.get_consolidated_portfolio(
                account_type=AccountType.PAPER
            )

            # 构建 AccountState
            print(f"  Building AccountState...")
            account_state = build_account_state_from_portfolio(portfolio, "ibkr")

            print(f"\n  AccountState built successfully:")
            print(f"    Broker: {account_state.broker}")
            print(f"    NLV: ${account_state.total_equity:,.2f}")
            print(f"    Cash: ${account_state.cash_balance:,.2f}")
            print(f"    Used Margin: ${account_state.used_margin:,.2f}")
            print(f"    Available Margin: ${account_state.available_margin:,.2f}")
            print(f"\n  Risk Metrics (Four Pillars):")
            print(f"    Margin Utilization: {account_state.margin_utilization:.1%}")
            print(f"    Cash Ratio: {account_state.cash_ratio:.1%}")
            print(f"    Gross Leverage: {account_state.gross_leverage:.2f}x")
            print(f"\n  Position Counts:")
            print(f"    Total: {account_state.total_position_count}")
            print(f"    Options: {account_state.option_position_count}")
            print(f"    Stocks: {account_state.stock_position_count}")

            if verbose and account_state.exposure_by_underlying:
                print(f"\n  Exposure by Underlying:")
                for underlying, exposure in sorted(
                    account_state.exposure_by_underlying.items(),
                    key=lambda x: -x[1]
                )[:5]:
                    print(f"    {underlying}: ${exposure:,.2f}")

            print("\n  [PASS] AccountState built successfully")
            return True, account_state

        finally:
            ibkr.disconnect()

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Build AccountState error")
        return False, None


def test_can_open_position(account_state, verbose: bool = False) -> bool:
    """测试 can_open_position

    Args:
        account_state: AccountState 实例
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 2: can_open_position Validation")
    print("=" * 60)

    if account_state is None:
        print("  [SKIP] No AccountState available")
        return False

    try:
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()

        # 测试不带保证金要求
        print("\n  Testing without required margin...")
        can_open, reasons = analyzer.can_open_position(account_state)

        if can_open:
            print("  [PASS] Can open new positions")
        else:
            print("  [INFO] Cannot open new positions:")
            for reason in reasons:
                print(f"         - {reason}")

        # 测试带保证金要求 (模拟需要 10% NLV 的保证金)
        required_margin = account_state.total_equity * 0.10
        print(f"\n  Testing with required margin: ${required_margin:,.2f}")
        can_open_with_margin, reasons_with_margin = analyzer.can_open_position(
            account_state, required_margin=required_margin
        )

        if can_open_with_margin:
            print("  [PASS] Can open with projected margin")
        else:
            print("  [INFO] Cannot open with projected margin:")
            for reason in reasons_with_margin:
                print(f"         - {reason}")

        print("\n  [PASS] can_open_position validation completed")
        return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("can_open_position error")
        return False


def test_available_capital(account_state, verbose: bool = False) -> bool:
    """测试 get_available_capital_for_opening

    Args:
        account_state: AccountState 实例
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 3: Available Capital Calculation")
    print("=" * 60)

    if account_state is None:
        print("  [SKIP] No AccountState available")
        return False

    try:
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        available = analyzer.get_available_capital_for_opening(account_state)

        print(f"\n  Account Status:")
        print(f"    NLV: ${account_state.total_equity:,.2f}")
        print(f"    Cash: ${account_state.cash_balance:,.2f}")
        print(f"    Used Margin: ${account_state.used_margin:,.2f}")

        print(f"\n  Available Capital for Opening: ${available:,.2f}")

        if available > 0:
            pct = available / account_state.total_equity * 100
            print(f"    ({pct:.1f}% of NLV)")
        else:
            print("    (No capital available for new positions)")

        print("\n  [PASS] Available capital calculation completed")
        return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Available capital error")
        return False


def test_account_health_summary(account_state, verbose: bool = False) -> bool:
    """测试 get_account_health_summary

    Args:
        account_state: AccountState 实例
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 4: Account Health Summary")
    print("=" * 60)

    if account_state is None:
        print("  [SKIP] No AccountState available")
        return False

    try:
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        summary = analyzer.get_account_health_summary(account_state)

        print("\n  Health Summary:")
        print(f"    Can Open Position: {summary['can_open_position']}")

        if summary['rejection_reasons']:
            print(f"    Rejection Reasons:")
            for reason in summary['rejection_reasons']:
                print(f"      - {reason}")

        print(f"\n  Current Metrics:")
        print(f"    Margin Utilization: {summary['margin_utilization']:.1%}")
        print(f"    Cash Ratio: {summary['cash_ratio']:.1%}")
        print(f"    Gross Leverage: {summary['gross_leverage']:.2f}x")
        print(f"    Option Position Count: {summary['option_position_count']}")

        print(f"\n  Limits (Config):")
        limits = summary['limits']
        print(f"    Max Margin Utilization: {limits['max_margin_utilization']:.1%}")
        print(f"    Min Cash Ratio: {limits['min_cash_ratio']:.1%}")
        print(f"    Max Gross Leverage: {limits['max_gross_leverage']:.1f}x")
        print(f"    Max Option Positions: {limits['max_option_positions']}")

        print(f"\n  Available Capital: ${summary['available_capital']:,.2f}")

        print("\n  [PASS] Account health summary completed")
        return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Account health summary error")
        return False


def test_underlying_exposure(account_state, verbose: bool = False) -> bool:
    """测试 check_underlying_exposure

    Args:
        account_state: AccountState 实例
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 5: Underlying Exposure Check")
    print("=" * 60)

    if account_state is None:
        print("  [SKIP] No AccountState available")
        return False

    try:
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()

        # 获取当前暴露最大的标的
        if account_state.exposure_by_underlying:
            top_underlying = max(
                account_state.exposure_by_underlying.items(),
                key=lambda x: x[1]
            )
            underlying, current_exposure = top_underlying

            print(f"\n  Testing exposure for: {underlying}")
            print(f"    Current Exposure: ${current_exposure:,.2f}")

            # 测试不增加暴露
            is_ok, reason = analyzer.check_underlying_exposure(
                account_state, underlying, additional_notional=0
            )
            print(f"\n  Without additional notional:")
            print(f"    Within Limit: {is_ok}")
            if reason:
                print(f"    Reason: {reason}")

            # 测试增加 5% NLV 的暴露
            additional = account_state.total_equity * 0.05
            is_ok2, reason2 = analyzer.check_underlying_exposure(
                account_state, underlying, additional_notional=additional
            )
            print(f"\n  With additional ${additional:,.2f}:")
            print(f"    Within Limit: {is_ok2}")
            if reason2:
                print(f"    Reason: {reason2}")

        else:
            print("  No current exposures to test")
            # 测试新标的
            is_ok, reason = analyzer.check_underlying_exposure(
                account_state, "AAPL", additional_notional=10000
            )
            print(f"\n  Test new underlying (AAPL, $10,000):")
            print(f"    Within Limit: {is_ok}")
            if reason:
                print(f"    Reason: {reason}")

        print("\n  [PASS] Underlying exposure check completed")
        return True

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Underlying exposure error")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="AccountStateAnalyzer Verification (IBKR Only)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output with stack traces"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("AccountStateAnalyzer Verification")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Broker: IBKR (Paper Trading Only)")
    print("=" * 60)

    results = {}

    # Test 1: Build AccountState
    success, account_state = test_build_account_state(args.verbose)
    results["build_account_state"] = success

    # Test 2: can_open_position
    results["can_open_position"] = test_can_open_position(account_state, args.verbose)

    # Test 3: Available Capital
    results["available_capital"] = test_available_capital(account_state, args.verbose)

    # Test 4: Health Summary
    results["health_summary"] = test_account_health_summary(account_state, args.verbose)

    # Test 5: Underlying Exposure
    results["underlying_exposure"] = test_underlying_exposure(account_state, args.verbose)

    # Summary
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
