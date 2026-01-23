"""Suggestion Generator - 调整建议生成

将监控 Alert 转换为可执行的调整建议。

基于三层指标体系（Portfolio/Position/Capital Level）和 ALERT_ACTION_MAP 配置。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    PositionData,
)
from src.engine.models.enums import StrategyType

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """建议动作类型"""

    HOLD = "hold"  # 继续持有
    MONITOR = "monitor"  # 密切关注
    CLOSE = "close"  # 平仓
    REDUCE = "reduce"  # 减仓
    ROLL = "roll"  # 展期
    HEDGE = "hedge"  # 对冲
    ADJUST = "adjust"  # 调整策略
    SET_STOP = "set_stop"  # 设置止损
    REVIEW = "review"  # 复盘评估
    DIVERSIFY = "diversify"  # 分散化
    TAKE_PROFIT = "take_profit"  # 止盈


class UrgencyLevel(str, Enum):
    """紧急程度"""

    IMMEDIATE = "immediate"  # 立即处理
    SOON = "soon"  # 尽快处理
    MONITOR = "monitor"  # 持续观察


@dataclass
class PositionSuggestion:
    """持仓调整建议"""

    position_id: str
    symbol: str
    action: ActionType
    urgency: UrgencyLevel
    reason: str
    details: str = ""
    trigger_alerts: list[Alert] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# ALERT_ACTION_MAP 配置
# 映射结构: (AlertType, AlertLevel) → (ActionType, UrgencyLevel)
# =============================================================================

ALERT_ACTION_MAP: dict[tuple[AlertType, AlertLevel], tuple[ActionType, UrgencyLevel]] = {
    # === RED Alerts → IMMEDIATE ===
    (AlertType.STOP_LOSS, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.DTE_WARNING, AlertLevel.RED): (ActionType.ROLL, UrgencyLevel.IMMEDIATE),
    (AlertType.MONEYNESS, AlertLevel.RED): (ActionType.ROLL, UrgencyLevel.IMMEDIATE),
    (AlertType.DELTA_CHANGE, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.GAMMA_EXPOSURE, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.TGR_LOW, AlertLevel.RED): (ActionType.ADJUST, UrgencyLevel.IMMEDIATE),
    # Capital 级 - 核心风控四大支柱
    (AlertType.MARGIN_UTILIZATION, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.CASH_RATIO, AlertLevel.RED): (ActionType.HOLD, UrgencyLevel.IMMEDIATE),
    (AlertType.GROSS_LEVERAGE, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.STRESS_TEST_LOSS, AlertLevel.RED): (ActionType.HEDGE, UrgencyLevel.IMMEDIATE),
    (AlertType.CONCENTRATION, AlertLevel.RED): (ActionType.DIVERSIFY, UrgencyLevel.IMMEDIATE),
    (AlertType.DELTA_EXPOSURE, AlertLevel.RED): (ActionType.HEDGE, UrgencyLevel.IMMEDIATE),
    # === YELLOW Alerts → SOON or MONITOR ===
    (AlertType.DTE_WARNING, AlertLevel.YELLOW): (ActionType.ROLL, UrgencyLevel.SOON),
    (AlertType.MONEYNESS, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.DELTA_CHANGE, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.GAMMA_EXPOSURE, AlertLevel.YELLOW): (ActionType.SET_STOP, UrgencyLevel.SOON),
    (AlertType.GAMMA_NEAR_EXPIRY, AlertLevel.YELLOW): (ActionType.ROLL, UrgencyLevel.SOON),
    (AlertType.IV_HV_CHANGE, AlertLevel.YELLOW): (ActionType.REVIEW, UrgencyLevel.MONITOR),
    (AlertType.TGR_LOW, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.VEGA_EXPOSURE, AlertLevel.YELLOW): (ActionType.REDUCE, UrgencyLevel.SOON),
    # Capital 级 - 核心风控四大支柱 YELLOW
    (AlertType.MARGIN_UTILIZATION, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.CASH_RATIO, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.GROSS_LEVERAGE, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.STRESS_TEST_LOSS, AlertLevel.YELLOW): (ActionType.REVIEW, UrgencyLevel.SOON),
    (AlertType.CONCENTRATION, AlertLevel.YELLOW): (ActionType.DIVERSIFY, UrgencyLevel.SOON),
    (AlertType.DELTA_EXPOSURE, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    # === GREEN Alerts → Opportunities ===
    (AlertType.PROFIT_TARGET, AlertLevel.GREEN): (
        ActionType.TAKE_PROFIT,
        UrgencyLevel.SOON,
    ),
    (AlertType.IV_HV_CHANGE, AlertLevel.GREEN): (
        ActionType.HOLD,
        UrgencyLevel.MONITOR,
    ),
}

# =============================================================================
# STRATEGY_SPECIFIC_SUGGESTIONS 配置
# 映射结构: (AlertType, AlertLevel, StrategyType) → (ActionType, UrgencyLevel, suggestion_text)
# 当持仓有 strategy_type 时，优先使用此映射来生成更具针对性的建议
# =============================================================================

STRATEGY_SPECIFIC_SUGGESTIONS: dict[
    tuple[AlertType, AlertLevel, StrategyType],
    tuple[ActionType, UrgencyLevel, str]
] = {
    # === DTE < 7 天 (RED) - 按策略区分 ===
    (AlertType.DTE_WARNING, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.ROLL, UrgencyLevel.IMMEDIATE,
        "强制平仓或展期到下月"
    ),
    (AlertType.DTE_WARNING, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.HOLD, UrgencyLevel.MONITOR,
        "可持有到期（Gamma 风险由正股覆盖）"
    ),
    (AlertType.DTE_WARNING, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.ROLL, UrgencyLevel.IMMEDIATE,
        "强制平仓或双腿同时展期"
    ),

    # === |Delta| > 0.50 (RED) - 按策略区分 ===
    (AlertType.DELTA_CHANGE, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.ROLL, UrgencyLevel.IMMEDIATE,
        "展期到更低 Strike 或平仓止损"
    ),
    (AlertType.DELTA_CHANGE, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.ADJUST, UrgencyLevel.SOON,
        "可接受行权（卖出正股）或展期到更高 Strike"
    ),
    (AlertType.DELTA_CHANGE, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "平仓 Delta 恶化的腿，保留另一腿"
    ),

    # === OTM% < 5% (RED) - 按策略区分 ===
    (AlertType.OTM_PCT, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.ROLL, UrgencyLevel.IMMEDIATE,
        "展期到下月或更低 Strike"
    ),
    (AlertType.OTM_PCT, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.ADJUST, UrgencyLevel.SOON,
        "展期到更高 Strike 或接受行权"
    ),
    (AlertType.OTM_PCT, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.ROLL, UrgencyLevel.IMMEDIATE,
        "展期恶化的腿"
    ),

    # === P&L < -100% (RED) - 按策略区分 ===
    (AlertType.STOP_LOSS, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "无条件平仓止损，不抗单"
    ),
    (AlertType.STOP_LOSS, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "平仓 Call 腿止损"
    ),
    (AlertType.STOP_LOSS, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "平仓亏损腿或整体止损"
    ),

    # === TGR < 1.0 (RED) - 按策略区分 ===
    (AlertType.POSITION_TGR, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "平仓换到更高效的合约"
    ),
    (AlertType.POSITION_TGR, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.CLOSE, UrgencyLevel.SOON,
        "平仓换到更高效的合约"
    ),
    (AlertType.POSITION_TGR, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "平仓换到更高效的合约"
    ),

    # === Gamma Risk > 1% (RED) - 按策略区分 ===
    (AlertType.GAMMA_RISK_PCT, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.ROLL, UrgencyLevel.IMMEDIATE,
        "平仓或展期到更远 Strike"
    ),
    (AlertType.GAMMA_RISK_PCT, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.HOLD, UrgencyLevel.MONITOR,
        "一般不触发（正股覆盖）"
    ),
    (AlertType.GAMMA_RISK_PCT, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "平仓 Put 腿或整体平仓"
    ),

    # === IV/HV < 0.8 (RED) - 按策略区分 ===
    (AlertType.POSITION_IV_HV, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.TAKE_PROFIT, UrgencyLevel.SOON,
        "如盈利可提前止盈，禁止在该标的继续卖出"
    ),
    (AlertType.POSITION_IV_HV, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.TAKE_PROFIT, UrgencyLevel.SOON,
        "如盈利可提前止盈，禁止在该标的继续卖出"
    ),
    (AlertType.POSITION_IV_HV, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.TAKE_PROFIT, UrgencyLevel.SOON,
        "如盈利可提前止盈，禁止在该标的继续卖出"
    ),

    # === Expected ROC < 0% (RED) - 按策略区分 ===
    (AlertType.EXPECTED_ROC_LOW, AlertLevel.RED, StrategyType.SHORT_PUT): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "立即平仓，策略已失效"
    ),
    (AlertType.EXPECTED_ROC_LOW, AlertLevel.RED, StrategyType.COVERED_CALL): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "立即平仓，策略已失效"
    ),
    (AlertType.EXPECTED_ROC_LOW, AlertLevel.RED, StrategyType.SHORT_STRANGLE): (
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "立即平仓，策略已失效"
    ),
}

# 优先级顺序（用于排序）
ALERT_PRIORITY = {
    # RED alerts - 按危险程度
    AlertType.STOP_LOSS: 100,
    # Capital 级 - 核心风控四大支柱
    AlertType.MARGIN_UTILIZATION: 95,  # 生存
    AlertType.CASH_RATIO: 90,  # 流动性
    AlertType.GROSS_LEVERAGE: 85,  # 敞口
    AlertType.STRESS_TEST_LOSS: 80,  # 稳健
    AlertType.MONEYNESS: 75,  # 行权风险
    AlertType.DTE_WARNING: 70,
    AlertType.DELTA_CHANGE: 65,
    AlertType.GAMMA_EXPOSURE: 60,
    AlertType.DELTA_EXPOSURE: 50,
    AlertType.TGR_LOW: 45,
    AlertType.CONCENTRATION: 40,
    # YELLOW alerts
    AlertType.GAMMA_NEAR_EXPIRY: 35,
    AlertType.VEGA_EXPOSURE: 30,
    AlertType.IV_HV_CHANGE: 25,
    # GREEN alerts
    AlertType.PROFIT_TARGET: 10,
}

URGENCY_PRIORITY = {
    UrgencyLevel.IMMEDIATE: 3,
    UrgencyLevel.SOON: 2,
    UrgencyLevel.MONITOR: 1,
}


class SuggestionGenerator:
    """建议生成器

    将监控 Alert 转换为可执行的调整建议。

    Usage:
        >>> generator = SuggestionGenerator()
        >>> suggestions = generator.generate(monitor_result, positions)
    """

    def __init__(
        self,
        action_map: dict[
            tuple[AlertType, AlertLevel], tuple[ActionType, UrgencyLevel]
        ]
        | None = None,
        vix_high_threshold: float = 25.0,
        vix_extreme_threshold: float = 35.0,
    ):
        """初始化建议生成器

        Args:
            action_map: 自定义 Alert → Action 映射
            vix_high_threshold: VIX 高波动阈值
            vix_extreme_threshold: VIX 极端波动阈值
        """
        self._action_map = action_map or ALERT_ACTION_MAP
        self._vix_high = vix_high_threshold
        self._vix_extreme = vix_extreme_threshold

    def generate(
        self,
        monitor_result: MonitorResult,
        positions: list[PositionData] | None = None,
        vix: float | None = None,
    ) -> list[PositionSuggestion]:
        """主入口：生成调整建议

        Args:
            monitor_result: 监控结果（包含 alerts）
            positions: 持仓数据列表（用于获取额外上下文）
            vix: 当前 VIX 值（用于市场环境调整）

        Returns:
            排序后的 PositionSuggestion 列表
        """
        if not monitor_result.alerts:
            return []

        # Step 1: 按 position_id 分组 alerts
        grouped_alerts = self._group_alerts_by_position(monitor_result.alerts)

        # Step 2: 为每个持仓生成建议
        suggestions = []
        for position_id, alerts in grouped_alerts.items():
            suggestion = self._generate_for_position(position_id, alerts, positions)
            if suggestion:
                suggestions.append(suggestion)

        # Step 3: 市场环境调整
        if vix:
            suggestions = self._adjust_for_market(suggestions, vix)

        # Step 4: 按优先级排序
        suggestions = self._sort_by_priority(suggestions)

        return suggestions

    def _group_alerts_by_position(
        self, alerts: list[Alert]
    ) -> dict[str, list[Alert]]:
        """按 position_id 分组 alerts

        Args:
            alerts: Alert 列表

        Returns:
            position_id -> alerts 的映射
        """
        grouped: dict[str, list[Alert]] = {}
        for alert in alerts:
            position_id = alert.position_id or alert.symbol or "portfolio"
            if position_id not in grouped:
                grouped[position_id] = []
            grouped[position_id].append(alert)
        return grouped

    def _get_highest_priority_alert(self, alerts: list[Alert]) -> Alert:
        """从多个 alert 中选取最高优先级

        优先级规则：
        1. AlertLevel: RED > YELLOW > GREEN
        2. 同级别内按 ALERT_PRIORITY 排序

        Args:
            alerts: Alert 列表

        Returns:
            最高优先级的 Alert
        """
        level_priority = {
            AlertLevel.RED: 3,
            AlertLevel.YELLOW: 2,
            AlertLevel.GREEN: 1,
        }

        def alert_sort_key(alert: Alert) -> tuple[int, int]:
            level_score = level_priority.get(alert.level, 0)
            type_score = ALERT_PRIORITY.get(alert.alert_type, 0)
            return (-level_score, -type_score)  # 负数使得高优先级排在前面

        sorted_alerts = sorted(alerts, key=alert_sort_key)
        return sorted_alerts[0]

    def _generate_for_position(
        self,
        position_id: str,
        alerts: list[Alert],
        positions: list[PositionData] | None,
    ) -> PositionSuggestion | None:
        """为单个持仓生成建议

        优先查找策略特定建议（STRATEGY_SPECIFIC_SUGGESTIONS），
        若无则使用通用映射（ALERT_ACTION_MAP）。

        Args:
            position_id: 持仓 ID
            alerts: 该持仓的 alerts
            positions: 所有持仓数据

        Returns:
            PositionSuggestion 或 None
        """
        if not alerts:
            return None

        # 获取最高优先级 alert
        primary_alert = self._get_highest_priority_alert(alerts)

        # 获取策略类型
        strategy_type: StrategyType | None = None
        if positions:
            pos = next((p for p in positions if p.position_id == position_id), None)
            if pos:
                strategy_type = pos.strategy_type

        # 优先查找策略特定建议
        suggestion_text: str | None = None
        if strategy_type:
            strategy_key = (primary_alert.alert_type, primary_alert.level, strategy_type)
            if strategy_key in STRATEGY_SPECIFIC_SUGGESTIONS:
                action, urgency, suggestion_text = STRATEGY_SPECIFIC_SUGGESTIONS[strategy_key]
            else:
                # 回退到通用映射
                key = (primary_alert.alert_type, primary_alert.level)
                if key in self._action_map:
                    action, urgency = self._action_map[key]
                else:
                    action = ActionType.MONITOR
                    urgency = UrgencyLevel.MONITOR
        else:
            # 无策略类型，使用通用映射
            key = (primary_alert.alert_type, primary_alert.level)
            if key in self._action_map:
                action, urgency = self._action_map[key]
            else:
                action = ActionType.MONITOR
                urgency = UrgencyLevel.MONITOR

        # 构建原因说明（使用策略特定建议文本优先）
        if suggestion_text:
            reason = f"{primary_alert.message} → {suggestion_text}"
        else:
            reason = self._build_reason(primary_alert, alerts)

        # 构建详细说明
        details = self._build_details(primary_alert, alerts, positions, position_id)

        # 获取 symbol 和合约信息
        symbol = primary_alert.symbol or position_id
        metadata: dict[str, Any] = {}

        # 从 positions 获取合约详细信息
        if positions:
            pos = next((p for p in positions if p.position_id == position_id), None)
            if pos and pos.is_option:
                metadata["strategy_type"] = pos.strategy_type
                metadata["option_type"] = pos.option_type
                metadata["strike"] = pos.strike
                metadata["expiry"] = pos.expiry
                metadata["dte"] = pos.dte
                metadata["underlying"] = pos.underlying or pos.symbol
                # 构建更友好的显示名称
                if pos.option_type and pos.strike and pos.expiry:
                    try:
                        exp_str = f"{pos.expiry[4:6]}/{pos.expiry[6:8]}"
                        symbol = f"{pos.symbol} {pos.option_type.upper()} {pos.strike:.0f} {exp_str}"
                    except (IndexError, TypeError):
                        pass

        return PositionSuggestion(
            position_id=position_id,
            symbol=symbol,
            action=action,
            urgency=urgency,
            reason=reason,
            details=details,
            trigger_alerts=alerts,
            metadata=metadata,
        )

    def _build_reason(self, primary: Alert, all_alerts: list[Alert]) -> str:
        """构建原因说明

        Args:
            primary: 主要 alert
            all_alerts: 所有相关 alerts

        Returns:
            原因说明文本
        """
        reasons = []

        # 主要原因
        reasons.append(primary.message)

        # 次要原因（如果有多个 alert）
        if len(all_alerts) > 1:
            secondary_count = len(all_alerts) - 1
            reasons.append(f"(+{secondary_count} more alerts)")

        return " ".join(reasons)

    def _build_details(
        self,
        primary: Alert,
        all_alerts: list[Alert],
        positions: list[PositionData] | None,
        position_id: str,
    ) -> str:
        """构建详细说明

        Args:
            primary: 主要 alert
            all_alerts: 所有相关 alerts
            positions: 持仓数据
            position_id: 持仓 ID

        Returns:
            详细说明文本
        """
        details = []

        # 添加持仓合约信息（优先显示）
        if positions:
            pos = next((p for p in positions if p.position_id == position_id), None)
            if pos and pos.is_option:
                # 合约标识信息
                contract_info = []
                if pos.strategy_type:
                    contract_info.append(pos.strategy_type.upper())
                if pos.option_type:
                    contract_info.append(pos.option_type.upper())
                if pos.strike:
                    contract_info.append(f"K={pos.strike:.0f}")
                if pos.expiry:
                    # 格式化 expiry: YYYYMMDD -> MM/DD
                    try:
                        exp_str = f"{pos.expiry[4:6]}/{pos.expiry[6:8]}"
                        contract_info.append(f"Exp={exp_str}")
                    except (IndexError, TypeError):
                        contract_info.append(f"Exp={pos.expiry}")
                if contract_info:
                    details.append(" ".join(contract_info))

        # 添加阈值信息
        if primary.current_value is not None and primary.threshold_value is not None:
            details.append(
                f"Current: {primary.current_value:.2f}, Threshold: {primary.threshold_value:.2f}"
            )

        # 添加建议操作
        if primary.suggested_action:
            details.append(f"Suggested: {primary.suggested_action}")

        # 添加持仓上下文
        if positions:
            pos = next((p for p in positions if p.position_id == position_id), None)
            if pos:
                if pos.is_option and pos.dte is not None:
                    details.append(f"DTE: {pos.dte}")
                if pos.unrealized_pnl_pct:
                    details.append(f"PnL: {pos.unrealized_pnl_pct:.1%}")

        return " | ".join(details)

    def _adjust_for_market(
        self, suggestions: list[PositionSuggestion], vix: float
    ) -> list[PositionSuggestion]:
        """根据市场环境调整建议优先级

        调整规则：
        - VIX > 25: REDUCE/HEDGE/CLOSE 建议 MONITOR → SOON
        - VIX > 35: 所有风险建议 SOON → IMMEDIATE

        Args:
            suggestions: 建议列表
            vix: 当前 VIX 值

        Returns:
            调整后的建议列表
        """
        if vix <= self._vix_high:
            return suggestions

        risk_actions = {
            ActionType.CLOSE,
            ActionType.REDUCE,
            ActionType.HEDGE,
            ActionType.ROLL,
        }

        for suggestion in suggestions:
            if suggestion.action in risk_actions:
                if vix > self._vix_extreme:
                    # VIX > 35: 所有风险建议 → IMMEDIATE
                    if suggestion.urgency != UrgencyLevel.IMMEDIATE:
                        suggestion.urgency = UrgencyLevel.IMMEDIATE
                        suggestion.details += f" | VIX={vix:.1f} (extreme)"
                elif vix > self._vix_high:
                    # VIX > 25: MONITOR → SOON
                    if suggestion.urgency == UrgencyLevel.MONITOR:
                        suggestion.urgency = UrgencyLevel.SOON
                        suggestion.details += f" | VIX={vix:.1f} (elevated)"

        return suggestions

    def _sort_by_priority(
        self, suggestions: list[PositionSuggestion]
    ) -> list[PositionSuggestion]:
        """按优先级排序

        排序规则：IMMEDIATE > SOON > MONITOR，同级别按 alert priority

        Args:
            suggestions: 建议列表

        Returns:
            排序后的列表
        """

        def sort_key(s: PositionSuggestion) -> tuple[int, int]:
            urgency_score = URGENCY_PRIORITY.get(s.urgency, 0)
            # 取触发 alerts 中最高优先级
            alert_score = 0
            for alert in s.trigger_alerts:
                type_score = ALERT_PRIORITY.get(alert.alert_type, 0)
                alert_score = max(alert_score, type_score)
            return (-urgency_score, -alert_score)

        return sorted(suggestions, key=sort_key)
