"""
Roll Target Calculator - 展期目标合约计算器

根据持仓状态和触发的告警，计算展期目标合约的参数：
- suggested_expiry: 目标到期日
- suggested_strike: 目标行权价（None 表示保持不变）
- suggested_dte: 目标 DTE
- roll_credit: 预期展期收益（需要行情数据）

规则来源：持仓监测指标汇总表 v2
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from src.business.monitoring.models import Alert, AlertType, PositionData
from src.engine.models.enums import StrategyType


@dataclass
class RollTarget:
    """展期目标合约参数"""

    suggested_expiry: str  # YYYY-MM-DD 格式
    suggested_strike: Optional[float]  # None = 保持不变
    suggested_dte: int
    roll_credit: Optional[float]  # 需要行情数据才能计算，暂为 None
    reason: str  # 选择理由


class RollTargetCalculator:
    """展期目标合约计算器

    根据持仓和告警计算展期目标合约参数。

    DTE 选择规则：
    - DTE/TGR 触发：选择最优 DTE（35 天）
    - Delta/OTM% 触发：保持接近当前 DTE

    Strike 调整规则：
    - DTE/TGR 触发：不调整 Strike
    - Delta/OTM% 触发：
      - PUT: 降低 Strike，目标 OTM% = 10%
      - CALL: 提高 Strike，目标 OTM% = 10%

    Usage:
        calculator = RollTargetCalculator()
        target = calculator.calculate(position, alert)
    """

    # DTE 范围配置
    MIN_DTE = 25
    MAX_DTE = 45
    IDEAL_DTE = 35

    # OTM 目标配置
    TARGET_OTM_PCT = 0.10  # 10%

    # Strike 取整步长（根据标的价格动态调整）
    STRIKE_STEP_SMALL = 1.0  # 标的价格 < $50
    STRIKE_STEP_MEDIUM = 2.5  # $50 <= 标的价格 < $100
    STRIKE_STEP_LARGE = 5.0  # 标的价格 >= $100

    # 需要调整 Strike 的告警类型
    STRIKE_ADJUST_ALERTS = {
        AlertType.DELTA_CHANGE,
        AlertType.OTM_PCT,
        AlertType.MONEYNESS,
    }

    # 需要展期到最优 DTE 的告警类型
    DTE_RESET_ALERTS = {
        AlertType.DTE_WARNING,
        AlertType.TGR_LOW,
        AlertType.POSITION_TGR,
        AlertType.GAMMA_NEAR_EXPIRY,
    }

    def __init__(
        self,
        min_dte: int = 25,
        max_dte: int = 45,
        ideal_dte: int = 35,
        target_otm_pct: float = 0.10,
    ) -> None:
        """初始化计算器

        Args:
            min_dte: 最小 DTE
            max_dte: 最大 DTE
            ideal_dte: 理想 DTE
            target_otm_pct: 目标 OTM 百分比
        """
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.ideal_dte = ideal_dte
        self.target_otm_pct = target_otm_pct

    def calculate(
        self,
        position: PositionData,
        alert: Alert,
        available_expiries: Optional[list[str]] = None,
        available_strikes: Optional[list[float]] = None,
        today: Optional[date] = None,
    ) -> RollTarget:
        """根据持仓和告警计算展期目标

        Args:
            position: 持仓数据
            alert: 触发的告警
            available_expiries: 可用的到期日列表（YYYY-MM-DD 格式，来自期权链）
            available_strikes: 可用的行权价列表（来自期权链）
            today: 今天日期（用于测试注入）

        Returns:
            RollTarget: 展期目标参数
        """
        today = today or date.today()

        # 1. 计算目标 DTE
        current_dte = position.dte or self._calc_dte(position.expiry, today)
        target_dte = self._select_target_dte(current_dte, alert.alert_type)

        # 2. 确定目标到期日
        if available_expiries:
            target_expiry = self._find_nearest_expiry(
                target_dte, available_expiries, today
            )
        else:
            # 没有可用到期日列表时，计算理论到期日
            target_expiry = self._calc_target_expiry(target_dte, today)

        # 3. 计算目标 Strike
        raw_strike = self._calc_target_strike(
            current_strike=position.strike,
            underlying_price=position.underlying_price,
            option_type=position.option_type,
            strategy_type=position.strategy_type,
            alert_type=alert.alert_type,
        )

        # 4. 从可用 Strike 中选择最接近的
        if raw_strike is not None and available_strikes:
            target_strike = self._find_nearest_strike(
                raw_strike, available_strikes, position.option_type
            )
        else:
            target_strike = raw_strike

        # 5. 构建 reason
        reason = self._build_reason(
            alert=alert,
            current_dte=current_dte,
            target_dte=target_dte,
            current_strike=position.strike,
            target_strike=target_strike,
            from_chain=bool(available_expiries or available_strikes),
        )

        return RollTarget(
            suggested_expiry=target_expiry,
            suggested_strike=target_strike,
            suggested_dte=target_dte,
            roll_credit=None,  # 需要行情数据，暂不计算
            reason=reason,
        )

    def _select_target_dte(
        self,
        current_dte: int,
        alert_type: AlertType,
    ) -> int:
        """选择目标 DTE

        规则:
        1. DTE/TGR 触发: 选择 ideal_dte (35 天)
        2. Delta/OTM% 触发: 保持接近当前 DTE
        3. 结果必须在 [min_dte, max_dte] 范围内

        Args:
            current_dte: 当前 DTE
            alert_type: 触发的告警类型

        Returns:
            目标 DTE
        """
        if alert_type in self.DTE_RESET_ALERTS:
            # 临期或效率问题 → 选择最优区间中点
            return self.ideal_dte
        else:
            # 其他触发 → 尽量保持当前 DTE，但限制在有效范围内
            target = max(self.min_dte, min(current_dte, self.max_dte))
            return target

    def _calc_target_strike(
        self,
        current_strike: Optional[float],
        underlying_price: Optional[float],
        option_type: Optional[str],
        strategy_type: Optional[StrategyType],
        alert_type: AlertType,
    ) -> Optional[float]:
        """计算目标行权价（理论值）

        规则:
        1. DTE/TGR 触发: 不调整 Strike (return None)
        2. Delta/OTM% 触发:
           - PUT: 降低 Strike，目标 OTM% = 10%
           - CALL: 提高 Strike，目标 OTM% = 10%

        Args:
            current_strike: 当前行权价
            underlying_price: 标的价格
            option_type: 期权类型 ("put" / "call")
            strategy_type: 策略类型
            alert_type: 触发的告警类型

        Returns:
            目标行权价（理论值），None 表示保持不变
        """
        # DTE/TGR 触发不调整 Strike
        if alert_type not in self.STRIKE_ADJUST_ALERTS:
            return None

        # 缺少必要数据时不调整
        if not underlying_price or not option_type:
            return None

        # 计算目标 Strike
        if option_type == "put":
            # PUT: new_strike = S × (1 - target_otm_pct)
            raw_strike = underlying_price * (1 - self.target_otm_pct)
            step = self._get_strike_step(underlying_price)
            new_strike = math.floor(raw_strike / step) * step
        else:
            # CALL: new_strike = S × (1 + target_otm_pct)
            raw_strike = underlying_price * (1 + self.target_otm_pct)
            step = self._get_strike_step(underlying_price)
            new_strike = math.ceil(raw_strike / step) * step

        # 如果新 Strike 与当前相同，返回 None
        if current_strike and abs(new_strike - current_strike) < 0.01:
            return None

        return new_strike

    def _find_nearest_strike(
        self,
        target_strike: float,
        available_strikes: list[float],
        option_type: Optional[str],
    ) -> float:
        """从可用行权价中选择最接近目标的

        对于 PUT，选择 <= target 的最大值（更保守）
        对于 CALL，选择 >= target 的最小值（更保守）

        Args:
            target_strike: 目标行权价
            available_strikes: 可用的行权价列表
            option_type: 期权类型

        Returns:
            最接近的有效行权价
        """
        if not available_strikes:
            return target_strike

        sorted_strikes = sorted(available_strikes)

        if option_type == "put":
            # PUT: 选择 <= target 的最大值（更 OTM，更保守）
            valid = [s for s in sorted_strikes if s <= target_strike]
            if valid:
                return max(valid)
            # 如果没有更低的，选择最接近的
            return min(sorted_strikes, key=lambda s: abs(s - target_strike))
        else:
            # CALL: 选择 >= target 的最小值（更 OTM，更保守）
            valid = [s for s in sorted_strikes if s >= target_strike]
            if valid:
                return min(valid)
            # 如果没有更高的，选择最接近的
            return min(sorted_strikes, key=lambda s: abs(s - target_strike))

    def _get_strike_step(self, price: float) -> float:
        """根据标的价格获取 Strike 取整步长

        Args:
            price: 标的价格

        Returns:
            Strike 取整步长
        """
        if price < 50:
            return self.STRIKE_STEP_SMALL
        elif price < 100:
            return self.STRIKE_STEP_MEDIUM
        else:
            return self.STRIKE_STEP_LARGE

    def _find_nearest_expiry(
        self,
        target_dte: int,
        available_expiries: list[str],
        today: date,
    ) -> str:
        """从可用到期日中选择最接近目标 DTE 的

        Args:
            target_dte: 目标 DTE
            available_expiries: 可用的到期日列表（YYYY-MM-DD 格式）
            today: 今天日期

        Returns:
            最接近目标 DTE 的到期日
        """
        best_expiry = None
        best_diff = float("inf")

        for expiry_str in available_expiries:
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            dte = (expiry_date - today).days
            # 只考虑未来的到期日
            if dte < self.min_dte:
                continue

            diff = abs(dte - target_dte)
            if diff < best_diff:
                best_diff = diff
                best_expiry = expiry_str

        # 如果没有找到合适的到期日，返回计算的理论到期日
        if best_expiry is None:
            return self._calc_target_expiry(target_dte, today)

        return best_expiry

    def _calc_target_expiry(self, target_dte: int, today: date) -> str:
        """计算理论目标到期日

        Args:
            target_dte: 目标 DTE
            today: 今天日期

        Returns:
            目标到期日（YYYY-MM-DD 格式）
        """
        target_date = today + timedelta(days=target_dte)
        return target_date.strftime("%Y-%m-%d")

    def _calc_dte(self, expiry: Optional[str], today: date) -> int:
        """从到期日计算 DTE

        Args:
            expiry: 到期日（支持 YYYY-MM-DD 或 YYYYMMDD 格式）
            today: 今天日期

        Returns:
            DTE，如果无法解析返回 0
        """
        if not expiry:
            return 0

        try:
            # 尝试 YYYY-MM-DD 格式
            if "-" in expiry:
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            else:
                # YYYYMMDD 格式
                expiry_date = datetime.strptime(expiry, "%Y%m%d").date()

            return (expiry_date - today).days
        except ValueError:
            return 0

    def _build_reason(
        self,
        alert: Alert,
        current_dte: int,
        target_dte: int,
        current_strike: Optional[float],
        target_strike: Optional[float],
        from_chain: bool = False,
    ) -> str:
        """构建展期原因说明

        Args:
            alert: 触发的告警
            current_dte: 当前 DTE
            target_dte: 目标 DTE
            current_strike: 当前 Strike
            target_strike: 目标 Strike
            from_chain: 是否来自真实期权链数据

        Returns:
            原因说明
        """
        parts = [f"触发: {alert.alert_type.value}"]

        # DTE 变化
        if target_dte != current_dte:
            parts.append(f"DTE: {current_dte} → {target_dte}")

        # Strike 变化
        if target_strike is not None and current_strike is not None:
            parts.append(f"Strike: {current_strike:.0f} → {target_strike:.0f}")
        elif target_strike is None:
            parts.append("Strike: 保持不变")

        # 标记数据来源
        if from_chain:
            parts.append("[期权链]")

        return " | ".join(parts)
