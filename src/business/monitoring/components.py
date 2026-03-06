"""
Monitoring Components - 可复用的监控检查组件

提供 Protocol 定义和从 PositionMonitor 中提取的可复用组件。
策略可从此组件库中挑选组件，组装自定义监控逻辑。

组件分为:
- 卖方策略通用组件 (Short options)
- 买方策略预留组件 (Long options)

使用示例:
    from src.business.monitoring.components import TakeProfitCheck, StopLossCheck

    checks = [
        TakeProfitCheck(dte_threshold=14, pnl_threshold=0.7),
        StopLossCheck(pnl_threshold=-1.0),
        DTEWarningCheck(warning_days=7, critical_days=2),
    ]

    for pos in positions:
        for check in checks:
            passed, reason, urgency = check.check(pos)
"""

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.business.monitoring.models import PositionData

logger = logging.getLogger(__name__)


# ==========================
# 协议定义
# ==========================

@runtime_checkable
class PositionCheck(Protocol):
    """持仓检查协议

    返回 (should_act, reason, urgency):
    - should_act=True: 需要采取行动（平仓/展期等）
    - reason: 说明原因
    - urgency: "immediate" | "soon" | "monitor"
    """

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        ...


# ==========================
# 卖方策略通用组件
# ==========================

@dataclass
class TakeProfitCheck:
    """提前止盈检查

    DTE + PnL 联合止盈：当 DTE 低于阈值且盈利达到目标时触发。

    Args:
        dte_threshold: DTE 门槛天数
        pnl_threshold: 盈利百分比门槛 (如 0.7 表示 70%)
    """
    dte_threshold: int = 14
    pnl_threshold: float = 0.70

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.dte is None or position.unrealized_pnl_pct is None:
            return False, "", "monitor"

        if position.dte <= self.dte_threshold and position.unrealized_pnl_pct >= self.pnl_threshold:
            return (
                True,
                f"DTE={position.dte} <= {self.dte_threshold} 且盈利 "
                f"{position.unrealized_pnl_pct:.1%} >= {self.pnl_threshold:.0%}，建议止盈",
                "immediate",
            )

        return False, "", "monitor"


@dataclass
class StopLossCheck:
    """止损检查

    当亏损超过阈值时触发。

    Args:
        pnl_threshold: 亏损百分比门槛 (如 -1.0 表示 -100%)
    """
    pnl_threshold: float = -1.0

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.unrealized_pnl_pct is None:
            return False, "", "monitor"

        if position.unrealized_pnl_pct < self.pnl_threshold:
            return (
                True,
                f"亏损 {position.unrealized_pnl_pct:.1%} 超过阈值 {self.pnl_threshold:.0%}",
                "immediate",
            )

        return False, "", "monitor"


@dataclass
class DTEWarningCheck:
    """DTE 预警检查

    临近到期预警。

    Args:
        warning_days: 黄色预警天数
        critical_days: 红色预警天数 (应平仓或展期)
    """
    warning_days: int = 7
    critical_days: int = 2

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.dte is None:
            return False, "", "monitor"

        if position.dte <= self.critical_days:
            pnl = position.unrealized_pnl_pct or 0
            if pnl > 0:
                return (
                    True,
                    f"DTE={position.dte} <= {self.critical_days}，已盈利 {pnl:.1%}，应平仓止盈",
                    "immediate",
                )
            else:
                return (
                    True,
                    f"DTE={position.dte} <= {self.critical_days}，亏损 {pnl:.1%}，应展期或平仓",
                    "immediate",
                )

        if position.dte <= self.warning_days:
            return (
                False,
                f"DTE={position.dte} <= {self.warning_days}，关注到期风险",
                "soon",
            )

        return False, "", "monitor"


@dataclass
class TGRMonitorCheck:
    """TGR 监控检查

    TGR (Theta/Gamma Ratio) 低于阈值时预警。

    Args:
        min_tgr: 最低 TGR
    """
    min_tgr: float = 0.8

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.tgr is None:
            return False, "", "monitor"

        if position.tgr < self.min_tgr:
            return (
                True,
                f"TGR={position.tgr:.2f} < {self.min_tgr}，时间衰减效率不足",
                "soon",
            )

        return False, f"TGR={position.tgr:.2f}，正常", "monitor"


@dataclass
class OTMCheck:
    """OTM 百分比检查

    当 OTM% 低于阈值时预警（期权变得接近 ATM/ITM）。

    Args:
        min_otm_pct: 最低 OTM 百分比
    """
    min_otm_pct: float = 0.05

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.otm_pct is None:
            return False, "", "monitor"

        if position.otm_pct < self.min_otm_pct:
            return (
                True,
                f"OTM%={position.otm_pct:.1%} < {self.min_otm_pct:.0%}，接近 ATM/ITM",
                "soon",
            )

        return False, f"OTM%={position.otm_pct:.1%}，安全", "monitor"


# ==========================
# 买方策略预留组件
# ==========================

@dataclass
class ThetaDecayCheck:
    """时间衰减效率检查（买方用）

    买方策略需要监控时间衰减对头寸的影响。
    当日 theta 损耗占持仓价值的比例超过阈值时预警。

    Args:
        max_daily_theta_pct: 最大日 theta 损耗占比
    """
    max_daily_theta_pct: float = 0.03  # 每日 3%

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.theta is None or position.current_price is None:
            return False, "", "monitor"

        if position.current_price == 0:
            return False, "", "monitor"

        # 买方的 theta 是负数（持仓亏损），取绝对值计算比例
        daily_theta_pct = abs(position.theta) / position.current_price

        if daily_theta_pct > self.max_daily_theta_pct:
            return (
                True,
                f"日 Theta 损耗={daily_theta_pct:.1%} > {self.max_daily_theta_pct:.0%}，"
                f"时间价值流失过快",
                "soon",
            )

        return False, f"日 Theta 损耗={daily_theta_pct:.1%}，正常", "monitor"


@dataclass
class IVCrushCheck:
    """IV 暴跌检查（买方用）

    买方持有 long vega 头寸，IV 暴跌会造成损失。
    当 IV/HV 比率跌破阈值时预警。

    Args:
        iv_drop_threshold: IV/HV 比率下限
    """
    iv_drop_threshold: float = 0.8

    def check(self, position: PositionData) -> tuple[bool, str, str]:
        if position.iv_hv_ratio is None:
            return False, "", "monitor"

        if position.iv_hv_ratio < self.iv_drop_threshold:
            return (
                True,
                f"IV/HV={position.iv_hv_ratio:.2f} < {self.iv_drop_threshold}，"
                f"IV 偏低/已暴跌，买方 vega 受损",
                "immediate",
            )

        return False, f"IV/HV={position.iv_hv_ratio:.2f}，正常", "monitor"
