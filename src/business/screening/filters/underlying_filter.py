"""
Underlying Filter - 标的过滤器

第二层筛选：评估单个标的是否适合期权卖方策略

检查项目：
- IV Rank >= 50%
- IV/HV 比率在合理范围
- 技术面（RSI、布林带、均线排列）
- 基本面（可选）
"""

import logging
from datetime import date, timedelta
from typing import Protocol

from src.business.config.screening_config import (
    FundamentalConfig,
    ScreeningConfig,
    TechnicalConfig,
    UnderlyingFilterConfig,
)
from src.business.screening.models import (
    FundamentalScore,
    MarketType,
    TechnicalScore,
    UnderlyingScore,
)
from src.engine.position.technical.metrics import (
    calc_technical_score,
    calc_technical_signal,
)
from src.engine.position.volatility.metrics import (
    evaluate_volatility,
    get_iv_hv_ratio,
    get_iv_rank,
    interpret_iv_rank,
)

logger = logging.getLogger(__name__)


class DataProvider(Protocol):
    """数据提供者接口"""

    def get_stock_quote(self, symbol: str) -> object | None:
        """获取股票报价"""
        ...

    def get_history_kline(
        self,
        symbol: str,
        ktype: object,
        start_date: date,
        end_date: date,
    ) -> list:
        """获取历史K线"""
        ...

    def get_stock_volatility(
        self,
        symbol: str,
        include_iv_rank: bool = True,
    ) -> object | None:
        """获取股票波动率数据"""
        ...

    def get_fundamental(self, symbol: str) -> object | None:
        """获取基本面数据"""
        ...


class UnderlyingFilter:
    """标的过滤器

    根据配置检查单个标的是否适合开仓：
    1. IV Rank 在合适范围内（>= min_iv_rank）
    2. IV/HV 比率合理（min_iv_hv_ratio <= ratio <= max_iv_hv_ratio）
    3. 技术面信号有利（RSI 企稳、均线排列等）
    4. 基本面检查（可选，如 PE 百分位、分析师评级等）

    使用方式：
        filter = UnderlyingFilter(config, data_provider)
        scores = filter.evaluate(symbols, MarketType.US)
        for score in scores:
            if score.passed:
                # 继续筛选合约
    """

    def __init__(
        self,
        config: ScreeningConfig,
        data_provider: DataProvider,
    ) -> None:
        """初始化标的过滤器

        Args:
            config: 筛选配置
            data_provider: 数据提供者（Yahoo/IBKR）
        """
        self.config = config
        self.provider = data_provider

    def evaluate(
        self,
        symbols: list[str],
        market_type: MarketType,
    ) -> list[UnderlyingScore]:
        """批量评估标的

        Args:
            symbols: 标的列表
            market_type: 市场类型

        Returns:
            UnderlyingScore 列表
        """
        results: list[UnderlyingScore] = []

        for symbol in symbols:
            try:
                score = self._evaluate_single(symbol, market_type)
                results.append(score)
            except Exception as e:
                logger.error(f"评估标的 {symbol} 失败: {e}")
                results.append(
                    UnderlyingScore(
                        symbol=symbol,
                        market_type=market_type,
                        passed=False,
                        disqualify_reasons=[f"评估失败: {str(e)}"],
                    )
                )

        return results

    def evaluate_single(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> UnderlyingScore:
        """评估单个标的

        Args:
            symbol: 标的代码
            market_type: 市场类型

        Returns:
            UnderlyingScore: 评估结果
        """
        return self._evaluate_single(symbol, market_type)

    def _evaluate_single(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> UnderlyingScore:
        """评估单个标的（内部实现）"""
        filter_config = self.config.underlying_filter
        disqualify_reasons: list[str] = []

        # 获取当前价格
        current_price = self._get_current_price(symbol)

        # 1. 获取波动率数据
        vol_data = self._get_volatility_data(symbol)
        iv_rank = None
        iv_hv_ratio = None
        hv_20 = None
        current_iv = None

        if vol_data:
            iv_rank = get_iv_rank(vol_data)
            iv_hv_ratio = get_iv_hv_ratio(vol_data)
            hv_20 = vol_data.hv
            current_iv = vol_data.iv

            # 检查 IV Rank
            if iv_rank is not None and iv_rank < filter_config.min_iv_rank:
                disqualify_reasons.append(
                    f"IV Rank={iv_rank:.1f}% 偏低（<{filter_config.min_iv_rank}%）"
                )

            # 检查 IV/HV 比率
            if iv_hv_ratio is not None:
                if iv_hv_ratio < filter_config.min_iv_hv_ratio:
                    disqualify_reasons.append(
                        f"IV/HV={iv_hv_ratio:.2f} 偏低（<{filter_config.min_iv_hv_ratio}），"
                        f"期权相对便宜"
                    )
                elif iv_hv_ratio > filter_config.max_iv_hv_ratio:
                    disqualify_reasons.append(
                        f"IV/HV={iv_hv_ratio:.2f} 过高（>{filter_config.max_iv_hv_ratio}），"
                        f"可能有特殊事件"
                    )
        else:
            disqualify_reasons.append("无法获取波动率数据")

        # 2. 获取技术面评分
        technical = self._evaluate_technical(symbol, filter_config.technical)
        tech_reasons = self._check_technical(technical, filter_config.technical)
        disqualify_reasons.extend(tech_reasons)

        # 3. 获取基本面评分（可选）
        fundamental = None
        if filter_config.fundamental.enabled:
            fundamental = self._evaluate_fundamental(symbol, filter_config.fundamental)
            fund_reasons = self._check_fundamental(fundamental, filter_config.fundamental)
            disqualify_reasons.extend(fund_reasons)

        # 综合判断
        passed = len(disqualify_reasons) == 0

        return UnderlyingScore(
            symbol=symbol,
            market_type=market_type,
            passed=passed,
            current_price=current_price,
            iv_rank=iv_rank,
            iv_hv_ratio=iv_hv_ratio,
            hv_20=hv_20,
            current_iv=current_iv,
            technical=technical,
            fundamental=fundamental,
            disqualify_reasons=disqualify_reasons,
        )

    def _get_current_price(self, symbol: str) -> float | None:
        """获取当前价格"""
        try:
            quote = self.provider.get_stock_quote(symbol)
            if quote and hasattr(quote, "close") and quote.close:
                return quote.close
            return None
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格失败: {e}")
            return None

    def _get_volatility_data(self, symbol: str) -> object | None:
        """获取波动率数据"""
        try:
            return self.provider.get_stock_volatility(symbol, include_iv_rank=True)
        except Exception as e:
            logger.warning(f"获取 {symbol} 波动率数据失败: {e}")
            return None

    def _evaluate_technical(
        self,
        symbol: str,
        config: TechnicalConfig,
    ) -> TechnicalScore | None:
        """评估技术面"""
        from src.data.models.stock import KlineType
        from src.data.models.technical import TechnicalData

        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=300)  # 足够计算技术指标

            klines = self.provider.get_history_kline(
                symbol,
                KlineType.DAY,
                start_date,
                end_date,
            )

            if not klines or len(klines) < 50:
                logger.warning(f"{symbol} 历史数据不足")
                return None

            # 构建 TechnicalData
            tech_data = TechnicalData(
                symbol=symbol,
                opens=[k.open for k in klines],
                highs=[k.high for k in klines],
                lows=[k.low for k in klines],
                closes=[k.close for k in klines],
                volumes=[k.volume for k in klines] if hasattr(klines[0], "volume") else None,
            )

            # 计算技术评分和信号
            score = calc_technical_score(tech_data)
            signal = calc_technical_signal(tech_data)

            # 映射 RSI zone
            rsi_zone = "neutral"
            if score.rsi is not None:
                if score.rsi <= 30:
                    rsi_zone = "oversold"
                elif score.rsi <= 45:
                    rsi_zone = "stabilizing"
                elif score.rsi <= 55:
                    rsi_zone = "neutral"
                elif score.rsi <= 70:
                    rsi_zone = "exhausting"
                else:
                    rsi_zone = "overbought"

            # 计算距离支撑位的百分比
            support_distance = None
            if score.support and score.current_price:
                support_distance = (score.current_price - score.support) / score.support * 100

            return TechnicalScore(
                rsi=score.rsi,
                rsi_zone=rsi_zone,
                bb_percent_b=score.bb_percent_b,
                adx=score.adx,
                sma_alignment=score.ma_alignment,
                support_distance=support_distance,
            )

        except Exception as e:
            logger.warning(f"评估 {symbol} 技术面失败: {e}")
            return None

    def _check_technical(
        self,
        technical: TechnicalScore | None,
        config: TechnicalConfig,
    ) -> list[str]:
        """检查技术面是否符合条件"""
        reasons: list[str] = []

        if technical is None:
            return reasons  # 技术面数据缺失不作为淘汰条件

        # RSI 检查
        if technical.rsi is not None:
            if technical.rsi < config.min_rsi:
                reasons.append(f"RSI={technical.rsi:.1f} 过低（<{config.min_rsi}），超卖风险")
            elif technical.rsi > config.max_rsi:
                reasons.append(f"RSI={technical.rsi:.1f} 过高（>{config.max_rsi}），超买风险")

        # ADX 检查（趋势过强不利于期权卖方）
        if technical.adx is not None and technical.adx > config.max_adx:
            reasons.append(f"ADX={technical.adx:.1f} 过高（>{config.max_adx}），趋势过强")

        # 均线排列检查
        alignment_order = [
            "strong_bullish",
            "bullish",
            "neutral",
            "bearish",
            "strong_bearish",
        ]
        min_alignment = config.min_sma_alignment
        if min_alignment in alignment_order:
            min_idx = alignment_order.index(min_alignment)
            current_alignment = technical.sma_alignment or "neutral"
            if current_alignment in alignment_order:
                current_idx = alignment_order.index(current_alignment)
                # 对于 short put，空头排列不利
                if current_idx > min_idx + 1:  # 允许一定容忍度
                    reasons.append(
                        f"均线排列为 {current_alignment}，"
                        f"需至少 {min_alignment}"
                    )

        return reasons

    def _evaluate_fundamental(
        self,
        symbol: str,
        config: FundamentalConfig,
    ) -> FundamentalScore | None:
        """评估基本面"""
        try:
            fundamental = self.provider.get_fundamental(symbol)

            if fundamental is None:
                return None

            # 提取关键指标
            pe_ratio = getattr(fundamental, "pe_ratio", None)
            revenue_growth = getattr(fundamental, "revenue_growth", None)
            recommendation = getattr(fundamental, "recommendation", None)
            recommendation_mean = getattr(fundamental, "recommendation_mean", None)

            # 计算 PE 百分位（需要历史数据或行业对比，这里简化处理）
            pe_percentile = None
            if pe_ratio is not None:
                # 简化假设：PE 在 10-30 之间为正常
                if pe_ratio < 10:
                    pe_percentile = 0.1
                elif pe_ratio > 30:
                    pe_percentile = 0.9
                else:
                    pe_percentile = (pe_ratio - 10) / 20

            # 映射推荐评级
            rec_map = {
                "strong_buy": "strong_buy",
                "buy": "buy",
                "hold": "hold",
                "sell": "sell",
                "strong_sell": "strong_sell",
            }
            rec = rec_map.get(recommendation, None)

            # 计算综合评分
            score = 50.0  # 默认中性
            if pe_percentile is not None:
                # PE 越低越好
                score += (0.5 - pe_percentile) * 30

            if revenue_growth is not None:
                # 正增长加分
                if revenue_growth > 0.2:
                    score += 20
                elif revenue_growth > 0.1:
                    score += 10
                elif revenue_growth < 0:
                    score -= 10

            if rec in ["strong_buy", "buy"]:
                score += 15
            elif rec in ["sell", "strong_sell"]:
                score -= 15

            score = max(0.0, min(100.0, score))

            return FundamentalScore(
                pe_ratio=pe_ratio,
                pe_percentile=pe_percentile,
                revenue_growth=revenue_growth,
                recommendation=rec,
                score=score,
            )

        except Exception as e:
            logger.warning(f"评估 {symbol} 基本面失败: {e}")
            return None

    def _check_fundamental(
        self,
        fundamental: FundamentalScore | None,
        config: FundamentalConfig,
    ) -> list[str]:
        """检查基本面是否符合条件"""
        reasons: list[str] = []

        if fundamental is None:
            return reasons  # 基本面数据缺失不作为淘汰条件

        # PE 百分位检查
        if fundamental.pe_percentile is not None:
            if fundamental.pe_percentile > config.max_pe_percentile:
                reasons.append(
                    f"PE 百分位={fundamental.pe_percentile:.1%} 过高"
                    f"（>{config.max_pe_percentile:.0%}），估值偏贵"
                )

        # 推荐评级检查
        if fundamental.recommendation is not None:
            rec_order = ["strong_buy", "buy", "hold", "sell", "strong_sell"]
            min_rec = config.min_recommendation
            if min_rec in rec_order and fundamental.recommendation in rec_order:
                min_idx = rec_order.index(min_rec)
                current_idx = rec_order.index(fundamental.recommendation)
                if current_idx > min_idx:
                    reasons.append(
                        f"分析师评级为 {fundamental.recommendation}，"
                        f"需至少 {min_rec}"
                    )

        return reasons

    def filter_passed(
        self,
        scores: list[UnderlyingScore],
    ) -> list[UnderlyingScore]:
        """过滤出通过筛选的标的

        Args:
            scores: 评分列表

        Returns:
            通过筛选的标的列表
        """
        return [s for s in scores if s.passed]

    def sort_by_score(
        self,
        scores: list[UnderlyingScore],
        descending: bool = True,
    ) -> list[UnderlyingScore]:
        """按综合评分排序

        Args:
            scores: 评分列表
            descending: 是否降序

        Returns:
            排序后的列表
        """
        return sorted(
            scores,
            key=lambda s: s.composite_score,
            reverse=descending,
        )
