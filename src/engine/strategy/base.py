"""Base classes for option strategies.

Contains the abstract OptionStrategy base class.
For data models, import from src.engine.models directly.
"""

import math
from abc import ABC, abstractmethod

from src.data.models.option import Greeks
from src.engine.models.strategy import OptionLeg, StrategyMetrics, StrategyParams


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

    def calc_sharpe_ratio(self) -> float | None:
        """Calculate Sharpe ratio.

        SR = (E[π] - Rf) / Std[π]
        Rf = margin × (e^(rT) - 1)

        Returns:
            Sharpe ratio, or None if std is zero.
        """
        e_pi = self.calc_expected_return()
        std_pi = self.calc_return_std()

        if std_pi <= 0:
            return None

        # Use actual margin requirement from broker formula
        try:
            margin = self.calc_margin_requirement()
        except Exception:
            # Fallback to capital at risk if margin calc fails
            margin = self._calc_capital_at_risk()

        # Risk-free return on margin capital
        rf = margin * (math.exp(self.params.risk_free_rate * self.params.time_to_expiry) - 1)

        return (e_pi - rf) / std_pi

    def calc_sharpe_ratio_annualized(self) -> float | None:
        """Calculate annualized Sharpe ratio.

        SR_annual = SR / sqrt(T)

        Returns:
            Annualized Sharpe ratio, or None if not calculable.
        """
        sr = self.calc_sharpe_ratio()
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

    def _get_total_gamma(self) -> float | None:
        """Get total gamma across all legs (position-adjusted).

        Returns:
            Sum of leg gammas adjusted for position side, or None if any leg missing gamma.
        """
        total = 0.0
        for leg in self.legs:
            if leg.gamma is None:
                return None
            total += leg.gamma * leg.sign * leg.quantity
        return total

    def _get_total_vega(self) -> float | None:
        """Get total vega across all legs (position-adjusted).

        Returns:
            Sum of leg vegas adjusted for position side, or None if any leg missing vega.
        """
        total = 0.0
        for leg in self.legs:
            if leg.vega is None:
                return None
            total += leg.vega * leg.sign * leg.quantity
        return total

    def _get_total_theta(self) -> float | None:
        """Get total theta across all legs (position-adjusted).

        Returns:
            Sum of leg thetas adjusted for position side, or None if any leg missing theta.
        """
        total = 0.0
        for leg in self.legs:
            if leg.theta is None:
                return None
            total += leg.theta * leg.sign * leg.quantity
        return total

    def _get_iv(self) -> float | None:
        """Get implied volatility for strategy.

        Uses first leg's volatility or strategy-level volatility.
        """
        if self.leg and self.leg.volatility is not None:
            return self.leg.volatility
        return self.params.volatility

    def calc_prei(self) -> float | None:
        """Calculate Position Risk Exposure Index (PREI).

        PREI measures tail risk exposure based on gamma, vega, and DTE.
        Requires: leg.gamma, leg.vega, params.dte

        Returns:
            PREI score (0-100), or None if insufficient data.
        """
        from src.engine.models.position import Position
        from src.engine.position.risk_return import calc_prei

        gamma = self._get_total_gamma()
        vega = self._get_total_vega()
        dte = self.params.dte

        if gamma is None or vega is None or dte is None:
            return None

        # Create temporary Position for calculation
        temp_position = Position(
            symbol="strategy",
            quantity=1,
            greeks=Greeks(gamma=gamma, vega=vega),
            underlying_price=self.params.spot_price,
            dte=dte,
        )
        return calc_prei(temp_position)

    def calc_sas(self) -> float | None:
        """Calculate Strategy Attractiveness Score (SAS).

        SAS evaluates option selling attractiveness based on IV/HV, Sharpe, and win prob.
        Requires: params.volatility (IV), params.hv, sharpe_ratio, win_probability

        Returns:
            SAS score (0-100), or None if insufficient data.
        """
        from src.engine.position.option_metrics import calc_sas

        iv = self._get_iv()
        hv = self.params.hv
        sharpe_ratio = self.calc_sharpe_ratio()
        win_probability = self.calc_win_probability()

        if iv is None or hv is None or sharpe_ratio is None:
            return None

        return calc_sas(iv, hv, sharpe_ratio, win_probability)

    def calc_tgr(self) -> float | None:
        """Calculate Theta/Gamma Ratio (TGR).

        TGR measures theta income per unit of gamma risk.
        Requires: leg.theta, leg.gamma

        Returns:
            TGR value, or None if insufficient data.
        """
        from src.engine.models.position import Position
        from src.engine.position.risk_return import calc_tgr

        theta = self._get_total_theta()
        gamma = self._get_total_gamma()

        if theta is None or gamma is None:
            return None

        # Create temporary Position for calculation
        temp_position = Position(
            symbol="strategy",
            quantity=1,
            greeks=Greeks(theta=theta, gamma=gamma),
        )
        return calc_tgr(temp_position)

    def calc_roc(self) -> float | None:
        """Calculate annualized Return on Capital (ROC).

        For option strategies, ROC measures the premium received relative to
        margin requirement, annualized to DTE.

        ROC = (premium / margin) * (365 / dte)

        Returns:
            Annualized ROC, or None if insufficient data.
        """
        from src.engine.position.risk_return import calc_roc_from_dte

        dte = self.params.dte
        if dte is None or dte <= 0:
            return None

        # For option strategies, use premium (actual income) not expected return
        premium = self.leg.premium if self.leg else 0.0
        if premium <= 0:
            return None

        # Use actual margin requirement from broker formula
        try:
            margin = self.calc_margin_requirement()
        except Exception:
            # Fallback to capital at risk if margin calc fails
            margin = self._calc_capital_at_risk()

        if margin <= 0:
            return None

        return calc_roc_from_dte(premium, margin, dte)

    def calc_expected_roc(self) -> float | None:
        """Calculate annualized Expected Return on Capital.

        Similar to calc_roc() but uses expected_return instead of premium.
        While ROC uses the certain premium income, expected ROC uses the
        probability-weighted expected return from the strategy.

        Formula: (expected_return / capital) × (365 / dte)

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

        # Use actual margin requirement from broker formula
        try:
            capital = self.calc_margin_requirement()
        except Exception:
            # Fallback to capital at risk if margin calc fails
            capital = self._calc_capital_at_risk()

        if capital is None or capital <= 0:
            return None

        return calc_roc_from_dte(expected_return, capital, dte)

    def calc_metrics(self) -> StrategyMetrics:
        """Calculate all metrics for the strategy.

        Extended metrics (prei, sas, tgr, roc) are calculated automatically
        if the required data is available in legs and params.

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
            sharpe_ratio=self.calc_sharpe_ratio(),
            kelly_fraction=self.calc_kelly_fraction(),
            prei=self.calc_prei(),
            sas=self.calc_sas(),
            tgr=self.calc_tgr(),
            roc=self.calc_roc(),
            expected_roc=self.calc_expected_roc(),
        )
