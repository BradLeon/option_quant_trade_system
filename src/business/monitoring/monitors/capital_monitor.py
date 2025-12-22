"""
Capital Monitor - 资金级监控器

监控资金层面的风险指标：
- Sharpe Ratio
- Kelly 使用率
- 保证金使用率
- 回撤
"""

import logging
from datetime import datetime
from typing import Optional

from src.business.config.monitoring_config import CapitalThresholds, MonitoringConfig
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    CapitalMetrics,
    MonitorStatus,
)

logger = logging.getLogger(__name__)


class CapitalMonitor:
    """资金级监控器

    监控资金层面的风险指标：
    1. Sharpe Ratio - 风险调整收益
    2. Kelly 使用率 - 仓位是否合理
    3. 保证金使用率 - 杠杆风险
    4. 回撤 - 最大回撤控制
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

        Args:
            metrics: 资金指标

        Returns:
            预警列表
        """
        alerts: list[Alert] = []

        # 检查 Sharpe Ratio
        alerts.extend(self._check_sharpe_ratio(metrics))

        # 检查 Kelly 使用率
        alerts.extend(self._check_kelly_usage(metrics))

        # 检查保证金使用率
        alerts.extend(self._check_margin_usage(metrics))

        # 检查回撤
        alerts.extend(self._check_drawdown(metrics))

        return alerts

    def _check_sharpe_ratio(
        self,
        metrics: CapitalMetrics,
    ) -> list[Alert]:
        """检查 Sharpe Ratio"""
        alerts: list[Alert] = []
        sharpe = metrics.sharpe_ratio

        if sharpe is None:
            return alerts

        if sharpe < self.thresholds.sharpe_red_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.SHARPE_LOW,
                    level=AlertLevel.RED,
                    message=f"Sharpe Ratio 过低: {sharpe:.2f} < {self.thresholds.sharpe_red_below}",
                    current_value=sharpe,
                    threshold_value=self.thresholds.sharpe_red_below,
                    suggested_action="风险调整收益不佳，检视策略执行",
                )
            )
        elif sharpe < self.thresholds.sharpe_yellow_range[1]:
            alerts.append(
                Alert(
                    alert_type=AlertType.SHARPE_LOW,
                    level=AlertLevel.YELLOW,
                    message=f"Sharpe Ratio 偏低: {sharpe:.2f}",
                    current_value=sharpe,
                    suggested_action="关注风险调整收益",
                )
            )
        elif sharpe >= self.thresholds.sharpe_green_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.SHARPE_LOW,
                    level=AlertLevel.GREEN,
                    message=f"Sharpe Ratio 良好: {sharpe:.2f}",
                    current_value=sharpe,
                    suggested_action="风险调整收益良好",
                )
            )

        return alerts

    def _check_kelly_usage(
        self,
        metrics: CapitalMetrics,
    ) -> list[Alert]:
        """检查 Kelly 使用率"""
        alerts: list[Alert] = []
        kelly_usage = metrics.kelly_usage

        if kelly_usage is None:
            return alerts

        if kelly_usage > self.thresholds.kelly_usage_red_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.KELLY_USAGE,
                    level=AlertLevel.RED,
                    message=f"Kelly 使用率过高: {kelly_usage:.1%} > {self.thresholds.kelly_usage_red_above:.0%}",
                    current_value=kelly_usage,
                    threshold_value=self.thresholds.kelly_usage_red_above,
                    suggested_action="仓位过重，考虑减仓",
                )
            )
        elif kelly_usage < self.thresholds.kelly_usage_opportunity_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.KELLY_USAGE,
                    level=AlertLevel.GREEN,
                    message=f"Kelly 使用率偏低: {kelly_usage:.1%}，有加仓空间",
                    current_value=kelly_usage,
                    threshold_value=self.thresholds.kelly_usage_opportunity_below,
                    suggested_action="仓位较轻，可寻找新机会",
                )
            )
        else:
            green_low, green_high = self.thresholds.kelly_usage_green_range
            if green_low <= kelly_usage <= green_high:
                alerts.append(
                    Alert(
                        alert_type=AlertType.KELLY_USAGE,
                        level=AlertLevel.GREEN,
                        message=f"Kelly 使用率适中: {kelly_usage:.1%}",
                        current_value=kelly_usage,
                        suggested_action="仓位合理",
                    )
                )

        return alerts

    def _check_margin_usage(
        self,
        metrics: CapitalMetrics,
    ) -> list[Alert]:
        """检查保证金使用率"""
        alerts: list[Alert] = []
        margin_usage = metrics.margin_usage

        if margin_usage is None:
            return alerts

        if margin_usage > self.thresholds.margin_red_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.MARGIN_WARNING,
                    level=AlertLevel.RED,
                    message=f"保证金使用率过高: {margin_usage:.1%} > {self.thresholds.margin_red_above:.0%}",
                    current_value=margin_usage,
                    threshold_value=self.thresholds.margin_red_above,
                    suggested_action="保证金使用率过高，有追保风险，立即减仓",
                )
            )
        elif margin_usage > self.thresholds.margin_warning_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.MARGIN_WARNING,
                    level=AlertLevel.YELLOW,
                    message=f"保证金使用率偏高: {margin_usage:.1%}",
                    current_value=margin_usage,
                    threshold_value=self.thresholds.margin_warning_above,
                    suggested_action="保证金使用率接近警戒线，谨慎加仓",
                )
            )
        elif margin_usage < self.thresholds.margin_green_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.MARGIN_WARNING,
                    level=AlertLevel.GREEN,
                    message=f"保证金使用率健康: {margin_usage:.1%}",
                    current_value=margin_usage,
                    suggested_action="保证金使用率良好",
                )
            )

        return alerts

    def _check_drawdown(
        self,
        metrics: CapitalMetrics,
    ) -> list[Alert]:
        """检查回撤"""
        alerts: list[Alert] = []
        drawdown = metrics.current_drawdown

        if drawdown is None:
            return alerts

        if drawdown > self.thresholds.max_drawdown_red_pct:
            alerts.append(
                Alert(
                    alert_type=AlertType.DRAWDOWN,
                    level=AlertLevel.RED,
                    message=f"回撤过大: {drawdown:.1%} > {self.thresholds.max_drawdown_red_pct:.0%}",
                    current_value=drawdown,
                    threshold_value=self.thresholds.max_drawdown_red_pct,
                    suggested_action="回撤超限，执行风险控制，考虑减仓或暂停交易",
                )
            )
        elif drawdown > self.thresholds.max_drawdown_warning_pct:
            alerts.append(
                Alert(
                    alert_type=AlertType.DRAWDOWN,
                    level=AlertLevel.YELLOW,
                    message=f"回撤接近警戒线: {drawdown:.1%}",
                    current_value=drawdown,
                    threshold_value=self.thresholds.max_drawdown_warning_pct,
                    suggested_action="关注回撤变化，准备执行风控",
                )
            )

        return alerts

    def get_status(self, alerts: list[Alert]) -> MonitorStatus:
        """根据预警确定状态"""
        if any(a.level == AlertLevel.RED for a in alerts):
            return MonitorStatus.RED
        elif any(a.level == AlertLevel.YELLOW for a in alerts):
            return MonitorStatus.YELLOW
        else:
            return MonitorStatus.GREEN


def calc_capital_metrics(
    total_equity: float,
    cash_balance: float,
    maintenance_margin: float,
    realized_pnl: float,
    unrealized_pnl: float,
    sharpe_ratio: float | None = None,
    total_position_value: float | None = None,
    kelly_capacity: float | None = None,
    peak_equity: float | None = None,
) -> CapitalMetrics:
    """计算资金指标的便捷函数

    Args:
        total_equity: 总权益
        cash_balance: 现金余额
        maintenance_margin: 维持保证金
        realized_pnl: 已实现盈亏
        unrealized_pnl: 未实现盈亏
        sharpe_ratio: Sharpe 比率（可选）
        total_position_value: 总持仓价值（可选）
        kelly_capacity: Kelly 仓位容量（可选）
        peak_equity: 峰值权益（可选）

    Returns:
        CapitalMetrics
    """
    # 计算保证金使用率
    margin_usage = None
    if total_equity > 0:
        margin_usage = maintenance_margin / total_equity

    # 计算 Kelly 使用率
    kelly_usage = None
    if kelly_capacity and kelly_capacity > 0 and total_position_value:
        kelly_usage = total_position_value / kelly_capacity

    # 计算回撤
    current_drawdown = None
    if peak_equity and peak_equity > 0:
        current_drawdown = (peak_equity - total_equity) / peak_equity
        current_drawdown = max(0, current_drawdown)  # 确保非负

    return CapitalMetrics(
        total_equity=total_equity,
        cash_balance=cash_balance,
        maintenance_margin=maintenance_margin,
        margin_usage=margin_usage,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        sharpe_ratio=sharpe_ratio,
        total_position_value=total_position_value,
        kelly_capacity=kelly_capacity,
        kelly_usage=kelly_usage,
        peak_equity=peak_equity,
        current_drawdown=current_drawdown,
        timestamp=datetime.now(),
    )
