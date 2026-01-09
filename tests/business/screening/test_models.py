"""Tests for screening models"""

import pytest

from src.business.screening.models import (
    ContractOpportunity,
    FilterStatus,
    MarketStatus,
    MarketType,
    ScreeningResult,
    TermStructureStatus,
    TrendStatus,
    UnderlyingScore,
    VolatilityIndexStatus,
    VolatilityStatus,
)


class TestMarketType:
    """Tests for MarketType enum"""

    def test_us_market(self):
        assert MarketType.US.value == "US"

    def test_hk_market(self):
        assert MarketType.HK.value == "HK"


class TestTrendStatus:
    """Tests for TrendStatus enum"""

    def test_trend_values(self):
        assert TrendStatus.STRONG_BULLISH.value == "strong_bullish"
        assert TrendStatus.NEUTRAL.value == "neutral"
        assert TrendStatus.STRONG_BEARISH.value == "strong_bearish"


class TestVolatilityIndexStatus:
    """Tests for VolatilityIndexStatus model"""

    def test_create_volatility_index(self):
        vi = VolatilityIndexStatus(
            symbol="VIX",
            value=18.5,
            percentile=45.0,
            status=VolatilityStatus.NORMAL,
            filter_status=FilterStatus.FAVORABLE,
        )
        assert vi.value == 18.5
        assert vi.percentile == 45.0
        assert vi.filter_status == FilterStatus.FAVORABLE

    def test_default_values(self):
        vi = VolatilityIndexStatus(symbol="VIX", value=20.0)
        assert vi.percentile is None
        assert vi.status == VolatilityStatus.NORMAL


class TestTermStructureStatus:
    """Tests for TermStructureStatus model"""

    def test_contango_structure(self):
        ts = TermStructureStatus(
            vix_value=18.0,
            vix3m_value=20.0,
            ratio=0.90,
            is_contango=True,
        )
        assert ts.is_contango is True
        assert ts.ratio == 0.90

    def test_backwardation_structure(self):
        ts = TermStructureStatus(
            vix_value=25.0,
            vix3m_value=22.0,
            ratio=1.14,
            is_contango=False,
        )
        assert ts.is_contango is False


class TestMarketStatus:
    """Tests for MarketStatus model"""

    def test_create_market_status(self):
        ms = MarketStatus(
            market_type=MarketType.US,
            volatility_index=VolatilityIndexStatus(symbol="VIX", value=18.0),
            overall_trend=TrendStatus.BULLISH,
            is_favorable=True,
        )
        assert ms.is_favorable is True
        assert ms.overall_trend == TrendStatus.BULLISH

    def test_market_status_with_term_structure(self):
        ts = TermStructureStatus(
            vix_value=18.0,
            vix3m_value=20.0,
            ratio=0.90,
            is_contango=True,
        )
        ms = MarketStatus(
            market_type=MarketType.US,
            volatility_index=VolatilityIndexStatus(symbol="VIX", value=18.0),
            overall_trend=TrendStatus.NEUTRAL,
            term_structure=ts,
            is_favorable=True,
        )
        assert ms.term_structure is not None
        assert ms.term_structure.is_contango is True

    def test_get_trend_filter_status(self):
        ms = MarketStatus(
            market_type=MarketType.US,
            overall_trend=TrendStatus.BULLISH,
            is_favorable=True,
        )
        assert ms.get_trend_filter_status() == FilterStatus.FAVORABLE

        ms.overall_trend = TrendStatus.BEARISH
        assert ms.get_trend_filter_status() == FilterStatus.UNFAVORABLE


class TestUnderlyingScore:
    """Tests for UnderlyingScore model"""

    def test_create_underlying_score(self):
        score = UnderlyingScore(
            symbol="AAPL",
            market_type=MarketType.US,
            iv_rank=55.0,
            iv_hv_ratio=1.2,
            passed=True,
        )
        assert score.symbol == "AAPL"
        assert score.passed is True

    def test_composite_score(self):
        score = UnderlyingScore(
            symbol="AAPL",
            market_type=MarketType.US,
            iv_rank=60.0,
            iv_hv_ratio=1.2,
            passed=True,
        )
        # composite_score 应该大于 0
        assert score.composite_score > 0


class TestContractOpportunity:
    """Tests for ContractOpportunity model"""

    def test_create_contract_opportunity(self):
        opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            dte=30,
            option_type="put",
            sas=2.5,
            delta=-0.25,
            gamma=0.02,
            theta=0.05,
            vega=-0.15,
            sharpe_ratio=1.8,
        )
        assert opp.symbol == "AAPL"
        assert opp.dte == 30
        assert opp.sharpe_ratio == 1.8

    def test_bid_ask_spread(self):
        opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            option_type="put",
            bid=2.50,
            ask=2.60,
            mid_price=2.55,
        )
        assert opp.bid_ask_spread is not None
        assert opp.bid_ask_spread == pytest.approx(0.039, rel=0.01)

    def test_is_liquid(self):
        # 流动性好的合约
        liquid_opp = ContractOpportunity(
            symbol="AAPL",
            strike=175.0,
            expiry="2025-01-17",
            option_type="put",
            bid=2.50,
            ask=2.55,
            mid_price=2.525,
            open_interest=500,
        )
        assert liquid_opp.is_liquid is True

        # 流动性差的合约
        illiquid_opp = ContractOpportunity(
            symbol="XYZ",
            strike=50.0,
            expiry="2025-01-17",
            option_type="put",
            bid=1.00,
            ask=1.50,
            mid_price=1.25,
            open_interest=10,
        )
        assert illiquid_opp.is_liquid is False


class TestScreeningResult:
    """Tests for ScreeningResult model"""

    def test_create_screening_result_with_opportunities(self):
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
        assert result.passed is True
        assert len(result.opportunities) == 1
        assert result.scanned_underlyings == 10

    def test_create_screening_result_no_opportunities(self):
        result = ScreeningResult(
            passed=False,
            market_status=None,
            strategy_type="short_put",
            scanned_underlyings=10,
            passed_underlyings=0,
            opportunities=[],
            rejection_reason="市场环境不利",
        )
        assert result.passed is False
        assert result.rejection_reason == "市场环境不利"

    def test_summary_property(self):
        result = ScreeningResult(
            passed=True,
            strategy_type="short_put",
            scanned_underlyings=10,
            passed_underlyings=3,
        )
        summary = result.summary
        assert "passed" in summary
        assert "strategy" in summary
        assert summary["scanned_underlyings"] == 10
