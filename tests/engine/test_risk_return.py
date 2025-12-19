"""Tests for position-level risk/return calculations (SAS, PREI, TGR)."""

import pytest
import math

from src.data.models.option import Greeks
from src.engine.models.position import Position
from src.engine.position.option_metrics import calc_sas
from src.engine.position.risk_return import calc_prei, calc_tgr, calc_roc_from_dte, calc_risk_reward_ratio


class TestSAS:
    """Tests for Strategy Attractiveness Score (SAS)."""

    def test_calc_sas_high_attractiveness(self):
        """High attractiveness: IV > HV, good Sharpe, high win prob."""
        sas = calc_sas(iv=0.30, hv=0.20, sharpe_ratio=2.0, win_probability=0.85)
        assert sas is not None
        # IV/HV = 1.5 -> score = 75
        # Sharpe = 2.0 -> score = 66.67
        # Win = 0.85 -> score = 85
        # Weighted: 0.35*75 + 0.35*66.67 + 0.30*85 = 26.25 + 23.33 + 25.5 = 75.08
        assert sas > 70  # Should be high score

    def test_calc_sas_low_attractiveness(self):
        """Low attractiveness: IV < HV, low Sharpe."""
        sas = calc_sas(iv=0.15, hv=0.20, sharpe_ratio=0.5, win_probability=0.60)
        assert sas is not None
        # IV/HV = 0.75 -> score = 37.5
        # Sharpe = 0.5 -> score = 16.67
        # Win = 0.60 -> score = 60
        # Weighted: 0.35*37.5 + 0.35*16.67 + 0.30*60 = 13.125 + 5.83 + 18 = 36.96
        assert sas < 50  # Should be low score

    def test_calc_sas_maximum_values(self):
        """Test SAS with maximum/capped values."""
        sas = calc_sas(iv=0.50, hv=0.20, sharpe_ratio=5.0, win_probability=0.95)
        assert sas is not None
        # IV/HV = 2.5, capped at 2.0 -> score = 100
        # Sharpe = 5.0, capped at 3.0 -> score = 100
        # Win = 0.95 -> score = 95
        # Weighted: 0.35*100 + 0.35*100 + 0.30*95 = 35 + 35 + 28.5 = 98.5
        assert sas > 95

    def test_calc_sas_minimum_values(self):
        """Test SAS with minimum values."""
        sas = calc_sas(iv=0.10, hv=0.50, sharpe_ratio=0.0, win_probability=0.30)
        assert sas is not None
        # IV/HV = 0.2 -> score = 10
        # Sharpe = 0 -> score = 0
        # Win = 0.30 -> score = 30
        # Weighted: 0.35*10 + 0.35*0 + 0.30*30 = 3.5 + 0 + 9 = 12.5
        assert sas < 20

    def test_calc_sas_negative_sharpe(self):
        """Test SAS with negative Sharpe (clamped to 0)."""
        sas = calc_sas(iv=0.20, hv=0.20, sharpe_ratio=-1.0, win_probability=0.50)
        assert sas is not None
        # IV/HV = 1.0 -> score = 50
        # Sharpe = -1.0, clamped to 0 -> score = 0
        # Win = 0.50 -> score = 50
        # Weighted: 0.35*50 + 0.35*0 + 0.30*50 = 17.5 + 0 + 15 = 32.5
        assert 30 <= sas <= 35

    def test_calc_sas_custom_weights(self):
        """Test SAS with custom weights."""
        # Equal weighting
        sas = calc_sas(
            iv=0.30, hv=0.20, sharpe_ratio=1.5, win_probability=0.80,
            weights=(0.33, 0.34, 0.33)
        )
        assert sas is not None
        assert 50 <= sas <= 80

    def test_calc_sas_invalid_hv_zero(self):
        """Test SAS returns None for zero HV."""
        assert calc_sas(iv=0.20, hv=0.0, sharpe_ratio=1.0, win_probability=0.70) is None

    def test_calc_sas_invalid_hv_negative(self):
        """Test SAS returns None for negative HV."""
        assert calc_sas(iv=0.20, hv=-0.10, sharpe_ratio=1.0, win_probability=0.70) is None

    def test_calc_sas_invalid_win_probability(self):
        """Test SAS returns None for out-of-range win probability."""
        assert calc_sas(iv=0.20, hv=0.20, sharpe_ratio=1.0, win_probability=1.5) is None
        assert calc_sas(iv=0.20, hv=0.20, sharpe_ratio=1.0, win_probability=-0.1) is None

    def test_calc_sas_none_inputs(self):
        """Test SAS returns None for None inputs."""
        assert calc_sas(iv=None, hv=0.20, sharpe_ratio=1.0, win_probability=0.70) is None
        assert calc_sas(iv=0.20, hv=None, sharpe_ratio=1.0, win_probability=0.70) is None
        assert calc_sas(iv=0.20, hv=0.20, sharpe_ratio=None, win_probability=0.70) is None
        assert calc_sas(iv=0.20, hv=0.20, sharpe_ratio=1.0, win_probability=None) is None


class TestPREI:
    """Tests for Position Risk Exposure Index (PREI).

    Uses sigmoid normalization aligned with calc_portfolio_prei:
    - Gamma_Risk = |gamma| / (|gamma| + k), k=1.0
    - Vega_Risk = |vega| / (|vega| + k), k=100.0
    - DTE_Risk = sqrt(1 / max(1, DTE))
    """

    def test_calc_prei_high_gamma(self):
        """High gamma position should have high risk."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=1.0, vega=100.0),  # gamma=1 -> risk=0.5, vega=100 -> risk=0.5
            underlying_price=500.0,
            dte=30,
        )
        prei = calc_prei(pos)
        assert prei is not None
        # gamma_risk = 1/(1+1) = 0.5
        # vega_risk = 100/(100+100) = 0.5
        # dte_risk = sqrt(1/30) ≈ 0.183
        # prei = (0.4*0.5 + 0.3*0.5 + 0.3*0.183) * 100 = 40.5
        assert 35 <= prei <= 45

    def test_calc_prei_low_gamma(self):
        """Low gamma position should have low risk."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.01, vega=10.0),
            underlying_price=100.0,
            dte=60,
        )
        prei = calc_prei(pos)
        assert prei is not None
        # gamma_risk = 0.01/(0.01+1) ≈ 0.0099
        # vega_risk = 10/(10+100) ≈ 0.091
        # dte_risk = sqrt(1/60) ≈ 0.129
        # prei should be low
        assert prei < 15

    def test_calc_prei_near_expiry(self):
        """Near expiry position should have higher DTE risk."""
        pos_far = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.05, vega=20.0),
            underlying_price=200.0,
            dte=45,
        )
        pos_near = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.05, vega=20.0),
            underlying_price=200.0,
            dte=3,
        )

        prei_far = calc_prei(pos_far)
        prei_near = calc_prei(pos_near)

        assert prei_far is not None
        assert prei_near is not None
        # Near expiry should have higher risk
        assert prei_near > prei_far

    def test_calc_prei_dte_one(self):
        """Test PREI at DTE=1 (maximum DTE risk component)."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.02, vega=10.0),
            underlying_price=200.0,
            dte=1,
        )
        prei = calc_prei(pos)
        assert prei is not None
        # DTE_Risk = sqrt(1/1) = 1.0 (maximum)
        # This should push PREI higher
        assert prei > 25

    def test_calc_prei_custom_weights(self):
        """Test PREI with custom weights emphasizing DTE risk."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.02, vega=10.0),
            underlying_price=200.0,
            dte=5,
        )
        prei_default = calc_prei(pos)
        prei_dte_heavy = calc_prei(pos, weights=(0.20, 0.20, 0.60))

        assert prei_default is not None
        assert prei_dte_heavy is not None
        # DTE risk emphasized should change the score
        # (Result depends on relative component values)

    def test_calc_prei_missing_gamma(self):
        """Test PREI returns None when gamma is missing."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(vega=10.0),
            underlying_price=200.0,
            dte=30,
        )
        assert calc_prei(pos) is None

    def test_calc_prei_missing_vega(self):
        """Test PREI returns None when vega is missing."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.02),
            underlying_price=200.0,
            dte=30,
        )
        assert calc_prei(pos) is None

    def test_calc_prei_missing_dte(self):
        """Test PREI returns None when DTE is missing."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.02, vega=10.0),
            underlying_price=200.0,
        )
        assert calc_prei(pos) is None


class TestTGR:
    """Tests for Theta/Gamma Ratio (TGR)."""

    def test_calc_tgr_basic(self):
        """Test basic TGR calculation."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(theta=-0.05, gamma=0.01),
        )
        tgr = calc_tgr(pos)
        assert tgr is not None
        # TGR = abs(-0.05) / abs(0.01) = 5.0
        assert tgr == 5.0

    def test_calc_tgr_zero_gamma(self):
        """Test TGR returns None for zero gamma."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(theta=-0.05, gamma=0),
        )
        assert calc_tgr(pos) is None

    def test_calc_tgr_missing_theta(self):
        """Test TGR returns None when theta is missing."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(gamma=0.01),
        )
        assert calc_tgr(pos) is None

    def test_calc_tgr_missing_gamma(self):
        """Test TGR returns None when gamma is missing."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(theta=-0.05),
        )
        assert calc_tgr(pos) is None

    def test_calc_tgr_absolute_values(self):
        """Test TGR uses absolute values."""
        pos = Position(
            symbol="AAPL",
            quantity=1,
            greeks=Greeks(theta=-0.10, gamma=-0.02),  # Negative theta and gamma
        )
        tgr = calc_tgr(pos)
        assert tgr is not None
        # TGR = abs(-0.10) / abs(-0.02) = 5.0
        assert tgr == 5.0


class TestRiskReturn:
    """Tests for other risk/return calculations."""

    def test_calc_roc_from_dte(self):
        """Test annualized ROC from DTE."""
        roc = calc_roc_from_dte(profit=65, capital=5500, dte=30)
        assert roc is not None
        # Simple ROC = 65/5500 = 0.0118
        # Annualized = 0.0118 * (365/30) = 0.144
        assert abs(roc - 0.144) < 0.01

    def test_calc_roc_from_dte_zero_capital(self):
        """Test ROC returns None for zero capital."""
        assert calc_roc_from_dte(profit=65, capital=0, dte=30) is None

    def test_calc_roc_from_dte_zero_dte(self):
        """Test ROC returns None for zero DTE."""
        assert calc_roc_from_dte(profit=65, capital=5500, dte=0) is None

    def test_calc_risk_reward_ratio(self):
        """Test risk/reward ratio calculation."""
        ratio = calc_risk_reward_ratio(max_profit=650, max_loss=5500)
        assert ratio is not None
        assert abs(ratio - 8.46) < 0.01  # 5500/650

    def test_calc_risk_reward_ratio_zero_profit(self):
        """Test risk/reward returns None for zero max profit."""
        assert calc_risk_reward_ratio(max_profit=0, max_loss=5500) is None
