"""
Portfolio Monitor - 组合级监控器

监控组合级风险指标（使用 NLV 归一化百分比）：
- Beta 加权 Delta % - 方向性杠杆
- Gamma % - 凸性/暴跌风险
- Vega % - 波动率风险（做空方向严格监控）
- Theta % - 每日收租率
- Theta/Gamma 比率 (TGR)
- 集中度风险 (HHI)
- Vega 加权 IV/HV - 持仓质量

设计原则：
- 只做阈值检查，不做计算（遵循 Decision #0）
- 所有指标由 engine/portfolio 层计算
- 接收预计算的 PortfolioMetrics，只做规则判断
- 使用通用 _check_threshold 函数，消息和建议从配置中读取
- 优先使用 NLV 归一化指标，实现账户大小无关的风险评估
"""

import logging

from src.business.config.monitoring_config import MonitoringConfig, ThresholdRange
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorStatus,
)
from src.engine.models.portfolio import PortfolioMetrics

logger = logging.getLogger(__name__)


class PortfolioMonitor:
    """组合级监控器

    使用 NLV 归一化指标监控组合层面的风险：
    1. Beta 加权 Delta % - 方向性杠杆（±20%绿色，±50%红色）
    2. Gamma % - 凸性/暴跌风险（<-0.5%红色）
    3. Vega % - 波动率风险（<-0.5%做空方向红色）
    4. Theta % - 每日收租率（0.05~0.15%绿色，>0.30%或<0%红色）
    5. TGR - 时间衰减效率（≥0.15绿色，<0.05红色）
    6. 集中度 (HHI) - 单一标的风险（<0.25绿色，>0.5红色）
    7. Vega加权 IV/HV - 持仓质量（>1.0绿色，<0.8红色）
    """

    def __init__(self, config: MonitoringConfig) -> None:
        """初始化组合监控器

        Args:
            config: 监控配置
        """
        self.config = config
        self.thresholds = config.portfolio

    def evaluate(self, metrics: PortfolioMetrics) -> list[Alert]:
        """评估组合风险

        使用 NLV 归一化百分比指标进行阈值检查，实现账户大小无关的风险评估。
        只做阈值检查，不做计算。所有指标由 engine 层预计算。
        使用通用 _check_threshold 函数，消息和建议从配置中读取。

        Args:
            metrics: 由 engine/portfolio 层预计算的组合指标

        Returns:
            预警列表
        """
        alerts: list[Alert] = []

        # === NLV 归一化百分比指标（优先使用，账户大小无关）===

        # 检查 Beta 加权 Delta % (方向性杠杆)
        alerts.extend(self._check_threshold(
            value=metrics.beta_weighted_delta_pct,
            threshold=self.thresholds.beta_weighted_delta_pct,
            metric_name="beta_weighted_delta_pct",
        ))

        # 检查 Gamma % (凸性/暴跌风险)
        alerts.extend(self._check_threshold(
            value=metrics.gamma_pct,
            threshold=self.thresholds.gamma_pct,
            metric_name="gamma_pct",
        ))

        # 检查 Vega % (波动率风险，做空方向严格监控)
        alerts.extend(self._check_threshold(
            value=metrics.vega_pct,
            threshold=self.thresholds.vega_pct,
            metric_name="vega_pct",
        ))

        # 检查 Theta % (每日收租率)
        alerts.extend(self._check_threshold(
            value=metrics.theta_pct,
            threshold=self.thresholds.theta_pct,
            metric_name="theta_pct",
        ))

        # === 比率指标（已经是归一化的）===

        # 检查 TGR (Theta/Gamma 效率)
        alerts.extend(self._check_threshold(
            value=metrics.portfolio_tgr,
            threshold=self.thresholds.portfolio_tgr,
            metric_name="portfolio_tgr",
        ))

        # 检查集中度 (HHI)
        alerts.extend(self._check_threshold(
            value=metrics.concentration_hhi,
            threshold=self.thresholds.concentration_hhi,
            metric_name="concentration_hhi",
        ))

        # 检查 Vega 加权 IV/HV (持仓质量)
        alerts.extend(self._check_threshold(
            value=metrics.vega_weighted_iv_hv,
            threshold=self.thresholds.vega_weighted_iv_hv,
            metric_name="vega_weighted_iv_hv",
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

        # 检查黄色范围
        if threshold.yellow:
            yellow_low, yellow_high = threshold.yellow
            if value < yellow_low or value > yellow_high:
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
        """根据预警确定组合状态"""
        if any(a.level == AlertLevel.RED for a in alerts):
            return MonitorStatus.RED
        elif any(a.level == AlertLevel.YELLOW for a in alerts):
            return MonitorStatus.YELLOW
        else:
            return MonitorStatus.GREEN
