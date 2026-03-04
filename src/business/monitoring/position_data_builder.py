"""PositionDataBuilder - 统一的 PositionData 转换辅助工具

将回测 (PositionManager) 和实盘 (MonitoringDataBridge) 两条转换路径中
重复的计算逻辑提取为共享静态方法。

共享逻辑包括：
- moneyness / OTM% 计算
- unrealized_pnl_pct 计算
- 策略指标批量填充 (tgr, prei, sas, roc 等)
- 策略对象创建 (复用 engine/strategy 工厂)
"""

import logging
import math
from typing import Optional

from src.business.monitoring.models import PositionData, StrategyMetricsData
from src.engine.models.enums import StrategyType

logger = logging.getLogger(__name__)


class PositionDataBuilder:
    """共享的 PositionData 转换辅助方法（全部为静态方法）"""

    @staticmethod
    def calc_moneyness(underlying_price: float, strike: float) -> float:
        """计算 moneyness: (S - K) / K

        Args:
            underlying_price: 标的价格
            strike: 行权价

        Returns:
            moneyness 值，正值表示 ITM(Put OTM)，负值表示 OTM(Put ITM)
        """
        if strike <= 0:
            return 0.0
        return (underlying_price - strike) / strike

    @staticmethod
    def calc_otm_pct(
        underlying_price: float, strike: float, option_type: str
    ) -> float:
        """计算 OTM 百分比

        Put: OTM% = (S - K) / S  (正值表示 OTM)
        Call: OTM% = (K - S) / S  (正值表示 OTM)

        Args:
            underlying_price: 标的价格
            strike: 行权价
            option_type: "put" 或 "call"

        Returns:
            OTM 百分比，正值表示 OTM，负值表示 ITM
        """
        if underlying_price <= 0:
            return 0.0
        if option_type == "put":
            return (underlying_price - strike) / underlying_price
        else:  # call
            return (strike - underlying_price) / underlying_price

    @staticmethod
    def calc_unrealized_pnl_pct(
        unrealized_pnl: float,
        quantity: float,
        entry_price: float,
        lot_size: int,
    ) -> float:
        """计算未实现盈亏百分比

        Args:
            unrealized_pnl: 未实现盈亏金额
            quantity: 持仓数量
            entry_price: 入场价格
            lot_size: 合约乘数

        Returns:
            未实现盈亏百分比
        """
        entry_value = abs(quantity * entry_price * lot_size)
        if entry_value <= 0:
            return 0.0
        return unrealized_pnl / entry_value

    @staticmethod
    def build_option_symbol(
        underlying: str,
        expiration_str: str,
        strike: float,
        option_type: str,
    ) -> str:
        """构建期权标识符

        Args:
            underlying: 标的代码
            expiration_str: 到期日字符串 (YYYYMMDD)
            strike: 行权价
            option_type: "put" 或 "call"

        Returns:
            期权标识符，如 "AAPL 20260101 450.0P"
        """
        type_char = option_type[0].upper() if option_type else "?"
        return f"{underlying} {expiration_str} {strike:.1f}{type_char}"

    @staticmethod
    def populate_strategy_metrics(
        pos_data: PositionData,
        strategy_obj,
    ) -> None:
        """统一填充策略指标到 PositionData

        从 strategy.calc_metrics() 结果中填充所有策略指标字段，
        包括 tgr, prei, sas, roc, expected_roc, sharpe, kelly 等。

        同时计算 gamma_risk_pct = |Gamma| / Margin。

        Args:
            pos_data: 要填充的 PositionData 对象
            strategy_obj: 策略实例（需要有 calc_metrics() 方法）
        """
        try:
            metrics = strategy_obj.calc_metrics()
            pos_data.prei = metrics.prei
            pos_data.tgr = metrics.tgr
            pos_data.sas = metrics.sas
            pos_data.roc = metrics.roc
            pos_data.expected_roc = metrics.expected_roc
            pos_data.sharpe = metrics.sharpe_ratio
            pos_data.kelly = metrics.kelly_fraction
            pos_data.win_probability = metrics.win_probability
            pos_data.expected_return = metrics.expected_return
            pos_data.max_profit = metrics.max_profit
            pos_data.max_loss = metrics.max_loss
            pos_data.breakeven = metrics.breakeven
            pos_data.return_std = metrics.return_std

            # gamma_risk_pct: |Gamma| / Margin
            if (
                pos_data.margin
                and pos_data.margin > 0
                and pos_data.gamma is not None
            ):
                pos_data.gamma_risk_pct = abs(pos_data.gamma) / pos_data.margin
        except Exception as e:
            logger.debug(
                f"Failed to populate strategy metrics for {pos_data.symbol}: {e}"
            )

    @staticmethod
    def create_strategy_object(
        strategy_type: StrategyType,
        underlying_price: float,
        strike: float,
        premium: float,
        iv: Optional[float],
        dte: int,
        delta: Optional[float] = None,
        gamma: Optional[float] = None,
        theta: Optional[float] = None,
        vega: Optional[float] = None,
        risk_free_rate: float = 0.03,
    ):
        """统一创建策略对象

        根据 strategy_type 创建对应的策略实例，用于计算指标。

        Args:
            strategy_type: 策略类型枚举
            underlying_price: 标的价格
            strike: 行权价
            premium: 权利金 (取绝对值)
            iv: 隐含波动率
            dte: 到期天数
            delta/gamma/theta/vega: Greeks
            risk_free_rate: 无风险利率

        Returns:
            策略对象实例，若不支持的类型则返回 None
        """
        time_to_expiry = max(0.01, dte / 365.0)
        abs_premium = abs(premium)
        fallback_iv = iv or 0.2

        if strategy_type == StrategyType.SHORT_PUT:
            from src.engine.strategy.short_put import ShortPutStrategy

            return ShortPutStrategy(
                spot_price=underlying_price,
                strike_price=strike,
                premium=abs_premium,
                volatility=fallback_iv,
                time_to_expiry=time_to_expiry,
                risk_free_rate=risk_free_rate,
                dte=dte,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            )
        elif strategy_type in (StrategyType.NAKED_CALL, StrategyType.COVERED_CALL):
            from src.engine.strategy.short_call import ShortCallStrategy

            return ShortCallStrategy(
                spot_price=underlying_price,
                strike_price=strike,
                premium=abs_premium,
                volatility=fallback_iv,
                time_to_expiry=time_to_expiry,
                risk_free_rate=risk_free_rate,
                dte=dte,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            )

        return None

    @staticmethod
    def calc_iv_hv_ratio(iv: Optional[float], hv: Optional[float]) -> Optional[float]:
        """计算 IV/HV 比率

        Args:
            iv: 隐含波动率
            hv: 历史波动率

        Returns:
            IV/HV 比率，若数据不足返回 None
        """
        if iv is not None and hv is not None and hv > 0:
            return iv / hv
        return None
