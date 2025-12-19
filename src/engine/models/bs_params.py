"""Black-Scholes calculation parameters."""

from dataclasses import dataclass

from src.data.models import MacroData, OptionQuote, StockQuote
from src.data.models.option import OptionType


@dataclass
class BSParams:
    """Black-Scholes calculation parameters.

    Encapsulates all parameters needed for B-S pricing and Greeks calculation.
    This provides a clean interface instead of passing 5-6 primitive parameters.

    Attributes:
        spot_price: Current price of underlying asset (S)
        strike_price: Strike price of the option (K)
        risk_free_rate: Annual risk-free interest rate (r)
        volatility: Implied volatility as decimal (sigma, e.g., 0.25 for 25%)
        time_to_expiry: Time to expiration in years (T)
        is_call: True for call option, False for put option

    Example:
        >>> params = BSParams(
        ...     spot_price=100.0,
        ...     strike_price=105.0,
        ...     risk_free_rate=0.05,
        ...     volatility=0.25,
        ...     time_to_expiry=0.5,
        ...     is_call=True
        ... )
        >>> # Can be used with B-S functions:
        >>> # delta = calc_bs_delta(params)
    """

    spot_price: float
    strike_price: float
    risk_free_rate: float
    volatility: float
    time_to_expiry: float
    is_call: bool = True

    @classmethod
    def from_option_quote(
        cls,
        quote: OptionQuote,
        spot_price: float,
        risk_free_rate: float = 0.05,
    ) -> "BSParams":
        """Create BSParams from an OptionQuote.

        This factory method bridges the data layer (OptionQuote) with the
        engine layer (BSParams), extracting relevant fields automatically.

        Args:
            quote: Option quote containing contract details and IV
            spot_price: Current price of the underlying asset
            risk_free_rate: Annual risk-free rate (default: 0.05)

        Returns:
            BSParams instance ready for B-S calculations

        Raises:
            ValueError: If quote.iv is None (IV required for B-S calculation)

        Example:
            >>> from src.data.models import OptionQuote, OptionContract, OptionType
            >>> from datetime import date, datetime
            >>> contract = OptionContract(
            ...     symbol="AAPL240119C00190000",
            ...     underlying="AAPL",
            ...     option_type=OptionType.CALL,
            ...     strike_price=190.0,
            ...     expiry_date=date(2024, 1, 19)
            ... )
            >>> quote = OptionQuote(
            ...     contract=contract,
            ...     timestamp=datetime.now(),
            ...     iv=0.25
            ... )
            >>> params = BSParams.from_option_quote(quote, spot_price=185.0)
        """
        if quote.iv is None:
            raise ValueError("OptionQuote.iv is required for BSParams")

        return cls(
            spot_price=spot_price,
            strike_price=quote.contract.strike_price,
            risk_free_rate=risk_free_rate,
            volatility=quote.iv,
            time_to_expiry=quote.contract.days_to_expiry / 365.0,
            is_call=quote.contract.option_type == OptionType.CALL,
        )

    @classmethod
    def from_market_data(
        cls,
        option_quote: OptionQuote,
        stock_quote: StockQuote | None = None,
        treasury_rate: MacroData | None = None,
        spot_price: float | None = None,
        risk_free_rate: float | None = None,
    ) -> "BSParams":
        """Create BSParams from multiple data layer sources.

        This factory method integrates multiple data sources from the data layer:
        - OptionQuote: strike, expiry, IV, option type
        - StockQuote: spot price (underlying current price)
        - MacroData: risk-free rate (treasury yield)

        Priority for spot_price:
            1. Explicit spot_price parameter
            2. stock_quote.close
            3. Raises ValueError if neither available

        Priority for risk_free_rate:
            1. Explicit risk_free_rate parameter
            2. treasury_rate.value / 100 (convert from percentage)
            3. Default: 0.05 (5%)

        Args:
            option_quote: Option quote containing contract details and IV
            stock_quote: Stock quote for underlying asset (provides spot_price)
            treasury_rate: Treasury yield data (e.g., TNX for 10Y, IRX for 13W)
            spot_price: Override spot price (if provided, ignores stock_quote)
            risk_free_rate: Override risk-free rate (if provided, ignores treasury_rate)

        Returns:
            BSParams instance ready for B-S calculations

        Raises:
            ValueError: If IV is None or spot_price cannot be determined

        Example:
            >>> from src.data.models import OptionQuote, StockQuote, MacroData
            >>> # Option: AAPL 190 Call
            >>> option = get_option_quote("AAPL240119C00190000")
            >>> # Underlying stock price
            >>> stock = get_stock_quote("AAPL")
            >>> # 10-Year Treasury yield (e.g., 4.5 means 4.5%)
            >>> treasury = get_macro_data("^TNX")
            >>> # Create BSParams from all data sources
            >>> params = BSParams.from_market_data(option, stock, treasury)
        """
        if option_quote.iv is None:
            raise ValueError("OptionQuote.iv is required for BSParams")

        # Determine spot_price
        final_spot: float | None = spot_price
        if final_spot is None and stock_quote is not None:
            final_spot = stock_quote.close
        if final_spot is None:
            raise ValueError(
                "spot_price must be provided either directly or via stock_quote.close"
            )

        # Determine risk_free_rate
        final_rate: float
        if risk_free_rate is not None:
            final_rate = risk_free_rate
        elif treasury_rate is not None:
            # Treasury yields are quoted in percentage (e.g., 4.5 for 4.5%)
            final_rate = treasury_rate.value / 100.0
        else:
            final_rate = 0.05  # Default 5%

        return cls(
            spot_price=final_spot,
            strike_price=option_quote.contract.strike_price,
            risk_free_rate=final_rate,
            volatility=option_quote.iv,
            time_to_expiry=option_quote.contract.days_to_expiry / 365.0,
            is_call=option_quote.contract.option_type == OptionType.CALL,
        )

    def validate(self) -> bool:
        """Validate that parameters are valid for B-S calculation.

        Returns:
            True if all parameters are valid for B-S calculation.

        Raises:
            ValueError: If any parameter is invalid.
        """
        if self.spot_price <= 0:
            raise ValueError(f"spot_price must be positive, got {self.spot_price}")
        if self.strike_price <= 0:
            raise ValueError(f"strike_price must be positive, got {self.strike_price}")
        if self.volatility <= 0:
            raise ValueError(f"volatility must be positive, got {self.volatility}")
        if self.time_to_expiry <= 0:
            raise ValueError(
                f"time_to_expiry must be positive, got {self.time_to_expiry}"
            )
        return True

    @property
    def moneyness(self) -> float:
        """Calculate moneyness ratio (S/K).

        Returns:
            Ratio of spot price to strike price.
            > 1 means ITM for calls, OTM for puts
            < 1 means OTM for calls, ITM for puts
        """
        return self.spot_price / self.strike_price

    @property
    def is_itm(self) -> bool:
        """Check if option is in-the-money.

        Returns:
            True if option is ITM based on current spot price.
        """
        if self.is_call:
            return self.spot_price > self.strike_price
        else:
            return self.spot_price < self.strike_price

    @property
    def is_otm(self) -> bool:
        """Check if option is out-of-the-money.

        Returns:
            True if option is OTM based on current spot price.
        """
        return not self.is_itm

    def with_spot(self, spot_price: float) -> "BSParams":
        """Create new BSParams with different spot price.

        Useful for scenario analysis or Greeks calculation at different prices.

        Args:
            spot_price: New spot price to use

        Returns:
            New BSParams instance with updated spot price.
        """
        return BSParams(
            spot_price=spot_price,
            strike_price=self.strike_price,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            time_to_expiry=self.time_to_expiry,
            is_call=self.is_call,
        )

    def with_volatility(self, volatility: float) -> "BSParams":
        """Create new BSParams with different volatility.

        Useful for volatility scenario analysis.

        Args:
            volatility: New volatility to use

        Returns:
            New BSParams instance with updated volatility.
        """
        return BSParams(
            spot_price=self.spot_price,
            strike_price=self.strike_price,
            risk_free_rate=self.risk_free_rate,
            volatility=volatility,
            time_to_expiry=self.time_to_expiry,
            is_call=self.is_call,
        )

    def with_time(self, time_to_expiry: float) -> "BSParams":
        """Create new BSParams with different time to expiry.

        Useful for time decay analysis.

        Args:
            time_to_expiry: New time to expiry in years

        Returns:
            New BSParams instance with updated time to expiry.
        """
        return BSParams(
            spot_price=self.spot_price,
            strike_price=self.strike_price,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            time_to_expiry=time_to_expiry,
            is_call=self.is_call,
        )

    def with_is_call(self, is_call: bool) -> "BSParams":
        """Create new BSParams with different option type.

        Useful for comparing call vs put metrics.

        Args:
            is_call: True for call option, False for put option

        Returns:
            New BSParams instance with updated option type.
        """
        return BSParams(
            spot_price=self.spot_price,
            strike_price=self.strike_price,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            time_to_expiry=self.time_to_expiry,
            is_call=is_call,
        )
