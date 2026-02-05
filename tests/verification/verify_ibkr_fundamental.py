#!/usr/bin/env python3
"""
IBKR Fundamental Data API 探索脚本

测试 reqFundamentalData 返回的数据，确认是否包含历史基本面数据。

Report Types:
- ReportsFinStatements: 财务报表 (资产负债表、利润表、现金流量表)
- ReportsFinSummary: 财务摘要
- ReportSnapshot: 公司财务概览
- ReportsOwnership: 股权结构
- ReportRatios: 财务比率 (可能不可用)
- RESC: 分析师预测 (可能不可用)
- CalendarReport: 公司日历 (可能不可用)

Usage:
    # 需要先启动 TWS 或 IB Gateway
    python tests/verification/verify_ibkr_fundamental.py

    # 指定股票
    python tests/verification/verify_ibkr_fundamental.py --symbol AAPL

    # 保存 XML 原始数据
    python tests/verification/verify_ibkr_fundamental.py --symbol MSFT --save-xml
"""

import argparse
import asyncio
import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Report types to test
REPORT_TYPES = [
    "ReportsFinStatements",  # Financial statements (most important)
    "ReportsFinSummary",     # Financial summary
    "ReportSnapshot",        # Company snapshot
    "ReportsOwnership",      # Ownership data
    # These may not work:
    # "ReportRatios",        # Often returns error 430
    # "RESC",                # Analyst estimates - often fails
    # "CalendarReport",      # Calendar - often fails
]


def parse_financial_statements(xml_str: str) -> dict:
    """解析财务报表 XML

    提取关键财务数据，检查是否有历史数据。

    Returns:
        dict with parsed data summary
    """
    result = {
        "has_historical_data": False,
        "annual_periods": [],
        "quarterly_periods": [],
        "income_items": [],
        "balance_items": [],
        "cashflow_items": [],
        "sample_data": {},
    }

    try:
        root = ET.fromstring(xml_str)

        # 查找财务报表部分
        # IBKR XML 结构: FinancialStatements > AnnualPeriods/InterimPeriods > FiscalPeriod

        # 查找年度报表
        annual = root.find(".//AnnualPeriods")
        if annual is not None:
            for period in annual.findall("FiscalPeriod"):
                fiscal_year = period.get("FiscalYear")
                end_date = period.get("EndDate")
                if fiscal_year:
                    result["annual_periods"].append({
                        "fiscal_year": fiscal_year,
                        "end_date": end_date,
                    })

        # 查找季度报表
        interim = root.find(".//InterimPeriods")
        if interim is not None:
            for period in interim.findall("FiscalPeriod"):
                fiscal_year = period.get("FiscalYear")
                period_type = period.get("Type")  # Q1, Q2, Q3, Q4
                end_date = period.get("EndDate")
                if fiscal_year:
                    result["quarterly_periods"].append({
                        "fiscal_year": fiscal_year,
                        "period": period_type,
                        "end_date": end_date,
                    })

        # 检查是否有历史数据
        if len(result["annual_periods"]) > 1 or len(result["quarterly_periods"]) > 1:
            result["has_historical_data"] = True

        # 提取利润表项目示例
        income = root.find(".//IncomeStatement")
        if income is not None:
            for item in income[:10]:  # 取前10个项目
                result["income_items"].append(item.tag)

        # 提取资产负债表项目示例
        balance = root.find(".//BalanceSheet")
        if balance is not None:
            for item in balance[:10]:
                result["balance_items"].append(item.tag)

        # 提取现金流量表项目示例
        cashflow = root.find(".//CashFlowStatement")
        if cashflow is not None:
            for item in cashflow[:10]:
                result["cashflow_items"].append(item.tag)

        # 尝试提取一些具体数值 (EPS, Revenue 等)
        # 查找 EPS
        eps_elements = root.findall(".//EPS") or root.findall(".//EarningsPerShare")
        if eps_elements:
            result["sample_data"]["eps_elements"] = len(eps_elements)

        # 查找 Revenue
        rev_elements = root.findall(".//Revenue") or root.findall(".//TotalRevenue")
        if rev_elements:
            result["sample_data"]["revenue_elements"] = len(rev_elements)

    except ET.ParseError as e:
        result["parse_error"] = str(e)

    return result


def parse_report_snapshot(xml_str: str) -> dict:
    """解析 ReportSnapshot XML

    提取公司快照数据，检查是否有 PE、EPS 等指标。
    """
    result = {
        "company_name": None,
        "ratios": {},
        "per_share_data": {},
        "valuation": {},
    }

    try:
        root = ET.fromstring(xml_str)

        # 公司名称
        company = root.find(".//CoIDs/CoID[@Type='CompanyName']")
        if company is not None:
            result["company_name"] = company.text

        # 财务比率
        ratios = root.find(".//Ratios")
        if ratios is not None:
            for group in ratios:
                group_name = group.tag
                for ratio in group:
                    ratio_name = ratio.tag
                    ratio_value = ratio.text
                    result["ratios"][f"{group_name}.{ratio_name}"] = ratio_value

        # Per Share Data
        per_share = root.find(".//PerShareData") or root.find(".//perShareDataList")
        if per_share is not None:
            for item in per_share:
                result["per_share_data"][item.tag] = item.text

        # Valuation
        valuation = root.find(".//Valuation")
        if valuation is not None:
            for item in valuation:
                result["valuation"][item.tag] = item.text

    except ET.ParseError as e:
        result["parse_error"] = str(e)

    return result


async def test_fundamental_data(
    symbol: str = "AAPL",
    save_xml: bool = False,
    output_dir: str = "data/ibkr_fundamental",
) -> dict:
    """测试 IBKR reqFundamentalData API

    Args:
        symbol: 股票代码
        save_xml: 是否保存原始 XML
        output_dir: XML 输出目录

    Returns:
        测试结果字典
    """
    try:
        from ib_async import IB, Stock
    except ImportError:
        logger.error("ib_async not installed. Run: pip install ib_async")
        return {"error": "ib_async not installed"}

    results = {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "reports": {},
    }

    # 连接 IBKR
    ib = IB()

    try:
        # 尝试连接 (Paper: 7497, Live: 7496)
        port = int(os.getenv("IBKR_PORT", "7497"))
        logger.info(f"Connecting to IBKR on port {port}...")

        await ib.connectAsync("127.0.0.1", port, clientId=99)
        logger.info("Connected to IBKR")

        # 创建合约
        contract = Stock(symbol, "SMART", "USD")

        # 确认合约
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            logger.error(f"Failed to qualify contract for {symbol}")
            results["error"] = "Contract not found"
            return results

        contract = qualified[0]
        logger.info(f"Contract qualified: {contract}")

        # 创建输出目录
        if save_xml:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

        # 测试每种报告类型
        for report_type in REPORT_TYPES:
            logger.info(f"\n{'='*60}")
            logger.info(f"Testing report type: {report_type}")
            logger.info("=" * 60)

            try:
                # 请求基本面数据
                xml_data = await ib.reqFundamentalDataAsync(
                    contract, reportType=report_type
                )

                if xml_data:
                    logger.info(f"Received {len(xml_data)} bytes of XML data")

                    # 保存 XML
                    if save_xml:
                        xml_file = output_path / f"{symbol}_{report_type}.xml"
                        with open(xml_file, "w", encoding="utf-8") as f:
                            f.write(xml_data)
                        logger.info(f"Saved to {xml_file}")

                    # 解析数据
                    if report_type == "ReportsFinStatements":
                        parsed = parse_financial_statements(xml_data)
                    elif report_type == "ReportSnapshot":
                        parsed = parse_report_snapshot(xml_data)
                    else:
                        # 基本解析 - 只获取根元素和子元素数量
                        try:
                            root = ET.fromstring(xml_data)
                            parsed = {
                                "root_tag": root.tag,
                                "child_count": len(root),
                                "children": [child.tag for child in root[:10]],
                            }
                        except ET.ParseError as e:
                            parsed = {"parse_error": str(e)}

                    results["reports"][report_type] = {
                        "success": True,
                        "data_size": len(xml_data),
                        "parsed": parsed,
                    }

                    # 打印摘要
                    print(f"\n{report_type} Summary:")
                    print("-" * 40)
                    if report_type == "ReportsFinStatements":
                        print(f"  Has historical data: {parsed.get('has_historical_data')}")
                        print(f"  Annual periods: {len(parsed.get('annual_periods', []))}")
                        print(f"  Quarterly periods: {len(parsed.get('quarterly_periods', []))}")
                        if parsed.get("annual_periods"):
                            years = [p['fiscal_year'] for p in parsed['annual_periods'][:5]]
                            print(f"  Years: {years}")
                        if parsed.get("quarterly_periods"):
                            quarters = [f"{p['fiscal_year']}-{p['period']}" for p in parsed['quarterly_periods'][:4]]
                            print(f"  Recent quarters: {quarters}")
                    elif report_type == "ReportSnapshot":
                        print(f"  Company: {parsed.get('company_name')}")
                        print(f"  Ratios count: {len(parsed.get('ratios', {}))}")
                        print(f"  Per share items: {len(parsed.get('per_share_data', {}))}")
                        # 显示一些关键比率
                        for key, value in list(parsed.get("ratios", {}).items())[:5]:
                            print(f"    {key}: {value}")
                    else:
                        print(f"  Root: {parsed.get('root_tag')}")
                        print(f"  Children: {parsed.get('children', [])[:5]}")

                else:
                    logger.warning(f"No data returned for {report_type}")
                    results["reports"][report_type] = {
                        "success": False,
                        "error": "No data returned",
                    }

            except Exception as e:
                logger.error(f"Error fetching {report_type}: {e}")
                results["reports"][report_type] = {
                    "success": False,
                    "error": str(e),
                }

            # 等待一下避免请求过快
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Connection error: {e}")
        results["error"] = str(e)

    finally:
        if ib.isConnected():
            ib.disconnect()
            logger.info("Disconnected from IBKR")

    return results


def print_summary(results: dict) -> None:
    """打印测试结果摘要"""
    print("\n" + "=" * 60)
    print("IBKR Fundamental Data Test Summary")
    print("=" * 60)

    print(f"\nSymbol: {results.get('symbol')}")
    print(f"Timestamp: {results.get('timestamp')}")

    if "error" in results:
        print(f"\nError: {results['error']}")
        return

    print("\nReport Results:")
    print("-" * 40)

    for report_type, data in results.get("reports", {}).items():
        status = "✅" if data.get("success") else "❌"
        size = data.get("data_size", 0)
        error = data.get("error", "")

        print(f"  {status} {report_type}: ", end="")
        if data.get("success"):
            print(f"{size:,} bytes")

            # 特别标注财务报表的历史数据
            if report_type == "ReportsFinStatements":
                parsed = data.get("parsed", {})
                if parsed.get("has_historical_data"):
                    annual = len(parsed.get("annual_periods", []))
                    quarterly = len(parsed.get("quarterly_periods", []))
                    print(f"       → 历史数据: {annual} 年度 + {quarterly} 季度报表 ✅")
        else:
            print(f"Failed - {error}")

    # 结论
    print("\n" + "=" * 60)
    print("结论:")
    print("-" * 40)

    fin_statements = results.get("reports", {}).get("ReportsFinStatements", {})
    if fin_statements.get("success"):
        parsed = fin_statements.get("parsed", {})
        if parsed.get("has_historical_data"):
            print("✅ IBKR API 可以返回历史财务报表数据！")
            print("   - 年度报表: 可用于计算历史 PE、EPS 等")
            print("   - 季度报表: 可用于更细粒度的回测")
        else:
            print("⚠️  只有当期数据，无历史数据")
    else:
        print("❌ 无法获取财务报表数据")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Test IBKR reqFundamentalData API"
    )
    parser.add_argument(
        "--symbol", "-s",
        default="AAPL",
        help="Stock symbol to test (default: AAPL)",
    )
    parser.add_argument(
        "--save-xml",
        action="store_true",
        help="Save raw XML responses",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="data/ibkr_fundamental",
        help="Directory to save XML files",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("IBKR Fundamental Data API Test")
    print("=" * 60)
    print(f"\nSymbol: {args.symbol}")
    print(f"Save XML: {args.save_xml}")
    if args.save_xml:
        print(f"Output dir: {args.output_dir}")
    print("\nNote: Requires TWS or IB Gateway running on localhost")
    print("=" * 60 + "\n")

    # 运行测试
    results = asyncio.run(test_fundamental_data(
        symbol=args.symbol,
        save_xml=args.save_xml,
        output_dir=args.output_dir,
    ))

    # 打印摘要
    print_summary(results)

    return 0 if not results.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
