"""
DuckDB Schema - 回测数据表结构定义

定义股票和期权历史数据的表结构，支持 DuckDB 和 Parquet 存储。

表结构:
- stock_daily: 股票日线数据
- option_daily: 期权日线数据 (含 Greeks)

存储路径:
    data_dir/
    ├── stock_daily.parquet         # 所有股票的日线数据
    └── option_daily/               # 按标的分区的期权数据
        ├── AAPL/
        │   ├── 2020.parquet
        │   ├── 2021.parquet
        │   └── ...
        └── MSFT/
            └── ...
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal


@dataclass
class StockDailySchema:
    """股票日线数据 Schema

    对应 ThetaData /stock/history/eod 返回的数据。
    """

    # 主键
    symbol: str  # 股票代码, e.g., "AAPL"
    date: date  # 交易日期

    # OHLCV
    open: float
    high: float
    low: float
    close: float
    volume: int

    # 额外字段
    count: int = 0  # 成交笔数
    bid: float | None = None  # 收盘 bid
    ask: float | None = None  # 收盘 ask

    @classmethod
    def get_parquet_schema(cls) -> dict:
        """获取 PyArrow/Parquet 兼容的 schema"""
        return {
            "symbol": "string",
            "date": "date32",
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "int64",
            "count": "int32",
            "bid": "float64",
            "ask": "float64",
        }

    @classmethod
    def get_duckdb_create_table(cls, table_name: str = "stock_daily") -> str:
        """获取 DuckDB CREATE TABLE 语句"""
        return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            symbol VARCHAR NOT NULL,
            date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            count INTEGER,
            bid DOUBLE,
            ask DOUBLE,
            PRIMARY KEY (symbol, date)
        )
        """

    @classmethod
    def get_duckdb_indexes(cls, table_name: str = "stock_daily") -> list[str]:
        """获取 DuckDB 索引创建语句"""
        return [
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(date)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol ON {table_name}(symbol)",
        ]


@dataclass
class OptionDailySchema:
    """期权日线数据 Schema (含 Greeks)

    对应 ThetaData /option/history/greeks/eod 返回的数据。
    这是回测的核心数据结构。
    """

    # 主键 (合约标识)
    symbol: str  # 标的代码, e.g., "AAPL"
    expiration: date  # 到期日
    strike: float  # 行权价
    right: Literal["call", "put"]  # 期权类型
    date: date  # 数据日期

    # OHLCV
    open: float
    high: float
    low: float
    close: float
    volume: int
    count: int  # 成交笔数

    # Quote
    bid: float
    ask: float

    # Greeks (第一阶)
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float

    # IV
    implied_vol: float

    # 标的价格
    underlying_price: float

    # 可选字段
    open_interest: int | None = None
    iv_error: float | None = None

    @classmethod
    def get_parquet_schema(cls) -> dict:
        """获取 PyArrow/Parquet 兼容的 schema"""
        return {
            "symbol": "string",
            "expiration": "date32",
            "strike": "float64",
            "right": "string",  # "call" or "put"
            "date": "date32",
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "int64",
            "count": "int32",
            "bid": "float64",
            "ask": "float64",
            "delta": "float64",
            "gamma": "float64",
            "theta": "float64",
            "vega": "float64",
            "rho": "float64",
            "implied_vol": "float64",
            "underlying_price": "float64",
            "open_interest": "int64",
            "iv_error": "float64",
        }

    @classmethod
    def get_duckdb_create_table(cls, table_name: str = "option_daily") -> str:
        """获取 DuckDB CREATE TABLE 语句"""
        return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            symbol VARCHAR NOT NULL,
            expiration DATE NOT NULL,
            strike DOUBLE NOT NULL,
            right VARCHAR NOT NULL,
            date DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            count INTEGER,
            bid DOUBLE,
            ask DOUBLE,
            delta DOUBLE,
            gamma DOUBLE,
            theta DOUBLE,
            vega DOUBLE,
            rho DOUBLE,
            implied_vol DOUBLE,
            underlying_price DOUBLE,
            open_interest BIGINT,
            iv_error DOUBLE,
            PRIMARY KEY (symbol, expiration, strike, right, date)
        )
        """

    @classmethod
    def get_duckdb_indexes(cls, table_name: str = "option_daily") -> list[str]:
        """获取 DuckDB 索引创建语句"""
        return [
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(date)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol ON {table_name}(symbol)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_expiration ON {table_name}(expiration)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_symbol_date ON {table_name}(symbol, date)",
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_delta ON {table_name}(delta)",
        ]


def get_parquet_path(
    data_dir: Path | str,
    data_type: Literal["stock", "option"],
    symbol: str | None = None,
    year: int | None = None,
) -> Path:
    """获取 Parquet 文件路径

    Args:
        data_dir: 数据根目录
        data_type: 数据类型 ("stock" 或 "option")
        symbol: 标的代码 (option 必须)
        year: 年份 (option 可选)

    Returns:
        Parquet 文件路径

    Examples:
        >>> get_parquet_path("/data", "stock")
        Path("/data/stock_daily.parquet")

        >>> get_parquet_path("/data", "option", "AAPL", 2024)
        Path("/data/option_daily/AAPL/2024.parquet")
    """
    data_dir = Path(data_dir)

    if data_type == "stock":
        return data_dir / "stock_daily.parquet"

    elif data_type == "option":
        if symbol is None:
            raise ValueError("symbol is required for option data")

        option_dir = data_dir / "option_daily" / symbol.upper()

        if year:
            return option_dir / f"{year}.parquet"
        else:
            return option_dir

    else:
        raise ValueError(f"Unknown data_type: {data_type}")


def init_duckdb_schema(conn) -> None:
    """初始化 DuckDB 表结构

    Args:
        conn: DuckDB 连接对象

    Usage:
        import duckdb
        conn = duckdb.connect("backtest.duckdb")
        init_duckdb_schema(conn)
    """
    # 创建股票表
    conn.execute(StockDailySchema.get_duckdb_create_table())
    for idx_sql in StockDailySchema.get_duckdb_indexes():
        conn.execute(idx_sql)

    # 创建期权表
    conn.execute(OptionDailySchema.get_duckdb_create_table())
    for idx_sql in OptionDailySchema.get_duckdb_indexes():
        conn.execute(idx_sql)


def load_parquet_to_duckdb(
    conn,
    data_dir: Path | str,
    symbols: list[str] | None = None,
) -> None:
    """将 Parquet 文件加载到 DuckDB

    Args:
        conn: DuckDB 连接对象
        data_dir: 数据根目录
        symbols: 要加载的标的列表 (None 表示全部)

    Usage:
        conn = duckdb.connect("backtest.duckdb")
        init_duckdb_schema(conn)
        load_parquet_to_duckdb(conn, "/Volumes/TradingData/processed")
    """
    data_dir = Path(data_dir)

    # 加载股票数据
    stock_path = get_parquet_path(data_dir, "stock")
    if stock_path.exists():
        conn.execute(f"""
            INSERT INTO stock_daily
            SELECT * FROM read_parquet('{stock_path}')
            ON CONFLICT DO NOTHING
        """)

    # 加载期权数据
    option_base = data_dir / "option_daily"
    if option_base.exists():
        # 确定要加载的标的
        if symbols:
            symbol_dirs = [option_base / s.upper() for s in symbols]
            symbol_dirs = [d for d in symbol_dirs if d.exists()]
        else:
            symbol_dirs = [d for d in option_base.iterdir() if d.is_dir()]

        for symbol_dir in symbol_dirs:
            parquet_files = list(symbol_dir.glob("*.parquet"))
            for pf in parquet_files:
                conn.execute(f"""
                    INSERT INTO option_daily
                    SELECT * FROM read_parquet('{pf}')
                    ON CONFLICT DO NOTHING
                """)
