"""
Decision Engine - 决策引擎

信号接收 → 账户分析 → 仓位计算 → 冲突解决 → 决策输出

输入:
- ContractOpportunity (from Screen)
- PositionSuggestion (from Monitor)
- AccountState

输出:
- TradingDecision
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from src.business.monitoring.models import MonitorResult
from src.business.monitoring.suggestions import (
    ActionType,
    PositionSuggestion,
    UrgencyLevel,
)
from src.business.screening.models import ContractOpportunity, ScreeningResult
from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.decision.account_analyzer import AccountStateAnalyzer
from src.business.trading.decision.conflict_resolver import ConflictResolver
from src.business.trading.decision.position_sizer import PositionSizer
from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionSource,
    DecisionType,
    PositionContext,
    TradingDecision,
)

logger = logging.getLogger(__name__)


# ActionType -> DecisionType 映射
ACTION_TO_DECISION: dict[ActionType, DecisionType] = {
    ActionType.CLOSE: DecisionType.CLOSE,
    ActionType.REDUCE: DecisionType.ADJUST,
    ActionType.ROLL: DecisionType.ROLL,
    ActionType.HEDGE: DecisionType.HEDGE,
    ActionType.ADJUST: DecisionType.ADJUST,
    ActionType.TAKE_PROFIT: DecisionType.CLOSE,
    ActionType.HOLD: DecisionType.HOLD,
    ActionType.MONITOR: DecisionType.HOLD,
    ActionType.SET_STOP: DecisionType.HOLD,
    ActionType.REVIEW: DecisionType.HOLD,
    ActionType.DIVERSIFY: DecisionType.HOLD,
}

# UrgencyLevel -> DecisionPriority 映射
URGENCY_TO_PRIORITY: dict[UrgencyLevel, DecisionPriority] = {
    UrgencyLevel.IMMEDIATE: DecisionPriority.CRITICAL,
    UrgencyLevel.SOON: DecisionPriority.HIGH,
    UrgencyLevel.MONITOR: DecisionPriority.NORMAL,
}


class DecisionEngine:
    """决策引擎

    将 Screen 和 Monitor 信号转换为交易决策。

    Usage:
        engine = DecisionEngine()
        decisions = engine.process_batch(screen_result, monitor_result, account_state)
    """

    def __init__(
        self,
        config: DecisionConfig | None = None,
        account_analyzer: AccountStateAnalyzer | None = None,
        position_sizer: PositionSizer | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> None:
        """初始化决策引擎

        Args:
            config: 决策配置
            account_analyzer: 账户状态分析器
            position_sizer: 仓位计算器
            conflict_resolver: 冲突解决器
        """
        self._config = config or DecisionConfig.load()
        self._analyzer = account_analyzer or AccountStateAnalyzer(self._config)
        self._sizer = position_sizer or PositionSizer(self._config)
        self._resolver = conflict_resolver or ConflictResolver(self._config)

    def process_screen_signal(
        self,
        opportunity: ContractOpportunity,
        account_state: AccountState,
    ) -> TradingDecision | None:
        """处理开仓信号

        Args:
            opportunity: 合约机会
            account_state: 账户状态

        Returns:
            TradingDecision 或 None (如果不满足开仓条件)
        """
        # 检查是否可以开仓
        can_open, reasons = self._analyzer.can_open_position(account_state)

        if not can_open:
            logger.warning(
                f"Cannot open position for {opportunity.symbol}: {reasons}"
            )
            return None

        # 检查标的暴露
         # TODO，不要使用固定的100，要用OptionContract.lot_size or Position.contract_multip
        notional = (opportunity.strike or 0) * 100  # 估算名义价值
        within_limit, reason = self._analyzer.check_underlying_exposure(
            account_state, opportunity.symbol, notional
        )

        if not within_limit:
            logger.warning(
                f"Underlying exposure limit for {opportunity.symbol}: {reason}"
            )
            return None

        # 计算仓位大小
        quantity = self._sizer.calculate_size(opportunity, account_state)

        if quantity <= 0:
            logger.warning(f"Calculated position size is 0 for {opportunity.symbol}")
            return None

        # 创建决策
      
        decision = TradingDecision(
            decision_id=self._generate_decision_id(),
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol=opportunity.symbol,
            underlying=opportunity.symbol.split()[0] if " " in opportunity.symbol else opportunity.symbol,
            option_type=opportunity.option_type,
            strike=opportunity.strike,
            expiry=opportunity.expiry,
            trading_class=opportunity.trading_class,
            quantity=-quantity,  # 卖出期权为负
            recommended_position_size=float(quantity),
            limit_price=opportunity.mid_price,
            price_type=self._config.default_price_type,
            account_state=account_state,
            reason=self._build_open_reason(opportunity),
            broker=self._config.default_broker,
            timestamp=datetime.now(),
        )

        logger.info(
            f"Generated OPEN decision: {decision.decision_id} "
            f"for {opportunity.symbol}, qty={quantity}"
        )

        return decision

    def process_monitor_signal(
        self,
        suggestion: PositionSuggestion,
        account_state: AccountState,
        position_context: PositionContext | None = None,
    ) -> TradingDecision | None:
        """处理监控调整信号

        Args:
            suggestion: 调整建议
            account_state: 账户状态
            position_context: 持仓上下文

        Returns:
            TradingDecision 或 None
        """
        # 映射动作类型
        decision_type = ACTION_TO_DECISION.get(
            suggestion.action, DecisionType.HOLD
        )

        if decision_type == DecisionType.HOLD:
            logger.debug(
                f"Suggestion {suggestion.action.value} for {suggestion.symbol} "
                "maps to HOLD, skipping"
            )
            return None

        # 映射优先级
        priority = URGENCY_TO_PRIORITY.get(
            suggestion.urgency, DecisionPriority.NORMAL
        )

        # 确定数量
        # TODO, Monitor给出的一定是平仓数量吗？ 有无可能减仓？
        quantity = self._determine_close_quantity(suggestion, position_context)

        # 从 metadata 获取期权信息
        metadata = suggestion.metadata or {}

        # TODO, 不限价吗？(平仓用市价单？) 是默认Monitor_signal只有平仓一种订单吗？ 
        decision = TradingDecision(
            decision_id=self._generate_decision_id(),
            decision_type=decision_type,
            source=DecisionSource.MONITOR_ALERT,
            priority=priority,
            symbol=suggestion.symbol,
            underlying=metadata.get("underlying"),
            option_type=metadata.get("option_type"),
            strike=metadata.get("strike"),
            expiry=metadata.get("expiry"),
            quantity=quantity,
            account_state=account_state,
            position_context=position_context,
            reason=suggestion.reason,
            trigger_alerts=[a.message for a in suggestion.trigger_alerts],
            broker=self._config.default_broker,
            timestamp=datetime.now(),
        )

        logger.info(
            f"Generated {decision_type.value.upper()} decision: "
            f"{decision.decision_id} for {suggestion.symbol}, "
            f"priority={priority.value}"
        )

        return decision

    def process_batch(
        self,
        screen_result: ScreeningResult | None,
        monitor_result: MonitorResult | None,
        account_state: AccountState,
        suggestions: list[PositionSuggestion] | None = None,
    ) -> list[TradingDecision]:
        """批量处理信号

        Args:
            screen_result: 筛选结果
            monitor_result: 监控结果 (用于获取位置上下文)
            account_state: 账户状态
            suggestions: 调整建议列表 (可选，如果不提供则从 monitor_result 生成)

        Returns:
            解决冲突后的决策列表
        """
        all_decisions: list[TradingDecision] = []
        # TODO, 看来monitor_result并没用上

        # 处理 Monitor 信号 (优先，因为可能需要平仓)
        if suggestions:
            for suggestion in suggestions:
                decision = self.process_monitor_signal(
                    suggestion, account_state
                )
                if decision:
                    all_decisions.append(decision)

        # 处理 Screen 信号
        if screen_result and screen_result.confirmed:
            for opportunity in screen_result.confirmed:
                decision = self.process_screen_signal(
                    opportunity, account_state
                )
                if decision:
                    all_decisions.append(decision)

        # 解决冲突
        resolved = self._resolver.resolve(all_decisions, account_state)

        logger.info(
            f"Batch processing: {len(all_decisions)} decisions generated, "
            f"{len(resolved)} after conflict resolution"
        )

        return resolved

    def _generate_decision_id(self) -> str:
        """生成决策 ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:8]
        return f"DEC-{timestamp}-{unique}"

    def _build_open_reason(self, opportunity: ContractOpportunity) -> str:
        """构建开仓原因"""
        parts = []
        # TODO, 开仓原因是因为没有被三道过滤系统筛掉，而不是哪个指标高，所以开仓原因是没有短板，不太好写。
        if opportunity.expected_roc:
            parts.append(f"Expected ROC={opportunity.expected_roc:.1%}")

        if opportunity.win_probability:
            parts.append(f"WinProb={opportunity.win_probability:.0%}")

        if opportunity.kelly_fraction:
            parts.append(f"Kelly={opportunity.kelly_fraction:.2f}")

        if opportunity.delta:
            parts.append(f"Delta={opportunity.delta:.2f}")

        if opportunity.theta:
            parts.append(f"Theta={opportunity.theta:.2f}")

        return "Screen confirmed: " + ", ".join(parts)

    def _determine_close_quantity(
        self,
        suggestion: PositionSuggestion,
        position_context: PositionContext | None,
    ) -> int:
        """确定平仓数量"""
        if position_context:
            qty = position_context.quantity
            # 平仓方向与持仓方向相反
            return -int(qty) if qty != 0 else 0

        # 如果没有持仓上下文，返回 0 (需要后续查询)
        return 0
