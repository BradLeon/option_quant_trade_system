"""Tests for notification formatters"""

import pytest

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    MonitorStatus,
)
from src.business.notification.formatters.monitoring_formatter import MonitoringFormatter
from src.business.notification.formatters.screening_formatter import ScreeningFormatter
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    MarketType,
    ScreeningResult,
    TrendStatus,
    VolatilityIndexStatus,
)


class TestScreeningFormatter:
    """Tests for ScreeningFormatter"""

    @pytest.fixture
    def formatter(self):
        return ScreeningFormatter()

    def test_format_opportunity_result(self, formatter):
        opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            dte=30,
            option_type="put",
            sas=2.5,
            delta=-0.25,
            sharpe_ratio=1.8,
        )
        result = ScreeningResult(
            passed=True,
            market_status=MarketStatus(
                market_type=MarketType.US,
                volatility_index=VolatilityIndexStatus(symbol="VIX", value=18.0),
                overall_trend=TrendStatus.BULLISH,
                is_favorable=True,
            ),
            strategy_type="short_put",
            scanned_underlyings=10,
            passed_underlyings=3,
            opportunities=[opp],
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert "header" in card_data
        assert "elements" in card_data

    def test_format_no_opportunity_result(self, formatter):
        result = ScreeningResult(
            passed=True,
            market_status=MarketStatus(
                market_type=MarketType.US,
                volatility_index=VolatilityIndexStatus(symbol="VIX", value=18.0),
                overall_trend=TrendStatus.NEUTRAL,
                is_favorable=True,
            ),
            strategy_type="short_put",
            scanned_underlyings=10,
            passed_underlyings=0,
            opportunities=[],
        )

        card_data = formatter.format(result)

        assert card_data is not None
        assert "header" in card_data

    def test_format_market_unfavorable_result(self, formatter):
        result = ScreeningResult(
            passed=False,
            market_status=MarketStatus(
                market_type=MarketType.US,
                volatility_index=VolatilityIndexStatus(symbol="VIX", value=35.0),
                overall_trend=TrendStatus.STRONG_BEARISH,
                is_favorable=False,
            ),
            strategy_type="short_put",
            scanned_underlyings=0,
            passed_underlyings=0,
            opportunities=[],
            rejection_reason="市场环境不利：VIX 过高",
        )

        card_data = formatter.format(result)

        assert card_data is not None


class TestMonitoringFormatter:
    """Tests for MonitoringFormatter"""

    @pytest.fixture
    def formatter(self):
        return MonitoringFormatter()

    def test_format_red_alert(self, formatter):
        alert = Alert(
            level=AlertLevel.RED,
            alert_type=AlertType.STOP_LOSS,
            message="持仓亏损超过阈值",
            symbol="AAPL",
            current_value=-500.0,
            threshold_value=-300.0,
            suggested_action="建议止损",
        )

        card_data = formatter.format_alert(alert)

        assert card_data is not None
        assert "header" in card_data

    def test_format_yellow_alert(self, formatter):
        alert = Alert(
            level=AlertLevel.YELLOW,
            alert_type=AlertType.DELTA_EXPOSURE,
            message="Delta 暴露偏高",
            current_value=0.35,
            threshold_value=0.30,
        )

        card_data = formatter.format_alert(alert)

        assert card_data is not None

    def test_format_green_alert(self, formatter):
        alert = Alert(
            level=AlertLevel.GREEN,
            alert_type=AlertType.PROFIT_TARGET,
            message="达到止盈目标",
            symbol="MSFT",
        )

        card_data = formatter.format_alert(alert)

        assert card_data is not None

    def test_format_monitor_result(self, formatter):
        alerts = [
            Alert(
                level=AlertLevel.RED,
                alert_type=AlertType.STOP_LOSS,
                message="止损预警",
                symbol="AAPL",
            ),
            Alert(
                level=AlertLevel.YELLOW,
                alert_type=AlertType.DELTA_EXPOSURE,
                message="Delta 偏高",
            ),
        ]
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=alerts,
        )

        cards = formatter.format(result, alert_levels=["red", "yellow"])

        # 应该生成报告卡片 + 每个预警的卡片
        assert len(cards) >= 1

    def test_format_empty_result(self, formatter):
        result = MonitorResult(
            status=MonitorStatus.GREEN,
            alerts=[],
        )

        cards = formatter.format(result)

        assert len(cards) == 0
