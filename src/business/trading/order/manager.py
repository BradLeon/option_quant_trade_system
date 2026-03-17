"""Order Manager — order lifecycle management.

Handles: create → validate → submit → track → persist.
"""

import logging
from datetime import datetime
from typing import Any

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.models.order import (
    OrderRecord,
    OrderRequest,
    OrderStatus,
    RiskCheckResult,
)
from src.business.trading.models.trading import TradingResult
from src.business.trading.order.order_validator import OrderValidator
from src.business.trading.order.store import OrderStore
from src.business.trading.provider.base import TradingProvider
from src.strategy.models import PortfolioState

logger = logging.getLogger(__name__)


class OrderManager:
    """Order lifecycle manager.

    Usage:
        manager = OrderManager()
        result = manager.validate_order(order, portfolio)
        if result.passed:
            record = manager.submit_order(order)
    """

    def __init__(
        self,
        trading_provider: TradingProvider | None = None,
        config: OrderConfig | None = None,
        risk_config: RiskConfig | None = None,
        order_store: OrderStore | None = None,
        order_validator: OrderValidator | None = None,
    ) -> None:
        self._config = config or OrderConfig.load()
        self._risk_config = risk_config or RiskConfig.load()

        self._provider = trading_provider
        self._store = order_store or OrderStore(self._config)
        self._validator = order_validator or OrderValidator(self._risk_config)

        # Lazy-loaded notifier
        self._notifier: Any = None

    def set_trading_provider(self, provider: TradingProvider) -> None:
        self._provider = provider

    def validate_order(
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
        """
        result = self._validator.check(order, portfolio, current_mid_price)

        if result.passed:
            order.update_status(OrderStatus.APPROVED)
            logger.info(f"Order {order.order_id} passed validation")
        else:
            order.update_status(OrderStatus.VALIDATION_FAILED)
            order.validation_errors = result.failed_checks
            logger.warning(
                f"Order {order.order_id} failed validation: "
                f"{result.failed_checks}"
            )

        return result

    def submit_order(self, order: OrderRequest) -> OrderRecord:
        """Submit a validated order to the broker.

        Raises:
            ValueError: If order not APPROVED or no trading provider.
        """
        if order.status != OrderStatus.APPROVED:
            raise ValueError(
                f"Order must be APPROVED before submission, got {order.status}"
            )

        if self._provider is None:
            raise ValueError("Trading provider not set")

        record = OrderRecord(order=order)
        record.add_status_history(OrderStatus.APPROVED, "Order validated")

        try:
            result: TradingResult = self._provider.submit_order(order)

            if result.success:
                order.update_status(OrderStatus.SUBMITTED)
                record.broker_order_id = result.broker_order_id
                record.broker_status = result.broker_status
                record.add_status_history(
                    OrderStatus.SUBMITTED,
                    f"Submitted to {order.broker}, "
                    f"broker_id={result.broker_order_id}, "
                    f"status={result.broker_status}",
                )
                logger.info(
                    f"Order {order.order_id} submitted: "
                    f"broker_id={result.broker_order_id}"
                )
                self._notify_order_submitted(record)
            else:
                order.update_status(OrderStatus.REJECTED)
                record.error_message = result.error_message
                record.broker_order_id = result.broker_order_id
                record.broker_status = result.broker_status
                record.add_status_history(
                    OrderStatus.REJECTED,
                    f"Rejected: {result.error_message}",
                )
                logger.error(
                    f"Order {order.order_id} rejected: {result.error_message}"
                )
                self._notify_order_rejected(record)

        except Exception as e:
            order.update_status(OrderStatus.ERROR)
            record.error_message = str(e)
            record.add_status_history(OrderStatus.ERROR, f"Error: {e}")
            logger.exception(f"Order {order.order_id} error: {e}")
            self._notify_order_error(record)

        self._store.save(record)
        return record

    def submit_roll_orders(
        self,
        orders: list[OrderRequest],
    ) -> list[OrderRecord]:
        """Submit roll orders (close + open) sequentially.

        If close fails, open is cancelled.
        """
        if len(orders) != 2:
            raise ValueError(f"Expected 2 orders for roll, got {len(orders)}")

        close_order, open_order = orders
        records = []

        # 1. Submit close
        logger.info(f"Submitting roll close order: {close_order.order_id}")
        close_record = self.submit_order(close_order)
        records.append(close_record)

        # If close failed, cancel open
        if close_order.status != OrderStatus.SUBMITTED:
            logger.warning(
                f"Roll close order failed ({close_order.status}), "
                f"skipping open order"
            )
            open_order.update_status(OrderStatus.CANCELLED)
            open_record = OrderRecord(order=open_order)
            open_record.add_status_history(
                OrderStatus.CANCELLED,
                "Skipped: close order failed",
            )
            records.append(open_record)
            return records

        # 2. Submit open
        logger.info(f"Submitting roll open order: {open_order.order_id}")
        open_record = self.submit_order(open_order)
        records.append(open_record)

        return records

    def cancel_order(self, order_id: str) -> bool:
        record = self._store.get(order_id)
        if record is None:
            logger.warning(f"Order {order_id} not found")
            return False

        if record.is_complete:
            logger.warning(f"Order {order_id} is already complete")
            return False

        if self._provider is None:
            logger.error("Trading provider not set")
            return False

        if record.broker_order_id is None:
            record.order.update_status(OrderStatus.CANCELLED)
            record.add_status_history(
                OrderStatus.CANCELLED, "Cancelled before submission"
            )
            record.is_complete = True
            record.completion_time = datetime.now()
            self._store.save(record)
            return True

        result = self._provider.cancel_order(record.broker_order_id)

        if result.success:
            record.order.update_status(OrderStatus.CANCELLED)
            record.add_status_history(
                OrderStatus.CANCELLED, "Cancelled at broker"
            )
            record.is_complete = True
            record.completion_time = datetime.now()
            self._store.save(record)
            logger.info(f"Order {order_id} cancelled")
            return True
        else:
            logger.error(
                f"Failed to cancel order {order_id}: {result.error_message}"
            )
            return False

    def get_order_status(self, order_id: str) -> OrderRecord | None:
        return self._store.get(order_id)

    def get_open_orders(self) -> list[OrderRecord]:
        return self._store.get_open_orders()

    def get_orders_by_decision(self, decision_id: str) -> list[OrderRecord]:
        return self._store.get_by_decision(decision_id)

    def get_recent_orders(self, days: int = 7) -> list[OrderRecord]:
        return self._store.get_recent(days)

    def sync_order_status(self, order_id: str) -> OrderRecord | None:
        record = self._store.get(order_id)
        if record is None or self._provider is None:
            return None

        if record.broker_order_id is None:
            return record

        query_result = self._provider.query_order(record.broker_order_id)

        if not query_result.found:
            return record

        old_status = record.order.status

        if query_result.is_filled:
            record.order.update_status(OrderStatus.FILLED)
            record.total_filled_quantity = query_result.filled_quantity
            record.average_fill_price = query_result.average_price
            record.is_complete = True
            record.completion_time = datetime.now()

            if old_status != OrderStatus.FILLED:
                record.add_status_history(OrderStatus.FILLED, "Fully filled")
                self._notify_order_filled(record)

        elif query_result.is_partially_filled:
            record.order.update_status(OrderStatus.PARTIAL_FILLED)
            record.total_filled_quantity = query_result.filled_quantity
            record.average_fill_price = query_result.average_price

        record.broker_status = query_result.status
        self._store.save(record)

        return record

    # ── Notifications ──

    def _notify_order_submitted(self, record: OrderRecord) -> None:
        if not self._config.notify_on_submit:
            return
        self._send_notification(
            f"Order Submitted: {record.order.symbol}", record
        )

    def _notify_order_filled(self, record: OrderRecord) -> None:
        if not self._config.notify_on_fill:
            return
        self._send_notification(
            f"Order Filled: {record.order.symbol}", record
        )

    def _notify_order_rejected(self, record: OrderRecord) -> None:
        if not self._config.notify_on_reject:
            return
        self._send_notification(
            f"Order Rejected: {record.order.symbol}", record
        )

    def _notify_order_error(self, record: OrderRecord) -> None:
        self._send_notification(
            f"Order Error: {record.order.symbol}", record
        )

    def _send_notification(self, title: str, record: OrderRecord) -> None:
        try:
            if self._notifier is None:
                try:
                    from src.business.notification.dispatcher import (
                        NotificationDispatcher,
                    )

                    self._notifier = NotificationDispatcher()
                except ImportError:
                    logger.debug("Notification module not available")
                    return

            message = self._build_notification_message(record)
            self._notifier.send_text(title, message)
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    def _build_notification_message(self, record: OrderRecord) -> str:
        order = record.order
        lines = [
            f"Order ID: {order.order_id}",
            f"Symbol: {order.symbol}",
            f"Side: {order.side.value.upper()}",
            f"Quantity: {order.quantity}",
            f"Status: {order.status.value}",
        ]
        if order.limit_price:
            lines.append(f"Limit Price: {order.limit_price:.2f}")
        if record.broker_order_id:
            lines.append(f"Broker ID: {record.broker_order_id}")
        if record.average_fill_price:
            lines.append(f"Avg Fill: {record.average_fill_price:.2f}")
        if record.error_message:
            lines.append(f"Error: {record.error_message}")
        return "\n".join(lines)
