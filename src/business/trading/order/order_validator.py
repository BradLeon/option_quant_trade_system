"""Order Validator — order-level risk validation.

Renamed from risk_checker.py. Now accepts PortfolioState instead of
AccountState, eliminating the AccountState dependency.

Validates:
- Account type (CRITICAL: must be "paper")
- Price deviation from mid
- Projected margin utilization
- Order value as percentage of NLV
"""

import logging

from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.models.order import (
    OrderRequest,
    OrderSide,
    RiskCheckResult,
)
from src.strategy.models import PortfolioState

logger = logging.getLogger(__name__)


class OrderValidator:
    """Order-level risk validator.

    Usage:
        validator = OrderValidator()
        result = validator.validate(order, portfolio)
        if not result.passed:
            print(result.failed_checks)
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self._config = config or RiskConfig.load()

    def check(
        self,
        order: OrderRequest,
        portfolio: PortfolioState | None = None,
        current_mid_price: float | None = None,
    ) -> RiskCheckResult:
        """Validate order against risk limits.

        Args:
            order: Order to validate
            portfolio: Portfolio state (for margin/value checks)
            current_mid_price: Current mid price (for deviation check)

        Returns:
            RiskCheckResult with pass/fail and details
        """
        result = RiskCheckResult(passed=True)

        # === CRITICAL: Account type check ===
        self._check_account_type(order, result)

        # === Price deviation check ===
        if current_mid_price and order.limit_price:
            self._check_price_deviation(order, current_mid_price, result)

        # === Portfolio state required for remaining checks ===
        if portfolio is None:
            result.add_check(
                name="portfolio_state_required",
                passed=False,
                message="PortfolioState is required for margin and order value checks",
            )
            return result

        # === Margin projection ===
        self._check_margin_projection(order, portfolio, result)
        self._check_order_value(order, portfolio, result)

        return result

    def _check_account_type(
        self, order: OrderRequest, result: RiskCheckResult
    ) -> None:
        """CRITICAL: Orders MUST be for paper accounts."""
        if order.account_type != "paper":
            result.add_check(
                name="account_type",
                passed=False,
                message=(
                    f"CRITICAL: Order account_type must be 'paper', "
                    f"got '{order.account_type}'. Real trading is NOT supported."
                ),
            )
            logger.error(
                f"CRITICAL: Attempted to submit order with "
                f"account_type='{order.account_type}'"
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
        if not order.limit_price or current_mid_price <= 0:
            return

        deviation = abs(order.limit_price - current_mid_price) / current_mid_price
        max_deviation = self._config.max_price_deviation_pct

        passed = deviation < max_deviation
        result.add_check(
            name="price_deviation",
            passed=passed,
            message=(
                f"Price deviation {deviation:.1%} "
                f"{'within' if passed else 'exceeds'} limit {max_deviation:.1%}"
            ),
            current_value=deviation,
            threshold=max_deviation,
        )
        if not passed:
            logger.warning(
                f"OrderValidator: price deviation {deviation:.1%} >= "
                f"{max_deviation:.1%} for {order.symbol}"
            )

    def _check_margin_projection(
        self,
        order: OrderRequest,
        portfolio: PortfolioState,
        result: RiskCheckResult,
    ) -> None:
        """Check projected margin utilization after this order.

        Long options (BUY): premium only, no margin impact.
        Short options (SELL): ~20% of underlying for stock options.
        """
        if order.side == OrderSide.BUY:
            result.add_check(
                name="margin_projection",
                passed=True,
                message="Long position: premium only, no margin requirement",
            )
            return

        estimated_margin = 0.0
        if order.strike:
            multiplier = order.contract_multiplier
            margin_rate = self._config.margin_rate_stock_option
            estimated_margin = (
                order.strike * multiplier * abs(order.quantity) * margin_rate
            )

        nlv = portfolio.nlv
        if nlv <= 0:
            result.add_warning(
                "Unable to calculate margin: NLV is zero or negative"
            )
            return

        projected_margin = portfolio.margin_used + estimated_margin
        projected_utilization = projected_margin / nlv
        result.projected_margin_utilization = projected_utilization

        max_utilization = self._config.max_projected_margin_utilization
        passed = projected_utilization < max_utilization

        result.add_check(
            name="margin_projection",
            passed=passed,
            message=(
                f"Projected margin utilization {projected_utilization:.1%} "
                f"{'within' if passed else 'exceeds'} limit {max_utilization:.1%}"
            ),
            current_value=projected_utilization,
            threshold=max_utilization,
        )
        if not passed:
            logger.warning(
                f"OrderValidator: margin projection {projected_utilization:.1%} "
                f">= {max_utilization:.1%} for {order.symbol}"
            )

    def _check_order_value(
        self,
        order: OrderRequest,
        portfolio: PortfolioState,
        result: RiskCheckResult,
    ) -> None:
        nlv = portfolio.nlv
        if nlv <= 0:
            return

        if not order.limit_price:
            return

        multiplier = order.contract_multiplier if order.is_option else 1
        order_value = order.limit_price * abs(order.quantity) * multiplier

        value_pct = order_value / nlv
        max_value_pct = self._config.max_order_value_pct
        passed = value_pct < max_value_pct

        result.add_check(
            name="order_value",
            passed=passed,
            message=(
                f"Order value {value_pct:.1%} of NLV "
                f"{'within' if passed else 'exceeds'} limit {max_value_pct:.1%}"
            ),
            current_value=value_pct,
            threshold=max_value_pct,
        )
        if not passed:
            logger.warning(
                f"OrderValidator: order value {value_pct:.1%} >= "
                f"{max_value_pct:.1%} for {order.symbol}"
            )
