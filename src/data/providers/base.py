"""Abstract base class for data providers."""

from abc import ABC, abstractmethod
from datetime import date
from typing import Protocol

from src.data.models import (
    Fundamental,
    KlineBar,
    MacroData,
    OptionChain,
    OptionQuote,
    StockQuote,
)
from src.data.models.stock import KlineType


class DataProvider(ABC):
    """Abstract base class for market data providers.

    All data provider implementations must inherit from this class
    and implement the required methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'futu', 'yahoo')."""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available and connected."""
        pass

    # Stock Data Methods

    @abstractmethod
    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """Get real-time stock quote.

        Args:
            symbol: Stock symbol (e.g., 'AAPL', 'US.AAPL').

        Returns:
            StockQuote instance or None if not available.
        """
        pass

    @abstractmethod
    def get_stock_quotes(self, symbols: list[str]) -> list[StockQuote]:
        """Get real-time quotes for multiple stocks.

        Args:
            symbols: List of stock symbols.

        Returns:
            List of StockQuote instances.
        """
        pass

    @abstractmethod
    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """Get historical K-line data.

        Args:
            symbol: Stock symbol.
            ktype: K-line type (day, 1min, etc.).
            start_date: Start date for historical data.
            end_date: End date for historical data.

        Returns:
            List of KlineBar instances sorted by timestamp.
        """
        pass

    # Option Data Methods

    @abstractmethod
    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
    ) -> OptionChain | None:
        """Get option chain for an underlying asset.

        Args:
            underlying: Underlying stock symbol.
            expiry_start: Optional start date for expiry filter.
            expiry_end: Optional end date for expiry filter.

        Returns:
            OptionChain instance or None if not available.
        """
        pass

    @abstractmethod
    def get_option_quote(self, symbol: str) -> OptionQuote | None:
        """Get quote for a specific option contract.

        Args:
            symbol: Option symbol.

        Returns:
            OptionQuote instance or None if not available.
        """
        pass

    # Fundamental Data Methods

    @abstractmethod
    def get_fundamental(self, symbol: str) -> Fundamental | None:
        """Get fundamental data for a stock.

        Args:
            symbol: Stock symbol.

        Returns:
            Fundamental instance or None if not available.
        """
        pass

    # Macro Data Methods

    @abstractmethod
    def get_macro_data(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroData]:
        """Get macro economic data.

        Args:
            indicator: Macro indicator symbol (e.g., ^VIX, ^TNX).
            start_date: Start date for data.
            end_date: End date for data.

        Returns:
            List of MacroData instances sorted by date.
        """
        pass

    # Utility Methods

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for this provider.

        Override in subclass if provider uses different format.

        Args:
            symbol: Stock symbol in any format.

        Returns:
            Symbol in provider-specific format.
        """
        return symbol.upper()


class DataProviderError(Exception):
    """Base exception for data provider errors."""

    pass


class ConnectionError(DataProviderError):
    """Connection-related errors."""

    pass


class RateLimitError(DataProviderError):
    """Rate limit exceeded errors."""

    pass


class DataNotFoundError(DataProviderError):
    """Data not found errors."""

    pass
