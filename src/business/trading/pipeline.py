"""Trading Pipeline — orchestrates order validation and execution.

V2 API: execute_orders(orders, portfolio) — accepts OrderRequest directly
V1 API: execute_decisions() — deprecated, kept for backward compat
"""

import logging
from datetime import datetime
from typing import Any

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.daily_limits import DailyLimitsConfig, DailyTradeTracker
from src.business.trading.models.order import OrderRecord, OrderRequest, OrderStatus
from src.business.trading.order.manager import OrderManager
from src.business.trading.provider.base import TradingProvider
from src.business.trading.provider.ibkr_trading import IBKRTradingProvider
from src.strategy.models import PortfolioState

logger = logging.getLogger(__name__)


class TradingPipeline:
    """Trading pipeline — orchestrates order validation and execution.

    V2 flow: execute_orders(orders, portfolio)
    V1 flow: execute_decisions(decisions, account_state) — deprecated
    """

    def __init__(
        self,
        order_config: OrderConfig | None = None,
        risk_config: RiskConfig | None = None,
        daily_limits_config: DailyLimitsConfig | None = None,
        trading_provider: TradingProvider | None = None,
    ) -> None:
        self._order_config = order_config or OrderConfig.load()
        self._risk_config = risk_config or RiskConfig.load()
        self._daily_limits_config = daily_limits_config or DailyLimitsConfig.load()

        self._order_manager = OrderManager(
            config=self._order_config,
            risk_config=self._risk_config,
        )

        self._daily_tracker = DailyTradeTracker(
            order_store=self._order_manager._store,
            config=self._daily_limits_config,
        )

        self._provider = trading_provider
        self._connected = False

    def __enter__(self) -> "TradingPipeline":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.disconnect()

    def connect(self, broker: str = "ibkr") -> None:
        if self._connected:
            return

        if self._provider is None:
            if broker == "ibkr":
                self._provider = IBKRTradingProvider()
            else:
                raise ValueError(f"Unsupported broker: {broker}")

        try:
            self._provider.connect()
            self._order_manager.set_trading_provider(self._provider)
            self._connected = True
            logger.info(f"Trading pipeline connected to {broker}")
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise

    def disconnect(self) -> None:
        if self._provider and self._connected:
            try:
                self._provider.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")
            finally:
                self._connected = False
                logger.info("Trading pipeline disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._provider is not None

    # ── V2 API: execute_orders ──

    def execute_orders(
        self,
        orders: list[OrderRequest],
        portfolio: PortfolioState,
        dry_run: bool = False,
    ) -> list[OrderRecord]:
        """Execute pre-built orders (V2 flow).

        DailyLimits checking has already been done at signal level
        (DailyLimitsGuard in RiskGuard chain). This method only does
        order-level validation and submission.

        Args:
            orders: OrderRequest list from SignalOrderBuilder
            portfolio: Current portfolio state
            dry_run: If True, validate but don't submit
        """
        if not self.is_connected and not dry_run:
            raise RuntimeError("Trading pipeline not connected")

        results: list[OrderRecord] = []

        for order in orders:
            try:
                result = self._execute_single_order(
                    order, portfolio, dry_run
                )
                if result:
                    if isinstance(result, list):
                        results.extend(result)
                    else:
                        results.append(result)
            except Exception as e:
                logger.error(
                    f"Failed to execute order {order.order_id}: {e}"
                )

        logger.info(
            f"Executed {len(results)} orders "
            f"({'dry-run' if dry_run else 'live'})"
        )
        return results

    def execute_roll_orders(
        self,
        close_order: OrderRequest,
        open_order: OrderRequest,
        portfolio: PortfolioState,
        dry_run: bool = False,
    ) -> list[OrderRecord]:
        """Execute a roll order pair (close + open).

        Validates both orders first, then submits sequentially.
        If close fails, open is cancelled.
        """
        orders = [close_order, open_order]
        records: list[OrderRecord] = []
        all_validated = True

        # Validate both
        for order in orders:
            validation = self._order_manager.validate_order(
                order, portfolio, current_mid_price=order.limit_price
            )
            if not validation.passed:
                logger.warning(
                    f"Roll order {order.order_id} failed validation: "
                    f"{validation.failed_checks}"
                )
                record = OrderRecord(order=order)
                record.add_status_history(
                    OrderStatus.VALIDATION_FAILED,
                    f"Validation failed: {validation.failed_checks}",
                )
                records.append(record)
                all_validated = False

        if not all_validated:
            # Cancel remaining
            for order in orders:
                if not any(r.order.order_id == order.order_id for r in records):
                    record = OrderRecord(order=order)
                    record.add_status_history(
                        OrderStatus.CANCELLED,
                        "Cancelled: other order in roll failed validation",
                    )
                    records.append(record)
            return records

        if dry_run:
            for order in orders:
                logger.info(f"[DRY-RUN] Would submit roll: {order.order_id}")
                record = OrderRecord(order=order)
                record.add_status_history(
                    OrderStatus.APPROVED,
                    "Dry-run: validated but not submitted",
                )
                records.append(record)
            return records

        return self._order_manager.submit_roll_orders(orders)

    def _execute_single_order(
        self,
        order: OrderRequest,
        portfolio: PortfolioState,
        dry_run: bool,
    ) -> OrderRecord | list[OrderRecord] | None:
        """Execute a single order: validate → submit."""
        # Skip non-executable
        if order.quantity == 0:
            logger.warning(
                f"Pipeline: skipped zero-quantity order {order.symbol}"
            )
            return None

        # Check if this is part of a roll pair — handled by caller
        if order.context.get("roll_pair"):
            # Roll orders should be submitted via execute_roll_orders
            pass

        # Validate
        validation = self._order_manager.validate_order(
            order, portfolio, current_mid_price=order.limit_price
        )

        if not validation.passed:
            logger.warning(
                f"Order {order.order_id} failed validation: "
                f"{validation.failed_checks}"
            )
            record = OrderRecord(order=order)
            record.add_status_history(
                OrderStatus.VALIDATION_FAILED,
                f"Validation failed: {validation.failed_checks}",
            )
            return record

        if dry_run:
            logger.info(f"[DRY-RUN] Would submit: {order.order_id}")
            record = OrderRecord(order=order)
            record.add_status_history(
                OrderStatus.APPROVED,
                "Dry-run: validated but not submitted",
            )
            return record

        return self._order_manager.submit_order(order)

    # ── Query APIs ──

    def get_order_status(self, order_id: str) -> OrderRecord | None:
        return self._order_manager.get_order_status(order_id)

    def get_open_orders(self) -> list[OrderRecord]:
        return self._order_manager.get_open_orders()

    def get_recent_orders(self, days: int = 7) -> list[OrderRecord]:
        return self._order_manager.get_recent_orders(days)

    def cancel_order(self, order_id: str) -> bool:
        return self._order_manager.cancel_order(order_id)

    def sync_order_status(self, order_id: str) -> OrderRecord | None:
        return self._order_manager.sync_order_status(order_id)

    def get_system_status(self) -> dict[str, Any]:
        return {
            "connected": self.is_connected,
            "broker": self._provider.name if self._provider else None,
            "account_type": (
                self._provider.account_type.value if self._provider else None
            ),
            "open_orders": len(self.get_open_orders()),
            "timestamp": datetime.now().isoformat(),
        }

    def get_daily_limits_usage(self, nlv: float) -> dict[str, dict[str, Any]]:
        return self._daily_tracker.get_usage_summary(nlv)

    @property
    def daily_limits_enabled(self) -> bool:
        return self._daily_limits_config.enabled

    @property
    def order_store(self) -> Any:
        """Expose OrderStore for DailyLimitsGuard construction."""
        return self._order_manager._store
