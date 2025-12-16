"""Data type and market enumerations for routing."""

from enum import Enum


class DataType(Enum):
    """Data type enumeration for routing decisions."""

    STOCK_QUOTE = "stock_quote"
    STOCK_QUOTES = "stock_quotes"
    HISTORY_KLINE = "history_kline"
    OPTION_CHAIN = "option_chain"
    OPTION_QUOTE = "option_quote"
    OPTION_QUOTES = "option_quotes"
    FUNDAMENTAL = "fundamental"
    MACRO_DATA = "macro_data"


class Market(Enum):
    """Market type enumeration."""

    US = "us"  # United States
    HK = "hk"  # Hong Kong
    CN = "cn"  # China mainland (Shanghai/Shenzhen)
