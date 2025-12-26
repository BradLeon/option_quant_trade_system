"""Strategy-related models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.data.models.option import Greeks, OptionType  # 统一使用 data 层定义
from src.engine.models.enums import PositionSide

if TYPE_CHECKING:
    from src.data.models.option import OptionQuote


class OptionLeg:
    """Single option leg in a strategy.

    Uses composition pattern for Greeks (delta, gamma, theta, vega, rho).
    Property accessors provide convenient access to individual Greek values.

    Attributes:
        option_type: Call or Put
        side: Long (buy) or Short (sell)
        strike: Strike price
        premium: Option premium (per share)
        quantity: Number of contracts (default 1)
        volatility: IV for this specific leg (optional, can use strategy-level)
        greeks: Greeks object containing delta, gamma, theta, vega, rho

    Example:
        >>> leg = OptionLeg(
        ...     option_type=OptionType.CALL,
        ...     side=PositionSide.LONG,
        ...     strike=100.0,
        ...     premium=5.0,
        ...     greeks=Greeks(delta=0.5, gamma=0.02, theta=-0.05, vega=0.30)
        ... )
        >>> leg.delta  # Convenience accessor
        0.5
    """

    def __init__(
        self,
        option_type: OptionType,
        side: PositionSide,
        strike: float,
        premium: float,
        quantity: int = 1,
        volatility: float | None = None,
        greeks: Greeks | None = None,
    ):
        """Initialize OptionLeg.

        Args:
            option_type: Call or Put
            side: Long (buy) or Short (sell)
            strike: Strike price
            premium: Option premium (per share)
            quantity: Number of contracts (default 1)
            volatility: IV for this specific leg
            greeks: Greeks object containing delta, gamma, theta, vega, rho
        """
        self.option_type = option_type
        self.side = side
        self.strike = strike
        self.premium = premium
        self.quantity = quantity
        self.volatility = volatility
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
        """Option delta (sensitivity to $1 move in underlying)."""
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
        """Option gamma (rate of change of delta)."""
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
        """Option theta - daily time decay."""
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
        """Option vega (sensitivity to 1% volatility change)."""
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
        """Option rho (sensitivity to interest rate changes)."""
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

    @property
    def is_call(self) -> bool:
        """Check if this is a call option."""
        return self.option_type == OptionType.CALL

    @property
    def is_put(self) -> bool:
        """Check if this is a put option."""
        return self.option_type == OptionType.PUT

    @property
    def is_long(self) -> bool:
        """Check if this is a long position."""
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        """Check if this is a short position."""
        return self.side == PositionSide.SHORT

    @property
    def sign(self) -> int:
        """Get position sign (+1 for long, -1 for short)."""
        return 1 if self.is_long else -1

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"OptionLeg(option_type={self.option_type!r}, side={self.side!r}, "
            f"strike={self.strike}, premium={self.premium}, quantity={self.quantity}, "
            f"volatility={self.volatility}, greeks={self._greeks!r})"
        )

    def __eq__(self, other: object) -> bool:
        """Check equality."""
        if not isinstance(other, OptionLeg):
            return NotImplemented
        return (
            self.option_type == other.option_type
            and self.side == other.side
            and self.strike == other.strike
            and self.premium == other.premium
            and self.quantity == other.quantity
            and self.volatility == other.volatility
            and self._greeks == other._greeks
        )

    @classmethod
    def from_option_quote(
        cls,
        option_quote: OptionQuote,
        side: PositionSide,
        quantity: int = 1,
        premium_override: float | None = None,
    ) -> OptionLeg:
        """Create OptionLeg from an OptionQuote.

        Factory method that extracts data from an OptionQuote to create
        an OptionLeg for strategy construction.

        Args:
            option_quote: OptionQuote with contract info, price, greeks, and IV.
            side: PositionSide.LONG (buy) or PositionSide.SHORT (sell).
            quantity: Number of contracts (default 1).
            premium_override: Override premium (uses mid_price if not provided).

        Returns:
            OptionLeg instance with data extracted from the quote.

        Example:
            >>> from src.data.providers.yahoo import YahooFinanceProvider
            >>> provider = YahooFinanceProvider()
            >>> chain = provider.get_option_chain("AAPL")
            >>> call_quote = chain.calls[0]
            >>> leg = OptionLeg.from_option_quote(call_quote, PositionSide.LONG)
        """
        contract = option_quote.contract

        # Determine premium
        if premium_override is not None:
            premium = premium_override
        elif option_quote.mid_price is not None:
            premium = option_quote.mid_price
        elif option_quote.last_price is not None:
            premium = option_quote.last_price
        else:
            premium = 0.0  # Fallback

        # Extract Greeks
        greeks = option_quote.greeks if option_quote.greeks else Greeks()

        return cls(
            option_type=contract.option_type,
            side=side,
            strike=contract.strike_price,
            premium=premium,
            quantity=quantity,
            volatility=option_quote.iv,
            greeks=greeks,
        )


@dataclass
class StrategyParams:
    """Common parameters for strategy calculations.

    Attributes:
        spot_price: Current stock price (S)
        volatility: Default implied volatility (σ), used if leg doesn't specify
        time_to_expiry: Time to expiration in years (T)
        risk_free_rate: Annual risk-free rate (r)
        hv: Historical volatility for SAS calculation (optional)
        dte: Days to expiration for PREI/ROC calculation (optional)
    """

    spot_price: float
    volatility: float
    time_to_expiry: float
    risk_free_rate: float = 0.035
    hv: float | None = None
    dte: int | None = None

    def validate(self) -> bool:
        """Validate parameters."""
        return (
            self.spot_price > 0
            and self.volatility > 0
            and self.time_to_expiry > 0
        )


@dataclass
class StrategyMetrics:
    """Calculated metrics for a strategy.

    Attributes:
        expected_return: Expected profit E[π]
        return_std: Standard deviation of return Std[π]
        return_variance: Variance of return Var[π]
        max_profit: Maximum possible profit
        max_loss: Maximum possible loss (as positive number)
        breakeven: Breakeven price(s)
        win_probability: Probability of profit
        sharpe_ratio: Risk-adjusted return (optional)
        kelly_fraction: Optimal position size (optional)
        prei: Position Risk Exposure Index (0-100, higher = more risk)
        sas: Strategy Attractiveness Score (0-100, higher = more attractive)
        tgr: Theta/Gamma Ratio (higher = better for theta strategies)
        roc: Annualized Return on Capital
    """

    expected_return: float
    return_std: float
    return_variance: float
    max_profit: float
    max_loss: float
    breakeven: float | list[float]
    win_probability: float
    sharpe_ratio: float | None = None
    kelly_fraction: float | None = None
    prei: float | None = None
    sas: float | None = None
    tgr: float | None = None
    roc: float | None = None
    expected_roc: float | None = None
