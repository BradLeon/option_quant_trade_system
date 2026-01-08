"""
Capital Monitor - 资金级监控器

监控资金层面的风险指标（核心风控四大支柱）：
1. Margin Utilization (保证金使用率) - 生存：距离追保的距离
2. Cash Ratio (现金留存率) - 流动性：操作灵活度
3. Gross Leverage (总名义杠杆) - 敞口：防止"虚胖"
4. Stress Test Loss (压力测试风险) - 稳健：尾部风险保护

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

    监控资金层面的风险指标（核心风控四大支柱）：
    1. Margin Utilization - 保证金使用率（生存）
    2. Cash Ratio - 现金留存率（流动性）
    3. Gross Leverage - 总名义杠杆（敞口）
    4. Stress Test Loss - 压力测试风险（稳健）

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

        核心风控四大支柱：
        1. Margin Utilization - 保证金使用率（生存）
        2. Cash Ratio - 现金留存率（流动性）
        3. Gross Leverage - 总名义杠杆（敞口）
        4. Stress Test Loss - 压力测试风险（稳健）

        Args:
            metrics: 资金指标

        Returns:
            预警列表
        """
        alerts: list[Alert] = []

        # 1. 检查 Margin Utilization (保证金使用率)
        alerts.extend(self._check_threshold(
            value=metrics.margin_utilization,
            threshold=self.thresholds.margin_utilization,
            metric_name="margin_utilization",
        ))

        # 2. 检查 Cash Ratio (现金留存率)
        alerts.extend(self._check_threshold(
            value=metrics.cash_ratio,
            threshold=self.thresholds.cash_ratio,
            metric_name="cash_ratio",
        ))

        # 3. 检查 Gross Leverage (总名义杠杆)
        alerts.extend(self._check_threshold(
            value=metrics.gross_leverage,
            threshold=self.thresholds.gross_leverage,
            metric_name="gross_leverage",
        ))

        # 4. 检查 Stress Test Loss (压力测试风险)
        alerts.extend(self._check_threshold(
            value=metrics.stress_test_loss,
            threshold=self.thresholds.stress_test_loss,
            metric_name="stress_test_loss",
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
