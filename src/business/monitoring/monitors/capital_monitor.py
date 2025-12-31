"""
Capital Monitor - 资金级监控器

监控资金层面的风险指标：
- Sharpe Ratio
- Kelly 使用率
- 保证金使用率
- 回撤

设计原则：
- 只做阈值检查，不做计算（遵循 Decision #0）
- 所有指标由 engine/account 层计算
- 接收预计算的 CapitalMetrics，只做规则判断
- 使用通用 _check_threshold() 函数，消息和建议从配置中读取
"""

import logging

from src.business.config.monitoring_config import MonitoringConfig, ThresholdRange
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorStatus,
)
from src.engine.models.capital import CapitalMetrics

logger = logging.getLogger(__name__)


class CapitalMonitor:
    """资金级监控器

    监控资金层面的风险指标：
    1. Sharpe Ratio - 风险调整收益
    2. Kelly 使用率 - 仓位是否合理
    3. 保证金使用率 - 杠杆风险
    4. 回撤 - 最大回撤控制

    使用通用 _check_threshold() 方法，消息和建议从配置读取。
    """

    def __init__(self, config: MonitoringConfig) -> None:
        """初始化资金监控器

        Args:
            config: 监控配置
        """
        self.config = config
        self.thresholds = config.capital

    def evaluate(
        self,
        metrics: CapitalMetrics,
    ) -> list[Alert]:
        """评估资金风险

        使用通用 _check_threshold() 方法进行阈值检查，
        消息和建议从 ThresholdRange 配置读取。

        Args:
            metrics: 资金指标

        Returns:
            预警列表
        """
        alerts: list[Alert] = []

        # 检查 Sharpe Ratio
        alerts.extend(self._check_threshold(
            value=metrics.sharpe_ratio,
            threshold=self.thresholds.sharpe,
            metric_name="sharpe_ratio",
        ))

        # 检查 Kelly 使用率
        alerts.extend(self._check_threshold(
            value=metrics.kelly_usage,
            threshold=self.thresholds.kelly_usage,
            metric_name="kelly_usage",
        ))

        # 检查保证金使用率
        alerts.extend(self._check_threshold(
            value=metrics.margin_usage,
            threshold=self.thresholds.margin_usage,
            metric_name="margin_usage",
        ))

        # 检查回撤
        alerts.extend(self._check_threshold(
            value=metrics.current_drawdown,
            threshold=self.thresholds.drawdown,
            metric_name="drawdown",
        ))

        return alerts

    def _check_threshold(
        self,
        value: float | None,
        threshold: ThresholdRange,
        metric_name: str,
    ) -> list[Alert]:
        """通用阈值检查函数

        根据 ThresholdRange 配置检查值是否超出阈值，
        消息和建议操作从配置中读取。

        Args:
            value: 当前指标值
            threshold: 阈值配置（含消息模板）
            metric_name: 指标名称（用于日志）

        Returns:
            预警列表
        """
        if value is None:
            return []

        alerts: list[Alert] = []

        # 获取 AlertType
        try:
            alert_type = AlertType[threshold.alert_type] if threshold.alert_type else AlertType.DELTA_EXPOSURE
        except KeyError:
            logger.warning(f"Unknown alert_type: {threshold.alert_type}, using DELTA_EXPOSURE")
            alert_type = AlertType.DELTA_EXPOSURE

        # 检查红色上限
        if threshold.red_above is not None and value > threshold.red_above:
            message = threshold.red_above_message.format(value=value, threshold=threshold.red_above) \
                if threshold.red_above_message else f"{metric_name} 过高: {value:.2f} > {threshold.red_above}"
            alerts.append(Alert(
                alert_type=alert_type,
                level=AlertLevel.RED,
                message=message,
                current_value=value,
                threshold_value=threshold.red_above,
                suggested_action=threshold.red_above_action or None,
            ))
            return alerts  # RED 优先，不再检查其他

        # 检查红色下限
        if threshold.red_below is not None and value < threshold.red_below:
            message = threshold.red_below_message.format(value=value, threshold=threshold.red_below) \
                if threshold.red_below_message else f"{metric_name} 过低: {value:.2f} < {threshold.red_below}"
            alerts.append(Alert(
                alert_type=alert_type,
                level=AlertLevel.RED,
                message=message,
                current_value=value,
                threshold_value=threshold.red_below,
                suggested_action=threshold.red_below_action or None,
            ))
            return alerts  # RED 优先，不再检查其他

        # 检查绿色范围 - 如果在绿色范围内，产生 GREEN Alert
        if threshold.green:
            green_low, green_high = threshold.green
            in_green = green_low <= value <= green_high or (green_high == float("inf") and value >= green_low)
            if in_green:
                message = threshold.green_message.format(value=value) \
                    if threshold.green_message else f"{metric_name} 正常: {value:.2f}"
                alerts.append(Alert(
                    alert_type=alert_type,
                    level=AlertLevel.GREEN,
                    message=message,
                    current_value=value,
                    suggested_action=threshold.green_action or None,
                ))
                return alerts

        # 不在红色范围，也不在绿色范围 -> 黄色预警
        message = threshold.yellow_message.format(value=value) \
            if threshold.yellow_message else f"{metric_name} 偏离正常范围: {value:.2f}"
        alerts.append(Alert(
            alert_type=alert_type,
            level=AlertLevel.YELLOW,
            message=message,
            current_value=value,
            suggested_action=threshold.yellow_action or None,
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
