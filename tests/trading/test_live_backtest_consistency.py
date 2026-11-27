"""Verification test suite for Live Paper Trading vs. Backtest execution consistency.

Tests all 6 structural engineering fixes identified in the 2026 QQQ leaps_smartrisk
live paper trading postmortem:
1. LeapsContractSelector pre-quote candidate sorting (1,400+ contracts -> target DTE=252, Delta=0.70)
2. Option limit price tick-size normalization (eliminating IBKR Error 110 on .xx5 3-decimal mid prices)
3. Stateless daily CLI state pre-warming (VIX history, SMA200 20d slope, VIX3M neutral fallback, 5d rebalance cooldown restoration)
4. Multi-contract rebalance reduction and weighted-average delta target calculation
5. Post-RiskGuard CashSweep (SHV) exit quantity resynchronization & leaps_smartrisk RiskConfig alignment
6. IBKR PendingSubmit working-order handling & same-day anti-oversell guard (preventing naked short calls)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

# Prevent futu import-time log dir creation error inside sandbox
sys.modules.setdefault("futu", None)

from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.daily_limits import DailyLimitsConfig
from src.business.trading.live_executor import LiveStrategyExecutor
from src.business.trading.models.order import (
    AssetClass,
    OrderRecord,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.business.trading.provider.ibkr_trading import IBKRTradingProvider
from src.business.trading.signal_order_builder import (
    SignalOrderBuilder,
    normalize_tick_price,
)
from src.data.models.option import Greeks, OptionChain, OptionContract, OptionQuote
from src.engine.bs.core import calc_bs_price
from src.engine.bs.greeks import calc_bs_delta
from src.engine.models.bs_params import BSParams
from src.strategy.cash_sweep import CashSweepConfig
from src.strategy.execution_log import ExecutionLog
from src.strategy.leaps_selector import LeapsContractSelector, LeapsSelectionConfig
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
from src.strategy.risk import RiskGuard
from src.strategy.versions.leaps_smartrisk import (
    LeapsSmartRiskConfig,
    LeapsSmartRiskStrategy,
)


# ============================================================================
# Helpers & Mock Data Builders
# ============================================================================


@dataclass
class MockMacroPoint:
    date: date
    value: float
    close: float


@dataclass
class MockStockBar:
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class MockIBKRChainDataProvider:
    """Simulates IBKR's large unsorted option chain (1,400+ contracts across 7 expiries)."""

    def __init__(self, as_of: date, spot: float = 602.20) -> None:
        self.as_of = as_of
        self.spot = spot
        self.last_requested_candidates: list[OptionContract] = []

    def get_option_chain(
        self,
        underlying: str,
        expiry_min_days: int = 180,
        expiry_max_days: int = 400,
    ) -> OptionChain:
        # IBKR returns contracts sorted by expiry ascending, then strike ascending (from deep ITM $250 to $850)
        dte_list = [185, 215, 252, 285, 315, 345, 375]
        calls: list[OptionQuote] = []
        ts = datetime.combine(self.as_of, datetime.min.time())
        for dte in dte_list:
            exp = self.as_of + timedelta(days=dte)
            # 204 strikes per expiry * 7 expiries = 1,428 call contracts
            for idx in range(204):
                strike = 250.0 + idx * 3.0
                c = OptionContract(
                    symbol=f"{underlying}_{exp.strftime('%Y%m%d')}_C_{int(strike)}",
                    underlying=underlying,
                    option_type="call",
                    strike_price=strike,
                    expiry_date=exp,
                    lot_size=100,
                )
                calls.append(OptionQuote(contract=c, timestamp=ts))
        return OptionChain(
            underlying=underlying,
            timestamp=ts,
            expiry_dates=[self.as_of + timedelta(days=d) for d in dte_list],
            calls=calls,
            puts=[],
        )

    def get_option_quotes_batch(
        self, contracts: list[OptionContract], min_volume: int = 0
    ) -> list[OptionQuote]:
        self.last_requested_candidates = list(contracts)
        quotes: list[OptionQuote] = []
        for c in contracts:
            dte = max(1, (c.expiry_date - self.as_of).days)
            params = BSParams(
                spot_price=self.spot,
                strike_price=c.strike_price,
                risk_free_rate=0.04,
                volatility=0.22,
                time_to_expiry=dte / 365.0,
                is_call=True,
            )
            delta = calc_bs_delta(params)
            theo = max(0.50, calc_bs_price(params))
            # Create odd-cent bid/ask spread (0.01 wide -> .xx5 raw mid) to test tick rounding too
            bid = round(theo - 0.005, 2)
            ask = round(bid + 0.01, 2)
            quotes.append(
                OptionQuote(
                    contract=c,
                    timestamp=datetime.combine(self.as_of, datetime.min.time()),
                    last_price=round(theo, 2),
                    bid=bid,
                    ask=ask,
                    volume=150,
                    open_interest=1200,
                    iv=0.22,
                    greeks=Greeks(delta=delta, gamma=0.003, theta=-0.05, vega=0.80),
                )
            )
        return quotes


# ============================================================================
# Issue 1: LeapsContractSelector Pre-Quote Candidate Sorting
# ============================================================================


def test_issue1_leaps_selector_presorts_1400_contracts() -> None:
    """Verify LeapsContractSelector pre-sorts 1,428 contracts before taking top 60.

    Without pre-sorting, prefiltered[:60] only keeps DTE=185 and deep ITM strikes (K=250..427, Delta>0.90).
    With pre-sorting, shortlisted[:60] centers around target_dte=252 and target_delta=0.70.
    """
    as_of = date(2026, 9, 23)
    spot = 602.20
    dp = MockIBKRChainDataProvider(as_of=as_of, spot=spot)
    cfg = LeapsSelectionConfig(
        target_dte=252,
        min_dte=180,
        max_dte=400,
        target_delta=0.70,
        min_delta=0.50,
        max_delta=0.85,
        max_candidates=60,
    )

    # Confirm raw chain has 1,428 contracts and naive [:60] would only see DTE=185, K<=427
    raw_chain = dp.get_option_chain("QQQ")
    assert len(raw_chain.calls) == 1428
    naive_first_60 = raw_chain.calls[:60]
    assert all((c.contract.expiry_date - as_of).days == 185 for c in naive_first_60)
    assert max(c.contract.strike_price for c in naive_first_60) < 430.0

    # Run fixed LeapsContractSelector
    selector = LeapsContractSelector()
    best = selector.select("QQQ", spot, as_of, dp, cfg)

    assert best is not None
    selected_dte = (best.contract.expiry_date - as_of).days
    selected_delta = best.greeks.delta

    # Must pick the 252-DTE expiry and delta close to 0.70 (not DTE=185, delta=0.85)
    assert selected_dte == 252, f"Expected DTE=252, got {selected_dte}"
    assert 0.67 <= selected_delta <= 0.73, f"Expected delta ~0.70, got {selected_delta:.3f}"
    assert 555.0 <= best.contract.strike_price <= 585.0


# ============================================================================
# Issue 2: Option Limit Price Tick-Size Normalization (IBKR Error 110 Fix)
# ============================================================================


def test_issue2_tick_size_normalization_prevents_error_110() -> None:
    """Verify 3-decimal mid prices (.xx5) are normalized to 2-decimal tick increments across all layers."""
    # 1. Direct helper check (exact 2026-07-02 live failure prices: 132.155, 68.255, 134.185)
    for raw_mid in (132.155, 68.255, 134.185, 134.965):
        norm = normalize_tick_price(raw_mid, AssetClass.OPTION)
        assert norm is not None
        assert round(norm, 2) == norm
        assert abs(norm - raw_mid) <= 0.0051

    # 2. Strategy _build_leaps_entry quote_price check
    as_of = date(2026, 7, 2)
    dp = MockIBKRChainDataProvider(as_of=as_of, spot=602.20)
    strat = LeapsSmartRiskStrategy()
    strat._last_nlv = 1_000_000.0
    strat._last_cash = 1_000_000.0
    market = MarketSnapshot(date=as_of, prices={"QQQ": 602.20}, vix=16.5)

    sig = strat._build_leaps_entry("QQQ", 602.20, 1.0, market, dp)
    assert sig is not None
    assert sig.quote_price is not None
    assert round(sig.quote_price, 2) == sig.quote_price, (
        f"Signal quote_price {sig.quote_price} has more than 2 decimal places"
    )

    # 3. SignalOrderBuilder check with an explicitly unrounded 132.155 quote_price
    unrounded_sig = replace(sig, quote_price=132.155)
    builder = SignalOrderBuilder()
    orders = builder.build(
        [unrounded_sig],
        PortfolioState(date=as_of, nlv=1_000_000.0, cash=1_000_000.0, margin_used=0.0, positions=[]),
    )
    assert len(orders) == 1
    assert orders[0].limit_price == 132.16

    # 4. IBKRTradingProvider._build_order safety-net rounding check
    provider = IBKRTradingProvider.__new__(IBKRTradingProvider)
    raw_order = replace(orders[0], limit_price=134.965)
    ib_order = provider._build_order(raw_order)
    assert ib_order.lmtPrice == 134.97


# ============================================================================
# Issue 3: Stateless CLI Cooldown & History Pre-Warming (VIX, SMA200, VIX3M)
# ============================================================================


class MockStatelessHistoryProvider:
    """Provides historical QQQ prices (with declining SMA200), VIX spike history, and missing VIX3M."""

    def __init__(self, as_of: date) -> None:
        self.as_of = as_of

    def get_history_kline(
        self, symbol: str, ktype: Any, start_date: date, end_date: date
    ) -> list[MockStockBar]:
        # Construct 260 trading days where earlier days were high (720) and recent 60 days
        # rallied from 560 to 616: short/medium-term momentum score > 0,
        # while current close (616) < price 200 days ago (720) -> 20-day SMA200 slope < 0!
        prices: list[MockStockBar] = []
        n_days = 260
        for i in range(n_days):
            d = end_date - timedelta(days=n_days - 1 - i)
            if i < 65:
                close = 720.0
            elif i < 200:
                close = 560.0
            else:
                close = 560.0 + (i - 200) * 0.95
            prices.append(
                MockStockBar(
                    symbol=symbol,
                    date=d,
                    open=close,
                    high=close * 1.005,
                    low=close * 0.995,
                    close=round(close, 2),
                    volume=1_000_000,
                )
            )
        return prices

    def get_macro_data(self, indicator: str, start_date: date, end_date: date) -> list[MockMacroPoint]:
        if indicator == "^VIX3M":
            # Simulate missing VIX3M data on live IBKR feed
            return []
        if indicator == "^VIX":
            # 25 days of VIX around 16.0, then today spikes to 22.0 (+7.5 pts with market.vix=23.5)
            pts: list[MockMacroPoint] = []
            for i in range(25):
                d = end_date - timedelta(days=25 - i)
                v = 16.0 if i < 24 else 22.0
                pts.append(MockMacroPoint(date=d, value=v, close=v))
            return pts
        return []


def test_issue3_stateless_cli_cooldown_and_history_prewarm() -> None:
    """Verify a fresh LeapsSmartRiskStrategy instance pre-warms VIX, SMA200 slope, VIX3M, and cooldown."""
    as_of = date(2026, 9, 23)
    dp = MockStatelessHistoryProvider(as_of=as_of)
    strat = LeapsSmartRiskStrategy()

    # 1. Missing ^VIX3M with VIX=27.0 must fall back to neutral ratio=1.0 (not 27.0 / 20.0 = 1.35 panic exit!)
    market_vix_23 = MarketSnapshot(date=as_of, prices={"QQQ": 616.0}, vix=27.0)
    vix3m = strat._get_vix3m(market_vix_23, dp)
    assert vix3m == 27.0, f"Expected neutral fallback vix3m=27.0, got {vix3m}"

    # 2. Fresh instance pre-warms _vix_history and _sma200_history on Day 1
    assert len(strat._vix_history) == 0
    assert len(strat._sma200_history) == 0

    strat._apply_smartrisk_filters(market_vix_23, dp)
    assert len(strat._vix_history) >= 20, "Expected _vix_history to be pre-warmed from data_provider"
    assert len(strat._sma200_history) > 20, "Expected _sma200_history to be pre-warmed from momentum computer"

    # Verify VIX 5-day change (+11.0 pts from 16.0 to 27.0, > 10.0 threshold) and Bear Market Limiter (declining SMA200) both worked on Day 1
    vix_5d = strat._get_vix_5d_change(27.0)
    assert vix_5d is not None and vix_5d == pytest.approx(11.0, abs=0.01)
    filtered_result = strat._momentum.compute(market_vix_23, dp)
    assert filtered_result["panic_regime"] == "vix_5d_spike"
    assert filtered_result["bear_regime"] in ("sma200_declining", "below_sma200")

    # 3. Vega Guard triggers on Day 1 of a fresh strategy instance when VIX spikes > 1.3x SMA20
    fresh_strat = LeapsSmartRiskStrategy()
    pos = PositionView(
        position_id="pos_1",
        instrument=Instrument(
            InstrumentType.OPTION, "QQQ", OptionRight.CALL, 550.0, date(2027, 6, 17), 100
        ),
        quantity=10,
        entry_price=75.0,
        entry_date=date(2026, 6, 1),
        current_price=80.0,
        underlying_price=616.0,
        unrealized_pnl=5_000.0,
        delta=0.72,
        dte=267,
        lot_size=100,
    )
    portfolio = PortfolioState(
        date=as_of, nlv=500_000.0, cash=420_000.0, margin_used=0.0, positions=[pos]
    )
    fresh_strat.on_day_start(market_vix_23, portfolio)
    fresh_strat._ensure_vix_history(market_vix_23, dp)
    vega_signals = fresh_strat._check_vega_guard([pos], market_vix_23)
    assert len(vega_signals) == 1
    assert vega_signals[0].target_quantity == -5  # 50% reduction of 10 contracts

    # 4. Cooldown restoration across stateless CLI restarts via OrderStore
    cooldown_strat = LeapsSmartRiskStrategy()
    mock_pipeline = MagicMock()
    recent_order = OrderRequest(
        order_id="ord_prev",
        decision_id="dec_prev",
        symbol="QQQ 20270617 C 550",
        asset_class=AssetClass.OPTION,
        underlying="QQQ",
        option_type="call",
        strike=550.0,
        expiry="2027-06-17",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=5,
        limit_price=75.0,
        status=OrderStatus.FILLED,
        created_at=datetime(2026, 9, 21, 22, 0, 0),  # 2 business days before 2026-09-23
    )
    mock_pipeline.order_store.get_recent.return_value = [OrderRecord(order=recent_order)]

    executor = LiveStrategyExecutor(
        strategy=cooldown_strat,
        data_provider=dp,
        account_aggregator=MagicMock(),
        trading_pipeline=mock_pipeline,
        symbols=["QQQ"],
    )
    executor._restore_strategy_state(market_vix_23)
    assert cooldown_strat._last_rebalance_date == date(2026, 9, 21)
    # 2 business days < min_rebalance_interval (5) -> cooldown blocks rebalance!
    assert cooldown_strat._is_rebalance_cooldown_ok(date(2026, 9, 23), 5) is False
    # 5 business days later (2026-09-28) -> cooldown allows rebalance!
    assert cooldown_strat._is_rebalance_cooldown_ok(date(2026, 9, 28), 5) is True


# ============================================================================
# Issue 4: Multi-Contract Rebalance Reduction & Weighted-Average Delta
# ============================================================================


def test_issue4_multi_contract_rebalance_and_weighted_delta() -> None:
    """Verify _rebalance_signals reduces across multiple held option contracts in a single run."""
    as_of = date(2026, 8, 5)
    market = MarketSnapshot(date=as_of, prices={"QQQ": 550.0}, vix=20.0)
    strat = LeapsSmartRiskStrategy()
    strat._last_nlv = 990_000.0

    # 3 fragmented option holdings (9 contracts each = 27 total), reproducing June-Oct 2026 fragmentation
    p1 = PositionView(
        position_id="c610",
        instrument=Instrument(InstrumentType.OPTION, "QQQ", OptionRight.CALL, 610.0, date(2027, 3, 19), 100),
        quantity=9,
        entry_price=45.0,
        entry_date=date(2026, 6, 15),
        current_price=45.0,
        underlying_price=550.0,
        unrealized_pnl=0.0,
        delta=0.60,
        dte=226,
        lot_size=100,
    )
    p2 = PositionView(
        position_id="c625",
        instrument=Instrument(InstrumentType.OPTION, "QQQ", OptionRight.CALL, 625.0, date(2027, 1, 15), 100),
        quantity=9,
        entry_price=38.0,
        entry_date=date(2026, 6, 20),
        current_price=38.0,
        underlying_price=550.0,
        unrealized_pnl=0.0,
        delta=0.50,
        dte=163,
        lot_size=100,
    )
    p3 = PositionView(
        position_id="c630",
        instrument=Instrument(InstrumentType.OPTION, "QQQ", OptionRight.CALL, 630.0, date(2027, 6, 17), 100),
        quantity=9,
        entry_price=52.0,
        entry_date=date(2026, 7, 1),
        current_price=52.0,
        underlying_price=550.0,
        unrealized_pnl=0.0,
        delta=0.70,
        dte=316,
        lot_size=100,
    )
    leaps_pos = [p1, p2, p3]

    # Weighted-average delta across p1(0.60), p2(0.50), p3(0.70) with equal qty 9 is 0.60
    # At target_pct = 0.30, target_contracts = floor(0.30 * 990,000 / (0.60 * 100 * 550)) = 9 contracts
    target_contracts = strat._compute_leaps_target(0.30, leaps_pos, market)
    assert target_contracts == 9

    # Rebalance from 27 -> 9 requires selling 18 contracts across 2 positions in ONE day (not 9 per day!)
    signals = strat._rebalance_signals([], leaps_pos, target_pct=0.30, current_pct=0.90, market=market)
    assert len(signals) == 2, f"Expected 2 EXIT signals across contracts, got {len(signals)}"
    total_sold = sum(abs(s.target_quantity) for s in signals)
    assert total_sold == 18, f"Expected 18 total contracts sold in single rebalance, got {total_sold}"
    # Shorter DTE contract (p2, DTE=163) should be prioritized first among equal-quantity positions
    assert signals[0].position_id == "c625"
    assert signals[0].target_quantity == -9
    assert signals[1].position_id == "c610"
    assert signals[1].target_quantity == -9


# ============================================================================
# Issue 5: Post-RiskGuard CashSweep Resync & leaps_smartrisk RiskConfig
# ============================================================================


class TruncatingRiskGuard(RiskGuard):
    """Test RiskGuard that truncates option ENTRY quantity from 20 down to 8 contracts."""

    def check(
        self, signals: list[Signal], portfolio: PortfolioState, market: MarketSnapshot
    ) -> list[Signal]:
        out: list[Signal] = []
        for s in signals:
            if s.type == SignalType.ENTRY and not s.metadata.get("is_cash_equivalent"):
                out.append(replace(s, target_quantity=8))
            else:
                out.append(s)
        return out


def test_issue5_post_guard_cash_sweep_resync_and_leaps_risk_config() -> None:
    """Verify SHV cash-sweep sell is scaled down when RiskGuard truncates option ENTRY, and RiskConfig loads."""
    # 1. Verify config/trading/leaps_smartrisk.yaml loads 50% daily limit instead of 10% default
    rc = RiskConfig.load("leaps_smartrisk")
    dl_cfg = DailyLimitsConfig.from_risk_config(rc)
    assert rc.daily_max_value_pct_per_underlying == 50.0
    assert rc.max_order_value_pct == 0.50
    assert dl_cfg.max_value_pct_per_underlying == 50.0

    # Verify default leaps_smartrisk uses Opt-C Smooth VolTarget (vol_target=20.0, vol_scalar_max=1.0)
    from src.strategy.registry import StrategyRegistry
    live_strat = StrategyRegistry.create("leaps_smartrisk")
    assert live_strat._config.momentum.vol_target == 20.0
    assert live_strat._config.momentum.vol_scalar_max == 1.0

    # 2. Verify LiveStrategyExecutor._resync_cash_sweep_signals scales down SHV sell after ENTRY truncation
    as_of = date(2026, 7, 1)
    market = MarketSnapshot(date=as_of, prices={"QQQ": 600.0, "SHV": 110.0}, vix=15.0)
    shv_pos = PositionView(
        position_id="shv_1",
        instrument=Instrument(InstrumentType.STOCK, "SHV", lot_size=1),
        quantity=2000,
        entry_price=110.0,
        entry_date=date(2026, 5, 1),
        current_price=110.0,
        underlying_price=110.0,
        unrealized_pnl=0.0,
        lot_size=1,
    )
    port_state = PortfolioState(
        date=as_of,
        nlv=1_000_000.0,
        cash=10_000.0,  # Only $10k raw cash, rest in SHV
        margin_used=0.0,
        positions=[shv_pos],
    )

    strat = LeapsSmartRiskStrategy(
        LeapsSmartRiskConfig(
            cash_sweep_config=CashSweepConfig(
                enabled=True, instrument_symbol="SHV", min_cash_buffer_pct=0.005
            )
        )
    )
    option_inst = Instrument(
        InstrumentType.OPTION, "QQQ", OptionRight.CALL, 570.0, date(2027, 3, 19), 100
    )
    # Initial pre-guard signals: Buy 20x QQQ Call @ $65.00 ($130,000 needed) -> Sell 1,137 sh SHV
    pre_guard_entry = Signal(
        type=SignalType.ENTRY,
        instrument=option_inst,
        target_quantity=20,
        reason="LEAPS entry 20x",
        quote_price=65.0,
    )
    pre_cash_needed = 20 * 65.0 * 100  # $130,000
    initial_shv_exits = strat.compute_cash_sweep_exits(market, port_state, pre_cash_needed)
    assert len(initial_shv_exits) == 1
    initial_shv_sell_qty = abs(initial_shv_exits[0].target_quantity)
    assert initial_shv_sell_qty > 1100  # ~$125k of SHV

    # Now TruncatingRiskGuard cuts option ENTRY from 20 -> 8 contracts ($52,000 needed)
    guard = TruncatingRiskGuard()
    post_guard_signals = guard.check(initial_shv_exits + [pre_guard_entry], port_state, market)

    executor = LiveStrategyExecutor(
        strategy=strat,
        data_provider=MagicMock(),
        account_aggregator=MagicMock(),
        trading_pipeline=MagicMock(),
        symbols=["QQQ"],
        risk_guards=[guard],
    )
    trace = ExecutionLog()
    resynced = executor._resync_cash_sweep_signals(
        post_guard_signals, pre_cash_needed, port_state, market, trace
    )

    shv_exits_after = [s for s in resynced if s.metadata.get("is_cash_equivalent")]
    assert len(shv_exits_after) == 1
    resynced_shv_sell_qty = abs(shv_exits_after[0].target_quantity)
    # 8 contracts * $65 * 100 = $52,000 needed; with $5,000 usable cash ($10k - $5k reserve),
    # deficit is $47,000 -> ceil(47000 / 110) = 428 shares (far less than 1,137 shares!)
    assert resynced_shv_sell_qty == 428, (
        f"Expected resynced SHV sell qty=428, got {resynced_shv_sell_qty}"
    )


# ============================================================================
# Issue 6: IBKR PendingSubmit Timeout Handling & Anti-Oversell Guard
# ============================================================================


def test_issue6_ibkr_pendingsubmit_and_anti_oversell_guard() -> None:
    """Verify PendingSubmit without error is treated as working, and duplicate same-day EXIT is clamped."""
    # Part A: IBKRTradingProvider.submit_order with PendingSubmit and no IBKR error
    provider = IBKRTradingProvider.__new__(IBKRTradingProvider)
    provider._connected = True
    provider._order_errors = {}
    provider._submit_wait_seconds = 0.1  # Fast poll for unit test
    provider._validate_paper_account = MagicMock()
    provider._build_contract = MagicMock(return_value=MagicMock())
    provider._build_order = MagicMock(return_value=MagicMock())

    mock_trade = MagicMock()
    mock_trade.order.orderId = 9001
    mock_trade.orderStatus.status = "PendingSubmit"

    mock_ib = MagicMock()
    mock_ib.isConnected.return_value = True
    mock_ib.managedAccounts.return_value = ["DUM321734"]
    mock_ib.placeOrder.return_value = mock_trade
    provider._ib = mock_ib

    order_req = OrderRequest(
        order_id="test_pending_submit",
        decision_id="dec_1",
        symbol="QQQ 20270617 C 650",
        asset_class=AssetClass.OPTION,
        underlying="QQQ",
        option_type="call",
        strike=650.0,
        expiry="2027-06-17",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=9,
        account_type="paper",
    )

    res = provider.submit_order(order_req)
    assert res.success is True, "PendingSubmit without error must be treated as working/submitted, not failed"
    assert res.broker_status == "PendingSubmit"
    assert res.broker_order_id == "9001"

    # If an IBKR error WAS recorded for orderId 9001, PendingSubmit timeout MUST fail
    provider._order_errors[9001] = [(110, "The price does not conform to the minimum price variation.")]
    res_err = provider.submit_order(order_req)
    assert res_err.success is False
    assert res_err.error_code == "ORDER_TIMEOUT"

    # Part B: Anti-oversell guard prevents 2026-10-15 double-sell into -9 naked short calls
    as_of = date(2026, 10, 15)
    market = MarketSnapshot(date=as_of, prices={"QQQ": 598.0}, vix=22.0)
    c650_inst = Instrument(
        InstrumentType.OPTION, "QQQ", OptionRight.CALL, 650.0, date(2027, 6, 17), 100
    )
    c650_pos = PositionView(
        position_id="pos_c650",
        instrument=c650_inst,
        quantity=9,
        entry_price=48.0,
        entry_date=date(2026, 9, 25),
        current_price=40.0,
        underlying_price=598.0,
        unrealized_pnl=-7_200.0,
        delta=0.55,
        dte=245,
        lot_size=100,
    )
    port_state = PortfolioState(
        date=as_of, nlv=950_000.0, cash=500_000.0, margin_used=0.0, positions=[c650_pos]
    )

    # OrderStore already has a working/filled SELL 9 order for C650 submitted earlier today
    working_sell_record = OrderRecord(
        order=replace(order_req, status=OrderStatus.SUBMITTED)
    )
    mock_pipeline = MagicMock()
    mock_pipeline.order_store.get_daily_orders_by_underlying.return_value = [working_sell_record]

    executor = LiveStrategyExecutor(
        strategy=MagicMock(),
        data_provider=MagicMock(),
        account_aggregator=MagicMock(),
        trading_pipeline=mock_pipeline,
        symbols=["QQQ"],
    )

    duplicate_exit_sig = Signal(
        type=SignalType.EXIT,
        instrument=c650_inst,
        target_quantity=-9,
        reason="Exit: target=0",
        position_id="pos_c650",
        priority=10,
    )
    trace = ExecutionLog()
    clamped_signals = executor._clamp_duplicate_exit_signals(
        [duplicate_exit_sig], port_state, market, trace
    )
    assert len(clamped_signals) == 0, (
        "Duplicate EXIT signal must be blocked when full position is already being sold today"
    )
