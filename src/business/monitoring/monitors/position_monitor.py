"""
Position Monitor - 持仓级监控器

监控单个持仓的风险指标：
- Moneyness (虚值程度)
- Delta 变化
- Gamma 临近到期风险
- IV/HV 变化
- PREI (持仓风险暴露指数)
- DTE 到期预警
- 盈亏止盈止损
"""

import logging
from datetime import datetime
from typing import Optional

from src.business.config.monitoring_config import MonitoringConfig, PositionThresholds
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

    监控单个持仓的风险指标：
    1. Moneyness - 虚值程度，靠近平值风险增加
    2. Delta 变化 - Delta 快速变化预警
    3. Gamma 临近到期 - 到期前 Gamma 风险放大
    4. IV/HV 变化 - 波动率环境变化
    5. PREI - 综合风险暴露指数
    6. DTE - 到期日预警
    7. 盈亏 - 止盈止损检查
    """

    def __init__(self, config: MonitoringConfig) -> None:
        """初始化持仓监控器

        Args:
            config: 监控配置
        """
        self.config = config
        self.thresholds = config.position

        # 用于跟踪 Delta 变化
        self._prev_deltas: dict[str, float] = {}

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
        """评估单个持仓"""
        alerts: list[Alert] = []

        # 检查 Moneyness
        alerts.extend(self._check_moneyness(pos))

        # 检查 Delta 变化
        alerts.extend(self._check_delta_change(pos))

        # 检查 Gamma 临近到期
        alerts.extend(self._check_gamma_near_expiry(pos))

        # 检查 IV/HV
        alerts.extend(self._check_iv_hv(pos))

        # 检查 PREI
        alerts.extend(self._check_prei(pos))

        # 检查 DTE
        alerts.extend(self._check_dte(pos))

        # 检查盈亏
        alerts.extend(self._check_pnl(pos))

        # 检查 SAS (策略吸引力)
        alerts.extend(self._check_sas(pos))

        # 检查 TGR (Position Level)
        alerts.extend(self._check_tgr(pos))

        return alerts

    def _check_moneyness(self, pos: PositionData) -> list[Alert]:
        """检查虚值程度"""
        alerts: list[Alert] = []
        moneyness = pos.moneyness

        if moneyness is None:
            return alerts

        # 对于卖 Put，moneyness > 0 表示 OTM (安全)
        # 对于卖 Call，moneyness < 0 表示 OTM (安全)
        is_put = pos.option_type == "put"

        if is_put:
            # Sell Put: S > K 为 OTM，moneyness > 0
            if moneyness < self.thresholds.moneyness_red_below:
                alerts.append(
                    Alert(
                        alert_type=AlertType.MONEYNESS,
                        level=AlertLevel.RED,
                        message=f"持仓 {pos.symbol} 已变为 ITM (Moneyness={moneyness:.2%})",
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        current_value=moneyness,
                        threshold_value=self.thresholds.moneyness_red_below,
                        suggested_action="考虑止损或展期",
                    )
                )
            elif moneyness < self.thresholds.moneyness_yellow_range[1]:
                alerts.append(
                    Alert(
                        alert_type=AlertType.MONEYNESS,
                        level=AlertLevel.YELLOW,
                        message=f"持仓 {pos.symbol} 接近平值 (Moneyness={moneyness:.2%})",
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        current_value=moneyness,
                        suggested_action="密切关注标的走势",
                    )
                )
        else:
            # Sell Call: S < K 为 OTM，moneyness < 0
            if moneyness > -self.thresholds.moneyness_red_below:
                alerts.append(
                    Alert(
                        alert_type=AlertType.MONEYNESS,
                        level=AlertLevel.RED,
                        message=f"持仓 {pos.symbol} 已变为 ITM (Moneyness={moneyness:.2%})",
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        current_value=moneyness,
                        suggested_action="考虑止损或展期",
                    )
                )

        return alerts

    def _check_delta_change(self, pos: PositionData) -> list[Alert]:
        """检查 Delta 变化"""
        alerts: list[Alert] = []
        delta = pos.delta

        if delta is None:
            return alerts

        # 检查 Delta 绝对值是否过高
        if abs(delta) > self.thresholds.delta_red_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.DELTA_CHANGE,
                    level=AlertLevel.RED,
                    message=f"持仓 {pos.symbol} Delta 过高: {delta:.2f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=delta,
                    threshold_value=self.thresholds.delta_red_above,
                    suggested_action="Delta 接近 1，期权类似标的，考虑平仓",
                )
            )

        # 检查 Delta 变化幅度
        prev_delta = self._prev_deltas.get(pos.position_id)
        if prev_delta is not None:
            delta_change = abs(delta - prev_delta)
            if delta_change > self.thresholds.delta_change_warning:
                alerts.append(
                    Alert(
                        alert_type=AlertType.DELTA_CHANGE,
                        level=AlertLevel.YELLOW,
                        message=f"持仓 {pos.symbol} Delta 变化较大: {delta_change:.2f}",
                        symbol=pos.symbol,
                        position_id=pos.position_id,
                        current_value=delta_change,
                        threshold_value=self.thresholds.delta_change_warning,
                        details={"prev_delta": prev_delta, "current_delta": delta},
                        suggested_action="关注 Delta 变化趋势",
                    )
                )

        # 更新历史 Delta
        self._prev_deltas[pos.position_id] = delta

        return alerts

    def _check_gamma_near_expiry(self, pos: PositionData) -> list[Alert]:
        """检查临近到期的 Gamma 风险"""
        alerts: list[Alert] = []
        gamma = pos.gamma
        dte = pos.dte

        if gamma is None or dte is None:
            return alerts

        # 临近到期时，Gamma 风险放大
        gamma_abs = abs(gamma)
        effective_threshold = self.thresholds.gamma_red_above

        if dte <= self.thresholds.dte_urgent_days:
            # 临近到期，降低 Gamma 阈值
            effective_threshold *= (1 / self.thresholds.gamma_near_expiry_multiplier)

        if gamma_abs > effective_threshold:
            alerts.append(
                Alert(
                    alert_type=AlertType.GAMMA_NEAR_EXPIRY,
                    level=AlertLevel.RED if dte <= 3 else AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} Gamma 风险高: {gamma:.4f} (DTE={dte})",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=gamma_abs,
                    threshold_value=effective_threshold,
                    details={"dte": dte},
                    suggested_action="临近到期 Gamma 放大，考虑平仓或展期",
                )
            )
        elif gamma_abs > self.thresholds.gamma_yellow_range[0]:
            alerts.append(
                Alert(
                    alert_type=AlertType.GAMMA_NEAR_EXPIRY,
                    level=AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} Gamma 偏高: {gamma:.4f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=gamma_abs,
                    suggested_action="关注 Gamma 风险",
                )
            )

        return alerts

    def _check_iv_hv(self, pos: PositionData) -> list[Alert]:
        """检查 IV/HV 变化"""
        alerts: list[Alert] = []
        iv_hv = pos.iv_hv_ratio

        if iv_hv is None:
            return alerts

        if iv_hv < self.thresholds.iv_hv_unfavorable_below:
            alerts.append(
                Alert(
                    alert_type=AlertType.IV_HV_CHANGE,
                    level=AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} IV/HV 偏低: {iv_hv:.2f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=iv_hv,
                    threshold_value=self.thresholds.iv_hv_unfavorable_below,
                    suggested_action="IV 相对 HV 偏低，持仓吸引力下降",
                )
            )
        elif iv_hv > self.thresholds.iv_hv_favorable_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.IV_HV_CHANGE,
                    level=AlertLevel.GREEN,
                    message=f"持仓 {pos.symbol} IV/HV 良好: {iv_hv:.2f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=iv_hv,
                    suggested_action="IV 相对 HV 偏高，有利于期权卖方",
                )
            )

        return alerts

    def _check_prei(self, pos: PositionData) -> list[Alert]:
        """检查 PREI"""
        alerts: list[Alert] = []
        prei = pos.prei

        if prei is None:
            return alerts

        if prei > self.thresholds.prei_red_above:
            alerts.append(
                Alert(
                    alert_type=AlertType.PREI_HIGH,
                    level=AlertLevel.RED,
                    message=f"持仓 {pos.symbol} PREI 过高: {prei:.1f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=prei,
                    threshold_value=self.thresholds.prei_red_above,
                    suggested_action="风险暴露过高，考虑减仓或对冲",
                )
            )
        elif prei > self.thresholds.prei_yellow_range[0]:
            alerts.append(
                Alert(
                    alert_type=AlertType.PREI_HIGH,
                    level=AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} PREI 偏高: {prei:.1f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=prei,
                    suggested_action="关注风险暴露",
                )
            )

        return alerts

    def _check_dte(self, pos: PositionData) -> list[Alert]:
        """检查 DTE"""
        alerts: list[Alert] = []
        dte = pos.dte

        if dte is None:
            return alerts

        if dte <= self.thresholds.dte_urgent_days:
            alerts.append(
                Alert(
                    alert_type=AlertType.DTE_WARNING,
                    level=AlertLevel.RED,
                    message=f"持仓 {pos.symbol} 即将到期: {dte} 天",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=dte,
                    threshold_value=self.thresholds.dte_urgent_days,
                    suggested_action="临近到期，需要决定平仓或展期",
                )
            )
        elif dte <= self.thresholds.dte_warning_days:
            alerts.append(
                Alert(
                    alert_type=AlertType.DTE_WARNING,
                    level=AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} 接近到期: {dte} 天",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=dte,
                    threshold_value=self.thresholds.dte_warning_days,
                    suggested_action="开始考虑出场策略",
                )
            )

        return alerts

    def _check_pnl(self, pos: PositionData) -> list[Alert]:
        """检查盈亏"""
        alerts: list[Alert] = []
        pnl_pct = pos.unrealized_pnl_pct

        if pnl_pct is None:
            return alerts

        if pnl_pct >= self.thresholds.take_profit_pct:
            alerts.append(
                Alert(
                    alert_type=AlertType.PROFIT_TARGET,
                    level=AlertLevel.GREEN,
                    message=f"持仓 {pos.symbol} 达到止盈目标: {pnl_pct:.1%}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=pnl_pct,
                    threshold_value=self.thresholds.take_profit_pct,
                    suggested_action="考虑止盈平仓，锁定利润",
                )
            )
        elif pnl_pct <= self.thresholds.stop_loss_pct:
            alerts.append(
                Alert(
                    alert_type=AlertType.STOP_LOSS,
                    level=AlertLevel.RED,
                    message=f"持仓 {pos.symbol} 触发止损: {pnl_pct:.1%}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=pnl_pct,
                    threshold_value=self.thresholds.stop_loss_pct,
                    suggested_action="触发止损，执行风险管理",
                )
            )

        return alerts

    def _check_sas(self, pos: PositionData) -> list[Alert]:
        """检查 SAS (Strategy Attractiveness Score)

        SAS 阈值规则：
        - SAS < 30: RED - 策略失效，建议平仓
        - SAS 30-50: YELLOW - 边缘区域，需要评估
        - SAS >= 50: GREEN - 可持有
        """
        alerts: list[Alert] = []
        sas = pos.sas

        if sas is None:
            return alerts

        # 使用配置的阈值或默认值
        sas_red = getattr(self.thresholds, "sas_red_below", 30.0)
        sas_yellow = getattr(self.thresholds, "sas_yellow_range", (30.0, 50.0))

        if sas < sas_red:
            alerts.append(
                Alert(
                    alert_type=AlertType.TGR_LOW,  # 复用 TGR_LOW 类型
                    level=AlertLevel.RED,
                    message=f"持仓 {pos.symbol} SAS 过低: {sas:.1f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=sas,
                    threshold_value=sas_red,
                    suggested_action="策略吸引力不足，考虑平仓",
                    details={"metric": "sas"},
                )
            )
        elif sas < sas_yellow[1]:
            alerts.append(
                Alert(
                    alert_type=AlertType.TGR_LOW,
                    level=AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} SAS 偏低: {sas:.1f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=sas,
                    suggested_action="策略吸引力边缘，密切关注",
                    details={"metric": "sas"},
                )
            )

        return alerts

    def _check_tgr(self, pos: PositionData) -> list[Alert]:
        """检查 TGR (Theta/Gamma Ratio) at Position Level

        TGR 阈值规则：
        - TGR < 0.1: YELLOW - 效率较低，需调整
        - TGR >= 0.1: GREEN - 效率良好
        """
        alerts: list[Alert] = []
        tgr = pos.tgr

        if tgr is None:
            return alerts

        # 使用配置的阈值或默认值
        tgr_yellow = getattr(self.thresholds, "tgr_yellow_below", 0.1)

        if tgr < tgr_yellow:
            alerts.append(
                Alert(
                    alert_type=AlertType.TGR_LOW,
                    level=AlertLevel.YELLOW,
                    message=f"持仓 {pos.symbol} TGR 偏低: {tgr:.2f}",
                    symbol=pos.symbol,
                    position_id=pos.position_id,
                    current_value=tgr,
                    threshold_value=tgr_yellow,
                    suggested_action="Theta/Gamma 效率偏低，考虑调整",
                    details={"metric": "tgr"},
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
