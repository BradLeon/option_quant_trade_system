"""Long Call pricer implementation.

Buy a call option for bullish speculation or leveraged upside exposure.
Mirror of ShortCallPricer: E[Long Call] = -E[Short Call].
"""

import math

from src.data.models.option import Greeks, OptionType
from src.engine.bs.core import calc_d1, calc_d2, calc_d3, calc_n
from src.engine.models import BSParams
from src.engine.models.enums import PositionSide
from src.engine.models.pricing import OptionLeg, PricingParams
from src.engine.pricing.base import OptionPricer


class LongCallPricer(OptionPricer):
    """Long Call (Buy Call) pricer.

    Profit/Loss Profile:
    - Max Profit: Unlimited (stock can rise indefinitely)
    - Max Loss: Premium paid
    - Breakeven: Strike + Premium

    Use case:
    - Bullish outlook
    - Leveraged upside exposure with limited risk
    - Alternative to buying stock outright
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
        """Initialize Long Call strategy.

        Args:
            spot_price: Current stock price (S)
            strike_price: Call strike price (K)
            premium: Premium paid per share (C)
            volatility: Implied volatility (σ)
            time_to_expiry: Time to expiration in years (T)
            risk_free_rate: Annual risk-free rate (r)
            hv: Historical volatility (optional)
            dte: Days to expiration (optional)
            delta: Option delta (optional)
            gamma: Option gamma (optional)
            theta: Option theta - daily time decay (optional)
            vega: Option vega (optional)
        """
        leg = OptionLeg(
            option_type=OptionType.CALL,
            side=PositionSide.LONG,
            strike=strike_price,
            premium=premium,
            greeks=Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega),
        )
        params = PricingParams(
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

        # Cache B-S parameters (IV-based, for variance/greeks)
        self._d1 = calc_d1(bs_params)
        self._d2 = calc_d2(bs_params, self._d1) if self._d1 else None
        self._d3 = calc_d3(bs_params, self._d2) if self._d2 else None

        # Cache HV-based d1/d2 for expected return (physical measure)
        sigma_real = hv if hv and hv > 0 else volatility
        if sigma_real != volatility:
            bs_params_hv = BSParams(
                spot_price=spot_price,
                strike_price=strike_price,
                risk_free_rate=risk_free_rate,
                volatility=sigma_real,
                time_to_expiry=time_to_expiry,
                is_call=True,
            )
            self._d1_hv = calc_d1(bs_params_hv)
            self._d2_hv = calc_d2(bs_params_hv, self._d1_hv) if self._d1_hv else None
        else:
            self._d1_hv = self._d1
            self._d2_hv = self._d2

    def calc_expected_return(self) -> float:
        """Calculate expected return for long call (physical measure).

        E[π] = N(d2_hv) * [S * e^(rT) * N(d1_hv) / N(d2_hv) - K] - C

        This is the exact negation of ShortCallPricer.calc_expected_return().

        Returns:
            Expected return in dollar amount per share.
        """
        if self._d1_hv is None or self._d2_hv is None:
            return 0.0

        c = self.leg.premium
        k = self.leg.strike
        s = self.params.spot_price
        r = self.params.risk_free_rate
        t = self.params.time_to_expiry

        n_d1 = calc_n(self._d1_hv)
        n_d2 = calc_n(self._d2_hv)

        if n_d2 == 0:
            # No exercise probability, expected return = -premium
            return -c

        # Expected stock price if exercised (conditional expectation)
        exp_rt = math.exp(r * t)
        expected_stock_if_exercised = exp_rt * s * n_d1 / n_d2

        # E[π_long] = N(d2) * (Expected_Stock - K) - C = -E[π_short]
        expected_return = n_d2 * (expected_stock_if_exercised - k) - c

        return expected_return

    def calc_return_variance(self) -> float:
        """Calculate variance of return for long call.

        Long call payoff = max(S_T - K, 0) - C
        Variance is the same as short call (negation doesn't change variance).

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

        # E[π²] for long call: payoff = max(S_T - K, 0) - C
        # Same variance structure as short call (Var[-X] = Var[X])
        e_pi_squared = (
            c**2 * (1 - n_d2)
            + (c + k) ** 2 * n_d2
            - 2 * (c + k) * exp_rt * s * n_d1
            + s**2 * exp_2rt_sigma2t * n_d3
        )

        e_pi = self.calc_expected_return()
        variance = e_pi_squared - e_pi**2

        return max(0.0, variance)

    def calc_max_profit(self) -> float:
        """Calculate maximum profit (theoretically unlimited).

        We return 10x strike as a practical upper bound (same convention as ShortCallPricer).
        """
        return 10 * self.leg.strike

    def calc_max_loss(self) -> float:
        """Calculate maximum loss (premium paid)."""
        return self.leg.premium

    def calc_breakeven(self) -> float:
        """Calculate breakeven price (strike + premium)."""
        return self.leg.strike + self.leg.premium

    def calc_win_probability(self) -> float:
        """Calculate probability of profit (stock rises above breakeven).

        Win probability = N(d2) evaluated at breakeven = K + C.

        Returns:
            Win probability (0-1).
        """
        breakeven = self.calc_breakeven()

        be_params = BSParams(
            spot_price=self.params.spot_price,
            strike_price=breakeven,
            risk_free_rate=self.params.risk_free_rate,
            volatility=self.params.volatility,
            time_to_expiry=self.params.time_to_expiry,
            is_call=True,
        )

        d1_be = calc_d1(be_params)
        if d1_be is None:
            return 0.0

        d2_be = calc_d2(be_params, d1_be)
        if d2_be is None:
            return 0.0

        # P(S_T > breakeven) = N(d2)
        return calc_n(d2_be)

    def calc_margin_requirement(self) -> float:
        """Long options have no margin — capital = premium paid."""
        return self.leg.premium

    def get_effective_margin(self) -> float:
        """For long options, capital at risk = premium paid."""
        return self.leg.premium

    # ---- Seller-specific metrics: return None for buyers ----

    def calc_tgr(self) -> float | None:
        """TGR is a seller metric (theta as income). Not applicable to buyers."""
        return None

    def calc_sas(self) -> float | None:
        """SAS is a seller attractiveness score. Not applicable to buyers."""
        return None

    def calc_premium_rate(self) -> float | None:
        """Premium rate is a seller metric. Not applicable to buyers."""
        return None

    def calc_theta_margin_ratio(self) -> float | None:
        """Theta/margin ratio is a seller capital efficiency metric. Not applicable to buyers."""
        return None

    # ---- ROC redefined for buyers ----

    def calc_roc(self) -> float | None:
        """Calculate annualized ROC for long call.

        ROC = (expected_return / premium_paid) × (365 / DTE)

        For buyers, capital = premium paid (no margin concept).
        """
        from src.engine.position.risk_return import calc_roc_from_dte

        dte = self.params.dte
        if dte is None or dte <= 0:
            return None

        expected_return = self.calc_expected_return()
        premium = self.leg.premium
        if premium <= 0:
            return None

        return calc_roc_from_dte(expected_return, premium, dte)

    def calc_expected_roc(self) -> float | None:
        """For buyers, expected_roc equals roc (both use expected_return / premium)."""
        return self.calc_roc()
