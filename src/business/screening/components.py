"""
Screening Components - 可复用的筛选检查组件

提供 Protocol 定义和从现有 Filter 中提取的可复用组件。
策略可从此组件库中挑选组件，组装到 ComposableScreeningPipeline 中。

三层组件:
- MarketCheck: 市场环境检查
- UnderlyingCheck: 标的检查
- ContractCheck: 合约检查

使用示例:
    from src.business.screening.components import VIXRangeCheck, IVRankCheck, DTERangeCheck

    pipeline = ComposableScreeningPipeline(
        market_checks=[VIXRangeCheck(vix_range=(12, 28))],
        underlying_checks=[IVRankCheck(min_iv_rank=30)],
        contract_checks=[DTERangeCheck(dte_range=(21, 45)), DeltaRangeCheck(delta_range=(0.15, 0.30))],
        data_provider=provider,
    )
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol, runtime_checkable

from src.business.screening.models import ContractOpportunity

logger = logging.getLogger(__name__)


# ==========================
# 协议定义
# ==========================

@runtime_checkable
class MarketCheck(Protocol):
    """市场环境检查协议

    返回 (passed, reason):
    - passed=True: 检查通过
    - passed=False: 检查未通过，reason 说明原因
    """

    def check(self, market_type: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        ...


@runtime_checkable
class UnderlyingCheck(Protocol):
    """标的检查协议

    返回 (passed, reason):
    - passed=True: 检查通过
    - passed=False: 检查未通过，reason 说明原因
    """

    def check(self, symbol: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        ...


@runtime_checkable
class ContractCheck(Protocol):
    """合约检查协议

    返回 (passed, reason):
    - passed=True: 检查通过
    - passed=False: 检查未通过，reason 说明原因
    """

    def check(self, opportunity: ContractOpportunity) -> tuple[bool, str]:
        ...


# ==========================
# 市场级检查组件 (MarketCheck)
# ==========================

@dataclass
class VIXRangeCheck:
    """VIX 区间检查

    检查当前 VIX 是否在指定范围内。
    卖方策略通常要求 VIX 在 12-28 之间（权利金充足但不至于恐慌）。

    Args:
        vix_range: (下限, 上限) 元组
        vix_symbol: VIX 符号，默认 "^VIX"
    """
    vix_range: tuple[float, float] = (12.0, 28.0)
    vix_symbol: str = "^VIX"

    def check(self, market_type: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            ref_date = _get_reference_date(data_provider)
            start_date = ref_date - timedelta(days=5)

            macro_data = data_provider.get_macro_data(self.vix_symbol, start_date, ref_date)
            if not macro_data:
                return True, "VIX 数据不可用，默认通过"

            current_vix = macro_data[-1].close
            if current_vix is None:
                return True, "VIX 值为空，默认通过"

            vix_low, vix_high = self.vix_range
            if vix_low <= current_vix <= vix_high:
                return True, f"VIX={current_vix:.1f} 在范围 [{vix_low}, {vix_high}] 内"
            elif current_vix < vix_low:
                return False, f"VIX={current_vix:.1f} 偏低（<{vix_low}），权利金不足"
            else:
                return False, f"VIX={current_vix:.1f} 过高（>{vix_high}），风险过大"
        except Exception as e:
            logger.warning(f"VIXRangeCheck 失败: {e}")
            return True, f"VIX 检查异常: {e}，默认通过"


@dataclass
class TermStructureCheck:
    """VIX 期限结构检查

    检查 VIX/VIX3M 比率。Backwardation（比率 >= threshold）表示短期恐慌。

    Args:
        threshold: Backwardation 阈值，默认 1.0
        vix_symbol: VIX 符号
        vix3m_symbol: VIX3M 符号
    """
    threshold: float = 1.0
    vix_symbol: str = "^VIX"
    vix3m_symbol: str = "^VIX3M"

    def check(self, market_type: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            from src.engine.account.sentiment import calc_term_structure

            ref_date = _get_reference_date(data_provider)
            start_date = ref_date - timedelta(days=5)

            vix_data = data_provider.get_macro_data(self.vix_symbol, start_date, ref_date)
            vix3m_data = data_provider.get_macro_data(self.vix3m_symbol, start_date, ref_date)

            if not vix_data or not vix3m_data:
                return True, "期限结构数据不可用，默认通过"

            vix_value = vix_data[-1].close
            vix3m_value = vix3m_data[-1].close

            if vix_value is None or vix3m_value is None or vix3m_value == 0:
                return True, "期限结构数据不完整，默认通过"

            ts_result = calc_term_structure(vix_value, vix3m_value)
            if ts_result is None:
                return True, "期限结构计算失败，默认通过"

            if ts_result.ratio >= self.threshold:
                return False, (
                    f"期限结构异常: VIX/VIX3M={ts_result.ratio:.2f} "
                    f"(>={self.threshold}), 短期恐慌"
                )
            return True, f"期限结构正常: VIX/VIX3M={ts_result.ratio:.2f}"

        except Exception as e:
            logger.warning(f"TermStructureCheck 失败: {e}")
            return True, f"期限结构检查异常: {e}，默认通过"


@dataclass
class TrendCheck:
    """大盘趋势检查

    检查指数 SMA 趋势是否满足要求。

    Args:
        indices: 指数列表 [(symbol, weight), ...]
        required_trend: 要求的最低趋势，如 "bullish_or_neutral"
    """
    indices: list[tuple[str, float]] = None
    required_trend: str = "bullish_or_neutral"

    def __post_init__(self):
        if self.indices is None:
            self.indices = [("SPY", 0.6), ("QQQ", 0.4)]

    def check(self, market_type: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            from src.engine.account.sentiment import calc_sma, calc_spy_trend
            from src.engine.models.enums import TrendSignal
            from src.data.models.stock import KlineType
            from src.business.screening.models import TrendStatus

            ref_date = _get_reference_date(data_provider)
            start_date = ref_date - timedelta(days=300)

            weighted_scores = []
            for symbol, weight in self.indices:
                try:
                    klines = data_provider.get_history_kline(symbol, KlineType.DAY, start_date, ref_date)
                    if not klines or len(klines) < 50:
                        continue

                    closes = [k.close for k in klines]
                    current_price = closes[-1]
                    sma200 = calc_sma(closes, 200) if len(closes) >= 200 else None
                    sma20 = calc_sma(closes, 20)

                    trend_signal = calc_spy_trend(closes)
                    if trend_signal == TrendSignal.BULLISH:
                        score = 2.0 if (sma200 and current_price > sma200 and sma20 and sma20 > sma200) else 1.0
                    elif trend_signal == TrendSignal.BEARISH:
                        score = -2.0 if (sma200 and current_price < sma200 and sma20 and sma20 < sma200) else -1.0
                    else:
                        if sma200 and current_price > sma200:
                            score = 0.3
                        elif sma200 and current_price < sma200:
                            score = -0.3
                        else:
                            score = 0.0
                    weighted_scores.append((score, weight))
                except Exception as e:
                    logger.warning(f"TrendCheck: {symbol} 失败: {e}")
                    continue

            if not weighted_scores:
                return True, "趋势数据不可用，默认通过"

            total_weight = sum(w for _, w in weighted_scores)
            avg_score = sum(s * w for s, w in weighted_scores) / total_weight if total_weight > 0 else 0.0

            if avg_score >= 1.5:
                trend = "strong_bullish"
            elif avg_score >= 0.5:
                trend = "bullish"
            elif avg_score <= -1.5:
                trend = "strong_bearish"
            elif avg_score <= -0.5:
                trend = "bearish"
            else:
                trend = "neutral"

            # 判断是否满足要求
            if self.required_trend == "bullish_or_neutral":
                if trend in ("strong_bearish", "bearish"):
                    return False, f"大盘趋势为空头 ({trend})"
            elif self.required_trend == "bullish":
                if trend not in ("bullish", "strong_bullish"):
                    return False, f"大盘趋势非多头 ({trend})"
            elif self.required_trend == "neutral_or_bearish":
                if trend in ("strong_bullish", "bullish"):
                    return False, f"大盘趋势为多头 ({trend})，不适合"

            return True, f"大盘趋势: {trend} (score={avg_score:.2f})"

        except Exception as e:
            logger.warning(f"TrendCheck 失败: {e}")
            return True, f"趋势检查异常: {e}，默认通过"


# ==========================
# 标的级检查组件 (UnderlyingCheck)
# ==========================

@dataclass
class IVRankCheck:
    """IV Rank 门槛检查

    卖方策略要求 IV Rank 在一定水平以上（卖"贵"的期权）。
    买方策略可能要求 IV Rank 在低位（买"便宜"的期权）。

    Args:
        min_iv_rank: 最低 IV Rank (%)，默认 30
        max_iv_rank: 最高 IV Rank (%)，默认 None（不限）
    """
    min_iv_rank: float = 30.0
    max_iv_rank: float | None = None

    def check(self, symbol: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            from src.engine.position.volatility.metrics import get_iv_rank

            vol_data = data_provider.get_stock_volatility(symbol)
            if not vol_data:
                return False, f"{symbol}: 无法获取波动率数据"

            iv_rank = get_iv_rank(vol_data)
            if iv_rank is None:
                return False, f"{symbol}: IV Rank 不可用"

            if iv_rank < self.min_iv_rank:
                return False, f"{symbol}: IV Rank={iv_rank:.1f}% < {self.min_iv_rank:.0f}%"

            if self.max_iv_rank is not None and iv_rank > self.max_iv_rank:
                return False, f"{symbol}: IV Rank={iv_rank:.1f}% > {self.max_iv_rank:.0f}%"

            return True, f"{symbol}: IV Rank={iv_rank:.1f}%"

        except Exception as e:
            logger.warning(f"IVRankCheck {symbol} 失败: {e}")
            return False, f"{symbol}: IV Rank 检查异常"


@dataclass
class IVHVRatioCheck:
    """IV/HV 比率检查

    检查隐含波动率与历史波动率的比率。
    卖方策略要求 IV/HV > 1（隐含波动率偏高，期权相对"贵"）。

    Args:
        min_ratio: 最低比率
        max_ratio: 最高比率（过高可能有特殊事件）
    """
    min_ratio: float = 1.0
    max_ratio: float = 3.0

    def check(self, symbol: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            from src.engine.position.volatility.metrics import get_iv_hv_ratio

            vol_data = data_provider.get_stock_volatility(symbol)
            if not vol_data:
                return False, f"{symbol}: 无法获取波动率数据"

            ratio = get_iv_hv_ratio(vol_data)
            if ratio is None:
                return False, f"{symbol}: IV/HV 比率不可用"

            if ratio < self.min_ratio:
                return False, f"{symbol}: IV/HV={ratio:.2f} < {self.min_ratio}，期权相对便宜"
            if ratio > self.max_ratio:
                return False, f"{symbol}: IV/HV={ratio:.2f} > {self.max_ratio}，可能有特殊事件"

            return True, f"{symbol}: IV/HV={ratio:.2f}"

        except Exception as e:
            logger.warning(f"IVHVRatioCheck {symbol} 失败: {e}")
            return False, f"{symbol}: IV/HV 检查异常"


@dataclass
class RSIRangeCheck:
    """RSI 区间检查

    Args:
        min_rsi: 最低 RSI
        max_rsi: 最高 RSI
    """
    min_rsi: float = 25.0
    max_rsi: float = 75.0

    def check(self, symbol: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            from src.data.models.stock import KlineType
            from src.data.models.technical import TechnicalData
            from src.engine.position.technical.metrics import calc_technical_score

            ref_date = _get_reference_date(data_provider)
            start_date = ref_date - timedelta(days=300)

            klines = data_provider.get_history_kline(symbol, KlineType.DAY, start_date, ref_date)
            if not klines or len(klines) < 50:
                return True, f"{symbol}: 历史数据不足，跳过 RSI 检查"

            tech_data = TechnicalData.from_klines(klines)
            score = calc_technical_score(tech_data)

            if score.rsi is None:
                return True, f"{symbol}: RSI 不可用，跳过"

            if score.rsi < self.min_rsi:
                return False, f"{symbol}: RSI={score.rsi:.1f} < {self.min_rsi}，超卖"
            if score.rsi > self.max_rsi:
                return False, f"{symbol}: RSI={score.rsi:.1f} > {self.max_rsi}，超买"

            return True, f"{symbol}: RSI={score.rsi:.1f}"

        except Exception as e:
            logger.warning(f"RSIRangeCheck {symbol} 失败: {e}")
            return True, f"{symbol}: RSI 检查异常，跳过"


@dataclass
class ADXCheck:
    """趋势强度检查

    ADX 过高表示趋势过强，卖方策略不宜入场。

    Args:
        max_adx: 最高 ADX
    """
    max_adx: float = 40.0

    def check(self, symbol: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            from src.data.models.stock import KlineType
            from src.data.models.technical import TechnicalData
            from src.engine.position.technical.metrics import calc_technical_score

            ref_date = _get_reference_date(data_provider)
            start_date = ref_date - timedelta(days=300)

            klines = data_provider.get_history_kline(symbol, KlineType.DAY, start_date, ref_date)
            if not klines or len(klines) < 50:
                return True, f"{symbol}: 历史数据不足，跳过 ADX 检查"

            tech_data = TechnicalData.from_klines(klines)
            score = calc_technical_score(tech_data)

            if score.adx is None:
                return True, f"{symbol}: ADX 不可用，跳过"

            if score.adx > self.max_adx:
                return False, f"{symbol}: ADX={score.adx:.1f} > {self.max_adx}，趋势过强"

            return True, f"{symbol}: ADX={score.adx:.1f}"

        except Exception as e:
            logger.warning(f"ADXCheck {symbol} 失败: {e}")
            return True, f"{symbol}: ADX 检查异常，跳过"


@dataclass
class EarningsCheck:
    """财报日距离检查

    检查标的距下一个财报日的天数。

    Args:
        min_days: 最少距离天数
    """
    min_days: int = 7

    def check(self, symbol: str, data_provider: "DataProvider", **kwargs) -> tuple[bool, str]:
        try:
            fundamental = data_provider.get_fundamental(symbol)
            if fundamental is None:
                return True, f"{symbol}: 基本面数据不可用，跳过"

            earnings_date = getattr(fundamental, "earnings_date", None)
            if not earnings_date:
                return True, f"{symbol}: 无财报日期"

            ref_date = _get_reference_date(data_provider)
            if earnings_date < ref_date:
                return True, f"{symbol}: 财报已过"

            days_to_earnings = (earnings_date - ref_date).days
            if days_to_earnings < self.min_days:
                return False, (
                    f"{symbol}: 财报日 {earnings_date} 仅剩 {days_to_earnings} 天"
                    f"（<{self.min_days}）"
                )

            return True, f"{symbol}: 距财报 {days_to_earnings} 天"

        except Exception as e:
            logger.warning(f"EarningsCheck {symbol} 失败: {e}")
            return True, f"{symbol}: 财报检查异常，跳过"


# ==========================
# 合约级检查组件 (ContractCheck)
# ==========================

@dataclass
class DTERangeCheck:
    """DTE 区间检查

    Args:
        dte_range: (最小DTE, 最大DTE) 元组
    """
    dte_range: tuple[int, int] = (21, 45)

    def check(self, opportunity: ContractOpportunity) -> tuple[bool, str]:
        if opportunity.dte is None:
            return False, f"{opportunity.symbol}: DTE 不可用"

        dte_min, dte_max = self.dte_range
        if dte_min <= opportunity.dte <= dte_max:
            return True, f"DTE={opportunity.dte}"
        return False, f"DTE={opportunity.dte} 不在 [{dte_min}, {dte_max}] 范围内"


@dataclass
class DeltaRangeCheck:
    """Delta 区间检查

    使用绝对值检查。

    Args:
        delta_range: (最小|delta|, 最大|delta|) 元组
    """
    delta_range: tuple[float, float] = (0.15, 0.30)

    def check(self, opportunity: ContractOpportunity) -> tuple[bool, str]:
        if opportunity.delta is None:
            return False, f"{opportunity.symbol}: Delta 不可用"

        abs_delta = abs(opportunity.delta)
        d_min, d_max = self.delta_range
        if d_min <= abs_delta <= d_max:
            return True, f"|Delta|={abs_delta:.3f}"
        return False, f"|Delta|={abs_delta:.3f} 不在 [{d_min}, {d_max}] 范围内"


@dataclass
class LiquidityCheck:
    """流动性检查

    Args:
        min_oi: 最低持仓量
        max_spread: 最大 bid-ask spread 比率
    """
    min_oi: int = 100
    max_spread: float = 0.10

    def check(self, opportunity: ContractOpportunity) -> tuple[bool, str]:
        # 检查 OI
        oi = opportunity.open_interest or 0
        if oi < self.min_oi:
            return False, f"OI={oi} < {self.min_oi}，流动性不足"

        # 检查 spread
        if opportunity.bid and opportunity.ask and opportunity.ask > 0:
            spread = (opportunity.ask - opportunity.bid) / opportunity.ask
            if spread > self.max_spread:
                return False, f"Spread={spread:.1%} > {self.max_spread:.0%}，交易成本过高"

        return True, f"OI={oi}, 流动性正常"


@dataclass
class ExpectedROCCheck:
    """预期 ROC 检查

    Args:
        min_roc: 最低预期 ROC
    """
    min_roc: float = 0.0

    def check(self, opportunity: ContractOpportunity) -> tuple[bool, str]:
        roc = opportunity.expected_roc
        if roc is None:
            return False, "Expected ROC 不可用"

        if roc > self.min_roc:
            return True, f"E[ROC]={roc:.1%}"
        return False, f"E[ROC]={roc:.1%} < {self.min_roc:.1%}"


@dataclass
class TGRCheck:
    """Theta/Gamma 比率检查

    TGR > 1.0 表示时间衰减收益覆盖 gamma 风险。

    Args:
        min_tgr: 最低 TGR
    """
    min_tgr: float = 1.0

    def check(self, opportunity: ContractOpportunity) -> tuple[bool, str]:
        tgr = opportunity.tgr
        if tgr is None:
            return False, "TGR 不可用"

        if tgr >= self.min_tgr:
            return True, f"TGR={tgr:.2f}"
        return False, f"TGR={tgr:.2f} < {self.min_tgr}"


# ==========================
# 工具函数
# ==========================

def _get_reference_date(data_provider) -> date:
    """获取参考日期（回测兼容）"""
    if hasattr(data_provider, "as_of_date"):
        return data_provider.as_of_date
    return date.today()
