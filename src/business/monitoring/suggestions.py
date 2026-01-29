"""Suggestion Generator - 调整建议生成

将监控 Alert 转换为可执行的调整建议。

基于三层指标体系（Portfolio/Position/Capital Level）和 ALERT_ACTION_MAP 配置。
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    PositionData,
)
from src.business.monitoring.roll_calculator import RollTargetCalculator
from src.data.models.option import OptionChain
from src.engine.models.enums import StrategyType


@runtime_checkable
class OptionChainProvider(Protocol):
    """期权链数据提供者协议

    任何实现了 get_option_chain 方法的对象都可以作为提供者。
    """

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
    ) -> OptionChain | None:
        """获取期权链数据"""
        ...

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
    (AlertType.CASH_RATIO, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.GROSS_LEVERAGE, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.STRESS_TEST_LOSS, AlertLevel.RED): (ActionType.HEDGE, UrgencyLevel.IMMEDIATE),
    (AlertType.CONCENTRATION, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.DELTA_EXPOSURE, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.VEGA_EXPOSURE, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.THETA_EXPOSURE, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
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
        ActionType.CLOSE, UrgencyLevel.IMMEDIATE,
        "强制平仓（盈利止盈，亏损不展期，等待新开仓机会）"
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


# =============================================================================
# POSITION SELECTOR 配置
# 用于 Capital/Portfolio 级 Alert 选择具体持仓
# =============================================================================

@dataclass
class PositionSelectorConfig:
    """持仓选择器配置

    当 Capital/Portfolio 级 RED Alert 触发时，用于选择具体持仓进行操作。
    """

    sort_key: str  # 排序字段
    ascending: bool  # 升序/降序
    action: ActionType  # 目标操作
    max_positions: int = 3  # 最多选择持仓数
    filter_profitable_only: bool = False  # 只选盈利持仓
    filter_gamma_negative: bool = False  # 只选 Gamma < 0 的持仓
    filter_vega_negative: bool = False  # 只选 Vega < 0 的持仓
    filter_tgr_below: float | None = None  # TGR 阈值


# AlertType -> PositionSelectorConfig
# 用于将 Capital/Portfolio 级 RED Alert 转换为具体持仓操作
PORTFOLIO_ALERT_POSITION_SELECTOR: dict[AlertType, PositionSelectorConfig] = {
    # === Capital 级 ===
    # Margin > 70%: 按 Theta/Margin 升序（效率最低先平）
    AlertType.MARGIN_UTILIZATION: PositionSelectorConfig(
        sort_key="theta_margin_ratio",
        ascending=True,
        action=ActionType.CLOSE,
    ),
    # Cash < 10%: 按 P&L% 降序（盈利最多先平）
    AlertType.CASH_RATIO: PositionSelectorConfig(
        sort_key="unrealized_pnl_pct",
        ascending=False,
        action=ActionType.CLOSE,
        filter_profitable_only=True,
    ),
    # Leverage > 4x: 按 Notional 降序（敞口最大先平）
    AlertType.GROSS_LEVERAGE: PositionSelectorConfig(
        sort_key="notional",
        ascending=False,
        action=ActionType.CLOSE,
    ),
    # Stress > 20%: 按 |Gamma| × S² 降序（Gamma 空头最大先平）
    AlertType.STRESS_TEST_LOSS: PositionSelectorConfig(
        sort_key="gamma_s_squared",
        ascending=False,
        action=ActionType.CLOSE,
        filter_gamma_negative=True,
    ),

    # === Portfolio 级 ===
    # BWD% > 50%: 按 Delta 贡献降序
    AlertType.DELTA_EXPOSURE: PositionSelectorConfig(
        sort_key="delta_contribution",
        ascending=False,
        action=ActionType.CLOSE,
    ),
    # Gamma% < -0.5%: 按 Gamma 升序（负最大先平）
    AlertType.GAMMA_EXPOSURE: PositionSelectorConfig(
        sort_key="gamma",
        ascending=True,
        action=ActionType.CLOSE,
        filter_gamma_negative=True,
    ),
    # Vega% < -0.5%: 按 Vega 升序（负最大先平）
    AlertType.VEGA_EXPOSURE: PositionSelectorConfig(
        sort_key="vega",
        ascending=True,
        action=ActionType.CLOSE,
        filter_vega_negative=True,
    ),
    # Theta% > 0.30%: 按 Theta 降序（Theta 最高先平）
    AlertType.THETA_EXPOSURE: PositionSelectorConfig(
        sort_key="theta",
        ascending=False,
        action=ActionType.CLOSE,
    ),
    # TGR < 1.0: 按 Position TGR 升序（TGR 最低先平）
    AlertType.TGR_LOW: PositionSelectorConfig(
        sort_key="tgr",
        ascending=True,
        action=ActionType.CLOSE,
        filter_tgr_below=0.5,
    ),
    # HHI > 0.50: 按市值降序（占比最高先平）
    AlertType.CONCENTRATION: PositionSelectorConfig(
        sort_key="market_value_abs",
        ascending=False,
        action=ActionType.CLOSE,
    ),
    # IV_HV_QUALITY: 不配置 → 保持 HOLD，不生成订单
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
        roll_calculator: RollTargetCalculator | None = None,
        option_chain_provider: OptionChainProvider | None = None,
    ):
        """初始化建议生成器

        Args:
            action_map: 自定义 Alert → Action 映射
            vix_high_threshold: VIX 高波动阈值
            vix_extreme_threshold: VIX 极端波动阈值
            roll_calculator: 展期目标计算器
            option_chain_provider: 期权链数据提供者（用于获取真实到期日和行权价）
        """
        self._action_map = action_map or ALERT_ACTION_MAP
        self._vix_high = vix_high_threshold
        self._vix_extreme = vix_extreme_threshold
        self._roll_calculator = roll_calculator or RollTargetCalculator()
        self._option_chain_provider = option_chain_provider

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

        suggestions: list[PositionSuggestion] = []

        # Step 1: 分离组合级和持仓级 Alert
        portfolio_alerts: list[Alert] = []
        position_alerts: list[Alert] = []

        for alert in monitor_result.alerts:
            if self._is_portfolio_level_alert(alert):
                portfolio_alerts.append(alert)
            else:
                position_alerts.append(alert)

        # Step 2: 处理组合级 RED Alert → 选择具体持仓
        positions_list = positions or []
        processed_position_ids: set[str] = set()  # 避免重复

        for alert in portfolio_alerts:
            if alert.level == AlertLevel.RED:
                config = PORTFOLIO_ALERT_POSITION_SELECTOR.get(alert.alert_type)
                if config:
                    selected = self._select_positions_for_alert(alert, positions_list)
                    for pos in selected:
                        # 避免同一持仓被多个组合级 Alert 重复添加
                        if pos.position_id in processed_position_ids:
                            continue
                        processed_position_ids.add(pos.position_id)

                        suggestion = self._create_suggestion_for_portfolio_alert(
                            alert, pos, config
                        )
                        suggestions.append(suggestion)
                else:
                    # 无配置的组合级 Alert，仍走原逻辑（生成 portfolio 级建议）
                    position_alerts.append(alert)
            else:
                # 非 RED 级别的组合级 Alert，仍走原逻辑
                position_alerts.append(alert)

        # Step 3: 处理持仓级 Alert（现有逻辑）
        grouped_alerts = self._group_alerts_by_position(position_alerts)

        for position_id, alerts in grouped_alerts.items():
            # 跳过已被组合级 Alert 处理的持仓
            if position_id in processed_position_ids:
                logger.debug(
                    f"Skipping position {position_id} - already processed by portfolio alert"
                )
                continue

            suggestion = self._generate_for_position(position_id, alerts, positions)
            if suggestion:
                suggestions.append(suggestion)

        # Step 4: 市场环境调整
        if vix:
            suggestions = self._adjust_for_market(suggestions, vix)

        # Step 5: 按优先级排序
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
            if pos:
                # 通用字段
                metadata["quantity"] = pos.quantity
                metadata["lot_size"] = getattr(pos, "contract_multiplier", 100)

                if pos.is_option:
                    metadata["strategy_type"] = pos.strategy_type
                    metadata["option_type"] = pos.option_type
                    metadata["strike"] = pos.strike
                    metadata["expiry"] = pos.expiry
                    metadata["dte"] = pos.dte
                    metadata["underlying"] = pos.underlying or pos.symbol
                    metadata["trading_class"] = pos.trading_class  # For HK options
                    metadata["con_id"] = pos.con_id  # IBKR contract ID
                    # 构建更友好的显示名称
                    if pos.option_type and pos.strike and pos.expiry:
                        try:
                            exp_str = f"{pos.expiry[4:6]}/{pos.expiry[6:8]}"
                            symbol = f"{pos.symbol} {pos.option_type.upper()} {pos.strike:.0f} {exp_str}"
                        except (IndexError, TypeError):
                            pass

                    # ROLL 操作：计算展期目标参数
                    if action == ActionType.ROLL:
                        # 获取期权链数据（如果有提供者）
                        available_expiries, available_strikes = self._fetch_option_chain_data(
                            underlying=pos.underlying or pos.symbol,
                            option_type=pos.option_type,
                        )

                        roll_target = self._roll_calculator.calculate(
                            position=pos,
                            alert=primary_alert,
                            available_expiries=available_expiries,
                            available_strikes=available_strikes,
                        )
                        metadata["suggested_expiry"] = roll_target.suggested_expiry
                        metadata["suggested_strike"] = roll_target.suggested_strike
                        metadata["suggested_dte"] = roll_target.suggested_dte
                        metadata["roll_credit"] = roll_target.roll_credit
                        metadata["roll_reason"] = roll_target.reason
                        logger.info(
                            f"Roll target calculated for {pos.symbol}: "
                            f"expiry={roll_target.suggested_expiry}, "
                            f"strike={roll_target.suggested_strike}, "
                            f"dte={roll_target.suggested_dte}"
                            f"{' [from chain]' if available_expiries else ''}"
                        )

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

    def _fetch_option_chain_data(
        self,
        underlying: str,
        option_type: str | None,
    ) -> tuple[list[str] | None, list[float] | None]:
        """获取期权链数据用于 ROLL 目标计算

        Args:
            underlying: 标的代码
            option_type: 期权类型 ("put" / "call")

        Returns:
            (available_expiries, available_strikes) 元组
            如果无法获取，返回 (None, None)
        """
        if not self._option_chain_provider:
            return None, None

        try:
            # 获取期权链（DTE 25-60 天范围）
            today = date.today()
            expiry_start = today + timedelta(days=25)
            expiry_end = today + timedelta(days=60)

            chain = self._option_chain_provider.get_option_chain(
                underlying=underlying,
                expiry_start=expiry_start,
                expiry_end=expiry_end,
            )

            if not chain:
                logger.debug(f"No option chain data for {underlying}")
                return None, None

            # 提取到期日列表
            available_expiries = [
                d.strftime("%Y-%m-%d") for d in chain.expiry_dates
            ]

            # 根据期权类型选择合约列表提取 strikes
            if option_type == "put":
                contracts = chain.puts
            elif option_type == "call":
                contracts = chain.calls
            else:
                contracts = chain.puts + chain.calls

            # 提取唯一的 strikes
            available_strikes = sorted(set(
                q.contract.strike_price
                for q in contracts
                if q.contract and q.contract.strike_price
            ))

            logger.debug(
                f"Option chain for {underlying}: "
                f"{len(available_expiries)} expiries, {len(available_strikes)} strikes"
            )

            return available_expiries, available_strikes

        except Exception as e:
            logger.warning(f"Failed to fetch option chain for {underlying}: {e}")
            return None, None

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

    # =========================================================================
    # Portfolio/Capital 级 Alert 持仓选择
    # =========================================================================

    def _is_portfolio_level_alert(self, alert: Alert) -> bool:
        """判断是否为组合级 Alert（无 position_id）

        Capital/Portfolio Monitor 生成的 Alert 没有 position_id 和 symbol。

        Args:
            alert: Alert 对象

        Returns:
            是否为组合级 Alert
        """
        return alert.position_id is None and alert.symbol is None

    def _calc_sort_value(self, pos: PositionData, sort_key: str) -> float:
        """计算排序值

        Args:
            pos: 持仓数据
            sort_key: 排序字段名

        Returns:
            排序值
        """
        if sort_key == "theta_margin_ratio":
            # Theta / Margin，效率越低值越小
            theta = pos.theta or 0
            margin = pos.margin or 1
            if margin == 0:
                margin = 1
            return theta / margin

        elif sort_key == "notional":
            # Strike × Quantity × Multiplier
            strike = pos.strike or 0
            qty = abs(pos.quantity)
            multiplier = pos.contract_multiplier or 100
            return strike * qty * multiplier

        elif sort_key == "gamma_s_squared":
            # |Gamma| × S²，Gamma 风险贡献
            gamma = abs(pos.gamma or 0)
            underlying_price = pos.underlying_price or 0
            return gamma * (underlying_price ** 2)

        elif sort_key == "delta_contribution":
            # |Delta| × Beta × S，Delta 风险贡献
            delta = abs(pos.delta or 0)
            beta = pos.beta or 1
            underlying_price = pos.underlying_price or 0
            return delta * beta * underlying_price

        elif sort_key == "market_value_abs":
            # |Market Value|
            return abs(pos.market_value or 0)

        else:
            # 其他字段直接从 PositionData 获取
            return getattr(pos, sort_key, 0) or 0

    def _select_positions_for_alert(
        self,
        alert: Alert,
        positions: list[PositionData],
    ) -> list[PositionData]:
        """根据 Alert 类型选择目标持仓

        用于将 Capital/Portfolio 级 RED Alert 转换为具体持仓操作。

        Args:
            alert: 组合级 Alert
            positions: 所有持仓数据

        Returns:
            选中的持仓列表
        """
        config = PORTFOLIO_ALERT_POSITION_SELECTOR.get(alert.alert_type)
        if not config:
            logger.debug(
                f"No position selector config for {alert.alert_type.value}, "
                "skipping position selection"
            )
            return []

        # 过滤期权持仓
        candidates = [p for p in positions if p.is_option]

        if not candidates:
            logger.debug("No option positions available for selection")
            return []

        # 应用过滤条件
        if config.filter_profitable_only:
            profitable = [p for p in candidates if (p.unrealized_pnl_pct or 0) > 0]
            if not profitable:
                # 回退逻辑：按 DTE 升序（最临近到期先平）
                logger.info(
                    f"No profitable positions for {alert.alert_type.value}, "
                    "falling back to DTE ascending"
                )
                candidates.sort(key=lambda p: p.dte or 999)
                return candidates[: config.max_positions]
            candidates = profitable

        if config.filter_gamma_negative:
            candidates = [p for p in candidates if (p.gamma or 0) < 0]
            if not candidates:
                logger.debug(
                    f"No gamma-negative positions for {alert.alert_type.value}"
                )
                return []

        if config.filter_vega_negative:
            candidates = [p for p in candidates if (p.vega or 0) < 0]
            if not candidates:
                logger.debug(
                    f"No vega-negative positions for {alert.alert_type.value}"
                )
                return []

        if config.filter_tgr_below is not None:
            candidates = [
                p for p in candidates
                if (p.tgr or 999) < config.filter_tgr_below
            ]
            if not candidates:
                logger.debug(
                    f"No positions with TGR < {config.filter_tgr_below} "
                    f"for {alert.alert_type.value}"
                )
                return []

        # 排序
        candidates.sort(
            key=lambda p: self._calc_sort_value(p, config.sort_key),
            reverse=not config.ascending,
        )

        selected = candidates[: config.max_positions]

        logger.info(
            f"Selected {len(selected)} positions for {alert.alert_type.value} "
            f"(sort_key={config.sort_key}, ascending={config.ascending}): "
            f"{[p.symbol for p in selected]}"
        )

        return selected

    def _create_suggestion_for_portfolio_alert(
        self,
        alert: Alert,
        pos: PositionData,
        config: PositionSelectorConfig,
    ) -> PositionSuggestion:
        """为组合级 Alert 创建持仓建议

        Args:
            alert: 组合级 Alert
            pos: 选中的持仓
            config: 选择器配置

        Returns:
            PositionSuggestion
        """
        # 构建 symbol 显示名称
        symbol = pos.symbol
        if pos.option_type and pos.strike and pos.expiry:
            try:
                exp_str = f"{pos.expiry[4:6]}/{pos.expiry[6:8]}"
                symbol = f"{pos.symbol} {pos.option_type.upper()} {pos.strike:.0f} {exp_str}"
            except (IndexError, TypeError):
                pass

        # 构建 metadata
        metadata: dict[str, Any] = {
            "quantity": pos.quantity,
            "lot_size": pos.contract_multiplier or 100,
            "portfolio_alert": True,  # 标记来自组合级 Alert
        }

        if pos.is_option:
            metadata["strategy_type"] = pos.strategy_type
            metadata["option_type"] = pos.option_type
            metadata["strike"] = pos.strike
            metadata["expiry"] = pos.expiry
            metadata["dte"] = pos.dte
            metadata["underlying"] = pos.underlying or pos.symbol
            metadata["trading_class"] = pos.trading_class
            metadata["con_id"] = pos.con_id

        # 构建 reason
        reason = f"[Portfolio] {alert.message}"

        # 构建 details
        details_parts = []
        if pos.strategy_type:
            details_parts.append(pos.strategy_type.value.upper())
        if pos.option_type:
            details_parts.append(pos.option_type.upper())
        if pos.strike:
            details_parts.append(f"K={pos.strike:.0f}")
        if pos.dte is not None:
            details_parts.append(f"DTE={pos.dte}")
        if pos.unrealized_pnl_pct:
            details_parts.append(f"PnL={pos.unrealized_pnl_pct:.1%}")
        details = " | ".join(details_parts) if details_parts else ""

        return PositionSuggestion(
            position_id=pos.position_id,
            symbol=symbol,
            action=config.action,
            urgency=UrgencyLevel.IMMEDIATE,
            reason=reason,
            details=details,
            trigger_alerts=[alert],
            metadata=metadata,
        )
