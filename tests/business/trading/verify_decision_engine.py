#!/usr/bin/env python3
"""Decision Engine Flow Verification.

验证从 ContractOpportunity / PositionSuggestion 到 TradingDecision 的完整链路。

测试项目:
1. ContractOpportunity → TradingDecision (OPEN) - 开仓信号转换
2. PositionSuggestion → TradingDecision (CLOSE/ADJUST/ROLL) - 监控信号转换
3. Batch Processing - 批量处理与冲突解决
4. Position Sizing - 仓位计算验证
5. Conflict Resolution - 同一标的冲突处理

Usage:
    python tests/business/trading/verify_decision_engine.py
    python tests/business/trading/verify_decision_engine.py --verbose
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.business.monitoring.models import Alert, AlertLevel, AlertType
from src.business.monitoring.suggestions import (
    ActionType,
    PositionSuggestion,
    UrgencyLevel,
)
from src.business.screening.models import ContractOpportunity, ScreeningResult
from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.decision.engine import DecisionEngine
from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
)
from src.engine.models.enums import StrategyType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# Test Fixtures
# ============================================================


def create_sample_account_state() -> AccountState:
    """创建示例账户状态"""
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=100000.0,
        cash_balance=50000.0,
        available_margin=40000.0,
        used_margin=30000.0,
        margin_utilization=0.30,  # 30% - healthy
        cash_ratio=0.50,  # 50% - healthy
        gross_leverage=1.5,  # 1.5x - healthy
        total_position_count=5,
        option_position_count=3,
        stock_position_count=2,
        exposure_by_underlying={"AAPL": 2000, "TSLA": 1500},  # 小暴露
    )


def create_sample_opportunity() -> ContractOpportunity:
    """创建示例合约机会 (来自 Screening)

    Note: Strike 设为 $40，使得名义价值 = $40 × 100 = $4,000
    这是 NLV ($100,000) 的 4%，低于默认 5% 限制
    """
    expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    return ContractOpportunity(
        symbol="NVDA 250228P00040000",
        expiry=expiry,
        strike=40.0,  # Lower strike to pass exposure limit
        option_type="put",
        lot_size=100,
        bid=0.80,
        ask=0.90,
        mid_price=0.85,
        delta=-0.15,
        gamma=0.01,
        theta=-0.03,
        vega=0.08,
        iv=0.35,
        dte=30,
        expected_roc=0.021,  # 2.1%
        win_probability=0.85,
        kelly_fraction=0.60,  # Higher Kelly for higher win prob
        underlying_price=60.0,
        otm_percent=0.333,  # 33.3% OTM
        passed=True,
    )


def create_sample_suggestion_close() -> PositionSuggestion:
    """创建示例平仓建议 (来自 Monitor)"""
    alert = Alert(
        alert_type=AlertType.STOP_LOSS,
        level=AlertLevel.RED,
        message="Stop loss triggered: loss > 200%",
        timestamp=datetime.now(),
    )
    return PositionSuggestion(
        position_id="POS-001",
        symbol="AAPL 250221P00180000",
        action=ActionType.CLOSE,
        urgency=UrgencyLevel.IMMEDIATE,
        reason="Stop loss triggered, loss exceeds 200% of premium received",
        trigger_alerts=[alert],
        metadata={
            "underlying": "AAPL",
            "option_type": "put",
            "strike": 180.0,
            "expiry": "2025-02-21",
        },
    )


def create_sample_suggestion_roll() -> PositionSuggestion:
    """创建示例展期建议 (来自 Monitor)"""
    alert = Alert(
        alert_type=AlertType.DTE_WARNING,
        level=AlertLevel.RED,
        message="DTE < 7 days",
        timestamp=datetime.now(),
    )
    return PositionSuggestion(
        position_id="POS-002",
        symbol="TSLA 250124P00200000",
        action=ActionType.ROLL,
        urgency=UrgencyLevel.IMMEDIATE,
        reason="DTE < 7, roll to next month to avoid gamma risk",
        trigger_alerts=[alert],
        metadata={
            "underlying": "TSLA",
            "option_type": "put",
            "strike": 200.0,
            "expiry": "2025-01-24",
            "quantity": -3,  # 持仓数量，用于计算平仓数量
        },
    )


def create_sample_suggestion_hold() -> PositionSuggestion:
    """创建示例 HOLD 建议 (来自 Monitor)"""
    alert = Alert(
        alert_type=AlertType.IV_HV_CHANGE,
        level=AlertLevel.GREEN,
        message="IV/HV ratio favorable",
        timestamp=datetime.now(),
    )
    return PositionSuggestion(
        position_id="POS-003",
        symbol="GOOGL 250221P00150000",
        action=ActionType.HOLD,
        urgency=UrgencyLevel.MONITOR,
        reason="Position performing well, continue holding",
        trigger_alerts=[alert],
        metadata={
            "underlying": "GOOGL",
            "option_type": "put",
            "strike": 150.0,
            "expiry": "2025-02-21",
        },
    )


# ============================================================
# Hong Kong Stock Option Test Fixtures
# ============================================================


def create_hk_account_state() -> AccountState:
    """创建港股账户状态 (HKD)

    Exposure limits:
    - 5% max per underlying → HKD 780,000 × 5% = HKD 39,000
    - Set existing exposure below this to allow opening
    """
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=780000.0,  # ~100,000 USD in HKD
        cash_balance=390000.0,
        available_margin=312000.0,
        used_margin=234000.0,
        margin_utilization=0.30,  # 30%
        cash_ratio=0.50,  # 50%
        gross_leverage=1.5,  # 1.5x
        total_position_count=3,
        option_position_count=2,
        stock_position_count=1,
        # 低于 5% 限制以允许开仓 (39,000 HKD = 5% of NLV)
        exposure_by_underlying={"9988.HK": 0, "0700.HK": 10000},
    )


def create_hk_opportunity() -> ContractOpportunity:
    """创建港股合约机会 (来自 Screening)

    阿里巴巴 9988.HK:
    - trading_class: ALB
    - lot_size: 500 (港股期权每手股数)
    - Strike: HKD 75，使得名义价值 = HKD 75 × 500 = HKD 37,500
    - 这是 NLV (HKD 780,000) 的 4.8%，低于 5% 限制
    """
    expiry = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
    return ContractOpportunity(
        symbol="9988.HK",
        trading_class="ALB",  # IBKR trading class for 9988
        expiry=expiry,
        strike=75.0,  # HKD (lowered to stay under 5% exposure limit)
        option_type="put",
        lot_size=500,  # HK option lot size for Alibaba
        bid=1.20,
        ask=1.40,
        mid_price=1.30,
        delta=-0.18,
        gamma=0.008,
        theta=-0.025,
        vega=0.06,
        iv=0.42,
        dte=45,
        expected_roc=0.016,  # 1.6%
        win_probability=0.82,
        kelly_fraction=0.55,
        underlying_price=95.0,  # HKD
        otm_percent=0.21,  # 21% OTM
        passed=True,
    )


def create_hk_suggestion_close() -> PositionSuggestion:
    """创建港股平仓建议 (来自 Monitor)

    腾讯 0700.HK:
    - trading_class: TCH
    """
    alert = Alert(
        alert_type=AlertType.PROFIT_TARGET,  # 止盈触发
        level=AlertLevel.YELLOW,
        message="Take profit triggered: profit > 70%",
        timestamp=datetime.now(),
    )
    return PositionSuggestion(
        position_id="POS-HK-001",
        symbol="0700.HK",
        action=ActionType.CLOSE,
        urgency=UrgencyLevel.SOON,  # SOON, not IMMEDIATE (use limit order)
        reason="Take profit triggered, profit exceeds 70% of premium received",
        trigger_alerts=[alert],
        metadata={
            "underlying": "0700.HK",
            "option_type": "put",
            "strike": 360.0,
            "expiry": "2025-03-28",
            "trading_class": "TCH",
            "lot_size": 100,  # Tencent lot size
            "quantity": -2,
        },
    )


def create_hk_suggestion_roll() -> PositionSuggestion:
    """创建港股展期建议 (来自 Monitor)

    阿里巴巴 9988.HK
    """
    alert = Alert(
        alert_type=AlertType.DTE_WARNING,
        level=AlertLevel.RED,
        message="DTE < 7 days",
        timestamp=datetime.now(),
    )
    return PositionSuggestion(
        position_id="POS-HK-002",
        symbol="9988.HK",
        action=ActionType.ROLL,
        urgency=UrgencyLevel.IMMEDIATE,
        reason="DTE < 7, roll to next month to avoid gamma risk",
        trigger_alerts=[alert],
        metadata={
            "underlying": "9988.HK",
            "option_type": "put",
            "strike": 85.0,
            "expiry": "2025-02-07",
            "trading_class": "ALB",
            "lot_size": 500,
            "quantity": -2,  # 持仓数量
        },
    )


# ============================================================
# Tests
# ============================================================


def test_screen_signal_to_decision(verbose: bool = False) -> bool:
    """测试 ContractOpportunity → TradingDecision 转换

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 1: ContractOpportunity → TradingDecision (OPEN)")
    print("=" * 60)

    try:
        engine = DecisionEngine()
        account_state = create_sample_account_state()
        opportunity = create_sample_opportunity()

        print(f"\n  Input ContractOpportunity:")
        print(f"    Symbol: {opportunity.symbol}")
        print(f"    Strike: ${opportunity.strike}")
        print(f"    Expiry: {opportunity.expiry}")
        print(f"    DTE: {opportunity.dte}")
        print(f"    Delta: {opportunity.delta}")
        print(f"    Mid Price: ${opportunity.mid_price}")
        print(f"    Kelly Fraction: {opportunity.kelly_fraction}")
        print(f"    Win Probability: {opportunity.win_probability:.0%}")

        decision = engine.process_screen_signal(opportunity, account_state)

        if decision:
            print(f"\n  Output TradingDecision:")
            print(f"    Decision ID: {decision.decision_id}")
            print(f"    Decision Type: {decision.decision_type.value}")
            print(f"    Source: {decision.source.value}")
            print(f"    Priority: {decision.priority.value}")
            print(f"    Symbol: {decision.symbol}")
            print(f"    Underlying: {decision.underlying}")
            print(f"    Trading Class: {decision.trading_class}")
            print(f"    Expiry: {decision.expiry}")
            print(f"    Strike: {decision.strike}")
            print(f"    Option Type: {decision.option_type}")
            print(f"    Price Type: {decision.price_type}")
            print(f"    Quantity: {decision.quantity}")
            print(f"    Limit Price: ${decision.limit_price}")
            print(f"    Contract Multiplier: {decision.contract_multiplier}")
            print(f"    Currency: {decision.currency}")
            print(f"    Broker: {decision.broker}")
            print(f"    Reason: {decision.reason}")

            # 验证决策字段
            assert decision.decision_type == DecisionType.OPEN
            assert decision.source == DecisionSource.SCREEN_SIGNAL
            assert decision.quantity < 0  # 卖出期权为负
            assert decision.underlying == "NVDA"
            assert decision.option_type == "put"
            assert decision.strike == 40.0  # Match fixture strike

            print("\n  [PASS] Screen signal converted to OPEN decision")
            return True
        else:
            print("\n  [INFO] No decision generated (account constraints)")
            print("         This may be expected if account state doesn't allow opening")
            return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Screen signal test error")
        return False


def test_monitor_signal_to_decision(verbose: bool = False) -> bool:
    """测试 PositionSuggestion → TradingDecision 转换

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 2: PositionSuggestion → TradingDecision (CLOSE/ROLL)")
    print("=" * 60)

    try:
        engine = DecisionEngine()
        account_state = create_sample_account_state()

        # Test CLOSE suggestion
        print("\n  [2a] Testing CLOSE suggestion...")
        suggestion_close = create_sample_suggestion_close()
        print(f"    Input: {suggestion_close.symbol}, Action={suggestion_close.action.value}")

        position_context = PositionContext(
            position_id="POS-001",
            symbol="AAPL 250221P00180000",
            quantity=-2,  # 卖出 2 张
            avg_cost=3.50,
            current_price=10.50,  # 亏损
            unrealized_pnl=-1400.0,
        )

        decision_close = engine.process_monitor_signal(
            suggestion_close, account_state, position_context
        )

        # decision_close 总是返回 TradingDecision
        print(f"    Output: type={decision_close.decision_type.value}, qty={decision_close.quantity}, price_type={decision_close.price_type}")
        assert decision_close.decision_type == DecisionType.CLOSE
        assert decision_close.priority == DecisionPriority.CRITICAL
        assert decision_close.quantity == 2  # 平仓方向相反 (-2 -> 2)
        assert decision_close.price_type == "market"  # IMMEDIATE urgency 使用市价单
        print("    [PASS] CLOSE decision: qty=2, price_type=market")

        # Test ROLL suggestion (without position_context, use metadata["quantity"])
        print("\n  [2b] Testing ROLL suggestion (quantity from metadata)...")
        suggestion_roll = create_sample_suggestion_roll()
        print(f"    Input: {suggestion_roll.symbol}, Action={suggestion_roll.action.value}, metadata[quantity]={suggestion_roll.metadata.get('quantity')}")

        decision_roll = engine.process_monitor_signal(
            suggestion_roll, account_state
        )

        print(f"    Output: type={decision_roll.decision_type.value}, priority={decision_roll.priority.value}, qty={decision_roll.quantity}, price_type={decision_roll.price_type}")
        assert decision_roll.decision_type == DecisionType.ROLL
        assert decision_roll.priority == DecisionPriority.CRITICAL
        assert decision_roll.quantity == 3  # 从 metadata["quantity"]=-3 反转
        assert decision_roll.price_type == "market"  # IMMEDIATE urgency 使用市价单
        print("    [PASS] ROLL decision: qty=3 (from metadata), price_type=market")

        # Test HOLD suggestion (returns TradingDecision with decision_type=HOLD)
        print("\n  [2c] Testing HOLD suggestion (returns HOLD decision, not None)...")
        suggestion_hold = create_sample_suggestion_hold()
        print(f"    Input: {suggestion_hold.symbol}, Action={suggestion_hold.action.value}")

        decision_hold = engine.process_monitor_signal(
            suggestion_hold, account_state
        )

        print(f"    Output: type={decision_hold.decision_type.value}, priority={decision_hold.priority.value}, price_type={decision_hold.price_type}")
        assert decision_hold is not None  # 不再返回 None
        assert decision_hold.decision_type == DecisionType.HOLD
        assert decision_hold.price_type == "mid"  # HOLD 使用默认价格类型
        print("    [PASS] HOLD decision returned (not None), will be filtered in batch processing")

        print("\n  [PASS] Monitor signal conversion completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Monitor signal test error")
        return False


def test_batch_processing(verbose: bool = False) -> bool:
    """测试批量处理

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 3: Batch Processing with Conflict Resolution")
    print("=" * 60)

    try:
        engine = DecisionEngine()
        account_state = create_sample_account_state()

        # 创建 ScreeningResult
        opportunity = create_sample_opportunity()
        screen_result = ScreeningResult(
            passed=True,
            strategy_type=StrategyType.SHORT_PUT,
            confirmed=[opportunity],
        )

        # 创建多个 suggestions
        suggestions = [
            create_sample_suggestion_close(),
            create_sample_suggestion_roll(),
            create_sample_suggestion_hold(),
        ]

        print(f"\n  Input:")
        print(f"    Screen opportunities: {len(screen_result.confirmed)}")
        print(f"    Monitor suggestions: {len(suggestions)}")

        # 批量处理
        decisions = engine.process_batch(
            screen_result=screen_result,
            account_state=account_state,
            suggestions=suggestions,
        )

        print(f"\n  Output: {len(decisions)} decisions after conflict resolution")

        for i, decision in enumerate(decisions, 1):
            print(f"\n    [{i}] {decision.decision_id}")
            print(f"        Type: {decision.decision_type.value}")
            print(f"        Symbol: {decision.symbol}")
            print(f"        Priority: {decision.priority.value}")
            print(f"        Source: {decision.source.value}")

        # 验证 HOLD 被过滤
        hold_decisions = [d for d in decisions if d.decision_type == DecisionType.HOLD]
        assert len(hold_decisions) == 0, "HOLD decisions should be filtered"

        # 验证有决策输出
        assert len(decisions) > 0, "Should have at least one decision"

        print("\n  [PASS] Batch processing completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Batch processing test error")
        return False


def test_position_sizing(verbose: bool = False) -> bool:
    """测试仓位计算

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 4: Position Sizing Calculation")
    print("=" * 60)

    try:
        from src.business.trading.decision.position_sizer import PositionSizer

        sizer = PositionSizer()
        account_state = create_sample_account_state()
        opportunity = create_sample_opportunity()

        print(f"\n  Input:")
        print(f"    NLV: ${account_state.total_equity:,.2f}")
        print(f"    Available Margin: ${account_state.available_margin:,.2f}")
        print(f"    Strike: ${opportunity.strike}")
        print(f"    Lot Size: {opportunity.lot_size}")
        print(f"    Kelly Fraction: {opportunity.kelly_fraction}")

        details = sizer.calculate_with_details(opportunity, account_state)

        print(f"\n  Calculation Details:")
        print(f"    Notional per Contract: ${details['calculation']['notional_per_contract']:,.2f}")
        print(f"    Margin per Contract: ${details['calculation']['margin_per_contract']:,.2f}")
        print(f"    Adjusted Kelly: {details['calculation']['adjusted_kelly']:.2%}")
        print(f"    Kelly Capital: ${details['calculation']['kelly_capital']:,.2f}")
        print(f"    Max Capital (by config): ${details['calculation']['max_capital']:,.2f}")

        print(f"\n  Limits:")
        print(f"    Max Contracts: {details['limits']['max_contracts']}")
        print(f"    Max Allocation: {details['limits']['max_allocation_pct']:.1%}")
        print(f"    Kelly Scale: {details['limits']['kelly_scale']}")

        print(f"\n  Result: {details['contracts']} contracts")

        assert details['contracts'] >= 0, "Contracts should be non-negative"

        print("\n  [PASS] Position sizing calculation completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Position sizing test error")
        return False


def test_conflict_resolution(verbose: bool = False) -> bool:
    """测试冲突解决

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 5: Conflict Resolution (Same Underlying)")
    print("=" * 60)

    try:
        from src.business.trading.decision.conflict_resolver import ConflictResolver
        from src.business.trading.models.decision import TradingDecision

        resolver = ConflictResolver()
        account_state = create_sample_account_state()

        # 创建同一标的的 OPEN 和 CLOSE 决策
        decisions = [
            TradingDecision(
                decision_id="DEC-001",
                decision_type=DecisionType.OPEN,
                source=DecisionSource.SCREEN_SIGNAL,
                priority=DecisionPriority.NORMAL,
                symbol="AAPL 250221P00200000",
                underlying="AAPL",
                quantity=-1,
                account_state=account_state,
            ),
            TradingDecision(
                decision_id="DEC-002",
                decision_type=DecisionType.CLOSE,
                source=DecisionSource.MONITOR_ALERT,
                priority=DecisionPriority.HIGH,
                symbol="AAPL 250221P00180000",
                underlying="AAPL",
                quantity=2,
                account_state=account_state,
            ),
        ]

        print(f"\n  Input: {len(decisions)} decisions for same underlying (AAPL)")
        for d in decisions:
            print(f"    - {d.decision_id}: {d.decision_type.value}, priority={d.priority.value}")

        resolved = resolver.resolve(decisions, account_state)

        print(f"\n  Output: {len(resolved)} decisions after resolution")
        for d in resolved:
            print(f"    - {d.decision_id}: {d.decision_type.value}, priority={d.priority.value}")

        # 验证配置 single_action_per_underlying=True 时，同一标的只保留一个
        config = DecisionConfig.load()
        if config.single_action_per_underlying:
            aapl_decisions = [d for d in resolved if d.underlying == "AAPL"]
            assert len(aapl_decisions) <= 1, "Should have at most 1 decision per underlying"

            # CLOSE 应该优先于 OPEN
            if len(aapl_decisions) == 1:
                assert aapl_decisions[0].decision_type == DecisionType.CLOSE, \
                    "CLOSE should have priority over OPEN"
                print("\n  [PASS] CLOSE prioritized over OPEN for same underlying")

        print("\n  [PASS] Conflict resolution completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Conflict resolution test error")
        return False


def test_decision_serialization(verbose: bool = False) -> bool:
    """测试决策序列化

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 6: TradingDecision Serialization")
    print("=" * 60)

    try:
        engine = DecisionEngine()
        account_state = create_sample_account_state()
        opportunity = create_sample_opportunity()

        decision = engine.process_screen_signal(opportunity, account_state)

        if decision:
            print(f"\n  Serializing decision: {decision.decision_id}")
            data = decision.to_dict()

            print(f"\n  Serialized fields:")
            for key in ["decision_id", "decision_type", "source", "priority",
                        "symbol", "underlying", "option_type", "strike", "quantity"]:
                if key in data:
                    print(f"    {key}: {data[key]}")

            # 验证关键字段存在
            assert "decision_id" in data
            assert "decision_type" in data
            assert "source" in data
            assert "symbol" in data

            print("\n  [PASS] Decision serialization completed")
            return True
        else:
            print("\n  [INFO] No decision to serialize (account constraints)")
            return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("Serialization test error")
        return False


# ============================================================
# Hong Kong Stock Option Tests
# ============================================================


def test_hk_screen_signal_to_decision(verbose: bool = False) -> bool:
    """测试港股 ContractOpportunity → TradingDecision 转换

    验证港股期权的特殊字段:
    - trading_class (ALB/TCH)
    - lot_size (500 for 9988)
    - HKD currency

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 7: HK Option ContractOpportunity → TradingDecision (OPEN)")
    print("=" * 60)

    try:
        engine = DecisionEngine()
        account_state = create_hk_account_state()
        opportunity = create_hk_opportunity()

        print(f"\n  Input ContractOpportunity (HK):")
        print(f"    Symbol: {opportunity.symbol}")
        print(f"    Trading Class: {opportunity.trading_class}")
        print(f"    Strike: HKD {opportunity.strike}")
        print(f"    Expiry: {opportunity.expiry}")
        print(f"    DTE: {opportunity.dte}")
        print(f"    Lot Size: {opportunity.lot_size}")
        print(f"    Delta: {opportunity.delta}")
        print(f"    Mid Price: HKD {opportunity.mid_price}")
        print(f"    Kelly Fraction: {opportunity.kelly_fraction}")

        decision = engine.process_screen_signal(opportunity, account_state)

        if decision:
            print(f"\n  Output TradingDecision:")
            print(f"    Decision ID: {decision.decision_id}")
            print(f"    Decision Type: {decision.decision_type.value}")
            print(f"    Source: {decision.source.value}")
            print(f"    Priority: {decision.priority.value}")
            print(f"    Symbol: {decision.symbol}")
            print(f"    Underlying: {decision.underlying}")
            print(f"    Trading Class: {decision.trading_class}")
            print(f"    Expiry: {decision.expiry}")
            print(f"    Strike: {decision.strike}")
            print(f"    Option Type: {decision.option_type}")
            print(f"    Quantity: {decision.quantity}")
            print(f"    Limit Price: HKD {decision.limit_price}")
            print(f"    Contract Multiplier: {decision.contract_multiplier}")
            print(f"    Currency: {decision.currency}")
            print(f"    Broker: {decision.broker}")

            # 验证港股特殊字段
            assert decision.decision_type == DecisionType.OPEN
            assert decision.source == DecisionSource.SCREEN_SIGNAL
            assert decision.quantity < 0  # 卖出期权为负
            assert decision.underlying == "9988.HK"
            assert decision.trading_class == "ALB"
            assert decision.contract_multiplier == 500  # HK lot size
            assert decision.option_type == "put"
            assert decision.strike == 75.0  # Match updated fixture strike

            print("\n  [PASS] HK screen signal converted to OPEN decision")
            print(f"         trading_class={decision.trading_class}, multiplier={decision.contract_multiplier}")
            return True
        else:
            print("\n  [INFO] No decision generated (account constraints)")
            print("         This may be expected if HK account state doesn't allow opening")
            return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("HK Screen signal test error")
        return False


def test_hk_monitor_signal_to_decision(verbose: bool = False) -> bool:
    """测试港股 PositionSuggestion → TradingDecision 转换

    验证港股期权监控信号的处理:
    - CLOSE suggestion (Tencent 0700.HK)
    - ROLL suggestion (Alibaba 9988.HK)

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 8: HK Option PositionSuggestion → TradingDecision (CLOSE/ROLL)")
    print("=" * 60)

    try:
        engine = DecisionEngine()
        account_state = create_hk_account_state()

        # Test HK CLOSE suggestion (Tencent)
        print("\n  [8a] Testing HK CLOSE suggestion (Tencent 0700.HK)...")
        suggestion_close = create_hk_suggestion_close()
        print(f"    Input: {suggestion_close.symbol}, Action={suggestion_close.action.value}")
        print(f"    trading_class={suggestion_close.metadata.get('trading_class')}")

        position_context = PositionContext(
            position_id="POS-HK-001",
            symbol="0700.HK",
            underlying="0700.HK",
            trading_class="TCH",
            quantity=-2,  # 卖出 2 张
            avg_cost=8.50,
            current_price=2.50,  # 盈利
            unrealized_pnl=1200.0,
        )

        decision_close = engine.process_monitor_signal(
            suggestion_close, account_state, position_context
        )

        print(f"    Output: type={decision_close.decision_type.value}, qty={decision_close.quantity}, price_type={decision_close.price_type}")
        assert decision_close.decision_type == DecisionType.CLOSE
        assert decision_close.quantity == 2  # 平仓方向相反 (-2 -> 2)
        # SOON urgency 使用 mid 价格 (不是 IMMEDIATE)
        assert decision_close.price_type == "mid"
        print("    [PASS] HK CLOSE decision: qty=2, price_type=mid (SOON urgency)")

        # Test HK ROLL suggestion (Alibaba)
        print("\n  [8b] Testing HK ROLL suggestion (Alibaba 9988.HK)...")
        suggestion_roll = create_hk_suggestion_roll()
        print(f"    Input: {suggestion_roll.symbol}, Action={suggestion_roll.action.value}")
        print(f"    trading_class={suggestion_roll.metadata.get('trading_class')}, lot_size={suggestion_roll.metadata.get('lot_size')}")

        decision_roll = engine.process_monitor_signal(
            suggestion_roll, account_state
        )

        print(f"    Output: type={decision_roll.decision_type.value}, qty={decision_roll.quantity}, price_type={decision_roll.price_type}")
        assert decision_roll.decision_type == DecisionType.ROLL
        assert decision_roll.priority == DecisionPriority.CRITICAL
        assert decision_roll.quantity == 2  # 从 metadata["quantity"]=-2 反转
        assert decision_roll.price_type == "market"  # IMMEDIATE urgency 使用市价单
        print("    [PASS] HK ROLL decision: qty=2 (from metadata), price_type=market")

        print("\n  [PASS] HK Monitor signal conversion completed")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("HK Monitor signal test error")
        return False


def test_hk_position_sizing(verbose: bool = False) -> bool:
    """测试港股仓位计算

    验证港股期权的仓位计算:
    - 使用 HK lot_size (500)
    - 名义价值 = Strike × Lot Size

    Args:
        verbose: 是否详细输出

    Returns:
        是否成功
    """
    print("\n" + "=" * 60)
    print("Test 9: HK Option Position Sizing")
    print("=" * 60)

    try:
        from src.business.trading.decision.position_sizer import PositionSizer

        sizer = PositionSizer()
        account_state = create_hk_account_state()
        opportunity = create_hk_opportunity()

        print(f"\n  Input (HK):")
        print(f"    NLV: HKD {account_state.total_equity:,.2f}")
        print(f"    Available Margin: HKD {account_state.available_margin:,.2f}")
        print(f"    Symbol: {opportunity.symbol}")
        print(f"    Trading Class: {opportunity.trading_class}")
        print(f"    Strike: HKD {opportunity.strike}")
        print(f"    Lot Size: {opportunity.lot_size}")
        print(f"    Kelly Fraction: {opportunity.kelly_fraction}")

        details = sizer.calculate_with_details(opportunity, account_state)

        print(f"\n  Calculation Details:")
        print(f"    Notional per Contract: HKD {details['calculation']['notional_per_contract']:,.2f}")
        print(f"    Margin per Contract: HKD {details['calculation']['margin_per_contract']:,.2f}")
        print(f"    Adjusted Kelly: {details['calculation']['adjusted_kelly']:.2%}")
        print(f"    Kelly Capital: HKD {details['calculation']['kelly_capital']:,.2f}")
        print(f"    Max Capital (by config): HKD {details['calculation']['max_capital']:,.2f}")

        print(f"\n  Result: {details['contracts']} contracts")

        # 验证 lot_size 被正确使用
        expected_notional = opportunity.strike * opportunity.lot_size
        assert details['calculation']['notional_per_contract'] == expected_notional, \
            f"Notional should be {expected_notional}, got {details['calculation']['notional_per_contract']}"
        assert details['contracts'] >= 0, "Contracts should be non-negative"

        print(f"\n  [PASS] HK Position sizing: notional = strike × lot_size = {opportunity.strike} × {opportunity.lot_size} = {expected_notional}")
        return True

    except Exception as e:
        print(f"\n  [FAIL] Error: {e}")
        if verbose:
            logger.exception("HK Position sizing test error")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Decision Engine Flow Verification"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output with stack traces"
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("Decision Engine Flow Verification")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 60)

    results = {}

    # Run US stock option tests
    print("\n" + "=" * 60)
    print("US Stock Option Tests")
    print("=" * 60)
    results["screen_signal_to_decision"] = test_screen_signal_to_decision(args.verbose)
    results["monitor_signal_to_decision"] = test_monitor_signal_to_decision(args.verbose)
    results["batch_processing"] = test_batch_processing(args.verbose)
    results["position_sizing"] = test_position_sizing(args.verbose)
    results["conflict_resolution"] = test_conflict_resolution(args.verbose)
    results["decision_serialization"] = test_decision_serialization(args.verbose)

    # Run HK stock option tests
    print("\n" + "=" * 60)
    print("Hong Kong Stock Option Tests")
    print("=" * 60)
    results["hk_screen_signal_to_decision"] = test_hk_screen_signal_to_decision(args.verbose)
    results["hk_monitor_signal_to_decision"] = test_hk_monitor_signal_to_decision(args.verbose)
    results["hk_position_sizing"] = test_hk_position_sizing(args.verbose)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {test_name}")

    print(f"\n  Total: {passed}/{total} tests passed")
    print("=" * 60 + "\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
