"""Tests for market sentiment calculations.

Includes:
- Unit tests for individual sentiment components (VIX, PCR, trend, term structure)
- Integration tests for aggregated sentiment analysis
- Data bridge tests for real data fetching (requires live connections)
"""

import pytest

from src.engine.models.enums import MarketType, TermStructure, TrendSignal, VixZone
from src.engine.account.sentiment import (
    # Existing
    calc_pcr,
    calc_spy_trend,
    calc_trend_strength,
    get_vix_zone,
    interpret_pcr,
    interpret_vix,
    # VIX Term Structure
    analyze_term_structure,
    calc_vix_term_ratio,
    get_term_structure,
    interpret_term_structure,
    # Market Trend
    analyze_market_trend,
    calc_market_trend,
    # Aggregation
    analyze_hk_sentiment,
    analyze_us_sentiment,
    calc_composite_score,
    score_to_signal,
)
from src.engine.models.sentiment import MarketTrend


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


class TestVixTermStructure:
    """Tests for VIX term structure analysis."""

    def test_calc_vix_term_ratio_contango(self):
        """Test ratio calculation in contango (normal market)."""
        ratio = calc_vix_term_ratio(vix=15.0, vix_3m=17.0)
        assert ratio == pytest.approx(1.133, rel=0.01)

    def test_calc_vix_term_ratio_backwardation(self):
        """Test ratio calculation in backwardation (fear/panic)."""
        ratio = calc_vix_term_ratio(vix=25.0, vix_3m=22.0)
        assert ratio == pytest.approx(0.88, rel=0.01)

    def test_calc_vix_term_ratio_zero_vix(self):
        """Test ratio with zero VIX returns None."""
        ratio = calc_vix_term_ratio(vix=0, vix_3m=15.0)
        assert ratio is None

    def test_calc_vix_term_ratio_none_inputs(self):
        """Test ratio with None inputs returns None."""
        assert calc_vix_term_ratio(vix=None, vix_3m=15.0) is None
        assert calc_vix_term_ratio(vix=15.0, vix_3m=None) is None

    def test_get_term_structure_contango(self):
        """Test contango classification (ratio > 1.05)."""
        structure = get_term_structure(1.10)
        assert structure == TermStructure.CONTANGO

    def test_get_term_structure_backwardation(self):
        """Test backwardation classification (ratio < 0.95)."""
        structure = get_term_structure(0.90)
        assert structure == TermStructure.BACKWARDATION

    def test_get_term_structure_flat(self):
        """Test flat term structure (0.95 <= ratio <= 1.05)."""
        structure = get_term_structure(1.02)
        assert structure == TermStructure.FLAT
        structure = get_term_structure(0.98)
        assert structure == TermStructure.FLAT

    def test_interpret_term_structure_backwardation(self):
        """Test backwardation interpretation (contrarian bullish)."""
        signal = interpret_term_structure(TermStructure.BACKWARDATION)
        assert signal == TrendSignal.BULLISH

    def test_interpret_term_structure_contango(self):
        """Test contango interpretation (bearish warning)."""
        signal = interpret_term_structure(TermStructure.CONTANGO)
        assert signal == TrendSignal.BEARISH

    def test_interpret_term_structure_flat(self):
        """Test flat term structure interpretation (neutral)."""
        signal = interpret_term_structure(TermStructure.FLAT)
        assert signal == TrendSignal.NEUTRAL

    def test_analyze_term_structure_complete(self):
        """Test complete term structure analysis."""
        result = analyze_term_structure(vix=20.0, vix_3m=18.0)
        assert result.vix == 20.0
        assert result.vix_3m == 18.0
        assert result.ratio == pytest.approx(0.9, rel=0.01)
        assert result.structure == TermStructure.BACKWARDATION
        assert result.signal == TrendSignal.BULLISH


class TestMarketTrend:
    """Tests for generalized market trend analysis."""

    def test_calc_market_trend_spy_bullish(self):
        """Test SPY trend in uptrend."""
        prices = list(range(100, 160))
        signal = calc_market_trend("SPY", prices, short_window=10, long_window=30)
        assert signal == TrendSignal.BULLISH

    def test_calc_market_trend_qqq_bearish(self):
        """Test QQQ trend in downtrend."""
        prices = list(range(160, 100, -1))
        signal = calc_market_trend("QQQ", prices, short_window=10, long_window=30)
        assert signal == TrendSignal.BEARISH

    def test_calc_market_trend_hk_index(self):
        """Test HK index trend (2800.HK)."""
        prices = list(range(20, 80))  # Uptrend
        signal = calc_market_trend("2800.HK", prices, short_window=10, long_window=30)
        assert signal == TrendSignal.BULLISH

    def test_calc_market_trend_uses_defaults(self):
        """Test that market-specific defaults are used."""
        prices = list(range(100, 160))
        # Should use SPY defaults when no params provided
        signal = calc_market_trend("SPY", prices)
        assert signal in [TrendSignal.BULLISH, TrendSignal.BEARISH, TrendSignal.NEUTRAL]

    def test_analyze_market_trend_complete(self):
        """Test complete trend analysis with all fields."""
        prices = [100 + i * 0.5 for i in range(60)]
        current = prices[-1]
        result = analyze_market_trend("SPY", prices, current_price=current)
        assert result.symbol == "SPY"
        assert result.signal == TrendSignal.BULLISH
        assert result.strength > 0
        assert result.short_ma is not None
        assert result.long_ma is not None

    def test_analyze_market_trend_with_200ma(self):
        """Test 200MA check when sufficient data."""
        prices = [100 + i * 0.1 for i in range(250)]
        current = prices[-1]
        result = analyze_market_trend("SPY", prices, current_price=current)
        assert result.above_200ma is True  # Price above 200MA in uptrend


class TestMarketSentimentAggregation:
    """Tests for market sentiment aggregation."""

    def test_analyze_us_sentiment_bullish(self):
        """Test US sentiment analysis with bullish conditions."""
        spy_prices = list(range(100, 160))  # Uptrend
        qqq_prices = list(range(200, 260))  # Uptrend

        result = analyze_us_sentiment(
            vix=28.0,  # High fear = bullish
            vix_3m=24.0,  # Backwardation
            spy_prices=spy_prices,
            qqq_prices=qqq_prices,
            pcr=1.2,  # High PCR = bullish
        )

        assert result.market == MarketType.US
        assert result.composite_signal == TrendSignal.BULLISH
        assert result.composite_score > 0
        assert result.vix_value == 28.0
        assert result.term_structure is not None
        assert result.term_structure.structure == TermStructure.BACKWARDATION

    def test_analyze_us_sentiment_bearish(self):
        """Test US sentiment analysis with bearish conditions."""
        spy_prices = list(range(160, 100, -1))  # Downtrend
        qqq_prices = list(range(260, 200, -1))  # Downtrend

        result = analyze_us_sentiment(
            vix=12.0,  # Low VIX = complacency
            vix_3m=14.0,  # Contango
            spy_prices=spy_prices,
            qqq_prices=qqq_prices,
            pcr=0.5,  # Low PCR = bearish
        )

        assert result.market == MarketType.US
        assert result.composite_signal == TrendSignal.BEARISH
        assert result.composite_score < 0

    def test_analyze_us_sentiment_neutral(self):
        """Test US sentiment with mixed signals."""
        prices = [100 + i * 0.01 for i in range(60)]  # Nearly flat

        result = analyze_us_sentiment(
            vix=18.0,  # Normal VIX
            vix_3m=18.0,  # Flat term structure
            spy_prices=prices,
            qqq_prices=prices,
            pcr=0.85,  # Neutral PCR
        )

        assert result.composite_signal == TrendSignal.NEUTRAL
        assert -20 <= result.composite_score <= 20

    def test_analyze_hk_sentiment(self):
        """Test HK sentiment analysis."""
        hsi_prices = list(range(20, 50))
        hstech_prices = list(range(10, 40))

        result = analyze_hk_sentiment(
            vhsi_proxy=25.0,
            vhsi_3m_proxy=22.0,
            hsi_prices=hsi_prices,
            hstech_prices=hstech_prices,
        )

        assert result.market == MarketType.HK
        assert result.vix_value == 25.0
        assert result.primary_trend is not None
        assert result.secondary_trend is not None

    def test_calc_composite_score_all_bullish(self):
        """Test composite score with all bullish signals."""
        primary = MarketTrend(
            symbol="SPY",
            signal=TrendSignal.BULLISH,
            strength=0.8,
        )
        secondary = MarketTrend(
            symbol="QQQ",
            signal=TrendSignal.BULLISH,
            strength=0.7,
        )

        score = calc_composite_score(
            vix_signal=TrendSignal.BULLISH,
            term_signal=TrendSignal.BULLISH,
            primary_trend=primary,
            secondary_trend=secondary,
            pcr_signal=TrendSignal.BULLISH,
        )

        assert score > 50  # Strong bullish

    def test_calc_composite_score_mixed(self):
        """Test composite score with mixed signals."""
        primary = MarketTrend(
            symbol="SPY",
            signal=TrendSignal.BULLISH,
            strength=0.5,
        )
        secondary = MarketTrend(
            symbol="QQQ",
            signal=TrendSignal.BEARISH,
            strength=0.3,
        )

        score = calc_composite_score(
            vix_signal=TrendSignal.NEUTRAL,
            term_signal=TrendSignal.NEUTRAL,
            primary_trend=primary,
            secondary_trend=secondary,
            pcr_signal=TrendSignal.NEUTRAL,
        )

        # Should be slightly positive due to stronger bullish primary
        assert -30 < score < 30

    def test_score_to_signal_thresholds(self):
        """Test score to signal conversion thresholds."""
        assert score_to_signal(50) == TrendSignal.BULLISH
        assert score_to_signal(25) == TrendSignal.BULLISH
        assert score_to_signal(15) == TrendSignal.NEUTRAL
        assert score_to_signal(0) == TrendSignal.NEUTRAL
        assert score_to_signal(-15) == TrendSignal.NEUTRAL
        assert score_to_signal(-25) == TrendSignal.BEARISH
        assert score_to_signal(-50) == TrendSignal.BEARISH

    def test_analyze_us_sentiment_partial_data(self):
        """Test US sentiment with missing data."""
        result = analyze_us_sentiment(
            vix=20.0,
            vix_3m=None,  # Missing VIX3M
            spy_prices=list(range(100, 160)),
            qqq_prices=None,  # Missing QQQ
            pcr=None,  # Missing PCR
        )

        # Should still produce a result
        assert result.market == MarketType.US
        assert result.vix_value == 20.0
        assert result.secondary_trend is None
        assert result.pcr is None

    def test_analyze_term_structure_returns_none_when_missing_data(self):
        """Test that analyze_term_structure returns None when data is missing.

        This is important to distinguish between:
        - None: Cannot calculate (data missing)
        - VixTermStructure(structure=FLAT): Actual flat term structure
        """
        # Missing vix_3m
        result = analyze_term_structure(vix=20.0, vix_3m=None)
        assert result is None

        # Missing vix
        result = analyze_term_structure(vix=None, vix_3m=18.0)
        assert result is None

        # Both missing
        result = analyze_term_structure(vix=None, vix_3m=None)
        assert result is None

    def test_analyze_hk_sentiment_without_term_structure(self):
        """Test HK sentiment when vhsi_3m_proxy is unavailable.

        In production, IBKR cannot provide far-dated HK option IV data,
        so vhsi_3m_proxy is typically None. The sentiment analysis
        should handle this gracefully.
        """
        hsi_prices = list(range(20, 50))
        hstech_prices = list(range(10, 40))

        result = analyze_hk_sentiment(
            vhsi_proxy=25.0,
            vhsi_3m_proxy=None,  # Not available from IBKR
            hsi_prices=hsi_prices,
            hstech_prices=hstech_prices,
            pcr=0.9,
        )

        assert result.market == MarketType.HK
        assert result.vix_value == 25.0
        # Term structure should be None, not a fake FLAT
        assert result.term_structure is None
        # Composite score should still be calculated (without term structure weight)
        assert result.composite_score is not None
        assert result.composite_signal is not None

    def test_analyze_us_sentiment_without_term_structure(self):
        """Test US sentiment when vix_3m is unavailable."""
        spy_prices = list(range(100, 160))
        qqq_prices = list(range(200, 260))

        result = analyze_us_sentiment(
            vix=20.0,
            vix_3m=None,  # Missing
            spy_prices=spy_prices,
            qqq_prices=qqq_prices,
            pcr=0.85,
        )

        assert result.market == MarketType.US
        assert result.term_structure is None
        # Composite score should still work
        assert result.composite_score is not None


class TestSentimentDataBridge:
    """Tests for data bridge integration with real data providers.

    These tests require live connections to data providers (Futu, IBKR).
    Mark with @pytest.mark.integration to skip in CI.
    """

    @pytest.mark.integration
    def test_fetch_us_sentiment_data(self):
        """Test fetching US sentiment data from providers."""
        from src.data.providers import UnifiedDataProvider
        from src.engine.account.sentiment.data_bridge import fetch_us_sentiment_data

        provider = UnifiedDataProvider()
        data = fetch_us_sentiment_data(provider)

        # Should have all expected keys
        assert "vix" in data
        assert "vix_3m" in data
        assert "spy_prices" in data
        assert "qqq_prices" in data
        assert "spy_current" in data
        assert "qqq_current" in data
        assert "pcr" in data

        # VIX data should be available (from Yahoo)
        assert data["vix"] is not None
        assert isinstance(data["vix"], float)
        assert 5 < data["vix"] < 100  # Reasonable VIX range

        # Price data should be available
        assert data["spy_prices"] is not None
        assert len(data["spy_prices"]) > 50  # Enough for trend analysis

    @pytest.mark.integration
    def test_fetch_hk_sentiment_data(self):
        """Test fetching HK sentiment data from providers."""
        from src.data.providers import UnifiedDataProvider
        from src.engine.account.sentiment.data_bridge import fetch_hk_sentiment_data

        provider = UnifiedDataProvider()
        data = fetch_hk_sentiment_data(provider)

        # Should have all expected keys
        assert "vhsi_proxy" in data
        assert "vhsi_3m_proxy" in data
        assert "hsi_prices" in data
        assert "hstech_prices" in data
        assert "hsi_current" in data
        assert "hstech_current" in data
        assert "pcr" in data

        # VHSI proxy should be available (from Futu 800125.HK or IBKR 2800.HK IV)
        assert data["vhsi_proxy"] is not None
        assert isinstance(data["vhsi_proxy"], float)
        assert 5 < data["vhsi_proxy"] < 100  # Reasonable VHSI range

        # vhsi_3m_proxy is expected to be None (IBKR far-dated options not available)
        assert data["vhsi_3m_proxy"] is None

        # HSI prices should be available (from Futu 800000.HK)
        assert data["hsi_prices"] is not None
        assert len(data["hsi_prices"]) > 50

    @pytest.mark.integration
    def test_get_us_sentiment_end_to_end(self):
        """End-to-end test for US sentiment analysis."""
        from src.data.providers import UnifiedDataProvider
        from src.engine.account.sentiment.data_bridge import get_us_sentiment

        provider = UnifiedDataProvider()
        result = get_us_sentiment(provider)

        assert result.market == MarketType.US
        assert result.vix_value is not None
        assert result.composite_score is not None
        assert result.composite_signal in [
            TrendSignal.BULLISH,
            TrendSignal.BEARISH,
            TrendSignal.NEUTRAL,
        ]

    @pytest.mark.integration
    def test_get_hk_sentiment_end_to_end(self):
        """End-to-end test for HK sentiment analysis."""
        from src.data.providers import UnifiedDataProvider
        from src.engine.account.sentiment.data_bridge import get_hk_sentiment

        provider = UnifiedDataProvider()
        result = get_hk_sentiment(provider)

        assert result.market == MarketType.HK
        assert result.vix_value is not None  # VHSI proxy
        # Term structure may be None (expected for HK)
        assert result.composite_score is not None
        assert result.composite_signal in [
            TrendSignal.BULLISH,
            TrendSignal.BEARISH,
            TrendSignal.NEUTRAL,
        ]
