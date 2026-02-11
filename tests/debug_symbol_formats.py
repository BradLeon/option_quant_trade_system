"""
符号格式测试脚本

目的：探索各个 provider (Futu, IBKR, Yahoo) 对不同数据类型的符号格式要求
测试标的：9988.HK (港股), TSLA (美股)

测试项目：
1. 股票行情 (Stock Quote)
2. 期权链 (Option Chain)
3. 期权报价 (Option Quotes)
4. 技术面数据 (Historical Data)
5. 基本面数据 (Fundamentals)
"""

import sys
from pathlib import Path
from datetime import date, timedelta
# 简单的表格打印函数（避免 tabulate 依赖）
def print_table(data, headers):
    """简单的表格打印"""
    col_widths = [max(len(str(row[i])) for row in [headers] + data) for i in range(len(headers))]
    fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("-+-".join("-" * w for w in col_widths))
    for row in data:
        print(fmt.format(*[str(x)[:50] for x in row]))

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_symbol_formats():
    """测试各种符号格式"""

    # 测试标的
    test_symbols = {
        "HK": ["9988.HK", "HK.09988", "9988", "09988"],
        "US": ["TSLA", "US.TSLA", "tsla"],
    }

    results = []

    # =============================================
    # 1. 测试 Futu Provider
    # =============================================
    print("\n" + "="*60)
    print("1. FUTU PROVIDER")
    print("="*60)

    try:
        from src.data.providers.futu_provider import FutuProvider
        futu = FutuProvider()

        # 1.1 股票行情
        print("\n--- 1.1 股票行情 (get_stock_quote) ---")
        for market, symbols in test_symbols.items():
            for sym in symbols:
                try:
                    quote = futu.get_stock_quote(sym)
                    status = f"OK (returned: {quote.symbol})" if quote else "None"
                except Exception as e:
                    status = f"Error: {type(e).__name__}"
                results.append(["Futu", "Stock Quote", market, sym, status])
                print(f"  {sym}: {status}")

        # 1.2 期权链
        print("\n--- 1.2 期权链 (get_option_chain) ---")
        for sym in ["9988.HK", "TSLA"]:
            try:
                chain = futu.get_option_chain(
                    sym,
                    expiry_min_days=7,
                    expiry_max_days=60
                )
                if chain:
                    # 检查返回的 underlying 格式
                    first_put = chain.puts[0] if chain.puts else None
                    underlying_format = first_put.contract.underlying if first_put else "N/A"
                    option_symbol = first_put.contract.symbol if first_put else "N/A"
                    status = f"OK (underlying={underlying_format}, option_sym={option_symbol[:30]}...)"
                else:
                    status = "None"
            except Exception as e:
                status = f"Error: {type(e).__name__}: {e}"
            market = "HK" if "HK" in sym or sym.isdigit() else "US"
            results.append(["Futu", "Option Chain", market, sym, status])
            print(f"  {sym}: {status}")

        # 1.3 期权报价 - 检查从期权链返回的合约能否直接用于报价查询
        print("\n--- 1.3 期权报价 (get_option_quotes_batch) ---")
        for sym in ["9988.HK"]:
            try:
                chain = futu.get_option_chain(sym, expiry_min_days=7, expiry_max_days=30)
                if chain and chain.puts:
                    # 取前 3 个合约测试
                    contracts = [q.contract for q in chain.puts[:3]]
                    print(f"  测试合约: {[c.symbol for c in contracts]}")
                    quotes = futu.get_option_quotes_batch(contracts)
                    status = f"OK ({len(quotes)} quotes)" if quotes else "None (0 quotes)"
                else:
                    status = "No chain data"
            except Exception as e:
                status = f"Error: {type(e).__name__}: {e}"
            results.append(["Futu", "Option Quotes", "HK", sym, status])
            print(f"  {sym}: {status}")

    except Exception as e:
        print(f"Futu Provider 初始化失败: {e}")

    # =============================================
    # 2. 测试 IBKR Provider
    # =============================================
    print("\n" + "="*60)
    print("2. IBKR PROVIDER")
    print("="*60)

    try:
        from src.data.providers.ibkr_provider import IBKRProvider
        ibkr = IBKRProvider()

        # 2.1 股票行情
        print("\n--- 2.1 股票行情 (get_stock_quote) ---")
        for market, symbols in test_symbols.items():
            for sym in symbols:
                try:
                    quote = ibkr.get_stock_quote(sym)
                    status = f"OK (returned: {quote.symbol})" if quote else "None"
                except Exception as e:
                    status = f"Error: {type(e).__name__}"
                results.append(["IBKR", "Stock Quote", market, sym, status])
                print(f"  {sym}: {status}")

        # 2.2 期权链
        print("\n--- 2.2 期权链 (get_option_chain) ---")
        for sym in ["9988.HK", "TSLA"]:
            try:
                chain = ibkr.get_option_chain(
                    sym,
                    expiry_min_days=7,
                    expiry_max_days=60
                )
                if chain:
                    first_put = chain.puts[0] if chain.puts else None
                    underlying_format = first_put.contract.underlying if first_put else "N/A"
                    trading_class = first_put.contract.trading_class if first_put else "N/A"
                    status = f"OK (underlying={underlying_format}, trading_class={trading_class})"
                else:
                    status = "None"
            except Exception as e:
                status = f"Error: {type(e).__name__}: {e}"
            market = "HK" if "HK" in sym else "US"
            results.append(["IBKR", "Option Chain", market, sym, status])
            print(f"  {sym}: {status}")

    except Exception as e:
        print(f"IBKR Provider 初始化失败: {e}")

    # =============================================
    # 3. 测试 Yahoo Provider
    # =============================================
    print("\n" + "="*60)
    print("3. YAHOO PROVIDER")
    print("="*60)

    try:
        from src.data.providers.yahoo_provider import YahooFinanceProvider
        yahoo = YahooFinanceProvider()

        # 3.1 股票行情
        print("\n--- 3.1 股票行情 (get_stock_quote) ---")
        for market, symbols in test_symbols.items():
            for sym in symbols:
                try:
                    quote = yahoo.get_stock_quote(sym)
                    status = f"OK (returned: {quote.symbol})" if quote else "None"
                except Exception as e:
                    status = f"Error: {type(e).__name__}"
                results.append(["Yahoo", "Stock Quote", market, sym, status])
                print(f"  {sym}: {status}")

        # 3.2 历史数据 (技术面)
        print("\n--- 3.2 历史数据 (get_historical_data) ---")
        for sym in ["9988.HK", "TSLA"]:
            try:
                data = yahoo.get_historical_data(
                    sym,
                    start_date=date.today() - timedelta(days=30),
                    end_date=date.today()
                )
                status = f"OK ({len(data)} bars)" if data else "None"
            except Exception as e:
                status = f"Error: {type(e).__name__}"
            market = "HK" if "HK" in sym else "US"
            results.append(["Yahoo", "Historical", market, sym, status])
            print(f"  {sym}: {status}")

    except Exception as e:
        print(f"Yahoo Provider 初始化失败: {e}")

    # =============================================
    # 打印汇总表格
    # =============================================
    print("\n" + "="*60)
    print("汇总表格")
    print("="*60)

    headers = ["Provider", "Data Type", "Market", "Input Symbol", "Result"]
    print_table(results, headers)


def explore_futu_option_chain_details():
    """深入探索 Futu 期权链返回的详细信息"""
    print("\n" + "="*60)
    print("探索 Futu 期权链返回数据结构")
    print("="*60)

    try:
        from src.data.providers.futu_provider import FutuProvider
        futu = FutuProvider()

        from datetime import timedelta
        chain = futu.get_option_chain(
            "9988.HK",
            expiry_start=date.today() + timedelta(days=7),
            expiry_end=date.today() + timedelta(days=30)
        )

        if chain and chain.puts:
            print(f"\nOptionChain.underlying: {chain.underlying}")
            print(f"OptionChain.source: {chain.source}")
            print(f"到期日: {chain.expiry_dates}")

            print("\n前 3 个 PUT 合约:")
            for i, quote in enumerate(chain.puts[:3]):
                c = quote.contract
                print(f"\n  [{i+1}] OptionContract:")
                print(f"      symbol: {c.symbol}")
                print(f"      underlying: {c.underlying}")
                print(f"      option_type: {c.option_type}")
                print(f"      strike_price: {c.strike_price}")
                print(f"      expiry_date: {c.expiry_date}")
                print(f"      lot_size: {c.lot_size}")
                print(f"      trading_class: {c.trading_class}")

                # 尝试从 symbol 解析期权代码
                sym = c.symbol
                if sym.startswith("HK."):
                    # 解析 HK.ALB260129P152500
                    code_part = sym[3:]  # 去掉 HK.
                    print(f"      -> 期权代码部分: {code_part}")
    except Exception as e:
        print(f"Error: {e}")


def explore_ibkr_option_chain_details():
    """深入探索 IBKR 期权链返回的详细信息"""
    print("\n" + "="*60)
    print("探索 IBKR 期权链返回数据结构")
    print("="*60)

    try:
        from src.data.providers.ibkr_provider import IBKRProvider
        ibkr = IBKRProvider()

        chain = ibkr.get_option_chain(
            "9988.HK",
            expiry_start=date.today() + timedelta(days=7),
            expiry_end=date.today() + timedelta(days=30)
        )

        if chain and chain.puts:
            print(f"\nOptionChain.underlying: {chain.underlying}")
            print(f"OptionChain.source: {chain.source}")
            print(f"到期日: {chain.expiry_dates}")

            print("\n前 3 个 PUT 合约:")
            for i, quote in enumerate(chain.puts[:3]):
                c = quote.contract
                print(f"\n  [{i+1}] OptionContract:")
                print(f"      symbol: {c.symbol}")
                print(f"      underlying: {c.underlying}")
                print(f"      option_type: {c.option_type}")
                print(f"      strike_price: {c.strike_price}")
                print(f"      expiry_date: {c.expiry_date}")
                print(f"      lot_size: {c.lot_size}")
                print(f"      trading_class: {c.trading_class}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="符号格式测试")
    parser.add_argument("--detail", action="store_true", help="显示详细的期权链数据结构")
    args = parser.parse_args()

    if args.detail:
        explore_futu_option_chain_details()
        explore_ibkr_option_chain_details()
    else:
        test_symbol_formats()
