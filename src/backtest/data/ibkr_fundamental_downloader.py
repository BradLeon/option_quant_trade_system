"""
IBKR Fundamental Data Downloader

从 IBKR TWS API 下载历史基本面数据并保存为 Parquet 文件。
支持 EPS、Revenue、Dividends 等财务数据。

数据来源: IBKR reqFundamentalData API (ReportsFinSummary)

Usage:
    downloader = IBKRFundamentalDownloader(data_dir="data/backtest")

    # 下载单个股票
    downloader.download_symbol("AAPL")

    # 批量下载
    downloader.download_symbols(["AAPL", "MSFT", "GOOGL"])
"""

import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


@dataclass
class EPSRecord:
    """EPS 数据记录"""

    symbol: str
    as_of_date: date
    report_type: str  # TTM, P (Preliminary), R (Reported), A (Actual)
    period: str  # 3M, 12M
    eps: float
    currency: str = "USD"


@dataclass
class RevenueRecord:
    """营收数据记录"""

    symbol: str
    as_of_date: date
    report_type: str  # TTM, P, R, A
    period: str  # 3M, 12M
    revenue: float
    currency: str = "USD"


@dataclass
class DividendRecord:
    """股息数据记录"""

    symbol: str
    ex_date: date
    record_date: date | None
    pay_date: date | None
    declaration_date: date | None
    dividend_type: str  # CD (Cash Dividend)
    amount: float
    currency: str = "USD"


@dataclass
class FundamentalData:
    """汇总的基本面数据"""

    symbol: str
    eps_records: list[EPSRecord] = field(default_factory=list)
    revenue_records: list[RevenueRecord] = field(default_factory=list)
    dividend_records: list[DividendRecord] = field(default_factory=list)
    raw_xml: str | None = None


class XMLParser:
    """解析 IBKR ReportsFinSummary XML"""

    @staticmethod
    def parse_date(date_str: str | None) -> date | None:
        """解析日期字符串"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    @classmethod
    def parse_fin_summary(cls, symbol: str, xml_str: str) -> FundamentalData:
        """解析 ReportsFinSummary XML

        Args:
            symbol: 股票代码
            xml_str: XML 字符串

        Returns:
            FundamentalData 对象
        """
        result = FundamentalData(symbol=symbol, raw_xml=xml_str)

        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML for {symbol}: {e}")
            return result

        # 解析 EPS
        eps_section = root.find(".//EPSs")
        if eps_section is not None:
            currency = eps_section.get("currency", "USD")
            for eps_elem in eps_section.findall("EPS"):
                as_of_date = cls.parse_date(eps_elem.get("asofDate"))
                if as_of_date is None:
                    continue

                try:
                    eps_value = float(eps_elem.text or 0)
                except (ValueError, TypeError):
                    continue

                record = EPSRecord(
                    symbol=symbol,
                    as_of_date=as_of_date,
                    report_type=eps_elem.get("reportType", ""),
                    period=eps_elem.get("period", ""),
                    eps=eps_value,
                    currency=currency,
                )
                result.eps_records.append(record)

        # 解析 Revenue
        revenue_section = root.find(".//TotalRevenues")
        if revenue_section is not None:
            currency = revenue_section.get("currency", "USD")
            for rev_elem in revenue_section.findall("TotalRevenue"):
                as_of_date = cls.parse_date(rev_elem.get("asofDate"))
                if as_of_date is None:
                    continue

                try:
                    rev_value = float(rev_elem.text or 0)
                except (ValueError, TypeError):
                    continue

                record = RevenueRecord(
                    symbol=symbol,
                    as_of_date=as_of_date,
                    report_type=rev_elem.get("reportType", ""),
                    period=rev_elem.get("period", ""),
                    revenue=rev_value,
                    currency=currency,
                )
                result.revenue_records.append(record)

        # 解析 Dividends
        div_section = root.find(".//Dividends")
        if div_section is not None:
            currency = div_section.get("currency", "USD")
            for div_elem in div_section.findall("Dividend"):
                ex_date = cls.parse_date(div_elem.get("exDate"))
                if ex_date is None:
                    continue

                try:
                    div_amount = float(div_elem.text or 0)
                except (ValueError, TypeError):
                    continue

                record = DividendRecord(
                    symbol=symbol,
                    ex_date=ex_date,
                    record_date=cls.parse_date(div_elem.get("recordDate")),
                    pay_date=cls.parse_date(div_elem.get("payDate")),
                    declaration_date=cls.parse_date(div_elem.get("declarationDate")),
                    dividend_type=div_elem.get("type", "CD"),
                    amount=div_amount,
                    currency=currency,
                )
                result.dividend_records.append(record)

        return result


class IBKRFundamentalDownloader:
    """IBKR 基本面数据下载器

    从 IBKR TWS API 下载历史基本面数据并保存为 Parquet 文件。

    Features:
    - 支持批量下载多个股票
    - 自动解析 XML 并提取关键财务数据
    - 保存为 Parquet 格式，便于 DuckDB 查询
    - 支持增量更新
    """

    def __init__(
        self,
        data_dir: Path | str,
        host: str = "127.0.0.1",
        port: int | None = None,
        client_id: int = 97,
    ) -> None:
        """初始化下载器

        Args:
            data_dir: 数据存储目录
            host: TWS/Gateway 主机地址
            port: TWS/Gateway 端口 (默认从环境变量读取，或使用 7497)
            client_id: API 客户端 ID
        """
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._host = host
        self._port = port or int(os.getenv("IBKR_PORT", "7497"))
        self._client_id = client_id

        self._ib = None

    def _get_eps_parquet_path(self) -> Path:
        """EPS 数据 Parquet 路径"""
        return self._data_dir / "fundamental_eps.parquet"

    def _get_revenue_parquet_path(self) -> Path:
        """Revenue 数据 Parquet 路径"""
        return self._data_dir / "fundamental_revenue.parquet"

    def _get_dividend_parquet_path(self) -> Path:
        """Dividend 数据 Parquet 路径"""
        return self._data_dir / "fundamental_dividend.parquet"

    async def _connect(self) -> bool:
        """连接到 IBKR"""
        try:
            from ib_async import IB

            logger.info(f"   Connecting to IBKR at {self._host}:{self._port}...")
            self._ib = IB()
            await self._ib.connectAsync(
                self._host, self._port, clientId=self._client_id
            )
            logger.info(f"   ✅ Connected to IBKR")
            return True
        except Exception as e:
            logger.error(f"   ❌ Failed to connect to IBKR: {e}")
            return False

    def _disconnect(self) -> None:
        """断开 IBKR 连接"""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            logger.info("   Disconnected from IBKR")

    async def _fetch_fundamental_data(self, symbol: str) -> FundamentalData | None:
        """获取单个股票的基本面数据

        Args:
            symbol: 股票代码

        Returns:
            FundamentalData 或 None
        """
        if not self._ib or not self._ib.isConnected():
            logger.error("Not connected to IBKR")
            return None

        try:
            from ib_async import Stock

            # 创建合约
            logger.info(f"   Qualifying contract for {symbol}...")
            contract = Stock(symbol, "SMART", "USD")

            # 确认合约
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                logger.warning(f"   ❌ Failed to qualify contract for {symbol}")
                return None

            contract = qualified[0]
            logger.info(f"   ✅ Contract qualified: {contract.symbol}")

            # 请求 ReportsFinSummary
            logger.info(f"   Requesting fundamental data (ReportsFinSummary)...")
            xml_data = await self._ib.reqFundamentalDataAsync(
                contract, reportType="ReportsFinSummary"
            )

            if not xml_data:
                logger.warning(f"   ❌ No fundamental data returned for {symbol}")
                return None

            logger.info(f"   ✅ Received {len(xml_data):,} bytes of XML data")

            # 解析 XML
            logger.info(f"   Parsing XML data...")
            result = XMLParser.parse_fin_summary(symbol, xml_data)
            logger.info(
                f"   ✅ Parsed: {len(result.eps_records)} EPS, "
                f"{len(result.revenue_records)} Revenue, "
                f"{len(result.dividend_records)} Dividend records"
            )
            return result

        except Exception as e:
            logger.error(f"   ❌ Error fetching fundamental data for {symbol}: {e}")
            return None

    async def download_symbol_async(self, symbol: str) -> FundamentalData | None:
        """异步下载单个股票的基本面数据

        Args:
            symbol: 股票代码

        Returns:
            FundamentalData 或 None
        """
        connected = await self._connect()
        if not connected:
            return None

        try:
            return await self._fetch_fundamental_data(symbol)
        finally:
            self._disconnect()

    def download_symbol(self, symbol: str) -> FundamentalData | None:
        """下载单个股票的基本面数据 (同步接口)

        Args:
            symbol: 股票代码

        Returns:
            FundamentalData 或 None
        """
        return asyncio.run(self.download_symbol_async(symbol))

    async def download_symbols_async(
        self,
        symbols: list[str],
        on_progress: Callable[[str, int, int], None] | None = None,
        delay: float = 1.0,
    ) -> dict[str, FundamentalData]:
        """异步批量下载多个股票的基本面数据

        Args:
            symbols: 股票代码列表
            on_progress: 进度回调 (symbol, current, total)
            delay: 请求间隔（秒）

        Returns:
            {symbol: FundamentalData} 字典
        """
        connected = await self._connect()
        if not connected:
            return {}

        results = {}
        total = len(symbols)

        try:
            for i, symbol in enumerate(symbols):
                if on_progress:
                    on_progress(symbol, i + 1, total)

                logger.info(f"[{i + 1}/{total}] Downloading {symbol}...")

                data = await self._fetch_fundamental_data(symbol)
                if data:
                    results[symbol] = data

                # 请求间隔
                if i < total - 1:
                    await asyncio.sleep(delay)

        finally:
            self._disconnect()

        return results

    def download_symbols(
        self,
        symbols: list[str],
        on_progress: Callable[[str, int, int], None] | None = None,
        delay: float = 1.0,
    ) -> dict[str, FundamentalData]:
        """批量下载多个股票的基本面数据 (同步接口)

        Args:
            symbols: 股票代码列表
            on_progress: 进度回调
            delay: 请求间隔

        Returns:
            {symbol: FundamentalData} 字典
        """
        return asyncio.run(
            self.download_symbols_async(symbols, on_progress, delay)
        )

    def save_to_parquet(
        self,
        data: dict[str, FundamentalData],
        append: bool = True,
    ) -> dict[str, int]:
        """保存基本面数据为 Parquet 文件

        Args:
            data: {symbol: FundamentalData} 字典
            append: 是否追加到现有文件

        Returns:
            {data_type: record_count} 保存的记录数
        """
        # 收集所有记录
        all_eps: list[EPSRecord] = []
        all_revenue: list[RevenueRecord] = []
        all_dividend: list[DividendRecord] = []

        for fund_data in data.values():
            all_eps.extend(fund_data.eps_records)
            all_revenue.extend(fund_data.revenue_records)
            all_dividend.extend(fund_data.dividend_records)

        saved_counts = {}

        # 保存 EPS
        if all_eps:
            count = self._save_eps_parquet(all_eps, append)
            saved_counts["eps"] = count

        # 保存 Revenue
        if all_revenue:
            count = self._save_revenue_parquet(all_revenue, append)
            saved_counts["revenue"] = count

        # 保存 Dividend
        if all_dividend:
            count = self._save_dividend_parquet(all_dividend, append)
            saved_counts["dividend"] = count

        return saved_counts

    def _save_eps_parquet(self, records: list[EPSRecord], append: bool) -> int:
        """保存 EPS 数据"""
        parquet_path = self._get_eps_parquet_path()

        data = {
            "symbol": [r.symbol for r in records],
            "as_of_date": [r.as_of_date for r in records],
            "report_type": [r.report_type for r in records],
            "period": [r.period for r in records],
            "eps": [r.eps for r in records],
            "currency": [r.currency for r in records],
        }

        new_table = pa.Table.from_pydict(data)

        if append and parquet_path.exists():
            existing_table = pq.read_table(parquet_path)
            combined = pa.concat_tables([existing_table, new_table])

            # 去重
            df = combined.to_pandas()
            df = df.drop_duplicates(
                subset=["symbol", "as_of_date", "report_type", "period"],
                keep="last",
            )
            df = df.sort_values(["symbol", "as_of_date", "report_type"])
            new_table = pa.Table.from_pandas(df, preserve_index=False)

        pq.write_table(new_table, parquet_path)
        logger.info(f"Saved {len(new_table)} EPS records to {parquet_path}")
        return len(new_table)

    def _save_revenue_parquet(self, records: list[RevenueRecord], append: bool) -> int:
        """保存 Revenue 数据"""
        parquet_path = self._get_revenue_parquet_path()

        data = {
            "symbol": [r.symbol for r in records],
            "as_of_date": [r.as_of_date for r in records],
            "report_type": [r.report_type for r in records],
            "period": [r.period for r in records],
            "revenue": [r.revenue for r in records],
            "currency": [r.currency for r in records],
        }

        new_table = pa.Table.from_pydict(data)

        if append and parquet_path.exists():
            existing_table = pq.read_table(parquet_path)
            combined = pa.concat_tables([existing_table, new_table])

            # 去重
            df = combined.to_pandas()
            df = df.drop_duplicates(
                subset=["symbol", "as_of_date", "report_type", "period"],
                keep="last",
            )
            df = df.sort_values(["symbol", "as_of_date", "report_type"])
            new_table = pa.Table.from_pandas(df, preserve_index=False)

        pq.write_table(new_table, parquet_path)
        logger.info(f"Saved {len(new_table)} Revenue records to {parquet_path}")
        return len(new_table)

    def _save_dividend_parquet(self, records: list[DividendRecord], append: bool) -> int:
        """保存 Dividend 数据"""
        parquet_path = self._get_dividend_parquet_path()

        data = {
            "symbol": [r.symbol for r in records],
            "ex_date": [r.ex_date for r in records],
            "record_date": [r.record_date for r in records],
            "pay_date": [r.pay_date for r in records],
            "declaration_date": [r.declaration_date for r in records],
            "dividend_type": [r.dividend_type for r in records],
            "amount": [r.amount for r in records],
            "currency": [r.currency for r in records],
        }

        new_table = pa.Table.from_pydict(data)

        if append and parquet_path.exists():
            existing_table = pq.read_table(parquet_path)
            combined = pa.concat_tables([existing_table, new_table])

            # 去重
            df = combined.to_pandas()
            df = df.drop_duplicates(
                subset=["symbol", "ex_date"],
                keep="last",
            )
            df = df.sort_values(["symbol", "ex_date"])
            new_table = pa.Table.from_pandas(df, preserve_index=False)

        pq.write_table(new_table, parquet_path)
        logger.info(f"Saved {len(new_table)} Dividend records to {parquet_path}")
        return len(new_table)

    def download_and_save(
        self,
        symbols: list[str],
        on_progress: Callable[[str, int, int], None] | None = None,
        delay: float = 1.0,
    ) -> dict[str, int]:
        """下载并保存基本面数据 (一体化接口)

        Args:
            symbols: 股票代码列表
            on_progress: 进度回调
            delay: 请求间隔

        Returns:
            {data_type: record_count} 保存的记录数
        """
        data = self.download_symbols(symbols, on_progress, delay)
        if not data:
            return {}

        result = self.save_to_parquet(data)

        # 更新数据目录
        self._update_catalog()

        return result

    def _update_catalog(self) -> None:
        """更新数据目录（如果 DataDownloader 可用）"""
        try:
            from src.backtest.data.data_downloader import DataDownloader
            downloader = DataDownloader(data_dir=self._data_dir)
            downloader.update_catalog()
        except Exception as e:
            logger.debug(f"Catalog update skipped: {e}")

    def get_available_symbols(self) -> list[str]:
        """获取已下载的股票列表"""
        eps_path = self._get_eps_parquet_path()
        if not eps_path.exists():
            return []

        try:
            import duckdb

            conn = duckdb.connect(":memory:")
            result = conn.execute(
                f"SELECT DISTINCT symbol FROM read_parquet('{eps_path}') ORDER BY symbol"
            ).fetchall()
            return [r[0] for r in result]
        except Exception as e:
            logger.error(f"Failed to get available symbols: {e}")
            return []

    def get_eps_date_range(self, symbol: str) -> tuple[date, date] | None:
        """获取股票的 EPS 数据日期范围"""
        eps_path = self._get_eps_parquet_path()
        if not eps_path.exists():
            return None

        try:
            import duckdb

            conn = duckdb.connect(":memory:")
            result = conn.execute(
                f"""
                SELECT MIN(as_of_date), MAX(as_of_date)
                FROM read_parquet('{eps_path}')
                WHERE symbol = ?
                """,
                [symbol],
            ).fetchone()

            if result and result[0] and result[1]:
                return result[0], result[1]
            return None
        except Exception as e:
            logger.error(f"Failed to get EPS date range: {e}")
            return None
