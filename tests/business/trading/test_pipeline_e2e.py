"""
交易链路端到端测试

使用 test_suggestion_coverage.py 中的所有 TestCase 构建 Mock 持仓数据，
测试完整转换链路:

    PositionData + Alert
         ↓ SuggestionGenerator
    PositionSuggestion
         ↓ DecisionEngine
    TradingDecision
         ↓ OrderGenerator
    OrderRequest
         ↓ TradingProvider (Mock)
    TradingResult

覆盖三层:
- Capital 级 (4 个指标)
- Portfolio 级 (7 个指标)
- Position 级 (多个指标)
"""

import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中（支持直接运行）
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from datetime import datetime
from dataclasses import dataclass

# Import from monitoring
from src.business.monitoring.suggestions import (
    SuggestionGenerator,
    ActionType,
    UrgencyLevel,
    PositionSuggestion,
)
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    MonitorStatus,
    PositionData,
)
from src.engine.models.enums import StrategyType

# Import from trading
from src.business.trading.decision.engine import (
    DecisionEngine,
    ACTION_TO_DECISION,
    URGENCY_TO_PRIORITY,
)
from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
    TradingDecision,
)
from src.business.trading.models.order import (
    AssetClass,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.business.trading.models.trading import TradingResult
from src.business.trading.order.generator import OrderGenerator

# Import test cases from test_suggestion_coverage
from tests.business.monitoring.test_suggestion_coverage import (
    TestCase,
    CAPITAL_TEST_CASES,
    PORTFOLIO_TEST_CASES,
    POSITION_TEST_CASES,
    create_mock_position,
    create_mock_alert,
)


# =============================================================================
# Mock Data Factory
# =============================================================================

def create_mock_account_state(
    total_equity: float = 100000,
    cash_balance: float = 30000,
    used_margin: float = 20000,
    available_margin: float = 60000,
    margin_utilization: float = 0.20,
    cash_ratio: float = 0.30,
    gross_leverage: float = 1.5,
    broker: str = "ibkr",
    account_type: str = "paper",
    **kwargs,
) -> AccountState:
    """创建模拟账户状态"""
    return AccountState(
        broker=broker,
        account_type=account_type,
        total_equity=total_equity,
        cash_balance=cash_balance,
        available_margin=available_margin,
        used_margin=used_margin,
        margin_utilization=margin_utilization,
        cash_ratio=cash_ratio,
        gross_leverage=gross_leverage,
        **kwargs,
    )


def create_mock_trading_result(
    success: bool = True,
    internal_order_id: str = "ORD-20250129-abc12345",
    broker_order_id: str = "IBKR-123456",
    broker_status: str = "Submitted",
    executed_quantity: int = 0,
    executed_price: float = 0,
    commission: float = 0,
    error_code: str | None = None,
    error_message: str | None = None,
) -> TradingResult:
    """创建模拟 TradingResult"""
    return TradingResult(
        success=success,
        internal_order_id=internal_order_id,
        broker_order_id=broker_order_id,
        broker_status=broker_status,
        executed_quantity=executed_quantity,
        executed_price=executed_price,
        commission=commission,
        error_code=error_code,
        error_message=error_message,
    )


def position_to_context(position: PositionData) -> PositionContext:
    """将 PositionData 转换为 PositionContext"""
    return PositionContext(
        position_id=position.position_id,
        symbol=position.symbol,
        underlying=position.underlying,
        option_type=position.option_type,
        strike=position.strike,
        expiry=position.expiry,
        dte=position.dte,
        quantity=position.quantity,
        avg_cost=abs(position.market_value / position.quantity) if position.quantity else 0,
        current_price=abs(position.market_value / position.quantity) if position.quantity else 0,
        market_value=position.market_value,
        unrealized_pnl=position.market_value * position.unrealized_pnl_pct if position.unrealized_pnl_pct else 0,
    )


# =============================================================================
# Mock TradingProvider
# =============================================================================

class MockTradingProvider:
    """Mock 交易提供者，用于测试"""

    def __init__(self, preset_results: dict[str, TradingResult] | None = None):
        self._preset_results = preset_results or {}
        self._submitted_orders: list[OrderRequest] = []

    def submit_order(self, order: OrderRequest) -> TradingResult:
        """提交订单并返回模拟结果"""
        self._submitted_orders.append(order)

        if order.order_id in self._preset_results:
            result = self._preset_results[order.order_id]
        elif "default" in self._preset_results:
            result = self._preset_results["default"]
        else:
            result = create_mock_trading_result(
                success=True,
                internal_order_id=order.order_id,
                broker_order_id=f"IBKR-{order.order_id[-8:]}",
                broker_status="Submitted",
            )

        return TradingResult(
            success=result.success,
            internal_order_id=order.order_id,
            broker_order_id=result.broker_order_id,
            broker_status=result.broker_status,
            executed_quantity=result.executed_quantity,
            executed_price=result.executed_price,
            commission=result.commission,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    @property
    def submitted_orders(self) -> list[OrderRequest]:
        return self._submitted_orders

    def reset(self) -> None:
        self._submitted_orders.clear()


# =============================================================================
# Pipeline Result
# =============================================================================

@dataclass
class PipelineResult:
    """完整链路执行结果"""
    test_case: TestCase
    positions: list[PositionData]
    alerts: list[Alert]
    suggestions: list[PositionSuggestion]
    decisions: list[TradingDecision]
    orders: list[OrderRequest]
    results: list[TradingResult]
    passed: bool
    errors: list[str]


# =============================================================================
# Pipeline Runner
# =============================================================================

def run_pipeline(test_case: TestCase) -> PipelineResult:
    """运行完整链路测试"""
    suggestion_gen = SuggestionGenerator()
    decision_engine = DecisionEngine()
    order_generator = OrderGenerator()
    trading_provider = MockTradingProvider(preset_results={
        "default": create_mock_trading_result(success=True, broker_status="Submitted")
    })

    errors = []

    # Step 1: Generate PositionSuggestion from Alert + Position
    monitor_result = MonitorResult(
        status=MonitorStatus.RED,
        alerts=test_case.alerts,
        positions=test_case.positions,
    )
    suggestions = suggestion_gen.generate(monitor_result, test_case.positions)

    # Validate suggestion count
    if len(suggestions) != test_case.expected_count:
        errors.append(f"Expected {test_case.expected_count} suggestions, got {len(suggestions)}")

    # Validate action
    if test_case.expected_action and suggestions:
        for s in suggestions:
            if s.action != test_case.expected_action:
                errors.append(f"Expected action {test_case.expected_action.value}, got {s.action.value}")

    # Validate urgency
    if test_case.expected_urgency and suggestions:
        for s in suggestions:
            if s.urgency != test_case.expected_urgency:
                errors.append(f"Expected urgency {test_case.expected_urgency.value}, got {s.urgency.value}")

    # Step 2 & 3: For each suggestion, generate Decision and Order
    account_state = create_mock_account_state()
    all_decisions = []
    all_orders = []
    all_results = []

    # Build position lookup for context
    position_map = {p.position_id: p for p in test_case.positions}

    for suggestion in suggestions:
        # Skip HOLD/MONITOR actions - they don't generate orders
        if suggestion.action in (ActionType.HOLD, ActionType.MONITOR, ActionType.REVIEW):
            # Still generate decision for tracking
            position_ctx = None
            if suggestion.position_id in position_map:
                position_ctx = position_to_context(position_map[suggestion.position_id])

            decision = decision_engine.process_monitor_signal(
                suggestion=suggestion,
                account_state=account_state,
                position_context=position_ctx,
            )
            all_decisions.append(decision)
            continue

        # Get position context
        position_ctx = None
        if suggestion.position_id in position_map:
            position_ctx = position_to_context(position_map[suggestion.position_id])

        # Step 2: Suggestion → Decision
        decision = decision_engine.process_monitor_signal(
            suggestion=suggestion,
            account_state=account_state,
            position_context=position_ctx,
        )
        all_decisions.append(decision)

        # Step 3: Decision → Order(s)
        if decision.decision_type == DecisionType.ROLL:
            try:
                orders = order_generator.generate_roll(decision)
            except ValueError as e:
                # ROLL without roll_to_expiry - skip order generation
                errors.append(f"ROLL decision missing parameters: {e}")
                continue
        elif decision.decision_type == DecisionType.HOLD:
            # HOLD doesn't generate orders
            continue
        else:
            orders = [order_generator.generate(decision)]

        all_orders.extend(orders)

        # Step 4: Order(s) → Result(s)
        for order in orders:
            result = trading_provider.submit_order(order)
            all_results.append(result)

    passed = len(errors) == 0

    return PipelineResult(
        test_case=test_case,
        positions=test_case.positions,
        alerts=test_case.alerts,
        suggestions=suggestions,
        decisions=all_decisions,
        orders=all_orders,
        results=all_results,
        passed=passed,
        errors=errors,
    )


# =============================================================================
# Pretty Printer
# =============================================================================

def print_pipeline_result(result: PipelineResult) -> None:
    """打印完整链路详细信息"""
    tc = result.test_case
    status = "✅ PASS" if result.passed else "❌ FAIL"

    print(f"\n{'='*90}")
    print(f"{status} {tc.name}")
    print(f"{'='*90}")
    print(f"📝 Description: {tc.description}")

    if result.errors:
        print(f"\n⚠️  Errors:")
        for err in result.errors:
            print(f"    - {err}")

    # 1. Positions
    print(f"\n{'─'*90}")
    print(f"【1. Position Data (持仓数据)】 - 共 {len(result.positions)} 个持仓")
    print(f"{'─'*90}")
    for i, pos in enumerate(result.positions, 1):
        strategy = pos.strategy_type.value if pos.strategy_type else "N/A"
        print(f"  [{i}] {pos.position_id} | {pos.symbol}")
        print(f"      strategy: {strategy} | qty: {pos.quantity} | strike: {pos.strike}")
        print(f"      dte: {pos.dte} | delta: {pos.delta:.2f} | theta: {pos.theta:.2f}")
        print(f"      gamma: {pos.gamma:.3f} | vega: {pos.vega:.2f} | margin: ${pos.margin:.0f}")
        print(f"      pnl%: {pos.unrealized_pnl_pct:.1%} | tgr: {pos.tgr:.2f}")

    # 2. Alerts
    print(f"\n{'─'*90}")
    print(f"【2. Triggered Alerts (触发的告警)】 - 共 {len(result.alerts)} 个")
    print(f"{'─'*90}")
    for i, alert in enumerate(result.alerts, 1):
        pos_info = f" | pos: {alert.position_id}" if alert.position_id else ""
        print(f"  [{i}] {alert.alert_type.value} | {alert.level.value}{pos_info}")
        print(f"      message: {alert.message}")
        print(f"      current: {alert.current_value} | threshold: {alert.threshold_value}")

    # 3. Suggestions
    print(f"\n{'─'*90}")
    print(f"【3. PositionSuggestion (调整建议)】 - 共 {len(result.suggestions)} 个")
    print(f"{'─'*90}")
    for i, s in enumerate(result.suggestions, 1):
        print(f"  [{i}] {s.position_id} | {s.symbol}")
        print(f"      action : {s.action.value}")
        print(f"      urgency: {s.urgency.value}")
        print(f"      reason : {s.reason[:70]}{'...' if len(s.reason) > 70 else ''}")
        if s.metadata:
            meta = s.metadata
            if meta.get("quantity"):
                print(f"      qty: {meta.get('quantity')} | strike: {meta.get('strike')} | expiry: {meta.get('expiry')}")

    # 4. Decisions
    print(f"\n{'─'*90}")
    print(f"【4. TradingDecision (交易决策)】 - 共 {len(result.decisions)} 个")
    print(f"{'─'*90}")
    for i, d in enumerate(result.decisions, 1):
        direction = "BUY" if d.quantity > 0 else "SELL" if d.quantity < 0 else "N/A"
        print(f"  [{i}] {d.decision_id[:25]}...")
        print(f"      type    : {d.decision_type.value} | priority: {d.priority.value}")
        print(f"      symbol  : {d.symbol}")
        print(f"      qty     : {d.quantity} ({direction}) | price_type: {d.price_type}")
        if d.roll_to_expiry:
            print(f"      → roll_to: {d.roll_to_expiry} K={d.roll_to_strike}")

    # 5. Orders
    print(f"\n{'─'*90}")
    print(f"【5. OrderRequest (订单请求)】 - 共 {len(result.orders)} 个")
    print(f"{'─'*90}")
    if not result.orders:
        print("  (无订单 - HOLD/MONITOR 类型不生成订单)")
    for i, order in enumerate(result.orders, 1):
        print(f"  [{i}] {order.order_id[:25]}...")
        print(f"      symbol : {order.symbol}")
        print(f"      side   : {order.side.value} | type: {order.order_type.value} | qty: {order.quantity}")
        if order.limit_price:
            print(f"      limit  : ${order.limit_price:.2f}")

    # 6. Results
    print(f"\n{'─'*90}")
    print(f"【6. TradingResult (交易结果)】 - 共 {len(result.results)} 个")
    print(f"{'─'*90}")
    if not result.results:
        print("  (无结果 - HOLD/MONITOR 类型不提交订单)")
    for i, tr in enumerate(result.results, 1):
        status_icon = "✅" if tr.success else "❌"
        print(f"  [{i}] {status_icon} {tr.broker_status}")
        print(f"      order_id: {tr.internal_order_id[:25]}...")
        print(f"      broker  : {tr.broker_order_id}")
        if tr.error_code:
            print(f"      error   : {tr.error_code} - {tr.error_message}")


def run_all_tests() -> bool:
    """运行所有端到端测试"""
    all_cases = [
        ("Capital 级", CAPITAL_TEST_CASES),
        ("Portfolio 级", PORTFOLIO_TEST_CASES),
        ("Position 级", POSITION_TEST_CASES),
    ]

    total = 0
    passed = 0
    failed = 0

    for category, cases in all_cases:
        print(f"\n\n{'#'*90}")
        print(f"#  {category} 测试")
        print(f"#  PositionData → Alert → Suggestion → Decision → Order → Result")
        print(f"{'#'*90}")

        for case in cases:
            result = run_pipeline(case)
            print_pipeline_result(result)

            total += 1
            if result.passed:
                passed += 1
            else:
                failed += 1

    # Summary
    print(f"\n\n{'='*90}")
    print("测试总结")
    print(f"{'='*90}")
    print(f"  Total : {total}")
    print(f"  Passed: {passed} ✅")
    print(f"  Failed: {failed} {'❌' if failed > 0 else ''}")
    print(f"  Pass Rate: {passed/total*100:.1f}%")
    print(f"{'='*90}")

    return failed == 0


# =============================================================================
# Pytest Tests
# =============================================================================

class TestCapitalPipeline:
    """Capital 级端到端测试"""

    @pytest.mark.parametrize("case", CAPITAL_TEST_CASES, ids=[c.name for c in CAPITAL_TEST_CASES])
    def test_capital_pipeline(self, case: TestCase) -> None:
        result = run_pipeline(case)
        assert result.passed, f"Failed: {result.errors}"


class TestPortfolioPipeline:
    """Portfolio 级端到端测试"""

    @pytest.mark.parametrize("case", PORTFOLIO_TEST_CASES, ids=[c.name for c in PORTFOLIO_TEST_CASES])
    def test_portfolio_pipeline(self, case: TestCase) -> None:
        result = run_pipeline(case)
        assert result.passed, f"Failed: {result.errors}"


class TestPositionPipeline:
    """Position 级端到端测试"""

    @pytest.mark.parametrize("case", POSITION_TEST_CASES, ids=[c.name for c in POSITION_TEST_CASES])
    def test_position_pipeline(self, case: TestCase) -> None:
        result = run_pipeline(case)
        assert result.passed, f"Failed: {result.errors}"


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--pytest":
        pytest.main([__file__, "-v", "--tb=short"])
    else:
        success = run_all_tests()
        exit(0 if success else 1)
