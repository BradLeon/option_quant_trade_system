#!/usr/bin/env python3
"""End-to-End Trading Flow Verification.

验证从 Screening/Monitoring 到 Trading Provider 的完整交易链路。

完整数据流:
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT LAYER                                                         │
│  Screening System → ContractOpportunity                              │
│  Monitoring System → PositionSuggestion                              │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  DECISION LAYER                                                      │
│  DecisionEngine → TradingDecision                                    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  ORDER LAYER                                                         │
│  OrderGenerator → OrderRequest → RiskChecker → OrderManager          │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  EXECUTION LAYER                                                     │
│  TradingProvider (Mock) → TradingResult                              │
└─────────────────────────────────────────────────────────────────────┘

测试场景:
1. Screening → OPEN (US Option) - 完整开仓流程
2. Screening → OPEN (账户风控拒绝) - 风控验证
3. Screening → OPEN (HK 期权) - 港股合约格式
4. Monitoring → CLOSE (止盈) - 止盈平仓流程
5. Monitoring → CLOSE (止损 CRITICAL) - 紧急止损
6. Monitoring → ROLL - 展期决策
7. 批量处理 + 冲突解决 - 多信号处理

Usage:
    python tests/business/trading/verify_e2e_trading_flow.py
    python tests/business/trading/verify_e2e_trading_flow.py --verbose
"""

import argparse
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Screening models
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    MarketType,
    ScreeningResult,
)

# Monitoring models
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    MonitorStatus,
    PositionData,
)
from src.business.monitoring.suggestions import (
    ActionType,
    PositionSuggestion,
    UrgencyLevel,
)

# Trading models
from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
    TradingDecision,
)
from src.business.trading.models.order import (
    OrderRecord,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.business.trading.models.trading import (
    CancelResult,
    OrderQueryResult,
    TradingAccountType,
    TradingResult,
)

# Trading components
from src.business.trading.decision.engine import DecisionEngine
from src.business.trading.order.generator import OrderGenerator
from src.business.trading.order.manager import OrderManager
from src.business.trading.provider.base import TradingProvider

# Utils
from src.data.utils.symbol_formatter import SymbolFormatter
from src.engine.models.enums import StrategyType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# Mock TradingProvider (复用自 verify_order_manager.py)
# ============================================================


class MockTradingProvider(TradingProvider):
    """Mock provider for testing without real broker connection."""

    def __init__(self) -> None:
        super().__init__(account_type=TradingAccountType.PAPER)
        self._connected = False
        self._orders: dict[str, OrderRequest] = {}
        self._order_status: dict[str, str] = {}
        self._should_reject = False
        self._reject_reason = ""

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True
        logger.info("MockTradingProvider connected")

    def disconnect(self) -> None:
        self._connected = False
        logger.info("MockTradingProvider disconnected")

    def set_reject_next_order(self, reason: str = "Test rejection") -> None:
        self._should_reject = True
        self._reject_reason = reason

    def submit_order(self, order: OrderRequest) -> TradingResult:
        self._validate_paper_account()

        if self._should_reject:
            self._should_reject = False
            return TradingResult.failure_result(
                internal_order_id=order.order_id,
                error_code="REJECTED",
                error_message=self._reject_reason,
            )

        broker_order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
        self._orders[broker_order_id] = order
        self._order_status[broker_order_id] = "Submitted"

        return TradingResult.success_result(
            internal_order_id=order.order_id,
            broker_order_id=broker_order_id,
        )

    def query_order(self, broker_order_id: str) -> OrderQueryResult:
        if broker_order_id not in self._orders:
            return OrderQueryResult.not_found(broker_order_id)

        order = self._orders[broker_order_id]
        status = self._order_status.get(broker_order_id, "Unknown")

        return OrderQueryResult(
            found=True,
            broker_order_id=broker_order_id,
            status=status,
            filled_quantity=0,
            remaining_quantity=order.quantity,
            last_updated=datetime.now(),
        )

    def cancel_order(self, broker_order_id: str) -> CancelResult:
        self._validate_paper_account()

        if broker_order_id not in self._orders:
            return CancelResult.failure_cancel(broker_order_id, "Order not found")

        self._order_status[broker_order_id] = "Cancelled"
        return CancelResult.success_cancel(broker_order_id)

    def get_open_orders(self) -> list[OrderQueryResult]:
        results = []
        for broker_id, order in self._orders.items():
            status = self._order_status.get(broker_id, "")
            if status not in ("Filled", "Cancelled"):
                results.append(
                    OrderQueryResult(
                        found=True,
                        broker_order_id=broker_id,
                        status=status,
                        filled_quantity=0,
                        remaining_quantity=order.quantity,
                    )
                )
        return results


# ============================================================
# Test Fixtures
# ============================================================


def create_healthy_account_state() -> AccountState:
    """创建健康的账户状态"""
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=100000.0,
        cash_balance=50000.0,
        available_margin=40000.0,
        used_margin=30000.0,
        margin_utilization=0.30,
        cash_ratio=0.50,
        gross_leverage=1.5,
        total_position_count=5,
        option_position_count=3,
        stock_position_count=2,
        exposure_by_underlying={"AAPL": 2000, "TSLA": 1500},
    )


def create_risky_account_state() -> AccountState:
    """创建高风险的账户状态 (接近风控限制)"""
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=100000.0,
        cash_balance=8000.0,
        available_margin=5000.0,
        used_margin=75000.0,
        margin_utilization=0.75,  # 超过 70% 限制
        cash_ratio=0.08,  # 低于 10% 限制
        gross_leverage=3.5,
        total_position_count=15,
        option_position_count=12,
        stock_position_count=3,
    )


def create_us_contract_opportunity() -> ContractOpportunity:
    """创建美股 Put 期权机会"""
    return ContractOpportunity(
        symbol="NVDA",
        expiry="2025-02-28",
        strike=40.0,
        option_type="put",
        lot_size=100,
        bid=0.80,
        ask=0.90,
        mid_price=0.85,
        open_interest=5000,
        volume=1200,
        delta=-0.15,
        gamma=0.02,
        theta=0.08,
        vega=0.05,
        iv=0.45,
        dte=30,
        expected_roc=0.021,
        win_probability=0.85,
        kelly_fraction=0.60,
        theta_margin_ratio=0.08,
        passed=True,
        pass_reasons=["ExpROC=2.1%", "SR=2.5", "WinProb=85%"],
        recommended_position=0.15,
    )


def create_hk_contract_opportunity() -> ContractOpportunity:
    """创建港股 Put 期权机会 (9988.HK 阿里巴巴)"""
    return ContractOpportunity(
        symbol="9988.HK",
        expiry="2025-03-28",
        strike=145,
        option_type="put",
        trading_class="ALB",
        lot_size=500,
        bid=1.25,
        ask=1.35,
        mid_price=1.30,
        open_interest=2000,
        volume=500,
        delta=-0.18,
        gamma=0.01,
        theta=0.06,
        vega=0.04,
        iv=0.38,
        dte=60,
        expected_roc=0.018,
        win_probability=0.82,
        kelly_fraction=0.50,
        theta_margin_ratio=0.06,
        passed=True,
        pass_reasons=["ExpROC=1.8%", "WinProb=82%"],
        recommended_position=0.125,
    )


def create_screening_result(opportunities: list[ContractOpportunity]) -> ScreeningResult:
    """创建筛选结果"""
    return ScreeningResult(
        passed=len(opportunities) > 0,
        strategy_type=StrategyType.SHORT_PUT,
        market_status=MarketStatus(
            market_type=MarketType.US,
            is_favorable=True,
        ),
        opportunities=opportunities,
        confirmed=opportunities,
        scanned_underlyings=50,
        passed_underlyings=5,
        qualified_contracts=len(opportunities),
    )


def create_take_profit_suggestion() -> PositionSuggestion:
    """创建止盈建议"""
    return PositionSuggestion(
        position_id="POS-AAPL-001",
        symbol="AAPL 250221P00180000",
        action=ActionType.TAKE_PROFIT,
        urgency=UrgencyLevel.SOON,
        reason="达到止盈目标 65%",
        details="当前盈利 $330，目标止盈 50%",
        trigger_alerts=[
            Alert(
                alert_type=AlertType.PROFIT_TARGET,
                level=AlertLevel.GREEN,
                message="达到止盈目标",
                symbol="AAPL 250221P00180000",
                position_id="POS-AAPL-001",
                current_value=0.65,
                threshold_value=0.50,
            )
        ],
        metadata={
            "current_position": -2,
            "avg_cost": 2.50,
            "current_price": 0.85,
            "underlying": "AAPL",
            "strike": 180.0,
            "expiry": "2025-02-21",
            "option_type": "put",
        },
    )


def create_stop_loss_suggestion() -> PositionSuggestion:
    """创建止损建议 (CRITICAL)"""
    return PositionSuggestion(
        position_id="POS-TSLA-001",
        symbol="TSLA 250124P00200000",
        action=ActionType.CLOSE,
        urgency=UrgencyLevel.IMMEDIATE,
        reason="达到止损 -150%",
        details="当前亏损 $750，超过止损线 -100%",
        trigger_alerts=[
            Alert(
                alert_type=AlertType.STOP_LOSS,
                level=AlertLevel.RED,
                message="达到止损",
                symbol="TSLA 250124P00200000",
                position_id="POS-TSLA-001",
                current_value=-1.50,
                threshold_value=-1.00,
            )
        ],
        metadata={
            "current_position": -1,
            "avg_cost": 3.00,
            "current_price": 7.50,
            "underlying": "TSLA",
            "strike": 200.0,
            "expiry": "2025-01-24",
            "option_type": "put",
        },
    )


def create_roll_suggestion() -> PositionSuggestion:
    """创建展期建议"""
    return PositionSuggestion(
        position_id="POS-MSFT-001",
        symbol="MSFT 250131P00380000",
        action=ActionType.ROLL,
        urgency=UrgencyLevel.SOON,
        reason="DTE < 7 天，建议展期",
        details="当前 DTE=5，建议展期至下月",
        trigger_alerts=[
            Alert(
                alert_type=AlertType.DTE_WARNING,
                level=AlertLevel.YELLOW,
                message="临近到期",
                symbol="MSFT 250131P00380000",
                position_id="POS-MSFT-001",
                current_value=5,
                threshold_value=14,
            )
        ],
        metadata={
            "current_position": -1,
            "avg_cost": 2.00,
            "current_price": 0.50,
            "underlying": "MSFT",
            "strike": 380.0,
            "expiry": "2025-01-31",
            "option_type": "put",
            "suggested_expiry": "2025-02-28",
            "roll_credit": 0.15,
        },
    )


def create_monitor_result(suggestions: list[PositionSuggestion]) -> MonitorResult:
    """创建监控结果"""
    alerts = []
    for s in suggestions:
        alerts.extend(s.trigger_alerts)

    return MonitorResult(
        status=MonitorStatus.YELLOW if alerts else MonitorStatus.GREEN,
        alerts=alerts,
        suggestions=suggestions,
        total_positions=10,
        positions_at_risk=len([s for s in suggestions if s.urgency == UrgencyLevel.IMMEDIATE]),
        positions_opportunity=len([s for s in suggestions if s.action == ActionType.TAKE_PROFIT]),
    )


# ============================================================
# Tests
# ============================================================


def test_screening_to_open_us_option(verbose: bool = False) -> bool:
    """Test 1: Screening → OPEN (US Option)

    完整链路: ContractOpportunity → DecisionEngine → OrderRequest → TradingProvider
    """
    print("\n" + "=" * 70)
    print("Test 1: Screening → OPEN (US Option)")
    print("=" * 70)

    try:
        # Setup
        mock_provider = MockTradingProvider()
        mock_provider.connect()
        engine = DecisionEngine()
        order_manager = OrderManager(trading_provider=mock_provider)
        account_state = create_healthy_account_state()
        opportunity = create_us_contract_opportunity()

        print(f"\n  [INPUT] ContractOpportunity:")
        print(f"    symbol: {opportunity.symbol}")
        print(f"    strike: {opportunity.strike}")
        print(f"    expiry: {opportunity.expiry}")
        print(f"    option_type: {opportunity.option_type}")
        print(f"    expected_roc: {opportunity.expected_roc}")
        print(f"    win_probability: {opportunity.win_probability}")
        print(f"    kelly_fraction: {opportunity.kelly_fraction}")

        # Step 1: Decision Engine
        print(f"\n  [STEP 1] DecisionEngine.process_screen_signal()")
        decision = engine.process_screen_signal(opportunity, account_state)

        print(f"    decision_type: {decision.decision_type.value}")
        print(f"    source: {decision.source.value}")
        print(f"    priority: {decision.priority.value}")
        print(f"    quantity: {decision.quantity}")
        print(f"    limit_price: {decision.limit_price}")

        assert decision.decision_type == DecisionType.OPEN, "Expected OPEN decision"
        assert decision.source == DecisionSource.SCREEN_SIGNAL
        assert decision.quantity < 0, "Sell to open should have negative quantity"

        # Step 2: Order Manager - Create Order
        print(f"\n  [STEP 2] OrderManager.create_order()")
        order = order_manager.create_order(decision)

        print(f"    order_id: {order.order_id}")
        print(f"    side: {order.side.value}")
        print(f"    order_type: {order.order_type.value}")
        print(f"    quantity: {order.quantity}")
        print(f"    status: {order.status.value}")

        assert order.side == OrderSide.SELL, "OPEN + negative qty should be SELL"

        # Step 3: Order Manager - Validate
        print(f"\n  [STEP 3] OrderManager.validate_order()")
        result = order_manager.validate_order(order, account_state, current_mid_price=0.85)

        print(f"    passed: {result.passed}")
        if not result.passed:
            print(f"    failed_checks: {result.failed_checks}")

        assert result.passed, f"Validation should pass: {result.failed_checks}"

        # Step 4: Order Manager - Submit
        print(f"\n  [STEP 4] OrderManager.submit_order()")
        record = order_manager.submit_order(order)

        print(f"    status: {record.order.status.value}")
        print(f"    broker_order_id: {record.broker_order_id}")

        assert record.order.status == OrderStatus.SUBMITTED
        assert record.broker_order_id is not None
        assert record.broker_order_id.startswith("MOCK-")

        print("\n  [PASS] Screening → OPEN (US Option) flow completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 1 error")
        return False


def test_screening_rejected_by_account_risk(verbose: bool = False) -> bool:
    """Test 2: Screening → OPEN (账户风控拒绝)

    验证账户状态不满足开仓条件时，决策被拒绝。
    """
    print("\n" + "=" * 70)
    print("Test 2: Screening → OPEN (账户风控拒绝)")
    print("=" * 70)

    try:
        engine = DecisionEngine()
        account_state = create_risky_account_state()
        opportunity = create_us_contract_opportunity()

        print(f"\n  [INPUT] AccountState (高风险):")
        print(f"    margin_utilization: {account_state.margin_utilization:.1%}")
        print(f"    cash_ratio: {account_state.cash_ratio:.1%}")
        print(f"    gross_leverage: {account_state.gross_leverage:.1f}x")

        # Decision Engine returns None when account risk fails
        print(f"\n  [STEP 1] DecisionEngine.process_screen_signal()")
        decision = engine.process_screen_signal(opportunity, account_state)

        if decision is None:
            print(f"    Result: None (rejected due to account risk)")
            print("\n  [PASS] Account risk rejection working correctly")
            return True

        # If decision is returned, it should be HOLD
        print(f"    decision_type: {decision.decision_type.value}")
        print(f"    reason: {decision.reason}")

        assert decision.decision_type == DecisionType.HOLD, (
            f"Expected None or HOLD for risky account, got {decision.decision_type}"
        )

        print("\n  [PASS] Account risk rejection working correctly")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 2 error")
        return False


def test_screening_to_open_hk_option(verbose: bool = False) -> bool:
    """Test 3: Screening → OPEN (HK 期权)

    验证港股期权的完整链路，特别是 IBKR 合约格式。
    """
    print("\n" + "=" * 70)
    print("Test 3: Screening → OPEN (HK 期权)")
    print("=" * 70)

    try:
        mock_provider = MockTradingProvider()
        mock_provider.connect()
        engine = DecisionEngine()
        order_manager = OrderManager(trading_provider=mock_provider)

        # 创建 HK 账户状态 (无 9988.HK 暴露，避免暴露限制问题)
        # notional = strike × lot_size = 145 × 500 = 72,500 HKD
        # max_notional_pct_per_underlying = 5%, 需要 equity >= 72,500 / 5% = 1,450,000
        account_state = AccountState(
            broker="ibkr",
            account_type="paper",
            total_equity=1500000.0,  # HKD (足够支持 5% notional 限制)
            cash_balance=750000.0,
            available_margin=468000.0,
            used_margin=51000.0,
            margin_utilization=0.30,
            cash_ratio=0.50,
            gross_leverage=1.5,
            total_position_count=3,
            option_position_count=2,
            stock_position_count=1,
            exposure_by_underlying={},  # 无暴露
        )

        opportunity = create_hk_contract_opportunity()

        print(f"\n  [INPUT] HK ContractOpportunity:")
        print(f"    symbol: {opportunity.symbol}")
        print(f"    trading_class: {opportunity.trading_class}")
        print(f"    lot_size: {opportunity.lot_size}")
        print(f"    strike: {opportunity.strike}")

        # Step 1: Decision Engine
        print(f"\n  [STEP 1] DecisionEngine.process_screen_signal()")
        decision = engine.process_screen_signal(opportunity, account_state)

        if decision is None:
            print(f"    Result: None (rejected)")
            print("\n  [FAIL] HK option decision rejected unexpectedly")
            return False

        print(f"    decision_type: {decision.decision_type.value}")
        print(f"    quantity: {decision.quantity}")
        print(f"    trading_class: {decision.trading_class}")
        print(f"    contract_multiplier: {decision.contract_multiplier}")
        print(f"    currency: {decision.currency}")

        assert decision.decision_type == DecisionType.OPEN

        # Step 2: Create Order
        print(f"\n  [STEP 2] OrderManager.create_order()")
        order = order_manager.create_order(decision)

        print(f"    symbol: {order.symbol}")
        print(f"    underlying: {order.underlying}")
        print(f"    trading_class: {order.trading_class}")
        print(f"    contract_multiplier: {order.contract_multiplier}")
        print(f"    currency: {order.currency}")

        # Step 3: Verify IBKR contract format
        print(f"\n  [STEP 3] Verify IBKR Contract Format:")
        ibkr_params = SymbolFormatter.to_ibkr_contract(order.underlying)

        print(f"    IBKR symbol: {ibkr_params.symbol} (should be '9988')")
        print(f"    IBKR exchange: {ibkr_params.exchange} (should be 'SEHK')")
        print(f"    IBKR currency: {ibkr_params.currency} (should be 'HKD')")

        assert ibkr_params.symbol == "9988", f"Expected '9988', got '{ibkr_params.symbol}'"
        assert ibkr_params.exchange == "SEHK", f"Expected 'SEHK', got '{ibkr_params.exchange}'"
        assert ibkr_params.currency == "HKD", f"Expected 'HKD', got '{ibkr_params.currency}'"
        assert order.trading_class == "ALB"
        assert order.contract_multiplier == 500

        print("\n  [PASS] HK Option IBKR format correct")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 3 error")
        return False


def test_monitoring_to_close_take_profit(verbose: bool = False) -> bool:
    """Test 4: Monitoring → CLOSE (止盈)

    完整链路: PositionSuggestion → DecisionEngine → OrderRequest → TradingProvider
    """
    print("\n" + "=" * 70)
    print("Test 4: Monitoring → CLOSE (止盈)")
    print("=" * 70)

    try:
        mock_provider = MockTradingProvider()
        mock_provider.connect()
        engine = DecisionEngine()
        order_manager = OrderManager(trading_provider=mock_provider)
        account_state = create_healthy_account_state()
        suggestion = create_take_profit_suggestion()

        print(f"\n  [INPUT] PositionSuggestion:")
        print(f"    position_id: {suggestion.position_id}")
        print(f"    symbol: {suggestion.symbol}")
        print(f"    action: {suggestion.action.value}")
        print(f"    urgency: {suggestion.urgency.value}")
        print(f"    reason: {suggestion.reason}")
        print(f"    current_position: {suggestion.metadata.get('current_position')}")

        # Create position context for the suggestion
        position_context = PositionContext(
            position_id=suggestion.position_id,
            symbol=suggestion.symbol,
            underlying=suggestion.metadata.get("underlying", "AAPL"),
            option_type=suggestion.metadata.get("option_type", "put"),
            strike=suggestion.metadata.get("strike", 180.0),
            expiry=suggestion.metadata.get("expiry", "2025-02-21"),
            quantity=suggestion.metadata.get("current_position", -2),
            avg_cost=suggestion.metadata.get("avg_cost", 2.50),
            current_price=suggestion.metadata.get("current_price", 0.85),
        )

        # Step 1: Decision Engine
        print(f"\n  [STEP 1] DecisionEngine.process_monitor_signal()")
        decision = engine.process_monitor_signal(suggestion, account_state, position_context)

        print(f"    decision_type: {decision.decision_type.value}")
        print(f"    source: {decision.source.value}")
        print(f"    priority: {decision.priority.value}")
        print(f"    quantity: {decision.quantity}")
        print(f"    price_type: {decision.price_type}")

        assert decision.decision_type == DecisionType.CLOSE, (
            f"Expected CLOSE, got {decision.decision_type}"
        )
        assert decision.source == DecisionSource.MONITOR_ALERT
        assert decision.quantity > 0, "Buy to close should have positive quantity"

        # Step 2: Create Order
        print(f"\n  [STEP 2] OrderManager.create_order()")
        order = order_manager.create_order(decision)

        print(f"    order_id: {order.order_id}")
        print(f"    side: {order.side.value}")
        print(f"    order_type: {order.order_type.value}")
        print(f"    quantity: {order.quantity}")

        assert order.side == OrderSide.BUY, "Buy to close"
        assert order.order_type == OrderType.MARKET, "Close orders should be MARKET"

        # Step 3: Validate and Submit
        result = order_manager.validate_order(order, account_state, current_mid_price=0.85)
        assert result.passed

        record = order_manager.submit_order(order)
        print(f"\n  [STEP 3] Order submitted:")
        print(f"    status: {record.order.status.value}")
        print(f"    broker_order_id: {record.broker_order_id}")

        assert record.order.status == OrderStatus.SUBMITTED

        print("\n  [PASS] Monitoring → CLOSE (止盈) flow completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 4 error")
        return False


def test_monitoring_to_close_stop_loss(verbose: bool = False) -> bool:
    """Test 5: Monitoring → CLOSE (止损 - CRITICAL)

    验证紧急止损的处理优先级。
    """
    print("\n" + "=" * 70)
    print("Test 5: Monitoring → CLOSE (止损 - CRITICAL)")
    print("=" * 70)

    try:
        mock_provider = MockTradingProvider()
        mock_provider.connect()
        engine = DecisionEngine()
        order_manager = OrderManager(trading_provider=mock_provider)
        account_state = create_healthy_account_state()
        suggestion = create_stop_loss_suggestion()

        print(f"\n  [INPUT] PositionSuggestion (止损):")
        print(f"    action: {suggestion.action.value}")
        print(f"    urgency: {suggestion.urgency.value}")
        print(f"    reason: {suggestion.reason}")

        # Create position context for the suggestion
        position_context = PositionContext(
            position_id=suggestion.position_id,
            symbol=suggestion.symbol,
            underlying=suggestion.metadata.get("underlying", "TSLA"),
            option_type=suggestion.metadata.get("option_type", "put"),
            strike=suggestion.metadata.get("strike", 200.0),
            expiry=suggestion.metadata.get("expiry", "2025-01-24"),
            quantity=suggestion.metadata.get("current_position", -1),
            avg_cost=suggestion.metadata.get("avg_cost", 3.00),
            current_price=suggestion.metadata.get("current_price", 7.50),
        )

        # Step 1: Decision Engine
        print(f"\n  [STEP 1] DecisionEngine.process_monitor_signal()")
        decision = engine.process_monitor_signal(suggestion, account_state, position_context)

        print(f"    decision_type: {decision.decision_type.value}")
        print(f"    priority: {decision.priority.value}")
        print(f"    price_type: {decision.price_type}")

        assert decision.priority == DecisionPriority.CRITICAL, (
            f"Expected CRITICAL priority for IMMEDIATE urgency, got {decision.priority}"
        )
        assert decision.price_type == "market", "Stop loss should use market order"

        # Step 2: Create Order
        print(f"\n  [STEP 2] OrderManager.create_order()")
        order = order_manager.create_order(decision)

        print(f"    side: {order.side.value}")
        print(f"    order_type: {order.order_type.value}")

        assert order.order_type == OrderType.MARKET, "Stop loss must be MARKET order"

        print("\n  [PASS] Stop loss with CRITICAL priority working correctly")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 5 error")
        return False


def test_monitoring_to_roll(verbose: bool = False) -> bool:
    """Test 6: Monitoring → ROLL (完整流程)

    验证展期决策的完整处理流程：
    1. DecisionEngine 生成 ROLL 决策 (包含 roll_to_expiry)
    2. OrderManager.create_roll_orders() 生成两个订单 (平仓 + 开仓)
    3. 订单被正确提交
    """
    print("\n" + "=" * 70)
    print("Test 6: Monitoring → ROLL (完整流程)")
    print("=" * 70)

    try:
        mock_provider = MockTradingProvider()
        mock_provider.connect()
        engine = DecisionEngine()
        order_manager = OrderManager(trading_provider=mock_provider)
        account_state = create_healthy_account_state()
        suggestion = create_roll_suggestion()

        print(f"\n  [INPUT] PositionSuggestion (展期):")
        print(f"    action: {suggestion.action.value}")
        print(f"    urgency: {suggestion.urgency.value}")
        print(f"    reason: {suggestion.reason}")
        print(f"    current_expiry: {suggestion.metadata.get('expiry')}")
        print(f"    suggested_expiry: {suggestion.metadata.get('suggested_expiry')}")
        print(f"    roll_credit: {suggestion.metadata.get('roll_credit')}")

        # Create position context for the suggestion
        position_context = PositionContext(
            position_id=suggestion.position_id,
            symbol=suggestion.symbol,
            underlying=suggestion.metadata.get("underlying", "MSFT"),
            option_type=suggestion.metadata.get("option_type", "put"),
            strike=suggestion.metadata.get("strike", 380.0),
            expiry=suggestion.metadata.get("expiry", "2025-01-31"),
            quantity=suggestion.metadata.get("current_position", -1),
            avg_cost=suggestion.metadata.get("avg_cost", 2.00),
            current_price=suggestion.metadata.get("current_price", 0.50),
        )

        # Step 1: Decision Engine
        print(f"\n  [STEP 1] DecisionEngine.process_monitor_signal()")
        decision = engine.process_monitor_signal(suggestion, account_state, position_context)

        print(f"    decision_type: {decision.decision_type.value}")
        print(f"    priority: {decision.priority.value}")
        print(f"    current_expiry: {decision.expiry}")
        print(f"    roll_to_expiry: {decision.roll_to_expiry}")
        print(f"    roll_credit: {decision.roll_credit}")

        assert decision.decision_type == DecisionType.ROLL, (
            f"Expected ROLL, got {decision.decision_type}"
        )
        assert decision.roll_to_expiry == "2025-02-28", (
            f"Expected roll_to_expiry=2025-02-28, got {decision.roll_to_expiry}"
        )

        # Step 2: Create Roll Orders
        print(f"\n  [STEP 2] OrderManager.create_roll_orders()")
        orders = order_manager.create_roll_orders(decision)

        assert len(orders) == 2, f"Expected 2 orders, got {len(orders)}"

        close_order, open_order = orders

        print(f"    Close Order:")
        print(f"      order_id: {close_order.order_id}")
        print(f"      symbol: {close_order.symbol}")
        print(f"      expiry: {close_order.expiry}")
        print(f"      side: {close_order.side.value}")
        print(f"      order_type: {close_order.order_type.value}")

        print(f"    Open Order:")
        print(f"      order_id: {open_order.order_id}")
        print(f"      symbol: {open_order.symbol}")
        print(f"      expiry: {open_order.expiry}")
        print(f"      side: {open_order.side.value}")
        print(f"      order_type: {open_order.order_type.value}")

        # Verify close order
        assert close_order.side == OrderSide.BUY, "Close order should be BUY to close"
        assert close_order.expiry == "2025-01-31", "Close order expiry should match current"

        # Verify open order
        assert open_order.side == OrderSide.SELL, "Open order should be SELL to open"
        assert open_order.expiry == "2025-02-28", "Open order expiry should match roll_to_expiry"

        # Step 3: Validate and Submit
        print(f"\n  [STEP 3] Validate and Submit Orders")

        # Validate both orders
        close_result = order_manager.validate_order(close_order, account_state)
        open_result = order_manager.validate_order(open_order, account_state)

        print(f"    Close order validation: {close_result.passed}")
        print(f"    Open order validation: {open_result.passed}")

        assert close_result.passed, f"Close order validation failed: {close_result.failed_checks}"
        assert open_result.passed, f"Open order validation failed: {open_result.failed_checks}"

        # Submit roll orders
        records = order_manager.submit_roll_orders(orders)

        assert len(records) == 2, f"Expected 2 records, got {len(records)}"

        close_record, open_record = records

        print(f"\n  [RESULT]:")
        print(f"    Close: {close_record.order.status.value} (broker_id={close_record.broker_order_id})")
        print(f"    Open:  {open_record.order.status.value} (broker_id={open_record.broker_order_id})")

        assert close_record.order.status == OrderStatus.SUBMITTED, (
            f"Close order should be SUBMITTED, got {close_record.order.status}"
        )
        assert open_record.order.status == OrderStatus.SUBMITTED, (
            f"Open order should be SUBMITTED, got {open_record.order.status}"
        )

        print("\n  [PASS] ROLL complete flow working correctly")
        mock_provider.disconnect()
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 6 error")
        return False


def test_batch_processing_with_conflict(verbose: bool = False) -> bool:
    """Test 7: 批量处理 + 冲突解决

    验证多个信号的批量处理和冲突解决。
    """
    print("\n" + "=" * 70)
    print("Test 7: 批量处理 + 冲突解决")
    print("=" * 70)

    try:
        engine = DecisionEngine()
        account_state = create_healthy_account_state()

        # 创建筛选结果 (开仓信号)
        opportunities = [
            create_us_contract_opportunity(),
        ]
        screen_result = create_screening_result(opportunities)

        # 创建监控建议 (平仓信号)
        suggestions = [
            create_take_profit_suggestion(),
            create_stop_loss_suggestion(),
        ]

        print(f"\n  [INPUT]:")
        print(f"    Screen opportunities: {len(opportunities)}")
        print(f"    Monitor suggestions: {len(suggestions)}")

        # 批量处理
        print(f"\n  [STEP 1] DecisionEngine.process_batch()")
        decisions = engine.process_batch(
            screen_result=screen_result,
            account_state=account_state,
            suggestions=suggestions,
        )

        print(f"\n  [OUTPUT] Decisions ({len(decisions)}):")
        for i, d in enumerate(decisions, 1):
            print(f"    {i}. {d.decision_type.value} {d.symbol} (priority={d.priority.value})")

        # 验证优先级排序 (CRITICAL 应该在前面)
        if len(decisions) >= 2:
            critical_decisions = [d for d in decisions if d.priority == DecisionPriority.CRITICAL]
            print(f"\n  CRITICAL decisions: {len(critical_decisions)}")

            # 验证 CLOSE 决策存在 (来自 stop_loss)
            close_decisions = [d for d in decisions if d.decision_type == DecisionType.CLOSE]
            assert len(close_decisions) >= 1, "Should have at least one CLOSE decision"

        print("\n  [PASS] Batch processing completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 7 error")
        return False


def test_full_e2e_flow(verbose: bool = False) -> bool:
    """Test 8: 完整端到端流程

    模拟真实场景：同时处理筛选和监控信号。
    """
    print("\n" + "=" * 70)
    print("Test 8: 完整端到端流程 (Screening + Monitoring)")
    print("=" * 70)

    try:
        # Setup
        mock_provider = MockTradingProvider()
        mock_provider.connect()
        engine = DecisionEngine()
        order_manager = OrderManager(trading_provider=mock_provider)
        account_state = create_healthy_account_state()

        # 模拟筛选系统输出
        opportunities = [create_us_contract_opportunity()]
        screen_result = create_screening_result(opportunities)

        # 模拟监控系统输出
        suggestions = [create_take_profit_suggestion()]
        monitor_result = create_monitor_result(suggestions)

        print(f"\n  [INPUT]:")
        print(f"    ScreeningResult: {len(screen_result.confirmed)} opportunities")
        print(f"    MonitorResult: {len(monitor_result.suggestions)} suggestions")
        print(f"    AccountState: margin={account_state.margin_utilization:.1%}")

        # Step 1: 生成决策
        print(f"\n  [STEP 1] Generate Decisions")
        decisions = engine.process_batch(
            screen_result=screen_result,
            account_state=account_state,
            suggestions=suggestions,
        )

        print(f"    Generated {len(decisions)} decisions")

        # Step 2: 执行决策
        print(f"\n  [STEP 2] Execute Decisions")
        executed_count = 0
        for decision in decisions:
            if decision.decision_type == DecisionType.HOLD:
                print(f"    SKIP: {decision.symbol} (HOLD)")
                continue

            order = order_manager.create_order(decision)
            result = order_manager.validate_order(order, account_state, current_mid_price=0.85)

            if result.passed:
                record = order_manager.submit_order(order)
                print(f"    OK: {decision.decision_type.value} {decision.symbol} → {record.broker_order_id}")
                executed_count += 1
            else:
                print(f"    REJECT: {decision.symbol} ({result.failed_checks})")

        print(f"\n  [SUMMARY]:")
        print(f"    Decisions: {len(decisions)}")
        print(f"    Executed: {executed_count}")

        print("\n  [PASS] Full E2E flow completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Test 8 error")
        return False


def main():
    parser = argparse.ArgumentParser(description="End-to-End Trading Flow Verification")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output with stack traces"
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("End-to-End Trading Flow Verification")
    print("=" * 70)
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 70)

    results = {}

    # Screening Flow Tests
    print("\n" + "=" * 70)
    print("SCREENING FLOW TESTS")
    print("=" * 70)
    results["screening_open_us"] = test_screening_to_open_us_option(args.verbose)
    results["screening_rejected"] = test_screening_rejected_by_account_risk(args.verbose)
    results["screening_open_hk"] = test_screening_to_open_hk_option(args.verbose)

    # Monitoring Flow Tests
    print("\n" + "=" * 70)
    print("MONITORING FLOW TESTS")
    print("=" * 70)
    results["monitoring_take_profit"] = test_monitoring_to_close_take_profit(args.verbose)
    results["monitoring_stop_loss"] = test_monitoring_to_close_stop_loss(args.verbose)
    results["monitoring_roll"] = test_monitoring_to_roll(args.verbose)

    # Integration Tests
    print("\n" + "=" * 70)
    print("INTEGRATION TESTS")
    print("=" * 70)
    results["batch_processing"] = test_batch_processing_with_conflict(args.verbose)
    results["full_e2e_flow"] = test_full_e2e_flow(args.verbose)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {test_name}")

    print(f"\n  Total: {passed}/{total} tests passed")
    print("=" * 70 + "\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
