"""Threshold checker for Dashboard metrics.

Determines AlertLevel for various metrics based on configuration thresholds.
"""

from typing import Optional

from src.business.config.monitoring_config import MonitoringConfig
from src.business.monitoring.models import AlertLevel


class ThresholdChecker:
    """Threshold checker - determines AlertLevel for metrics.

    Uses monitoring configuration to check if metric values fall
    within green/yellow/red ranges.
    """

    def __init__(self, config: Optional[MonitoringConfig] = None):
        """Initialize threshold checker.

        Args:
            config: Monitoring configuration, uses defaults if None
        """
        self.config = config or MonitoringConfig.load()

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

        threshold = self.config.portfolio.beta_weighted_delta

        if threshold.red_above and value > threshold.red_above:
            return AlertLevel.RED
        if threshold.red_below and value < threshold.red_below:
            return AlertLevel.RED
        if threshold.yellow:
            low, high = threshold.yellow
            if value < low or value > high:
                return AlertLevel.YELLOW
        if threshold.green:
            low, high = threshold.green
            if low <= value <= high:
                return AlertLevel.GREEN

        return AlertLevel.GREEN

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

        # For theta, positive is good (selling premium)
        if value >= 0:
            return AlertLevel.GREEN
        # Moderate negative theta
        if value >= -100:
            return AlertLevel.YELLOW
        # Large negative theta
        return AlertLevel.RED

    def check_vega(self, value: Optional[float]) -> AlertLevel:
        """Check portfolio vega threshold.

        Args:
            value: Total vega value

        Returns:
            AlertLevel based on thresholds
        """
        if value is None:
            return AlertLevel.GREEN

        threshold = self.config.portfolio.portfolio_vega

        if threshold.red_above and value > threshold.red_above:
            return AlertLevel.RED
        if threshold.red_below and value < threshold.red_below:
            return AlertLevel.RED
        if threshold.yellow:
            low, high = threshold.yellow
            if value < low or value > high:
                return AlertLevel.YELLOW
        if threshold.green:
            low, high = threshold.green
            if low <= value <= high:
                return AlertLevel.GREEN

        return AlertLevel.GREEN

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

        threshold = self.config.portfolio.portfolio_gamma

        if threshold.red_below and value < threshold.red_below:
            return AlertLevel.RED
        if threshold.yellow:
            low, high = threshold.yellow
            if value < low:
                return AlertLevel.YELLOW
        if threshold.green:
            low, high = threshold.green
            if low <= value <= high:
                return AlertLevel.GREEN

        return AlertLevel.GREEN

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

        thresholds = self.config.portfolio

        if value >= thresholds.tgr_green_above:
            return AlertLevel.GREEN
        if value < thresholds.tgr_red_below:
            return AlertLevel.RED
        # Between red and green is yellow
        return AlertLevel.YELLOW

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

        # Use max_concentration threshold
        max_conc = self.config.portfolio.max_concentration

        # HHI > 0.5 means effectively < 2 positions
        if value > 0.5:
            return AlertLevel.RED
        # HHI > 0.25 means effectively < 4 positions
        if value > max_conc or value > 0.25:
            return AlertLevel.YELLOW

        return AlertLevel.GREEN

    # ==================== Capital Level ====================

    def check_sharpe(self, value: Optional[float]) -> AlertLevel:
        """Check Sharpe Ratio threshold.

        Higher Sharpe is better.

        Args:
            value: Sharpe ratio value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        thresholds = self.config.capital

        if value >= thresholds.sharpe_green_above:
            return AlertLevel.GREEN
        if value < thresholds.sharpe_red_below:
            return AlertLevel.RED

        return AlertLevel.YELLOW

    def check_kelly_usage(self, value: Optional[float]) -> AlertLevel:
        """Check Kelly usage threshold.

        Optimal Kelly usage is 0.5-1.0.
        Below 0.5 is opportunity (green with different meaning).
        Above 1.0 is over-leveraged (red).

        Args:
            value: Kelly usage ratio

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        thresholds = self.config.capital

        if value > thresholds.kelly_usage_red_above:
            return AlertLevel.RED
        if value < thresholds.kelly_usage_opportunity_below:
            # Below optimal range - opportunity to add
            return AlertLevel.GREEN
        green_low, green_high = thresholds.kelly_usage_green_range
        if green_low <= value <= green_high:
            return AlertLevel.GREEN

        return AlertLevel.YELLOW

    def check_margin_usage(self, value: Optional[float]) -> AlertLevel:
        """Check margin usage threshold.

        Lower margin usage is safer.

        Args:
            value: Margin usage ratio (0-1)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        thresholds = self.config.capital

        if value > thresholds.margin_red_above:
            return AlertLevel.RED
        if value > thresholds.margin_warning_above:
            return AlertLevel.YELLOW
        if value < thresholds.margin_green_below:
            return AlertLevel.GREEN

        return AlertLevel.YELLOW

    def check_drawdown(self, value: Optional[float]) -> AlertLevel:
        """Check drawdown threshold.

        Lower drawdown is better.

        Args:
            value: Current drawdown ratio (0-1)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        thresholds = self.config.capital

        if value > thresholds.max_drawdown_red_pct:
            return AlertLevel.RED
        if value > thresholds.max_drawdown_warning_pct:
            return AlertLevel.YELLOW

        return AlertLevel.GREEN

    # ==================== Position Level ====================

    def check_prei(self, value: Optional[float]) -> AlertLevel:
        """Check PREI (Position Risk Exposure Index) threshold.

        Lower PREI is better (less risk per unit return).

        Args:
            value: PREI value

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        thresholds = self.config.position

        if value > thresholds.prei_red_above:
            return AlertLevel.RED
        if value < thresholds.prei_green_below:
            return AlertLevel.GREEN

        return AlertLevel.YELLOW

    def check_sas(self, value: Optional[float]) -> AlertLevel:
        """Check SAS (Strategy Assessment Score) threshold.

        Higher SAS is better.

        Args:
            value: SAS score

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        # SAS scoring: higher is better
        # Green > 80, Yellow 60-80, Red < 60
        if value >= 80:
            return AlertLevel.GREEN
        if value < 60:
            return AlertLevel.RED

        return AlertLevel.YELLOW

    def check_position_tgr(self, value: Optional[float]) -> AlertLevel:
        """Check position-level TGR threshold.

        Uses same thresholds as portfolio TGR.

        Args:
            value: Position TGR value

        Returns:
            AlertLevel
        """
        return self.check_tgr(value)

    def check_dte(self, value: Optional[int]) -> AlertLevel:
        """Check DTE (Days to Expiration) threshold.

        Lower DTE means closer to expiration, higher risk.

        Args:
            value: Days to expiration

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        thresholds = self.config.position

        if value <= thresholds.dte_urgent_days:
            return AlertLevel.RED
        if value <= thresholds.dte_warning_days:
            return AlertLevel.YELLOW

        return AlertLevel.GREEN

    def check_roc(self, value: Optional[float]) -> AlertLevel:
        """Check ROC (Return on Capital) threshold.

        Higher ROC is better.

        Args:
            value: ROC as decimal (0.28 = 28%)

        Returns:
            AlertLevel
        """
        if value is None:
            return AlertLevel.GREEN

        # ROC > 30% is excellent
        if value >= 0.30:
            return AlertLevel.GREEN
        # ROC < 10% is concerning
        if value < 0.10:
            return AlertLevel.RED

        return AlertLevel.YELLOW

    def get_position_overall_level(
        self,
        prei: Optional[float],
        dte: Optional[int],
        tgr: Optional[float],
    ) -> Optional[AlertLevel]:
        """Determine overall alert level for a position.

        Returns the most severe alert level among key metrics.
        Returns None if no alerts (all green).

        Args:
            prei: PREI value
            dte: Days to expiration
            tgr: Position TGR

        Returns:
            Most severe AlertLevel, or None if all green
        """
        levels = [
            self.check_prei(prei),
            self.check_dte(dte),
            self.check_position_tgr(tgr),
        ]

        if AlertLevel.RED in levels:
            return AlertLevel.RED
        if AlertLevel.YELLOW in levels:
            return AlertLevel.YELLOW
        # Return None to indicate no icon needed
        return None
