"""Tests for portfolio calculations."""

import pytest

from src.engine.base import Position
from src.engine.portfolio import (
    calc_beta_weighted_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_var,
    calc_portfolio_vega,
    calc_prei,
    calc_roc,
    calc_sas,
    calc_tgr,
)


class TestPortfolioGreeks:
    """Tests for portfolio Greeks aggregation."""

    def test_calc_portfolio_theta(self):
        """Test portfolio theta calculation."""
        positions = [
            Position(symbol="AAPL", quantity=1, theta=-5.0),
            Position(symbol="MSFT", quantity=2, theta=-3.0),
            Position(symbol="GOOGL", quantity=-1, theta=-4.0),
        ]
        theta = calc_portfolio_theta(positions)
        # 1*(-5) + 2*(-3) + (-1)*(-4) = -5 - 6 + 4 = -7
        assert theta == -7.0

    def test_calc_portfolio_vega(self):
        """Test portfolio vega calculation."""
        positions = [
            Position(symbol="AAPL", quantity=1, vega=10.0),
            Position(symbol="MSFT", quantity=-2, vega=8.0),
        ]
        vega = calc_portfolio_vega(positions)
        # 1*10 + (-2)*8 = 10 - 16 = -6
        assert vega == -6.0

    def test_calc_portfolio_gamma(self):
        """Test portfolio gamma calculation."""
        positions = [
            Position(symbol="AAPL", quantity=1, gamma=0.05),
            Position(symbol="MSFT", quantity=1, gamma=0.03),
        ]
        gamma = calc_portfolio_gamma(positions)
        assert gamma == 0.08

    def test_calc_portfolio_greeks_empty(self):
        """Test portfolio Greeks with empty list."""
        assert calc_portfolio_theta([]) == 0.0
        assert calc_portfolio_vega([]) == 0.0
        assert calc_portfolio_gamma([]) == 0.0


class TestRiskMetrics:
    """Tests for portfolio risk metrics."""

    def test_calc_tgr(self):
        """Test Theta/Gamma Ratio calculation."""
        # $50/day theta, 10 gamma
        tgr = calc_tgr(-50, 10)
        assert tgr == 5.0

    def test_calc_tgr_zero_gamma(self):
        """Test TGR with zero gamma."""
        tgr = calc_tgr(-50, 0)
        assert tgr is None

    def test_calc_roc(self):
        """Test Return on Capital calculation."""
        roc = calc_roc(150, 1000)
        assert roc == 0.15

    def test_calc_roc_zero_capital(self):
        """Test ROC with zero capital."""
        roc = calc_roc(150, 0)
        assert roc is None


class TestCompositeMetrics:
    """Tests for composite portfolio metrics."""

    def test_calc_sas_equal_allocation(self):
        """Test SAS with equal allocation."""
        allocations = [0.5, 0.5]
        sas = calc_sas(allocations)
        assert sas == 100.0  # Maximum diversification

    def test_calc_sas_single_strategy(self):
        """Test SAS with single strategy."""
        allocations = [1.0]
        sas = calc_sas(allocations)
        assert sas == 0.0  # No diversification

    def test_calc_sas_three_equal(self):
        """Test SAS with three equal allocations."""
        allocations = [0.33, 0.33, 0.34]
        sas = calc_sas(allocations)
        assert sas > 95.0  # Near maximum for 3 strategies

    def test_calc_prei_moderate_exposure(self):
        """Test PREI with moderate exposures."""
        exposures = {
            "delta": 0.5,
            "gamma": -0.2,
            "theta": 0.3,
            "vega": -0.4,
            "concentration": 0.3,
        }
        prei = calc_prei(exposures)
        assert prei is not None
        assert 0 <= prei <= 100

    def test_calc_prei_low_exposure(self):
        """Test PREI with low exposures."""
        exposures = {
            "delta": 0.1,
            "gamma": 0.05,
            "theta": 0.05,
            "vega": 0.1,
            "concentration": 0.1,
        }
        prei = calc_prei(exposures)
        assert prei is not None
        assert prei < 20  # Should be low

    def test_calc_prei_high_exposure(self):
        """Test PREI with high exposures."""
        exposures = {
            "delta": 0.9,
            "gamma": 0.8,
            "theta": 0.7,
            "vega": 0.9,
            "concentration": 0.8,
        }
        prei = calc_prei(exposures)
        assert prei is not None
        assert prei > 70  # Should be high
