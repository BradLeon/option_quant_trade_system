"""Short Strangle strategy implementation.

Sell both a put and a call with different strikes to collect premium.
"""

import math

from src.engine.bs.core import calc_d1, calc_d2, calc_n
from src.engine.strategy.base import (
    OptionLeg,
    OptionStrategy,
    OptionType,
    PositionSide,
    StrategyParams,
)


class ShortStrangleStrategy(OptionStrategy):
    """Short Strangle strategy.

    Short put (lower strike) + Short call (higher strike).

    Profit/Loss Profile:
    - Max Profit: Put Premium + Call Premium (if stock stays between strikes)
    - Max Loss: Unlimited on upside, (Put Strike - Total Premium) on downside
    - Breakeven: Two points
        - Lower: Put Strike - Total Premium
        - Upper: Call Strike + Total Premium

    Use case:
    - Neutral outlook, expecting low volatility
    - Profit from time decay and IV crush
    - Higher risk due to unlimited loss potential on upside
    """

    def __init__(
        self,
        spot_price: float,
        put_strike: float,
        call_strike: float,
        put_premium: float,
        call_premium: float,
        volatility: float,
        time_to_expiry: float,
        risk_free_rate: float = 0.03,
        put_volatility: float | None = None,
        call_volatility: float | None = None,
    ):
        """Initialize Short Strangle strategy.

        Args:
            spot_price: Current stock price (S)
            put_strike: Put strike price (K_p), should be < spot
            call_strike: Call strike price (K_c), should be > spot
            put_premium: Premium received for put
            call_premium: Premium received for call
            volatility: Default implied volatility (σ)
            time_to_expiry: Time to expiration in years (T)
            risk_free_rate: Annual risk-free rate (r)
            put_volatility: IV for put leg (optional)
            call_volatility: IV for call leg (optional)
        """
        put_leg = OptionLeg(
            option_type=OptionType.PUT,
            side=PositionSide.SHORT,
            strike=put_strike,
            premium=put_premium,
            volatility=put_volatility,
        )
        call_leg = OptionLeg(
            option_type=OptionType.CALL,
            side=PositionSide.SHORT,
            strike=call_strike,
            premium=call_premium,
            volatility=call_volatility,
        )
        params = StrategyParams(
            spot_price=spot_price,
            volatility=volatility,
            time_to_expiry=time_to_expiry,
            risk_free_rate=risk_free_rate,
        )
        super().__init__([put_leg, call_leg], params)

        self.put_leg = put_leg
        self.call_leg = call_leg

        # Cache B-S parameters for both legs
        self._cache_bs_params()

    def _cache_bs_params(self):
        """Cache B-S parameters for both legs."""
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        # Put leg
        put_vol = self.get_leg_volatility(self.put_leg)
        self._put_d1 = calc_d1(s, self.put_leg.strike, r, put_vol, t)
        self._put_d2 = (
            calc_d2(self._put_d1, put_vol, t) if self._put_d1 else None
        )

        # Call leg
        call_vol = self.get_leg_volatility(self.call_leg)
        self._call_d1 = calc_d1(s, self.call_leg.strike, r, call_vol, t)
        self._call_d2 = (
            calc_d2(self._call_d1, call_vol, t) if self._call_d1 else None
        )

    @property
    def total_premium(self) -> float:
        """Total premium received."""
        return self.put_leg.premium + self.call_leg.premium

    def calc_expected_return(self) -> float:
        """Calculate expected return for short strangle.

        E[π] = E[π_put] + E[π_call]

        For short put:
        E[π_put] = C_p - N(-d2_p) * [K_p - e^(rT) * S * N(-d1_p) / N(-d2_p)]

        For short call:
        E[π_call] = C_c - N(d2_c) * [e^(rT) * S * N(d1_c) / N(d2_c) - K_c]

        Returns:
            Expected return in dollar amount per share.
        """
        e_put = self._calc_put_expected_return()
        e_call = self._calc_call_expected_return()

        return e_put + e_call

    def _calc_put_expected_return(self) -> float:
        """Calculate expected return for the put leg."""
        if self._put_d1 is None or self._put_d2 is None:
            return 0.0

        c = self.put_leg.premium
        k = self.put_leg.strike
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        n_minus_d1 = calc_n(-self._put_d1)
        n_minus_d2 = calc_n(-self._put_d2)

        if n_minus_d2 == 0:
            return c

        exp_rt = math.exp(r * t)
        expected_stock_if_exercised = exp_rt * s * n_minus_d1 / n_minus_d2

        return c - n_minus_d2 * (k - expected_stock_if_exercised)

    def _calc_call_expected_return(self) -> float:
        """Calculate expected return for the call leg."""
        if self._call_d1 is None or self._call_d2 is None:
            return 0.0

        c = self.call_leg.premium
        k = self.call_leg.strike
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        n_d1 = calc_n(self._call_d1)
        n_d2 = calc_n(self._call_d2)

        if n_d2 == 0:
            return c

        exp_rt = math.exp(r * t)
        expected_stock_if_exercised = exp_rt * s * n_d1 / n_d2

        return c - n_d2 * (expected_stock_if_exercised - k)

    def calc_return_variance(self) -> float:
        """Calculate variance of return for short strangle.

        For simplicity, we use a simplified approach:
        - The three regions: S_T < K_p, K_p <= S_T <= K_c, S_T > K_c
        - Calculate E[π²] in each region and sum

        This is an approximation as the full calculation is complex.

        Returns:
            Variance of return.
        """
        if any(
            x is None
            for x in [self._put_d1, self._put_d2, self._call_d1, self._call_d2]
        ):
            return 0.0

        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry
        put_vol = self.get_leg_volatility(self.put_leg)
        call_vol = self.get_leg_volatility(self.call_leg)

        k_p = self.put_leg.strike
        k_c = self.call_leg.strike
        c_p = self.put_leg.premium
        c_c = self.call_leg.premium
        total_c = c_p + c_c

        exp_rt = math.exp(r * t)

        # Probabilities of regions
        n_minus_d2_put = calc_n(-self._put_d2)  # P(S_T < K_p)
        n_d2_call = calc_n(self._call_d2)  # P(S_T > K_c)
        p_middle = 1 - n_minus_d2_put - n_d2_call  # P(K_p <= S_T <= K_c)

        # Region 1: S_T < K_p (put exercised)
        # Payoff = C_p + C_c - (K_p - S_T) = C_p + C_c - K_p + S_T
        if n_minus_d2_put > 0:
            n_minus_d1_put = calc_n(-self._put_d1)
            e_st_given_below_kp = exp_rt * s * n_minus_d1_put / n_minus_d2_put

            # E[(total_c - k_p + S_T)² | S_T < K_p]
            fixed_part = total_c - k_p
            e_payoff_sq_1 = (
                fixed_part**2
                + 2 * fixed_part * e_st_given_below_kp
                + self._calc_e_st_sq_below(k_p, put_vol) / n_minus_d2_put
                if n_minus_d2_put > 0
                else 0
            ) * n_minus_d2_put
        else:
            e_payoff_sq_1 = 0

        # Region 2: K_p <= S_T <= K_c (neither exercised)
        # Payoff = C_p + C_c = total_c (constant)
        e_payoff_sq_2 = total_c**2 * p_middle

        # Region 3: S_T > K_c (call exercised)
        # Payoff = C_p + C_c - (S_T - K_c) = C_p + C_c + K_c - S_T
        if n_d2_call > 0:
            n_d1_call = calc_n(self._call_d1)
            e_st_given_above_kc = exp_rt * s * n_d1_call / n_d2_call

            fixed_part = total_c + k_c
            e_payoff_sq_3 = (
                fixed_part**2
                - 2 * fixed_part * e_st_given_above_kc
                + self._calc_e_st_sq_above(k_c, call_vol) / n_d2_call
                if n_d2_call > 0
                else 0
            ) * n_d2_call
        else:
            e_payoff_sq_3 = 0

        e_pi_squared = e_payoff_sq_1 + e_payoff_sq_2 + e_payoff_sq_3
        e_pi = self.calc_expected_return()

        variance = e_pi_squared - e_pi**2
        return max(0.0, variance)

    def _calc_e_st_sq_below(self, strike: float, vol: float) -> float:
        """Calculate E[S_T² × 1{S_T < K}]."""
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        exp_2rt_vol2t = math.exp(2 * r * t + vol**2 * t)

        # d3 for E[S_T²]
        d3 = (math.log(s / strike) + (r + 1.5 * vol**2) * t) / (vol * math.sqrt(t))
        n_minus_d3 = calc_n(-d3)

        return s**2 * exp_2rt_vol2t * n_minus_d3

    def _calc_e_st_sq_above(self, strike: float, vol: float) -> float:
        """Calculate E[S_T² × 1{S_T > K}]."""
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        exp_2rt_vol2t = math.exp(2 * r * t + vol**2 * t)

        d3 = (math.log(s / strike) + (r + 1.5 * vol**2) * t) / (vol * math.sqrt(t))
        n_d3 = calc_n(d3)

        return s**2 * exp_2rt_vol2t * n_d3

    def calc_max_profit(self) -> float:
        """Calculate maximum profit (total premium received)."""
        return self.total_premium

    def calc_max_loss(self) -> float:
        """Calculate maximum loss.

        Theoretical max loss is unlimited on upside.
        On downside, max loss = Put Strike - Total Premium (if stock goes to 0).

        Returns:
            Downside max loss (upside is theoretically unlimited).
        """
        return self.put_leg.strike - self.total_premium

    def calc_breakeven(self) -> list[float]:
        """Calculate breakeven prices.

        Lower breakeven = Put Strike - Total Premium
        Upper breakeven = Call Strike + Total Premium

        Returns:
            List of [lower_breakeven, upper_breakeven].
        """
        return [
            self.put_leg.strike - self.total_premium,
            self.call_leg.strike + self.total_premium,
        ]

    def calc_win_probability(self) -> float:
        """Calculate probability of profit.

        Profit when: Lower BE < S_T < Upper BE

        Returns:
            Win probability (0-1).
        """
        breakevens = self.calc_breakeven()
        lower_be = breakevens[0]
        upper_be = breakevens[1]

        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry
        vol = self.params.volatility

        # P(Lower BE < S_T < Upper BE) = N(d2_upper) - N(d2_lower)
        # where d2 is calculated relative to each breakeven

        d1_lower = calc_d1(s, lower_be, r, vol, t)
        d1_upper = calc_d1(s, upper_be, r, vol, t)

        if d1_lower is None or d1_upper is None:
            return 0.0

        d2_lower = calc_d2(d1_lower, vol, t)
        d2_upper = calc_d2(d1_upper, vol, t)

        if d2_lower is None or d2_upper is None:
            return 0.0

        # P(S_T > Lower BE) - P(S_T > Upper BE)
        return calc_n(d2_lower) - calc_n(d2_upper)

    def calc_put_exercise_probability(self) -> float:
        """Calculate probability of put being exercised."""
        if self._put_d2 is None:
            return 0.0
        return calc_n(-self._put_d2)

    def calc_call_exercise_probability(self) -> float:
        """Calculate probability of call being exercised."""
        if self._call_d2 is None:
            return 0.0
        return calc_n(self._call_d2)

    def _calc_capital_at_risk(self) -> float:
        """Capital at risk for strangle.

        Typically the margin requirement is based on the higher risk leg.
        Here we use put strike as a conservative estimate.
        """
        return max(self.put_leg.strike, self.call_leg.strike)
