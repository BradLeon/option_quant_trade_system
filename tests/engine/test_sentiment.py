"""Tests for market sentiment calculations."""

import pytest

from src.engine.models.enums import TrendSignal, VixZone
from src.engine.account.sentiment import (
    calc_pcr,
    calc_spy_trend,
    calc_trend_strength,
    get_vix_zone,
    interpret_pcr,
    interpret_vix,
)


class TestVIX:
    """Tests for VIX interpretation."""

    def test_interpret_vix_high(self):
        """Test VIX interpretation for high fear."""
        signal = interpret_vix(30)
        assert signal == TrendSignal.BULLISH  # High fear = contrarian bullish

    def test_interpret_vix_low(self):
        """Test VIX interpretation for low/complacency."""
        signal = interpret_vix(12)
        assert signal == TrendSignal.BEARISH  # Low fear = contrarian bearish

    def test_interpret_vix_normal(self):
        """Test VIX interpretation for normal levels."""
        signal = interpret_vix(18)
        assert signal == TrendSignal.NEUTRAL

    def test_get_vix_zone(self):
        """Test VIX zone categorization."""
        assert get_vix_zone(12) == VixZone.LOW
        assert get_vix_zone(17) == VixZone.NORMAL
        assert get_vix_zone(22) == VixZone.ELEVATED
        assert get_vix_zone(30) == VixZone.HIGH
        assert get_vix_zone(40) == VixZone.EXTREME


class TestTrend:
    """Tests for trend analysis."""

    def test_calc_spy_trend_bullish(self):
        """Test trend detection in uptrend."""
        # Uptrending prices
        prices = list(range(100, 160))  # 100 to 159
        signal = calc_spy_trend(prices, short_window=10, long_window=30)
        assert signal == TrendSignal.BULLISH

    def test_calc_spy_trend_bearish(self):
        """Test trend detection in downtrend."""
        # Downtrending prices
        prices = list(range(160, 100, -1))  # 160 to 101
        signal = calc_spy_trend(prices, short_window=10, long_window=30)
        assert signal == TrendSignal.BEARISH

    def test_calc_trend_strength_uptrend(self):
        """Test trend strength in uptrend."""
        prices = [100 + i * 0.5 for i in range(30)]  # Gradual uptrend
        strength = calc_trend_strength(prices, window=20)
        assert strength is not None
        assert strength > 0  # Positive for uptrend

    def test_calc_trend_strength_downtrend(self):
        """Test trend strength in downtrend."""
        prices = [130 - i * 0.5 for i in range(30)]  # Gradual downtrend
        strength = calc_trend_strength(prices, window=20)
        assert strength is not None
        assert strength < 0  # Negative for downtrend


class TestPCR:
    """Tests for Put/Call Ratio."""

    def test_calc_pcr_basic(self):
        """Test basic PCR calculation."""
        pcr = calc_pcr(1000, 800)
        assert pcr == 1.25

    def test_calc_pcr_low(self):
        """Test PCR with more calls."""
        pcr = calc_pcr(600, 1000)
        assert pcr == 0.6

    def test_calc_pcr_zero_calls(self):
        """Test PCR with zero call volume."""
        pcr = calc_pcr(1000, 0)
        assert pcr is None

    def test_interpret_pcr_bullish(self):
        """Test PCR interpretation when high (contrarian bullish)."""
        signal = interpret_pcr(1.2)
        assert signal == TrendSignal.BULLISH

    def test_interpret_pcr_bearish(self):
        """Test PCR interpretation when low (contrarian bearish)."""
        signal = interpret_pcr(0.5)
        assert signal == TrendSignal.BEARISH

    def test_interpret_pcr_neutral(self):
        """Test PCR interpretation for neutral range."""
        signal = interpret_pcr(0.85)
        assert signal == TrendSignal.NEUTRAL
