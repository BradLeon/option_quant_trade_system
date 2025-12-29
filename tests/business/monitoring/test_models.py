"""Tests for monitoring models"""

import pytest

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    CapitalMetrics,
    MonitorResult,
    MonitorStatus,
    PortfolioMetrics,
    PositionData,
)


class TestAlertLevel:
    """Tests for AlertLevel enum"""

    def test_alert_levels(self):
        assert AlertLevel.RED.value == "red"
        assert AlertLevel.YELLOW.value == "yellow"
        assert AlertLevel.GREEN.value == "green"


class TestAlertType:
    """Tests for AlertType enum"""

    def test_alert_types(self):
        assert AlertType.DELTA_EXPOSURE.value == "delta_exposure"
        assert AlertType.STOP_LOSS.value == "stop_loss"
        assert AlertType.MARGIN_WARNING.value == "margin_warning"


class TestMonitorStatus:
    """Tests for MonitorStatus enum"""

    def test_status_values(self):
        assert MonitorStatus.GREEN.value == "green"
        assert MonitorStatus.YELLOW.value == "yellow"
        assert MonitorStatus.RED.value == "red"


class TestAlert:
    """Tests for Alert model"""

    def test_create_red_alert(self):
        alert = Alert(
            level=AlertLevel.RED,
            alert_type=AlertType.STOP_LOSS,
            message="持仓亏损超过阈值",
            symbol="AAPL",
            current_value=-500.0,
            threshold_value=-300.0,
            suggested_action="建议止损",
        )
        assert alert.level == AlertLevel.RED
        assert alert.symbol == "AAPL"
        assert alert.suggested_action == "建议止损"

    def test_create_yellow_alert(self):
        alert = Alert(
            level=AlertLevel.YELLOW,
            alert_type=AlertType.DELTA_EXPOSURE,
            message="Delta 暴露偏高",
        )
        assert alert.level == AlertLevel.YELLOW
        assert alert.symbol is None

    def test_create_green_alert(self):
        alert = Alert(
            level=AlertLevel.GREEN,
            alert_type=AlertType.PROFIT_TARGET,
            message="达到止盈目标",
            symbol="MSFT",
        )
        assert alert.level == AlertLevel.GREEN


class TestPositionData:
    """Tests for PositionData model"""

    def test_create_short_put_position(self):
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
        assert pos.symbol == "AAPL250117P180"
        assert pos.quantity == -1
        assert pos.dte == 25

    def test_moneyness_property(self):
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
            # moneyness is now pre-calculated by DataBridge, not computed property
            moneyness=0.0278,  # (S-K)/K = (185-180)/180
        )
        assert pos.moneyness == pytest.approx(0.0278, rel=0.01)

    def test_iv_hv_ratio_property(self):
        """Test that iv_hv_ratio is a pre-filled field (by DataBridge)"""
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
            iv=0.30,
            hv=0.25,
            # iv_hv_ratio is now pre-calculated by DataBridge
            iv_hv_ratio=1.2,  # IV/HV = 0.30/0.25
        )
        assert pos.iv_hv_ratio == pytest.approx(1.2, rel=0.01)


class TestCapitalMetrics:
    """Tests for CapitalMetrics model"""

    def test_create_capital_metrics(self):
        cm = CapitalMetrics(
            total_equity=100000.0,
            cash_balance=50000.0,
            maintenance_margin=25000.0,
            margin_usage=0.25,
            unrealized_pnl=1500.0,
            realized_pnl=3000.0,
            sharpe_ratio=1.5,
            kelly_usage=0.10,
            current_drawdown=0.02,
        )
        assert cm.total_equity == 100000.0
        assert cm.maintenance_margin == 25000.0
        assert cm.sharpe_ratio == 1.5


class TestPortfolioMetrics:
    """Tests for PortfolioMetrics model"""

    def test_create_portfolio_metrics(self):
        pm = PortfolioMetrics(
            beta_weighted_delta=0.15,
            total_delta=0.50,
            total_gamma=0.08,
            total_theta=0.25,
            total_vega=-0.50,
            concentration_hhi=0.35,  # Changed from max_symbol_weight
            portfolio_tgr=1.2,
        )
        assert pm.beta_weighted_delta == 0.15
        assert pm.portfolio_tgr == 1.2
        assert pm.concentration_hhi == 0.35


class TestMonitorResult:
    """Tests for MonitorResult model"""

    def test_create_monitor_result(self):
        alerts = [
            Alert(
                level=AlertLevel.RED,
                alert_type=AlertType.STOP_LOSS,
                message="止损预警",
            ),
            Alert(
                level=AlertLevel.YELLOW,
                alert_type=AlertType.DELTA_EXPOSURE,
                message="Delta 偏高",
            ),
            Alert(
                level=AlertLevel.GREEN,
                alert_type=AlertType.PROFIT_TARGET,
                message="发现机会",
            ),
        ]
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=alerts,
        )
        assert result.status == MonitorStatus.RED
        assert len(result.alerts) == 3

    def test_alert_filtering(self):
        alerts = [
            Alert(level=AlertLevel.RED, alert_type=AlertType.STOP_LOSS, message="止损"),
            Alert(level=AlertLevel.RED, alert_type=AlertType.MARGIN_WARNING, message="保证金"),
            Alert(level=AlertLevel.YELLOW, alert_type=AlertType.DELTA_EXPOSURE, message="Delta"),
        ]
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=alerts,
        )
        assert len(result.red_alerts) == 2
        assert len(result.yellow_alerts) == 1
        assert len(result.green_alerts) == 0

    def test_empty_alerts(self):
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
        )
        assert len(result.alerts) == 0
        assert result.status == MonitorStatus.GREEN

    def test_summary_property(self):
        alerts = [
            Alert(level=AlertLevel.RED, alert_type=AlertType.STOP_LOSS, message="止损"),
        ]
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=alerts,
            total_positions=5,
            positions_at_risk=1,
        )
        summary = result.summary
        assert "status" in summary
        assert summary["red_alerts"] == 1
        assert summary["total_positions"] == 5
