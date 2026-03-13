"""Risk Rules Validation — 验证每条风控规则被触发时能正确阻断操作。

三层风控 + 紧急检查:
- Layer 1: AccountRiskGuard (Signal-Level) — max_positions, margin_util, cash_reserve, available_margin
- Layer 2: RiskChecker (Order-Level) — account_type, price_deviation, margin_projection, order_value
- Layer 3: DailyTradeTracker (Daily Limits) — open/close/roll qty, per-underlying value, total value

每条规则都有对应的 pass/block 测试。
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backtest.strategy.risk.account_risk import AccountRiskGuard, AccountRiskConfig
from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.daily_limits import DailyLimitsConfig, DailyTradeTracker, DailyStats
from src.business.trading.models.decision import AccountState
from src.business.trading.models.order import (
    AssetClass,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskCheckResult,
)
from src.business.trading.order.risk_checker import RiskChecker
from src.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
    Signal,
    SignalType,
)


# ============================================================
# Fixtures / Helpers
# ============================================================


def _make_portfolio(
    nlv: float = 100_000,
    cash: float = 50_000,
    margin_used: float = 20_000,
    positions: list[PositionView] | None = None,
) -> PortfolioState:
    return PortfolioState(
        date=date(2026, 3, 13),
        nlv=nlv,
        cash=cash,
        margin_used=margin_used,
        positions=positions or [],
    )


def _make_market(prices: dict[str, float] | None = None) -> MarketSnapshot:
    return MarketSnapshot(
        date=date(2026, 3, 13),
        prices=prices or {"SPY": 500.0},
    )


def _make_entry_signal(
    underlying: str = "SPY",
    instrument_type: InstrumentType = InstrumentType.OPTION,
    right: OptionRight = OptionRight.PUT,
    strike: float = 480.0,
    quantity: int = -1,
) -> Signal:
    return Signal(
        type=SignalType.ENTRY,
        instrument=Instrument(
            type=instrument_type,
            underlying=underlying,
            right=right if instrument_type == InstrumentType.OPTION else None,
            strike=strike if instrument_type == InstrumentType.OPTION else None,
            expiry=date(2026, 4, 17) if instrument_type == InstrumentType.OPTION else None,
        ),
        target_quantity=quantity,
        reason="test entry",
    )


def _make_exit_signal(underlying: str = "SPY") -> Signal:
    return Signal(
        type=SignalType.EXIT,
        instrument=Instrument(InstrumentType.OPTION, underlying, OptionRight.PUT, 480.0, date(2026, 4, 17)),
        target_quantity=1,
        reason="test exit",
        position_id="pos_1",
    )


def _make_position(underlying: str = "SPY", instrument_type: InstrumentType = InstrumentType.OPTION) -> PositionView:
    return PositionView(
        position_id=f"pos_{uuid.uuid4().hex[:6]}",
        instrument=Instrument(
            type=instrument_type,
            underlying=underlying,
            right=OptionRight.PUT if instrument_type == InstrumentType.OPTION else None,
            strike=480.0 if instrument_type == InstrumentType.OPTION else None,
            expiry=date(2026, 4, 17) if instrument_type == InstrumentType.OPTION else None,
            lot_size=100 if instrument_type == InstrumentType.OPTION else 1,
        ),
        quantity=-1,
        entry_price=3.50,
        entry_date=date(2026, 3, 1),
        current_price=2.00,
        underlying_price=500.0,
        unrealized_pnl=150.0,
        lot_size=100 if instrument_type == InstrumentType.OPTION else 1,
    )


def _make_order(
    side: OrderSide = OrderSide.SELL,
    quantity: int = 1,
    limit_price: float = 3.50,
    strike: float = 480.0,
    asset_class: AssetClass = AssetClass.OPTION,
    account_type: str = "paper",
) -> OrderRequest:
    return OrderRequest(
        order_id=f"ord_{uuid.uuid4().hex[:6]}",
        decision_id="dec_001",
        symbol="SPY_260417_P_480",
        asset_class=asset_class,
        underlying="SPY",
        option_type="put" if asset_class == AssetClass.OPTION else None,
        strike=strike if asset_class == AssetClass.OPTION else None,
        expiry="20260417" if asset_class == AssetClass.OPTION else None,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        contract_multiplier=100 if asset_class == AssetClass.OPTION else 1,
        account_type=account_type,
        broker="ibkr",
    )


def _make_account_state(
    total_equity: float = 100_000,
    used_margin: float = 20_000,
    cash_balance: float = 50_000,
) -> AccountState:
    nlv = total_equity
    margin_util = used_margin / nlv if nlv > 0 else 0
    cash_ratio = cash_balance / nlv if nlv > 0 else 0
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=nlv,
        cash_balance=cash_balance,
        available_margin=nlv - used_margin,
        used_margin=used_margin,
        margin_utilization=margin_util,
        cash_ratio=cash_ratio,
        gross_leverage=1.0,
        total_position_count=5,
    )


# ============================================================
# Layer 1: AccountRiskGuard
# ============================================================


class TestAccountRiskGuard:
    """Signal-level risk guard tests."""

    def _guard(self, **overrides) -> AccountRiskGuard:
        cfg = AccountRiskConfig(
            max_positions=5,
            max_margin_utilization=0.70,
            min_cash_reserve_pct=0.10,
            min_available_margin=10_000,
        )
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return AccountRiskGuard(cfg)

    # -- EXIT always passes --

    def test_exit_always_passes(self):
        """EXIT signals should never be blocked, even at max limits."""
        guard = self._guard(max_positions=0, max_margin_utilization=0.0)
        portfolio = _make_portfolio(nlv=100_000, margin_used=100_000, positions=[_make_position()] * 10)
        signals = [_make_exit_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1
        assert result[0].type == SignalType.EXIT

    # -- Rule: max_positions --

    def test_max_positions_pass(self):
        """ENTRY allowed when position_count < max_positions."""
        guard = self._guard(max_positions=5)
        positions = [_make_position() for _ in range(4)]
        portfolio = _make_portfolio(positions=positions)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1

    def test_max_positions_block(self):
        """ENTRY blocked when position_count >= max_positions."""
        guard = self._guard(max_positions=5)
        positions = [_make_position() for _ in range(5)]
        portfolio = _make_portfolio(positions=positions)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 0

    def test_max_positions_multi_entry_partial_block(self):
        """Multiple entries: only the first N that fit are approved."""
        guard = self._guard(max_positions=3)
        positions = [_make_position() for _ in range(2)]  # 2 existing
        portfolio = _make_portfolio(positions=positions)
        signals = [_make_entry_signal(underlying=f"SYM{i}") for i in range(3)]  # request 3
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1  # only 1 fits (2+1=3)

    # -- Rule: max_margin_utilization --

    def test_margin_utilization_pass(self):
        """ENTRY allowed when margin_used/nlv < max."""
        guard = self._guard(max_margin_utilization=0.70)
        portfolio = _make_portfolio(nlv=100_000, margin_used=60_000)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1

    def test_margin_utilization_block(self):
        """ENTRY blocked when margin_used/nlv >= max."""
        guard = self._guard(max_margin_utilization=0.70)
        portfolio = _make_portfolio(nlv=100_000, margin_used=70_000)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 0

    # -- Rule: min_available_margin (Option entries) --

    def test_available_margin_option_pass(self):
        """Option ENTRY allowed when available margin > min_available_margin."""
        guard = self._guard(max_margin_utilization=0.70, min_available_margin=10_000)
        # available = NLV*0.70 - margin_used = 70k - 40k = 30k > 10k
        portfolio = _make_portfolio(nlv=100_000, margin_used=40_000)
        signals = [_make_entry_signal(instrument_type=InstrumentType.OPTION)]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1

    def test_available_margin_option_block(self):
        """Option ENTRY blocked when available margin < min_available_margin."""
        guard = self._guard(max_margin_utilization=0.70, min_available_margin=10_000)
        # available = NLV*0.70 - margin_used = 70k - 65k = 5k < 10k
        portfolio = _make_portfolio(nlv=100_000, margin_used=65_000)
        signals = [_make_entry_signal(instrument_type=InstrumentType.OPTION)]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 0

    # -- Rule: min_cash_reserve_pct (Stock entries) --

    def test_cash_reserve_stock_pass(self):
        """Stock ENTRY allowed when cash/nlv >= min_cash_reserve_pct."""
        guard = self._guard(min_cash_reserve_pct=0.10)
        portfolio = _make_portfolio(nlv=100_000, cash=15_000, margin_used=10_000)
        signals = [_make_entry_signal(instrument_type=InstrumentType.STOCK, quantity=10)]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1

    def test_cash_reserve_stock_block(self):
        """Stock ENTRY blocked when cash/nlv < min_cash_reserve_pct."""
        guard = self._guard(min_cash_reserve_pct=0.10)
        portfolio = _make_portfolio(nlv=100_000, cash=5_000, margin_used=10_000)
        signals = [_make_entry_signal(instrument_type=InstrumentType.STOCK, quantity=10)]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 0

    # -- Rule: accepts RiskConfig (duck-typing) --

    def test_accepts_risk_config(self):
        """AccountRiskGuard works with RiskConfig (not just AccountRiskConfig)."""
        rc = RiskConfig(max_positions=2, max_margin_utilization=0.50)
        guard = AccountRiskGuard(rc)
        portfolio = _make_portfolio(nlv=100_000, margin_used=60_000, positions=[_make_position()])
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        # margin_used/nlv = 0.60 >= 0.50 → blocked
        assert len(result) == 0


# ============================================================
# Layer 2: RiskChecker
# ============================================================


class TestRiskChecker:
    """Order-level risk checker tests."""

    def _checker(self, **overrides) -> RiskChecker:
        cfg = RiskConfig(
            max_projected_margin_utilization=0.80,
            max_price_deviation_pct=0.05,
            max_order_value_pct=0.10,
            margin_rate_stock_option=0.20,
        )
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return RiskChecker(cfg)

    # -- Rule: account_type must be "paper" --

    def test_account_type_paper_pass(self):
        """Paper account orders pass account_type check."""
        checker = self._checker()
        order = _make_order(account_type="paper")
        result = checker.check(order, _make_account_state())
        account_check = next(c for c in result.checks if c["name"] == "account_type")
        assert account_check["passed"] is True

    def test_account_type_live_block(self):
        """Live account orders are BLOCKED — critical safety."""
        checker = self._checker()
        order = _make_order(account_type="live")
        result = checker.check(order, _make_account_state())
        assert result.passed is False
        assert any("account_type" in c["name"] for c in result.checks if not c["passed"])

    # -- Rule: price_deviation --

    def test_price_deviation_pass(self):
        """Order within price deviation limit passes."""
        checker = self._checker(max_price_deviation_pct=0.05)
        order = _make_order(limit_price=3.50)
        result = checker.check(order, _make_account_state(), current_mid_price=3.45)
        price_check = [c for c in result.checks if c["name"] == "price_deviation"]
        assert len(price_check) == 1
        assert price_check[0]["passed"] is True

    def test_price_deviation_block(self):
        """Order exceeding price deviation limit is blocked."""
        checker = self._checker(max_price_deviation_pct=0.05)
        order = _make_order(limit_price=3.50)
        # mid=3.00 → deviation = |3.50-3.00|/3.00 = 16.7% > 5%
        result = checker.check(order, _make_account_state(), current_mid_price=3.00)
        assert result.passed is False
        assert any("price_deviation" in fc for fc in result.failed_checks)

    # -- Rule: margin_projection (short options) --

    def test_margin_projection_short_pass(self):
        """Short option within projected margin limit passes."""
        checker = self._checker(max_projected_margin_utilization=0.80)
        order = _make_order(side=OrderSide.SELL, quantity=1, strike=480.0)
        # margin = 480 * 100 * 1 * 0.20 = $9,600
        # current_margin = 20k, projected = 29.6k, NLV = 100k → 29.6% < 80%
        acct = _make_account_state(total_equity=100_000, used_margin=20_000)
        result = checker.check(order, acct)
        margin_check = next(c for c in result.checks if c["name"] == "margin_projection")
        assert margin_check["passed"] is True

    def test_margin_projection_short_block(self):
        """Short option exceeding projected margin limit is blocked."""
        checker = self._checker(max_projected_margin_utilization=0.80)
        order = _make_order(side=OrderSide.SELL, quantity=10, strike=480.0)
        # margin = 480 * 100 * 10 * 0.20 = $96,000
        # current = 20k, projected = 116k, NLV = 100k → 116% > 80%
        acct = _make_account_state(total_equity=100_000, used_margin=20_000)
        result = checker.check(order, acct)
        assert result.passed is False
        assert any("margin_projection" in fc for fc in result.failed_checks)

    def test_margin_projection_long_skip(self):
        """Long option (BUY) skips margin check — premium only."""
        checker = self._checker(max_projected_margin_utilization=0.01)  # absurdly low
        order = _make_order(side=OrderSide.BUY, quantity=1, strike=480.0)
        acct = _make_account_state(total_equity=100_000, used_margin=95_000)
        result = checker.check(order, acct)
        margin_check = next(c for c in result.checks if c["name"] == "margin_projection")
        assert margin_check["passed"] is True  # Long option always passes margin

    # -- Rule: order_value --

    def test_order_value_pass(self):
        """Order within value limit passes."""
        checker = self._checker(max_order_value_pct=0.10)
        # value = 3.50 * 1 * 100 = $350, NLV = 100k → 0.35% < 10%
        order = _make_order(limit_price=3.50, quantity=1)
        result = checker.check(order, _make_account_state(total_equity=100_000))
        value_check = next(c for c in result.checks if c["name"] == "order_value")
        assert value_check["passed"] is True

    def test_order_value_block(self):
        """Order exceeding value limit is blocked."""
        checker = self._checker(max_order_value_pct=0.10)
        # value = 3.50 * 50 * 100 = $17,500, NLV = 100k → 17.5% > 10%
        order = _make_order(limit_price=3.50, quantity=50)
        result = checker.check(order, _make_account_state(total_equity=100_000))
        assert result.passed is False
        assert any("order_value" in fc for fc in result.failed_checks)

    # -- Rule: no account_state → fail --

    def test_no_account_state_block(self):
        """Missing account state blocks margin/value checks."""
        checker = self._checker()
        order = _make_order()
        result = checker.check(order, account_state=None)
        assert result.passed is False
        assert any("account_state_required" in fc for fc in result.failed_checks)


# ============================================================
# Layer 3: DailyTradeTracker
# ============================================================


class TestDailyTradeTracker:
    """Daily limits tests with mocked OrderStore."""

    def _make_tracker(
        self,
        existing_stats: DailyStats | None = None,
        total_daily_value: float = 0.0,
        **config_overrides,
    ) -> DailyTradeTracker:
        """Create tracker with mocked store."""
        config = DailyLimitsConfig(
            enabled=True,
            max_open_quantity_per_underlying=5,
            max_close_quantity_per_underlying=5,
            max_roll_quantity_per_underlying=5,
            max_value_pct_per_underlying=10.0,
            max_total_value_pct=25.0,
        )
        for k, v in config_overrides.items():
            setattr(config, k, v)

        store = MagicMock()

        # Mock get_daily_orders_by_underlying to return empty (stats computed from cache)
        store.get_daily_orders_by_underlying.return_value = []
        store.get_recent.return_value = []

        tracker = DailyTradeTracker(order_store=store, config=config)

        # Inject pre-computed stats into cache
        if existing_stats:
            today = date.today()
            cache_key = f"{existing_stats.underlying}:{today.isoformat()}"
            tracker._cache[cache_key] = existing_stats
            tracker._cache_date = today

        # Override total daily value
        tracker.get_total_daily_value = MagicMock(return_value=total_daily_value)

        return tracker

    def _stats(
        self,
        underlying: str = "SPY",
        open_qty: int = 0,
        close_qty: int = 0,
        roll_qty: int = 0,
        total_value: float = 0.0,
    ) -> DailyStats:
        return DailyStats(
            underlying=underlying,
            date=date.today(),
            total_quantity=open_qty + close_qty + roll_qty,
            total_value=total_value,
            order_count=0,
            open_quantity=open_qty,
            close_quantity=close_qty,
            roll_quantity=roll_qty,
        )

    # -- Disabled --

    def test_disabled_always_pass(self):
        """When disabled, all limits are skipped."""
        tracker = self._make_tracker(enabled=False)
        allowed, reason = tracker.check_limits("SPY", 100, 999_999.0, nlv=100_000, decision_type="open")
        assert allowed is True

    # -- Rule: max_open_qty_per_underlying --

    def test_open_qty_pass(self):
        """Open quantity within limit passes."""
        tracker = self._make_tracker(
            existing_stats=self._stats(open_qty=3),
        )
        allowed, reason = tracker.check_limits("SPY", 2, 1000.0, nlv=100_000, decision_type="open")
        assert allowed is True  # 3+2=5 <= 5

    def test_open_qty_block(self):
        """Open quantity exceeding limit is blocked."""
        tracker = self._make_tracker(
            existing_stats=self._stats(open_qty=4),
        )
        allowed, reason = tracker.check_limits("SPY", 2, 1000.0, nlv=100_000, decision_type="open")
        assert allowed is False  # 4+2=6 > 5
        assert "OPEN" in reason

    # -- Rule: max_close_qty_per_underlying --

    def test_close_qty_pass(self):
        tracker = self._make_tracker(
            existing_stats=self._stats(close_qty=3),
        )
        allowed, _ = tracker.check_limits("SPY", 2, 1000.0, nlv=100_000, decision_type="close")
        assert allowed is True

    def test_close_qty_block(self):
        tracker = self._make_tracker(
            existing_stats=self._stats(close_qty=5),
        )
        allowed, reason = tracker.check_limits("SPY", 1, 1000.0, nlv=100_000, decision_type="close")
        assert allowed is False
        assert "CLOSE" in reason

    # -- Rule: max_roll_qty_per_underlying (roll_count = qty * 2) --

    def test_roll_qty_pass(self):
        tracker = self._make_tracker(
            existing_stats=self._stats(roll_qty=2),
        )
        # qty=1 → roll_count=2, new_total=2+2=4 <= 5
        allowed, _ = tracker.check_limits("SPY", 1, 1000.0, nlv=100_000, decision_type="roll")
        assert allowed is True

    def test_roll_qty_block(self):
        tracker = self._make_tracker(
            existing_stats=self._stats(roll_qty=4),
        )
        # qty=1 → roll_count=2, new_total=4+2=6 > 5
        allowed, reason = tracker.check_limits("SPY", 1, 1000.0, nlv=100_000, decision_type="roll")
        assert allowed is False
        assert "ROLL" in reason

    # -- Rule: max_value_pct_per_underlying --

    def test_per_underlying_value_pass(self):
        """Per-underlying daily value within limit."""
        tracker = self._make_tracker(
            existing_stats=self._stats(total_value=5_000),  # 5% of 100k
        )
        # new_value=4000 → total=9000 → 9% <= 10%
        allowed, _ = tracker.check_limits("SPY", 1, 4_000.0, nlv=100_000, decision_type="open")
        assert allowed is True

    def test_per_underlying_value_block(self):
        """Per-underlying daily value exceeding limit."""
        tracker = self._make_tracker(
            existing_stats=self._stats(total_value=8_000),  # 8% of 100k
        )
        # new_value=3000 → total=11000 → 11% > 10%
        allowed, reason = tracker.check_limits("SPY", 1, 3_000.0, nlv=100_000, decision_type="open")
        assert allowed is False
        assert "市值限额" in reason

    # -- Rule: max_total_value_pct (cross-underlying) --

    def test_total_daily_value_pass(self):
        """Cross-underlying total daily value within limit."""
        tracker = self._make_tracker(
            existing_stats=self._stats(total_value=1_000),
            total_daily_value=20_000,  # 20% already used
        )
        # new=4000 → total=24000/100k=24% <= 25%
        allowed, _ = tracker.check_limits("SPY", 1, 4_000.0, nlv=100_000, decision_type="open")
        assert allowed is True

    def test_total_daily_value_block(self):
        """Cross-underlying total daily value exceeding limit."""
        tracker = self._make_tracker(
            existing_stats=self._stats(total_value=1_000),
            total_daily_value=23_000,  # 23% already used
        )
        # new=3000 → (23000+3000)/100k=26% > 25%
        allowed, reason = tracker.check_limits("SPY", 1, 3_000.0, nlv=100_000, decision_type="open")
        assert allowed is False
        assert "总市值限额" in reason


# ============================================================
# Cross-Layer: RiskConfig per-strategy override validation
# ============================================================


class TestRiskConfigPerStrategy:
    """Verify per-strategy YAML correctly overrides base config."""

    def test_base_config_defaults(self):
        """Base config has expected defaults."""
        cfg = RiskConfig.load()
        assert cfg.max_positions == 20
        assert cfg.max_margin_utilization == 0.70

    def test_leaps_strategy_overrides(self):
        """spy_leaps_only_vol_target.yaml widens limits for long options."""
        cfg = RiskConfig.load("spy_leaps_only_vol_target")
        # LEAPS: relaxed margin since long options don't use margin
        assert cfg.max_margin_utilization > 0.70
        assert cfg.min_available_margin == 0
        assert cfg.max_order_value_pct > 0.10  # higher for expensive LEAPS
        assert cfg.daily_max_open_qty_per_underlying > 5

    def test_short_put_strategy_overrides(self):
        """short_put_with_assignment.yaml tightens limits for naked puts."""
        cfg = RiskConfig.load("short_put_with_assignment")
        # Short put: tighter margin controls
        assert cfg.max_positions < 20
        assert cfg.max_margin_utilization < 0.70
        assert cfg.min_available_margin > 10_000  # higher reserve
        assert cfg.max_projected_margin_utilization < 0.80

    def test_unknown_strategy_falls_back_to_base(self):
        """Unknown strategy name loads base config (no crash)."""
        cfg = RiskConfig.load("nonexistent_strategy_xyz")
        assert cfg.max_positions == 20  # base default


# ============================================================
# Integration: AccountRiskGuard + RiskConfig per-strategy
# ============================================================


class TestAccountRiskGuardWithStrategyConfig:
    """Verify per-strategy config actually changes guard behavior."""

    def test_short_put_config_blocks_at_lower_margin(self):
        """Short put strategy has tighter margin → blocks earlier."""
        cfg = RiskConfig.load("short_put_with_assignment")
        guard = AccountRiskGuard(cfg)

        # margin_used/nlv = 0.65 → above short_put's 0.60 limit, but below base 0.70
        portfolio = _make_portfolio(nlv=100_000, margin_used=65_000)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 0  # blocked by short_put config

    def test_base_config_allows_at_same_margin(self):
        """Base config (0.70) allows what short_put config blocks at margin_util level."""
        cfg = RiskConfig.load()
        guard = AccountRiskGuard(cfg)

        # margin_used/nlv = 0.65 < base max 0.70 → passes utilization check
        # available = 100k*0.70 - 55k = 15k > min 10k → passes available margin too
        portfolio = _make_portfolio(nlv=100_000, margin_used=55_000)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1  # allowed by base config

    def test_leaps_config_allows_low_margin_reserve(self):
        """LEAPS config sets min_available_margin=0 → very permissive."""
        cfg = RiskConfig.load("spy_leaps_only_vol_target")
        guard = AccountRiskGuard(cfg)

        # available = NLV*0.90 - margin_used = 90k - 85k = 5k
        # min_available_margin=0, so this passes
        portfolio = _make_portfolio(nlv=100_000, margin_used=85_000)
        signals = [_make_entry_signal(instrument_type=InstrumentType.OPTION)]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 1

    def test_short_put_fewer_max_positions(self):
        """Short put has max_positions=10 → blocks at 10."""
        cfg = RiskConfig.load("short_put_with_assignment")
        guard = AccountRiskGuard(cfg)

        positions = [_make_position() for _ in range(10)]
        portfolio = _make_portfolio(positions=positions, margin_used=10_000)
        signals = [_make_entry_signal()]
        result = guard.check(signals, portfolio, _make_market())
        assert len(result) == 0  # blocked: 10 >= 10
