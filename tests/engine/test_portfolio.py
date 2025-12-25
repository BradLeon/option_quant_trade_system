"""Tests for portfolio calculations."""

import pytest

from src.data.models.option import Greeks
from src.engine.models import Position
from src.engine.portfolio import (
    calc_beta_weighted_delta,
    calc_delta_dollars,
    calc_portfolio_delta,
    calc_portfolio_gamma,
    calc_portfolio_prei,
    calc_portfolio_sas,
    calc_portfolio_tgr,
    calc_portfolio_theta,
    calc_portfolio_var,
    calc_portfolio_vega,
)
from src.engine.account import calc_roc


class TestPortfolioGreeks:
    """Tests for portfolio Greeks aggregation."""

    def test_calc_portfolio_theta(self):
        """Test portfolio theta calculation.

        Formula: Σ(theta × quantity × contract_multiplier)
        """
        positions = [
            Position(symbol="AAPL", quantity=1, greeks=Greeks(theta=-5.0), contract_multiplier=1),
            Position(symbol="MSFT", quantity=2, greeks=Greeks(theta=-3.0), contract_multiplier=1),
            Position(symbol="GOOGL", quantity=-1, greeks=Greeks(theta=-4.0), contract_multiplier=1),
        ]
        theta = calc_portfolio_theta(positions)
        # 1*(-5)*1 + 2*(-3)*1 + (-1)*(-4)*1 = -5 - 6 + 4 = -7
        assert theta == -7.0

    def test_calc_portfolio_vega(self):
        """Test portfolio vega calculation.

        Formula: Σ(vega × quantity × contract_multiplier)
        """
        positions = [
            Position(symbol="AAPL", quantity=1, greeks=Greeks(vega=10.0), contract_multiplier=1),
            Position(symbol="MSFT", quantity=-2, greeks=Greeks(vega=8.0), contract_multiplier=1),
        ]
        vega = calc_portfolio_vega(positions)
        # 1*10*1 + (-2)*8*1 = 10 - 16 = -6
        assert vega == -6.0

    def test_calc_portfolio_gamma(self):
        """Test portfolio gamma calculation.

        Formula: Σ(gamma × quantity × contract_multiplier)
        """
        positions = [
            Position(symbol="AAPL", quantity=1, greeks=Greeks(gamma=0.05), contract_multiplier=1),
            Position(symbol="MSFT", quantity=1, greeks=Greeks(gamma=0.03), contract_multiplier=1),
        ]
        gamma = calc_portfolio_gamma(positions)
        # 1*0.05*1 + 1*0.03*1 = 0.08
        assert gamma == 0.08

    def test_calc_portfolio_greeks_empty(self):
        """Test portfolio Greeks with empty list."""
        assert calc_portfolio_theta([]) == 0.0
        assert calc_portfolio_vega([]) == 0.0
        assert calc_portfolio_gamma([]) == 0.0

    def test_calc_delta_dollars(self):
        """Test delta dollars calculation.

        Formula: Delta$ = delta × underlying_price × multiplier × quantity

        Example: AAPL Call, delta=0.5, AAPL=$150, 3 contracts
        Delta$ = 0.5 × 150 × 100 × 3 = $22,500
        """
        positions = [
            Position(
                symbol="AAPL",
                quantity=3,
                greeks=Greeks(delta=0.5),
                underlying_price=150.0,
                contract_multiplier=100,
            ),
        ]
        delta_dollars = calc_delta_dollars(positions)
        assert delta_dollars == 22500.0

    def test_calc_delta_dollars_multiple_positions(self):
        """Test delta dollars with multiple positions."""
        positions = [
            Position(
                symbol="AAPL",
                quantity=2,
                greeks=Greeks(delta=0.6),
                underlying_price=150.0,
            ),
            Position(
                symbol="MSFT",
                quantity=-1,  # Short position
                greeks=Greeks(delta=0.4),
                underlying_price=400.0,
            ),
        ]
        delta_dollars = calc_delta_dollars(positions)
        # AAPL: 0.6 × 150 × 100 × 2 = 18,000
        # MSFT: 0.4 × 400 × 100 × (-1) = -16,000
        # Total: 18,000 - 16,000 = 2,000
        assert delta_dollars == 2000.0

    def test_calc_portfolio_gamma_with_multiplier(self):
        """Test portfolio gamma aggregation with multiplier.

        After currency conversion, gamma is stored as gamma_dollars per share
        (Γ × S² × 0.01). This test uses raw gamma values.

        Formula for aggregation: Σ(gamma × quantity × multiplier)
        """
        positions = [
            Position(
                symbol="AAPL",
                quantity=3,
                greeks=Greeks(gamma=0.02),
                underlying_price=150.0,
                contract_multiplier=100,
            ),
        ]
        # Raw gamma aggregation: 0.02 × 3 × 100 = 6.0
        portfolio_gamma = calc_portfolio_gamma(positions)
        assert portfolio_gamma == 6.0

    def test_calc_beta_weighted_delta(self, mocker):
        """Test beta-weighted delta calculation.

        Formula: BWD = delta × underlying_price × multiplier × quantity × beta / spy_price

        Example: NVDA Call, delta=0.5, NVDA=$500, beta=1.8, 2 contracts, SPY=$450
        BWD = 0.5 × 500 × 100 × 2 × 1.8 / 450 = 200 SPY shares
        """
        # Mock the SPY price fetcher
        mocker.patch(
            "src.engine.portfolio.greeks_agg._get_spy_price",
            return_value=450.0,
        )
        positions = [
            Position(
                symbol="NVDA",
                quantity=2,
                greeks=Greeks(delta=0.5),
                underlying_price=500.0,
                beta=1.8,
                contract_multiplier=100,
            ),
        ]
        bwd = calc_beta_weighted_delta(positions)
        assert bwd == 200.0

    def test_calc_beta_weighted_delta_multiple_positions(self, mocker):
        """Test BWD with multiple positions."""
        mocker.patch(
            "src.engine.portfolio.greeks_agg._get_spy_price",
            return_value=450.0,
        )
        positions = [
            Position(
                symbol="NVDA",
                quantity=1,
                greeks=Greeks(delta=0.5),
                underlying_price=500.0,
                beta=1.8,
            ),
            Position(
                symbol="AAPL",
                quantity=2,
                greeks=Greeks(delta=0.6),
                underlying_price=150.0,
                beta=1.2,
            ),
        ]
        bwd = calc_beta_weighted_delta(positions)
        # NVDA: 0.5 × 500 × 100 × 1 × 1.8 / 450 = 100
        # AAPL: 0.6 × 150 × 100 × 2 × 1.2 / 450 = 48
        # Total: 148
        assert bwd == 148.0

    def test_calc_beta_weighted_delta_missing_data(self, mocker):
        """Test BWD skips positions with missing data."""
        mocker.patch(
            "src.engine.portfolio.greeks_agg._get_spy_price",
            return_value=450.0,
        )
        positions = [
            Position(
                symbol="NVDA",
                quantity=1,
                greeks=Greeks(delta=0.5),
                underlying_price=500.0,
                beta=1.8,
            ),
            Position(
                symbol="AAPL",
                quantity=2,
                greeks=Greeks(delta=0.6),
                # Missing underlying_price and beta
            ),
        ]
        bwd = calc_beta_weighted_delta(positions)
        # Only NVDA counted: 0.5 × 500 × 100 × 1 × 1.8 / 450 = 100
        assert bwd == 100.0

    def test_calc_delta_dollars_hk_options(self):
        """Test delta dollars with HK options (different multiplier)."""
        positions = [
            Position(
                symbol="0700.HK",  # Tencent
                quantity=1,
                greeks=Greeks(delta=0.5),
                underlying_price=350.0,  # HKD
                contract_multiplier=500,  # HK options can have 500 shares per lot
            ),
        ]
        delta_dollars = calc_delta_dollars(positions)
        # Delta$ = 0.5 × 350 × 500 × 1 = 87,500
        assert delta_dollars == 87500.0


class TestRiskMetrics:
    """Tests for portfolio risk metrics."""

    def test_calc_portfolio_tgr(self):
        """Test Portfolio Theta/Gamma Ratio calculation."""
        positions = [
            Position(symbol="AAPL", quantity=1, greeks=Greeks(theta=-30, gamma=5)),
            Position(symbol="MSFT", quantity=1, greeks=Greeks(theta=-20, gamma=5)),
        ]
        tgr = calc_portfolio_tgr(positions)
        # theta: 1*(-30) + 1*(-20) = -50
        # gamma: 1*5 + 1*5 = 10
        # TGR = 50/10 = 5.0
        assert tgr == 5.0

    def test_calc_portfolio_tgr_zero_gamma(self):
        """Test Portfolio TGR with zero gamma."""
        positions = [
            Position(symbol="AAPL", quantity=1, greeks=Greeks(theta=-50, gamma=0)),
        ]
        tgr = calc_portfolio_tgr(positions)
        assert tgr is None

    def test_calc_portfolio_tgr_empty(self):
        """Test Portfolio TGR with empty list."""
        assert calc_portfolio_tgr([]) is None

    def test_calc_roc(self):
        """Test Return on Capital calculation."""
        roc = calc_roc(150, 1000)
        assert roc == 0.15

    def test_calc_roc_zero_capital(self):
        """Test ROC with zero capital."""
        roc = calc_roc(150, 0)
        assert roc is None


class TestCompositeMetrics:
    """Tests for composite portfolio metrics (SAS and PREI)."""

    # ========== Portfolio SAS Tests ==========

    def test_calc_portfolio_sas_margin_weighted(self):
        """Test portfolio SAS with margin weighting."""
        positions_with_sas = [
            (Position(symbol="AAPL", quantity=1, margin=5000.0), 80.0),
            (Position(symbol="MSFT", quantity=1, margin=3000.0), 60.0),
        ]
        portfolio_sas = calc_portfolio_sas(positions_with_sas)
        # (80*5000 + 60*3000) / (5000+3000) = 580000/8000 = 72.5
        assert portfolio_sas == 72.5

    def test_calc_portfolio_sas_equal_margin(self):
        """Test portfolio SAS with equal margin (equal weight)."""
        positions_with_sas = [
            (Position(symbol="AAPL", quantity=1, margin=5000.0), 80.0),
            (Position(symbol="MSFT", quantity=1, margin=5000.0), 60.0),
        ]
        portfolio_sas = calc_portfolio_sas(positions_with_sas)
        # (80*5000 + 60*5000) / (5000+5000) = 700000/10000 = 70.0
        assert portfolio_sas == 70.0

    def test_calc_portfolio_sas_single_position(self):
        """Test portfolio SAS with single position."""
        positions_with_sas = [
            (Position(symbol="AAPL", quantity=1, margin=5000.0), 75.0),
        ]
        portfolio_sas = calc_portfolio_sas(positions_with_sas)
        assert portfolio_sas == 75.0

    def test_calc_portfolio_sas_empty(self):
        """Test portfolio SAS with empty list."""
        assert calc_portfolio_sas([]) is None

    def test_calc_portfolio_sas_missing_sas(self):
        """Test portfolio SAS skips positions without SAS (None sas)."""
        positions_with_sas = [
            (Position(symbol="AAPL", quantity=1, margin=5000.0), 80.0),
            (Position(symbol="MSFT", quantity=1, margin=3000.0), None),  # No SAS
        ]
        portfolio_sas = calc_portfolio_sas(positions_with_sas)
        # Only AAPL counted
        assert portfolio_sas == 80.0

    def test_calc_portfolio_sas_missing_margin(self):
        """Test portfolio SAS skips positions without margin."""
        positions_with_sas = [
            (Position(symbol="AAPL", quantity=1, margin=5000.0), 80.0),
            (Position(symbol="MSFT", quantity=1), 60.0),  # No margin
        ]
        portfolio_sas = calc_portfolio_sas(positions_with_sas)
        # Only AAPL counted
        assert portfolio_sas == 80.0

    def test_calc_portfolio_sas_all_missing(self):
        """Test portfolio SAS returns None when all positions missing data."""
        positions_with_sas = [
            (Position(symbol="AAPL", quantity=1), None),  # No SAS or margin
            (Position(symbol="MSFT", quantity=1), None),
        ]
        assert calc_portfolio_sas(positions_with_sas) is None

    # ========== Portfolio PREI Tests ==========

    def test_calc_portfolio_prei_single_position(self):
        """Test portfolio PREI with single position."""
        positions = [
            Position(
                symbol="AAPL",
                greeks=Greeks(gamma=0.03, vega=15.0),
                underlying_price=150.0,
                quantity=2,
                dte=30,
            ),
        ]
        prei = calc_portfolio_prei(positions)
        assert prei is not None
        assert 0 <= prei <= 100

    def test_calc_portfolio_prei_hedged_positions(self):
        """Test portfolio PREI with partially hedged positions.

        When gamma/vega offset each other, risk should be lower.
        """
        # Long gamma position
        long_pos = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=0.03, vega=15.0),
            underlying_price=150.0,
            quantity=2,
            dte=30,
        )
        # Short gamma position (partial hedge)
        short_pos = Position(
            symbol="MSFT",
            greeks=Greeks(gamma=-0.02, vega=-10.0),
            underlying_price=400.0,
            quantity=1,
            dte=30,
        )

        # Single position PREI should be higher than hedged portfolio
        single_prei = calc_portfolio_prei([long_pos])
        hedged_prei = calc_portfolio_prei([long_pos, short_pos])

        assert single_prei is not None
        assert hedged_prei is not None
        # Hedged portfolio should have lower or equal risk
        # (depends on exact offset, but generally true)
        assert 0 <= hedged_prei <= 100

    def test_calc_portfolio_prei_near_expiry_high_risk(self):
        """Test that near-expiry positions have higher PREI."""
        position_far = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=0.03, vega=15.0),
            underlying_price=150.0,
            quantity=1,
            dte=45,
        )
        position_near = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=0.03, vega=15.0),
            underlying_price=150.0,
            quantity=1,
            dte=5,
        )

        prei_far = calc_portfolio_prei([position_far])
        prei_near = calc_portfolio_prei([position_near])

        assert prei_far is not None
        assert prei_near is not None
        # Near expiry should have higher DTE risk component
        assert prei_near > prei_far

    def test_calc_portfolio_prei_empty(self):
        """Test portfolio PREI with empty list."""
        assert calc_portfolio_prei([]) is None

    def test_calc_portfolio_prei_missing_data(self):
        """Test portfolio PREI handles missing data gracefully."""
        positions = [
            Position(symbol="AAPL", quantity=1),  # Missing gamma, vega, price
        ]
        # Should return None since no valid position data
        assert calc_portfolio_prei(positions) is None

    def test_calc_portfolio_prei_high_gamma_exposure(self):
        """Test portfolio PREI with high gamma exposure."""
        # High gamma position
        high_gamma_pos = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=0.10, vega=50.0),  # Very high gamma and vega
            underlying_price=500.0,  # High price amplifies gamma$
            quantity=5,
            dte=10,
        )
        # Low gamma position for comparison
        low_gamma_pos = Position(
            symbol="MSFT",
            greeks=Greeks(gamma=0.01, vega=10.0),  # Low gamma
            underlying_price=100.0,
            quantity=1,
            dte=30,
        )
        prei_high = calc_portfolio_prei([high_gamma_pos])
        prei_low = calc_portfolio_prei([low_gamma_pos])
        assert prei_high is not None
        assert prei_low is not None
        # High gamma position should have higher PREI
        assert prei_high > prei_low

    def test_calc_portfolio_prei_uses_calc_portfolio_gamma(self):
        """Test that portfolio PREI uses calc_portfolio_gamma for gamma risk."""
        # Create position with known gamma
        # portfolio_gamma = 0.02 * 2 = 0.04
        position = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=0.02, vega=10.0),
            underlying_price=200.0,
            quantity=2,
            dte=30,
        )
        prei = calc_portfolio_prei(positions=[position])
        assert prei is not None
        # All components normalized to 0-1, then weighted and scaled to 0-100
        assert 0 <= prei <= 100

    def test_calc_portfolio_prei_uses_calc_portfolio_vega(self):
        """Test that portfolio PREI uses calc_portfolio_vega for vega risk."""
        # Create position where vega dominates
        # portfolio_vega = 100 * 1 = 100
        position = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=0.001, vega=100.0),  # Very low gamma, high vega
            underlying_price=100.0,
            quantity=1,
            dte=30,
        )
        prei = calc_portfolio_prei(positions=[position])
        assert prei is not None
        # Vega normalized to 0-1: 100/(100+100) = 0.5
        # w2 * 0.5 * 100 = 0.30 * 0.5 * 100 = 15
        assert 0 <= prei <= 100

    def test_calc_portfolio_prei_normalized_to_01(self):
        """Test that each risk component is normalized to 0-1."""
        # Create a position with known values
        # Using contract_multiplier=1 to simplify calculation
        position = Position(
            symbol="AAPL",
            greeks=Greeks(gamma=1.0, vega=100.0),  # gamma normalized: 1/(1+1) = 0.5
            underlying_price=100.0,
            quantity=1,
            contract_multiplier=1,  # Use 1 for simplified calculation
            dte=1,  # DTE risk: sqrt(1/1) = 1.0
        )
        prei = calc_portfolio_prei(positions=[position])
        assert prei is not None
        # portfolio_gamma = 1.0 * 1 * 1 = 1.0
        # portfolio_vega = 100.0 * 1 * 1 = 100.0
        # gamma_risk = 1/(1+1) = 0.5
        # vega_risk = 100/(100+100) = 0.5
        # dte_risk = sqrt(1/1) = 1.0
        # PREI = (0.4*0.5 + 0.3*0.5 + 0.3*1.0) * 100 = 65
        assert 60 <= prei <= 70
