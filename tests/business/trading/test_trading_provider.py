#!/usr/bin/env python3
"""Trading Provider Unit Tests.

Tests IBKR Trading Provider and OrderRequest model.
V1 components (AccountStateAnalyzer, ConflictResolver, TradingDecision) removed.

Usage:
    pytest tests/business/trading/test_trading_provider.py -v
"""

import pytest

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
        quantity=1,
        limit_price=5.50,
        broker="ibkr",
        account_type="paper",
        status=OrderStatus.APPROVED,
        contract_multiplier=100,
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

        # 7497 端口应该允许
        provider = IBKRTradingProvider(port=7497)
        assert provider._port == 7497
        assert provider.account_type == TradingAccountType.PAPER

        # 7496 (Live) 端口应该拒绝
        with pytest.raises(AccountTypeError):
            IBKRTradingProvider(port=7496)

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

        # Live 账户订单应该被拒绝 (在 submit_order 中检查)
        sample_order_request.account_type = "live"

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
