#!/usr/bin/env python3
"""
IBKR Fundamental Data API 探索脚本 (使用 ib_fundamental 库)

使用 ib_fundamental 库简化 XML 解析，直接获取 DataFrame 格式的数据。

安装:
    pip install ib-fundamental

Usage:
    python tests/verification/verify_ibkr_fundamental_v2.py
    python tests/verification/verify_ibkr_fundamental_v2.py --symbol MSFT
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_with_ib_fundamental(symbol: str = "AAPL") -> dict:
    """使用 ib_fundamental 库测试

    Returns:
        测试结果字典
    """
    results = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "library": "ib_fundamental",
        "data": {},
    }

    try:
        from ib_async import IB
        from ib_fundamental import CompanyFinancials
    except ImportError as e:
        logger.error(f"Required packages not installed: {e}")
        logger.info("Install with: pip install ib_async ib-fundamental")
        results["error"] = str(e)
        return results

    ib = IB()

    try:
        port = int(os.getenv("IBKR_PORT", "7497"))
        logger.info(f"Connecting to IBKR on port {port}...")

        await ib.connectAsync("127.0.0.1", port, clientId=98)
        logger.info("Connected to IBKR")

        # 使用 ib_fundamental 获取数据
        logger.info(f"\nFetching fundamental data for {symbol}...")
        company = CompanyFinancials(ib=ib, symbol=symbol)

        # 等待数据加载
        await asyncio.sleep(3)

        print("\n" + "=" * 60)
        print(f"Fundamental Data for {symbol}")
        print("=" * 60)

        # 1. 公司信息
        print("\n--- Company Information ---")
        try:
            info = company.company_information
            if info is not None and not info.empty:
                print(info.to_string())
                results["data"]["company_info"] = True
            else:
                print("No company information available")
                results["data"]["company_info"] = False
        except Exception as e:
            print(f"Error: {e}")
            results["data"]["company_info"] = False

        # 2. 年度利润表
        print("\n--- Income Statement (Annual) ---")
        try:
            income_annual = company.income_annual
            if income_annual is not None and not income_annual.empty:
                print(f"Shape: {income_annual.shape}")
                print(f"Columns (Years): {list(income_annual.columns)[:10]}")
                print(f"Rows (Items): {list(income_annual.index)[:10]}")

                # 检查有多少年的数据
                years = [c for c in income_annual.columns if str(c).isdigit() or (isinstance(c, str) and c.startswith("20"))]
                results["data"]["income_annual"] = {
                    "available": True,
                    "years": len(years),
                    "items": len(income_annual.index),
                }
                print(f"\n✅ {len(years)} years of annual income data available")

                # 显示样本数据
                print("\nSample data (first 5 rows, first 3 columns):")
                print(income_annual.iloc[:5, :3].to_string())
            else:
                print("No annual income data")
                results["data"]["income_annual"] = {"available": False}
        except Exception as e:
            print(f"Error: {e}")
            results["data"]["income_annual"] = {"available": False, "error": str(e)}

        # 3. 季度利润表
        print("\n--- Income Statement (Quarterly) ---")
        try:
            income_quarterly = company.income_quarterly
            if income_quarterly is not None and not income_quarterly.empty:
                print(f"Shape: {income_quarterly.shape}")
                print(f"Columns (Quarters): {list(income_quarterly.columns)[:8]}")

                quarters = len([c for c in income_quarterly.columns if c not in ["statement_type"]])
                results["data"]["income_quarterly"] = {
                    "available": True,
                    "quarters": quarters,
                }
                print(f"\n✅ {quarters} quarters of income data available")
            else:
                print("No quarterly income data")
                results["data"]["income_quarterly"] = {"available": False}
        except Exception as e:
            print(f"Error: {e}")
            results["data"]["income_quarterly"] = {"available": False, "error": str(e)}

        # 4. 资产负债表
        print("\n--- Balance Sheet (Annual) ---")
        try:
            balance_annual = company.balance_annual
            if balance_annual is not None and not balance_annual.empty:
                print(f"Shape: {balance_annual.shape}")
                results["data"]["balance_annual"] = {
                    "available": True,
                    "years": balance_annual.shape[1],
                }
                print(f"✅ Balance sheet data available")
            else:
                print("No balance sheet data")
                results["data"]["balance_annual"] = {"available": False}
        except Exception as e:
            print(f"Error: {e}")
            results["data"]["balance_annual"] = {"available": False, "error": str(e)}

        # 5. 现金流量表
        print("\n--- Cash Flow (Annual) ---")
        try:
            cashflow_annual = company.cashflow_annual
            if cashflow_annual is not None and not cashflow_annual.empty:
                print(f"Shape: {cashflow_annual.shape}")
                results["data"]["cashflow_annual"] = {
                    "available": True,
                    "years": cashflow_annual.shape[1],
                }
                print(f"✅ Cash flow data available")
            else:
                print("No cash flow data")
                results["data"]["cashflow_annual"] = {"available": False}
        except Exception as e:
            print(f"Error: {e}")
            results["data"]["cashflow_annual"] = {"available": False, "error": str(e)}

        # 6. EPS 数据
        print("\n--- EPS Data ---")
        try:
            # TTM EPS
            eps_ttm = company.eps_ttm
            if eps_ttm is not None and not eps_ttm.empty:
                print("EPS TTM:")
                print(eps_ttm.to_string())
                results["data"]["eps_ttm"] = {"available": True}
            else:
                results["data"]["eps_ttm"] = {"available": False}

            # Quarterly EPS
            eps_q = company.eps_q
            if eps_q is not None and not eps_q.empty:
                print("\nEPS Quarterly:")
                print(eps_q.head(10).to_string())
                results["data"]["eps_quarterly"] = {
                    "available": True,
                    "records": len(eps_q),
                }
                print(f"\n✅ {len(eps_q)} quarterly EPS records available")
            else:
                results["data"]["eps_quarterly"] = {"available": False}
        except Exception as e:
            print(f"Error getting EPS: {e}")
            results["data"]["eps"] = {"error": str(e)}

        # 7. 财务比率
        print("\n--- Financial Ratios ---")
        try:
            # 尝试获取各种比率
            ratios_available = []

            # ROE
            if hasattr(company, "roe") and company.roe is not None:
                ratios_available.append("ROE")

            # 其他比率通过 data 属性访问
            if hasattr(company, "data"):
                data = company.data
                if hasattr(data, "revenue_ttm") and data.revenue_ttm:
                    ratios_available.append("Revenue TTM")
                if hasattr(data, "dividend_per_share") and data.dividend_per_share:
                    ratios_available.append("Dividend Per Share")

            print(f"Available ratios: {ratios_available}")
            results["data"]["ratios"] = ratios_available
        except Exception as e:
            print(f"Error getting ratios: {e}")

    except Exception as e:
        logger.error(f"Error: {e}")
        results["error"] = str(e)

    finally:
        if ib.isConnected():
            ib.disconnect()
            logger.info("Disconnected from IBKR")

    return results


def print_conclusion(results: dict) -> None:
    """打印结论"""
    print("\n" + "=" * 60)
    print("Summary & Conclusion")
    print("=" * 60)

    if "error" in results:
        print(f"\n❌ Error: {results['error']}")
        return

    data = results.get("data", {})

    # 检查历史数据可用性
    has_historical_income = data.get("income_annual", {}).get("available", False)
    has_historical_quarterly = data.get("income_quarterly", {}).get("available", False)
    has_eps = data.get("eps_quarterly", {}).get("available", False)

    print(f"\nSymbol: {results['symbol']}")
    print("\nData Availability:")
    print("-" * 40)

    for key, value in data.items():
        if isinstance(value, dict):
            status = "✅" if value.get("available") else "❌"
            details = ""
            if value.get("years"):
                details = f" ({value['years']} years)"
            elif value.get("quarters"):
                details = f" ({value['quarters']} quarters)"
            elif value.get("records"):
                details = f" ({value['records']} records)"
            print(f"  {status} {key}{details}")
        elif isinstance(value, list):
            print(f"  📊 {key}: {value}")
        else:
            status = "✅" if value else "❌"
            print(f"  {status} {key}")

    print("\n" + "-" * 40)
    print("Conclusion for Backtesting:")
    print("-" * 40)

    if has_historical_income:
        years = data.get("income_annual", {}).get("years", 0)
        print(f"✅ 历史年度财务报表: {years} 年")
        print("   → 可用于计算历史 PE、PB、PS 等估值指标")

    if has_historical_quarterly:
        quarters = data.get("income_quarterly", {}).get("quarters", 0)
        print(f"✅ 历史季度财务报表: {quarters} 个季度")
        print("   → 可用于更细粒度的基本面回测")

    if has_eps:
        records = data.get("eps_quarterly", {}).get("records", 0)
        print(f"✅ 历史 EPS 数据: {records} 条记录")
        print("   → 可直接用于 PE 计算")

    if has_historical_income or has_historical_quarterly:
        print("\n🎉 IBKR API 支持历史基本面数据，可用于回测！")
        print("\n建议:")
        print("  1. 创建 IBKRFundamentalProvider 封装 ib_fundamental")
        print("  2. 下载历史数据并存储为 Parquet")
        print("  3. 在 DuckDBProvider 中实现 get_fundamental()")
    else:
        print("\n⚠️  无法获取历史基本面数据")
        print("   可能原因:")
        print("   - 市场数据订阅不足")
        print("   - 该股票无基本面数据")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Test IBKR Fundamental Data using ib_fundamental library"
    )
    parser.add_argument(
        "--symbol", "-s",
        default="AAPL",
        help="Stock symbol to test (default: AAPL)",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("IBKR Fundamental Data Test (ib_fundamental)")
    print("=" * 60)
    print(f"\nSymbol: {args.symbol}")
    print("Library: ib_fundamental")
    print("\nNote: Requires TWS or IB Gateway running on localhost")
    print("=" * 60)

    results = asyncio.run(test_with_ib_fundamental(symbol=args.symbol))
    print_conclusion(results)

    return 0 if not results.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
