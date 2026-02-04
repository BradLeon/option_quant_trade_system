"""
Trading Pipeline - 交易流水线

编排层，协调决策引擎、订单管理器和交易提供者。

Usage:
    pipeline = TradingPipeline()
    decisions = pipeline.process_signals(screen_result, monitor_result)
    results = pipeline.execute_decisions(decisions)
"""

import logging
from datetime import datetime
from typing import Any

from src.business.monitoring.models import MonitorResult
from src.business.monitoring.suggestions import PositionSuggestion, SuggestionGenerator
from src.business.screening.models import ScreeningResult
from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.config.order_config import OrderConfig
from src.business.trading.config.risk_config import RiskConfig
from src.business.trading.daily_limits import DailyLimitsConfig, DailyTradeTracker
from src.business.trading.decision.engine import DecisionEngine
from src.business.trading.models.decision import AccountState, TradingDecision
from src.business.trading.models.order import OrderRecord, OrderStatus
from src.business.trading.order.manager import OrderManager
from src.business.trading.provider.base import TradingProvider
from src.business.trading.provider.ibkr_trading import IBKRTradingProvider

logger = logging.getLogger(__name__)


class TradingPipeline:
    """交易流水线

    协调整个交易流程:
    1. 接收信号 (Screen/Monitor)
    2. 生成决策 (DecisionEngine)
    3. 验证订单 (OrderManager)
    4. 执行交易 (TradingProvider)

    Usage:
        pipeline = TradingPipeline()
        with pipeline:
            decisions = pipeline.process_signals(screen_result, monitor_result, account_state)
            if auto_execute:
                results = pipeline.execute_decisions(decisions, account_state)
    """

    def __init__(
        self,
        decision_config: DecisionConfig | None = None,
        order_config: OrderConfig | None = None,
        risk_config: RiskConfig | None = None,
        daily_limits_config: DailyLimitsConfig | None = None,
        trading_provider: TradingProvider | None = None,
    ) -> None:
        """初始化交易流水线

        Args:
            decision_config: 决策配置
            order_config: 订单配置
            risk_config: 风控配置
            daily_limits_config: 每日交易限额配置
            trading_provider: 交易提供者 (可选，后续设置)
        """
        self._decision_config = decision_config or DecisionConfig.load()
        self._order_config = order_config or OrderConfig.load()
        self._risk_config = risk_config or RiskConfig.load()
        self._daily_limits_config = daily_limits_config or DailyLimitsConfig.load()

        self._decision_engine = DecisionEngine(self._decision_config)
        self._order_manager = OrderManager(
            config=self._order_config,
            risk_config=self._risk_config,
        )

        # 每日交易限额追踪器
        self._daily_tracker = DailyTradeTracker(
            order_store=self._order_manager._store,
            config=self._daily_limits_config,
        )

        self._provider = trading_provider
        self._connected = False

    def __enter__(self) -> "TradingPipeline":
        """进入上下文管理器"""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """退出上下文管理器"""
        self.disconnect()

    def connect(self, broker: str = "ibkr") -> None:
        """连接交易提供者

        Args:
            broker: 券商名称 (ibkr 或 futu)
        """
        if self._connected:
            return

        if self._provider is None:
            if broker == "ibkr":
                self._provider = IBKRTradingProvider()
            else:
                # 可以添加 Futu 支持
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
        """断开连接"""
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
        """是否已连接"""
        return self._connected and self._provider is not None

    def process_signals(
        self,
        screen_result: ScreeningResult | None,
        monitor_result: MonitorResult | None,
        account_state: AccountState,
        suggestions: list[PositionSuggestion] | None = None,
    ) -> list[TradingDecision]:
        """处理信号生成决策

        Args:
            screen_result: 筛选结果
            monitor_result: 监控结果
            account_state: 账户状态
            suggestions: 调整建议 (可选)

        Returns:
            解决冲突后的决策列表
        """
        # 如果没有提供 suggestions，从 monitor_result 生成
        if suggestions is None and monitor_result is not None:
            generator = SuggestionGenerator()
            suggestions = generator.generate(monitor_result)

        decisions = self._decision_engine.process_batch(
            screen_result,
            account_state,
            suggestions,
        )

        logger.info(f"Generated {len(decisions)} decisions from signals")
        return decisions

    def execute_decisions(
        self,
        decisions: list[TradingDecision],
        account_state: AccountState | None = None,
        dry_run: bool = False,
    ) -> list[OrderRecord]:
        """执行决策

        Args:
            decisions: 决策列表
            account_state: 账户状态 (用于风控和每日限额)
            dry_run: 是否仅模拟 (不实际下单)

        Returns:
            订单记录列表
        """
        if not self.is_connected and not dry_run:
            raise RuntimeError("Trading pipeline not connected")

        results: list[OrderRecord] = []

        # 获取 NLV 用于每日限额检查
        nlv = account_state.total_equity if account_state else 0.0

        # 追踪本批次内已通过的 underlying 累计量
        batch_quantities: dict[str, int] = {}
        batch_values: dict[str, float] = {}

        for decision in decisions:
            try:
                # 检查每日限额
                if self._daily_limits_config.enabled and nlv > 0:
                    skip_reason = self._check_daily_limits_for_decision(
                        decision, nlv, batch_quantities, batch_values
                    )
                    if skip_reason:
                        logger.info(
                            f"Skipping decision {decision.decision_id} "
                            f"({decision.symbol}): {skip_reason}"
                        )
                        continue

                result = self._execute_single_decision(
                    decision, account_state, dry_run
                )
                if result:
                    # ROLL 决策返回列表，普通决策返回单个记录
                    if isinstance(result, list):
                        results.extend(result)
                    else:
                        results.append(result)

                    # 更新本批次累计量（订单提交成功后）
                    underlying = decision.underlying or decision.symbol
                    qty = abs(decision.quantity)
                    value = self._calc_decision_value(decision)
                    batch_quantities[underlying] = (
                        batch_quantities.get(underlying, 0) + qty
                    )
                    batch_values[underlying] = (
                        batch_values.get(underlying, 0.0) + value
                    )

                    # 清除缓存，让后续检查能看到新订单
                    self._daily_tracker.invalidate_cache()

            except Exception as e:
                logger.error(
                    f"Failed to execute decision {decision.decision_id}: {e}"
                )

        logger.info(
            f"Executed {len(results)} decisions "
            f"({'dry-run' if dry_run else 'live'})"
        )
        return results

    def _check_daily_limits_for_decision(
        self,
        decision: TradingDecision,
        nlv: float,
        batch_quantities: dict[str, int],
        batch_values: dict[str, float],
    ) -> str | None:
        """检查决策是否超过每日限额

        Args:
            decision: 交易决策
            nlv: 账户净值
            batch_quantities: 本批次已累计的数量
            batch_values: 本批次已累计的市值

        Returns:
            如果超限，返回原因字符串；否则返回 None
        """
        underlying = decision.underlying or decision.symbol
        quantity = decision.quantity
        value = self._calc_decision_value(decision)

        # 加上本批次已累计的量
        check_qty = quantity + batch_quantities.get(underlying, 0)
        check_val = value + batch_values.get(underlying, 0.0)

        allowed, reason = self._daily_tracker.check_limits(
            underlying=underlying,
            quantity=check_qty,
            value=check_val,
            nlv=nlv,
            decision_type=decision.decision_type.value,
        )

        return None if allowed else reason

    def _calc_decision_value(self, decision: TradingDecision) -> float:
        """计算决策的市值

        Args:
            decision: 交易决策

        Returns:
            市值 = |quantity| * limit_price * contract_multiplier
        """
        qty = abs(decision.quantity)
        price = decision.limit_price or 0.0
        multiplier = decision.contract_multiplier or 100
        return qty * price * multiplier

    def _execute_single_decision(
        self,
        decision: TradingDecision,
        account_state: AccountState | None,
        dry_run: bool,
    ) -> OrderRecord | list[OrderRecord] | None:
        """执行单个决策

        Args:
            decision: 决策
            account_state: 账户状态
            dry_run: 是否仅模拟

        Returns:
            订单记录（单个或列表），或 None（如果决策不可执行）
            - 普通决策返回单个 OrderRecord
            - ROLL 决策返回 list[OrderRecord]（平仓 + 开仓）
        """
        from src.business.trading.models.decision import DecisionType

        # 过滤不可执行的决策
        if not self._is_executable_decision(decision):
            logger.info(
                f"Skipping non-executable decision: {decision.decision_id} "
                f"(symbol={decision.symbol}, type={decision.decision_type.value}, qty={decision.quantity})"
            )
            return None

        # ROLL 决策需要特殊处理（生成两个订单）
        if decision.decision_type == DecisionType.ROLL:
            return self._execute_roll_decision(decision, account_state, dry_run)

        # 创建订单
        order = self._order_manager.create_order(decision)

        # 验证订单
        validation = self._order_manager.validate_order(
            order,
            account_state,
            current_mid_price=decision.limit_price,
        )

        if not validation.passed:
            logger.warning(
                f"Order {order.order_id} failed validation: "
                f"{validation.failed_checks}"
            )
            # 保存失败的订单记录
            record = OrderRecord(order=order)
            record.add_status_history(
                OrderStatus.VALIDATION_FAILED,
                f"Validation failed: {validation.failed_checks}",
            )
            return record

        if dry_run:
            logger.info(f"[DRY-RUN] Would submit order: {order.order_id}")
            record = OrderRecord(order=order)
            record.add_status_history(
                OrderStatus.APPROVED,
                "Dry-run: order validated but not submitted",
            )
            return record

        # 提交订单
        record = self._order_manager.submit_order(order)
        return record

    def _execute_roll_decision(
        self,
        decision: TradingDecision,
        account_state: AccountState | None,
        dry_run: bool,
    ) -> list[OrderRecord]:
        """执行 ROLL 决策（生成两个订单：平仓 + 开仓）

        Args:
            decision: ROLL 类型的决策
            account_state: 账户状态
            dry_run: 是否仅模拟

        Returns:
            订单记录列表 [close_record, open_record]
        """
        # 1. 创建 ROLL 订单（平仓 + 开仓）
        orders = self._order_manager.create_roll_orders(decision)
        close_order, open_order = orders

        logger.info(
            f"Roll orders created for {decision.symbol}: "
            f"close={close_order.order_id}, open={open_order.order_id}"
        )

        # 2. 验证两个订单
        records: list[OrderRecord] = []
        all_validated = True

        for order in orders:
            validation = self._order_manager.validate_order(
                order,
                account_state,
                current_mid_price=decision.limit_price,
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

        # 如果任一订单验证失败，返回失败记录
        if not all_validated:
            # 补充未处理的订单记录
            for order in orders:
                if not any(r.order.order_id == order.order_id for r in records):
                    record = OrderRecord(order=order)
                    record.add_status_history(
                        OrderStatus.CANCELLED,
                        "Cancelled: other order in roll failed validation",
                    )
                    records.append(record)
            return records

        # 3. Dry-run 模式
        if dry_run:
            for order in orders:
                logger.info(f"[DRY-RUN] Would submit roll order: {order.order_id}")
                record = OrderRecord(order=order)
                record.add_status_history(
                    OrderStatus.APPROVED,
                    "Dry-run: roll order validated but not submitted",
                )
                records.append(record)
            return records

        # 4. 提交 ROLL 订单（先平仓，后开仓）
        records = self._order_manager.submit_roll_orders(orders)

        logger.info(
            f"Roll orders submitted for {decision.symbol}: "
            f"close={records[0].order.status.value}, "
            f"open={records[1].order.status.value if len(records) > 1 else 'N/A'}"
        )

        return records

    def _is_executable_decision(self, decision: TradingDecision) -> bool:
        """检查决策是否可执行

        不可执行的决策包括:
        - symbol 是 "portfolio" 或 "account"（组合级别建议，无具体交易操作）
        - quantity 是 0（无交易数量）
        - decision_type 是 HOLD（持有不操作）

        Args:
            decision: 交易决策

        Returns:
            True 如果可执行，False 如果应跳过
        """
        from src.business.trading.models.decision import DecisionType

        # 组合/账户级别的决策不可执行
        if decision.symbol in ("portfolio", "account"):
            return False

        # 数量为 0 的决策不可执行
        if decision.quantity == 0:
            return False

        # HOLD 类型不可执行
        if decision.decision_type == DecisionType.HOLD:
            return False

        return True

    def get_pending_decisions(self) -> list[TradingDecision]:
        """获取待执行的决策

        从最近的订单记录中提取未完成的决策。
        """
        # 简化实现: 返回空列表
        # 实际应该从存储中读取
        return []

    def get_order_status(self, order_id: str) -> OrderRecord | None:
        """获取订单状态"""
        return self._order_manager.get_order_status(order_id)

    def get_open_orders(self) -> list[OrderRecord]:
        """获取所有未完成订单"""
        return self._order_manager.get_open_orders()

    def get_recent_orders(self, days: int = 7) -> list[OrderRecord]:
        """获取最近订单"""
        return self._order_manager.get_recent_orders(days)

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        return self._order_manager.cancel_order(order_id)

    def sync_order_status(self, order_id: str) -> OrderRecord | None:
        """同步订单状态"""
        return self._order_manager.sync_order_status(order_id)

    def get_system_status(self) -> dict[str, Any]:
        """获取系统状态"""
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
        """获取每日限额使用情况

        Args:
            nlv: 账户净值

        Returns:
            {underlying: {qty_used, qty_limit, value_used, value_limit_pct, value_pct}}
        """
        return self._daily_tracker.get_usage_summary(nlv)

    @property
    def daily_limits_enabled(self) -> bool:
        """每日限额是否启用"""
        return self._daily_limits_config.enabled
