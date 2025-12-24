"""Tests for account models and providers with real data verification.

Run with: python tests/data/test_account.py
"""

from src.data.currency import CurrencyConverter
from src.data.models import AccountType, AssetType
from src.data.providers.account_aggregator import AccountAggregator
import logging

# Enable debug logging for troubleshooting
logging.basicConfig(level=logging.DEBUG)


# =============================================================================
# Ground Truth Data from Screenshots (2024-12-23/24)
# =============================================================================

# Futu 模拟账户 Ground Truth (2024-12-24)
FUTU_PAPER_GROUND_TRUTH = {
    "stocks": {
        "09988": {"qty": 400, "avg_cost": 118.70, "market_value": 58680.00, "pnl": 11200.00},
        "03042": {"qty": 10000, "avg_cost": 12.64, "market_value": 106600.00, "pnl": -19800.00},
        "02318": {"qty": 1000, "avg_cost": 41.494, "market_value": 66000.00, "pnl": 24505.56},
        "03968": {"qty": 1000, "avg_cost": 41.55, "market_value": 51250.00, "pnl": 9700.00},
        "01810": {"qty": 10000, "avg_cost": 35.00, "market_value": 393200.00, "pnl": 43200.00},
        "00700": {"qty": 1000, "avg_cost": 379.30, "market_value": 603500.00, "pnl": 224200.00},
    },
}

# IBKR 模拟账户 Ground Truth (2024-12-24)
IBKR_PAPER_GROUND_TRUTH = {
    "stocks": {
        "700": {"qty": 300, "avg_cost": 602.61, "market_value": 180391.00},
        "9988": {"qty": 500, "avg_cost": 147.58, "market_value": 73183.00},
    },
    "options": {
        "9988_CALL_155_20260129": {"qty": -2, "strike": 155, "expiry": "2026-01-29", "option_type": "call"},
        "700_CALL_640_20260129": {"qty": -3, "strike": 640, "expiry": "2026-01-29", "option_type": "call"},
    },
    "cash": {"HKD": -250089.00, "USD": 1015220.00},
}

# =============================================================================
# Futu 真实账户 Ground Truth (2024-12-23)
# =============================================================================

FUTU_GROUND_TRUTH = {
    "account_id": "2662",
    "total_assets_hkd": 266766.00,
    "cash_hkd": 51064.70,
    "market_value_hkd": 215693.20,
    "stocks": {
        # HK stocks (currency: HKD)
        "09988": {"qty": 1000, "avg_cost": 152.50, "market_value": 147200.00, "pnl": -5300.00},
        "00700": {"qty": 100, "avg_cost": 360.424, "market_value": 60200.00, "pnl": 24157.65},
        # US stocks (currency: USD)
        "NVDA": {"qty": 1, "avg_cost": 115.527, "market_value": 183.20, "pnl": 67.59},
        "TQQQ": {"qty": 10, "avg_cost": 22.521, "market_value": 543.60, "pnl": 318.19},
        "TSLA": {"qty": 1, "avg_cost": 279.613, "market_value": 490.56, "pnl": 210.25},
    },
    "options": {
        # ALB260129C160000 is actually a PUT (沽), not a call - see stock_name "阿里 260129 160.00 沽"
        "ALB260129C160000": {"qty": -1, "strike": 160.0, "expiry": "2026-01-29", "option_type": "call"},
    },
}

IBKR_GROUND_TRUTH = {
    "account_id": "U3198981",
    "total_assets_usd": 205286.14,
    "unrealized_pnl": 31031.62,
    "buying_power": 526379.15,
    "stocks": {
        "700": {"qty": 1200, "avg_cost": 500.00, "market_value": 723000.00, "pnl": 123000.00},
        "9988": {"qty": 600, "avg_cost": 156.69, "market_value": 88320.00, "pnl": -5692.75},
        "GOOG": {"qty": 150, "avg_cost": 278.90, "market_value": 46743.00, "pnl": 4908.75},
        "NVDA": {"qty": 100, "avg_cost": 173.60, "market_value": 18306.00, "pnl": 946.00},
        "TQQQ": {"qty": 200, "avg_cost": 49.62, "market_value": 10866.00, "pnl": 942.88},
        "TSLA": {"qty": 50, "avg_cost": 312.64, "market_value": 24525.00, "pnl": 8893.00},
    },
    "options": {
        "700_PUT_600_20251230": {"qty": -4, "strike": 600, "expiry": "2025-12-30", "option_type": "put"},
        "700_PUT_570_20260129": {"qty": -2, "strike": 570, "expiry": "2026-01-29", "option_type": "put"},
        "700_CALL_660_20260129": {"qty": -3, "strike": 660, "expiry": "2026-01-29", "option_type": "call"},
    },
    "cash": {"HKD": 6999.20, "USD": 11.13},
}


def compare(actual, expected, name, tolerance_pct=5.0):
    """Compare values with tolerance."""
    if expected == 0:
        match = abs(actual) < 1.0
    else:
        diff_pct = abs(actual - expected) / abs(expected) * 100
        match = diff_pct <= tolerance_pct
    status = "✓" if match else "✗"
    print(f"  {status} {name}: actual={actual:,.2f}, expected={expected:,.2f}, diff={actual - expected:+,.2f}")
    return match


def test_futu_real_account():
    """Test Futu real account."""
    from src.data.providers import FutuProvider

    print("\n" + "=" * 80)
    print("FUTU 真实账户测试")
    print("=" * 80)

    with FutuProvider() as futu:
        # Account Summary
        print("\n--- Account Summary ---")
        summary = futu.get_account_summary(AccountType.REAL)
        if summary:
            print(f"Account ID: {summary.account_id}")
            print(f"Total Assets: {summary.total_assets:,.2f}")
            print(f"Cash: {summary.cash:,.2f}")
            print(f"Market Value: {summary.market_value:,.2f}")
            compare(summary.total_assets, FUTU_GROUND_TRUTH["total_assets_hkd"], "Total Assets")
        else:
            print("  ✗ Failed to get account summary")

        # Positions
        print("\n--- Positions ---")
        positions = futu.get_positions(AccountType.REAL)
        stocks = [p for p in positions if p.asset_type != AssetType.OPTION]
        options = [p for p in positions if p.asset_type == AssetType.OPTION]

        print(f"\n[股票 ({len(stocks)})]")
        for pos in stocks:
            delta_str = f"{pos.delta:.2f}" if pos.delta is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, avg_cost={pos.avg_cost:.2f}, "
                  f"market_value={pos.market_value:,.2f}, pnl={pos.unrealized_pnl:,.2f}, delta={delta_str}")

        print(f"\n[期权 ({len(options)})]")
        for pos in options:
            delta_str = f"{pos.delta:.4f}" if pos.delta is not None else "N/A"
            iv_str = f"{pos.iv*100:.2f}%" if pos.iv is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, strike={pos.strike}, "
                  f"expiry={pos.expiry}, type={pos.option_type}, delta={delta_str}, iv={iv_str}")

        print("\n--- Ground Truth 股票对比 ---")
        for symbol, expected in FUTU_GROUND_TRUTH["stocks"].items():
            # Match symbol by stripping leading zeros and market prefixes
            actual = next((p for p in stocks if symbol.lstrip("0") in p.symbol.replace("HK.", "").replace("US.", "").replace(".HK", "").lstrip("0")), None)
            if actual:
                compare(actual.quantity, expected["qty"], f"{symbol} qty")
                compare(actual.avg_cost, expected["avg_cost"], f"{symbol} avg_cost")
                compare(actual.market_value, expected["market_value"], f"{symbol} market_value")
                compare(actual.unrealized_pnl, expected["pnl"], f"{symbol} pnl")
            else:
                print(f"  ? {symbol}: NOT FOUND")

        print("\n--- Ground Truth 期权对比 ---")
        for symbol, expected in FUTU_GROUND_TRUTH["options"].items():
            print(f"  Expected: qty={expected['qty']}, strike={expected['strike']}, type={expected['option_type']}, expiry={expected['expiry']}")
            # Match by symbol containing the option symbol
            actual = next((p for p in options if symbol in p.symbol), None)
            if actual:
                print(f"  Actual: {actual.symbol}, qty={actual.quantity}, strike={actual.strike}, type={actual.option_type}, expiry={actual.expiry}")
                compare(actual.quantity, expected["qty"], f"{symbol} qty")
                if actual.strike:
                    compare(actual.strike, expected["strike"], f"{symbol} strike")
            else:
                print(f"  ? {symbol}: NOT FOUND in options list")

        # Cash
        print("\n--- Cash Balances ---")
        cash = futu.get_cash_balances(AccountType.REAL)
        for c in cash:
            print(f"  {c.currency}: balance={c.balance:,.2f}")
        print("\n--- Ground Truth Cash 对比 ---")
        compare(cash[0].balance if cash else 0, FUTU_GROUND_TRUTH["cash_hkd"], "Cash HKD")


def test_ibkr_live_account():
    """Test IBKR live account."""
    from src.data.providers import IBKRProvider

    print("\n" + "=" * 80)
    print("IBKR Live 账户测试")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.REAL) as ibkr:
        # Account Summary
        print("\n--- Account Summary ---")
        summary = ibkr.get_account_summary()
        if summary:
            print(f"Account ID: {summary.account_id}")
            print(f"Port: {ibkr._port}")
            print(f"Total Assets: {summary.total_assets:,.2f}")
            print(f"Unrealized P&L: {summary.unrealized_pnl:,.2f}")
            print(f"Buying Power: {summary.buying_power:,.2f}")
            compare(summary.total_assets, IBKR_GROUND_TRUTH["total_assets_usd"], "Total Assets")
            compare(summary.unrealized_pnl, IBKR_GROUND_TRUTH["unrealized_pnl"], "Unrealized P&L")
        else:
            print("  ✗ Failed to get account summary")

        # Positions
        print("\n--- Positions ---")
        positions = ibkr.get_positions()
        stocks = [p for p in positions if p.asset_type != AssetType.OPTION]
        options = [p for p in positions if p.asset_type == AssetType.OPTION]

        print(f"\n[股票 ({len(stocks)})]")
        for pos in stocks:
            delta_str = f"{pos.delta:.2f}" if pos.delta is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, avg_cost={pos.avg_cost:.2f}, "
                  f"market_value={pos.market_value:,.2f}, pnl={pos.unrealized_pnl:,.2f}, {pos.currency}, delta={delta_str}")

        print(f"\n[期权 ({len(options)})]")
        for pos in options:
            delta_str = f"{pos.delta:.4f}" if pos.delta is not None else "N/A"
            iv_str = f"{pos.iv*100:.2f}%" if pos.iv is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, strike={pos.strike}, "
                  f"expiry={pos.expiry}, type={pos.option_type}, delta={delta_str}, iv={iv_str}")

        print("\n--- Ground Truth 股票对比 ---")
        for symbol, expected in IBKR_GROUND_TRUTH["stocks"].items():
            actual = next((p for p in stocks if symbol.upper() in p.symbol.upper()), None)
            if actual:
                compare(actual.quantity, expected["qty"], f"{symbol} qty")
                compare(actual.avg_cost, expected["avg_cost"], f"{symbol} avg_cost")
                compare(actual.market_value, expected["market_value"], f"{symbol} market_value")
                compare(actual.unrealized_pnl, expected["pnl"], f"{symbol} pnl")
            else:
                print(f"  ? {symbol}: NOT FOUND")

        print("\n--- Ground Truth 期权对比 ---")
        for symbol, expected in IBKR_GROUND_TRUTH["options"].items():
            print(f"  Expected: qty={expected['qty']}, strike={expected['strike']}, type={expected['option_type']}")
            actual = next((p for p in options if str(expected['strike']) in str(p.strike)), None)
            if actual:
                print(f"  Actual: {actual.symbol}, qty={actual.quantity}, strike={actual.strike}")

        # Cash
        print("\n--- Cash Balances ---")
        cash = ibkr.get_cash_balances()
        for c in cash:
            print(f"  {c.currency}: balance={c.balance:,.2f}")
        print("\n--- Ground Truth Cash 对比 ---")
        for currency, expected in IBKR_GROUND_TRUTH["cash"].items():
            actual = next((c.balance for c in cash if c.currency == currency), 0)
            compare(actual, expected, f"{currency}")


def test_currency_conversion():
    """Test currency conversion."""
    print("\n" + "=" * 80)
    print("Currency Conversion 测试")
    print("=" * 80)

    converter = CurrencyConverter()
    print("\n--- 默认汇率 ---")
    for currency, rate in converter.get_all_rates().items():
        print(f"  {currency}: {rate}")

    print("\n--- 转换测试 ---")
    print(f"  10,000 HKD -> {converter.convert(10000, 'HKD', 'USD'):,.2f} USD")
    print(f"  1,000 USD -> {converter.convert(1000, 'USD', 'HKD'):,.2f} HKD")


def test_consolidated_portfolio():
    """Test consolidated portfolio from both brokers."""
    from src.data.providers import IBKRProvider, FutuProvider

    print("\n" + "=" * 80)
    print("合并持仓测试 (Futu + IBKR)")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.REAL) as ibkr, FutuProvider() as futu:
        # AccountAggregator now fetches Greeks directly:
        # - IBKR options: Greeks fetched via IBKR's get_positions()
        # - Futu options: Greeks fetched via IBKR's fetch_greeks_for_hk_option()
        aggregator = AccountAggregator(ibkr, futu)
        portfolio = aggregator.get_consolidated_portfolio(
            account_type=AccountType.REAL,
            base_currency="USD",
        )

        print(f"\n--- 汇总数据 ---")
        print(f"Total Value (USD): ${portfolio.total_value_usd:,.2f}")
        print(f"Total Unrealized P&L (USD): ${portfolio.total_unrealized_pnl_usd:,.2f}")

        print(f"\n--- 持仓汇总 ({len(portfolio.positions)} positions) ---")
        for pos in portfolio.positions:
            print(f"  [{pos.broker}] {pos.symbol}: qty={pos.quantity}, "
                  f"market_value={pos.market_value:,.2f} {pos.currency}")

        print(f"\n--- 现金汇总 ---")
        for c in portfolio.cash_balances:
            print(f"  [{c.broker}] {c.currency}: {c.balance:,.2f}")

        print(f"\n--- 各券商汇总 ---")
        for broker, summary in portfolio.by_broker.items():
            print(f"  {broker}: total={summary.total_assets:,.2f}, pnl={summary.unrealized_pnl:,.2f}")

        # Verify calculation
        print("\n--- 计算逻辑验证 ---")
        manual_total = sum(aggregator._converter.convert(p.market_value, p.currency, "USD") for p in portfolio.positions)
        manual_total += sum(aggregator._converter.convert(c.balance, c.currency, "USD") for c in portfolio.cash_balances)
        print(f"  Reported: ${portfolio.total_value_usd:,.2f}")
        print(f"  Calculated: ${manual_total:,.2f}")
        print(f"  ✓ Match!" if abs(portfolio.total_value_usd - manual_total) < 1 else "  ✗ Mismatch!")

        # Portfolio Greeks
        print("\n--- 组合 Greeks ---")
        stocks = [p for p in portfolio.positions if p.asset_type != AssetType.OPTION]
        options = [p for p in portfolio.positions if p.asset_type == AssetType.OPTION]

        print("\n[股票 Greeks]")
        for p in stocks:
            delta = p.delta or 0
            pos_delta = p.quantity * delta
            print(f"  [{p.broker}] {p.symbol}: qty={p.quantity}, delta={delta}, pos_delta={pos_delta:,.2f}")

        print("\n[期权 Greeks]")
        for p in options:
            delta = p.delta
            multiplier = int(p.contract_multiplier or 1)
            pos_delta = p.quantity * multiplier * (delta or 0)
            iv_str = f"{p.iv*100:.2f}%" if p.iv else "N/A"
            print(f"  [{p.broker}] {p.symbol}: qty={p.quantity}, multiplier={multiplier}, "
                  f"delta={delta}, gamma={p.gamma}, theta={p.theta}, vega={p.vega}, iv={iv_str}, pos_delta={pos_delta:,.2f}")

        # Stock delta: qty * delta (delta=1 for long, -1 for short)
        stock_delta = sum(p.quantity * (p.delta or 0) for p in stocks)
        # Option delta: qty * multiplier * delta
        option_delta = sum(
            p.quantity * int(p.contract_multiplier or 1) * (p.delta or 0)
            for p in options
        )
        total_delta = stock_delta + option_delta

        print(f"\n  Stock Delta Total: {stock_delta:,.2f}")
        print(f"  Option Delta Total: {option_delta:,.2f}")
        print(f"  Portfolio Delta: {total_delta:,.2f}")


def test_exposure_by_market():
    """Test exposure by market."""
    from src.data.providers import IBKRProvider, FutuProvider

    print("\n" + "=" * 80)
    print("按市场计算敞口")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.REAL) as ibkr, FutuProvider() as futu:
        aggregator = AccountAggregator(ibkr, futu)
        exposure = aggregator.get_total_exposure_by_market(AccountType.REAL, "USD")

        print("\n--- 市场敞口 (USD) ---")
        total = 0
        for market, value in exposure.items():
            print(f"  {market}: ${value:,.2f}")
            total += value
        print(f"\n  Total: ${total:,.2f}")


def test_ibkr_paper_account():
    """Test IBKR paper trading account."""
    from src.data.providers import IBKRProvider

    print("\n" + "=" * 80)
    print("IBKR 模拟账户测试 (Paper Trading)")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.PAPER) as ibkr:
        # Account Summary
        print("\n--- Account Summary ---")
        summary = ibkr.get_account_summary()
        if summary:
            print(f"Account ID: {summary.account_id}")
            print(f"Account Type: {summary.account_type.value}")
            print(f"Port: {ibkr._port}")
            print(f"Total Assets: {summary.total_assets:,.2f}")
            print(f"Cash: {summary.cash:,.2f}")
            print(f"Market Value: {summary.market_value:,.2f}")
            print(f"Unrealized P&L: {summary.unrealized_pnl:,.2f}")
            if summary.buying_power:
                print(f"Buying Power: {summary.buying_power:,.2f}")
        else:
            print("  ✗ Failed to get account summary")

        # Positions
        print("\n--- Positions ---")
        positions = ibkr.get_positions()
        stocks = [p for p in positions if p.asset_type != AssetType.OPTION]
        options = [p for p in positions if p.asset_type == AssetType.OPTION]

        print(f"\n[股票 ({len(stocks)})]")
        for pos in stocks:
            delta_str = f"{pos.delta:.2f}" if pos.delta is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, avg_cost={pos.avg_cost:.2f}, "
                  f"market_value={pos.market_value:,.2f}, pnl={pos.unrealized_pnl:,.2f}, {pos.currency}, delta={delta_str}")

        print(f"\n[期权 ({len(options)})]")
        for pos in options:
            delta_str = f"{pos.delta:.4f}" if pos.delta is not None else "N/A"
            iv_str = f"{pos.iv*100:.2f}%" if pos.iv is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, strike={pos.strike}, "
                  f"expiry={pos.expiry}, type={pos.option_type}, delta={delta_str}, iv={iv_str}")

        # Cash
        print("\n--- Cash Balances ---")
        cash = ibkr.get_cash_balances()
        for c in cash:
            print(f"  {c.currency}: balance={c.balance:,.2f}")

        # Ground Truth comparison
        print("\n--- Ground Truth 股票对比 ---")
        for symbol, expected in IBKR_PAPER_GROUND_TRUTH["stocks"].items():
            actual = next((p for p in stocks if symbol.upper() in p.symbol.upper()), None)
            if actual:
                compare(actual.quantity, expected["qty"], f"{symbol} qty")
                compare(actual.avg_cost, expected["avg_cost"], f"{symbol} avg_cost")
                compare(actual.market_value, expected["market_value"], f"{symbol} market_value")
            else:
                print(f"  ? {symbol}: NOT FOUND")

        print("\n--- Ground Truth 期权对比 ---")
        for symbol, expected in IBKR_PAPER_GROUND_TRUTH["options"].items():
            print(f"  Expected: qty={expected['qty']}, strike={expected['strike']}, type={expected['option_type']}")
            actual = next((p for p in options if str(expected['strike']) in str(p.strike)), None)
            if actual:
                print(f"  Actual: {actual.symbol}, qty={actual.quantity}, strike={actual.strike}, type={actual.option_type}")
                compare(actual.quantity, expected["qty"], f"{symbol} qty")

        print("\n--- Ground Truth Cash 对比 ---")
        for currency, expected in IBKR_PAPER_GROUND_TRUTH["cash"].items():
            actual = next((c.balance for c in cash if c.currency == currency), 0)
            compare(actual, expected, f"{currency}")

        # Portfolio Greeks Summary
        if options:
            print("\n--- 期权 Greeks 汇总 ---")
            total_delta = sum(
                p.quantity * int(p.contract_multiplier or 1) * (p.delta or 0)
                for p in options
            )
            total_gamma = sum(
                p.quantity * int(p.contract_multiplier or 1) * (p.gamma or 0)
                for p in options
            )
            total_theta = sum(
                p.quantity * int(p.contract_multiplier or 1) * (p.theta or 0)
                for p in options
            )
            total_vega = sum(
                p.quantity * int(p.contract_multiplier or 1) * (p.vega or 0)
                for p in options
            )
            print(f"  Total Delta: {total_delta:,.2f}")
            print(f"  Total Gamma: {total_gamma:,.4f}")
            print(f"  Total Theta: {total_theta:,.2f}")
            print(f"  Total Vega: {total_vega:,.2f}")


def test_consolidated_portfolio_paper():
    """Test consolidated portfolio from both brokers (paper accounts)."""
    from src.data.providers import IBKRProvider, FutuProvider

    print("\n" + "=" * 80)
    print("合并持仓测试 - 模拟账户 (Futu + IBKR Paper)")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.PAPER) as ibkr, \
         FutuProvider(account_type=AccountType.PAPER) as futu:
        # AccountAggregator now fetches Greeks directly:
        # - IBKR options: Greeks fetched via IBKR's get_positions()
        # - Futu options: Greeks fetched via IBKR's fetch_greeks_for_hk_option()
        aggregator = AccountAggregator(ibkr, futu)
        portfolio = aggregator.get_consolidated_portfolio(
            account_type=AccountType.PAPER,
            base_currency="USD",
        )

        print(f"\n--- 汇总数据 ---")
        print(f"Total Value (USD): ${portfolio.total_value_usd:,.2f}")
        print(f"Total Unrealized P&L (USD): ${portfolio.total_unrealized_pnl_usd:,.2f}")

        print(f"\n--- 持仓汇总 ({len(portfolio.positions)} positions) ---")
        for pos in portfolio.positions:
            print(f"  [{pos.broker}] {pos.symbol}: qty={pos.quantity}, "
                  f"market_value={pos.market_value:,.2f} {pos.currency}")

        print(f"\n--- 现金汇总 ---")
        for c in portfolio.cash_balances:
            print(f"  [{c.broker}] {c.currency}: {c.balance:,.2f}")

        print(f"\n--- 各券商汇总 ---")
        for broker, summary in portfolio.by_broker.items():
            print(f"  {broker}: total={summary.total_assets:,.2f}, pnl={summary.unrealized_pnl:,.2f}")

        # Verify calculation
        print("\n--- 计算逻辑验证 ---")
        manual_total = sum(aggregator._converter.convert(p.market_value, p.currency, "USD") for p in portfolio.positions)
        manual_total += sum(aggregator._converter.convert(c.balance, c.currency, "USD") for c in portfolio.cash_balances)
        print(f"  Reported: ${portfolio.total_value_usd:,.2f}")
        print(f"  Calculated: ${manual_total:,.2f}")
        print(f"  ✓ Match!" if abs(portfolio.total_value_usd - manual_total) < 1 else "  ✗ Mismatch!")

        # Portfolio Greeks
        print("\n--- 组合 Greeks ---")
        stocks = [p for p in portfolio.positions if p.asset_type != AssetType.OPTION]
        options = [p for p in portfolio.positions if p.asset_type == AssetType.OPTION]

        print(f"\n[股票 ({len(stocks)})]")
        for p in stocks:
            delta = p.delta or 0
            pos_delta = p.quantity * delta
            print(f"  [{p.broker}] {p.symbol}: qty={p.quantity}, delta={delta}, pos_delta={pos_delta:,.2f}")

        print(f"\n[期权 ({len(options)})]")
        for p in options:
            delta = p.delta
            multiplier = int(p.contract_multiplier or 1)
            pos_delta = p.quantity * multiplier * (delta or 0)
            iv_str = f"{p.iv*100:.2f}%" if p.iv else "N/A"
            print(f"  [{p.broker}] {p.symbol}: qty={p.quantity}, multiplier={multiplier}, "
                  f"delta={delta}, gamma={p.gamma}, theta={p.theta}, vega={p.vega}, iv={iv_str}, pos_delta={pos_delta:,.2f}")

        # Stock delta: qty * delta (delta=1 for long, -1 for short)
        stock_delta = sum(p.quantity * (p.delta or 0) for p in stocks)
        # Option delta: qty * multiplier * delta
        option_delta = sum(
            p.quantity * int(p.contract_multiplier or 1) * (p.delta or 0)
            for p in options
        )
        total_delta = stock_delta + option_delta

        print(f"\n  Stock Delta Total: {stock_delta:,.2f}")
        print(f"  Option Delta Total: {option_delta:,.2f}")
        print(f"  Portfolio Delta: {total_delta:,.2f}")


def test_exposure_by_market_paper():
    """Test exposure by market (paper accounts)."""
    from src.data.providers import IBKRProvider, FutuProvider

    print("\n" + "=" * 80)
    print("按市场计算敞口 - 模拟账户")
    print("=" * 80)

    with IBKRProvider(account_type=AccountType.PAPER) as ibkr, \
         FutuProvider(account_type=AccountType.PAPER) as futu:
        aggregator = AccountAggregator(ibkr, futu)
        exposure = aggregator.get_total_exposure_by_market(AccountType.PAPER, "USD")

        print("\n--- 市场敞口 (USD) ---")
        total = 0
        for market, value in exposure.items():
            print(f"  {market}: ${value:,.2f}")
            total += value
        print(f"\n  Total: ${total:,.2f}")


def test_futu_paper_account():
    """Test Futu paper trading account."""
    from src.data.providers import FutuProvider

    print("\n" + "=" * 80)
    print("FUTU 模拟账户测试 (Paper Trading)")
    print("=" * 80)

    with FutuProvider(account_type=AccountType.PAPER) as futu:
        # Account Summary
        print("\n--- Account Summary ---")
        summary = futu.get_account_summary(AccountType.PAPER)
        if summary:
            print(f"Account ID: {summary.account_id}")
            print(f"Account Type: {summary.account_type.value}")
            print(f"Total Assets: {summary.total_assets:,.2f}")
            print(f"Cash: {summary.cash:,.2f}")
            print(f"Market Value: {summary.market_value:,.2f}")
            print(f"Unrealized P&L: {summary.unrealized_pnl:,.2f}")
        else:
            print("  ✗ Failed to get account summary")

        # Positions
        print("\n--- Positions ---")
        positions = futu.get_positions(AccountType.PAPER)
        stocks = [p for p in positions if p.asset_type != AssetType.OPTION]
        options = [p for p in positions if p.asset_type == AssetType.OPTION]

        print(f"\n[股票 ({len(stocks)})]")
        for pos in stocks:
            delta_str = f"{pos.delta:.2f}" if pos.delta is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, avg_cost={pos.avg_cost:.2f}, "
                  f"market_value={pos.market_value:,.2f}, pnl={pos.unrealized_pnl:,.2f}, {pos.currency}, delta={delta_str}")

        print(f"\n[期权 ({len(options)})]")
        for pos in options:
            delta_str = f"{pos.delta:.4f}" if pos.delta is not None else "N/A"
            iv_str = f"{pos.iv*100:.2f}%" if pos.iv is not None else "N/A"
            print(f"  {pos.symbol}: qty={pos.quantity}, strike={pos.strike}, "
                  f"expiry={pos.expiry}, type={pos.option_type}, delta={delta_str}, iv={iv_str}")

        # Ground Truth comparison
        print("\n--- Ground Truth 股票对比 ---")
        for symbol, expected in FUTU_PAPER_GROUND_TRUTH["stocks"].items():
            actual = next((p for p in stocks if symbol.lstrip("0") in p.symbol.replace("HK.", "").replace(".HK", "").lstrip("0")), None)
            if actual:
                compare(actual.quantity, expected["qty"], f"{symbol} qty")
                compare(actual.avg_cost, expected["avg_cost"], f"{symbol} avg_cost")
                compare(actual.market_value, expected["market_value"], f"{symbol} market_value")
                compare(actual.unrealized_pnl, expected["pnl"], f"{symbol} pnl")
            else:
                print(f"  ? {symbol}: NOT FOUND")

        # Cash
        print("\n--- Cash Balances ---")
        cash = futu.get_cash_balances(AccountType.PAPER)
        for c in cash:
            print(f"  {c.currency}: balance={c.balance:,.2f}")


if __name__ == "__main__":
    print("=" * 80)
    print("Account Integration Test Suite")
    print("=" * 80)
    '''
    try:
        test_futu_real_account()
    except Exception as e:
        print(f"\n✗ Futu test failed: {e}")

    try:
        test_ibkr_live_account()
    except Exception as e:
        print(f"\n✗ IBKR test failed: {e}")

    try:
        test_currency_conversion()
    except Exception as e:
        print(f"\n✗ Currency test failed: {e}")
    '''
    try:
        test_consolidated_portfolio()
    except Exception as e:
        print(f"\n✗ Consolidated portfolio test failed: {e}")

    try:
        test_exposure_by_market()
    except Exception as e:
        print(f"\n✗ Exposure test failed: {e}")

    print("\n" + "=" * 80)
    print("All tests completed!")
    print("=" * 80)
