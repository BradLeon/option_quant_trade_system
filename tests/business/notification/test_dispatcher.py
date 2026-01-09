"""Tests for message dispatcher"""

from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    MonitorStatus,
)
from src.business.notification.channels.base import SendResult, SendStatus
from src.business.notification.dispatcher import MessageDispatcher
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    MarketType,
    ScreeningResult,
    TrendStatus,
    VolatilityIndexStatus,
)


class TestMessageDispatcher:
    """Tests for MessageDispatcher"""

    @pytest.fixture
    def mock_channel(self):
        channel = MagicMock()
        channel.send.return_value = SendResult(
            status=SendStatus.SUCCESS,
            message_id="test-msg-id",
        )
        channel.send_card.return_value = SendResult(
            status=SendStatus.SUCCESS,
            message_id="test-msg-id",
        )
        return channel

    @pytest.fixture
    def dispatcher(self, mock_channel):
        config = {
            "rate_limit": {
                "dedup_window": 1800,
                "min_interval": 60,
                "silent_hours": {
                    "enabled": False,
                },
            },
            "content": {
                "alert_levels": ["red", "yellow"],
            },
        }
        return MessageDispatcher(channel=mock_channel, config=config)

    def test_send_screening_result_success(self, dispatcher, mock_channel):
        opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            dte=30,
            option_type="put",
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

        send_result = dispatcher.send_screening_result(result)

        assert send_result.is_success
        mock_channel.send_card.assert_called_once()

    def test_send_monitoring_result_success(self, dispatcher, mock_channel):
        alerts = [
            Alert(
                level=AlertLevel.RED,
                alert_type=AlertType.STOP_LOSS,
                message="止损预警",
            ),
        ]
        result = MonitorResult(
            status=MonitorStatus.RED,
            alerts=alerts,
        )

        send_results = dispatcher.send_monitoring_result(result)

        # 应该有结果返回（可能是成功或者被频率限制）
        assert len(send_results) >= 1
        # 至少第一个应该成功
        assert send_results[0].is_success

    def test_send_alert_success(self, dispatcher, mock_channel):
        alert = Alert(
            level=AlertLevel.RED,
            alert_type=AlertType.STOP_LOSS,
            message="止损预警",
        )

        send_result = dispatcher.send_alert(alert)

        assert send_result.is_success

    def test_send_text_success(self, dispatcher, mock_channel):
        send_result = dispatcher.send_text("测试标题", "测试内容")

        assert send_result.is_success
        mock_channel.send.assert_called_once()

    def test_duplicate_message_blocked(self, dispatcher, mock_channel):
        opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            dte=30,
            option_type="put",
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

        # 第一次发送成功
        send_result1 = dispatcher.send_screening_result(result)
        assert send_result1.is_success

        # 第二次应该被去重阻止
        send_result2 = dispatcher.send_screening_result(result)
        assert send_result2.status == SendStatus.RATE_LIMITED

    def test_force_send_bypasses_dedup(self, dispatcher, mock_channel):
        opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            dte=30,
            option_type="put",
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

        # 第一次发送
        dispatcher.send_screening_result(result)

        # 强制发送应该成功
        send_result = dispatcher.send_screening_result(result, force=True)
        assert send_result.is_success

    def test_alert_level_filtering(self, dispatcher, mock_channel):
        # Green 级别不在配置的 alert_levels 中
        alert = Alert(
            level=AlertLevel.GREEN,
            alert_type=AlertType.PROFIT_TARGET,
            message="达到止盈",
        )

        send_result = dispatcher.send_alert(alert)

        assert send_result.status == SendStatus.SILENCED


class TestSilentPeriod:
    """Tests for silent period handling"""

    def test_silent_period_detection_same_day(self):
        """测试同一天内的静默时段"""
        config = {
            "rate_limit": {
                "silent_hours": {
                    "enabled": True,
                    "start": "23:00",
                    "end": "07:00",
                },
            },
        }
        mock_channel = MagicMock()
        dispatcher = MessageDispatcher(channel=mock_channel, config=config)

        # 模拟凌晨 2 点
        with patch.object(dispatcher, "_is_silent_period", return_value=True):
            result = dispatcher.send_text("测试", "内容")
            assert result.status == SendStatus.SILENCED

    def test_silent_period_not_active(self):
        """测试非静默时段"""
        config = {
            "rate_limit": {
                "silent_hours": {
                    "enabled": True,
                    "start": "23:00",
                    "end": "07:00",
                },
            },
        }
        mock_channel = MagicMock()
        mock_channel.send.return_value = SendResult(
            status=SendStatus.SUCCESS,
            message_id="test",
        )
        dispatcher = MessageDispatcher(channel=mock_channel, config=config)

        # 模拟下午 2 点（非静默时段）
        with patch.object(dispatcher, "_is_silent_period", return_value=False):
            result = dispatcher.send_text("测试", "内容")
            assert result.is_success


class TestRateLimiting:
    """Tests for rate limiting"""

    def test_rate_limit_triggered(self):
        """测试频率限制触发"""
        config = {
            "rate_limit": {
                "min_interval": 60,
                "silent_hours": {"enabled": False},
            },
        }
        mock_channel = MagicMock()
        mock_channel.send.return_value = SendResult(
            status=SendStatus.SUCCESS,
            message_id="test",
        )
        dispatcher = MessageDispatcher(channel=mock_channel, config=config)

        # 第一次发送
        result1 = dispatcher.send_text("测试1", "内容1")
        assert result1.is_success

        # 立即第二次发送应该被限制
        result2 = dispatcher.send_text("测试2", "内容2")
        assert result2.status == SendStatus.RATE_LIMITED

    def test_force_bypasses_rate_limit(self):
        """测试强制发送绕过频率限制"""
        config = {
            "rate_limit": {
                "min_interval": 60,
                "silent_hours": {"enabled": False},
            },
        }
        mock_channel = MagicMock()
        mock_channel.send.return_value = SendResult(
            status=SendStatus.SUCCESS,
            message_id="test",
        )
        dispatcher = MessageDispatcher(channel=mock_channel, config=config)

        # 第一次发送
        dispatcher.send_text("测试1", "内容1")

        # 强制发送应该成功
        result = dispatcher.send_text("测试2", "内容2", force=True)
        assert result.is_success
