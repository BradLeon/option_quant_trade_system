"""Backtest data module - ThetaData client, downloader, DuckDB provider."""

from src.backtest.data.thetadata_client import (
    ThetaDataClient,
    ThetaDataConfig,
    ThetaDataError,
    StockEOD,
    OptionEOD,
    OptionEODGreeks,
)
from src.backtest.data.schema import (
    StockDailySchema,
    OptionDailySchema,
    get_parquet_path,
    init_duckdb_schema,
)
from src.backtest.data.data_downloader import DataDownloader, DownloadProgress
from src.backtest.data.macro_downloader import MacroDownloader, MacroEOD, DEFAULT_MACRO_INDICATORS
from src.backtest.data.ibkr_fundamental_downloader import (
    IBKRFundamentalDownloader,
    XMLParser,
    FundamentalData,
    EPSRecord,
    RevenueRecord,
    DividendRecord,
)
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.data.greeks_calculator import (
    GreeksCalculator,
    GreeksResult,
    OptionWithGreeks,
)

__all__ = [
    # ThetaData
    "ThetaDataClient",
    "ThetaDataConfig",
    "ThetaDataError",
    "StockEOD",
    "OptionEOD",
    "OptionEODGreeks",
    # Schema
    "StockDailySchema",
    "OptionDailySchema",
    "get_parquet_path",
    "init_duckdb_schema",
    # Downloader
    "DataDownloader",
    "DownloadProgress",
    # Macro Downloader
    "MacroDownloader",
    "MacroEOD",
    "DEFAULT_MACRO_INDICATORS",
    # IBKR Fundamental Downloader
    "IBKRFundamentalDownloader",
    "XMLParser",
    "FundamentalData",
    "EPSRecord",
    "RevenueRecord",
    "DividendRecord",
    # Provider
    "DuckDBProvider",
    # Greeks Calculator
    "GreeksCalculator",
    "GreeksResult",
    "OptionWithGreeks",
]
