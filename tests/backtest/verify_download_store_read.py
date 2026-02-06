#!/usr/bin/env python3
"""
数据管道验证: Download -> Store (Parquet) -> Read (DuckDB)

验证完整的数据管道流程:
1. Download: 从 ThetaData/yfinance/IBKR 下载数据
2. Store: 保存为 Parquet 文件
3. Read: 通过 DuckDBProvider 读取并验证

测试范围:
- 股票/期权: GOOG, SPY (最近 5 个交易日)
- 宏观数据: ^VIX, ^TNX (最近 1 个月)
- 基本面: GOOG (最近 1 年)

Usage:
    # 运行完整测试
    python tests/verification/verify_data_pipeline.py

    # 指定数据目录
    python tests/verification/verify_data_pipeline.py --data-dir /Volumes/ORICO/option_quant/

    # 只测试特定阶段
    python tests/verification/verify_data_pipeline.py --phase download
    python tests/verification/verify_data_pipeline.py --phase read
    python tests/verification/verify_data_pipeline.py --phase integrity
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

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
class TestPhaseResult:
    """测试阶段结果"""

    phase_name: str
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
# Pipeline Tester Class
# ============================================================


class PipelineTester:
    """数据管道测试器"""

    def __init__(
        self,
        data_dir: Path,
        symbols: list[str],
        stock_days: int = 5,
        macro_days: int = 30,
        fundamental_years: int = 1,
        max_dte: int = 30,
        ibkr_port: int | None = None,
    ):
        """初始化测试器

        Args:
            data_dir: 数据存储目录
            symbols: 测试标的列表
            stock_days: 股票/期权数据天数
            macro_days: 宏观数据天数
            fundamental_years: 基本面数据年数
            max_dte: 期权最大 DTE
            ibkr_port: IBKR TWS/Gateway 端口
        """
        self.data_dir = Path(data_dir)
        self.symbols = symbols
        self.stock_days = stock_days
        self.macro_days = macro_days
        self.fundamental_years = fundamental_years
        self.max_dte = max_dte
        self.ibkr_port = ibkr_port

        # 计算日期范围
        # 期权数据不能包含今天（expiration=* 限制），使用昨天作为 end_date
        self.end_date = date.today() - timedelta(days=1)
        self.stock_start_date = self.end_date - timedelta(days=stock_days + 5)  # 多加几天，确保有足够交易日
        self.macro_start_date = self.end_date - timedelta(days=macro_days)
        self.fundamental_start_date = self.end_date - timedelta(days=365 * fundamental_years)

        # 宏观指标
        self.macro_indicators = ["^VIX", "^TNX"]

        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ========== Download Phase ==========

    def test_download_phase(self) -> TestPhaseResult:
        """测试下载阶段"""
        print(f"\n{'='*60}")
        print("1. Download Phase")
        print("=" * 60)

        results: list[TestResult] = []

        # 1.1 ThetaData: Stock + Option
        print("\n   --- ThetaData (Stock + Option) ---")
        stock_results = self._test_download_thetadata()
        results.extend(stock_results)

        # 1.2 yfinance: Macro
        print("\n   --- yfinance (Macro) ---")
        macro_results = self._test_download_macro()
        results.extend(macro_results)

        # 1.3 IBKR: Fundamental
        print("\n   --- IBKR (Fundamental) ---")
        fundamental_results = self._test_download_fundamental()
        results.extend(fundamental_results)

        return TestPhaseResult(phase_name="Download", results=results)

    def _test_download_thetadata(self) -> list[TestResult]:
        """测试 ThetaData 下载"""
        results = []

        try:
            from src.backtest.data.data_downloader import DataDownloader
            from src.backtest.data.thetadata_client import ThetaDataClient, ThetaDataConfig

            # 测试连接
            config = ThetaDataConfig()
            client = ThetaDataClient(config)

            # 简单连接测试
            test_data = client.get_stock_eod(
                self.symbols[0],
                self.end_date - timedelta(days=3),
                self.end_date,
            )

            if not test_data:
                results.append(TestResult(
                    "ThetaData Connection",
                    False,
                    "No data returned - check ThetaData Terminal",
                ))
                print(f"   ❌ ThetaData connection failed")
                return results

            results.append(TestResult(
                "ThetaData Connection",
                True,
                f"Connected to {config.host}:{config.port}",
            ))
            print(f"   ✅ ThetaData connected to {config.host}:{config.port}")

            # 创建下载器
            downloader = DataDownloader(data_dir=self.data_dir, client=client)

            # 下载股票数据
            print(f"\n   Downloading stock data ({self.symbols})...")

            def stock_progress(symbol, current, total):
                print(f"     [{current+1}/{total}] {symbol}")

            stock_results = downloader.download_stocks(
                symbols=self.symbols,
                start_date=self.stock_start_date,
                end_date=self.end_date,
                on_progress=stock_progress,
            )

            for symbol, count in stock_results.items():
                passed = count > 0
                results.append(TestResult(
                    f"{symbol} Stock Download",
                    passed,
                    f"{count} records" if passed else "No data",
                    {"records": count},
                ))
                status = "✅" if passed else "❌"
                print(f"   {status} {symbol} Stock: {count} records")

            # 验证 Parquet 文件
            stock_parquet = self.data_dir / "stock_daily.parquet"
            if stock_parquet.exists():
                file_size = stock_parquet.stat().st_size / 1024
                results.append(TestResult(
                    "Stock Parquet File",
                    True,
                    f"Created at {stock_parquet.name} ({file_size:.1f} KB)",
                    {"path": str(stock_parquet), "size_kb": file_size},
                ))
                print(f"   ✅ Stock Parquet: {stock_parquet.name} ({file_size:.1f} KB)")

            # 下载期权数据
            print(f"\n   Downloading option data (max_dte={self.max_dte}, strike_range=30)...")

            def option_progress(symbol, current_date, day_idx, total_days):
                if day_idx % 2 == 0:  # 每 2 天打印一次
                    print(f"     {symbol} {current_date} ({day_idx+1}/{total_days})")

            option_results = downloader.download_options(
                symbols=self.symbols,
                start_date=self.stock_start_date,
                end_date=self.end_date,
                max_dte=self.max_dte,
                strike_range=30,  # ATM 上下各 30 个 strikes
                on_progress=option_progress,
            )

            for symbol, count in option_results.items():
                passed = count > 0
                results.append(TestResult(
                    f"{symbol} Option Download",
                    passed,
                    f"{count} contracts" if passed else "No data",
                    {"contracts": count},
                ))
                status = "✅" if passed else "❌"
                print(f"   {status} {symbol} Options: {count} contracts")

                # 验证 Parquet 文件
                option_parquet = self.data_dir / "option_daily" / symbol / f"{self.end_date.year}.parquet"
                if option_parquet.exists():
                    file_size = option_parquet.stat().st_size / 1024
                    print(f"       → {option_parquet.relative_to(self.data_dir)} ({file_size:.1f} KB)")

        except ImportError as e:
            results.append(TestResult(
                "ThetaData Import",
                False,
                f"Module not available: {e}",
            ))
            print(f"   ❌ ThetaData import error: {e}")
        except Exception as e:
            results.append(TestResult(
                "ThetaData Download",
                False,
                f"Error: {e}",
            ))
            print(f"   ❌ ThetaData error: {e}")

        return results

    def _test_download_macro(self) -> list[TestResult]:
        """测试 yfinance 宏观数据下载"""
        results = []

        try:
            import yfinance as yf
            import pyarrow as pa
            import pyarrow.parquet as pq

            macro_data = []

            for indicator in self.macro_indicators:
                print(f"\n   Downloading {indicator}...")

                ticker = yf.Ticker(indicator)
                hist = ticker.history(
                    start=self.macro_start_date.isoformat(),
                    end=(self.end_date + timedelta(days=1)).isoformat(),
                )

                if hist.empty:
                    results.append(TestResult(
                        f"{indicator} Download",
                        False,
                        "No data returned",
                    ))
                    print(f"   ❌ {indicator}: No data")
                    continue

                record_count = len(hist)
                close_min = hist["Close"].min()
                close_max = hist["Close"].max()

                results.append(TestResult(
                    f"{indicator} Download",
                    True,
                    f"{record_count} days, {close_min:.2f} ~ {close_max:.2f}",
                    {"records": record_count, "min": close_min, "max": close_max},
                ))
                print(f"   ✅ {indicator}: {record_count} days, range {close_min:.2f} ~ {close_max:.2f}")

                # 转换为统一格式
                for idx, row in hist.iterrows():
                    macro_data.append({
                        "indicator": indicator,
                        "date": idx.date(),
                        "open": row["Open"],
                        "high": row["High"],
                        "low": row["Low"],
                        "close": row["Close"],
                        "volume": int(row["Volume"]) if row["Volume"] > 0 else 0,
                    })

            # 保存为 Parquet
            if macro_data:
                macro_parquet = self.data_dir / "macro_daily.parquet"
                table = pa.Table.from_pylist(macro_data)
                pq.write_table(table, macro_parquet)

                file_size = macro_parquet.stat().st_size / 1024
                results.append(TestResult(
                    "Macro Parquet File",
                    True,
                    f"Created ({file_size:.1f} KB)",
                    {"path": str(macro_parquet), "records": len(macro_data)},
                ))
                print(f"   ✅ Macro Parquet: {macro_parquet.name} ({file_size:.1f} KB)")

        except ImportError as e:
            results.append(TestResult(
                "yfinance Import",
                False,
                f"Module not available: {e}",
            ))
            print(f"   ❌ yfinance import error: {e}")
        except Exception as e:
            results.append(TestResult(
                "Macro Download",
                False,
                f"Error: {e}",
            ))
            print(f"   ❌ Macro download error: {e}")

        return results

    def _test_download_fundamental(self) -> list[TestResult]:
        """测试 IBKR 基本面数据下载"""
        results = []

        try:
            from src.backtest.data.ibkr_fundamental_downloader import IBKRFundamentalDownloader

            downloader = IBKRFundamentalDownloader(
                data_dir=self.data_dir,
                port=self.ibkr_port,
            )

            for symbol in self.symbols:
                print(f"\n   Downloading {symbol} fundamental...")

                # SPY 是 ETF，跳过
                if symbol == "SPY":
                    results.append(TestResult(
                        f"{symbol} Fundamental",
                        True,
                        "Skipped (ETF)",
                        {"note": "SPY is an ETF, no fundamental data"},
                    ))
                    print(f"   ⚠️  {symbol}: Skipped (ETF, no fundamental data)")
                    continue

                try:
                    data = downloader.download_symbol(symbol)

                    if data is None:
                        results.append(TestResult(
                            f"{symbol} Fundamental",
                            False,
                            "No data - check IBKR connection",
                        ))
                        print(f"   ❌ {symbol}: No data returned")
                        continue

                    eps_count = len(data.eps_records)
                    revenue_count = len(data.revenue_records)
                    dividend_count = len(data.dividend_records)

                    results.append(TestResult(
                        f"{symbol} Fundamental",
                        eps_count > 0,
                        f"EPS: {eps_count}, Revenue: {revenue_count}, Dividend: {dividend_count}",
                        {
                            "eps": eps_count,
                            "revenue": revenue_count,
                            "dividend": dividend_count,
                        },
                    ))
                    print(f"   ✅ {symbol}: EPS={eps_count}, Revenue={revenue_count}, Dividend={dividend_count}")

                except Exception as e:
                    results.append(TestResult(
                        f"{symbol} Fundamental",
                        False,
                        f"Error: {e}",
                    ))
                    print(f"   ❌ {symbol}: Error - {e}")

            # 保存数据
            save_results = downloader.download_and_save(
                symbols=[s for s in self.symbols if s != "SPY"],
                delay=0.5,
            )

            if save_results:
                # 验证 Parquet 文件
                for name in ["fundamental_eps.parquet", "fundamental_revenue.parquet"]:
                    parquet_path = self.data_dir / name
                    if parquet_path.exists():
                        file_size = parquet_path.stat().st_size / 1024
                        print(f"   ✅ {name} ({file_size:.1f} KB)")

        except ImportError as e:
            results.append(TestResult(
                "IBKR Import",
                False,
                f"Module not available: {e}",
            ))
            print(f"   ❌ IBKR import error: {e}")
        except Exception as e:
            results.append(TestResult(
                "Fundamental Download",
                False,
                f"Error: {e}",
            ))
            print(f"   ❌ Fundamental error: {e}")

        return results

    # ========== Read Phase ==========

    def _get_latest_data_date(self) -> date | None:
        """获取数据中实际可用的最新日期"""
        import duckdb

        stock_path = self.data_dir / "stock_daily.parquet"
        if not stock_path.exists():
            return None

        try:
            conn = duckdb.connect(":memory:")
            # 获取所有 symbol 都有数据的最新日期
            result = conn.execute(f"""
                SELECT MAX(date) as latest_date
                FROM (
                    SELECT date, COUNT(DISTINCT symbol) as sym_count
                    FROM read_parquet('{stock_path}')
                    GROUP BY date
                    HAVING sym_count >= {len(self.symbols)}
                )
            """).fetchone()

            if result and result[0]:
                return result[0] if isinstance(result[0], date) else date.fromisoformat(str(result[0])[:10])
        except Exception as e:
            logger.warning(f"Failed to get latest data date: {e}")
        return None

    def test_read_phase(self) -> TestPhaseResult:
        """测试读取阶段"""
        print(f"\n{'='*60}")
        print("2. Read Phase (DuckDBProvider)")
        print("=" * 60)

        results: list[TestResult] = []

        try:
            from src.backtest.data.duckdb_provider import DuckDBProvider

            # 使用数据中实际可用的最新日期，而不是计算的 end_date
            actual_date = self._get_latest_data_date() or self.end_date

            # 初始化 Provider
            provider = DuckDBProvider(
                data_dir=self.data_dir,
                as_of_date=actual_date,
                auto_download_fundamental=False,  # 不自动下载，使用已下载的数据
            )

            results.append(TestResult(
                "DuckDBProvider Init",
                True,
                f"Initialized with as_of_date={actual_date}",
            ))
            print(f"\n   ✅ DuckDBProvider initialized (as_of_date={actual_date})")

            # 2.1 测试股票读取
            print("\n   --- Stock Quote Test ---")
            for symbol in self.symbols:
                quote = provider.get_stock_quote(symbol)
                if quote:
                    results.append(TestResult(
                        f"{symbol} Stock Quote",
                        True,
                        f"${quote.close:.2f} ({quote.timestamp.date()})",
                        {
                            "close": quote.close,
                            "date": str(quote.timestamp.date()),
                            "volume": quote.volume,
                        },
                    ))
                    print(f"   ✅ {symbol}: ${quote.close:.2f} ({quote.timestamp.date()})")
                else:
                    results.append(TestResult(
                        f"{symbol} Stock Quote",
                        False,
                        "No data returned",
                    ))
                    print(f"   ❌ {symbol}: No stock quote")

            # 2.2 测试期权链读取
            print("\n   --- Option Chain Test ---")
            for symbol in self.symbols:
                chain = provider.get_option_chain(symbol)
                if chain:
                    total_contracts = len(chain.calls) + len(chain.puts)
                    exp_count = len(chain.expiry_dates)

                    # 检查 Greeks
                    greeks_complete = 0
                    for opt in chain.calls + chain.puts:
                        if opt.greeks and all([
                            opt.greeks.delta is not None,
                            opt.greeks.gamma is not None,
                            opt.greeks.theta is not None,
                            opt.greeks.vega is not None,
                        ]):
                            greeks_complete += 1

                    greeks_pct = greeks_complete / total_contracts * 100 if total_contracts > 0 else 0

                    results.append(TestResult(
                        f"{symbol} Option Chain",
                        True,
                        f"{total_contracts} contracts, {exp_count} expirations, Greeks {greeks_pct:.0f}%",
                        {
                            "contracts": total_contracts,
                            "expirations": exp_count,
                            "greeks_pct": greeks_pct,
                        },
                    ))
                    print(f"   ✅ {symbol}: {total_contracts} contracts, {exp_count} expirations, Greeks {greeks_pct:.0f}%")
                else:
                    results.append(TestResult(
                        f"{symbol} Option Chain",
                        False,
                        "No data returned",
                    ))
                    print(f"   ❌ {symbol}: No option chain")

            # 2.3 测试宏观数据读取
            print("\n   --- Macro Data Test ---")
            for indicator in self.macro_indicators:
                macro_data = provider.get_macro_data(
                    indicator,
                    self.macro_start_date,
                    self.end_date,
                )
                if macro_data:
                    record_count = len(macro_data)
                    close_values = [m.close for m in macro_data if m.close]
                    close_min = min(close_values) if close_values else 0
                    close_max = max(close_values) if close_values else 0

                    results.append(TestResult(
                        f"{indicator} Macro Data",
                        True,
                        f"{record_count} records, {close_min:.2f} ~ {close_max:.2f}",
                        {"records": record_count, "min": close_min, "max": close_max},
                    ))
                    print(f"   ✅ {indicator}: {record_count} records, {close_min:.2f} ~ {close_max:.2f}")
                else:
                    results.append(TestResult(
                        f"{indicator} Macro Data",
                        False,
                        "No data returned",
                    ))
                    print(f"   ❌ {indicator}: No macro data")

            # 2.4 测试基本面数据读取
            print("\n   --- Fundamental Data Test ---")
            for symbol in self.symbols:
                if symbol == "SPY":
                    print(f"   ⚠️  {symbol}: Skipped (ETF)")
                    continue

                fundamental = provider.get_fundamental(symbol)
                if fundamental and fundamental.eps:
                    results.append(TestResult(
                        f"{symbol} Fundamental",
                        True,
                        f"EPS: ${fundamental.eps:.2f}, PE: {fundamental.pe_ratio:.1f}" if fundamental.pe_ratio else f"EPS: ${fundamental.eps:.2f}",
                        {
                            "eps": fundamental.eps,
                            "pe_ratio": fundamental.pe_ratio,
                        },
                    ))
                    pe_info = f", PE: {fundamental.pe_ratio:.1f}" if fundamental.pe_ratio else ""
                    print(f"   ✅ {symbol}: EPS=${fundamental.eps:.2f}{pe_info}")
                else:
                    results.append(TestResult(
                        f"{symbol} Fundamental",
                        False,
                        "No EPS data",
                    ))
                    print(f"   ❌ {symbol}: No fundamental data")

            provider.close()

        except ImportError as e:
            results.append(TestResult(
                "DuckDBProvider Import",
                False,
                f"Module not available: {e}",
            ))
            print(f"   ❌ DuckDBProvider import error: {e}")
        except Exception as e:
            results.append(TestResult(
                "DuckDBProvider",
                False,
                f"Error: {e}",
            ))
            print(f"   ❌ DuckDBProvider error: {e}")

        return TestPhaseResult(phase_name="Read", results=results)

    # ========== Integrity Check Phase ==========

    def test_integrity_phase(self) -> TestPhaseResult:
        """测试数据完整性"""
        print(f"\n{'='*60}")
        print("3. Data Integrity Check")
        print("=" * 60)

        results: list[TestResult] = []

        # 3.1 验证 Parquet 文件可读
        print("\n   --- Parquet File Validation ---")

        parquet_files = [
            ("stock_daily.parquet", "Stock"),
            ("macro_daily.parquet", "Macro"),
            ("fundamental_eps.parquet", "EPS"),
            ("fundamental_revenue.parquet", "Revenue"),
        ]

        for filename, name in parquet_files:
            filepath = self.data_dir / filename
            if filepath.exists():
                try:
                    table = pq.read_table(filepath)
                    row_count = table.num_rows
                    col_count = table.num_columns
                    results.append(TestResult(
                        f"{name} Parquet Readable",
                        True,
                        f"{row_count} rows, {col_count} columns",
                        {"rows": row_count, "columns": col_count},
                    ))
                    print(f"   ✅ {filename}: {row_count} rows, {col_count} columns")
                except Exception as e:
                    results.append(TestResult(
                        f"{name} Parquet Readable",
                        False,
                        f"Read error: {e}",
                    ))
                    print(f"   ❌ {filename}: Read error - {e}")
            else:
                results.append(TestResult(
                    f"{name} Parquet Exists",
                    False,
                    "File not found",
                ))
                print(f"   ⚠️  {filename}: Not found")

        # 3.2 验证期权 Parquet 文件
        for symbol in self.symbols:
            option_dir = self.data_dir / "option_daily" / symbol
            if option_dir.exists():
                parquet_files = list(option_dir.glob("*.parquet"))
                total_rows = 0
                for pf in parquet_files:
                    try:
                        table = pq.read_table(pf)
                        total_rows += table.num_rows
                    except Exception:
                        pass

                results.append(TestResult(
                    f"{symbol} Option Parquet",
                    total_rows > 0,
                    f"{total_rows} rows in {len(parquet_files)} files",
                    {"rows": total_rows, "files": len(parquet_files)},
                ))
                print(f"   ✅ {symbol} Options: {total_rows} rows in {len(parquet_files)} files")
            else:
                results.append(TestResult(
                    f"{symbol} Option Parquet",
                    False,
                    "Directory not found",
                ))
                print(f"   ⚠️  {symbol} Options: Directory not found")

        # 3.3 验证数据范围合理性
        print("\n   --- Data Quality Validation ---")

        # 验证股票价格合理性
        stock_parquet = self.data_dir / "stock_daily.parquet"
        if stock_parquet.exists():
            try:
                import duckdb
                conn = duckdb.connect(":memory:")

                # 检查价格合理性
                invalid_prices = conn.execute(f"""
                    SELECT COUNT(*) FROM read_parquet('{stock_parquet}')
                    WHERE close <= 0 OR high < low OR open < low OR open > high
                """).fetchone()[0]

                if invalid_prices == 0:
                    results.append(TestResult(
                        "Stock Price Validity",
                        True,
                        "All prices valid (OHLC consistent)",
                    ))
                    print(f"   ✅ Stock prices: All valid (OHLC consistent)")
                else:
                    results.append(TestResult(
                        "Stock Price Validity",
                        False,
                        f"{invalid_prices} invalid price records",
                    ))
                    print(f"   ❌ Stock prices: {invalid_prices} invalid records")

                conn.close()
            except Exception as e:
                print(f"   ⚠️  Stock validation error: {e}")

        # 验证期权 Greeks 合理性
        for symbol in self.symbols:
            option_dir = self.data_dir / "option_daily" / symbol
            if option_dir.exists():
                parquet_files = list(option_dir.glob("*.parquet"))
                if parquet_files:
                    try:
                        import duckdb
                        conn = duckdb.connect(":memory:")

                        # 检查 Greeks 范围
                        parquet_list = ", ".join([f"'{pf}'" for pf in parquet_files])
                        invalid_greeks = conn.execute(f"""
                            SELECT COUNT(*) FROM read_parquet([{parquet_list}])
                            WHERE delta IS NOT NULL AND (
                                (option_type = 'call' AND (delta < 0 OR delta > 1)) OR
                                (option_type = 'put' AND (delta < -1 OR delta > 0))
                            )
                        """).fetchone()[0]

                        if invalid_greeks == 0:
                            results.append(TestResult(
                                f"{symbol} Greeks Validity",
                                True,
                                "All Greeks in valid range",
                            ))
                            print(f"   ✅ {symbol} Greeks: All valid")
                        else:
                            results.append(TestResult(
                                f"{symbol} Greeks Validity",
                                False,
                                f"{invalid_greeks} invalid Greeks records",
                            ))
                            print(f"   ❌ {symbol} Greeks: {invalid_greeks} invalid records")

                        conn.close()
                    except Exception as e:
                        print(f"   ⚠️  {symbol} Greeks validation error: {e}")

        return TestPhaseResult(phase_name="Integrity", results=results)


# ============================================================
# Main Test Runner
# ============================================================


def print_summary(results: list[TestPhaseResult], data_dir: Path) -> int:
    """打印测试摘要"""
    print(f"\n{'='*60}")
    print("Summary")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    for phase in results:
        passed = phase.passed_count
        failed = phase.failed_count
        total = phase.total_count
        total_passed += passed
        total_failed += failed

        status = "✅" if failed == 0 and phase.error is None else "❌"
        error_note = f" (Error: {phase.error})" if phase.error else ""

        print(f"   {status} {phase.phase_name}: {passed}/{total} passed{error_note}")

    print(f"\n   Total: {total_passed}/{total_passed + total_failed} tests passed")

    # 打印数据文件列表
    print(f"\n{'='*60}")
    print("Data Files")
    print("=" * 60)

    for item in sorted(data_dir.rglob("*.parquet")):
        size_kb = item.stat().st_size / 1024
        rel_path = item.relative_to(data_dir)
        print(f"   {rel_path} ({size_kb:.1f} KB)")

    print("=" * 60)

    return 0 if total_failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Verify data pipeline: Download -> Store (Parquet) -> Read (DuckDB)"
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        type=Path,
        default=Path("/Volumes/ORICO/option_quant/"),
        help="Data storage directory (default: /Volumes/ORICO/option_quant/)",
    )
    parser.add_argument(
        "--phase",
        "-p",
        choices=["download", "read", "integrity", "all"],
        default="all",
        help="Test phase to run (default: all)",
    )
    parser.add_argument(
        "--symbols",
        "-s",
        nargs="+",
        default=["GOOG", "SPY"],
        help="Symbols to test (default: GOOG SPY)",
    )
    parser.add_argument(
        "--stock-days",
        type=int,
        default=5,
        help="Number of days for stock/option data (default: 5)",
    )
    parser.add_argument(
        "--macro-days",
        type=int,
        default=30,
        help="Number of days for macro data (default: 30)",
    )
    parser.add_argument(
        "--ibkr-port",
        type=int,
        default=None,
        help="IBKR TWS/Gateway port (default: from env or 7497)",
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

    # 验证数据目录
    if not args.data_dir.parent.exists():
        print(f"❌ Error: Parent directory not found: {args.data_dir.parent}")
        print("   Please ensure the external drive is mounted.")
        return 1

    print("=" * 60)
    print("Data Pipeline Verification")
    print("=" * 60)
    print(f"\nDate: {date.today()}")
    print(f"Data Directory: {args.data_dir}")
    print(f"Symbols: {', '.join(args.symbols)}")
    print(f"Stock/Option Days: {args.stock_days}")
    print(f"Macro Days: {args.macro_days}")

    # 创建测试器
    tester = PipelineTester(
        data_dir=args.data_dir,
        symbols=args.symbols,
        stock_days=args.stock_days,
        macro_days=args.macro_days,
        ibkr_port=args.ibkr_port,
    )

    # 运行测试
    results: list[TestPhaseResult] = []

    if args.phase in ["download", "all"]:
        results.append(tester.test_download_phase())

    if args.phase in ["read", "all"]:
        results.append(tester.test_read_phase())

    if args.phase in ["integrity", "all"]:
        results.append(tester.test_integrity_phase())

    # 打印摘要
    return print_summary(results, args.data_dir)


if __name__ == "__main__":
    sys.exit(main())
