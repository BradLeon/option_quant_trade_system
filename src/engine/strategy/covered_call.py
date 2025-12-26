"""Covered Call strategy implementation.

Own stock + Sell a call option to collect premium.
"""

import math

from src.data.models.option import Greeks, OptionType
from src.engine.bs.core import calc_d1, calc_d2, calc_d3, calc_n
from src.engine.models import BSParams
from src.engine.models.enums import PositionSide
from src.engine.models.strategy import OptionLeg, StrategyParams
from src.engine.strategy.base import OptionStrategy


class CoveredCallStrategy(OptionStrategy):
    """Covered Call strategy.

    Long stock + Short call option.

    Profit/Loss Profile:
    - Max Profit: (Strike - Stock Price) + Premium (if stock rises above strike)
    - Max Loss: Stock Price - Premium (if stock goes to 0)
    - Breakeven: Stock Price - Premium

    Use case:
    - Neutral to moderately bullish outlook
    - Willing to sell stock at strike price
    - Want to generate income from premium while holding stock
    """

    def __init__(
        self,
        spot_price: float,
        strike_price: float,
        premium: float,
        volatility: float,
        time_to_expiry: float,
        risk_free_rate: float = 0.03,
        stock_cost_basis: float | None = None,
        coverage_ratio: float = 1.0,
        hv: float | None = None,
        dte: int | None = None,
        delta: float | None = None,
        gamma: float | None = None,
        theta: float | None = None,
        vega: float | None = None,
    ):
        """Initialize Covered Call strategy.

        Args:
            spot_price: Current stock price (S)
            strike_price: Call strike price (K)
            premium: Premium received per share (C)
            volatility: Implied volatility (σ)
            time_to_expiry: Time to expiration in years (T)
            risk_free_rate: Annual risk-free rate (r)
            stock_cost_basis: Original cost of stock (defaults to spot_price) --正股买入价
            coverage_ratio: Ratio of stock shares to call shares (0.0-1.0)
                - 1.0 = fully covered (stock >= calls)
                - 0.75 = 75% covered, 25% naked
                - 0.0 = fully naked (no stock)
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

        self.stock_cost_basis = stock_cost_basis or spot_price
        self.coverage_ratio = max(0.0, min(1.0, coverage_ratio))  # Clamp to [0, 1]

        # Create BSParams for B-S calculations
        self._bs_params = BSParams(
            spot_price=spot_price,
            strike_price=strike_price,
            risk_free_rate=risk_free_rate,
            volatility=volatility,
            time_to_expiry=time_to_expiry,
            is_call=True,
        )

        # Cache B-S parameters
        self._d1 = calc_d1(self._bs_params)
        self._d2 = calc_d2(self._bs_params, self._d1) if self._d1 else None
        self._d3 = calc_d3(self._bs_params, self._d2) if self._d2 else None

    def calc_expected_return(self) -> float:
        """Calculate expected return for covered call.

        For covered call (long stock + short call):
        E[π] = E[Stock Return] + E[Call Premium]
             = E[S_T] - S + C - E[max(S_T - K, 0)]

        Using B-S framework:
        E[π] = C + S × (e^(rT) - 1) - [S × e^(rT) × N(d1) - K × N(d2)]
             = C + S × e^(rT) × (1 - N(d1)) - S + K × N(d2)
             = C + S × e^(rT) × N(-d1) - S + K × N(d2)

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
        n_minus_d1 = calc_n(-self._d1)

        exp_rt = math.exp(r * t)

        # Expected stock value at expiry under risk-neutral measure
        expected_stock = s * exp_rt

        # Expected call payoff = S × e^(rT) × N(d1) - K × N(d2)
        expected_call_payoff = s * exp_rt * n_d1 - k * n_d2

        # Covered call return = Stock gain + Premium - Call payoff
        # = (E[S_T] - S) + C - E[call payoff]
        expected_return = (expected_stock - s) + c - expected_call_payoff

        return expected_return

    def calc_return_variance(self) -> float:
        """Calculate variance of return for covered call.

        The covered call P&L is:
        - If S_T <= K: Premium + (S_T - S) = C + S_T - S
        - If S_T > K: Premium + (K - S) = C + K - S

        Var[π] = E[π²] - (E[π])²

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
        n_minus_d2 = calc_n(-self._d2)

        exp_rt = math.exp(r * t)
        exp_2rt_sigma2t = math.exp(2 * r * t + sigma**2 * t)

        # For covered call, the payoff is capped at K when S_T > K
        # P&L when S_T <= K: C + S_T - S (variable with stock)
        # P&L when S_T > K: C + K - S (fixed)

        # E[π²] for covered call
        # Region 1: S_T <= K (probability N(-d2))
        # Region 2: S_T > K (probability N(d2))

        # In region 2 (called away): (C + K - S)²
        fixed_payoff = c + k - s
        e_pi_sq_called = fixed_payoff**2 * n_d2

        # In region 1 (keep stock): E[(C + S_T - S)² | S_T <= K]
        # This requires conditional expectation of S_T² given S_T <= K

        # Using truncated lognormal moments:
        # E[S_T | S_T <= K] = S × e^(rT) × N(-d1) / N(-d2)
        # E[S_T² | S_T <= K] = S² × e^((2r + σ²)T) × N(-d3) / N(-d2)
        # where d3 = (ln(S/K) + (r + 3σ²/2)T) / (σ√T)

        # Actually d3 for E[S_T²] uses different formula
        d3_for_sq = (
            math.log(s / k) + (r + 1.5 * sigma**2) * t
        ) / (sigma * math.sqrt(t))
        n_minus_d3_sq = calc_n(-d3_for_sq)

        if n_minus_d2 > 0:
            # Conditional expectations
            e_st_given_below = s * exp_rt * calc_n(-self._d1) / n_minus_d2
            e_st_sq_given_below = s**2 * exp_2rt_sigma2t * n_minus_d3_sq / n_minus_d2

            # E[(C + S_T - S)²] = (C-S)² + 2(C-S)E[S_T] + E[S_T²]
            e_pi_sq_kept = (
                (c - s) ** 2
                + 2 * (c - s) * e_st_given_below
                + e_st_sq_given_below
            ) * n_minus_d2
        else:
            e_pi_sq_kept = 0.0

        e_pi_squared = e_pi_sq_called + e_pi_sq_kept

        e_pi = self.calc_expected_return()
        variance = e_pi_squared - e_pi**2

        return max(0.0, variance)

    def calc_max_profit(self) -> float:
        """Calculate maximum profit.

        Max profit = (Strike - Stock Cost) + Premium
        Occurs when stock is called away at strike price.
        """
        return (self.leg.strike - self.stock_cost_basis) + self.leg.premium

    def calc_max_loss(self) -> float:
        """Calculate maximum loss.

        Max loss = Stock Cost - Premium (if stock goes to 0)
        """
        return self.stock_cost_basis - self.leg.premium

    def calc_breakeven(self) -> float:
        """Calculate breakeven price.

        Breakeven = Stock Cost - Premium
        """
        return self.stock_cost_basis - self.leg.premium

    def calc_win_probability(self) -> float:
        """Calculate probability of profit.

        Profit when S_T > Breakeven = Stock Cost - Premium

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

        # P(S_T > breakeven) = N(d2)
        return calc_n(d2_be)

    def calc_assignment_probability(self) -> float:
        """Calculate probability of call being assigned (exercised).

        Assignment probability = N(d2) = probability S_T > K
        """
        if self._d2 is None:
            return 0.0

        return calc_n(self._d2)

    def _calc_capital_at_risk(self) -> float:
        """Capital at risk is the stock cost basis."""
        return self.stock_cost_basis

    def calc_roc(self) -> float | None:
        """Calculate annualized Return on Capital for Covered Call.

        For covered call, capital at risk is the stock cost basis,
        not the margin requirement (which is minimal for fully covered calls).

        ROC = (premium / stock_cost_basis) * (365 / dte)

        Returns:
            Annualized ROC, or None if insufficient data.
        """
        from src.engine.position.risk_return import calc_roc_from_dte

        dte = self.params.dte
        if dte is None or dte <= 0:
            return None

        premium = self.leg.premium
        if premium <= 0:
            return None

        # Use stock cost basis as capital at risk
        capital = self._calc_capital_at_risk()  # = stock_cost_basis
        if capital <= 0:
            return None

        return calc_roc_from_dte(premium, capital, dte)

    def calc_expected_roc(self) -> float | None:
        """Calculate annualized Expected ROC for Covered Call.

        For covered call, capital at risk is the stock cost basis,
        not the margin requirement.

        Formula: (expected_return / stock_cost_basis) × (365 / dte)

        Returns:
            Annualized expected ROC, or None if insufficient data.
        """
        from src.engine.position.risk_return import calc_roc_from_dte

        dte = self.params.dte
        if dte is None or dte <= 0:
            return None

        expected_return = self.calc_expected_return()
        if expected_return is None:
            return None

        # Use stock cost basis as capital at risk
        capital = self._calc_capital_at_risk()  # = stock_cost_basis
        if capital <= 0:
            return None

        return calc_roc_from_dte(expected_return, capital, dte)

    def calc_margin_requirement(self) -> float:
        """Calculate margin requirement using IBKR formula for Covered Call.

        For covered call, since we own the underlying stock, the margin
        requirement is typically just the call premium (no additional margin
        needed because the stock covers the short call obligation).

        ASSUMPTION: This assumes **full coverage** where stock_quantity >=
        call_quantity * contract_multiplier. Partial coverage scenarios
        should be handled separately with a combination of covered and
        naked call strategies.

        Returns:
            Margin requirement in dollars (minimal for fully covered calls).
        """
        # For fully covered call, margin requirement is minimal because
        # the stock position covers the short call obligation
        # Return the call premium as a conservative estimate
        return self.leg.premium
