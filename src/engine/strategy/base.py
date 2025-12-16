"""Base classes and data structures for option strategies."""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class OptionType(Enum):
    """Option type enumeration."""

    CALL = "call"
    PUT = "put"


class PositionSide(Enum):
    """Position side enumeration."""

    LONG = "long"  # Buy
    SHORT = "short"  # Sell


@dataclass
class OptionLeg:
    """Single option leg in a strategy.

    Attributes:
        option_type: Call or Put
        side: Long (buy) or Short (sell)
        strike: Strike price
        premium: Option premium (per share)
        quantity: Number of contracts (default 1)
        volatility: IV for this specific leg (optional, can use strategy-level)
    """

    option_type: OptionType
    side: PositionSide
    strike: float
    premium: float
    quantity: int = 1
    volatility: float | None = None

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


@dataclass
class StrategyParams:
    """Common parameters for strategy calculations.

    Attributes:
        spot_price: Current stock price (S)
        risk_free_rate: Annual risk-free rate (r)
        volatility: Default implied volatility (σ), used if leg doesn't specify
        time_to_expiry: Time to expiration in years (T)
    """

    spot_price: float
    volatility: float
    time_to_expiry: float
    risk_free_rate: float = 0.03

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


class OptionStrategy(ABC):
    """Abstract base class for option strategies.

    Subclasses must implement:
    - calc_expected_return()
    - calc_return_variance()
    - calc_max_profit()
    - calc_max_loss()
    - calc_breakeven()
    - calc_win_probability()
    """

    def __init__(self, legs: list[OptionLeg], params: StrategyParams):
        """Initialize strategy.

        Args:
            legs: List of option legs in the strategy
            params: Common calculation parameters
        """
        self.legs = legs
        self.params = params

    @property
    def leg(self) -> OptionLeg:
        """Get the first (or only) leg for single-leg strategies."""
        return self.legs[0] if self.legs else None

    def get_leg_volatility(self, leg: OptionLeg) -> float:
        """Get volatility for a leg, falling back to strategy-level."""
        return leg.volatility if leg.volatility is not None else self.params.volatility

    @abstractmethod
    def calc_expected_return(self) -> float:
        """Calculate expected return E[π].

        Must be implemented by subclass.
        """
        pass

    @abstractmethod
    def calc_return_variance(self) -> float:
        """Calculate return variance Var[π].

        Must be implemented by subclass.
        """
        pass

    def calc_return_std(self) -> float:
        """Calculate return standard deviation Std[π] = sqrt(Var[π])."""
        variance = self.calc_return_variance()
        return math.sqrt(max(0, variance))

    @abstractmethod
    def calc_max_profit(self) -> float:
        """Calculate maximum possible profit."""
        pass

    @abstractmethod
    def calc_max_loss(self) -> float:
        """Calculate maximum possible loss (as positive number)."""
        pass

    @abstractmethod
    def calc_breakeven(self) -> float | list[float]:
        """Calculate breakeven price(s)."""
        pass

    @abstractmethod
    def calc_win_probability(self) -> float:
        """Calculate probability of profit."""
        pass

    def calc_sharpe_ratio(self, margin_ratio: float = 1.0) -> float | None:
        """Calculate Sharpe ratio.

        SR = (E[π] - Rf) / Std[π]
        Rf = margin_ratio × K × (e^(rT) - 1)

        Args:
            margin_ratio: Margin requirement as fraction of capital at risk

        Returns:
            Sharpe ratio, or None if std is zero.
        """
        e_pi = self.calc_expected_return()
        std_pi = self.calc_return_std()

        if std_pi <= 0:
            return None

        # Calculate capital at risk for risk-free return
        capital = self._calc_capital_at_risk() * margin_ratio

        # Risk-free return on margin capital
        rf = capital * (math.exp(self.params.risk_free_rate * self.params.time_to_expiry) - 1)

        return (e_pi - rf) / std_pi

    def calc_sharpe_ratio_annualized(self, margin_ratio: float = 1.0) -> float | None:
        """Calculate annualized Sharpe ratio.

        SR_annual = SR / sqrt(T)

        Args:
            margin_ratio: Margin requirement as fraction of capital at risk

        Returns:
            Annualized Sharpe ratio, or None if not calculable.
        """
        sr = self.calc_sharpe_ratio(margin_ratio)
        if sr is None or self.params.time_to_expiry <= 0:
            return None

        return sr / math.sqrt(self.params.time_to_expiry)

    def calc_kelly_fraction(self) -> float:
        """Calculate Kelly fraction for optimal position sizing.

        f* = E[π] / Var[π]

        Returns:
            Kelly fraction (0 if negative expectation).
        """
        e_pi = self.calc_expected_return()
        var_pi = self.calc_return_variance()

        if var_pi <= 0 or e_pi <= 0:
            return 0.0

        return e_pi / var_pi

    def _calc_capital_at_risk(self) -> float:
        """Calculate capital at risk for the strategy.

        Default implementation uses sum of strike prices for short options.
        Override in subclass if needed.
        """
        capital = 0.0
        for leg in self.legs:
            if leg.is_short:
                capital += leg.strike * leg.quantity
        return capital if capital > 0 else self.params.spot_price

    def calc_metrics(self, margin_ratio: float = 1.0) -> StrategyMetrics:
        """Calculate all metrics for the strategy.

        Args:
            margin_ratio: Margin requirement for Sharpe calculation

        Returns:
            StrategyMetrics with all calculated values.
        """
        return StrategyMetrics(
            expected_return=self.calc_expected_return(),
            return_std=self.calc_return_std(),
            return_variance=self.calc_return_variance(),
            max_profit=self.calc_max_profit(),
            max_loss=self.calc_max_loss(),
            breakeven=self.calc_breakeven(),
            win_probability=self.calc_win_probability(),
            sharpe_ratio=self.calc_sharpe_ratio(margin_ratio),
            kelly_fraction=self.calc_kelly_fraction(),
        )
