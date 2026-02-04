"""
测试 SuggestionGenerator 的完整覆盖

遍历文档中所有层级的 Monitor 指标，验证生成的 PositionSuggestion 是否符合预期。

层级:
- Capital 级 (4 个指标)
- Portfolio 级 (7 个指标)
- Position 级 (多个指标)
"""

import pytest
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from src.business.monitoring.suggestions import (
    SuggestionGenerator,
    ActionType,
    UrgencyLevel,
    PORTFOLIO_ALERT_POSITION_SELECTOR,
    ALERT_ACTION_MAP,
)
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    AlertType,
    MonitorResult,
    MonitorStatus,
    PositionData,
)
from src.engine.models.enums import StrategyType


# =============================================================================
# Mock Data Factory
# =============================================================================

def create_mock_position(
    position_id: str,
    symbol: str,
    **kwargs,
) -> PositionData:
    """创建模拟持仓数据"""
    defaults = {
        "asset_type": "option",
        "quantity": -1,
        "strike": 100,
        "expiry": "20250228",
        "option_type": "put",
        "underlying": symbol,
        "underlying_price": 105,
        "dte": 30,
        "delta": -0.25,
        "gamma": -0.02,
        "theta": 0.5,
        "vega": -0.8,
        "margin": 2000,
        "market_value": -500,
        "unrealized_pnl_pct": 0.10,
        "tgr": 1.2,
        "contract_multiplier": 100,
        "beta": 1.0,
        "strategy_type": StrategyType.SHORT_PUT,
    }
    defaults.update(kwargs)
    return PositionData(position_id=position_id, symbol=symbol, **defaults)


def create_mock_alert(
    alert_type: AlertType,
    level: AlertLevel,
    message: str = "",
    current_value: float = 0,
    threshold_value: float = 0,
    position_id: str | None = None,
    symbol: str | None = None,
) -> Alert:
    """创建模拟 Alert"""
    return Alert(
        alert_type=alert_type,
        level=level,
        message=message or f"{alert_type.value} {level.value}",
        current_value=current_value,
        threshold_value=threshold_value,
        position_id=position_id,
        symbol=symbol,
    )


# =============================================================================
# Test Cases
# =============================================================================

@dataclass
class TestCase:
    """测试用例"""
    name: str
    description: str
    alerts: list[Alert]
    positions: list[PositionData]
    expected_count: int  # 预期生成的建议数量
    expected_action: ActionType | None = None  # 预期的操作类型
    expected_urgency: UrgencyLevel | None = None  # 预期的紧急程度
    expected_position_ids: list[str] | None = None  # 预期选中的持仓 ID
    validator: Any = None  # 自定义验证函数


# =============================================================================
# Capital 级测试用例
# =============================================================================

CAPITAL_TEST_CASES = [
    # 1. MARGIN_UTILIZATION > 70%
    TestCase(
        name="MARGIN_UTILIZATION_RED",
        description="保证金使用率 > 70%，按 Theta/Margin 升序选择效率最低的持仓平仓",
        alerts=[
            create_mock_alert(
                AlertType.MARGIN_UTILIZATION,
                AlertLevel.RED,
                "保证金使用率 75% > 70%",
                current_value=0.75,
                threshold_value=0.70,
            )
        ],
        positions=[
            # pos1: Theta/Margin = 0.5/2000 = 0.00025 (效率最低)
            create_mock_position("pos1", "AAPL", theta=0.5, margin=2000),
            # pos2: Theta/Margin = 1.0/1000 = 0.001 (效率较高)
            create_mock_position("pos2", "GOOG", theta=1.0, margin=1000),
            # pos3: Theta/Margin = 0.3/3000 = 0.0001 (效率最低)
            create_mock_position("pos3", "MSFT", theta=0.3, margin=3000),
            create_mock_position("pos4", "AMZN", theta=1.6, margin=1500),  # 效率最高
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        expected_urgency=UrgencyLevel.IMMEDIATE,
        # 按 Theta/Margin 升序: pos3 < pos1 < pos2
        expected_position_ids=["pos3", "pos1", "pos2"],
    ),

    # 2. CASH_RATIO < 10%
    TestCase(
        name="CASH_RATIO_RED",
        description="现金留存率 < 10%，优先平仓盈利最多的持仓",
        alerts=[
            create_mock_alert(
                AlertType.CASH_RATIO,
                AlertLevel.RED,
                "现金留存率 8% < 10%",
                current_value=0.08,
                threshold_value=0.10,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", unrealized_pnl_pct=0.15),  # 15% 盈利
            create_mock_position("pos2", "GOOG", unrealized_pnl_pct=-0.10),  # 10% 亏损
            create_mock_position("pos3", "MSFT", unrealized_pnl_pct=0.25),  # 25% 盈利 (最高)
            create_mock_position("pos4", "AMZN", unrealized_pnl_pct=0.05),  # 5% 盈利
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 按 P&L% 降序，只选盈利的: pos3(25%) > pos1(15%) > pos4(5%)
        expected_position_ids=["pos3", "pos1", "pos4"],
    ),

    # 2b. CASH_RATIO < 10% 回退逻辑 (无盈利持仓)
    TestCase(
        name="CASH_RATIO_RED_FALLBACK",
        description="现金留存率 < 10%，无盈利持仓时按 DTE 升序平仓",
        alerts=[
            create_mock_alert(
                AlertType.CASH_RATIO,
                AlertLevel.RED,
                "现金留存率 8% < 10%",
                current_value=0.08,
                threshold_value=0.10,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", unrealized_pnl_pct=-0.15, dte=30),
            create_mock_position("pos2", "GOOG", unrealized_pnl_pct=-0.10, dte=7),  # 最临近
            create_mock_position("pos3", "MSFT", unrealized_pnl_pct=-0.25, dte=45),
            create_mock_position("pos4", "AMZN", unrealized_pnl_pct=-0.05, dte=14),
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 回退: 按 DTE 升序: pos2(7) < pos4(14) < pos1(30)
        expected_position_ids=["pos2", "pos4", "pos1"],
    ),

    # 3. GROSS_LEVERAGE > 4.0x
    TestCase(
        name="GROSS_LEVERAGE_RED",
        description="总名义杠杆 > 4.0x，按 Notional 降序选择敞口最大的持仓平仓",
        alerts=[
            create_mock_alert(
                AlertType.GROSS_LEVERAGE,
                AlertLevel.RED,
                "总杠杆 4.5x > 4.0x",
                current_value=4.5,
                threshold_value=4.0,
            )
        ],
        positions=[
            # Notional = strike * qty * multiplier
            create_mock_position("pos1", "AAPL", strike=180, quantity=-1),  # 18000
            create_mock_position("pos2", "GOOG", strike=150, quantity=-2),  # 30000
            create_mock_position("pos3", "MSFT", strike=400, quantity=-1),  # 40000 (最大)
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 按 Notional 降序: pos3(40000) > pos2(30000) > pos1(18000)
        expected_position_ids=["pos3", "pos2", "pos1"],
    ),

    # 4. STRESS_TEST_LOSS > 20%
    TestCase(
        name="STRESS_TEST_LOSS_RED",
        description="压力测试亏损 > 20%，按 |Gamma| × S² 降序选择 Gamma 空头最大的持仓",
        alerts=[
            create_mock_alert(
                AlertType.STRESS_TEST_LOSS,
                AlertLevel.RED,
                "压力测试亏损 25% > 20%",
                current_value=0.25,
                threshold_value=0.20,
            )
        ],
        positions=[
            # |Gamma| × S²
            # pos1: 0.02 * 100² = 200
            create_mock_position("pos1", "AAPL", gamma=-0.02, underlying_price=100),
            # pos2: 0.05 * 150² = 1125 (最大)
            create_mock_position("pos2", "GOOG", gamma=-0.05, underlying_price=150),
            # pos3: 0.03 * 120² = 432
            create_mock_position("pos3", "MSFT", gamma=-0.03, underlying_price=120),
            # pos4: Gamma 为正，不会被选中
            create_mock_position("pos4", "AMZN", gamma=0.01, underlying_price=200),
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 只选 Gamma < 0，按 |Gamma| × S² 降序: pos2 > pos3 > pos1
        expected_position_ids=["pos2", "pos3", "pos1"],
    ),
]


# =============================================================================
# Portfolio 级测试用例
# =============================================================================

PORTFOLIO_TEST_CASES = [
    # 1. DELTA_EXPOSURE (BWD% > 50%)
    TestCase(
        name="DELTA_EXPOSURE_RED",
        description="Beta 加权 Delta % > 50%，按 Delta 贡献降序选择",
        alerts=[
            create_mock_alert(
                AlertType.DELTA_EXPOSURE,
                AlertLevel.RED,
                "BWD% 60% > 50%",
                current_value=0.60,
                threshold_value=0.50,
            )
        ],
        positions=[
            # Delta贡献 = |Delta| × Beta × S
            # pos1: 0.25 * 1.0 * 100 = 25
            create_mock_position("pos1", "AAPL", delta=-0.25, beta=1.0, underlying_price=100),
            # pos2: 0.40 * 1.2 * 150 = 72 (最大)
            create_mock_position("pos2", "GOOG", delta=-0.40, beta=1.2, underlying_price=150),
            # pos3: 0.30 * 0.8 * 200 = 48
            create_mock_position("pos3", "MSFT", delta=-0.30, beta=0.8, underlying_price=200),
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 按 Delta 贡献降序: pos2 > pos3 > pos1
        expected_position_ids=["pos2", "pos3", "pos1"],
    ),

    # 2. GAMMA_EXPOSURE (Gamma% < -0.5%)
    TestCase(
        name="GAMMA_EXPOSURE_RED",
        description="Gamma % < -0.5%，按 Gamma 升序选择 Gamma 空头最大的持仓",
        alerts=[
            create_mock_alert(
                AlertType.GAMMA_EXPOSURE,
                AlertLevel.RED,
                "Gamma% -0.6% < -0.5%",
                current_value=-0.006,
                threshold_value=-0.005,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", gamma=-0.02),
            create_mock_position("pos2", "GOOG", gamma=-0.05),  # Gamma 最负
            create_mock_position("pos3", "MSFT", gamma=-0.03),
            create_mock_position("pos4", "AMZN", gamma=0.01),  # Gamma 为正，不选
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 只选 Gamma < 0，按 Gamma 升序: pos2(-0.05) < pos3(-0.03) < pos1(-0.02)
        expected_position_ids=["pos2", "pos3", "pos1"],
    ),

    # 3. VEGA_EXPOSURE (Vega% < -0.5%)
    TestCase(
        name="VEGA_EXPOSURE_RED",
        description="Vega % < -0.5%，按 Vega 升序选择 Vega 空头最大的持仓",
        alerts=[
            create_mock_alert(
                AlertType.VEGA_EXPOSURE,
                AlertLevel.RED,
                "Vega% -0.6% < -0.5%",
                current_value=-0.006,
                threshold_value=-0.005,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", vega=-0.8),
            create_mock_position("pos2", "GOOG", vega=-1.5),  # Vega 最负
            create_mock_position("pos3", "MSFT", vega=-1.0),
            create_mock_position("pos4", "AMZN", vega=0.5),  # Vega 为正，不选
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 只选 Vega < 0，按 Vega 升序: pos2(-1.5) < pos3(-1.0) < pos1(-0.8)
        expected_position_ids=["pos2", "pos3", "pos1"],
    ),

    # 4. THETA_EXPOSURE (Theta% > 0.30%)
    TestCase(
        name="THETA_EXPOSURE_RED",
        description="Theta % > 0.30%（隐含 Gamma 风险），按 Theta 降序选择",
        alerts=[
            create_mock_alert(
                AlertType.THETA_EXPOSURE,
                AlertLevel.RED,
                "Theta% 0.35% > 0.30%",
                current_value=0.0035,
                threshold_value=0.0030,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", theta=0.5),
            create_mock_position("pos2", "GOOG", theta=1.2),  # Theta 最高
            create_mock_position("pos3", "MSFT", theta=0.8),
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 按 Theta 降序: pos2(1.2) > pos3(0.8) > pos1(0.5)
        expected_position_ids=["pos2", "pos3", "pos1"],
    ),

    # 5. TGR_LOW (Portfolio TGR < 1.0)
    TestCase(
        name="TGR_LOW_RED",
        description="Portfolio TGR < 1.0，只选择 Position TGR < 0.5 的持仓",
        alerts=[
            create_mock_alert(
                AlertType.TGR_LOW,
                AlertLevel.RED,
                "Portfolio TGR 0.8 < 1.0",
                current_value=0.8,
                threshold_value=1.0,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", tgr=1.2),  # TGR > 0.5，不选
            create_mock_position("pos2", "GOOG", tgr=0.3),  # TGR 最低
            create_mock_position("pos3", "MSFT", tgr=0.4),
            create_mock_position("pos4", "AMZN", tgr=0.8),  # TGR > 0.5，不选
        ],
        expected_count=2,  # 只有 2 个持仓满足 TGR < 0.5
        expected_action=ActionType.CLOSE,
        # 只选 TGR < 0.5，按 TGR 升序: pos2(0.3) < pos3(0.4)
        expected_position_ids=["pos2", "pos3"],
    ),

    # 6. CONCENTRATION (HHI > 0.50)
    TestCase(
        name="CONCENTRATION_RED",
        description="集中度 HHI > 0.50，按市值降序选择占比最高的持仓",
        alerts=[
            create_mock_alert(
                AlertType.CONCENTRATION,
                AlertLevel.RED,
                "HHI 0.6 > 0.5",
                current_value=0.6,
                threshold_value=0.5,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", market_value=-500),
            create_mock_position("pos2", "GOOG", market_value=-2000),  # 市值最大
            create_mock_position("pos3", "MSFT", market_value=-1000),
        ],
        expected_count=3,
        expected_action=ActionType.CLOSE,
        # 按 |market_value| 降序: pos2(2000) > pos3(1000) > pos1(500)
        expected_position_ids=["pos2", "pos3", "pos1"],
    ),

    # 7. IV_HV_QUALITY (< 0.8) - 不生成订单
    TestCase(
        name="IV_HV_QUALITY_RED",
        description="IV/HV Quality < 0.8，不配置选择器，不生成可执行订单",
        alerts=[
            create_mock_alert(
                AlertType.IV_HV_QUALITY,
                AlertLevel.RED,
                "IV/HV Quality 0.7 < 0.8",
                current_value=0.7,
                threshold_value=0.8,
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL"),
            create_mock_position("pos2", "GOOG"),
        ],
        # IV_HV_QUALITY 不在 PORTFOLIO_ALERT_POSITION_SELECTOR 中
        # 会走原有逻辑，生成 portfolio 级建议（仅提醒）
        expected_count=1,  # 生成 1 个 portfolio 级建议
        expected_action=None,  # 取决于 ALERT_ACTION_MAP
    ),
]


# =============================================================================
# Position 级测试用例
# =============================================================================

POSITION_TEST_CASES = [
    # 1a. STOP_LOSS (P&L% < -100%) - SHORT_PUT 策略
    # 文档: Short Put：无条件平仓止损，不抗单
    TestCase(
        name="STOP_LOSS_RED_SHORT_PUT",
        description="止损触发，SHORT_PUT：无条件平仓止损，不抗单",
        alerts=[
            create_mock_alert(
                AlertType.STOP_LOSS,
                AlertLevel.RED,
                "P&L% -120% 触发止损",
                current_value=-1.2,
                threshold_value=-1.0,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                strategy_type=StrategyType.SHORT_PUT,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.CLOSE,
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 1b. STOP_LOSS (P&L% < -100%) - COVERED_CALL 策略
    # 文档: Covered Call：平仓 Call 腿止损
    TestCase(
        name="STOP_LOSS_RED_COVERED_CALL",
        description="止损触发，COVERED_CALL：平仓 Call 腿止损",
        alerts=[
            create_mock_alert(
                AlertType.STOP_LOSS,
                AlertLevel.RED,
                "P&L% -120% 触发止损",
                current_value=-1.2,
                threshold_value=-1.0,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                option_type="call",
                strategy_type=StrategyType.COVERED_CALL,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.CLOSE,  # 平仓 Call 腿
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 1c. STOP_LOSS (P&L% < -100%) - SHORT_STRANGLE 策略
    # 文档: Straddle：平仓亏损腿或整体止损
    TestCase(
        name="STOP_LOSS_RED_STRANGLE",
        description="止损触发，STRANGLE：平仓亏损腿或整体止损",
        alerts=[
            create_mock_alert(
                AlertType.STOP_LOSS,
                AlertLevel.RED,
                "P&L% -120% 触发止损",
                current_value=-1.2,
                threshold_value=-1.0,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                strategy_type=StrategyType.SHORT_STRANGLE,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.CLOSE,
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 2a. DTE_WARNING (DTE < 7) - SHORT_PUT 策略
    # 文档: Short Put：强制平仓或展期到下月
    TestCase(
        name="DTE_WARNING_RED_SHORT_PUT",
        description="DTE < 7 天，SHORT_PUT：强制平仓或展期到下月",
        alerts=[
            create_mock_alert(
                AlertType.DTE_WARNING,
                AlertLevel.RED,
                "DTE 5 < 7",
                current_value=5,
                threshold_value=7,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                dte=5,
                strategy_type=StrategyType.SHORT_PUT,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.ROLL,  # SHORT_PUT -> ROLL
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 2b. DTE_WARNING (DTE < 4 且亏损) - COVERED_CALL 策略
    # 新规则: DTE < 4 且 P&L ≤ 0 → 展期（统一所有策略）
    TestCase(
        name="DTE_WARNING_RED_COVERED_CALL",
        description="DTE < 4 天且亏损，COVERED_CALL：展期到下月",
        alerts=[
            create_mock_alert(
                AlertType.DTE_WARNING,
                AlertLevel.RED,
                "DTE 3 < 4 且亏损",
                current_value=3,
                threshold_value=4,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                dte=3,
                option_type="call",
                strategy_type=StrategyType.COVERED_CALL,
                unrealized_pnl_pct=-0.1,  # 亏损
            ),
        ],
        expected_count=1,
        expected_action=ActionType.ROLL,  # DTE < 4 且亏损 → ROLL
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 2c. DTE_WARNING (DTE < 4 且亏损) - SHORT_STRANGLE 策略
    # 新规则: DTE < 4 且 P&L ≤ 0 → 展期（统一所有策略）
    TestCase(
        name="DTE_WARNING_RED_STRANGLE",
        description="DTE < 4 天且亏损，STRANGLE：展期到下月",
        alerts=[
            create_mock_alert(
                AlertType.DTE_WARNING,
                AlertLevel.RED,
                "DTE 3 < 4 且亏损",
                current_value=3,
                threshold_value=4,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                dte=3,
                strategy_type=StrategyType.SHORT_STRANGLE,
                unrealized_pnl_pct=-0.2,  # 亏损
            ),
        ],
        expected_count=1,
        expected_action=ActionType.ROLL,  # DTE < 4 且亏损 → ROLL
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 3a. DELTA_CHANGE (|Delta| > 0.50) - SHORT_PUT 策略
    # 文档: Short Put：展期到更低 Strike 或平仓止损
    TestCase(
        name="DELTA_CHANGE_RED_SHORT_PUT",
        description="|Delta| > 0.50，SHORT_PUT 策略：展期到更低 Strike 或平仓止损",
        alerts=[
            create_mock_alert(
                AlertType.DELTA_CHANGE,
                AlertLevel.RED,
                "Delta -0.55 超出阈值",
                current_value=-0.55,
                threshold_value=0.50,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                delta=-0.55,
                strategy_type=StrategyType.SHORT_PUT,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.ROLL,  # SHORT_PUT -> ROLL 到更低 Strike
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 3b. DELTA_CHANGE (|Delta| > 0.50) - COVERED_CALL 策略
    # 文档: Covered Call：可接受行权（卖出正股）或展期到更高 Strike
    TestCase(
        name="DELTA_CHANGE_RED_COVERED_CALL",
        description="|Delta| > 0.50，COVERED_CALL 策略：可接受行权或展期到更高 Strike",
        alerts=[
            create_mock_alert(
                AlertType.DELTA_CHANGE,
                AlertLevel.RED,
                "Delta -0.55 超出阈值",
                current_value=-0.55,
                threshold_value=0.50,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                delta=-0.55,
                option_type="call",
                strategy_type=StrategyType.COVERED_CALL,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.ADJUST,  # COVERED_CALL -> ADJUST
        expected_urgency=UrgencyLevel.SOON,  # 紧急程度较低，可接受行权
        expected_position_ids=["pos1"],
    ),

    # 3c. DELTA_CHANGE (|Delta| > 0.50) - SHORT_STRANGLE 策略
    # 文档: Straddle：平仓 Delta 恶化的腿，保留另一腿
    TestCase(
        name="DELTA_CHANGE_RED_STRANGLE",
        description="|Delta| > 0.50，STRANGLE 策略：平仓 Delta 恶化的腿",
        alerts=[
            create_mock_alert(
                AlertType.DELTA_CHANGE,
                AlertLevel.RED,
                "Delta -0.55 超出阈值",
                current_value=-0.55,
                threshold_value=0.50,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                delta=-0.55,
                strategy_type=StrategyType.SHORT_STRANGLE,
            ),
        ],
        expected_count=1,
        expected_action=ActionType.CLOSE,  # SHORT_STRANGLE -> CLOSE 恶化腿
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 3d. DELTA_CHANGE (|Delta| > 0.50) - 无策略类型时的默认行为
    TestCase(
        name="DELTA_CHANGE_RED_NO_STRATEGY",
        description="|Delta| > 0.50，无策略类型时使用通用映射",
        alerts=[
            create_mock_alert(
                AlertType.DELTA_CHANGE,
                AlertLevel.RED,
                "Delta -0.55 超出阈值",
                current_value=-0.55,
                threshold_value=0.50,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position(
                "pos1", "AAPL",
                delta=-0.55,
                strategy_type=None,  # 无策略类型
            ),
        ],
        expected_count=1,
        expected_action=ActionType.CLOSE,  # 通用映射 DELTA_CHANGE RED -> CLOSE
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),

    # 4. PROFIT_TARGET (达到止盈)
    TestCase(
        name="PROFIT_TARGET_GREEN",
        description="达到止盈目标",
        alerts=[
            create_mock_alert(
                AlertType.PROFIT_TARGET,
                AlertLevel.GREEN,
                "盈利 60% 达到止盈目标 50%",
                current_value=0.60,
                threshold_value=0.50,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL", unrealized_pnl_pct=0.60),
        ],
        expected_count=1,
        expected_action=ActionType.TAKE_PROFIT,
        expected_urgency=UrgencyLevel.SOON,
        expected_position_ids=["pos1"],
    ),

    # 5. MONEYNESS (OTM% < 5%)
    TestCase(
        name="MONEYNESS_RED",
        description="OTM% < 5%，接近 ATM",
        alerts=[
            create_mock_alert(
                AlertType.MONEYNESS,
                AlertLevel.RED,
                "OTM% 3% < 5%",
                current_value=0.03,
                threshold_value=0.05,
                position_id="pos1",
                symbol="AAPL",
            )
        ],
        positions=[
            create_mock_position("pos1", "AAPL"),
        ],
        expected_count=1,
        expected_action=ActionType.ROLL,
        expected_urgency=UrgencyLevel.IMMEDIATE,
        expected_position_ids=["pos1"],
    ),
]


# =============================================================================
# Test Runner
# =============================================================================

def run_test_case(case: TestCase, generator: SuggestionGenerator) -> dict:
    """运行单个测试用例"""
    result = MonitorResult(
        status=MonitorStatus.RED,
        alerts=case.alerts,
        positions=case.positions,
    )

    suggestions = generator.generate(result, case.positions)

    # 验证结果
    passed = True
    errors = []

    # 检查数量
    if len(suggestions) != case.expected_count:
        passed = False
        errors.append(f"Expected {case.expected_count} suggestions, got {len(suggestions)}")

    # 检查操作类型
    if case.expected_action and suggestions:
        for s in suggestions:
            if s.action != case.expected_action:
                passed = False
                errors.append(f"Expected action {case.expected_action.value}, got {s.action.value}")

    # 检查紧急程度
    if case.expected_urgency and suggestions:
        for s in suggestions:
            if s.urgency != case.expected_urgency:
                passed = False
                errors.append(f"Expected urgency {case.expected_urgency.value}, got {s.urgency.value}")

    # 检查选中的持仓 ID
    if case.expected_position_ids and suggestions:
        actual_ids = [s.position_id for s in suggestions]
        if actual_ids != case.expected_position_ids:
            passed = False
            errors.append(f"Expected position_ids {case.expected_position_ids}, got {actual_ids}")

    return {
        "name": case.name,
        "description": case.description,
        "passed": passed,
        "errors": errors,
        "suggestions": suggestions,
    }


def print_test_result(result: dict):
    """打印测试结果"""
    status = "✅ PASS" if result["passed"] else "❌ FAIL"
    print(f"\n{'='*60}")
    print(f"{status} {result['name']}")
    print(f"{'='*60}")
    print(f"Description: {result['description']}")

    if result["errors"]:
        print(f"\nErrors:")
        for err in result["errors"]:
            print(f"  - {err}")

    print(f"\nGenerated {len(result['suggestions'])} suggestions:")
    for s in result["suggestions"]:
        print(f"  - {s.position_id}: {s.action.value} | {s.symbol}")
        print(f"    urgency: {s.urgency.value}")
        print(f"    reason: {s.reason[:60]}...")
        if s.details:
            print(f"    details: {s.details}")


def run_all_tests():
    """运行所有测试"""
    generator = SuggestionGenerator()

    all_cases = [
        ("Capital 级", CAPITAL_TEST_CASES),
        ("Portfolio 级", PORTFOLIO_TEST_CASES),
        ("Position 级", POSITION_TEST_CASES),
    ]

    total = 0
    passed = 0
    failed = 0

    for category, cases in all_cases:
        print(f"\n\n{'#'*60}")
        print(f"# {category} 测试")
        print(f"{'#'*60}")

        for case in cases:
            result = run_test_case(case, generator)
            print_test_result(result)

            total += 1
            if result["passed"]:
                passed += 1
            else:
                failed += 1

    # 打印总结
    print(f"\n\n{'='*60}")
    print(f"测试总结")
    print(f"{'='*60}")
    print(f"Total: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Pass Rate: {passed/total*100:.1f}%")

    return failed == 0


# =============================================================================
# Pytest Tests
# =============================================================================

class TestCapitalLevel:
    """Capital 级测试"""

    @pytest.fixture
    def generator(self):
        return SuggestionGenerator()

    @pytest.mark.parametrize("case", CAPITAL_TEST_CASES, ids=[c.name for c in CAPITAL_TEST_CASES])
    def test_capital_alert(self, generator, case):
        result = run_test_case(case, generator)
        assert result["passed"], f"Failed: {result['errors']}"


class TestPortfolioLevel:
    """Portfolio 级测试"""

    @pytest.fixture
    def generator(self):
        return SuggestionGenerator()

    @pytest.mark.parametrize("case", PORTFOLIO_TEST_CASES, ids=[c.name for c in PORTFOLIO_TEST_CASES])
    def test_portfolio_alert(self, generator, case):
        result = run_test_case(case, generator)
        assert result["passed"], f"Failed: {result['errors']}"


class TestPositionLevel:
    """Position 级测试"""

    @pytest.fixture
    def generator(self):
        return SuggestionGenerator()

    @pytest.mark.parametrize("case", POSITION_TEST_CASES, ids=[c.name for c in POSITION_TEST_CASES])
    def test_position_alert(self, generator, case):
        result = run_test_case(case, generator)
        assert result["passed"], f"Failed: {result['errors']}"


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
