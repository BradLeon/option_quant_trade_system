"""
Position Monitor - 持仓级监控器

监控单个持仓的 9 个风险指标（基于实战经验优化）。

**策略差异化阈值**：
- Short Put: 标准阈值，裸卖需严格风控
- Covered Call: 有正股覆盖，DTE/Delta/Gamma 可放宽
- Short Strangle: 双向裸卖，使用标准阈值

| 指标            | Short Put      | Covered Call   | 说明                    |
|-----------------|----------------|----------------|-------------------------|
| OTM%            | ≥10% 绿        | ≥5% 绿         | CC 被行权是收益         |
| |Delta|         | ≤0.20 绿       | ≤0.40 绿       | CC 被行权 = 卖出正股    |
| DTE             | ≥14天 绿       | ≥7天 绿        | CC 有正股覆盖 Gamma     |
| Gamma Risk%     | ≤0.5% 绿       | ≤2% 绿         | CC 正股覆盖风险         |
| P&L%            | ≥50% 绿        | ≥50% 绿        | 相同                    |
| TGR/IV-HV/ROC   | 标准阈值       | 标准阈值       | 相同                    |

设计原则：
- 只做阈值检查，不做计算（遵循 Decision #0）
- 使用通用 _check_threshold() 函数，消息和建议从配置中读取
- 根据 pos.strategy_type 自动选择对应的阈值配置
- P&L 特殊处理：止盈为 GREEN alert（机会），止损为 RED alert
"""

import logging

from src.business.config.monitoring_config import (
    MonitoringConfig,
    PositionThresholds,
    ThresholdRange,
)
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorStatus,
    PositionData,
)

logger = logging.getLogger(__name__)


class PositionMonitor:
    """持仓级监控器

    监控单个持仓的 9 个风险指标，支持策略差异化阈值：

    **共同指标**：
    1. OTM% - 虚值百分比
    2. |Delta| - 方向性风险
    3. DTE - 到期日预警
    4. P&L% - 止盈止损
    5. Gamma Risk% - Gamma/Margin 百分比
    6. TGR - 时间衰减效率
    7. IV/HV - 波动率环境
    8. Expected ROC - 预期资本回报率
    9. Win Probability - 胜率

    **策略差异**：
    - Short Put: 标准阈值（裸卖需严格风控）
    - Covered Call: 放宽 DTE/Delta/Gamma/OTM（有正股覆盖）
    - Short Strangle: 标准阈值（双向裸卖）

    使用 config.get_position_thresholds(strategy_type) 获取策略特定阈值。
    """

    def __init__(self, config: MonitoringConfig) -> None:
        """初始化持仓监控器

        Args:
            config: 监控配置
        """
        self.config = config
        # 基础阈值（用于无策略类型的持仓）
        self._base_thresholds = config.position

    def evaluate(
        self,
        positions: list[PositionData],
    ) -> list[Alert]:
        """评估所有持仓

        Args:
            positions: 持仓数据列表

        Returns:
            预警列表
        """
        alerts: list[Alert] = []

        for pos in positions:
            alerts.extend(self._evaluate_position(pos))

        return alerts

    def _evaluate_position(self, pos: PositionData) -> list[Alert]:
        """评估单个持仓（仅期权）

        使用通用 _check_threshold() 方法进行阈值检查，
        根据 pos.strategy_type 选择策略特定的阈值配置。

        注意：Stock 类型持仓不在此监控器范围内，直接跳过。

        检查 9 个指标，按重要性排序：
        1. OTM% - 虚值百分比（核心风险指标）
        2. |Delta| - 方向性风险
        3. DTE - 到期日预警
        4. P&L% - 止盈止损（特殊逻辑）
        5. Gamma Risk% - Gamma/Margin 百分比
        6. TGR - 时间衰减效率
        7. IV/HV - 波动率环境
        8. Expected ROC - 预期资本回报率
        9. Win Probability - 胜率
        """
        # 跳过 Stock 类型持仓，PositionMonitor 只监控期权
        if pos.is_stock:
            return []

        alerts: list[Alert] = []

        # 获取策略特定阈值（根据 strategy_type 自动选择）
        thresholds = self.config.get_position_thresholds(pos.strategy_type)

        # 1. 检查 OTM%（统一公式，无需 Put/Call 区分）
        alerts.extend(self._check_threshold(
            value=pos.otm_pct,
            threshold=thresholds.otm_pct,
            metric_name="otm_pct",
            position=pos,
        ))

        # 2. 检查 |Delta|（使用绝对值）
        alerts.extend(self._check_threshold(
            value=abs(pos.delta) if pos.delta is not None else None,
            threshold=thresholds.delta,
            metric_name="delta",
            position=pos,
        ))

        # 3. 检查 DTE
        alerts.extend(self._check_threshold(
            value=pos.dte,
            threshold=thresholds.dte,
            metric_name="dte",
            position=pos,
        ))

        # 4. 检查 P&L%（特殊逻辑：止盈为 GREEN，止损为 RED）
        alerts.extend(self._check_pnl(pos, thresholds))

        # 5. 检查 Gamma Risk%（Gamma/Margin 百分比）
        alerts.extend(self._check_threshold(
            value=pos.gamma_risk_pct,
            threshold=thresholds.gamma_risk_pct,
            metric_name="gamma_risk_pct",
            position=pos,
        ))

        # 6. 检查 TGR
        alerts.extend(self._check_threshold(
            value=pos.tgr,
            threshold=thresholds.tgr,
            metric_name="tgr",
            position=pos,
        ))

        # 7. 检查 IV/HV
        alerts.extend(self._check_threshold(
            value=pos.iv_hv_ratio,
            threshold=thresholds.iv_hv,
            metric_name="iv_hv",
            position=pos,
        ))

        # 8. 检查 Expected ROC
        alerts.extend(self._check_threshold(
            value=pos.expected_roc,
            threshold=thresholds.expected_roc,
            metric_name="expected_roc",
            position=pos,
        ))

        # 9. 检查 Win Probability
        alerts.extend(self._check_threshold(
            value=pos.win_probability,
            threshold=thresholds.win_probability,
            metric_name="win_probability",
            position=pos,
        ))

        return alerts

    def _format_threshold_range(self, threshold: ThresholdRange, is_pct: bool = False) -> str:
        """格式化阈值范围字符串

        Args:
            threshold: 阈值配置
            is_pct: 是否为百分比格式

        Returns:
            格式化的范围字符串，如 "≥10%" 或 "40~60"
        """
        if not threshold.green:
            return ""

        green_low, green_high = threshold.green
        fmt = lambda v: f"{v:.0%}" if is_pct else (f"{v:.0f}" if v == int(v) else f"{v:.2f}")

        if green_high == float("inf"):
            return f"≥{fmt(green_low)}"
        elif green_low == float("-inf") or green_low == 0:
            return f"≤{fmt(green_high)}"
        else:
            return f"{fmt(green_low)}~{fmt(green_high)}"

    def _check_threshold(
        self,
        value: float | int | None,
        threshold: ThresholdRange,
        metric_name: str,
        position: PositionData,
    ) -> list[Alert]:
        """通用阈值检查函数

        根据 ThresholdRange 配置检查值是否超出阈值，
        消息和建议操作从配置中读取。

        Args:
            value: 当前指标值
            threshold: 阈值配置（含消息模板）
            metric_name: 指标名称（用于日志）
            position: 持仓数据（用于填充 symbol, position_id）

        Returns:
            预警列表
        """
        if value is None:
            return []

        alerts: list[Alert] = []

        # 获取 AlertType
        try:
            alert_type = AlertType[threshold.alert_type] if threshold.alert_type else AlertType.OTM_PCT
        except KeyError:
            logger.warning(f"Unknown alert_type: {threshold.alert_type}, using OTM_PCT")
            alert_type = AlertType.OTM_PCT

        # 判断是否为百分比格式（用于阈值范围显示）
        is_pct = metric_name in ("otm_pct", "pnl", "roc", "expected_roc", "win_probability", "gamma_risk_pct")

        # 格式化阈值范围
        threshold_range = self._format_threshold_range(threshold, is_pct)

        # 检查红色上限
        if threshold.red_above is not None and value > threshold.red_above:
            message = self._format_message(
                threshold.red_above_message,
                value, threshold.red_above, position, metric_name
            )
            alerts.append(Alert(
                alert_type=alert_type,
                level=AlertLevel.RED,
                message=message,
                symbol=position.symbol,
                position_id=position.position_id,
                current_value=float(value),
                threshold_value=threshold.red_above,
                threshold_range=threshold_range,
                suggested_action=threshold.red_above_action or None,
            ))
            return alerts  # RED 优先，不再检查其他

        # 检查红色下限
        if threshold.red_below is not None and value < threshold.red_below:
            message = self._format_message(
                threshold.red_below_message,
                value, threshold.red_below, position, metric_name
            )
            alerts.append(Alert(
                alert_type=alert_type,
                level=AlertLevel.RED,
                message=message,
                symbol=position.symbol,
                position_id=position.position_id,
                current_value=float(value),
                threshold_value=threshold.red_below,
                threshold_range=threshold_range,
                suggested_action=threshold.red_below_action or None,
            ))
            return alerts  # RED 优先，不再检查其他

        # 检查绿色范围 - 如果在绿色范围内，产生 GREEN Alert
        if threshold.green:
            green_low, green_high = threshold.green
            in_green = green_low <= value <= green_high or (green_high == float("inf") and value >= green_low)
            if in_green:
                # 产生 GREEN Alert（正常状态也要显示）
                message = self._format_message(
                    threshold.green_message or f"{{symbol}} {metric_name} 正常: {{value}}",
                    value, None, position, metric_name
                )
                alerts.append(Alert(
                    alert_type=alert_type,
                    level=AlertLevel.GREEN,
                    message=message,
                    symbol=position.symbol,
                    position_id=position.position_id,
                    current_value=float(value),
                    threshold_range=threshold_range,
                    suggested_action=threshold.green_action or None,
                ))
                return alerts

        # 不在红色范围，也不在绿色范围 -> 黄色预警
        message = self._format_message(
            threshold.yellow_message,
            value, None, position, metric_name
        )
        alerts.append(Alert(
            alert_type=alert_type,
            level=AlertLevel.YELLOW,
            message=message,
            symbol=position.symbol,
            position_id=position.position_id,
            current_value=float(value),
            threshold_range=threshold_range,
            suggested_action=threshold.yellow_action or None,
        ))

        return alerts

    def _format_message(
        self,
        template: str,
        value: float | int,
        threshold: float | None,
        position: PositionData,
        metric_name: str,
    ) -> str:
        """格式化消息模板

        Args:
            template: 消息模板（支持 {value}, {threshold}, {symbol}）
            value: 当前值
            threshold: 阈值
            position: 持仓数据
            metric_name: 指标名称

        Returns:
            格式化后的消息
        """
        if not template:
            return f"持仓 {position.symbol} {metric_name} 异常: {value}"

        try:
            # 支持的占位符
            return template.format(
                value=value,
                threshold=threshold if threshold is not None else "",
                symbol=position.symbol,
            )
        except (KeyError, ValueError):
            return f"持仓 {position.symbol} {metric_name}: {value}"

    def _check_pnl(self, pos: PositionData, thresholds: PositionThresholds) -> list[Alert]:
        """检查盈亏

        基于 ThresholdRange 的三档检查：
        - RED: 触发止损 (P&L < -100%，亏损超过原始权利金)
        - YELLOW: 未达止盈 (-100% ~ 50%)
        - GREEN: 达到止盈目标 (P&L >= 50%)

        Args:
            pos: 持仓数据
            thresholds: 策略特定的阈值配置
        """
        alerts: list[Alert] = []
        pnl_pct = pos.unrealized_pnl_pct

        if pnl_pct is None:
            return alerts

        threshold = thresholds.pnl
        threshold_range = self._format_threshold_range(threshold, is_pct=True)

        # 检查止损（red_below）
        if threshold.red_below is not None and pnl_pct < threshold.red_below:
            alerts.append(Alert(
                alert_type=AlertType.STOP_LOSS,
                level=AlertLevel.RED,
                message=f"持仓 {pos.symbol} 触发止损: {pnl_pct:.1%}",
                symbol=pos.symbol,
                position_id=pos.position_id,
                current_value=pnl_pct,
                threshold_value=threshold.red_below,
                threshold_range=threshold_range,
                suggested_action=threshold.red_below_action or "触发止损，执行风险管理",
            ))
            return alerts

        # 检查止盈（green 范围）
        if threshold.green:
            take_profit = threshold.green[0]  # green 范围下限即止盈目标
            if pnl_pct >= take_profit:
                alerts.append(Alert(
                    alert_type=AlertType.PROFIT_TARGET,
                    level=AlertLevel.GREEN,
                    message=f"持仓 {pos.symbol} 达到止盈目标: {pnl_pct:.1%}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=pnl_pct,
                    threshold_value=take_profit,
                    threshold_range=threshold_range,
                    suggested_action=threshold.green_action or "考虑止盈平仓，锁定利润",
                ))
                return alerts

        # 不在 RED 也不在 GREEN -> YELLOW
        alerts.append(Alert(
            alert_type=AlertType.PNL_TARGET,
            level=AlertLevel.YELLOW,
            message=f"持仓 {pos.symbol} 盈亏: {pnl_pct:.1%}",
            symbol=pos.symbol,
            position_id=pos.position_id,
            current_value=pnl_pct,
            threshold_range=threshold_range,
            suggested_action=threshold.yellow_action or "关注盈亏变化",
        ))

        return alerts

    def get_status(self, alerts: list[Alert]) -> MonitorStatus:
        """根据预警确定状态"""
        if any(a.level == AlertLevel.RED for a in alerts):
            return MonitorStatus.RED
        elif any(a.level == AlertLevel.YELLOW for a in alerts):
            return MonitorStatus.YELLOW
        else:
            return MonitorStatus.GREEN
