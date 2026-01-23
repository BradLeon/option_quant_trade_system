"""
Order Manager - 订单管理器

处理订单生命周期:
- 从决策创建订单
- 风控验证
- 提交执行
- 状态跟踪
- 持久化存储
"""

import logging
from datetime import datetime
from typing import Any

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.models.decision import AccountState, TradingDecision
from src.business.trading.models.order import (
    OrderRecord,
    OrderRequest,
    OrderStatus,
    RiskCheckResult,
)
from src.business.trading.models.trading import TradingResult
from src.business.trading.order.generator import OrderGenerator
from src.business.trading.order.risk_checker import RiskChecker
from src.business.trading.order.store import OrderStore
from src.business.trading.provider.base import TradingProvider

logger = logging.getLogger(__name__)


class OrderManager:
    """订单管理器

    处理完整的订单生命周期。

    Usage:
        manager = OrderManager(trading_provider)
        order = manager.create_order(decision)
        result = manager.validate_order(order)
        if result.passed:
            record = manager.submit_order(order)
    """

    def __init__(
        self,
        trading_provider: TradingProvider | None = None,
        config: OrderConfig | None = None,
        risk_config: RiskConfig | None = None,
        order_store: OrderStore | None = None,
        risk_checker: RiskChecker | None = None,
        order_generator: OrderGenerator | None = None,
    ) -> None:
        """初始化订单管理器

        Args:
            trading_provider: 交易提供者
            config: 订单配置
            risk_config: 风控配置
            order_store: 订单存储
            risk_checker: 风控检查器
            order_generator: 订单生成器
        """
        self._config = config or OrderConfig.load()
        self._risk_config = risk_config or RiskConfig.load()

        self._provider = trading_provider
        self._store = order_store or OrderStore(self._config)
        self._risk_checker = risk_checker or RiskChecker(self._risk_config)
        self._generator = order_generator or OrderGenerator(self._config)

        # 通知器 (延迟导入以避免循环依赖)
        self._notifier: Any = None

    def set_trading_provider(self, provider: TradingProvider) -> None:
        """设置交易提供者"""
        self._provider = provider

    def create_order(self, decision: TradingDecision) -> OrderRequest:
        """从决策创建订单

        Args:
            decision: 交易决策

        Returns:
            OrderRequest: 订单请求
        """
        return self._generator.generate(decision)

    def validate_order(
        self,
        order: OrderRequest,
        account_state: AccountState | None = None,
        current_mid_price: float | None = None,
    ) -> RiskCheckResult:
        """验证订单

        Args:
            order: 订单请求
            account_state: 账户状态
            current_mid_price: 当前中间价

        Returns:
            RiskCheckResult: 验证结果
        """
        result = self._risk_checker.check(order, account_state, current_mid_price)

        if result.passed:
            order.update_status(OrderStatus.APPROVED)
            logger.info(f"Order {order.order_id} passed validation")
        else:
            order.update_status(OrderStatus.VALIDATION_FAILED)
            order.validation_errors = result.failed_checks
            logger.warning(
                f"Order {order.order_id} failed validation: {result.failed_checks}"
            )

        return result

    def submit_order(self, order: OrderRequest) -> OrderRecord:
        """提交订单

        Args:
            order: 已验证的订单请求

        Returns:
            OrderRecord: 订单记录

        Raises:
            ValueError: 订单未通过验证或无交易提供者
        """
        # 验证订单状态
        if order.status != OrderStatus.APPROVED:
            raise ValueError(
                f"Order must be APPROVED before submission, got {order.status}"
            )

        if self._provider is None:
            raise ValueError("Trading provider not set")

        # 创建订单记录
        record = OrderRecord(order=order)
        record.add_status_history(OrderStatus.APPROVED, "Order validated")

        try:
            # 提交到券商
            result: TradingResult = self._provider.submit_order(order)

            if result.success:
                order.update_status(OrderStatus.SUBMITTED)
                record.broker_order_id = result.broker_order_id
                record.add_status_history(
                    OrderStatus.SUBMITTED,
                    f"Submitted to {order.broker}, broker_id={result.broker_order_id}",
                )
                logger.info(
                    f"Order {order.order_id} submitted: broker_id={result.broker_order_id}"
                )

                # 发送通知
                self._notify_order_submitted(record)

            else:
                order.update_status(OrderStatus.REJECTED)
                record.error_message = result.error_message
                record.add_status_history(
                    OrderStatus.REJECTED,
                    f"Rejected: {result.error_message}",
                )
                logger.error(
                    f"Order {order.order_id} rejected: {result.error_message}"
                )

                # 发送通知
                self._notify_order_rejected(record)

        except Exception as e:
            order.update_status(OrderStatus.ERROR)
            record.error_message = str(e)
            record.add_status_history(OrderStatus.ERROR, f"Error: {e}")
            logger.exception(f"Order {order.order_id} error: {e}")

            # 发送通知
            self._notify_order_error(record)

        # 保存订单记录
        self._store.save(record)

        return record

    def cancel_order(self, order_id: str) -> bool:
        """取消订单

        Args:
            order_id: 订单 ID

        Returns:
            是否成功取消
        """
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
            # 订单未提交，直接标记取消
            record.order.update_status(OrderStatus.CANCELLED)
            record.add_status_history(OrderStatus.CANCELLED, "Cancelled before submission")
            record.is_complete = True
            record.completion_time = datetime.now()
            self._store.save(record)
            return True

        # 调用券商取消
        result = self._provider.cancel_order(record.broker_order_id)

        if result.success:
            record.order.update_status(OrderStatus.CANCELLED)
            record.add_status_history(OrderStatus.CANCELLED, "Cancelled at broker")
            record.is_complete = True
            record.completion_time = datetime.now()
            self._store.save(record)
            logger.info(f"Order {order_id} cancelled")
            return True
        else:
            logger.error(f"Failed to cancel order {order_id}: {result.error_message}")
            return False

    def get_order_status(self, order_id: str) -> OrderRecord | None:
        """获取订单状态

        Args:
            order_id: 订单 ID

        Returns:
            订单记录
        """
        return self._store.get(order_id)

    def get_open_orders(self) -> list[OrderRecord]:
        """获取所有未完成订单"""
        return self._store.get_open_orders()

    def get_orders_by_decision(self, decision_id: str) -> list[OrderRecord]:
        """按决策 ID 获取订单"""
        return self._store.get_by_decision(decision_id)

    def get_recent_orders(self, days: int = 7) -> list[OrderRecord]:
        """获取最近订单"""
        return self._store.get_recent(days)

    def sync_order_status(self, order_id: str) -> OrderRecord | None:
        """同步订单状态

        从券商获取最新状态并更新本地记录。
        """
        record = self._store.get(order_id)
        if record is None or self._provider is None:
            return None

        if record.broker_order_id is None:
            return record

        # 查询券商状态
        query_result = self._provider.query_order(record.broker_order_id)

        if not query_result.found:
            return record

        # 更新状态
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

    def _notify_order_submitted(self, record: OrderRecord) -> None:
        """发送订单提交通知"""
        if not self._config.notify_on_submit:
            return
        self._send_notification(
            f"Order Submitted: {record.order.symbol}",
            record,
        )

    def _notify_order_filled(self, record: OrderRecord) -> None:
        """发送订单成交通知"""
        if not self._config.notify_on_fill:
            return
        self._send_notification(
            f"Order Filled: {record.order.symbol}",
            record,
        )

    def _notify_order_rejected(self, record: OrderRecord) -> None:
        """发送订单拒绝通知"""
        if not self._config.notify_on_reject:
            return
        self._send_notification(
            f"Order Rejected: {record.order.symbol}",
            record,
        )

    def _notify_order_error(self, record: OrderRecord) -> None:
        """发送订单错误通知"""
        self._send_notification(
            f"Order Error: {record.order.symbol}",
            record,
        )

    def _send_notification(self, title: str, record: OrderRecord) -> None:
        """发送通知"""
        try:
            # 延迟导入通知模块
            if self._notifier is None:
                try:
                    from src.business.notification.dispatcher import NotificationDispatcher
                    self._notifier = NotificationDispatcher()
                except ImportError:
                    logger.debug("Notification module not available")
                    return

            message = self._build_notification_message(record)
            self._notifier.send_text(title, message)

        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    def _build_notification_message(self, record: OrderRecord) -> str:
        """构建通知消息"""
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
