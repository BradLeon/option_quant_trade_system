"""Threshold checker for Dashboard metrics.

Determines AlertLevel for various metrics based on configuration thresholds.
"""

from typing import Optional

from src.business.config.monitoring_config import MonitoringConfig, ThresholdRange
from src.business.monitoring.models import AlertLevel


class ThresholdChecker:
    """Threshold checker - determines AlertLevel for metrics.

    Uses monitoring configuration to check if metric values fall
    within green/yellow/red ranges. Uses a generic _check_range method
    for consistent threshold checking across all metrics.
    """

    def __init__(self, config: Optional[MonitoringConfig] = None):
        """Initialize threshold checker.

        Args:
            config: Monitoring configuration, uses defaults if None
        """
        self.config = config or MonitoringConfig.load()

    def _check_range(self, value: float, threshold: ThresholdRange) -> AlertLevel:
        """Generic threshold range checker.

        Logic:
        1. Check RED thresholds first (value exceeds red_above or below red_below)
        2. Check GREEN range (value within green range)
        3. Otherwise YELLOW (value outside green but not in red)

        Args:
            value: Current metric value
            threshold: ThresholdRange configuration

        Returns:
            AlertLevel based on thresholds
        """
        # Check red thresholds first (highest priority)
        if threshold.red_above is not None and value > threshold.red_above:
            return AlertLevel.RED
        if threshold.red_below is not None and value < threshold.red_below:
            return AlertLevel.RED

        # Check green range - if value is within green range, it's safe
        if threshold.green:
            low, high = threshold.green
            # Handle infinity properly
            if low <= value <= high or (high == float("inf") and value >= low):
                return AlertLevel.GREEN

        # Not in red, not in green -> yellow
        return AlertLevel.YELLOW

    # ==================== Portfolio Level ====================

    def check_delta(self, value: Optional[float]) -> AlertLevel:
        """Check beta-weighted delta threshold.

        Args:
            value: Beta-weighted delta value

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.beta_weighted_delta)

    def check_theta(self, value: Optional[float]) -> AlertLevel:
        """Check portfolio theta threshold.

        Positive theta (time decay benefit) is green.
        Negative theta (paying for time) depends on magnitude.

        Args:
            value: Total theta value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.portfolio_theta)

    def check_vega(self, value: Optional[float]) -> AlertLevel:
        """Check portfolio vega threshold.

        Args:
            value: Total vega value

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.portfolio_vega)

    def check_gamma(self, value: Optional[float]) -> AlertLevel:
        """Check portfolio gamma threshold.

        Negative gamma (short options) is more risky.

        Args:
            value: Total gamma value

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.portfolio_gamma)

    def check_tgr(self, value: Optional[float]) -> AlertLevel:
        """Check Theta/Gamma Ratio threshold.

        Higher TGR is better for theta strategies.

        Args:
            value: Portfolio TGR value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.portfolio_tgr)

    def check_concentration(self, value: Optional[float]) -> AlertLevel:
        """Check concentration (HHI) threshold.

        Lower HHI means more diversified.
        HHI = 1.0 means single position
        HHI = 0.25 means 4 equal positions

        Args:
            value: Herfindahl-Hirschman Index value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.concentration_hhi)

    # ==================== NLV-Normalized Percentage Metrics ====================

    def check_delta_pct(self, value: Optional[float]) -> AlertLevel:
        """Check beta-weighted delta percentage threshold.

        Measures directional leverage relative to account size.
        ±20% green, ±50% red.

        Args:
            value: BWD / NLV ratio

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.beta_weighted_delta_pct)

    def check_gamma_pct(self, value: Optional[float]) -> AlertLevel:
        """Check gamma percentage threshold.

        Measures convexity/crash risk. More negative is worse.
        > -0.1% green, < -0.5% red.

        Args:
            value: Gamma / NLV ratio

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.gamma_pct)

    def check_vega_pct(self, value: Optional[float]) -> AlertLevel:
        """Check vega percentage threshold.

        Measures volatility risk. Short vega (negative) is strictly monitored.
        ±0.3% green, < -0.5% red (asymmetric - short vega is dangerous).

        Args:
            value: Vega / NLV ratio

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.vega_pct)

    def check_theta_pct(self, value: Optional[float]) -> AlertLevel:
        """Check theta percentage threshold.

        Measures daily time value accrual rate.
        0.05%~0.15% green, > 0.30% or < 0% red (dual red zones).

        Args:
            value: Theta / NLV ratio

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.theta_pct)

    def check_iv_hv_quality(self, value: Optional[float]) -> AlertLevel:
        """Check vega-weighted IV/HV quality threshold.

        Measures option pricing quality for short positions.
        > 1.0 green (selling overpriced), < 0.8 red (underselling).

        Args:
            value: Vega-weighted IV/HV ratio

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.portfolio.vega_weighted_iv_hv)

    # ==================== Capital Level ====================

    def check_sharpe(self, value: Optional[float]) -> AlertLevel:
        """Check Sharpe Ratio threshold.

        Higher Sharpe is better.
        Uses unified ThresholdRange configuration.

        Args:
            value: Sharpe ratio value

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.capital.sharpe)

    def check_kelly_usage(self, value: Optional[float]) -> AlertLevel:
        """Check Kelly usage threshold.

        Optimal Kelly usage is 0.5-1.0.
        Uses unified ThresholdRange configuration.

        Args:
            value: Kelly usage ratio

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.capital.kelly_usage)

    def check_margin_usage(self, value: Optional[float]) -> AlertLevel:
        """Check margin usage threshold.

        Lower margin usage is safer.
        Uses unified ThresholdRange configuration.

        Args:
            value: Margin usage ratio (0-1)

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.capital.margin_usage)

    def check_drawdown(self, value: Optional[float]) -> AlertLevel:
        """Check drawdown threshold.

        Lower drawdown is better.
        Uses unified ThresholdRange configuration.

        Args:
            value: Current drawdown ratio (0-1)

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.capital.drawdown)

    # ==================== Position Level ====================

    def check_otm_pct(self, value: Optional[float]) -> AlertLevel:
        """Check OTM% (Out of The Money Percentage) threshold.

        Unified formula: Put=(S-K)/S, Call=(K-S)/S
        Higher OTM% is safer for short options.
        ≥10% green, <5% red.

        Args:
            value: OTM percentage as decimal

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.otm_pct)

    def check_gamma_risk_pct(self, value: Optional[float]) -> AlertLevel:
        """Check Gamma Risk% (Gamma/Margin) threshold.

        Measures gamma risk relative to margin requirement.
        ≤0.5% green, >1% red.

        Args:
            value: Gamma/Margin ratio as decimal

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.gamma_risk_pct)

    def check_expected_roc(self, value: Optional[float]) -> AlertLevel:
        """Check Expected ROC threshold.

        Expected return on capital based on probability analysis.
        ≥10% green, <0% red.

        Args:
            value: Expected ROC as decimal

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.expected_roc)

    def check_win_probability(self, value: Optional[float]) -> AlertLevel:
        """Check Win Probability threshold.

        Probability of the option expiring worthless (for short positions).
        ≥70% green, <55% red.

        Args:
            value: Win probability as decimal (0-1)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.win_probability)

    def check_position_pnl(self, value: Optional[float]) -> AlertLevel:
        """Check position P&L% threshold.

        ≥50% green (take profit), <0% red (stop loss).

        Args:
            value: Unrealized P&L percentage as decimal

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.pnl)

    def check_prei(self, value: Optional[float]) -> AlertLevel:
        """Check PREI (Position Risk Exposure Index) threshold.

        Lower PREI is better (less risk per unit return).
        Uses unified ThresholdRange configuration.

        Args:
            value: PREI value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.prei)

    def check_sas(self, value: Optional[float]) -> AlertLevel:
        """Check SAS (Strategy Assessment Score) threshold.

        Higher SAS is better.
        Uses unified ThresholdRange configuration.

        Args:
            value: SAS score

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.sas)

    def check_position_tgr(self, value: Optional[float]) -> AlertLevel:
        """Check position-level TGR threshold.

        Uses position-level ThresholdRange configuration.

        Args:
            value: Position TGR value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.tgr)

    def check_dte(self, value: Optional[int]) -> AlertLevel:
        """Check DTE (Days to Expiration) threshold.

        Lower DTE means closer to expiration, higher risk.
        Uses unified ThresholdRange configuration.

        Args:
            value: Days to expiration

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(float(value), self.config.position.dte)

    def check_roc(self, value: Optional[float]) -> AlertLevel:
        """Check ROC (Return on Capital) threshold.

        Higher ROC is better.
        Uses unified ThresholdRange configuration.

        Args:
            value: ROC as decimal (0.28 = 28%)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.roc)

    def check_position_delta(self, value: Optional[float]) -> AlertLevel:
        """Check position-level delta threshold.

        Uses position-level ThresholdRange configuration.

        Args:
            value: Position delta value (absolute)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(abs(value), self.config.position.delta)

    def check_position_gamma(self, value: Optional[float]) -> AlertLevel:
        """Check position-level gamma threshold.

        Uses position-level ThresholdRange configuration.

        Args:
            value: Position gamma value (absolute)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(abs(value), self.config.position.gamma)

    def check_position_iv_hv(self, value: Optional[float]) -> AlertLevel:
        """Check position-level IV/HV ratio threshold.

        Uses position-level ThresholdRange configuration.

        Args:
            value: IV/HV ratio

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN
        return self._check_range(value, self.config.position.iv_hv)

    def get_position_overall_level(
        self,
        prei: Optional[float] = None,
        dte: Optional[int] = None,
        tgr: Optional[float] = None,
        otm_pct: Optional[float] = None,
        delta: Optional[float] = None,
        expected_roc: Optional[float] = None,
        win_probability: Optional[float] = None,
    ) -> Optional[AlertLevel]:
        """Determine overall alert level for a position.

        Returns the most severe alert level among key metrics.
        Returns None if no alerts (all green).

        Checks the most critical metrics:
        - OTM% (core risk indicator)
        - |Delta| (directional risk)
        - DTE (time to expiration)
        - Expected ROC (expected return)
        - Win Probability (probability of profit)
        - PREI (risk exposure)
        - TGR (theta/gamma efficiency)

        Args:
            prei: PREI value
            dte: Days to expiration
            tgr: Position TGR
            otm_pct: OTM percentage
            delta: Position delta (absolute value will be used)
            expected_roc: Expected ROC
            win_probability: Win probability

        Returns:
            Most severe AlertLevel, or None if all green
        """
        levels = [
            self.check_otm_pct(otm_pct),
            self.check_position_delta(delta),
            self.check_dte(dte),
            self.check_expected_roc(expected_roc),
            self.check_win_probability(win_probability),
            self.check_prei(prei),
            self.check_position_tgr(tgr),
        ]

        if AlertLevel.RED in levels:
            return AlertLevel.RED
        if AlertLevel.YELLOW in levels:
            return AlertLevel.YELLOW
        # Return None to indicate no icon needed
        return None
