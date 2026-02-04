"""Abstract base class for data providers."""

from abc import ABC, abstractmethod
from datetime import date
from typing import Protocol

from src.data.models import (
    AccountCash,
    AccountPosition,
    AccountSummary,
    AccountType,
    Fundamental,
    KlineBar,
    MacroData,
    OptionChain,
    OptionQuote,
    StockQuote,
    StockVolatility,
)
from src.data.models.option import OptionContract
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

    # Batch Option Methods

    @abstractmethod
    def get_option_quotes_batch(
        self,
        contracts: list[OptionContract],
        min_volume: int | None = None,
    ) -> list[OptionQuote]:
        """Get quotes for multiple option contracts.

        Args:
            contracts: List of OptionContract instances to query.
            min_volume: Optional minimum volume filter.

        Returns:
            List of OptionQuote instances for matching contracts.
        """
        pass

    # Screening Support Methods (optional implementations)

    def check_macro_blackout(
        self,
        target_date: date | None = None,
        blackout_days: int = 2,
        blackout_events: list[str] | None = None,
    ) -> tuple[bool, list]:
        """Check if date is in macro event blackout period.

        This is an optional method with a default implementation that
        returns (False, []) - i.e., no blackout. Subclasses can override
        to provide actual blackout checking using economic calendars.

        Args:
            target_date: Date to check. Defaults to current date.
            blackout_days: Number of days before/after event to blackout.
            blackout_events: List of event types to check (e.g., 'FOMC', 'CPI').

        Returns:
            Tuple of (is_blackout, list of upcoming events).
        """
        return False, []

    def get_stock_volatility(self, symbol: str) -> StockVolatility | None:
        """Get stock-level volatility metrics (IV/HV).

        This is an optional method with a default implementation that
        returns None. Subclasses can override to calculate HV from
        historical prices and estimate IV from option data.

        Args:
            symbol: Stock symbol.

        Returns:
            StockVolatility instance or None if not available.
        """
        return None

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


class AccountProvider(ABC):
    """Abstract base class for account/trading data providers.

    This is a mixin interface for providers that support
    account and position queries. Providers implementing this
    interface can fetch positions, cash balances, and account summaries.

    Note:
        Trading methods (place_order, cancel_order) are placeholders
        and raise NotImplementedError. Only read operations are supported.
    """

    @abstractmethod
    def get_account_summary(
        self,
        account_type: AccountType = AccountType.PAPER,
    ) -> AccountSummary | None:
        """Get account summary information.

        Args:
            account_type: Real or paper account.

        Returns:
            AccountSummary instance or None if not available.
        """
        pass

    @abstractmethod
    def get_positions(
        self,
        account_type: AccountType = AccountType.PAPER,
        fetch_greeks: bool = True,
    ) -> list[AccountPosition]:
        """Get all positions in the account.

        Args:
            account_type: Real or paper account.
            fetch_greeks: Whether to fetch Greeks for option positions.
                Set to False when using a centralized Greeks fetcher.

        Returns:
            List of AccountPosition instances.
        """
        pass

    @abstractmethod
    def get_cash_balances(
        self,
        account_type: AccountType = AccountType.PAPER,
    ) -> list[AccountCash]:
        """Get cash balances by currency.

        Args:
            account_type: Real or paper account.

        Returns:
            List of AccountCash instances.
        """
        pass

    # Trading placeholders (not implemented)

    def place_order(self, *args, **kwargs) -> None:
        """Place an order (not implemented).

        Raises:
            NotImplementedError: Trading is not implemented.
        """
        raise NotImplementedError("Trading not implemented. Read-only mode.")

    def cancel_order(self, *args, **kwargs) -> None:
        """Cancel an order (not implemented).

        Raises:
            NotImplementedError: Trading is not implemented.
        """
        raise NotImplementedError("Trading not implemented. Read-only mode.")
