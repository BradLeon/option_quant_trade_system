"""Tests for VIX term structure analysis module."""

import pytest

from src.engine.account.sentiment.term_structure import (
    TermStructureResult,
    calc_term_structure,
    get_term_structure_regime,
    get_term_structure_state,
    interpret_term_structure,
    is_term_structure_favorable,
)
from src.engine.models.enums import TermStructureState


class TestCalcTermStructure:
    """Tests for calc_term_structure function."""

    def test_contango_structure(self):
        """Test contango (normal) term structure: VIX < VIX3M."""
        result = calc_term_structure(vix=18.0, vix3m=20.0)

        assert result is not None
        assert result.ratio == pytest.approx(0.9)
        assert result.state == TermStructureState.CONTANGO
        assert result.is_favorable is True

    def test_backwardation_structure(self):
        """Test backwardation (stressed) term structure: VIX > VIX3M."""
        result = calc_term_structure(vix=25.0, vix3m=20.0)

        assert result is not None
        assert result.ratio == pytest.approx(1.25)
        assert result.state == TermStructureState.BACKWARDATION
        assert result.is_favorable is False

    def test_flat_structure(self):
        """Test flat term structure: VIX ≈ VIX3M."""
        result = calc_term_structure(vix=20.0, vix3m=20.0)

        assert result is not None
        assert result.ratio == pytest.approx(1.0)
        assert result.state == TermStructureState.FLAT
        assert result.is_favorable is True  # 1.0 <= max_ratio

    def test_invalid_inputs(self):
        """Test with invalid inputs."""
        assert calc_term_structure(vix=None, vix3m=20.0) is None
        assert calc_term_structure(vix=18.0, vix3m=None) is None
        assert calc_term_structure(vix=18.0, vix3m=0) is None
        assert calc_term_structure(vix=18.0, vix3m=-5) is None


class TestGetTermStructureState:
    """Tests for get_term_structure_state function."""

    def test_contango_state(self):
        """Test contango classification."""
        assert get_term_structure_state(0.85) == TermStructureState.CONTANGO
        assert get_term_structure_state(0.90) == TermStructureState.CONTANGO
        assert get_term_structure_state(0.97) == TermStructureState.CONTANGO

    def test_flat_state(self):
        """Test flat classification."""
        assert get_term_structure_state(0.99) == TermStructureState.FLAT
        assert get_term_structure_state(1.00) == TermStructureState.FLAT
        assert get_term_structure_state(1.01) == TermStructureState.FLAT

    def test_backwardation_state(self):
        """Test backwardation classification."""
        assert get_term_structure_state(1.03) == TermStructureState.BACKWARDATION
        assert get_term_structure_state(1.10) == TermStructureState.BACKWARDATION
        assert get_term_structure_state(1.25) == TermStructureState.BACKWARDATION

    def test_none_input(self):
        """Test with None input."""
        assert get_term_structure_state(None) == TermStructureState.FLAT


class TestIsTermStructureFavorable:
    """Tests for is_term_structure_favorable function."""

    def test_favorable_conditions(self):
        """Test favorable conditions (contango)."""
        assert is_term_structure_favorable(0.85) is True
        assert is_term_structure_favorable(0.95) is True
        assert is_term_structure_favorable(1.00) is True

    def test_unfavorable_conditions(self):
        """Test unfavorable conditions (backwardation)."""
        assert is_term_structure_favorable(1.01) is False
        assert is_term_structure_favorable(1.10) is False
        assert is_term_structure_favorable(1.25) is False

    def test_custom_threshold(self):
        """Test with custom threshold."""
        assert is_term_structure_favorable(1.05, max_ratio=1.10) is True
        assert is_term_structure_favorable(1.15, max_ratio=1.10) is False

    def test_none_input(self):
        """Test with None input."""
        assert is_term_structure_favorable(None) is False


class TestGetTermStructureRegime:
    """Tests for get_term_structure_regime function."""

    def test_strong_contango(self):
        """Test strong contango regime."""
        assert get_term_structure_regime(0.85) == "strong_contango"

    def test_normal_contango(self):
        """Test normal contango regime."""
        assert get_term_structure_regime(0.95) == "normal_contango"

    def test_flat_regime(self):
        """Test flat regime."""
        assert get_term_structure_regime(1.00) == "flat"

    def test_mild_backwardation(self):
        """Test mild backwardation regime."""
        assert get_term_structure_regime(1.05) == "mild_backwardation"

    def test_stressed_backwardation(self):
        """Test stressed backwardation regime."""
        assert get_term_structure_regime(1.15) == "stressed_backwardation"

    def test_none_input(self):
        """Test with None input."""
        assert get_term_structure_regime(None) == "unknown"


class TestInterpretTermStructure:
    """Tests for interpret_term_structure function."""

    def test_interpretation_strong_contango(self):
        """Test interpretation for strong contango."""
        result = interpret_term_structure(0.85)
        assert "Strong contango" in result
        assert "favorable" in result

    def test_interpretation_stressed_backwardation(self):
        """Test interpretation for stressed backwardation."""
        result = interpret_term_structure(1.15)
        assert "Stressed backwardation" in result
        assert "caution" in result

    def test_interpretation_none(self):
        """Test interpretation with None."""
        result = interpret_term_structure(None)
        assert "Unable to calculate" in result
