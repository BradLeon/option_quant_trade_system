"""Tests for option pricing implementations."""

import math

import pytest

from src.engine.pricing import (
    CoveredCallPricer,
    LongCallPricer,
    LongPutPricer,
    OptionLeg,
    OptionType,
    PositionSide,
    ShortCallPricer,
    ShortPutPricer,
    ShortStranglePricer,
    PricingMetrics,
    PricingParams,
)


class TestShortPutPricer:
    """Tests for Short Put strategy."""

    def test_init(self):
        """Test strategy initialization."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
        )
        assert strategy.leg.option_type == OptionType.PUT
        assert strategy.leg.side == PositionSide.SHORT
        assert strategy.leg.strike == 550
        assert strategy.leg.premium == 6.5

    def test_calc_expected_return_otm(self):
        """Test expected return for OTM put.

        OTM put (S > K) should have positive expected return.
        """
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        # OTM short put should have positive expected return
        assert e_return > 0
        # Expected return should be less than premium (some probability of loss)
        assert e_return < 6.5

    def test_calc_expected_return_atm(self):
        """Test expected return for ATM put."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=100,
            premium=5.0,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        # ATM short put expected return should be around 0 in fair pricing
        assert -2 < e_return < 5

    def test_calc_return_variance(self):
        """Test return variance calculation."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        variance = strategy.calc_return_variance()
        assert variance >= 0  # Variance must be non-negative

    def test_calc_return_std(self):
        """Test return standard deviation calculation."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        std = strategy.calc_return_std()
        assert std >= 0
        assert std == math.sqrt(strategy.calc_return_variance())

    def test_calc_max_profit(self):
        """Test max profit = premium."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        max_profit = strategy.calc_max_profit()
        assert max_profit == 6.5

    def test_calc_max_loss(self):
        """Test max loss = strike - premium."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        max_loss = strategy.calc_max_loss()
        assert max_loss == 550 - 6.5

    def test_calc_breakeven(self):
        """Test breakeven = strike - premium."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        breakeven = strategy.calc_breakeven()
        assert breakeven == 550 - 6.5

    def test_calc_win_probability_otm(self):
        """Test win probability for OTM put."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        win_prob = strategy.calc_win_probability()
        # OTM put should have > 50% win probability
        assert 0.5 < win_prob < 1.0

    def test_calc_exercise_probability(self):
        """Test exercise probability."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        exercise_prob = strategy.calc_exercise_probability()
        # OTM put should have < 50% exercise probability
        assert 0 < exercise_prob < 0.5

    def test_calc_sharpe_ratio(self):
        """Test Sharpe ratio calculation."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        sharpe = strategy.calc_sharpe_ratio()
        assert sharpe is not None

    def test_calc_kelly_fraction(self):
        """Test Kelly fraction calculation."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        kelly = strategy.calc_kelly_fraction()
        assert kelly >= 0

    def test_calc_metrics(self):
        """Test full metrics calculation."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        metrics = strategy.calc_metrics()
        assert isinstance(metrics, PricingMetrics)
        assert metrics.expected_return > 0
        assert metrics.return_std > 0
        assert metrics.max_profit == 6.5
        assert metrics.max_loss == 550 - 6.5
        assert metrics.breakeven == 550 - 6.5
        assert 0 < metrics.win_probability < 1


class TestCoveredCallPricer:
    """Tests for Covered Call strategy."""

    def test_init(self):
        """Test strategy initialization."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
        )
        assert strategy.leg.option_type == OptionType.CALL
        assert strategy.leg.side == PositionSide.SHORT
        assert strategy.leg.strike == 105

    def test_calc_expected_return(self):
        """Test expected return calculation."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
        )
        e_return = strategy.calc_expected_return()
        # Covered call has capped upside, expected return should be reasonable
        assert e_return is not None

    def test_calc_max_profit(self):
        """Test max profit = (strike - cost) + premium."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
            stock_cost_basis=100,
        )
        max_profit = strategy.calc_max_profit()
        # Max profit = (105 - 100) + 3 = 8
        assert max_profit == 8.0

    def test_calc_max_loss(self):
        """Test max loss = stock cost - premium."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
            stock_cost_basis=100,
        )
        max_loss = strategy.calc_max_loss()
        # Max loss = 100 - 3 = 97
        assert max_loss == 97.0

    def test_calc_breakeven(self):
        """Test breakeven = stock cost - premium."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
            stock_cost_basis=100,
        )
        breakeven = strategy.calc_breakeven()
        assert breakeven == 97.0

    def test_calc_assignment_probability(self):
        """Test assignment probability."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
        )
        assign_prob = strategy.calc_assignment_probability()
        # OTM call should have < 50% assignment probability
        assert 0 < assign_prob < 0.5

    def test_calc_win_probability(self):
        """Test win probability."""
        strategy = CoveredCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=45 / 365,
            stock_cost_basis=100,
        )
        win_prob = strategy.calc_win_probability()
        # Breakeven is 97, should have > 50% win probability
        assert 0.5 < win_prob < 1.0


class TestShortStranglePricer:
    """Tests for Short Strangle strategy."""

    def test_init(self):
        """Test strategy initialization."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.put_leg.option_type == OptionType.PUT
        assert strategy.call_leg.option_type == OptionType.CALL
        assert strategy.put_leg.strike == 95
        assert strategy.call_leg.strike == 105

    def test_total_premium(self):
        """Test total premium calculation."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.total_premium == 4.5

    def test_calc_expected_return(self):
        """Test expected return for short strangle."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        # Should be sum of put and call expected returns
        assert e_return is not None

    def test_calc_max_profit(self):
        """Test max profit = total premium."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        max_profit = strategy.calc_max_profit()
        assert max_profit == 4.5

    def test_calc_max_loss(self):
        """Test max loss on downside."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        max_loss = strategy.calc_max_loss()
        # Max loss = put strike - total premium = 95 - 4.5 = 90.5
        assert max_loss == 90.5

    def test_calc_breakeven(self):
        """Test two breakeven points."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        breakevens = strategy.calc_breakeven()
        assert len(breakevens) == 2
        # Lower BE = put strike - total premium = 95 - 4.5 = 90.5
        assert breakevens[0] == 90.5
        # Upper BE = call strike + total premium = 105 + 4.5 = 109.5
        assert breakevens[1] == 109.5

    def test_calc_win_probability(self):
        """Test win probability (between breakevens)."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        win_prob = strategy.calc_win_probability()
        # With wide breakeven range, should have decent win probability
        assert 0.3 < win_prob < 0.9

    def test_calc_exercise_probabilities(self):
        """Test individual exercise probabilities."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        put_prob = strategy.calc_put_exercise_probability()
        call_prob = strategy.calc_call_exercise_probability()

        # Both legs are OTM, so both probabilities should be < 50%
        assert 0 < put_prob < 0.5
        assert 0 < call_prob < 0.5

    def test_different_volatilities(self):
        """Test with different volatilities for each leg."""
        strategy = ShortStranglePricer(
            spot_price=100,
            put_strike=95,
            call_strike=105,
            put_premium=2.0,
            call_premium=2.5,
            volatility=0.25,
            time_to_expiry=30 / 365,
            put_volatility=0.28,  # Put skew
            call_volatility=0.22,  # Call skew
        )
        # Should still calculate without errors
        e_return = strategy.calc_expected_return()
        assert e_return is not None


class TestStrategyBase:
    """Tests for strategy base class functionality."""

    def test_leg_property(self):
        """Test leg property returns first leg."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=95,
            premium=3.0,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        assert strategy.leg == strategy.legs[0]

    def test_get_leg_volatility_with_leg_vol(self):
        """Test get_leg_volatility with leg-specific volatility."""
        leg = OptionLeg(
            option_type=OptionType.PUT,
            side=PositionSide.SHORT,
            strike=95,
            premium=3.0,
            volatility=0.25,
        )
        params = PricingParams(
            spot_price=100,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )

        class TestStrategy(ShortPutPricer):
            pass

        strategy = TestStrategy(
            spot_price=100,
            strike_price=95,
            premium=3.0,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        strategy.legs[0].volatility = 0.25

        vol = strategy.get_leg_volatility(strategy.legs[0])
        assert vol == 0.25

    def test_get_leg_volatility_fallback(self):
        """Test get_leg_volatility falls back to strategy volatility."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=95,
            premium=3.0,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        vol = strategy.get_leg_volatility(strategy.legs[0])
        assert vol == 0.20

    def test_sharpe_ratio_annualized(self):
        """Test annualized Sharpe ratio."""
        strategy = ShortPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        sr = strategy.calc_sharpe_ratio()
        sr_annual = strategy.calc_sharpe_ratio_annual()

        if sr is not None and sr_annual is not None:
            # Annualized should scale by 1/sqrt(T)
            expected_annual = sr / math.sqrt(30 / 365)
            assert abs(sr_annual - expected_annual) < 0.001

    def test_calc_metrics_extended(self):
        """Test extended metrics with PREI, SAS, TGR, ROC."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=95,
            premium=2.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
            hv=0.20,
            dte=30,
            gamma=0.02,
            vega=0.15,
            theta=-0.03,
        )
        metrics = strategy.calc_metrics()

        # Verify new fields exist and are not None
        assert metrics.prei is not None
        assert metrics.sas is not None
        assert metrics.tgr is not None
        assert metrics.roc is not None

        # PREI should be in 0-100 range
        assert 0 <= metrics.prei <= 100
        # SAS should be in 0-100 range
        assert 0 <= metrics.sas <= 100
        # TGR should be positive
        assert metrics.tgr > 0

    def test_calc_metrics_extended_without_optional_params(self):
        """Test extended metrics are None when optional params not provided."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=95,
            premium=2.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        # Call without Greeks - should still work
        metrics = strategy.calc_metrics()

        # Core metrics should exist
        assert metrics.expected_return is not None
        assert metrics.sharpe_ratio is not None

        # Extended metrics should be None (not enough data)
        assert metrics.prei is None
        assert metrics.sas is None
        assert metrics.tgr is None
        assert metrics.roc is None

    def test_calc_metrics_partial_extended(self):
        """Test partial extended metrics when some data provided."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=95,
            premium=2.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
            gamma=0.02,
            theta=-0.03,
            dte=30,
        )
        metrics = strategy.calc_metrics()

        # TGR should work (has gamma and theta)
        assert metrics.tgr is not None
        assert metrics.tgr > 0

        # ROC should work (has dte)
        assert metrics.roc is not None

        # PREI should be None (missing vega)
        assert metrics.prei is None
        # SAS should be None (missing hv)
        assert metrics.sas is None

    def test_calc_individual_extended_methods(self):
        """Test individual calc_prei, calc_sas, calc_tgr, calc_roc methods."""
        strategy = ShortPutPricer(
            spot_price=100,
            strike_price=95,
            premium=2.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
            hv=0.20,
            dte=30,
            gamma=0.02,
            vega=0.15,
            theta=-0.03,
        )

        # Test individual methods
        prei = strategy.calc_prei()
        assert prei is not None
        assert 0 <= prei <= 100

        sas = strategy.calc_sas()
        assert sas is not None
        assert 0 <= sas <= 100

        tgr = strategy.calc_tgr()
        assert tgr is not None
        assert tgr > 0

        roc = strategy.calc_roc()
        assert roc is not None


class TestPositionLevelTGR:
    """Tests for position-level calc_tgr function."""

    def test_calc_tgr_basic(self):
        """Test basic TGR calculation."""
        from src.data.models.option import Greeks
        from src.engine.models.position import Position
        from src.engine.position.risk_return import calc_tgr

        pos = Position(symbol="TEST", quantity=1, greeks=Greeks(theta=-0.05, gamma=0.01))
        tgr = calc_tgr(pos)
        assert tgr == 5.0

    def test_calc_tgr_negative_theta(self):
        """Test TGR with negative theta (typical for short options)."""
        from src.data.models.option import Greeks
        from src.engine.models.position import Position
        from src.engine.position.risk_return import calc_tgr

        pos = Position(symbol="TEST", quantity=1, greeks=Greeks(theta=-50, gamma=10))
        tgr = calc_tgr(pos)
        assert tgr == 5.0

    def test_calc_tgr_zero_gamma(self):
        """Test TGR returns None when gamma is zero."""
        from src.data.models.option import Greeks
        from src.engine.models.position import Position
        from src.engine.position.risk_return import calc_tgr

        pos = Position(symbol="TEST", quantity=1, greeks=Greeks(theta=-0.05, gamma=0))
        tgr = calc_tgr(pos)
        assert tgr is None

    def test_calc_tgr_none_inputs(self):
        """Test TGR returns None for None inputs."""
        from src.data.models.option import Greeks
        from src.engine.models.position import Position
        from src.engine.position.risk_return import calc_tgr

        pos1 = Position(symbol="TEST", quantity=1, greeks=Greeks(gamma=0.01))  # no theta
        pos2 = Position(symbol="TEST", quantity=1, greeks=Greeks(theta=-0.05))  # no gamma

        assert calc_tgr(pos1) is None
        assert calc_tgr(pos2) is None


class TestLongPutPricer:
    """Tests for Long Put strategy."""

    def test_init(self):
        """Test strategy initialization."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        assert strategy.leg.option_type == OptionType.PUT
        assert strategy.leg.side == PositionSide.LONG
        assert strategy.leg.strike == 550
        assert strategy.leg.premium == 6.5

    def test_expected_return_otm(self):
        """OTM long put (S > K) should have negative expected return."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        # OTM long put: paying premium with low probability of profit
        assert e_return < 0

    def test_expected_return_mirror(self):
        """E[Long Put] + E[Short Put] ≈ 0 (exact mirror)."""
        params = dict(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
        )
        long_put = LongPutPricer(**params)
        short_put = ShortPutPricer(**params)

        e_long = long_put.calc_expected_return()
        e_short = short_put.calc_expected_return()

        assert abs(e_long + e_short) < 1e-10, (
            f"Mirror violation: E[Long]={e_long}, E[Short]={e_short}, sum={e_long + e_short}"
        )

    def test_variance_mirror(self):
        """Var[Long Put] ≈ Var[Short Put] (variance unchanged by negation)."""
        params = dict(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        long_put = LongPutPricer(**params)
        short_put = ShortPutPricer(**params)

        var_long = long_put.calc_return_variance()
        var_short = short_put.calc_return_variance()

        assert abs(var_long - var_short) < 1e-6, (
            f"Variance mismatch: Long={var_long}, Short={var_short}"
        )

    def test_max_profit(self):
        """Max profit = K - C."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        assert strategy.calc_max_profit() == 550 - 6.5

    def test_max_loss(self):
        """Max loss = premium paid."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        assert strategy.calc_max_loss() == 6.5

    def test_breakeven(self):
        """Breakeven = K - C."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        assert strategy.calc_breakeven() == 550 - 6.5

    def test_win_probability(self):
        """OTM long put should have < 50% win probability."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        win_prob = strategy.calc_win_probability()
        assert 0 < win_prob < 0.5

    def test_seller_metrics_none(self):
        """Seller-specific metrics should return None for buyers."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            hv=0.18,
            dte=30,
            gamma=0.02,
            theta=-0.03,
            vega=0.15,
        )
        assert strategy.calc_tgr() is None
        assert strategy.calc_sas() is None
        assert strategy.calc_premium_rate() is None
        assert strategy.calc_theta_margin_ratio() is None

    def test_effective_margin_is_premium(self):
        """Effective margin for long options = premium paid."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
        )
        assert strategy.get_effective_margin() == 6.5

    def test_calc_metrics(self):
        """Test full metrics calculation."""
        strategy = LongPutPricer(
            spot_price=580,
            strike_price=550,
            premium=6.5,
            volatility=0.20,
            time_to_expiry=30 / 365,
            dte=30,
        )
        metrics = strategy.calc_metrics()
        assert isinstance(metrics, PricingMetrics)
        assert metrics.expected_return < 0  # OTM long put
        assert metrics.return_std > 0
        assert metrics.max_profit == 550 - 6.5
        assert metrics.max_loss == 6.5
        assert metrics.breakeven == 550 - 6.5
        assert 0 < metrics.win_probability < 1
        # Seller metrics should be None
        assert metrics.tgr is None
        assert metrics.sas is None
        assert metrics.premium_rate is None
        assert metrics.theta_margin_ratio is None


class TestLongCallPricer:
    """Tests for Long Call strategy."""

    def test_init(self):
        """Test strategy initialization."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.leg.option_type == OptionType.CALL
        assert strategy.leg.side == PositionSide.LONG
        assert strategy.leg.strike == 105
        assert strategy.leg.premium == 3.0

    def test_expected_return_otm(self):
        """OTM long call (S < K) should have negative expected return."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        e_return = strategy.calc_expected_return()
        assert e_return < 0

    def test_expected_return_mirror(self):
        """E[Long Call] + E[Short Call] ≈ 0 (exact mirror)."""
        params = dict(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
            risk_free_rate=0.03,
        )
        long_call = LongCallPricer(**params)
        short_call = ShortCallPricer(**params)

        e_long = long_call.calc_expected_return()
        e_short = short_call.calc_expected_return()

        assert abs(e_long + e_short) < 1e-10, (
            f"Mirror violation: E[Long]={e_long}, E[Short]={e_short}, sum={e_long + e_short}"
        )

    def test_variance_mirror(self):
        """Var[Long Call] ≈ Var[Short Call] (variance unchanged by negation)."""
        params = dict(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        long_call = LongCallPricer(**params)
        short_call = ShortCallPricer(**params)

        var_long = long_call.calc_return_variance()
        var_short = short_call.calc_return_variance()

        assert abs(var_long - var_short) < 1e-6, (
            f"Variance mismatch: Long={var_long}, Short={var_short}"
        )

    def test_max_profit(self):
        """Max profit = 10 * K (unlimited, practical bound)."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.calc_max_profit() == 10 * 105

    def test_max_loss(self):
        """Max loss = premium paid."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.calc_max_loss() == 3.0

    def test_breakeven(self):
        """Breakeven = K + C."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.calc_breakeven() == 105 + 3.0

    def test_win_probability(self):
        """OTM long call should have < 50% win probability."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        win_prob = strategy.calc_win_probability()
        assert 0 < win_prob < 0.5

    def test_seller_metrics_none(self):
        """Seller-specific metrics should return None for buyers."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
            hv=0.20,
            dte=30,
            gamma=0.02,
            theta=-0.03,
            vega=0.15,
        )
        assert strategy.calc_tgr() is None
        assert strategy.calc_sas() is None
        assert strategy.calc_premium_rate() is None
        assert strategy.calc_theta_margin_ratio() is None

    def test_effective_margin_is_premium(self):
        """Effective margin for long options = premium paid."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
        )
        assert strategy.get_effective_margin() == 3.0

    def test_calc_metrics(self):
        """Test full metrics calculation."""
        strategy = LongCallPricer(
            spot_price=100,
            strike_price=105,
            premium=3.0,
            volatility=0.25,
            time_to_expiry=30 / 365,
            dte=30,
        )
        metrics = strategy.calc_metrics()
        assert isinstance(metrics, PricingMetrics)
        assert metrics.expected_return < 0  # OTM long call
        assert metrics.return_std > 0
        assert metrics.max_profit == 10 * 105
        assert metrics.max_loss == 3.0
        assert metrics.breakeven == 105 + 3.0
        assert 0 < metrics.win_probability < 1
        # Seller metrics should be None
        assert metrics.tgr is None
        assert metrics.sas is None
        assert metrics.premium_rate is None
        assert metrics.theta_margin_ratio is None
