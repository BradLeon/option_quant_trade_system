"""Short Put strategy implementation.

Sell a put option to collect premium, with obligation to buy stock if exercised.

Reference: 期权量化指标计算-以卖看跌期权为例.md
"""

import math

from src.data.models.option import Greeks, OptionType
from src.engine.bs.core import calc_d1, calc_d2, calc_d3, calc_n
from src.engine.models import BSParams
from src.engine.models.enums import PositionSide
from src.engine.models.strategy import OptionLeg, StrategyMetrics, StrategyParams
from src.engine.strategy.base import OptionStrategy


class ShortPutStrategy(OptionStrategy):
    """Short Put (Sell Put) strategy.

    Profit/Loss Profile:
    - Max Profit: Premium received (if stock stays above strike)
    - Max Loss: Strike - Premium (if stock goes to 0)
    - Breakeven: Strike - Premium

    Use case:
    - Bullish to neutral outlook
    - Willing to buy stock at strike price
    - Want to generate income from premium
    """

    def __init__(
        self,
        spot_price: float,
        strike_price: float,
        premium: float,
        volatility: float,
        time_to_expiry: float,
        risk_free_rate: float = 0.03,
        hv: float | None = None,
        dte: int | None = None,
        delta: float | None = None,
        gamma: float | None = None,
        theta: float | None = None,
        vega: float | None = None,
    ):
        """Initialize Short Put strategy.

        Args:
            spot_price: Current stock price (S)
            strike_price: Put strike price (K)
            premium: Premium received per share (C)
            volatility: Implied volatility (σ)
            time_to_expiry: Time to expiration in years (T)
            risk_free_rate: Annual risk-free rate (r)
            hv: Historical volatility for SAS calculation (optional)
            dte: Days to expiration for PREI/ROC calculation (optional)
            delta: Option delta (optional)
            gamma: Option gamma (optional)
            theta: Option theta - daily time decay (optional)
            vega: Option vega (optional)
        """
        leg = OptionLeg(
            option_type=OptionType.PUT,
            side=PositionSide.SHORT,
            strike=strike_price,
            premium=premium,
            greeks=Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega),
        )
        params = StrategyParams(
            spot_price=spot_price,
            volatility=volatility,
            time_to_expiry=time_to_expiry,
            risk_free_rate=risk_free_rate,
            hv=hv,
            dte=dte,
        )
        super().__init__([leg], params)

        # Create BSParams for B-S calculations
        bs_params = BSParams(
            spot_price=spot_price,
            strike_price=strike_price,
            risk_free_rate=risk_free_rate,
            volatility=volatility,
            time_to_expiry=time_to_expiry,
            is_call=False,
        )

        # Cache B-S parameters
        self._d1 = calc_d1(bs_params)
        self._d2 = calc_d2(bs_params, self._d1) if self._d1 else None
        self._d3 = calc_d3(bs_params, self._d2) if self._d2 else None

    def calc_expected_return(self) -> float:
        """Calculate expected return for short put.

        E[π] = C - N(-d2) * [K - e^(rT) * S * N(-d1) / N(-d2)]
        
        Where:
        - C: Premium received
        - N(-d2): Exercise probability
        - K: Strike price
        - S: Spot price
        - r: Risk-free rate
        - T: Time to expiry

        Returns:
            Expected return in dollar amount per share.
        """
        if self._d1 is None or self._d2 is None:
            return 0.0

        c = self.leg.premium
        k = self.leg.strike
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        n_minus_d1 = calc_n(-self._d1)
        n_minus_d2 = calc_n(-self._d2)

        if n_minus_d2 == 0:
            # No exercise probability, expected return = premium
            return c

        # Expected stock price if exercised
        exp_rt = math.exp(r * t)
        expected_stock_if_exercised = exp_rt * s * n_minus_d1 / n_minus_d2

        # E[π] = C - N(-d2) * (K - Expected_Stock)
        expected_return = c - n_minus_d2 * (k - expected_stock_if_exercised)

        return expected_return

    def calc_return_variance(self) -> float:
        """Calculate variance of return for short put.

        Var[π] = E[π²] - (E[π])²

        E[π²] = C² × (1-N(-d2))
                + (C-K)² × N(-d2)
                + 2(C-K) × e^(rT) × S × N(-d1)
                + S² × e^(2rT + σ²T) × N(-d3)

        Returns:
            Variance of return.
        """
        if self._d1 is None or self._d2 is None or self._d3 is None:
            return 0.0

        c = self.leg.premium
        k = self.leg.strike
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry
        sigma = self.params.volatility

        n_minus_d1 = calc_n(-self._d1)
        n_minus_d2 = calc_n(-self._d2)
        n_minus_d3 = calc_n(-self._d3)

        exp_rt = math.exp(r * t)
        exp_2rt_sigma2t = math.exp(2 * r * t + sigma**2 * t)

        # E[π²] calculation
        e_pi_squared = (
            c**2 * (1 - n_minus_d2)
            + (c - k) ** 2 * n_minus_d2
            + 2 * (c - k) * exp_rt * s * n_minus_d1
            + s**2 * exp_2rt_sigma2t * n_minus_d3
        )

        # E[π]
        e_pi = self.calc_expected_return()

        # Var[π] = E[π²] - (E[π])²
        variance = e_pi_squared - e_pi**2

        return max(0.0, variance)

    def calc_max_profit(self) -> float:
        """Calculate maximum profit (premium received)."""
        return self.leg.premium

    def calc_max_loss(self) -> float:
        """Calculate maximum loss (strike - premium, if stock goes to 0)."""
        return self.leg.strike - self.leg.premium

    def calc_breakeven(self) -> float:
        """Calculate breakeven price (strike - premium)."""
        return self.leg.strike - self.leg.premium

    def calc_win_probability(self) -> float:
        """Calculate probability of profit (stock stays above breakeven).

        Win probability ≈ N(d2) = 1 - N(-d2)

        Returns:
            Win probability (0-1).
        """
        if self._d2 is None:
            return 0.0

        return calc_n(self._d2)

    def calc_expected_loss_if_exercised(self) -> float:
        """Calculate expected loss if put is exercised.

        Expected loss = C - [K - e^(rT) * S * N(-d1) / N(-d2)]

        Returns:
            Expected loss (negative means loss).
        """
        if self._d1 is None or self._d2 is None:
            return 0.0

        c = self.leg.premium
        k = self.leg.strike
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        n_minus_d1 = calc_n(-self._d1)
        n_minus_d2 = calc_n(-self._d2)

        if n_minus_d2 == 0:
            return 0.0

        exp_rt = math.exp(r * t)
        expected_stock_if_exercised = exp_rt * s * n_minus_d1 / n_minus_d2

        return c - (k - expected_stock_if_exercised)

    def calc_exercise_probability(self) -> float:
        """Calculate exercise probability N(-d2)."""
        if self._d2 is None:
            return 0.0

        return calc_n(-self._d2)

    def calc_margin_requirement(self) -> float:
        """Calculate margin requirement using IBKR formula for Short Put.

        IBKR Formula (Stock Options):
        Margin = Put Price + Max(
            20% × Underlying Price - OTM Amount,
            10% × Strike Price
        )

        underlying_price = 54.49
        put_price = 1.44
        strike_price = 51
        OTM = 54.49 - 51 = 3.49
        
        Margin = 1.44 + Max(0.20 × 54.49 - 3.49, 0.10 × 54.49)
        Margin = 1.44 + Max(10.898 - 3.49, 5.449)
        Margin = 1.44 + 10.898
        Margin = 12.338

        Where:
        - Put Price = Premium received
        - Underlying Price = Current stock price
        - OTM Amount = Max(0, Underlying Price - Strike Price)
        - Strike Price = Put strike

        Returns:
            Margin requirement in dollars.
        """
        put_price = self.leg.premium
        underlying_price = self.params.spot_price
        strike_price = self.leg.strike

        # Calculate out-of-the-money amount
        # For put: OTM when spot > strike
        otm_amount = max(0, underlying_price - strike_price)

        # IBKR margin formula
        option1 = 0.20 * underlying_price - otm_amount
        option2 = 0.10 * strike_price

        margin = put_price + max(option1, option2)

        return margin
