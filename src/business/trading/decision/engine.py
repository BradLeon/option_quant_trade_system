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

from src.business.monitoring.suggestions import (
    ActionType,
    PositionSuggestion,
    UrgencyLevel,
)
from src.business.screening.models import ContractOpportunity, ScreeningResult
from src.business.trading.config.decision_config import DecisionConfig
from src.data.utils.symbol_formatter import SymbolFormatter
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
        decisions = engine.process_batch(screen_result, account_state, suggestions)
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
        # 从期权符号中提取标的 (e.g., "NVDA 250228P00100000" -> "NVDA")
        underlying = opportunity.symbol.split()[0] if " " in opportunity.symbol else opportunity.symbol
        notional = (opportunity.strike or 0) * opportunity.lot_size  # 估算名义价值
        within_limit, reason = self._analyzer.check_underlying_exposure(
            account_state, underlying, notional
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
        # 根据 symbol 推断 currency
        underlying = opportunity.symbol.split()[0] if " " in opportunity.symbol else opportunity.symbol
        ibkr_params = SymbolFormatter.to_ibkr_contract(underlying)

        decision = TradingDecision(
            decision_id=self._generate_decision_id(),
            decision_type=DecisionType.OPEN,
            source=DecisionSource.SCREEN_SIGNAL,
            priority=DecisionPriority.NORMAL,
            symbol=opportunity.symbol,
            underlying=underlying,
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
            contract_multiplier=opportunity.lot_size,
            currency=ibkr_params.currency,
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
    ) -> TradingDecision:
        """处理监控调整信号

        Args:
            suggestion: 调整建议
            account_state: 账户状态
            position_context: 持仓上下文

        Returns:
            TradingDecision (包括 HOLD 类型，确保健壮性)
        """
        # 映射动作类型
        decision_type = ACTION_TO_DECISION.get(
            suggestion.action, DecisionType.HOLD
        )

        # 映射优先级
        priority = URGENCY_TO_PRIORITY.get(
            suggestion.urgency, DecisionPriority.NORMAL
        )

        # 从 metadata 获取期权信息
        metadata = suggestion.metadata or {}
        underlying = metadata.get("underlying") or suggestion.symbol.split()[0]

        # 根据 underlying 推断 currency
        ibkr_params = SymbolFormatter.to_ibkr_contract(underlying)

        # 确定数量 (Monitor 信号支持 CLOSE/REDUCE/ROLL 等多种动作)
        quantity = self._determine_close_quantity(suggestion, position_context)

        # 确定价格类型:
        # - CLOSE/ROLL 等紧急操作 (IMMEDIATE urgency) 使用市价单
        # - HOLD 和非紧急操作使用中间价
        if decision_type in (DecisionType.CLOSE, DecisionType.ROLL, DecisionType.ADJUST) \
                and suggestion.urgency == UrgencyLevel.IMMEDIATE:
            price_type = "market"
        else:
            price_type = self._config.default_price_type

        # trading_class (for HK options)
        trading_class = metadata.get("trading_class")
        con_id = metadata.get("con_id")  # IBKR contract ID

        # 展期参数 (仅 ROLL 类型)
        roll_to_expiry = None
        roll_to_strike = None
        roll_credit = None
        if decision_type == DecisionType.ROLL:
            roll_to_expiry = metadata.get("suggested_expiry")
            roll_to_strike = metadata.get("suggested_strike")  # 可选，None 表示保持不变
            roll_credit = metadata.get("roll_credit")

        decision = TradingDecision(
            decision_id=self._generate_decision_id(),
            decision_type=decision_type,
            source=DecisionSource.MONITOR_ALERT,
            priority=priority,
            symbol=suggestion.symbol,
            underlying=underlying,
            option_type=metadata.get("option_type"),
            strike=metadata.get("strike"),
            expiry=metadata.get("expiry"),
            trading_class=trading_class,  # For HK options (e.g., "ALB" for 9988)
            con_id=con_id,  # IBKR contract ID
            quantity=quantity,
            price_type=price_type,
            account_state=account_state,
            position_context=position_context,
            reason=suggestion.reason,
            trigger_alerts=[a.message for a in suggestion.trigger_alerts],
            broker=self._config.default_broker,
            contract_multiplier=metadata.get("lot_size", 100),
            currency=ibkr_params.currency,
            roll_to_expiry=roll_to_expiry,
            roll_to_strike=roll_to_strike,
            roll_credit=roll_credit,
            timestamp=datetime.now(),
        )

        logger.info(
            f"Generated {decision_type.value.upper()} decision: "
            f"{decision.decision_id} for {suggestion.symbol}, "
            f"priority={priority.value}, price_type={price_type}"
            + (f", roll_to={roll_to_expiry}" if roll_to_expiry else "")
        )

        return decision

    def process_batch(
        self,
        screen_result: ScreeningResult | None,
        account_state: AccountState,
        suggestions: list[PositionSuggestion] | None = None,
    ) -> list[TradingDecision]:
        """批量处理信号

        Args:
            screen_result: 筛选结果
            account_state: 账户状态
            suggestions: Monitor 调整建议列表

        Returns:
            解决冲突后的决策列表
        """
        all_decisions: list[TradingDecision] = []

        # 处理 Monitor 信号 (优先，因为可能需要平仓)
        # process_monitor_signal 总是返回 TradingDecision (包括 HOLD)
        # HOLD 类型会在 conflict resolution 阶段被过滤
        if suggestions:
            for suggestion in suggestions:
                decision = self.process_monitor_signal(
                    suggestion, account_state
                )
                all_decisions.append(decision)

        # 处理 Screen 信号
        if screen_result and screen_result.confirmed:
            # 每个 (underlying, option_type) 只选 annual_roc 最高的合约
            best_opportunities = self._select_best_opportunities(screen_result.confirmed)

            for opportunity in best_opportunities:
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
        """构建开仓原因

        通过三层筛选意味着各项指标均无短板，此处列出关键指标供参考。
        """
        parts = ["通过三层筛选"]

        if opportunity.expected_roc:
            parts.append(f"ROC={opportunity.expected_roc:.1%}")

        if opportunity.win_probability:
            parts.append(f"胜率={opportunity.win_probability:.0%}")

        if opportunity.kelly_fraction:
            parts.append(f"Kelly={opportunity.kelly_fraction:.2f}")

        if opportunity.delta:
            parts.append(f"Δ={opportunity.delta:.2f}")

        if opportunity.theta:
            parts.append(f"Θ={opportunity.theta:.2f}")

        return " | ".join(parts)

    def _determine_close_quantity(
        self,
        suggestion: PositionSuggestion,
        position_context: PositionContext | None,
    ) -> int:
        """确定平仓数量

        优先级:
        1. 从 position_context 获取 (最准确)
        2. 从 suggestion.metadata 获取 (备用)
           - "quantity" 或 "current_position"
        3. 返回 0 (需要后续查询补充)
        """
        # 优先从 position_context 获取
        if position_context:
            qty = position_context.quantity
            # 平仓方向与持仓方向相反
            return -int(qty) if qty != 0 else 0

        # 备用: 从 metadata 获取
        metadata = suggestion.metadata or {}
        qty = metadata.get("quantity") or metadata.get("current_position")
        if qty is not None:
            # 平仓方向与持仓方向相反
            return -int(qty) if qty != 0 else 0

        # 如果都没有，返回 0
        # 注：对于 portfolio 级别建议或 HOLD/MONITOR 类型，无数量是正常的
        if suggestion.symbol not in ("portfolio", "account") and \
                suggestion.action not in (ActionType.HOLD, ActionType.MONITOR, ActionType.REVIEW):
            logger.warning(
                f"No quantity available for {suggestion.symbol}, "
                "position_context and metadata['quantity'/'current_position'] both missing"
            )
        return 0

    def _select_best_opportunities(
        self,
        opportunities: list[ContractOpportunity],
    ) -> list[ContractOpportunity]:
        """每个 (underlying, option_type) 只选 annual_roc 最高的合约

        当同一标的有多个满足条件的合约时，只选择年化收益率最高的那个，
        避免在同一标的上开设过多仓位。

        Args:
            opportunities: 所有通过筛选的合约机会

        Returns:
            去重后的合约列表，每个 (underlying, option_type) 只保留一个
        """
        from collections import defaultdict

        # 按 (underlying, option_type) 分组
        groups: dict[tuple[str, str], list[ContractOpportunity]] = defaultdict(list)
        for opp in opportunities:
            # 从 symbol 提取 underlying (e.g., "GOOG 250213P00310000" -> "GOOG")
            underlying = opp.symbol.split()[0] if " " in opp.symbol else opp.symbol
            key = (underlying, opp.option_type or "unknown")
            groups[key].append(opp)

        # 每组选 annual_roc 最高的
        best: list[ContractOpportunity] = []
        for key, group in groups.items():
            sorted_group = sorted(
                group,
                key=lambda x: x.annual_roc or 0,
                reverse=True
            )
            best.append(sorted_group[0])

            if len(group) > 1:
                selected = sorted_group[0]
                ann_roc = selected.annual_roc or 0
                logger.info(
                    f"Selected best contract for {key[0]} {key[1]}: "
                    f"K={selected.strike} Exp={selected.expiry} "
                    f"(AnnROC={ann_roc:.1%}), skipped {len(group) - 1} others"
                )

        return best
