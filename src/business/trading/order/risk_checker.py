"""
Risk Checker - 订单风控检查

实现多层风控验证:
- Layer 3: Order-Level Validation
  - Margin check
  - Price check
  - Account type check (CRITICAL)
"""

import logging
from typing import Any

from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.models.decision import AccountState
from src.business.trading.models.order import OrderRequest, RiskCheckResult

logger = logging.getLogger(__name__)


class RiskChecker:
    """订单风控检查器

    执行 Layer 3 订单级别的风控验证。

    Usage:
        checker = RiskChecker()
        result = checker.check(order, account_state)
        if not result.passed:
            print(result.failed_checks)
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        """初始化风控检查器

        Args:
            config: 风控配置
        """
        self._config = config or RiskConfig.load()

    def check(
        self,
        order: OrderRequest,
        account_state: AccountState | None = None,
        current_mid_price: float | None = None,
    ) -> RiskCheckResult:
        """执行风控检查

        Args:
            order: 订单请求
            account_state: 账户状态 (可选)
            current_mid_price: 当前中间价 (可选)

        Returns:
            RiskCheckResult: 检查结果
        """

        result = RiskCheckResult(passed=True)

        # === CRITICAL: 账户类型检查 ===
        self._check_account_type(order, result)

        # === 价格偏离检查 ===
        if current_mid_price and order.limit_price:
            self._check_price_deviation(order, current_mid_price, result)

        # === 账户状态必须存在 ===
        if account_state is None:
            result.add_check(
                name="account_state_required",
                passed=False,
                message="AccountState is required for margin and order value checks",
            )
            return result  # 账户状态缺失，无法继续风控检查

        # === 保证金检查 ===
        self._check_margin_projection(order, account_state, result)
        self._check_order_value(order, account_state, result)

        return result

    def _check_account_type(
        self, order: OrderRequest, result: RiskCheckResult
    ) -> None:
        """检查账户类型 - CRITICAL

        This is the most important check. Orders MUST be for paper accounts.
        """
        if order.account_type != "paper":
            result.add_check(
                name="account_type",
                passed=False,
                message=(
                    f"CRITICAL: Order account_type must be 'paper', "
                    f"got '{order.account_type}'. Real trading is NOT supported."
                ),
                current_value=None,
                threshold=None,
            )
            logger.error(
                f"CRITICAL: Attempted to submit order with account_type='{order.account_type}'"
            )
        else:
            result.add_check(
                name="account_type",
                passed=True,
                message="Account type is paper",
            )

    def _check_price_deviation(
        self,
        order: OrderRequest,
        current_mid_price: float,
        result: RiskCheckResult,
    ) -> None:
        """检查价格偏离"""
        if not order.limit_price or current_mid_price <= 0:
            return

        deviation = abs(order.limit_price - current_mid_price) / current_mid_price
        max_deviation = self._config.max_price_deviation_pct

        if deviation >= max_deviation:
            result.add_check(
                name="price_deviation",
                passed=False,
                message=(
                    f"Limit price deviation {deviation:.1%} exceeds "
                    f"maximum {max_deviation:.1%}"
                ),
                current_value=deviation,
                threshold=max_deviation,
            )
        else:
            result.add_check(
                name="price_deviation",
                passed=True,
                message=f"Price deviation {deviation:.1%} within limit",
                current_value=deviation,
                threshold=max_deviation,
            )

    def _check_margin_projection(
        self,
        order: OrderRequest,
        account_state: AccountState,
        result: RiskCheckResult,
    ) -> None:
        """检查预计保证金使用率

        保证金估算基于 IBKR Reg T 规则:
        - 股票期权: 20% of underlying
        - 指数期权: 15% of underlying
        参考: https://www.interactivebrokers.com/en/trading/margin-options.php
        """
        estimated_margin = 0.0

        if order.strike:
            multiplier = order.contract_multiplier  # 从订单获取合约乘数
            # 使用配置的保证金率 (默认使用股票期权保证金率)
            margin_rate = self._config.margin_rate_stock_option
            estimated_margin = order.strike * multiplier * abs(order.quantity) * margin_rate

        current_margin = account_state.used_margin
        nlv = account_state.total_equity

        if nlv <= 0:
            result.add_warning("Unable to calculate margin: NLV is zero or negative")
            return

        projected_margin = current_margin + estimated_margin
        projected_utilization = projected_margin / nlv

        result.projected_margin_utilization = projected_utilization

        max_utilization = self._config.max_projected_margin_utilization

        if projected_utilization >= max_utilization:
            result.add_check(
                name="margin_projection",
                passed=False,
                message=(
                    f"Projected margin utilization {projected_utilization:.1%} "
                    f"exceeds maximum {max_utilization:.1%}"
                ),
                current_value=projected_utilization,
                threshold=max_utilization,
            )
        else:
            result.add_check(
                name="margin_projection",
                passed=True,
                message=f"Projected margin utilization {projected_utilization:.1%} within limit",
                current_value=projected_utilization,
                threshold=max_utilization,
            )

    def _check_order_value(
        self,
        order: OrderRequest,
        account_state: AccountState,
        result: RiskCheckResult,
    ) -> None:
        """检查订单价值占比"""
        nlv = account_state.total_equity
        if nlv <= 0:
            return

        # 注: 币种一致性检查需 order.currency 与 account_state 币种匹配 (未实现)

        # 计算订单价值
        if order.limit_price:
            multiplier = order.contract_multiplier if order.is_option else 1
            order_value = order.limit_price * abs(order.quantity) * multiplier
        else:
            return  # 无法计算

        value_pct = order_value / nlv
        max_value_pct = self._config.max_order_value_pct

        if value_pct >= max_value_pct:
            result.add_check(
                name="order_value",
                passed=False,
                message=(
                    f"Order value {value_pct:.1%} of NLV "
                    f"exceeds maximum {max_value_pct:.1%}"
                ),
                current_value=value_pct,
                threshold=max_value_pct,
            )
        else:
            result.add_check(
                name="order_value",
                passed=True,
                message=f"Order value {value_pct:.1%} of NLV within limit",
                current_value=value_pct,
                threshold=max_value_pct,
            )
