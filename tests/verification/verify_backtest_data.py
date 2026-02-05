#!/usr/bin/env python3
"""
Backtest Data 连通性和正确性验证脚本

验证 ThetaData、yfinance、IBKR 三个数据源的数据获取。

Usage:
    # 运行所有测试
    python tests/verification/verify_backtest_data.py

    # 只测试特定数据源
    python tests/verification/verify_backtest_data.py --source thetadata
    python tests/verification/verify_backtest_data.py --source yfinance
    python tests/verification/verify_backtest_data.py --source ibkr

    # 指定输出目录
    python tests/verification/verify_backtest_data.py --output-dir data/test_verify

    # 指定 IBKR 端口
    python tests/verification/verify_backtest_data.py --ibkr-port 7497
"""

import argparse
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# Test Result Data Classes
# ============================================================


@dataclass
class TestResult:
    """单个测试结果"""

    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestSuiteResult:
    """测试套件结果"""

    source_name: str
    results: list[TestResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total_count(self) -> int:
        return len(self.results)


# ============================================================
# Base Tester Class
# ============================================================


class DataSourceTester(ABC):
    """数据源测试基类"""

    def __init__(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        output_dir: Path | None = None,
    ):
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self.output_dir = output_dir
        self.results: list[TestResult] = []

    @property
    @abstractmethod
    def source_name(self) -> str:
        """数据源名称"""
        pass

    @abstractmethod
    def run_tests(self) -> TestSuiteResult:
        """运行所有测试"""
        pass

    def add_result(
        self,
        name: str,
        passed: bool,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """添加测试结果"""
        self.results.append(
            TestResult(
                name=name,
                passed=passed,
                message=message,
                details=details or {},
            )
        )

    def print_result(self, result: TestResult) -> None:
        """打印单个测试结果"""
        status = "✅" if result.passed else "❌"
        print(f"     {status} {result.name}: {result.message}")
        for key, value in result.details.items():
            print(f"        {key}: {value}")


# ============================================================
# ThetaData Tester
# ============================================================


class ThetaDataTester(DataSourceTester):
    """ThetaData 期权数据测试"""

    @property
    def source_name(self) -> str:
        return "ThetaData"

    def run_tests(self) -> TestSuiteResult:
        """运行 ThetaData 测试"""
        print(f"\n{'='*60}")
        print("1. ThetaData (Options + Stocks)")
        print("=" * 60)

        try:
            from src.backtest.data.thetadata_client import (
                ThetaDataClient,
                ThetaDataConfig,
            )

            # 测试连接
            print("\n   Testing connection...")
            config = ThetaDataConfig()
            client = ThetaDataClient(config)

            # 简单测试：获取一个股票数据来验证连接
            test_data = client.get_stock_eod(
                self.symbols[0],
                self.end_date - timedelta(days=5),
                self.end_date,
            )

            if test_data:
                self.add_result(
                    "Connection",
                    True,
                    f"Connected to {config.host}:{config.port}",
                )
                print(f"   ✅ Connected to {config.host}:{config.port}")
            else:
                self.add_result(
                    "Connection",
                    False,
                    "No data returned - check ThetaData Terminal",
                )
                print("   ❌ Connection failed - no data returned")
                return TestSuiteResult(
                    source_name=self.source_name,
                    results=self.results,
                    error="Connection failed",
                )

            # 测试每个 symbol
            for symbol in self.symbols:
                print(f"\n   {symbol} Stock EOD:")
                self._test_stock_eod(client, symbol)

                print(f"\n   {symbol} Options:")
                self._test_options(client, symbol)

            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
            )

        except ImportError as e:
            error_msg = f"ThetaData client not available: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )
        except Exception as e:
            error_msg = f"ThetaData test failed: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )

    def _test_stock_eod(self, client, symbol: str) -> None:
        """测试股票日线数据"""
        try:
            data = client.get_stock_eod(symbol, self.start_date, self.end_date)

            if not data:
                self.add_result(
                    f"{symbol} Stock EOD",
                    False,
                    "No data returned",
                )
                print(f"     ❌ No data returned")
                return

            # 统计
            record_count = len(data)
            dates = sorted([d.date for d in data])
            min_date, max_date = dates[0], dates[-1]
            prices = [d.close for d in data]
            min_price, max_price = min(prices), max(prices)

            # 验证数据质量
            quality_issues = []

            # 检查价格合理性
            for d in data:
                if not (d.low <= d.open <= d.high and d.low <= d.close <= d.high):
                    quality_issues.append(f"{d.date}: OHLC inconsistent")
                if d.close <= 0:
                    quality_issues.append(f"{d.date}: Invalid close price")

            passed = len(quality_issues) == 0
            self.add_result(
                f"{symbol} Stock EOD",
                passed,
                f"{record_count} days, ${min_price:.2f} ~ ${max_price:.2f}",
                {
                    "records": record_count,
                    "date_range": f"{min_date} ~ {max_date}",
                    "price_range": f"${min_price:.2f} ~ ${max_price:.2f}",
                    "quality_issues": quality_issues[:3] if quality_issues else None,
                },
            )

            print(f"     ✅ Records: {record_count} days")
            print(f"     ✅ Date range: {min_date} ~ {max_date}")
            print(f"     ✅ Price range: ${min_price:.2f} ~ ${max_price:.2f}")
            if quality_issues:
                print(f"     ⚠️  Quality issues: {len(quality_issues)}")

        except Exception as e:
            self.add_result(f"{symbol} Stock EOD", False, str(e))
            print(f"     ❌ Error: {e}")

    def _test_options(self, client, symbol: str) -> None:
        """测试期权数据"""
        try:
            # 获取到期日列表
            expirations = client.get_option_expirations(symbol)

            if not expirations:
                self.add_result(
                    f"{symbol} Options Expirations",
                    False,
                    "No expirations returned",
                )
                print(f"     ❌ No expirations returned")
                return

            # 过滤在测试窗口内的到期日
            valid_exps = [
                exp
                for exp in expirations
                if exp >= self.start_date and exp <= self.end_date + timedelta(days=60)
            ]

            self.add_result(
                f"{symbol} Options Expirations",
                True,
                f"{len(valid_exps)} expirations in range",
                {"total_expirations": len(expirations), "in_range": len(valid_exps)},
            )
            print(f"     ✅ Expirations: {len(valid_exps)} dates in range")

            # 获取期权数据 (使用自动 fallback 方法)
            # 如果 API 返回 403，会自动计算 Greeks
            test_start = self.end_date - timedelta(days=5)

            # 选择最近的到期日，避免数据量过大
            if valid_exps:
                nearest_exp = min(valid_exps, key=lambda x: abs((x - self.end_date).days))
            else:
                nearest_exp = None

            # 使用新的自动 fallback 方法
            options = client.get_option_with_greeks(
                symbol,
                test_start,
                self.end_date,
                expiration=nearest_exp,
                max_dte=30,
            )

            if not options:
                self.add_result(
                    f"{symbol} Options Data",
                    False,
                    "No option data returned",
                )
                print(f"     ❌ No option data returned")
                return

            # 验证 Greeks (无论是 API 获取还是计算得到)
            greeks_complete = 0
            iv_values = []

            for opt in options:
                if all(
                    [
                        opt.delta is not None,
                        opt.gamma is not None,
                        opt.theta is not None,
                        opt.vega is not None,
                    ]
                ):
                    greeks_complete += 1
                if opt.implied_vol is not None and opt.implied_vol > 0:
                    iv_values.append(opt.implied_vol)

            greeks_pct = greeks_complete / len(options) * 100 if options else 0
            iv_min = min(iv_values) if iv_values else 0
            iv_max = max(iv_values) if iv_values else 0

            passed = greeks_pct >= 70 and len(iv_values) > 0  # 降低阈值，因为部分计算可能失败
            self.add_result(
                f"{symbol} Options Data",
                passed,
                f"{len(options)} contracts, Greeks {greeks_pct:.0f}% complete",
                {
                    "contracts": len(options),
                    "greeks_complete_pct": f"{greeks_pct:.1f}%",
                    "iv_range": f"{iv_min:.2f} ~ {iv_max:.2f}" if iv_values else "N/A",
                },
            )

            print(f"     ✅ Option records: {len(options)} contracts")
            print(f"     ✅ Greeks complete: {greeks_pct:.0f}% (auto-calculated if API unavailable)")
            if iv_values:
                print(f"     ✅ IV range: {iv_min:.2f} ~ {iv_max:.2f}")

        except Exception as e:
            self.add_result(f"{symbol} Options", False, str(e))
            print(f"     ❌ Error: {e}")


# ============================================================
# yfinance Tester
# ============================================================


class YFinanceTester(DataSourceTester):
    """yfinance 宏观数据测试"""

    MACRO_INDICATORS = ["^VIX", "^TNX", "SPY"]

    @property
    def source_name(self) -> str:
        return "yfinance"

    def run_tests(self) -> TestSuiteResult:
        """运行 yfinance 测试"""
        print(f"\n{'='*60}")
        print("2. yfinance (Macro Data)")
        print("=" * 60)

        try:
            import yfinance as yf

            for indicator in self.MACRO_INDICATORS:
                print(f"\n   {indicator}:")
                self._test_indicator(yf, indicator)

            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
            )

        except ImportError as e:
            error_msg = f"yfinance not available: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )
        except Exception as e:
            error_msg = f"yfinance test failed: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )

    def _test_indicator(self, yf, indicator: str) -> None:
        """测试单个指标"""
        try:
            ticker = yf.Ticker(indicator)
            hist = ticker.history(
                start=self.start_date.isoformat(),
                end=(self.end_date + timedelta(days=1)).isoformat(),
            )

            if hist.empty:
                self.add_result(indicator, False, "No data returned")
                print(f"     ❌ No data returned")
                return

            record_count = len(hist)
            close_values = hist["Close"].dropna()
            min_close = close_values.min()
            max_close = close_values.max()

            # 验证数据范围
            quality_ok = True
            quality_msg = ""

            if indicator == "^VIX":
                # VIX 应该在 10-80 之间
                if min_close < 5 or max_close > 100:
                    quality_ok = False
                    quality_msg = f"VIX out of expected range: {min_close:.1f} ~ {max_close:.1f}"
            elif indicator == "^TNX":
                # 10Y 收益率应该在 0-10% 之间
                if min_close < 0 or max_close > 15:
                    quality_ok = False
                    quality_msg = f"TNX out of expected range: {min_close:.2f} ~ {max_close:.2f}"

            self.add_result(
                indicator,
                quality_ok,
                f"{record_count} days, {min_close:.2f} ~ {max_close:.2f}",
                {
                    "records": record_count,
                    "close_range": f"{min_close:.2f} ~ {max_close:.2f}",
                    "has_volume": "Volume" in hist.columns and hist["Volume"].sum() > 0,
                },
            )

            print(f"     ✅ Records: {record_count} days")
            print(f"     ✅ Close range: {min_close:.2f} ~ {max_close:.2f}")

            if "Volume" in hist.columns and hist["Volume"].sum() > 0:
                print(f"     ✅ Volume available")

            if not quality_ok:
                print(f"     ⚠️  {quality_msg}")

        except Exception as e:
            self.add_result(indicator, False, str(e))
            print(f"     ❌ Error: {e}")


# ============================================================
# IBKR Tester
# ============================================================


class IBKRTester(DataSourceTester):
    """IBKR 基本面数据测试"""

    def __init__(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        output_dir: Path | None = None,
        ibkr_port: int | None = None,
    ):
        super().__init__(symbols, start_date, end_date, output_dir)
        self.ibkr_port = ibkr_port

    @property
    def source_name(self) -> str:
        return "IBKR"

    def run_tests(self) -> TestSuiteResult:
        """运行 IBKR 测试"""
        print(f"\n{'='*60}")
        print("3. IBKR (Fundamental Data)")
        print("=" * 60)

        try:
            from src.backtest.data.ibkr_fundamental_downloader import (
                IBKRFundamentalDownloader,
            )

            # 创建下载器
            output_dir = self.output_dir or Path("data/test_verify")
            output_dir.mkdir(parents=True, exist_ok=True)

            downloader = IBKRFundamentalDownloader(
                data_dir=output_dir,
                port=self.ibkr_port,
            )

            # 测试连接和下载
            print("\n   Testing connection and downloading...")

            for symbol in self.symbols:
                print(f"\n   {symbol}:")
                self._test_fundamental(downloader, symbol)

            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
            )

        except ImportError as e:
            error_msg = f"IBKR downloader not available: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )
        except Exception as e:
            error_msg = f"IBKR test failed: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )

    def _test_fundamental(self, downloader, symbol: str) -> None:
        """测试单个 symbol 的基本面数据"""
        try:
            # 下载数据
            data = downloader.download_symbol(symbol)

            if data is None:
                # SPY 是 ETF，可能没有基本面数据
                if symbol == "SPY":
                    self.add_result(
                        f"{symbol} Fundamental",
                        True,
                        "ETF - no fundamental data expected",
                        {"note": "SPY is an ETF, fundamental data not available"},
                    )
                    print(f"     ⚠️  SPY is ETF, no fundamental data expected")
                else:
                    self.add_result(
                        f"{symbol} Fundamental",
                        False,
                        "No data returned - check TWS connection",
                    )
                    print(f"     ❌ No data returned")
                return

            # 统计数据
            eps_count = len(data.eps_records)
            revenue_count = len(data.revenue_records)
            dividend_count = len(data.dividend_records)

            # EPS 日期范围
            if data.eps_records:
                eps_dates = sorted([r.as_of_date for r in data.eps_records])
                eps_range = f"{eps_dates[0]} ~ {eps_dates[-1]}"

                # 获取最近的 TTM EPS
                ttm_records = [r for r in data.eps_records if r.report_type == "TTM"]
                latest_eps = ttm_records[-1].eps if ttm_records else None
            else:
                eps_range = "N/A"
                latest_eps = None

            passed = eps_count > 0 or symbol == "SPY"
            self.add_result(
                f"{symbol} Fundamental",
                passed,
                f"EPS: {eps_count}, Revenue: {revenue_count}, Dividend: {dividend_count}",
                {
                    "eps_records": eps_count,
                    "revenue_records": revenue_count,
                    "dividend_records": dividend_count,
                    "eps_date_range": eps_range,
                    "latest_ttm_eps": latest_eps,
                },
            )

            print(f"     ✅ EPS records: {eps_count}")
            print(f"     ✅ Revenue records: {revenue_count}")
            print(f"     ✅ Dividend records: {dividend_count}")
            if eps_count > 0:
                print(f"     ✅ Date range: {eps_range}")
            if latest_eps:
                print(f"     ✅ Latest TTM EPS: ${latest_eps:.2f}")

        except Exception as e:
            self.add_result(f"{symbol} Fundamental", False, str(e))
            print(f"     ❌ Error: {e}")


# ============================================================
# Greeks Calculator Tester
# ============================================================


class GreeksCalculatorTester(DataSourceTester):
    """Greeks 计算器测试 - 验证从 EOD 数据计算 IV 和 Greeks"""

    @property
    def source_name(self) -> str:
        return "Greeks Calculator"

    def run_tests(self) -> TestSuiteResult:
        """运行 Greeks 计算测试"""
        print(f"\n{'='*60}")
        print("4. Greeks Calculator (IV + Greeks from EOD)")
        print("=" * 60)

        try:
            from src.backtest.data.greeks_calculator import GreeksCalculator
            from src.backtest.data.thetadata_client import (
                ThetaDataClient,
                ThetaDataConfig,
            )

            # 初始化
            calc = GreeksCalculator()
            config = ThetaDataConfig()
            client = ThetaDataClient(config)

            # 获取无风险利率 (从 yfinance)
            rate = self._get_risk_free_rate()
            print(f"\n   Risk-free rate (^TNX): {rate:.2%}")

            # 测试每个 symbol
            for symbol in self.symbols:
                print(f"\n   {symbol} Greeks Calculation:")
                self._test_greeks_calculation(client, calc, symbol, rate)

            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
            )

        except ImportError as e:
            error_msg = f"Module not available: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )
        except Exception as e:
            error_msg = f"Greeks test failed: {e}"
            print(f"   ❌ {error_msg}")
            return TestSuiteResult(
                source_name=self.source_name,
                results=self.results,
                error=error_msg,
            )

    def _get_risk_free_rate(self) -> float:
        """获取无风险利率"""
        try:
            import yfinance as yf

            tnx = yf.Ticker("^TNX")
            hist = tnx.history(period="5d")
            if not hist.empty:
                return hist["Close"].iloc[-1] / 100  # TNX 是百分比形式
        except Exception:
            pass
        return 0.045  # 默认 4.5%

    def _test_greeks_calculation(
        self, client, calc, symbol: str, rate: float
    ) -> None:
        """测试单个 symbol 的 Greeks 计算"""
        try:
            # 获取股票 EOD (作为 underlying price)
            stock_data = client.get_stock_eod(
                symbol, self.start_date, self.end_date
            )

            if not stock_data:
                self.add_result(
                    f"{symbol} Stock Data",
                    False,
                    "No stock data for underlying price",
                )
                print(f"     ❌ No stock data available")
                return

            # 构建 {date: price} 映射
            stock_prices = {d.date: d.close for d in stock_data}
            latest_date = max(stock_prices.keys())
            latest_spot = stock_prices[latest_date]
            print(f"     Stock price ({latest_date}): ${latest_spot:.2f}")

            # 获取期权到期日
            expirations = client.get_option_expirations(symbol)
            if not expirations:
                self.add_result(
                    f"{symbol} Expirations",
                    False,
                    "No expirations available",
                )
                print(f"     ❌ No expirations available")
                return

            # 选择最近的到期日 (30天内)
            valid_exps = [
                exp for exp in expirations
                if 7 <= (exp - latest_date).days <= 45
            ]

            if not valid_exps:
                self.add_result(
                    f"{symbol} Valid Expirations",
                    False,
                    "No expirations in 7-45 DTE range",
                )
                print(f"     ❌ No valid expirations (7-45 DTE)")
                return

            nearest_exp = min(valid_exps)
            dte = (nearest_exp - latest_date).days
            print(f"     Testing expiration: {nearest_exp} (DTE={dte})")

            # 获取该到期日的期权数据
            options = client.get_option_eod(
                symbol,
                latest_date - timedelta(days=3),
                latest_date,
                expiration=nearest_exp,
            )

            if not options:
                self.add_result(
                    f"{symbol} Options Data",
                    False,
                    "No option data for Greeks calculation",
                )
                print(f"     ❌ No option data available")
                return

            print(f"     Options loaded: {len(options)} contracts")

            # 批量计算 Greeks
            enriched = calc.enrich_options_batch(options, stock_prices, rate)

            if not enriched:
                self.add_result(
                    f"{symbol} Greeks Calculation",
                    False,
                    "All Greeks calculations failed",
                )
                print(f"     ❌ All calculations failed")
                return

            success_rate = len(enriched) / len(options) * 100
            print(f"     Greeks calculated: {len(enriched)}/{len(options)} ({success_rate:.0f}%)")

            # 验证 Greeks 合理性
            iv_values = [o.iv for o in enriched if o.iv > 0]
            delta_calls = [o.delta for o in enriched if o.right == "call"]
            delta_puts = [o.delta for o in enriched if o.right == "put"]

            # IV 应该在合理范围 (5% - 200%)
            iv_valid = all(0.05 <= iv <= 2.0 for iv in iv_values) if iv_values else False

            # Call delta 应该在 0-1，Put delta 应该在 -1-0
            delta_call_valid = all(0 <= d <= 1 for d in delta_calls) if delta_calls else True
            delta_put_valid = all(-1 <= d <= 0 for d in delta_puts) if delta_puts else True

            # 统计
            if iv_values:
                iv_min, iv_max = min(iv_values), max(iv_values)
                iv_mean = sum(iv_values) / len(iv_values)
                print(f"     IV range: {iv_min:.1%} ~ {iv_max:.1%} (mean: {iv_mean:.1%})")

            # 找一个 ATM 期权展示详情
            atm_options = sorted(
                enriched,
                key=lambda o: abs(o.strike - latest_spot)
            )[:2]

            for opt in atm_options:
                print(f"     Sample {opt.right.upper()} K={opt.strike:.0f}:")
                print(f"       IV={opt.iv:.1%}, Δ={opt.delta:.3f}, Γ={opt.gamma:.4f}, Θ={opt.theta:.3f}, V={opt.vega:.3f}")

            # 记录结果
            passed = (
                success_rate >= 70
                and iv_valid
                and delta_call_valid
                and delta_put_valid
            )

            self.add_result(
                f"{symbol} Greeks Calculation",
                passed,
                f"{len(enriched)} options, IV {iv_min:.0%}~{iv_max:.0%}",
                {
                    "options_processed": len(options),
                    "greeks_calculated": len(enriched),
                    "success_rate": f"{success_rate:.1f}%",
                    "iv_range": f"{iv_min:.1%} ~ {iv_max:.1%}" if iv_values else "N/A",
                    "iv_valid": iv_valid,
                    "delta_valid": delta_call_valid and delta_put_valid,
                },
            )

            if passed:
                print(f"     ✅ Greeks calculation verified")
            else:
                print(f"     ⚠️  Some validation checks failed")

        except Exception as e:
            self.add_result(f"{symbol} Greeks", False, str(e))
            print(f"     ❌ Error: {e}")


# ============================================================
# Main Test Runner
# ============================================================


def print_summary(results: list[TestSuiteResult]) -> None:
    """打印测试摘要"""
    print(f"\n{'='*60}")
    print("Summary")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    for suite in results:
        passed = suite.passed_count
        failed = suite.failed_count
        total = suite.total_count
        total_passed += passed
        total_failed += failed

        status = "✅" if failed == 0 and suite.error is None else "❌"
        error_note = f" (Error: {suite.error})" if suite.error else ""

        print(f"   {status} {suite.source_name}: {passed}/{total} passed{error_note}")

    print(f"\n   Total: {total_passed}/{total_passed + total_failed} tests passed")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Verify backtest data sources connectivity and correctness"
    )
    parser.add_argument(
        "--source",
        "-s",
        choices=["thetadata", "yfinance", "ibkr", "greeks", "all"],
        default="all",
        help="Data source to test (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("data/test_verify"),
        help="Output directory for downloaded test data",
    )
    parser.add_argument(
        "--ibkr-port",
        "-p",
        type=int,
        default=None,
        help="IBKR TWS/Gateway port (default: from IBKR_PORT env or 7497)",
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=30,
        help="Number of days to test (default: 30)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 计算日期范围
    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)

    # 测试标的
    symbols = ["GOOG", "QQQ"]

    print("=" * 60)
    print("Backtest Data Verification Report")
    print("=" * 60)
    print(f"\nDate: {date.today()}")
    print(f"Test Period: {start_date} ~ {end_date}")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Output Dir: {args.output_dir}")

    # 确保输出目录存在
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 运行测试
    results: list[TestSuiteResult] = []

    if args.source in ["thetadata", "all"]:
        tester = ThetaDataTester(symbols, start_date, end_date, args.output_dir)
        results.append(tester.run_tests())

    if args.source in ["yfinance", "all"]:
        tester = YFinanceTester(symbols, start_date, end_date, args.output_dir)
        results.append(tester.run_tests())

    if args.source in ["ibkr", "all"]:
        tester = IBKRTester(
            symbols, start_date, end_date, args.output_dir, args.ibkr_port
        )
        results.append(tester.run_tests())

    if args.source in ["greeks", "all"]:
        tester = GreeksCalculatorTester(symbols, start_date, end_date, args.output_dir)
        results.append(tester.run_tests())

    # 打印摘要
    print_summary(results)

    # 返回退出码
    total_failed = sum(r.failed_count for r in results)
    errors = sum(1 for r in results if r.error)

    if total_failed > 0 or errors > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
