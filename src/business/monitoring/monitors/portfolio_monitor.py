"""
Portfolio Monitor - 组合级监控器

监控组合级风险指标：
- Beta 加权 Delta
- 组合 Vega 暴露
- 组合 Gamma 暴露
- Theta/Gamma 比率 (TGR)
- 集中度风险
"""

import logging
from datetime import datetime
from typing import Optional

from src.business.config.monitoring_config import MonitoringConfig, PortfolioThresholds
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorStatus,
    PortfolioMetrics,
    PositionData,
)

logger = logging.getLogger(__name__)


class PortfolioMonitor:
    """组合级监控器

    监控组合层面的风险指标：
    1. Beta 加权 Delta - 市场风险敞口
    2. 组合 Vega - 波动率风险
    3. 组合 Gamma - 凸性风险
    4. TGR - 时间衰减效率
    5. 集中度 - 单一标的风险
    """

    def __init__(self, config: MonitoringConfig) -> None:
        """初始化组合监控器

        Args:
            config: 监控配置
        """
        self.config = config
        self.thresholds = config.portfolio

    def evaluate(
        self,
        positions: list[PositionData],
        spy_beta_map: Optional[dict[str, float]] = None,
    ) -> tuple[list[Alert], PortfolioMetrics]:
        """评估组合风险

        Args:
            positions: 持仓数据列表
            spy_beta_map: 标的对 SPY 的 Beta 映射表

        Returns:
            (预警列表, 组合指标)
        """
        alerts: list[Alert] = []

        if not positions:
            return alerts, PortfolioMetrics()

        # 计算组合指标
        metrics = self._calc_portfolio_metrics(positions, spy_beta_map)

        # 检查 Beta 加权 Delta
        alerts.extend(self._check_beta_weighted_delta(metrics))

        # 检查组合 Vega
        alerts.extend(self._check_portfolio_vega(metrics))

        # 检查组合 Gamma
        alerts.extend(self._check_portfolio_gamma(metrics))

        # 检查 TGR
        alerts.extend(self._check_portfolio_tgr(metrics))

        # 检查集中度
        alerts.extend(self._check_concentration(positions, metrics))

        return alerts, metrics

    def _calc_portfolio_metrics(
        self,
        positions: list[PositionData],
        spy_beta_map: Optional[dict[str, float]],
    ) -> PortfolioMetrics:
        """计算组合指标"""
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        beta_weighted_delta = 0.0

        for pos in positions:
            qty = pos.quantity
            multiplier = 100  # 期权合约乘数

            if pos.delta is not None:
                delta_exposure = pos.delta * qty * multiplier
                total_delta += delta_exposure

                # Beta 加权 Delta
                beta = 1.0
                if spy_beta_map and pos.underlying in spy_beta_map:
                    beta = spy_beta_map[pos.underlying]
                beta_weighted_delta += delta_exposure * beta

            if pos.gamma is not None:
                total_gamma += pos.gamma * qty * multiplier

            if pos.theta is not None:
                total_theta += pos.theta * qty * multiplier

            if pos.vega is not None:
                total_vega += pos.vega * qty * multiplier

        # 计算组合 TGR
        portfolio_tgr = None
        if total_gamma != 0:
            portfolio_tgr = abs(total_theta) / abs(total_gamma)

        # 计算最大集中度
        symbol_exposure: dict[str, float] = {}
        for pos in positions:
            underlying = pos.underlying
            if pos.delta is not None:
                exposure = abs(pos.delta * pos.quantity * 100)
                symbol_exposure[underlying] = symbol_exposure.get(underlying, 0) + exposure

        max_weight = 0.0
        if symbol_exposure and total_delta != 0:
            max_exposure = max(symbol_exposure.values())
            max_weight = max_exposure / abs(total_delta) if total_delta != 0 else 0

        return PortfolioMetrics(
            beta_weighted_delta=beta_weighted_delta,
            total_delta=total_delta,
            total_gamma=total_gamma,
            total_theta=total_theta,
            total_vega=total_vega,
            portfolio_tgr=portfolio_tgr,
            max_symbol_weight=max_weight,
            timestamp=datetime.now(),
        )

    def _check_beta_weighted_delta(
        self,
        metrics: PortfolioMetrics,
    ) -> list[Alert]:
        """检查 Beta 加权 Delta"""
        alerts: list[Alert] = []
        value = metrics.beta_weighted_delta

        if value is None:
            return alerts

        threshold = self.thresholds.beta_weighted_delta

        if threshold.red_above and value > threshold.red_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.DELTA_EXPOSURE,
                    level=AlertLevel.RED,
                    message=f"Beta 加权 Delta 过高: {value:.0f} > {threshold.red_above}",
                    current_value=value,
                    threshold_value=threshold.red_above,
                    suggested_action="减少多头 Delta 暴露或对冲",
                )
            )
        elif threshold.red_below and value < threshold.red_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.DELTA_EXPOSURE,
                    level=AlertLevel.RED,
                    message=f"Beta 加权 Delta 过低: {value:.0f} < {threshold.red_below}",
                    current_value=value,
                    threshold_value=threshold.red_below,
                    suggested_action="减少空头 Delta 暴露或对冲",
                )
            )
        elif threshold.yellow:
            yellow_low, yellow_high = threshold.yellow
            if value < yellow_low or value > yellow_high:
                alerts.append(
                    Alert(
                        alert_type=AlertType.DELTA_EXPOSURE,
                        level=AlertLevel.YELLOW,
                        message=f"Beta 加权 Delta 偏离中性: {value:.0f}",
                        current_value=value,
                        suggested_action="关注 Delta 暴露变化",
                    )
                )

        return alerts

    def _check_portfolio_vega(
        self,
        metrics: PortfolioMetrics,
    ) -> list[Alert]:
        """检查组合 Vega"""
        alerts: list[Alert] = []
        value = metrics.total_vega

        if value is None:
            return alerts

        threshold = self.thresholds.portfolio_vega

        if threshold.red_above and value > threshold.red_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.VEGA_EXPOSURE,
                    level=AlertLevel.RED,
                    message=f"组合 Vega 暴露过高: {value:.0f} > {threshold.red_above}",
                    current_value=value,
                    threshold_value=threshold.red_above,
                    suggested_action="减少 Vega 暴露，考虑平仓部分头寸",
                )
            )
        elif threshold.red_below and value < threshold.red_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.VEGA_EXPOSURE,
                    level=AlertLevel.RED,
                    message=f"组合 Vega 暴露过低: {value:.0f} < {threshold.red_below}",
                    current_value=value,
                    threshold_value=threshold.red_below,
                    suggested_action="Vega 空头过大，波动率上升风险高",
                )
            )

        return alerts

    def _check_portfolio_gamma(
        self,
        metrics: PortfolioMetrics,
    ) -> list[Alert]:
        """检查组合 Gamma"""
        alerts: list[Alert] = []
        value = metrics.total_gamma

        if value is None:
            return alerts

        threshold = self.thresholds.portfolio_gamma

        if threshold.red_below and value < threshold.red_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.GAMMA_EXPOSURE,
                    level=AlertLevel.RED,
                    message=f"组合 Gamma 空头过大: {value:.0f} < {threshold.red_below}",
                    current_value=value,
                    threshold_value=threshold.red_below,
                    suggested_action="Gamma 空头风险高，大幅波动时亏损加速",
                )
            )
        elif threshold.yellow:
            yellow_low, yellow_high = threshold.yellow
            if value < yellow_low:
                alerts.append(
                    Alert(
                        alert_type=AlertType.GAMMA_EXPOSURE,
                        level=AlertLevel.YELLOW,
                        message=f"组合 Gamma 空头偏大: {value:.0f}",
                        current_value=value,
                        suggested_action="关注 Gamma 风险",
                    )
                )

        return alerts

    def _check_portfolio_tgr(
        self,
        metrics: PortfolioMetrics,
    ) -> list[Alert]:
        """检查组合 TGR"""
        alerts: list[Alert] = []
        value = metrics.portfolio_tgr

        if value is None:
            return alerts

        if value < self.thresholds.tgr_red_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.TGR_LOW,
                    level=AlertLevel.RED,
                    message=f"组合 TGR 过低: {value:.3f} < {self.thresholds.tgr_red_below}",
                    current_value=value,
                    threshold_value=self.thresholds.tgr_red_below,
                    suggested_action="时间衰减效率不足，考虑调整持仓",
                )
            )
        elif value < self.thresholds.tgr_yellow_range[1]:
            alerts.append(
                Alert(
                    alert_type=AlertType.TGR_LOW,
                    level=AlertLevel.YELLOW,
                    message=f"组合 TGR 偏低: {value:.3f}",
                    current_value=value,
                    suggested_action="关注时间衰减效率",
                )
            )
        elif value >= self.thresholds.tgr_green_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.TGR_LOW,
                    level=AlertLevel.GREEN,
                    message=f"组合 TGR 良好: {value:.3f}",
                    current_value=value,
                    suggested_action="时间衰减效率良好",
                )
            )

        return alerts

    def _check_concentration(
        self,
        positions: list[PositionData],
        metrics: PortfolioMetrics,
    ) -> list[Alert]:
        """检查集中度"""
        alerts: list[Alert] = []

        if metrics.max_symbol_weight is None:
            return alerts

        if metrics.max_symbol_weight > self.thresholds.max_concentration:
            alerts.append(
                Alert(
                    alert_type=AlertType.CONCENTRATION,
                    level=AlertLevel.YELLOW,
                    message=f"单一标的集中度过高: {metrics.max_symbol_weight:.1%}",
                    current_value=metrics.max_symbol_weight,
                    threshold_value=self.thresholds.max_concentration,
                    suggested_action="分散持仓，降低单一标的风险",
                )
            )

        return alerts

    def get_status(self, alerts: list[Alert]) -> MonitorStatus:
        """根据预警确定组合状态"""
        if any(a.level == AlertLevel.RED for a in alerts):
            return MonitorStatus.RED
        elif any(a.level == AlertLevel.YELLOW for a in alerts):
            return MonitorStatus.YELLOW
        else:
            return MonitorStatus.GREEN
