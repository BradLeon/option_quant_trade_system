"""Short Call (Naked Call) strategy implementation.

Sell a call option to collect premium, with obligation to sell stock if exercised.
High risk strategy with unlimited potential loss.
"""

import math

from src.data.models.option import Greeks, OptionType
from src.engine.bs.core import calc_d1, calc_d2, calc_d3, calc_n
from src.engine.models import BSParams
from src.engine.models.enums import PositionSide
from src.engine.models.strategy import OptionLeg, StrategyParams
from src.engine.strategy.base import OptionStrategy


class ShortCallStrategy(OptionStrategy):
    """Short Call (Sell Call / Naked Call) strategy.

    Profit/Loss Profile:
    - Max Profit: Premium received (if stock stays below strike)
    - Max Loss: Unlimited (if stock rises significantly)
    - Breakeven: Strike + Premium

    Use case:
    - Bearish to neutral outlook
    - Speculative premium collection
    - High risk tolerance

    WARNING: This is a high-risk strategy with unlimited loss potential.
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
        """Initialize Short Call strategy.

        Args:
            spot_price: Current stock price (S)
            strike_price: Call strike price (K)
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
            option_type=OptionType.CALL,
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
            is_call=True,
        )

        # Cache B-S parameters
        self._d1 = calc_d1(bs_params)
        self._d2 = calc_d2(bs_params, self._d1) if self._d1 else None
        self._d3 = calc_d3(bs_params, self._d2) if self._d2 else None

    def calc_expected_return(self) -> float:
        """Calculate expected return for short call.

        E[π] = C - N(d2) * [S * e^(rT) * N(d1) / N(d2) - K]

        Where:
        - C: Premium received
        - N(d2): Exercise probability
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

        n_d1 = calc_n(self._d1)
        n_d2 = calc_n(self._d2)

        if n_d2 == 0:
            # No exercise probability, expected return = premium
            return c

        # Expected stock price if exercised (conditional expectation)
        exp_rt = math.exp(r * t)
        expected_stock_if_exercised = exp_rt * s * n_d1 / n_d2

        # E[π] = C - N(d2) * (Expected_Stock - K)
        expected_return = c - n_d2 * (expected_stock_if_exercised - k)

        return expected_return

    def calc_return_variance(self) -> float:
        """Calculate variance of return for short call.

        Var[π] = E[π²] - (E[π])²

        E[π²] = C² × (1-N(d2))
                + (C-K)² × N(d2)  # Capped loss if assigned
                - 2(K-C) × S × e^(rT) × N(d1)
                + S² × e^(2rT + σ²T) × N(d3)

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

        n_d1 = calc_n(self._d1)
        n_d2 = calc_n(self._d2)
        n_d3 = calc_n(self._d3)

        exp_rt = math.exp(r * t)
        exp_2rt_sigma2t = math.exp(2 * r * t + sigma**2 * t)

        # E[π²] calculation
        # Region 1: S_T <= K (not exercised, keep premium)
        # Region 2: S_T > K (exercised, loss)
        e_pi_squared = (
            c**2 * (1 - n_d2)
            + (c + k) ** 2 * n_d2
            - 2 * (k - c) * exp_rt * s * n_d1
            + s**2 * exp_2rt_sigma2t * n_d3
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
        """Calculate maximum loss (theoretically unlimited).

        We return a very large number to represent unlimited loss.
        For practical risk management, use strike-based estimates.
        """
        # Return 10x strike as a practical upper bound
        return 10 * self.leg.strike

    def calc_breakeven(self) -> float:
        """Calculate breakeven price (strike + premium)."""
        return self.leg.strike + self.leg.premium

    def calc_win_probability(self) -> float:
        """Calculate probability of profit (stock stays below breakeven).

        Win probability ≈ 1 - N(d2_breakeven)

        Returns:
            Win probability (0-1).
        """
        breakeven = self.calc_breakeven()

        # Create BSParams with breakeven as strike
        be_params = BSParams(
            spot_price=self.params.spot_price,
            strike_price=breakeven,
            risk_free_rate=self.params.risk_free_rate,
            volatility=self.params.volatility,
            time_to_expiry=self.params.time_to_expiry,
            is_call=True,
        )

        # Calculate d2 relative to breakeven
        d1_be = calc_d1(be_params)
        if d1_be is None:
            return 0.0

        d2_be = calc_d2(be_params, d1_be)
        if d2_be is None:
            return 0.0

        # P(S_T < breakeven) = 1 - N(d2)
        return 1.0 - calc_n(d2_be)

    def calc_exercise_probability(self) -> float:
        """Calculate exercise probability N(d2)."""
        if self._d2 is None:
            return 0.0

        return calc_n(self._d2)

    def calc_margin_requirement(self) -> float:
        """Calculate margin requirement using IBKR formula for Short Call.

        IBKR Formula (Stock Options):
        Margin = Call Price + Max(
            20% × Underlying Price - OTM Amount,
            10% × Underlying Price
        )

        Where:
        - Call Price = Premium received
        - Underlying Price = Current stock price
        - OTM Amount = Max(0, Strike Price - Underlying Price)
        - Strike Price = Call strike

        Returns:
            Margin requirement in dollars.
        """
        call_price = self.leg.premium
        underlying_price = self.params.spot_price
        strike_price = self.leg.strike

        # Calculate out-of-the-money amount
        # For call: OTM when strike > spot
        otm_amount = max(0, strike_price - underlying_price)

        # IBKR margin formula
        option1 = 0.20 * underlying_price - otm_amount
        option2 = 0.10 * underlying_price

        margin = call_price + max(option1, option2)

        return margin

    def _calc_capital_at_risk(self) -> float:
        """Capital at risk for naked call.

        For risk management, we use strike price as capital at risk,
        though actual risk is theoretically unlimited.
        """
        return self.leg.strike
