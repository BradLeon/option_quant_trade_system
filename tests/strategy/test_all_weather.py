"""Tests for All-Weather Multi-Asset Allocation Strategy."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from src.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    PortfolioState,
    PositionView,
    SignalType,
)
from src.strategy.signals.cross_asset import CrossAssetConfig, CrossAssetSignalComputer
from src.strategy.versions.all_weather import AllWeatherConfig, AllWeatherStrategy


# ============================================================
# Fixtures
# ============================================================

def _make_market(prices: dict[str, float], d: date | None = None) -> MarketSnapshot:
    return MarketSnapshot(date=d or date(2024, 6, 3), prices=prices)


def _make_portfolio(
    nlv: float = 1_000_000,
    cash: float = 1_000_000,
    positions: list[PositionView] | None = None,
    d: date | None = None,
) -> PortfolioState:
    return PortfolioState(
        date=d or date(2024, 6, 3),
        nlv=nlv,
        cash=cash,
        margin_used=0,
        positions=positions or [],
    )


def _make_position(
    symbol: str,
    quantity: int,
    entry_price: float,
    current_price: float,
    position_id: str | None = None,
) -> PositionView:
    return PositionView(
        position_id=position_id or f"pos_{symbol}",
        instrument=Instrument(type=InstrumentType.STOCK, underlying=symbol, lot_size=1),
        quantity=quantity,
        entry_price=entry_price,
        entry_date=date(2024, 1, 1),
        current_price=current_price,
        underlying_price=current_price,
        unrealized_pnl=(current_price - entry_price) * quantity,
    )


def _make_data_provider(trend_data: dict[str, list[float]] | None = None):
    """Create a mock data provider that returns configurable price histories."""
    dp = MagicMock()

    def get_history_kline(symbol, ktype, start_date, end_date):
        if trend_data and symbol in trend_data:
            prices = trend_data[symbol]
            return [MagicMock(close=p) for p in prices]
        # Default: 300 points trending up (above SMA200)
        return [MagicMock(close=100.0 + i * 0.1) for i in range(300)]

    dp.get_history_kline = get_history_kline
    return dp


# ============================================================
# Weight computation tests
# ============================================================

class TestWeightComputation:
    """Test AllWeatherStrategy._compute_target_weights()."""

    def test_all_bullish_inverse_vol(self):
        """All assets trend up → inverse-vol weighted, no SHV."""
        strategy = AllWeatherStrategy(AllWeatherConfig())
        signals_data = {
            "trends": {"SPY": True, "TLT": True, "GLD": True, "DBC": True,
                       "TIP": True, "HYG": True, "EEM": True},
            "vols": {"SPY": 0.15, "TLT": 0.12, "GLD": 0.18, "DBC": 0.25,
                     "TIP": 0.08, "HYG": 0.10, "EEM": 0.22},
        }
        weights = strategy._compute_target_weights(signals_data)

        # All weights should be positive
        assert all(w >= 0 for w in weights.values())
        # When all assets active, inverse-vol redistributes original weight sum (1.0)
        assert abs(sum(weights.values()) - 1.0) < 0.01
        # TIP (lowest vol=0.08) should have highest weight among risk assets
        risk_assets = {k: v for k, v in weights.items() if k != "SHV"}
        assert max(risk_assets, key=risk_assets.get) == "TIP"
        # SHV should have minimal weight
        assert weights.get("SHV", 0) < 0.05

    def test_some_bearish_shifts_to_cash(self):
        """Assets with bearish trends shift weight to SHV."""
        strategy = AllWeatherStrategy(AllWeatherConfig())
        signals_data = {
            "trends": {"SPY": True, "TLT": False, "GLD": True, "DBC": False,
                       "TIP": True, "HYG": False, "EEM": False},
            "vols": {"SPY": 0.15, "TLT": 0.12, "GLD": 0.18, "DBC": 0.25,
                     "TIP": 0.08, "HYG": 0.10, "EEM": 0.22},
        }
        weights = strategy._compute_target_weights(signals_data)

        # Bearish assets should not be in weights (or 0)
        for sym in ["TLT", "DBC", "HYG", "EEM"]:
            assert weights.get(sym, 0) == 0

        # SHV should absorb the freed weight
        assert weights["SHV"] > 0.3
        assert abs(sum(weights.values()) - 0.98) < 0.01

    def test_all_bearish_100pct_cash(self):
        """All assets bearish → 100% SHV."""
        strategy = AllWeatherStrategy(AllWeatherConfig())
        signals_data = {
            "trends": {"SPY": False, "TLT": False, "GLD": False, "DBC": False,
                       "TIP": False, "HYG": False, "EEM": False},
            "vols": {"SPY": 0.15, "TLT": 0.12, "GLD": 0.18, "DBC": 0.25,
                     "TIP": 0.08, "HYG": 0.10, "EEM": 0.22},
        }
        weights = strategy._compute_target_weights(signals_data)

        # All risk assets should be 0
        for sym in ["SPY", "TLT", "GLD", "DBC", "TIP", "HYG", "EEM"]:
            assert weights.get(sym, 0) == 0

        # SHV should be ~98%
        assert weights["SHV"] == pytest.approx(0.98, abs=0.01)

    def test_no_trend_filter_holds_all(self):
        """use_trend_filter=False → hold all assets regardless of trend."""
        config = AllWeatherConfig(use_trend_filter=False)
        strategy = AllWeatherStrategy(config)
        signals_data = {
            "trends": {"SPY": False, "TLT": False, "GLD": False, "DBC": False,
                       "TIP": False, "HYG": False, "EEM": False},
            "vols": {"SPY": 0.15, "TLT": 0.12, "GLD": 0.18, "DBC": 0.25,
                     "TIP": 0.08, "HYG": 0.10, "EEM": 0.22},
        }
        weights = strategy._compute_target_weights(signals_data)

        # All risk assets should have positive weight
        for sym in ["SPY", "TLT", "GLD", "DBC", "TIP", "HYG", "EEM"]:
            assert weights.get(sym, 0) > 0

        # SHV minimal
        assert weights.get("SHV", 0) < 0.05

    def test_equal_weight_no_inverse_vol(self):
        """use_inverse_vol=False → uses static weights from config."""
        config = AllWeatherConfig(use_inverse_vol=False)
        strategy = AllWeatherStrategy(config)
        signals_data = {
            "trends": {"SPY": True, "TLT": True, "GLD": True, "DBC": True,
                       "TIP": True, "HYG": True, "EEM": True},
            "vols": {"SPY": 0.15, "TLT": 0.12, "GLD": 0.18, "DBC": 0.25,
                     "TIP": 0.08, "HYG": 0.10, "EEM": 0.22},
        }
        weights = strategy._compute_target_weights(signals_data)

        # Should match static config weights
        assert weights["SPY"] == pytest.approx(0.25, abs=0.01)
        assert weights["TLT"] == pytest.approx(0.25, abs=0.01)
        assert weights["GLD"] == pytest.approx(0.15, abs=0.01)


# ============================================================
# Rebalance signal tests
# ============================================================

class TestRebalanceSignals:
    """Test exit and entry signal generation."""

    def test_initial_entry_signals(self):
        """Day 1 → should generate entry signals for all bullish assets."""
        strategy = AllWeatherStrategy(AllWeatherConfig())
        prices = {"SPY": 500.0, "TLT": 90.0, "GLD": 200.0, "DBC": 22.0,
                  "TIP": 110.0, "HYG": 75.0, "EEM": 40.0, "SHV": 110.0}
        market = _make_market(prices)
        portfolio = _make_portfolio(nlv=1_000_000, cash=1_000_000)
        dp = _make_data_provider()

        signals = strategy.generate_signals(market, portfolio, dp)

        # Should have entry signals (all assets trending up with default mock)
        entry_signals = [s for s in signals if s.type == SignalType.ENTRY]
        assert len(entry_signals) > 0

        # All entry signals should have positive quantity
        for s in entry_signals:
            assert s.target_quantity > 0

        # No exit signals on day 1 (no positions)
        exit_signals = [s for s in signals if s.type == SignalType.EXIT]
        assert len(exit_signals) == 0

    def test_exit_priority_higher_than_entry(self):
        """EXIT signals should have higher priority than ENTRY signals."""
        strategy = AllWeatherStrategy(AllWeatherConfig())

        # Create positions that need rebalancing
        positions = [
            _make_position("SPY", 600, 450.0, 500.0),  # Over-weight
            _make_position("TLT", 100, 85.0, 90.0),    # Under-weight
        ]
        prices = {"SPY": 500.0, "TLT": 90.0, "GLD": 200.0, "DBC": 22.0,
                  "TIP": 110.0, "HYG": 75.0, "EEM": 40.0, "SHV": 110.0}
        market = _make_market(prices)
        portfolio = _make_portfolio(
            nlv=1_000_000,
            cash=100_000,
            positions=positions,
        )
        dp = _make_data_provider()

        signals = strategy.generate_signals(market, portfolio, dp)

        exit_signals = [s for s in signals if s.type == SignalType.EXIT]
        entry_signals = [s for s in signals if s.type == SignalType.ENTRY]

        if exit_signals and entry_signals:
            max_entry_priority = max(s.priority for s in entry_signals)
            min_exit_priority = min(s.priority for s in exit_signals)
            assert min_exit_priority > max_entry_priority

    def test_no_rebalance_between_periods(self):
        """Should not rebalance between monthly periods (without drift)."""
        strategy = AllWeatherStrategy(AllWeatherConfig(rebalance_frequency=21))

        prices = {"SPY": 500.0, "TLT": 90.0, "GLD": 200.0, "DBC": 22.0,
                  "TIP": 110.0, "HYG": 75.0, "EEM": 40.0, "SHV": 110.0}
        market = _make_market(prices)
        dp = _make_data_provider()

        # Day 1: initial rebalance
        portfolio1 = _make_portfolio(nlv=1_000_000, cash=1_000_000)
        signals1 = strategy.generate_signals(market, portfolio1, dp)
        assert len(signals1) > 0  # Should rebalance on day 1

        # Day 2-20: no rebalance
        for _ in range(19):
            portfolio2 = _make_portfolio(nlv=1_000_000, cash=100_000)
            signals2 = strategy.generate_signals(market, portfolio2, dp)
            # Should be empty (no rebalance needed, no drift)
            assert len(signals2) == 0


# ============================================================
# CrossAssetSignalComputer tests
# ============================================================

class TestCrossAssetSignalComputer:
    """Test the cross-asset signal computation."""

    def test_compute_returns_expected_keys(self):
        """Compute result should have trends, vols, sma_values, prices."""
        computer = CrossAssetSignalComputer()
        market = _make_market({"SPY": 500.0, "TLT": 90.0, "SHV": 110.0})
        dp = _make_data_provider()

        result = computer.compute(market, dp)

        assert "trends" in result
        assert "vols" in result
        assert "sma_values" in result
        assert "prices" in result

        # SHV should be excluded (cash equivalent)
        assert "SHV" not in result["trends"]
        assert "SPY" in result["trends"]
        assert "TLT" in result["trends"]

    def test_caching(self):
        """Same date should return cached result."""
        computer = CrossAssetSignalComputer()
        market = _make_market({"SPY": 500.0})
        dp = _make_data_provider()

        result1 = computer.compute(market, dp)
        result2 = computer.compute(market, dp)
        assert result1 is result2  # Same object (cached)

    def test_bearish_trend_below_sma(self):
        """Price below SMA200 should be bearish."""
        # Create declining prices (below SMA)
        declining = [200.0 - i * 0.3 for i in range(300)]
        dp = _make_data_provider(trend_data={"SPY": declining})
        computer = CrossAssetSignalComputer()
        market = _make_market({"SPY": declining[-1]})

        result = computer.compute(market, dp)
        assert result["trends"]["SPY"] is False

    def test_bullish_trend_above_sma(self):
        """Price above SMA200 should be bullish."""
        rising = [100.0 + i * 0.5 for i in range(300)]
        dp = _make_data_provider(trend_data={"SPY": rising})
        computer = CrossAssetSignalComputer()
        market = _make_market({"SPY": rising[-1]})

        result = computer.compute(market, dp)
        assert result["trends"]["SPY"] is True

    def test_volatility_computation(self):
        """Volatility should be a reasonable positive number."""
        computer = CrossAssetSignalComputer()
        market = _make_market({"SPY": 500.0})
        dp = _make_data_provider()

        result = computer.compute(market, dp)
        vol = result["vols"]["SPY"]
        assert vol > 0
        assert vol < 2.0  # Annualized vol should be < 200%


# ============================================================
# Registry tests
# ============================================================

class TestRegistry:
    """Test strategy registry integration."""

    def test_registry_creates_all_weather(self):
        from src.strategy.registry import StrategyRegistry

        strategy = StrategyRegistry.create("all_weather")
        assert strategy.name == "all_weather"

    def test_registry_creates_aw_alias(self):
        from src.strategy.registry import StrategyRegistry

        strategy = StrategyRegistry.create("aw")
        assert strategy.name == "all_weather"

    def test_registry_creates_no_trend_variant(self):
        from src.strategy.registry import StrategyRegistry

        strategy = StrategyRegistry.create("all_weather_no_trend")
        assert strategy.name == "all_weather"
        assert not strategy._config.use_trend_filter

    def test_registry_creates_equal_weight_variant(self):
        from src.strategy.registry import StrategyRegistry

        strategy = StrategyRegistry.create("all_weather_equal")
        assert strategy.name == "all_weather"
        assert not strategy._config.use_inverse_vol
