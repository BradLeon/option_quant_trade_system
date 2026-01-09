"""Tests for monitoring monitors - basic unit tests"""

import pytest

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    CapitalMetrics,
    MonitorResult,
    MonitorStatus,
    PositionData,
)


class TestMonitorModels:
    """Basic tests for monitor-related models"""

    def test_create_position_data(self):
        """Test creating PositionData"""
        pos = PositionData(
            position_id="pos-001",
            symbol="AAPL250117P180",
            underlying="AAPL",
            option_type="put",
            quantity=-1,
            entry_price=3.50,
            current_price=2.80,
            strike=180.0,
            expiry="2025-01-17",
            underlying_price=185.0,
            delta=-0.25,
            gamma=0.02,
            theta=0.05,
            vega=-0.15,
            iv=0.28,
            dte=25,
        )
        assert pos.underlying == "AAPL"
        assert pos.option_type == "put"

    def test_position_moneyness_otm(self):
        """Test OTM put position moneyness"""
        pos = PositionData(
            position_id="pos-001",
            symbol="AAPL250117P180",
            underlying="AAPL",
            option_type="put",
            quantity=-1,
            entry_price=3.50,
            current_price=2.80,
            strike=180.0,
            expiry="2025-01-17",
            underlying_price=200.0,  # 远离 strike
            moneyness=0.111,  # (S-K)/K = (200-180)/180, pre-calculated by DataBridge
        )
        assert pos.moneyness > 0  # OTM put

    def test_position_moneyness_itm(self):
        """Test ITM put position moneyness"""
        pos = PositionData(
            position_id="pos-001",
            symbol="AAPL250117P180",
            underlying="AAPL",
            option_type="put",
            quantity=-1,
            entry_price=3.50,
            current_price=8.00,
            strike=180.0,
            expiry="2025-01-17",
            underlying_price=170.0,  # 低于 strike
            moneyness=-0.0556,  # (S-K)/K = (170-180)/180, pre-calculated by DataBridge
        )
        assert pos.moneyness < 0  # ITM put

    def test_create_capital_metrics(self):
        """Test creating CapitalMetrics"""
        cm = CapitalMetrics(
            total_equity=100000.0,
            cash_balance=50000.0,
            # Core Risk Control Metrics (4 Pillars)
            margin_utilization=0.25,
            cash_ratio=0.50,
            gross_leverage=1.5,
            stress_test_loss=0.08,
        )
        assert cm.total_equity == 100000.0
        assert cm.margin_utilization == 0.25

    def test_create_alert(self):
        """Test creating Alert"""
        alert = Alert(
            level=AlertLevel.RED,
            alert_type=AlertType.STOP_LOSS,
            message="持仓亏损超过阈值",
            symbol="AAPL",
            current_value=-500.0,
            threshold_value=-300.0,
        )
        assert alert.level == AlertLevel.RED
        assert alert.alert_type == AlertType.STOP_LOSS

    def test_monitor_result_alert_filtering(self):
        """Test MonitorResult alert filtering"""
        alerts = [
            Alert(
                level=AlertLevel.RED,
                alert_type=AlertType.STOP_LOSS,
                message="止损",
            ),
            Alert(
                level=AlertLevel.YELLOW,
                alert_type=AlertType.DELTA_EXPOSURE,
                message="Delta",
            ),
            Alert(
                level=AlertLevel.GREEN,
                alert_type=AlertType.PROFIT_TARGET,
                message="止盈",
            ),
        ]
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=alerts,
        )

        assert len(result.red_alerts) == 1
        assert len(result.yellow_alerts) == 1
        assert len(result.green_alerts) == 1

    def test_monitor_result_summary(self):
        """Test MonitorResult summary property"""
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            total_positions=5,
        )
        summary = result.summary

        assert summary["status"] == "green"
        assert summary["total_positions"] == 5
        assert summary["red_alerts"] == 0


class TestAlertCreation:
    """Tests for creating different alert types"""

    def test_delta_exposure_alert(self):
        alert = Alert(
            level=AlertLevel.YELLOW,
            alert_type=AlertType.DELTA_EXPOSURE,
            message="Beta 加权 Delta 暴露过高",
            current_value=0.35,
            threshold_value=0.30,
            suggested_action="考虑减少方向性敞口",
        )
        assert alert.alert_type == AlertType.DELTA_EXPOSURE
        assert alert.current_value > alert.threshold_value

    def test_margin_utilization_alert(self):
        alert = Alert(
            level=AlertLevel.RED,
            alert_type=AlertType.MARGIN_UTILIZATION,
            message="保证金使用率过高",
            current_value=0.75,
            threshold_value=0.70,
            suggested_action="强制去杠杆：减仓直到保证金使用率低于40%",
        )
        assert alert.alert_type == AlertType.MARGIN_UTILIZATION
        assert alert.level == AlertLevel.RED

    def test_dte_warning_alert(self):
        alert = Alert(
            level=AlertLevel.YELLOW,
            alert_type=AlertType.DTE_WARNING,
            message="持仓临近到期",
            symbol="AAPL250117P180",
            current_value=3,
            threshold_value=5,
            suggested_action="考虑平仓或移仓",
        )
        assert alert.alert_type == AlertType.DTE_WARNING
        assert alert.symbol is not None

    def test_profit_target_alert(self):
        alert = Alert(
            level=AlertLevel.GREEN,
            alert_type=AlertType.PROFIT_TARGET,
            message="达到止盈目标",
            symbol="MSFT250117P400",
            current_value=0.75,
            threshold_value=0.50,
            suggested_action="考虑平仓锁定利润",
        )
        assert alert.alert_type == AlertType.PROFIT_TARGET
        assert alert.level == AlertLevel.GREEN
