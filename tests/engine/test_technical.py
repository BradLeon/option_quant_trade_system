"""Tests for technical analysis calculations."""

import pytest

from src.engine.models.enums import TrendSignal
from src.engine.position.technical import (
    # RSI
    calc_rsi,
    interpret_rsi,
    # Support/Resistance
    calc_support_distance,
    calc_support_level,
    find_support_resistance,
    # Moving Average
    calc_sma,
    calc_ema,
    calc_sma_series,
    calc_ema_series,
    interpret_ma_crossover,
    get_ma_trend,
    calc_ma_distance,
    get_ma_alignment,
    # ADX
    calc_adx,
    calc_true_range,
    interpret_adx,
    get_adx_trend_direction,
    is_trending,
    is_ranging,
    # Bollinger Bands
    calc_bollinger_bands,
    calc_bollinger_series,
    calc_percent_b,
    calc_bandwidth,
    is_squeeze,
    interpret_bb_position,
    is_favorable_for_selling,
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


class TestMovingAverage:
    """Tests for Moving Average calculations."""

    def test_calc_sma_basic(self):
        """Test basic SMA calculation."""
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        sma = calc_sma(prices, period=5)
        assert sma == 18.0  # Average of last 5: (16+17+18+19+20)/5

    def test_calc_sma_insufficient_data(self):
        """Test SMA with insufficient data."""
        prices = [10, 11, 12]
        sma = calc_sma(prices, period=5)
        assert sma is None

    def test_calc_ema_basic(self):
        """Test basic EMA calculation."""
        # Use non-monotonic prices so EMA and SMA differ
        prices = [10, 12, 11, 13, 12, 15, 14, 17, 16, 19, 20]
        ema = calc_ema(prices, period=5)
        assert ema is not None
        # EMA is valid and within reasonable range
        assert 15 < ema < 20

    def test_calc_ema_weight_recent(self):
        """Test that EMA weights recent prices more heavily."""
        # Prices with recent increase
        prices = [10, 10, 10, 10, 10, 15, 20]
        ema = calc_ema(prices, period=5)
        sma = calc_sma(prices, period=5)
        # EMA should be higher than SMA due to recent rise
        assert ema > sma

    def test_calc_sma_series(self):
        """Test SMA series calculation."""
        prices = [1, 2, 3, 4, 5]
        sma_series = calc_sma_series(prices, period=3)
        assert len(sma_series) == 5
        assert sma_series[0] is None
        assert sma_series[1] is None
        assert sma_series[2] == 2.0  # (1+2+3)/3
        assert sma_series[3] == 3.0  # (2+3+4)/3
        assert sma_series[4] == 4.0  # (3+4+5)/3

    def test_calc_ema_series(self):
        """Test EMA series calculation."""
        prices = [1, 2, 3, 4, 5]
        ema_series = calc_ema_series(prices, period=3)
        assert len(ema_series) == 5
        assert ema_series[0] is None
        assert ema_series[1] is None
        assert ema_series[2] is not None

    def test_interpret_ma_crossover_bullish(self):
        """Test MA crossover interpretation - bullish."""
        signal = interpret_ma_crossover(50.5, 48.0)
        assert signal == TrendSignal.BULLISH

    def test_interpret_ma_crossover_bearish(self):
        """Test MA crossover interpretation - bearish."""
        signal = interpret_ma_crossover(45.0, 50.0)
        assert signal == TrendSignal.BEARISH

    def test_interpret_ma_crossover_neutral(self):
        """Test MA crossover interpretation - neutral."""
        signal = interpret_ma_crossover(50.0, 50.1)
        assert signal == TrendSignal.NEUTRAL

    def test_get_ma_trend_uptrend(self):
        """Test MA trend detection in uptrend."""
        prices = list(range(1, 101))  # 1 to 100
        signal = get_ma_trend(prices, short_period=20, long_period=50)
        assert signal == TrendSignal.BULLISH

    def test_get_ma_trend_downtrend(self):
        """Test MA trend detection in downtrend."""
        prices = list(range(100, 0, -1))  # 100 to 1
        signal = get_ma_trend(prices, short_period=20, long_period=50)
        assert signal == TrendSignal.BEARISH

    def test_calc_ma_distance(self):
        """Test MA distance calculation."""
        distance = calc_ma_distance(110, 100)
        assert distance == 10.0  # 10% above MA

        distance = calc_ma_distance(90, 100)
        assert distance == -10.0  # 10% below MA

    def test_get_ma_alignment_strong_bullish(self):
        """Test MA alignment detection - strong bullish."""
        # Strong uptrend: price > MA20 > MA50 > MA200
        prices = list(range(1, 251))  # 250 prices in uptrend
        alignment = get_ma_alignment(prices, periods=[20, 50, 200])
        assert alignment == "strong_bullish"

    def test_get_ma_alignment_strong_bearish(self):
        """Test MA alignment detection - strong bearish."""
        # Strong downtrend: price < MA20 < MA50 < MA200
        prices = list(range(250, 0, -1))  # 250 prices in downtrend
        alignment = get_ma_alignment(prices, periods=[20, 50, 200])
        assert alignment == "strong_bearish"


class TestADX:
    """Tests for ADX calculation."""

    def test_calc_true_range(self):
        """Test True Range calculation."""
        # Case 1: High-Low is largest
        tr = calc_true_range(50, 45, 47)
        assert tr == 5

        # Case 2: High-PrevClose is largest
        tr = calc_true_range(55, 52, 48)
        assert tr == 7  # 55 - 48

        # Case 3: Low-PrevClose is largest
        tr = calc_true_range(52, 45, 54)
        assert tr == 9  # 54 - 45

    def test_calc_adx_uptrend(self):
        """Test ADX calculation in uptrend."""
        # Generate uptrend data
        n = 40
        highs = [50 + i * 0.5 for i in range(n)]
        lows = [48 + i * 0.5 for i in range(n)]
        closes = [49 + i * 0.5 for i in range(n)]

        result = calc_adx(highs, lows, closes, period=14)
        assert result is not None
        assert result.adx >= 0
        assert result.plus_di > result.minus_di  # Uptrend: +DI > -DI

    def test_calc_adx_downtrend(self):
        """Test ADX calculation in downtrend."""
        # Generate downtrend data
        n = 40
        highs = [70 - i * 0.5 for i in range(n)]
        lows = [68 - i * 0.5 for i in range(n)]
        closes = [69 - i * 0.5 for i in range(n)]

        result = calc_adx(highs, lows, closes, period=14)
        assert result is not None
        assert result.adx >= 0
        assert result.minus_di > result.plus_di  # Downtrend: -DI > +DI

    def test_calc_adx_insufficient_data(self):
        """Test ADX with insufficient data."""
        highs = [50, 51, 52]
        lows = [48, 49, 50]
        closes = [49, 50, 51]
        result = calc_adx(highs, lows, closes, period=14)
        assert result is None

    def test_interpret_adx_strong_trend(self):
        """Test ADX interpretation - strong trend."""
        assert interpret_adx(30) == "strong_trend"
        assert interpret_adx(50) == "strong_trend"

    def test_interpret_adx_ranging(self):
        """Test ADX interpretation - ranging."""
        assert interpret_adx(10) == "ranging"
        assert interpret_adx(14) == "ranging"

    def test_interpret_adx_emerging(self):
        """Test ADX interpretation - emerging trend."""
        assert interpret_adx(22) == "emerging_trend"

    def test_get_adx_trend_direction_bullish(self):
        """Test ADX trend direction - bullish."""
        signal = get_adx_trend_direction(25, 15)
        assert signal == TrendSignal.BULLISH

    def test_get_adx_trend_direction_bearish(self):
        """Test ADX trend direction - bearish."""
        signal = get_adx_trend_direction(15, 30)
        assert signal == TrendSignal.BEARISH

    def test_is_trending(self):
        """Test is_trending function."""
        assert is_trending(30) is True
        assert is_trending(20) is False

    def test_is_ranging(self):
        """Test is_ranging function."""
        assert is_ranging(15) is True
        assert is_ranging(25) is False


class TestBollingerBands:
    """Tests for Bollinger Bands calculation."""

    def test_calc_bollinger_bands_basic(self):
        """Test basic Bollinger Bands calculation."""
        prices = [20, 21, 22, 21, 20, 21, 22, 23, 22, 21,
                  22, 23, 24, 23, 22, 23, 24, 25, 24, 23]
        bb = calc_bollinger_bands(prices, period=20, num_std=2.0)
        assert bb is not None
        assert bb.lower < bb.middle < bb.upper
        assert bb.bandwidth > 0

    def test_calc_bollinger_bands_insufficient_data(self):
        """Test Bollinger Bands with insufficient data."""
        prices = [20, 21, 22]
        bb = calc_bollinger_bands(prices, period=20)
        assert bb is None

    def test_calc_bollinger_bands_middle_is_sma(self):
        """Test that middle band equals SMA."""
        prices = [20, 21, 22, 21, 20, 21, 22, 23, 22, 21,
                  22, 23, 24, 23, 22, 23, 24, 25, 24, 23]
        bb = calc_bollinger_bands(prices, period=20, num_std=2.0)
        sma = calc_sma(prices, period=20)
        assert bb.middle == sma

    def test_calc_bollinger_series(self):
        """Test Bollinger Bands series calculation."""
        prices = list(range(1, 25))  # 24 prices
        bb_series = calc_bollinger_series(prices, period=20)
        assert len(bb_series) == 24
        assert bb_series[18] is None  # Not enough data
        assert bb_series[19] is not None  # First valid BB

    def test_calc_percent_b(self):
        """Test %B calculation."""
        from src.engine.position.technical.bollinger_bands import BollingerBands
        bb = BollingerBands(upper=110, middle=100, lower=90,
                           bandwidth=0.2, percent_b=0.5)

        # Price at middle
        assert calc_percent_b(100, bb) == 0.5

        # Price at upper
        assert calc_percent_b(110, bb) == 1.0

        # Price at lower
        assert calc_percent_b(90, bb) == 0.0

        # Price above upper
        assert calc_percent_b(115, bb) == 1.25

        # Price below lower
        assert calc_percent_b(85, bb) == -0.25

    def test_calc_bandwidth(self):
        """Test bandwidth calculation."""
        from src.engine.position.technical.bollinger_bands import BollingerBands
        bb = BollingerBands(upper=110, middle=100, lower=90,
                           bandwidth=0.2, percent_b=0.5)
        bw = calc_bandwidth(bb)
        assert bw == 0.2  # (110-90)/100

    def test_is_squeeze(self):
        """Test squeeze detection."""
        assert is_squeeze(0.05) is True
        assert is_squeeze(0.15) is False
        assert is_squeeze(0.1, threshold=0.1) is False
        assert is_squeeze(0.09, threshold=0.1) is True

    def test_interpret_bb_position_overbought(self):
        """Test BB position interpretation - overbought."""
        assert interpret_bb_position(1.2) == "overbought"

    def test_interpret_bb_position_oversold(self):
        """Test BB position interpretation - oversold."""
        assert interpret_bb_position(-0.1) == "oversold"

    def test_interpret_bb_position_middle(self):
        """Test BB position interpretation - middle."""
        assert interpret_bb_position(0.5) == "middle"

    def test_interpret_bb_position_zones(self):
        """Test BB position interpretation - all zones."""
        assert interpret_bb_position(0.9) == "upper_zone"
        assert interpret_bb_position(0.1) == "lower_zone"

    def test_is_favorable_for_selling(self):
        """Test favorable zone for option selling."""
        assert is_favorable_for_selling(0.5) is True
        assert is_favorable_for_selling(0.3) is True
        assert is_favorable_for_selling(0.7) is True
        assert is_favorable_for_selling(0.1) is False  # Too low
        assert is_favorable_for_selling(0.9) is False  # Too high
        assert is_favorable_for_selling(1.1) is False  # Above upper
