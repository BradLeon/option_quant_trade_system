"""
RollTargetCalculator 单元测试

测试展期目标参数计算逻辑：
- DTE 选择规则
- Strike 调整规则
- 到期日选择
"""

from datetime import date, datetime

import pytest

from src.business.monitoring.models import Alert, AlertLevel, AlertType, PositionData
from src.business.monitoring.roll_calculator import RollTarget, RollTargetCalculator
from src.engine.models.enums import StrategyType


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def calculator() -> RollTargetCalculator:
    """创建默认计算器"""
    return RollTargetCalculator()


@pytest.fixture
def today() -> date:
    """固定今天日期用于测试"""
    return date(2025, 2, 1)


def create_position(
    position_id: str = "TEST-001",
    symbol: str = "NVDA 250215P00100000",
    option_type: str = "put",
    strike: float = 100.0,
    expiry: str = "20250215",
    dte: int = 14,
    underlying_price: float = 110.0,
    strategy_type: StrategyType = StrategyType.SHORT_PUT,
) -> PositionData:
    """创建测试用持仓数据"""
    return PositionData(
        position_id=position_id,
        symbol=symbol,
        asset_type="option",
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        dte=dte,
        underlying="NVDA",
        underlying_price=underlying_price,
        strategy_type=strategy_type,
        quantity=-2,
        current_price=1.50,
        delta=-0.25,
        gamma=-0.02,
        theta=0.05,
        vega=-0.10,
    )


def create_alert(
    alert_type: AlertType,
    level: AlertLevel = AlertLevel.RED,
    symbol: str = "NVDA 250215P00100000",
    position_id: str = "TEST-001",
) -> Alert:
    """创建测试用告警"""
    return Alert(
        alert_type=alert_type,
        level=level,
        message=f"Test alert: {alert_type.value}",
        symbol=symbol,
        position_id=position_id,
    )


# =============================================================================
# DTE 选择测试
# =============================================================================


class TestDTESelection:
    """测试 DTE 选择规则"""

    def test_dte_warning_triggers_ideal_dte(
        self, calculator: RollTargetCalculator, today: date
    ):
        """DTE < 7 触发：应选择理想 DTE (35)"""
        position = create_position(dte=5, expiry="20250206")
        alert = create_alert(AlertType.DTE_WARNING)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 35
        assert "DTE: 5 → 35" in result.reason

    def test_tgr_low_triggers_ideal_dte(
        self, calculator: RollTargetCalculator, today: date
    ):
        """TGR < 1.0 触发：应选择理想 DTE (35)"""
        position = create_position(dte=15, expiry="20250216")
        alert = create_alert(AlertType.TGR_LOW)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 35

    def test_position_tgr_triggers_ideal_dte(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Position TGR 触发：应选择理想 DTE (35)"""
        position = create_position(dte=15, expiry="20250216")
        alert = create_alert(AlertType.POSITION_TGR)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 35

    def test_gamma_near_expiry_triggers_ideal_dte(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Gamma Near Expiry 触发：应选择理想 DTE (35)"""
        position = create_position(dte=7, expiry="20250208")
        alert = create_alert(AlertType.GAMMA_NEAR_EXPIRY)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 35

    def test_delta_change_keeps_current_dte(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Delta 变化触发：应保持接近当前 DTE"""
        position = create_position(dte=30, expiry="20250303")
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 30 在 [25, 45] 范围内，保持不变
        assert result.suggested_dte == 30

    def test_otm_pct_keeps_current_dte(
        self, calculator: RollTargetCalculator, today: date
    ):
        """OTM% 触发：应保持接近当前 DTE"""
        position = create_position(dte=40, expiry="20250313")
        alert = create_alert(AlertType.OTM_PCT)

        result = calculator.calculate(position, alert, today=today)

        # 40 在 [25, 45] 范围内，保持不变
        assert result.suggested_dte == 40

    def test_dte_below_min_clamps_to_min(
        self, calculator: RollTargetCalculator, today: date
    ):
        """当前 DTE 低于最小值：应限制为最小值"""
        position = create_position(dte=10, expiry="20250211")
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 10 < 25，应限制为 25
        assert result.suggested_dte == 25

    def test_dte_above_max_clamps_to_max(
        self, calculator: RollTargetCalculator, today: date
    ):
        """当前 DTE 高于最大值：应限制为最大值"""
        position = create_position(dte=60, expiry="20250402")
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 60 > 45，应限制为 45
        assert result.suggested_dte == 45


# =============================================================================
# Strike 调整测试
# =============================================================================


class TestStrikeAdjustment:
    """测试 Strike 调整规则"""

    def test_dte_warning_no_strike_change(
        self, calculator: RollTargetCalculator, today: date
    ):
        """DTE 触发：不调整 Strike"""
        position = create_position(
            dte=5,
            strike=100.0,
            underlying_price=110.0,
        )
        alert = create_alert(AlertType.DTE_WARNING)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_strike is None
        assert "Strike: 保持不变" in result.reason

    def test_tgr_low_no_strike_change(
        self, calculator: RollTargetCalculator, today: date
    ):
        """TGR 触发：不调整 Strike"""
        position = create_position(
            dte=15,
            strike=100.0,
            underlying_price=110.0,
        )
        alert = create_alert(AlertType.TGR_LOW)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_strike is None

    def test_delta_change_put_lowers_strike(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Delta 变化 (PUT)：降低 Strike 至 OTM 10%"""
        position = create_position(
            option_type="put",
            strike=100.0,
            underlying_price=110.0,  # 当前 OTM% = 9%
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 110 * (1 - 0.10) = 99 → floor(99/5)*5 = 95
        assert result.suggested_strike == 95.0
        assert "Strike: 100 → 95" in result.reason

    def test_delta_change_call_raises_strike(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Delta 变化 (CALL)：提高 Strike 至 OTM 10%"""
        position = create_position(
            option_type="call",
            strike=100.0,
            underlying_price=95.0,  # Call ITM
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 95 * (1 + 0.10) = 104.5 → ceil(104.5/5)*5 = 105
        assert result.suggested_strike == 105.0

    def test_otm_pct_put_lowers_strike(
        self, calculator: RollTargetCalculator, today: date
    ):
        """OTM% 触发 (PUT)：降低 Strike"""
        position = create_position(
            option_type="put",
            strike=105.0,
            underlying_price=108.0,  # OTM% = 2.8%
        )
        alert = create_alert(AlertType.OTM_PCT)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 108 * (1 - 0.10) = 97.2 → floor(97.2/5)*5 = 95
        assert result.suggested_strike == 95.0

    def test_moneyness_alert_adjusts_strike(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Moneyness 触发：调整 Strike"""
        position = create_position(
            option_type="put",
            strike=100.0,
            underlying_price=105.0,
        )
        alert = create_alert(AlertType.MONEYNESS)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 105 * (1 - 0.10) = 94.5 → floor(94.5/5)*5 = 90
        assert result.suggested_strike == 90.0

    def test_strike_step_for_low_price_stock(
        self, calculator: RollTargetCalculator, today: date
    ):
        """低价股票 Strike 步长为 1"""
        position = create_position(
            option_type="put",
            strike=25.0,
            underlying_price=30.0,  # 低价股
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 30 * 0.90 = 27 → floor(27/1)*1 = 27
        assert result.suggested_strike == 27.0

    def test_strike_step_for_medium_price_stock(
        self, calculator: RollTargetCalculator, today: date
    ):
        """中价股票 Strike 步长为 2.5"""
        position = create_position(
            option_type="put",
            strike=70.0,
            underlying_price=75.0,  # 中价股
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 75 * 0.90 = 67.5 → floor(67.5/2.5)*2.5 = 67.5
        assert result.suggested_strike == 67.5

    def test_no_strike_change_if_same(
        self, calculator: RollTargetCalculator, today: date
    ):
        """如果计算的新 Strike 与当前相同，返回 None"""
        position = create_position(
            option_type="put",
            strike=90.0,  # 已经是 OTM 10%
            underlying_price=100.0,
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 目标: 100 * 0.90 = 90 → 与当前相同
        assert result.suggested_strike is None


# =============================================================================
# 到期日选择测试
# =============================================================================


class TestExpirySelection:
    """测试到期日选择"""

    def test_select_from_available_expiries(
        self, calculator: RollTargetCalculator, today: date
    ):
        """从可用到期日中选择最接近目标 DTE 的"""
        position = create_position(dte=5)
        alert = create_alert(AlertType.DTE_WARNING)

        available = ["2025-02-21", "2025-03-07", "2025-03-21", "2025-04-18"]

        result = calculator.calculate(
            position, alert, available_expiries=available, today=today
        )

        # 目标 DTE = 35，2025-03-07 距离 2025-02-01 是 34 天，最接近
        assert result.suggested_expiry == "2025-03-07"

    def test_skip_expired_dates(
        self, calculator: RollTargetCalculator, today: date
    ):
        """跳过已过期或 DTE < min_dte 的日期"""
        position = create_position(dte=5)
        alert = create_alert(AlertType.DTE_WARNING)

        available = ["2025-02-05", "2025-02-15", "2025-03-07"]  # 前两个 DTE 太短

        result = calculator.calculate(
            position, alert, available_expiries=available, today=today
        )

        # 只有 2025-03-07 满足 DTE >= 25
        assert result.suggested_expiry == "2025-03-07"

    def test_fallback_to_calculated_expiry(
        self, calculator: RollTargetCalculator, today: date
    ):
        """无可用到期日时计算理论到期日"""
        position = create_position(dte=5)
        alert = create_alert(AlertType.DTE_WARNING)

        result = calculator.calculate(position, alert, today=today)

        # 理论到期日 = today + 35 = 2025-03-08
        assert result.suggested_expiry == "2025-03-08"


# =============================================================================
# 综合测试
# =============================================================================


class TestIntegration:
    """综合测试"""

    def test_dte_trigger_full_flow(
        self, calculator: RollTargetCalculator, today: date
    ):
        """DTE < 7 完整流程测试"""
        position = create_position(
            dte=5,
            expiry="20250206",
            strike=100.0,
            underlying_price=110.0,
        )
        alert = create_alert(AlertType.DTE_WARNING)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 35
        assert result.suggested_expiry == "2025-03-08"  # today + 35
        assert result.suggested_strike is None  # DTE 触发不调整 Strike
        assert result.roll_credit is None  # 暂不计算
        assert "dte_warning" in result.reason

    def test_delta_trigger_full_flow(
        self, calculator: RollTargetCalculator, today: date
    ):
        """Delta > 0.50 完整流程测试"""
        position = create_position(
            dte=30,
            expiry="20250303",
            strike=100.0,
            underlying_price=105.0,
            option_type="put",
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 30  # 保持当前 DTE
        assert result.suggested_expiry == "2025-03-03"  # today + 30
        assert result.suggested_strike == 90.0  # 105 * 0.90 = 94.5 → 90
        assert "delta_change" in result.reason
        assert "Strike: 100 → 90" in result.reason

    def test_custom_config(self, today: date):
        """自定义配置测试"""
        calculator = RollTargetCalculator(
            min_dte=20,
            max_dte=60,
            ideal_dte=40,
            target_otm_pct=0.15,
        )

        position = create_position(dte=5)
        alert = create_alert(AlertType.DTE_WARNING)

        result = calculator.calculate(position, alert, today=today)

        assert result.suggested_dte == 40  # 自定义 ideal_dte


# =============================================================================
# 边界条件测试
# =============================================================================


class TestAvailableStrikes:
    """测试从真实期权链选择 Strike"""

    def test_select_nearest_strike_for_put(
        self, calculator: RollTargetCalculator, today: date
    ):
        """PUT: 从可用 strikes 中选择 <= 目标的最大值"""
        position = create_position(
            option_type="put",
            strike=100.0,
            underlying_price=110.0,  # 目标 strike = 110 * 0.9 = 99
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        # 可用的 strikes 不包含 99，但有 95 和 100
        available_strikes = [85.0, 90.0, 95.0, 100.0, 105.0, 110.0]

        result = calculator.calculate(
            position, alert,
            available_strikes=available_strikes,
            today=today
        )

        # PUT 应选择 <= 99 的最大值 = 95
        assert result.suggested_strike == 95.0

    def test_select_nearest_strike_for_call(
        self, calculator: RollTargetCalculator, today: date
    ):
        """CALL: 从可用 strikes 中选择 >= 目标的最小值"""
        position = create_position(
            option_type="call",
            strike=100.0,
            underlying_price=95.0,  # 目标 strike = 95 * 1.1 = 104.5
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        # 可用的 strikes 不包含 104.5，但有 105
        available_strikes = [90.0, 95.0, 100.0, 105.0, 110.0, 115.0]

        result = calculator.calculate(
            position, alert,
            available_strikes=available_strikes,
            today=today
        )

        # CALL 应选择 >= 104.5 的最小值 = 105
        assert result.suggested_strike == 105.0

    def test_fallback_to_nearest_if_no_valid_strike(
        self, calculator: RollTargetCalculator, today: date
    ):
        """如果没有符合方向的 strike，选择最接近的"""
        position = create_position(
            option_type="put",
            strike=50.0,
            underlying_price=55.0,  # 目标 strike = 55 * 0.9 = 49.5
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        # 可用的 strikes 都 > 49.5
        available_strikes = [50.0, 55.0, 60.0]

        result = calculator.calculate(
            position, alert,
            available_strikes=available_strikes,
            today=today
        )

        # 应选择最接近 49.5 的 = 50
        assert result.suggested_strike == 50.0

    def test_with_both_expiries_and_strikes(
        self, calculator: RollTargetCalculator, today: date
    ):
        """同时提供 expiries 和 strikes"""
        position = create_position(
            dte=5,
            option_type="put",
            strike=100.0,
            underlying_price=100.0,  # 只是 DTE 触发，不调整 strike
        )
        alert = create_alert(AlertType.DTE_WARNING)

        available_expiries = ["2025-02-28", "2025-03-07", "2025-03-14"]
        available_strikes = [85.0, 90.0, 95.0, 100.0, 105.0]

        result = calculator.calculate(
            position, alert,
            available_expiries=available_expiries,
            available_strikes=available_strikes,
            today=today
        )

        # DTE 触发不调整 strike
        assert result.suggested_strike is None
        # 应从可用日期中选择最接近 35 天的
        assert result.suggested_expiry in available_expiries
        assert "[期权链]" in result.reason


class TestEdgeCases:
    """边界条件测试"""

    def test_missing_underlying_price(
        self, calculator: RollTargetCalculator, today: date
    ):
        """缺少标的价格时不调整 Strike"""
        position = create_position(
            underlying_price=None,
            strike=100.0,
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 缺少必要数据，不调整 Strike
        assert result.suggested_strike is None

    def test_missing_option_type(
        self, calculator: RollTargetCalculator, today: date
    ):
        """缺少期权类型时不调整 Strike"""
        position = create_position(
            option_type=None,
            strike=100.0,
            underlying_price=110.0,
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 缺少必要数据，不调整 Strike
        assert result.suggested_strike is None

    def test_missing_dte_calculates_from_expiry(
        self, calculator: RollTargetCalculator, today: date
    ):
        """缺少 DTE 时从 expiry 计算"""
        position = create_position(
            dte=None,
            expiry="20250215",  # 2025-02-15，距离 2025-02-01 是 14 天
        )
        alert = create_alert(AlertType.DELTA_CHANGE)

        result = calculator.calculate(position, alert, today=today)

        # 14 天应该被限制到 min_dte = 25
        assert result.suggested_dte == 25

    def test_invalid_expiry_format(
        self, calculator: RollTargetCalculator, today: date
    ):
        """无效的 expiry 格式"""
        position = create_position(
            dte=None,
            expiry="invalid",
        )
        alert = create_alert(AlertType.DTE_WARNING)

        result = calculator.calculate(position, alert, today=today)

        # 无法解析 expiry，current_dte = 0，DTE_WARNING 触发 ideal_dte
        assert result.suggested_dte == 35


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
