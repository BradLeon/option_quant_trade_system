"""
Conflict Resolver - 冲突解决

解决多个交易决策之间的冲突。

规则:
1. 平仓决策优先于开仓决策
2. 同一标的只允许一个动作
3. 按优先级排序: CRITICAL > HIGH > NORMAL > LOW
"""

import logging
from collections import defaultdict

from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.models.decision import (
    AccountState,
    DecisionPriority,
    DecisionType,
    TradingDecision,
)

logger = logging.getLogger(__name__)


# 优先级排序
PRIORITY_ORDER = {
    DecisionPriority.CRITICAL: 4,
    DecisionPriority.HIGH: 3,
    DecisionPriority.NORMAL: 2,
    DecisionPriority.LOW: 1,
}

# 决策类型排序 (平仓 > 开仓)
TYPE_ORDER = {
    DecisionType.CLOSE: 5,
    DecisionType.ROLL: 4,
    DecisionType.ADJUST: 3,
    DecisionType.HEDGE: 2,
    DecisionType.OPEN: 1,
    DecisionType.HOLD: 0,
}


class ConflictResolver:
    """冲突解决器

    解决多个交易决策之间的冲突。

    Usage:
        resolver = ConflictResolver()
        resolved = resolver.resolve(decisions, account_state)
    """

    def __init__(self, config: DecisionConfig | None = None) -> None:
        """初始化冲突解决器

        Args:
            config: 决策配置
        """
        self._config = config or DecisionConfig.load()

    def resolve(
        self,
        decisions: list[TradingDecision],
        account_state: AccountState | None = None,
    ) -> list[TradingDecision]:
        """解决决策冲突

        Args:
            decisions: 原始决策列表
            account_state: 账户状态

        Returns:
            解决冲突后的决策列表
        """
        # TODO, 参数account_state没用上。
        if not decisions:
            return []

        # Step 1: 过滤掉 HOLD 类型
        active_decisions = [
            d for d in decisions if d.decision_type != DecisionType.HOLD
        ]

        if not active_decisions:
            return []

        # Step 2: 按标的分组
        if self._config.single_action_per_underlying:
            active_decisions = self._resolve_by_underlying(active_decisions)

        # Step 3: 排序
        sorted_decisions = self._sort_decisions(active_decisions)

        # Step 4: 如果配置了平仓优先，确保平仓在前
        # TODO, 前面的配置已经保证平仓的优先级了，这里step4没有必要。
        if self._config.close_before_open:
            sorted_decisions = self._prioritize_close(sorted_decisions)

        logger.info(
            f"Resolved {len(decisions)} decisions to {len(sorted_decisions)}"
        )

        return sorted_decisions

    def _resolve_by_underlying(
        self, decisions: list[TradingDecision]
    ) -> list[TradingDecision]:
        """按标的解决冲突

        同一标的只保留一个最高优先级的决策。
        """
        by_underlying: dict[str, list[TradingDecision]] = defaultdict(list)

        for decision in decisions:
            underlying = decision.underlying or decision.symbol
            by_underlying[underlying].append(decision)

        result = []
        for underlying, group in by_underlying.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                # 多个决策，选择最高优先级
                winner = self._select_winner(group)
                result.append(winner)
                logger.debug(
                    f"Underlying {underlying}: selected {winner.decision_id} "
                    f"({winner.decision_type.value}, {winner.priority.value}) "
                    f"from {len(group)} candidates"
                )

        return result

    def _select_winner(
        self, decisions: list[TradingDecision]
    ) -> TradingDecision:
        """从多个决策中选择获胜者

        规则:
        1. 优先选择平仓类型
        2. 同类型选择更高优先级
        3. 同优先级选择更早的
        """

        def sort_key(d: TradingDecision) -> tuple:
            type_score = TYPE_ORDER.get(d.decision_type, 0)
            priority_score = PRIORITY_ORDER.get(d.priority, 0)
            # 负数表示降序
            return (-type_score, -priority_score, d.timestamp)

        sorted_decisions = sorted(decisions, key=sort_key)
        return sorted_decisions[0]

    def _sort_decisions(
        self, decisions: list[TradingDecision]
    ) -> list[TradingDecision]:
        """排序决策

        排序规则:
        1. 优先级: CRITICAL > HIGH > NORMAL > LOW
        2. 类型: CLOSE > ROLL > ADJUST > HEDGE > OPEN
        3. 时间: 早的在前
        """

        def sort_key(d: TradingDecision) -> tuple:
            priority_score = PRIORITY_ORDER.get(d.priority, 0)
            type_score = TYPE_ORDER.get(d.decision_type, 0)
            return (-priority_score, -type_score, d.timestamp)

        return sorted(decisions, key=sort_key)

    def _prioritize_close(
        self, decisions: list[TradingDecision]
    ) -> list[TradingDecision]:
        """确保平仓决策在开仓决策之前

        这样可以先释放保证金，再开新仓。
        """
        close_types = {DecisionType.CLOSE, DecisionType.ROLL, DecisionType.ADJUST}
        open_types = {DecisionType.OPEN, DecisionType.HEDGE}

        close_decisions = [d for d in decisions if d.decision_type in close_types]
        open_decisions = [d for d in decisions if d.decision_type in open_types]
        other_decisions = [
            d for d in decisions
            if d.decision_type not in close_types
            and d.decision_type not in open_types
        ]

        return close_decisions + other_decisions + open_decisions

    def check_conflict(
        self,
        new_decision: TradingDecision,
        existing_decisions: list[TradingDecision],
    ) -> tuple[bool, str | None]:
        """检查新决策是否与现有决策冲突

        Args:
            new_decision: 新决策
            existing_decisions: 现有决策列表

        Returns:
            (has_conflict, conflict_reason)
        """
        underlying = new_decision.underlying or new_decision.symbol

        for existing in existing_decisions:
            existing_underlying = existing.underlying or existing.symbol

            if existing_underlying == underlying:
                return True, (
                    f"Conflict with existing decision {existing.decision_id} "
                    f"on {underlying}"
                )

        return False, None
