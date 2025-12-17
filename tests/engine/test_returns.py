"""Tests for return and risk calculations."""

import math

import pytest

from src.engine.strategy import ShortPutStrategy
from src.engine.portfolio.returns import (
    calc_annualized_return,
    calc_calmar_ratio,
    calc_expected_return,
    calc_expected_std,
    calc_max_drawdown,
    calc_sharpe_ratio,
    calc_win_rate,
)
from src.engine.account.position_sizing import calc_kelly, calc_kelly_from_trades


class TestBasicReturns:
    """Tests for basic return calculations."""

    def test_calc_win_rate(self):
        """Test win rate calculation."""
        trades = [100, -50, 200, -30, 150]  # 3 wins, 2 losses
        win_rate = calc_win_rate(trades)
        assert win_rate == 0.6

    def test_calc_win_rate_all_wins(self):
        """Test win rate with all winning trades."""
        trades = [100, 200, 150]
        win_rate = calc_win_rate(trades)
        assert win_rate == 1.0

    def test_calc_win_rate_no_trades(self):
        """Test win rate with empty list."""
        win_rate = calc_win_rate([])
        assert win_rate is None

    def test_calc_expected_return(self):
        """Test expected return calculation."""
        # 60% win rate, $100 avg win, $50 avg loss
        # E[R] = 0.6 * 100 - 0.4 * 50 = 60 - 20 = 40
        expected = calc_expected_return(0.6, 100, 50)
        assert expected == 40.0

    def test_calc_expected_return_negative_edge(self):
        """Test expected return with negative edge."""
        # 40% win rate, $100 avg win, $150 avg loss
        # E[R] = 0.4 * 100 - 0.6 * 150 = 40 - 90 = -50
        expected = calc_expected_return(0.4, 100, 150)
        assert expected == -50.0


class TestRiskMetrics:
    """Tests for risk metrics."""

    def test_calc_sharpe_ratio(self):
        """Test Sharpe ratio calculation."""
        # Positive returns with some volatility
        returns = [0.01, 0.02, -0.005, 0.015, 0.01, -0.01, 0.02, 0.005]
        sharpe = calc_sharpe_ratio(returns)
        assert sharpe is not None
        assert sharpe > 0  # Should be positive with positive mean return

    def test_calc_sharpe_ratio_zero_vol(self):
        """Test Sharpe ratio with zero volatility."""
        returns = [0.01, 0.01, 0.01, 0.01]  # Constant returns
        sharpe = calc_sharpe_ratio(returns)
        assert sharpe == 0.0

    def test_calc_max_drawdown(self):
        """Test max drawdown calculation."""
        equity = [100, 110, 105, 120, 100, 130]
        mdd = calc_max_drawdown(equity)
        # Max DD from 120 to 100 = 20/120 = 0.1667
        assert abs(mdd - 0.1667) < 0.01

    def test_calc_max_drawdown_no_dd(self):
        """Test max drawdown with monotonically increasing equity."""
        equity = [100, 110, 120, 130, 140]
        mdd = calc_max_drawdown(equity)
        assert mdd == 0.0

    def test_calc_calmar_ratio(self):
        """Test Calmar ratio calculation."""
        calmar = calc_calmar_ratio(0.15, 0.10)  # 15% return, 10% max DD
        assert abs(calmar - 1.5) < 0.001


class TestKelly:
    """Tests for Kelly criterion."""

    def test_calc_kelly_positive_edge(self):
        """Test Kelly with positive edge."""
        # 60% win rate, 1.5 win/loss ratio
        # Kelly = 0.6 - 0.4/1.5 = 0.6 - 0.267 = 0.333
        kelly = calc_kelly(0.6, 1.5)
        assert abs(kelly - 0.333) < 0.01

    def test_calc_kelly_no_edge(self):
        """Test Kelly with no edge (returns 0)."""
        # 50% win rate, 1.0 win/loss ratio
        # Kelly = 0.5 - 0.5/1.0 = 0
        kelly = calc_kelly(0.5, 1.0)
        assert kelly == 0.0

    def test_calc_kelly_negative_edge(self):
        """Test Kelly with negative edge."""
        # 40% win rate, 1.0 win/loss ratio -> negative Kelly
        kelly = calc_kelly(0.4, 1.0)
        assert kelly == 0.0  # Should be clamped to 0

    def test_calc_kelly_from_trades(self):
        """Test Kelly calculation from trades."""
        trades = [100, -50, 150, -60, 200, -40]
        kelly = calc_kelly_from_trades(trades)
        assert kelly is not None
        assert kelly > 0  # Should have positive edge


class TestAnnualizedReturn:
    """Tests for annualized return calculation."""

    def test_calc_annualized_return_daily(self):
        """Test annualized return from daily returns."""
        # 0.1% daily for 252 days should be about 28.6% annualized
        daily_returns = [0.001] * 252
        ann_return = calc_annualized_return(daily_returns)
        assert ann_return is not None
        assert 0.25 < ann_return < 0.30

    def test_calc_annualized_return_empty(self):
        """Test annualized return with empty list."""
        ann_return = calc_annualized_return([])
        assert ann_return is None


class TestOptionSharpeRatio:
    """Tests for option-specific Sharpe ratio using Strategy class directly."""

    def test_strategy_sharpe_ratio_basic(self):
        """Test option Sharpe ratio using Strategy class.

        Example: Sell put K=550, C=6.5, S=580, σ=20%, T=30 days, r=3%
        """
        strategy = ShortPutStrategy(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
        )
        sr = strategy.calc_sharpe_ratio(margin_ratio=0.2)
        assert sr is not None
        # Should have positive Sharpe ratio for OTM put
        assert sr > 0

    def test_strategy_metrics(self):
        """Test full metrics calculation via Strategy class."""
        strategy = ShortPutStrategy(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
        )
        metrics = strategy.calc_metrics(margin_ratio=0.2)
        assert metrics.expected_return > 0  # OTM put should have positive expected return
        assert metrics.return_std > 0
        assert metrics.sharpe_ratio is not None
        assert metrics.win_probability > 0.5  # OTM put should have >50% win prob

    def test_strategy_sharpe_ratio_annualized(self):
        """Test annualized option Sharpe ratio.

        SR_annual = SR / sqrt(T)
        """
        strategy = ShortPutStrategy(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
        )
        sr = strategy.calc_sharpe_ratio(margin_ratio=0.2)
        sr_annual = strategy.calc_sharpe_ratio_annualized(margin_ratio=0.2)

        assert sr_annual is not None
        # Annualized should be higher than non-annualized for short time periods
        assert sr_annual > sr

        # Verify the formula: SR_annual = SR / sqrt(T)
        expected_annual = sr / math.sqrt(30 / 365)
        assert abs(sr_annual - expected_annual) < 0.001
