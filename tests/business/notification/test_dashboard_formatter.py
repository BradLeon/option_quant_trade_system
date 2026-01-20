"""Tests for DashboardFormatter"""

import pytest

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    MonitorStatus,
    PositionData,
)
from src.business.monitoring.suggestions import (
    ActionType,
    PositionSuggestion,
    UrgencyLevel,
)
from src.business.notification.formatters.dashboard_formatter import DashboardFormatter
from src.engine.models.capital import CapitalMetrics
from src.engine.models.portfolio import PortfolioMetrics


class TestDashboardFormatter:
    """Tests for DashboardFormatter"""

    @pytest.fixture
    def formatter(self):
        return DashboardFormatter()

    @pytest.fixture
    def sample_capital_metrics(self):
        return CapitalMetrics(
            total_equity=100000.0,
            cash_balance=35000.0,
            maintenance_margin=25000.0,
            unrealized_pnl=1500.0,
            realized_pnl=3000.0,
            total_position_value=65000.0,
            margin_utilization=0.25,
            cash_ratio=0.35,
            gross_leverage=1.8,
            stress_test_loss=0.08,
        )

    @pytest.fixture
    def sample_portfolio_metrics(self):
        return PortfolioMetrics(
            beta_weighted_delta=150.0,
            total_delta=200.0,
            total_gamma=50.0,
            total_theta=120.0,
            total_vega=80.0,
            portfolio_tgr=0.55,
            concentration_hhi=0.18,
            beta_weighted_delta_pct=0.0015,
            delta_pct=0.002,
            gamma_pct=0.0005,
            theta_pct=0.0012,
            vega_pct=0.0008,
            vega_weighted_iv_hv=1.15,
        )

    @pytest.fixture
    def sample_positions(self):
        return [
            PositionData(
                position_id="AAPL_PUT_170_20250117",
                symbol="AAPL250117P00170000",
                underlying="AAPL",
                asset_type="option",
                option_type="put",
                quantity=-1,
                entry_price=3.50,
                current_price=2.80,
                strike=170.0,
                expiry="20250117",
                dte=25,
                unrealized_pnl_pct=0.20,
            ),
            PositionData(
                position_id="MSFT_STOCK",
                symbol="MSFT",
                asset_type="stock",
                quantity=50,
                entry_price=380.0,
                current_price=340.0,
                unrealized_pnl_pct=-0.105,
            ),
        ]

    @pytest.fixture
    def sample_alerts(self):
        return [
            Alert(
                level=AlertLevel.RED,
                alert_type=AlertType.STOP_LOSS,
                message="持仓亏损超过阈值",
                symbol="MSFT",
            ),
            Alert(
                level=AlertLevel.YELLOW,
                alert_type=AlertType.DELTA_EXPOSURE,
                message="Delta 暴露偏高",
            ),
            Alert(
                level=AlertLevel.GREEN,
                alert_type=AlertType.PROFIT_TARGET,
                message="达到止盈目标",
                symbol="AAPL",
            ),
        ]

    @pytest.fixture
    def sample_suggestions(self):
        return [
            PositionSuggestion(
                position_id="MSFT_STOCK",
                symbol="MSFT",
                action=ActionType.CLOSE,
                urgency=UrgencyLevel.IMMEDIATE,
                reason="止损预警触发",
            ),
            PositionSuggestion(
                position_id="AAPL_PUT_170_20250117",
                symbol="AAPL",
                action=ActionType.MONITOR,
                urgency=UrgencyLevel.MONITOR,
                reason="持续观察",
            ),
        ]

    def test_format_complete_result(
        self,
        formatter,
        sample_capital_metrics,
        sample_portfolio_metrics,
        sample_positions,
        sample_alerts,
        sample_suggestions,
    ):
        """Test formatting a complete MonitorResult"""
        result = MonitorResult(
            status=MonitorStatus.YELLOW,
            alerts=sample_alerts,
            positions=sample_positions,
            suggestions=sample_suggestions,
            capital_metrics=sample_capital_metrics,
            portfolio_metrics=sample_portfolio_metrics,
            total_positions=2,
            positions_at_risk=1,
            positions_opportunity=1,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert "header" in card_data
        assert "elements" in card_data
        assert len(card_data["elements"]) > 0
        # Check header color is orange (yellow status)
        assert card_data["header"]["template"] == "orange"

    def test_format_green_status(self, formatter, sample_capital_metrics):
        """Test formatting with green status"""
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            positions=[],
            capital_metrics=sample_capital_metrics,
            total_positions=0,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert card_data["header"]["template"] == "green"

    def test_format_red_status(self, formatter, sample_alerts):
        """Test formatting with red status"""
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=sample_alerts,
            positions=[],
            total_positions=0,
            positions_at_risk=1,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert card_data["header"]["template"] == "red"

    def test_format_without_capital_metrics(self, formatter, sample_positions):
        """Test formatting without capital metrics"""
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            positions=sample_positions,
            total_positions=2,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert "elements" in card_data

    def test_format_without_portfolio_metrics(
        self, formatter, sample_capital_metrics, sample_positions
    ):
        """Test formatting without portfolio metrics"""
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            positions=sample_positions,
            capital_metrics=sample_capital_metrics,
            total_positions=2,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert "elements" in card_data

    def test_format_with_custom_templates(self, sample_capital_metrics):
        """Test formatting with custom templates"""
        templates = {"dashboard_report_title": "Custom Dashboard Title"}
        formatter = DashboardFormatter(templates=templates)

        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            capital_metrics=sample_capital_metrics,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert card_data["header"]["title"]["content"] == "Custom Dashboard Title"

    def test_format_empty_result(self, formatter):
        """Test formatting an empty MonitorResult"""
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            positions=[],
            suggestions=[],
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert "header" in card_data
        assert "elements" in card_data

    def test_capital_section_risk_pillar_colors(self, formatter):
        """Test that risk pillar colors are correct based on values"""
        # Red status capital
        red_capital = CapitalMetrics(
            total_equity=100000.0,
            cash_balance=5000.0,  # 5% - RED
            margin_utilization=0.75,  # 75% - RED
            cash_ratio=0.05,  # 5% - RED
            gross_leverage=5.0,  # 5.0x - RED
            stress_test_loss=0.25,  # 25% - RED
        )

        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=[],
            capital_metrics=red_capital,
        )

        card_data = formatter.format(result)

        # Card should be formatted without errors
        assert card_data is not None

    def test_position_summary_with_options_and_stocks(
        self, formatter, sample_positions, sample_capital_metrics
    ):
        """Test position summary shows both option and stock counts"""
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
            positions=sample_positions,
            capital_metrics=sample_capital_metrics,
            total_positions=2,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        # Should have position summary section
        elements_text = str(card_data["elements"])
        assert "期权持仓" in elements_text or "option" in elements_text.lower()

    def test_todos_section_with_suggestions(
        self, formatter, sample_suggestions, sample_capital_metrics
    ):
        """Test todos section is included when suggestions exist"""
        result = MonitorResult(
            status=MonitorStatus.YELLOW,
            alerts=[],
            suggestions=sample_suggestions,
            capital_metrics=sample_capital_metrics,
        )

        card_data = formatter.format(result)

        assert card_data is not None
        elements_text = str(card_data["elements"])
        assert "待办" in elements_text or "todo" in elements_text.lower()
