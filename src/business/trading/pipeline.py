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
        trading_provider: TradingProvider | None = None,
    ) -> None:
        """初始化交易流水线

        Args:
            decision_config: 决策配置
            order_config: 订单配置
            risk_config: 风控配置
            trading_provider: 交易提供者 (可选，后续设置)
        """
        self._decision_config = decision_config or DecisionConfig.load()
        self._order_config = order_config or OrderConfig.load()
        self._risk_config = risk_config or RiskConfig.load()

        self._decision_engine = DecisionEngine(self._decision_config)
        self._order_manager = OrderManager(
            config=self._order_config,
            risk_config=self._risk_config,
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
            account_state: 账户状态 (用于风控)
            dry_run: 是否仅模拟 (不实际下单)

        Returns:
            订单记录列表
        """
        if not self.is_connected and not dry_run:
            raise RuntimeError("Trading pipeline not connected")

        results: list[OrderRecord] = []

        for decision in decisions:
            try:
                record = self._execute_single_decision(
                    decision, account_state, dry_run
                )
                if record:
                    results.append(record)
            except Exception as e:
                logger.error(
                    f"Failed to execute decision {decision.decision_id}: {e}"
                )

        logger.info(
            f"Executed {len(results)} decisions "
            f"({'dry-run' if dry_run else 'live'})"
        )
        return results

    def _execute_single_decision(
        self,
        decision: TradingDecision,
        account_state: AccountState | None,
        dry_run: bool,
    ) -> OrderRecord | None:
        """执行单个决策

        Args:
            decision: 决策
            account_state: 账户状态
            dry_run: 是否仅模拟

        Returns:
            订单记录，或 None（如果决策不可执行）
        """
        # 过滤不可执行的决策
        if not self._is_executable_decision(decision):
            logger.info(
                f"Skipping non-executable decision: {decision.decision_id} "
                f"(symbol={decision.symbol}, type={decision.decision_type.value}, qty={decision.quantity})"
            )
            return None

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
