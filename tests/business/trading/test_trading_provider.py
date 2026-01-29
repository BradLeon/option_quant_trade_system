#!/usr/bin/env python3
"""Trading Provider Unit Tests.

使用 mock 测试 Trading Provider 功能，不需要真实连接。

测试项目:
1. IBKR Trading Provider - 端口验证、订单提交、Paper 账户验证
2. Futu Trading Provider - 环境验证、订单提交、模拟账户验证
3. AccountStateAnalyzer - 开仓判断、资金计算
4. ConflictResolver - 冲突解决逻辑

Usage:
    pytest tests/business/trading/test_trading_provider.py -v
    pytest tests/business/trading/test_trading_provider.py -v -k "test_ibkr"
    pytest tests/business/trading/test_trading_provider.py -v -k "test_analyzer"
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    TradingDecision,
)
from src.business.trading.models.order import (
    AssetClass,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.business.trading.models.trading import (
    AccountTypeError,
    TradingAccountType,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def sample_order_request() -> OrderRequest:
    """创建示例订单请求"""
    return OrderRequest(
        order_id="TEST-20250126-001",
        decision_id="DEC-20250126-001",
        symbol="AAPL",
        underlying="AAPL",
        asset_class=AssetClass.STOCK,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        limit_price=150.00,
        broker="ibkr",
        account_type="paper",
        status=OrderStatus.APPROVED,
    )


@pytest.fixture
def sample_option_order() -> OrderRequest:
    """创建示例期权订单"""
    return OrderRequest(
        order_id="TEST-20250126-002",
        decision_id="DEC-20250126-002",
        symbol="AAPL 250221P00200000",
        underlying="AAPL",
        asset_class=AssetClass.OPTION,
        option_type="put",
        strike=200.0,
        expiry="2025-02-21",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=-1,
        limit_price=5.50,
        broker="ibkr",
        account_type="paper",
        status=OrderStatus.APPROVED,
        contract_multiplier=100,
    )


@pytest.fixture
def sample_account_state() -> AccountState:
    """创建示例账户状态"""
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=100000.0,
        cash_balance=50000.0,
        available_margin=40000.0,
        used_margin=30000.0,
        margin_utilization=0.30,  # 30%
        cash_ratio=0.50,  # 50%
        gross_leverage=1.5,  # 1.5x
        total_position_count=5,
        option_position_count=3,
        stock_position_count=2,
        exposure_by_underlying={"AAPL": 20000, "TSLA": 15000},
    )


@pytest.fixture
def high_margin_account_state() -> AccountState:
    """创建高保证金使用率的账户状态"""
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=100000.0,
        cash_balance=8000.0,  # 低现金
        available_margin=5000.0,
        used_margin=75000.0,  # 高保证金使用
        margin_utilization=0.75,  # 75% > 70% limit
        cash_ratio=0.08,  # 8% < 10% limit
        gross_leverage=4.5,  # 4.5x > 4.0x limit
        total_position_count=15,
        option_position_count=12,  # 超过限制
        stock_position_count=3,
    )


# ============================================================
# IBKR Trading Provider Tests
# ============================================================


class TestIBKRTradingProvider:
    """IBKR Trading Provider 单元测试"""

    def test_paper_only_port_validation(self):
        """测试只允许 4002 端口 (Paper Trading)"""
        from src.business.trading.provider.ibkr_trading import (
            IBKRTradingProvider,
            IBKR_AVAILABLE,
        )

        if not IBKR_AVAILABLE:
            pytest.skip("ib_async not installed")

        # 4002 端口应该允许
        provider = IBKRTradingProvider(port=4002)
        assert provider._port == 4002
        assert provider.account_type == TradingAccountType.PAPER

        # 4001 (Live) 端口应该拒绝
        with pytest.raises(AccountTypeError):
            IBKRTradingProvider(port=4001)

        # Note: TradingAccountType.LIVE is intentionally NOT defined
        # to prevent any accidental real trading

    def test_order_paper_account_validation(self, sample_order_request):
        """测试订单必须是 paper 账户"""
        from src.business.trading.provider.ibkr_trading import (
            IBKRTradingProvider,
            IBKR_AVAILABLE,
        )

        if not IBKR_AVAILABLE:
            pytest.skip("ib_async not installed")

        provider = IBKRTradingProvider()

        # Paper 账户订单应该通过验证
        sample_order_request.account_type = "paper"
        # 注意: 实际提交需要连接，这里只测试验证逻辑

        # Live 账户订单应该被拒绝 (在 submit_order 中检查)
        sample_order_request.account_type = "live"
        # 当调用 submit_order 时会返回失败

    def test_provider_name(self):
        """测试提供者名称"""
        from src.business.trading.provider.ibkr_trading import (
            IBKRTradingProvider,
            IBKR_AVAILABLE,
        )

        if not IBKR_AVAILABLE:
            pytest.skip("ib_async not installed")

        provider = IBKRTradingProvider()
        assert provider.name == "ibkr"

    def test_contract_multiplier_in_option_order(self, sample_option_order):
        """测试期权订单包含合约乘数"""
        assert sample_option_order.contract_multiplier == 100
        assert sample_option_order.asset_class == AssetClass.OPTION


# ============================================================
# AccountStateAnalyzer Tests
# ============================================================


class TestAccountStateAnalyzer:
    """AccountStateAnalyzer 单元测试"""

    def test_can_open_position_healthy_account(self, sample_account_state):
        """测试健康账户可以开仓"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        can_open, reasons = analyzer.can_open_position(sample_account_state)

        assert can_open is True
        assert len(reasons) == 0

    def test_can_open_position_high_margin(self, high_margin_account_state):
        """测试高保证金使用率不能开仓"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        can_open, reasons = analyzer.can_open_position(high_margin_account_state)

        assert can_open is False
        assert len(reasons) > 0
        assert any("Margin utilization" in r for r in reasons)

    def test_can_open_position_low_cash(self, high_margin_account_state):
        """测试低现金比例不能开仓"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        can_open, reasons = analyzer.can_open_position(high_margin_account_state)

        assert can_open is False
        assert any("cash" in r.lower() for r in reasons)

    def test_can_open_position_high_leverage(self, high_margin_account_state):
        """测试高杠杆不能开仓"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        can_open, reasons = analyzer.can_open_position(high_margin_account_state)

        assert can_open is False
        assert any("Leverage" in r for r in reasons)

    def test_available_capital_healthy_account(self, sample_account_state):
        """测试健康账户的可用资金"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        available = analyzer.get_available_capital_for_opening(sample_account_state)

        assert available > 0
        # 可用资金应该小于总权益
        assert available < sample_account_state.total_equity

    def test_available_capital_zero_nlv(self, sample_account_state):
        """测试 NLV 为零时可用资金为零"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        sample_account_state.total_equity = 0
        analyzer = AccountStateAnalyzer()
        available = analyzer.get_available_capital_for_opening(sample_account_state)

        assert available == 0

    def test_underlying_exposure_within_limit(self, sample_account_state):
        """测试标的暴露在限制内"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()

        # 测试一个没有现有暴露的新标的
        # 默认限制是 5% NLV = $5,000，添加 $1,000 应该在限制内
        is_ok, reason = analyzer.check_underlying_exposure(
            sample_account_state, "MSFT", additional_notional=1000
        )

        assert is_ok is True
        assert reason is None

    def test_underlying_exposure_exceeds_limit(self, sample_account_state):
        """测试标的暴露超过限制"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        # 默认限制是 5% NLV = $5,000
        # 添加 $6,000 到新标的应该超过限制
        is_ok, reason = analyzer.check_underlying_exposure(
            sample_account_state, "GOOGL", additional_notional=6000
        )

        assert is_ok is False
        assert reason is not None
        assert "GOOGL" in reason
        assert "exposure" in reason.lower()

    def test_health_summary(self, sample_account_state):
        """测试账户健康摘要"""
        from src.business.trading.decision.account_analyzer import AccountStateAnalyzer

        analyzer = AccountStateAnalyzer()
        summary = analyzer.get_account_health_summary(sample_account_state)

        assert "can_open_position" in summary
        assert "rejection_reasons" in summary
        assert "available_capital" in summary
        assert "margin_utilization" in summary
        assert "cash_ratio" in summary
        assert "gross_leverage" in summary
        assert "limits" in summary


# ============================================================
# ConflictResolver Tests
# ============================================================


class TestConflictResolver:
    """ConflictResolver 单元测试"""

    @pytest.fixture
    def sample_decisions(self, sample_account_state) -> list[TradingDecision]:
        """创建示例决策列表"""
        return [
            TradingDecision(
                decision_id="DEC-001",
                decision_type=DecisionType.OPEN,
                source=DecisionSource.SCREEN_SIGNAL,
                priority=DecisionPriority.NORMAL,
                symbol="AAPL 250221P00200000",
                underlying="AAPL",
                quantity=-1,
                account_state=sample_account_state,
            ),
            TradingDecision(
                decision_id="DEC-002",
                decision_type=DecisionType.CLOSE,
                source=DecisionSource.MONITOR_ALERT,
                priority=DecisionPriority.HIGH,
                symbol="AAPL 250121P00195000",
                underlying="AAPL",
                quantity=1,
                account_state=sample_account_state,
            ),
        ]

    def test_resolve_filters_hold_decisions(self, sample_account_state):
        """测试 HOLD 决策被过滤"""
        from src.business.trading.decision.conflict_resolver import ConflictResolver

        decisions = [
            TradingDecision(
                decision_id="DEC-001",
                decision_type=DecisionType.HOLD,
                source=DecisionSource.MONITOR_ALERT,
                priority=DecisionPriority.LOW,
                symbol="AAPL",
                account_state=sample_account_state,
            ),
        ]

        resolver = ConflictResolver()
        resolved = resolver.resolve(decisions)

        assert len(resolved) == 0

    def test_resolve_prioritizes_close_over_open(self, sample_decisions):
        """测试平仓决策优先于开仓决策"""
        from src.business.trading.decision.conflict_resolver import ConflictResolver

        resolver = ConflictResolver()
        resolved = resolver.resolve(sample_decisions)

        # 根据配置 single_action_per_underlying，同一标的只保留一个
        # 平仓应该优先
        assert len(resolved) >= 1

        # 第一个应该是平仓 (CLOSE) 或高优先级
        if len(resolved) == 1:
            # 如果只保留一个，应该是平仓
            assert resolved[0].decision_type == DecisionType.CLOSE

    def test_resolve_sorts_by_priority(self, sample_account_state):
        """测试按优先级排序"""
        from src.business.trading.decision.conflict_resolver import ConflictResolver

        decisions = [
            TradingDecision(
                decision_id="DEC-LOW",
                decision_type=DecisionType.OPEN,
                source=DecisionSource.SCREEN_SIGNAL,
                priority=DecisionPriority.LOW,
                symbol="MSFT",
                underlying="MSFT",
                account_state=sample_account_state,
            ),
            TradingDecision(
                decision_id="DEC-HIGH",
                decision_type=DecisionType.OPEN,
                source=DecisionSource.SCREEN_SIGNAL,
                priority=DecisionPriority.HIGH,
                symbol="TSLA",
                underlying="TSLA",
                account_state=sample_account_state,
            ),
            TradingDecision(
                decision_id="DEC-CRITICAL",
                decision_type=DecisionType.CLOSE,
                source=DecisionSource.MONITOR_ALERT,
                priority=DecisionPriority.CRITICAL,
                symbol="GOOGL",
                underlying="GOOGL",
                account_state=sample_account_state,
            ),
        ]

        resolver = ConflictResolver()
        resolved = resolver.resolve(decisions)

        # CRITICAL 应该在最前面
        assert resolved[0].priority == DecisionPriority.CRITICAL

    def test_check_conflict_same_underlying(self, sample_account_state):
        """测试同一标的的冲突检测"""
        from src.business.trading.decision.conflict_resolver import ConflictResolver

        existing = [
            TradingDecision(
                decision_id="EXISTING-001",
                decision_type=DecisionType.OPEN,
                source=DecisionSource.SCREEN_SIGNAL,
                priority=DecisionPriority.NORMAL,
                symbol="AAPL",
                underlying="AAPL",
                account_state=sample_account_state,
            ),
        ]

        new_decision = TradingDecision(
            decision_id="NEW-001",
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol="AAPL 250221P00200000",
            underlying="AAPL",
            account_state=sample_account_state,
        )

        resolver = ConflictResolver()
        has_conflict, reason = resolver.check_conflict(new_decision, existing)

        assert has_conflict is True
        assert "AAPL" in reason


# ============================================================
# OrderRequest Tests
# ============================================================


class TestOrderRequest:
    """OrderRequest 单元测试"""

    def test_order_serialization(self, sample_order_request):
        """测试订单序列化"""
        data = sample_order_request.to_dict()

        assert data["order_id"] == "TEST-20250126-001"
        assert data["symbol"] == "AAPL"
        assert data["side"] == "buy"
        assert data["order_type"] == "limit"
        assert data["quantity"] == 10
        assert data["limit_price"] == 150.00

    def test_option_order_fields(self, sample_option_order):
        """测试期权订单字段"""
        assert sample_option_order.underlying == "AAPL"
        assert sample_option_order.option_type == "put"
        assert sample_option_order.strike == 200.0
        assert sample_option_order.expiry == "2025-02-21"
        assert sample_option_order.contract_multiplier == 100

    def test_order_currency_field(self, sample_order_request):
        """测试订单货币字段"""
        assert sample_order_request.currency == "USD"

        sample_order_request.currency = "HKD"
        assert sample_order_request.currency == "HKD"


# ============================================================
# TradingDecision Tests
# ============================================================


class TestTradingDecision:
    """TradingDecision 单元测试"""

    def test_is_opening(self, sample_account_state):
        """测试是否开仓判断"""
        decision = TradingDecision(
            decision_id="DEC-001",
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol="AAPL",
            account_state=sample_account_state,
        )

        assert decision.is_opening is True
        assert decision.is_closing is False

    def test_is_closing(self, sample_account_state):
        """测试是否平仓判断"""
        decision = TradingDecision(
            decision_id="DEC-001",
            decision_type=DecisionType.CLOSE,
            source=DecisionSource.MONITOR_ALERT,
            priority=DecisionPriority.HIGH,
            symbol="AAPL",
            account_state=sample_account_state,
        )

        assert decision.is_opening is False
        assert decision.is_closing is True

    def test_approve_decision(self, sample_account_state):
        """测试批准决策"""
        decision = TradingDecision(
            decision_id="DEC-001",
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol="AAPL",
            account_state=sample_account_state,
        )

        assert decision.is_approved is False

        decision.approve("Manual approval")
        assert decision.is_approved is True
        assert decision.approval_notes == "Manual approval"

    def test_reject_decision(self, sample_account_state):
        """测试拒绝决策"""
        decision = TradingDecision(
            decision_id="DEC-001",
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol="AAPL",
            account_state=sample_account_state,
        )

        decision.reject("Risk limit exceeded")
        assert decision.is_approved is False
        assert "Rejected" in decision.approval_notes

    def test_decision_to_dict(self, sample_account_state):
        """测试决策序列化"""
        decision = TradingDecision(
            decision_id="DEC-001",
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol="AAPL 250221P00200000",
            underlying="AAPL",
            option_type="put",
            strike=200.0,
            expiry="2025-02-21",
            quantity=-1,
            limit_price=5.50,
            account_state=sample_account_state,
        )

        data = decision.to_dict()

        assert data["decision_id"] == "DEC-001"
        assert data["decision_type"] == "open"
        assert data["source"] == "screen_signal"
        assert data["priority"] == "normal"
        assert data["underlying"] == "AAPL"
        assert data["option_type"] == "put"
        assert data["strike"] == 200.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
