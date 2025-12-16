"""Tests for volatility calculations."""

import pytest

from src.engine.volatility import (
    calc_hv,
    calc_iv_hv_ratio,
    calc_iv_percentile,
    calc_iv_rank,
    get_iv,
)


class TestHistoricalVolatility:
    """Tests for historical volatility calculation."""

    def test_calc_hv_basic(self):
        """Test basic HV calculation."""
        # Generate a simple price series with known volatility
        prices = [100 + i * 0.5 for i in range(30)]  # Slight uptrend
        hv = calc_hv(prices, window=20)

        assert hv is not None
        assert 0 < hv < 1  # Reasonable range for annualized vol

    def test_calc_hv_insufficient_data(self):
        """Test HV with insufficient data."""
        prices = [100, 101, 102]  # Only 3 prices, need 21 for window=20
        hv = calc_hv(prices, window=20)

        assert hv is None

    def test_calc_hv_custom_window(self):
        """Test HV with custom window."""
        prices = [100 + i for i in range(15)]
        hv = calc_hv(prices, window=10)

        assert hv is not None

    def test_calc_hv_not_annualized(self):
        """Test HV without annualization."""
        prices = [100 + i for i in range(25)]
        hv_annual = calc_hv(prices, window=20, annualize=True)
        hv_daily = calc_hv(prices, window=20, annualize=False)

        assert hv_annual is not None
        assert hv_daily is not None
        assert hv_annual > hv_daily  # Annualized should be higher


class TestImpliedVolatility:
    """Tests for implied volatility functions."""

    def test_calc_iv_hv_ratio_basic(self):
        """Test IV/HV ratio calculation."""
        ratio = calc_iv_hv_ratio(0.30, 0.20)
        assert abs(ratio - 1.5) < 0.001

    def test_calc_iv_hv_ratio_cheap(self):
        """Test IV/HV ratio when options are cheap."""
        ratio = calc_iv_hv_ratio(0.15, 0.25)
        assert ratio == 0.6

    def test_calc_iv_hv_ratio_zero_hv(self):
        """Test IV/HV ratio with zero HV."""
        ratio = calc_iv_hv_ratio(0.25, 0)
        assert ratio is None

    def test_calc_iv_hv_ratio_none_inputs(self):
        """Test IV/HV ratio with None inputs."""
        assert calc_iv_hv_ratio(None, 0.20) is None
        assert calc_iv_hv_ratio(0.30, None) is None


class TestIVRank:
    """Tests for IV Rank calculations."""

    def test_calc_iv_rank_middle(self):
        """Test IV Rank in middle of range."""
        hist_ivs = [0.15, 0.20, 0.25, 0.30, 0.35]
        rank = calc_iv_rank(0.25, hist_ivs)
        assert abs(rank - 50.0) < 0.01

    def test_calc_iv_rank_low(self):
        """Test IV Rank at low end."""
        hist_ivs = [0.15, 0.20, 0.25, 0.30, 0.35]
        rank = calc_iv_rank(0.15, hist_ivs)
        assert rank == 0.0

    def test_calc_iv_rank_high(self):
        """Test IV Rank at high end."""
        hist_ivs = [0.15, 0.20, 0.25, 0.30, 0.35]
        rank = calc_iv_rank(0.35, hist_ivs)
        assert rank == 100.0

    def test_calc_iv_rank_equal_ivs(self):
        """Test IV Rank when all historical IVs are equal."""
        hist_ivs = [0.25, 0.25, 0.25, 0.25]
        rank = calc_iv_rank(0.25, hist_ivs)
        assert rank == 50.0  # Default to middle

    def test_calc_iv_percentile(self):
        """Test IV Percentile calculation."""
        hist_ivs = [0.15, 0.20, 0.25, 0.30, 0.35]
        percentile = calc_iv_percentile(0.25, hist_ivs)
        assert percentile == 40.0  # 2 out of 5 are lower
