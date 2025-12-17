"""Tests for technical analysis calculations."""

import pytest

from src.engine.models.enums import TrendSignal
from src.engine.position.technical import (
    calc_rsi,
    calc_support_distance,
    calc_support_level,
    find_support_resistance,
    interpret_rsi,
)


class TestRSI:
    """Tests for RSI calculation."""

    def test_calc_rsi_basic(self):
        """Test basic RSI calculation."""
        # Generate prices with some up/down movement
        prices = [44, 44.5, 44, 43.5, 44, 44.5, 44.8, 44.3, 44.7, 45,
                  45.2, 44.8, 45.1, 45.5, 45.2]
        rsi = calc_rsi(prices, period=14)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_calc_rsi_strong_uptrend(self):
        """Test RSI in strong uptrend."""
        # Consistently rising prices should give high RSI
        prices = [100 + i for i in range(20)]
        rsi = calc_rsi(prices, period=14)
        assert rsi is not None
        assert rsi > 70  # Should be overbought

    def test_calc_rsi_strong_downtrend(self):
        """Test RSI in strong downtrend."""
        # Consistently falling prices should give low RSI
        prices = [120 - i for i in range(20)]
        rsi = calc_rsi(prices, period=14)
        assert rsi is not None
        assert rsi < 30  # Should be oversold

    def test_calc_rsi_insufficient_data(self):
        """Test RSI with insufficient data."""
        prices = [100, 101, 102]
        rsi = calc_rsi(prices, period=14)
        assert rsi is None

    def test_interpret_rsi_overbought(self):
        """Test RSI interpretation for overbought."""
        signal = interpret_rsi(75)
        assert signal == TrendSignal.BEARISH

    def test_interpret_rsi_oversold(self):
        """Test RSI interpretation for oversold."""
        signal = interpret_rsi(25)
        assert signal == TrendSignal.BULLISH

    def test_interpret_rsi_neutral(self):
        """Test RSI interpretation for neutral."""
        signal = interpret_rsi(50)
        assert signal == TrendSignal.NEUTRAL


class TestSupportResistance:
    """Tests for support and resistance calculations."""

    def test_calc_support_level(self):
        """Test support level calculation."""
        prices = [100, 102, 98, 103, 99, 105, 101]
        support = calc_support_level(prices, window=5)
        # Last 5 prices: [99, 105, 101] - need at least window prices
        # Actually last 5: [103, 99, 105, 101] wait let me recount
        # prices[-5:] = [103, 99, 105, 101] no... prices has 7 elements
        # prices[-5:] = [99, 105, 101] no that's 3
        # [100, 102, 98, 103, 99, 105, 101][-5:] = [98, 103, 99, 105, 101]
        assert support == 98  # Min of last 5 prices

    def test_calc_support_distance(self):
        """Test support distance calculation."""
        distance = calc_support_distance(105, 100)
        assert distance == 0.05  # 5% above support

    def test_calc_support_distance_at_support(self):
        """Test support distance when at support."""
        distance = calc_support_distance(100, 100)
        assert distance == 0.0

    def test_calc_support_distance_below_support(self):
        """Test support distance when below support."""
        distance = calc_support_distance(95, 100)
        assert distance == -0.05  # 5% below support

    def test_find_support_resistance(self):
        """Test finding both support and resistance."""
        prices = [100, 105, 98, 110, 102, 108, 100]
        # Last 5: [98, 110, 102, 108, 100]
        sr = find_support_resistance(prices, window=5)
        assert sr.support == 98  # Min of last 5
        assert sr.resistance == 110  # Max of last 5
