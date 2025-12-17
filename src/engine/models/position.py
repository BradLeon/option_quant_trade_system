"""Position model for portfolio calculations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.data.models.option import Greeks

if TYPE_CHECKING:
    from src.data.models.fundamental import Fundamental
    from src.data.models.option import OptionQuote
    from src.data.models.stock import StockQuote


class Position:
    """Position information for portfolio calculations.

    Uses composition pattern for Greeks (delta, gamma, theta, vega, rho).
    Property accessors provide convenient access to individual Greek values.

    Attributes:
        symbol: The ticker symbol of the position.
        quantity: Number of contracts (positive for long, negative for short).
        greeks: Greeks object containing delta, gamma, theta, vega, rho.
        beta: Beta of the underlying stock relative to SPY/market.
              Data source: Yahoo Finance provider.get_fundamental(symbol).beta
        market_value: Current market value of the option position.
        underlying_price: Current price of the underlying stock.
                         Required for delta_dollars and beta_weighted_delta.
        contract_multiplier: Shares per contract (US equity = 100, HK varies e.g. 500).
        margin: Margin requirement for this position.
        dte: Days to expiration. Used for PREI calculation.

    Example:
        >>> pos = Position(
        ...     symbol="AAPL",
        ...     quantity=1,
        ...     greeks=Greeks(delta=0.5, gamma=0.02, theta=-0.05, vega=0.30)
        ... )
        >>> pos.delta  # Convenience accessor
        0.5
    """

    def __init__(
        self,
        symbol: str,
        quantity: float,
        greeks: Greeks | None = None,
        beta: float | None = None,
        market_value: float | None = None,
        underlying_price: float | None = None,
        contract_multiplier: int = 100,
        margin: float | None = None,
        dte: int | None = None,
    ):
        """Initialize Position.

        Args:
            symbol: Ticker symbol
            quantity: Number of contracts
            greeks: Greeks object containing delta, gamma, theta, vega, rho
            beta: Stock beta relative to market
            market_value: Current market value
            underlying_price: Underlying stock price
            contract_multiplier: Shares per contract (default 100)
            margin: Margin requirement
            dte: Days to expiration
        """
        self.symbol = symbol
        self.quantity = quantity
        self.beta = beta
        self.market_value = market_value
        self.underlying_price = underlying_price
        self.contract_multiplier = contract_multiplier
        self.margin = margin
        self.dte = dte
        self._greeks = greeks if greeks is not None else Greeks()

    @property
    def greeks(self) -> Greeks:
        """Get the Greeks object."""
        return self._greeks

    @greeks.setter
    def greeks(self, value: Greeks):
        """Set the Greeks object."""
        self._greeks = value

    @property
    def delta(self) -> float | None:
        """Position delta per share (sensitivity to $1 move in underlying)."""
        return self._greeks.delta

    @delta.setter
    def delta(self, value: float | None):
        """Set delta value."""
        self._greeks = Greeks(
            delta=value,
            gamma=self._greeks.gamma,
            theta=self._greeks.theta,
            vega=self._greeks.vega,
            rho=self._greeks.rho,
        )

    @property
    def gamma(self) -> float | None:
        """Position gamma per share (rate of change of delta)."""
        return self._greeks.gamma

    @gamma.setter
    def gamma(self, value: float | None):
        """Set gamma value."""
        self._greeks = Greeks(
            delta=self._greeks.delta,
            gamma=value,
            theta=self._greeks.theta,
            vega=self._greeks.vega,
            rho=self._greeks.rho,
        )

    @property
    def theta(self) -> float | None:
        """Position theta per share (time decay per day)."""
        return self._greeks.theta

    @theta.setter
    def theta(self, value: float | None):
        """Set theta value."""
        self._greeks = Greeks(
            delta=self._greeks.delta,
            gamma=self._greeks.gamma,
            theta=value,
            vega=self._greeks.vega,
            rho=self._greeks.rho,
        )

    @property
    def vega(self) -> float | None:
        """Position vega per share (sensitivity to 1% volatility change)."""
        return self._greeks.vega

    @vega.setter
    def vega(self, value: float | None):
        """Set vega value."""
        self._greeks = Greeks(
            delta=self._greeks.delta,
            gamma=self._greeks.gamma,
            theta=self._greeks.theta,
            vega=value,
            rho=self._greeks.rho,
        )

    @property
    def rho(self) -> float | None:
        """Position rho (sensitivity to interest rate changes)."""
        return self._greeks.rho

    @rho.setter
    def rho(self, value: float | None):
        """Set rho value."""
        self._greeks = Greeks(
            delta=self._greeks.delta,
            gamma=self._greeks.gamma,
            theta=self._greeks.theta,
            vega=self._greeks.vega,
            rho=value,
        )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Position(symbol={self.symbol!r}, quantity={self.quantity}, "
            f"greeks={self._greeks!r}, beta={self.beta}, "
            f"market_value={self.market_value}, underlying_price={self.underlying_price}, "
            f"contract_multiplier={self.contract_multiplier}, margin={self.margin}, "
            f"dte={self.dte})"
        )

    def __eq__(self, other: object) -> bool:
        """Check equality."""
        if not isinstance(other, Position):
            return NotImplemented
        return (
            self.symbol == other.symbol
            and self.quantity == other.quantity
            and self._greeks == other._greeks
            and self.beta == other.beta
            and self.market_value == other.market_value
            and self.underlying_price == other.underlying_price
            and self.contract_multiplier == other.contract_multiplier
            and self.margin == other.margin
            and self.dte == other.dte
        )

    @classmethod
    def from_market_data(
        cls,
        option_quote: OptionQuote,
        quantity: float,
        stock_quote: StockQuote | None = None,
        fundamental: Fundamental | None = None,
        margin: float | None = None,
    ) -> Position:
        """Create Position from market data objects.

        Factory method that extracts data from data layer models to create
        a Position instance with all available information populated.

        Args:
            option_quote: OptionQuote with contract info, greeks, and IV.
            quantity: Number of contracts (positive=long, negative=short).
            stock_quote: Optional StockQuote for underlying price.
            fundamental: Optional Fundamental for beta.
            margin: Optional margin requirement override.

        Returns:
            Position instance with data extracted from market sources.

        Example:
            >>> from src.data.providers.yahoo import YahooFinanceProvider
            >>> provider = YahooFinanceProvider()
            >>> quote = provider.get_option_quote("AAPL", ...)
            >>> stock = provider.get_stock_quote("AAPL")
            >>> fund = provider.get_fundamental("AAPL")
            >>> pos = Position.from_market_data(quote, 1, stock, fund)
        """
        contract = option_quote.contract

        # Extract Greeks from option quote
        greeks = option_quote.greeks if option_quote.greeks else Greeks()

        # Extract underlying price from stock quote
        underlying_price = None
        if stock_quote is not None and stock_quote.close is not None:
            underlying_price = stock_quote.close

        # Extract beta from fundamental
        beta = None
        if fundamental is not None:
            beta = fundamental.beta

        # Calculate market value from option quote
        market_value = None
        mid_price = option_quote.mid_price
        if mid_price is not None:
            market_value = mid_price * contract.lot_size * abs(quantity)

        # Get DTE from contract
        dte = contract.days_to_expiry if contract else None

        return cls(
            symbol=contract.symbol,
            quantity=quantity,
            greeks=greeks,
            beta=beta,
            market_value=market_value,
            underlying_price=underlying_price,
            contract_multiplier=contract.lot_size,
            margin=margin,
            dte=dte,
        )
