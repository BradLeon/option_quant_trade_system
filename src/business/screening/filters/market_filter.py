"""
Market Filter - 市场环境过滤器

第一层筛选：判断市场环境是否适合期权卖方策略

检查项目：
- VIX/波动率指数状态
- 大盘趋势（SPY/QQQ 或 2800.HK/3033.HK）
- 期限结构（VIX/VIX3M，仅美股）
- Put/Call Ratio
"""

import logging
from datetime import date, timedelta
from typing import Protocol

from src.business.config.screening_config import (
    HKMarketConfig,
    ScreeningConfig,
    USMarketConfig,
)
from src.business.screening.models import (
    FilterStatus,
    IndexStatus,
    MarketStatus,
    MarketType,
    PCRStatus,
    TermStructureStatus,
    TrendStatus,
    VolatilityIndexStatus,
    VolatilityStatus,
)
from src.engine.account.sentiment.trend import calc_sma, calc_spy_trend
from src.engine.account.sentiment.vix import get_vix_zone
from src.engine.models.enums import TrendSignal

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

    def get_macro_data(
        self,
        indicator: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """获取宏观数据"""
        ...

    def get_put_call_ratio(self, symbol: str) -> float | None:
        """获取 Put/Call Ratio"""
        ...

    def get_stock_volatility(self, symbol: str, include_iv_rank: bool = True) -> object | None:
        """获取股票波动率数据"""
        ...


class MarketFilter:
    """市场环境过滤器

    根据配置检查市场环境是否适合开仓：
    1. 波动率指数在合适范围内
    2. 大盘趋势不为强空头
    3. 期限结构（美股）处于正常状态
    4. PCR 在合理范围内

    使用方式：
        filter = MarketFilter(config, data_provider)
        status = filter.evaluate(MarketType.US)
        if status.is_favorable:
            # 继续筛选
    """

    def __init__(
        self,
        config: ScreeningConfig,
        data_provider: DataProvider,
    ) -> None:
        """初始化市场过滤器

        Args:
            config: 筛选配置
            data_provider: 数据提供者（Yahoo/IBKR）
        """
        self.config = config
        self.provider = data_provider

    def evaluate(self, market_type: MarketType) -> MarketStatus:
        """评估市场环境

        Args:
            market_type: 市场类型 (US/HK)

        Returns:
            MarketStatus: 市场状态评估结果
        """
        if market_type == MarketType.US:
            return self._evaluate_us_market()
        else:
            return self._evaluate_hk_market()

    def _evaluate_us_market(self) -> MarketStatus:
        """评估美股市场环境"""
        us_config = self.config.market_filter.us_market
        unfavorable_reasons: list[str] = []

        # 1. 检查 VIX
        vix_status = self._get_vix_status(us_config)

        # 2. 检查大盘趋势
        trend_indices, overall_trend = self._get_us_trend_status(us_config)

        # 3. 检查期限结构
        term_structure = self._get_term_structure_status(us_config)

        # 4. 检查 PCR
        pcr_status = self._get_pcr_status(us_config.pcr_symbol, us_config.pcr_range)

        # 评估是否有利
        is_favorable = True

        # VIX 检查
        if vix_status and vix_status.filter_status == FilterStatus.UNFAVORABLE:
            is_favorable = False
            if vix_status.value < us_config.vix_range[0]:
                unfavorable_reasons.append(
                    f"VIX={vix_status.value:.1f} 偏低（<{us_config.vix_range[0]}），"
                    f"权利金不足"
                )
            elif vix_status.value > us_config.vix_range[1]:
                unfavorable_reasons.append(
                    f"VIX={vix_status.value:.1f} 过高（>{us_config.vix_range[1]}），"
                    f"风险过大"
                )

        # 趋势检查
        if overall_trend in [TrendStatus.STRONG_BEARISH, TrendStatus.BEARISH]:
            trend_required = us_config.trend_required
            if trend_required == "bullish_or_neutral":
                is_favorable = False
                unfavorable_reasons.append(f"大盘趋势为空头 ({overall_trend.value})")
            elif trend_required == "bullish" and overall_trend != TrendStatus.BULLISH:
                is_favorable = False
                unfavorable_reasons.append("大盘趋势非多头")

        # 期限结构检查
        if term_structure and term_structure.filter_status == FilterStatus.UNFAVORABLE:
            is_favorable = False
            unfavorable_reasons.append(
                f"期限结构异常: VIX/VIX3M={term_structure.ratio:.2f} "
                f"(>={us_config.term_structure_threshold}), 短期恐慌"
            )

        # PCR 检查（仅作参考，不作为硬性条件）
        if pcr_status and pcr_status.filter_status == FilterStatus.UNFAVORABLE:
            # PCR 异常只记录警告，不影响 is_favorable
            logger.warning(
                f"PCR={pcr_status.value:.2f} 超出范围 {us_config.pcr_range}"
            )

        return MarketStatus(
            market_type=MarketType.US,
            is_favorable=is_favorable,
            volatility_index=vix_status,
            trend_indices=trend_indices,
            overall_trend=overall_trend,
            term_structure=term_structure,
            pcr=pcr_status,
            unfavorable_reasons=unfavorable_reasons,
        )

    def _evaluate_hk_market(self) -> MarketStatus:
        """评估港股市场环境"""
        hk_config = self.config.market_filter.hk_market
        unfavorable_reasons: list[str] = []

        # 1. 检查波动率（使用 2800.HK 期权链 IV）
        vol_status = self._get_hk_volatility_status(hk_config)

        # 2. 检查大盘趋势
        trend_indices, overall_trend = self._get_hk_trend_status(hk_config)

        # 评估是否有利
        is_favorable = True

        # 波动率检查
        if vol_status and vol_status.filter_status == FilterStatus.UNFAVORABLE:
            is_favorable = False
            if vol_status.value < hk_config.iv_range[0]:
                unfavorable_reasons.append(
                    f"2800.HK IV={vol_status.value:.1f}% 偏低（<{hk_config.iv_range[0]}），"
                    f"权利金不足"
                )
            elif vol_status.value > hk_config.iv_range[1]:
                unfavorable_reasons.append(
                    f"2800.HK IV={vol_status.value:.1f}% 过高（>{hk_config.iv_range[1]}），"
                    f"风险过大"
                )

        # 趋势检查
        if overall_trend in [TrendStatus.STRONG_BEARISH, TrendStatus.BEARISH]:
            trend_required = hk_config.trend_required
            if trend_required == "bullish_or_neutral":
                is_favorable = False
                unfavorable_reasons.append(f"大盘趋势为空头 ({overall_trend.value})")
            elif trend_required == "bullish" and overall_trend != TrendStatus.BULLISH:
                is_favorable = False
                unfavorable_reasons.append("大盘趋势非多头")

        return MarketStatus(
            market_type=MarketType.HK,
            is_favorable=is_favorable,
            volatility_index=vol_status,
            trend_indices=trend_indices,
            overall_trend=overall_trend,
            term_structure=None,  # 港股无期限结构
            pcr=None,  # 港股 PCR 数据可用性较低
            unfavorable_reasons=unfavorable_reasons,
        )

    def _get_vix_status(self, config: USMarketConfig) -> VolatilityIndexStatus | None:
        """获取 VIX 状态"""
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=365)

            # 获取 VIX 历史数据
            macro_data = self.provider.get_macro_data(
                config.vix_symbol,
                start_date,
                end_date,
            )

            if not macro_data:
                logger.warning("无法获取 VIX 数据")
                return None

            current_vix = macro_data[-1].close if macro_data else None
            if current_vix is None:
                return None

            # 计算百分位
            historical_values = [d.close for d in macro_data if d.close is not None]
            percentile = None
            if historical_values:
                count_lower = sum(1 for v in historical_values if v < current_vix)
                percentile = count_lower / len(historical_values)

            # 判断状态
            vix_zone = get_vix_zone(current_vix)
            if vix_zone.value == "low":
                status = VolatilityStatus.LOW
            elif vix_zone.value == "normal":
                status = VolatilityStatus.NORMAL
            elif vix_zone.value in ["elevated", "high"]:
                status = VolatilityStatus.HIGH
            else:
                status = VolatilityStatus.EXTREME

            # 判断过滤状态
            vix_low, vix_high = config.vix_range
            if vix_low <= current_vix <= vix_high:
                filter_status = FilterStatus.FAVORABLE
            else:
                filter_status = FilterStatus.UNFAVORABLE

            # 额外检查百分位
            if percentile is not None:
                pct_low, pct_high = config.vix_percentile_range
                if not (pct_low <= percentile <= pct_high):
                    filter_status = FilterStatus.UNFAVORABLE

            return VolatilityIndexStatus(
                symbol=config.vix_symbol,
                value=current_vix,
                percentile=percentile,
                status=status,
                filter_status=filter_status,
            )

        except Exception as e:
            logger.error(f"获取 VIX 状态失败: {e}")
            return None

    def _get_hk_volatility_status(
        self,
        config: HKMarketConfig,
    ) -> VolatilityIndexStatus | None:
        """获取港股波动率状态（使用 2800.HK 期权链 IV）"""
        try:
            # 使用 IBKR 的 get_stock_volatility 获取 2800.HK 的 IV
            vol_data = self.provider.get_stock_volatility(
                config.volatility_source,
                include_iv_rank=True,
            )

            if vol_data is None or vol_data.iv is None:
                logger.warning(f"无法获取 {config.volatility_source} 波动率数据")
                return None

            # IV 通常以小数形式存储，转换为百分比
            current_iv = vol_data.iv * 100 if vol_data.iv < 1 else vol_data.iv
            percentile = vol_data.iv_percentile

            # 判断状态
            iv_low, iv_high = config.iv_range
            if current_iv < iv_low:
                status = VolatilityStatus.LOW
                filter_status = FilterStatus.UNFAVORABLE
            elif current_iv > iv_high:
                status = VolatilityStatus.EXTREME if current_iv > iv_high * 1.5 else VolatilityStatus.HIGH
                filter_status = FilterStatus.UNFAVORABLE
            else:
                status = VolatilityStatus.NORMAL
                filter_status = FilterStatus.FAVORABLE

            # 额外检查百分位
            if percentile is not None:
                pct_low, pct_high = config.iv_percentile_range
                if not (pct_low <= percentile <= pct_high):
                    # 如果百分位超出范围，降级为中性或不利
                    if filter_status == FilterStatus.FAVORABLE:
                        filter_status = FilterStatus.NEUTRAL

            return VolatilityIndexStatus(
                symbol=config.volatility_source,
                value=current_iv,
                percentile=percentile,
                status=status,
                filter_status=filter_status,
            )

        except Exception as e:
            logger.error(f"获取港股波动率状态失败: {e}")
            return None

    def _get_us_trend_status(
        self,
        config: USMarketConfig,
    ) -> tuple[list[IndexStatus], TrendStatus]:
        """获取美股大盘趋势状态"""
        return self._get_trend_status(
            [(idx.symbol, idx.weight) for idx in config.trend_indices]
        )

    def _get_hk_trend_status(
        self,
        config: HKMarketConfig,
    ) -> tuple[list[IndexStatus], TrendStatus]:
        """获取港股大盘趋势状态"""
        return self._get_trend_status(
            [(idx.symbol, idx.weight) for idx in config.trend_indices]
        )

    def _get_trend_status(
        self,
        indices: list[tuple[str, float]],
    ) -> tuple[list[IndexStatus], TrendStatus]:
        """获取趋势状态（通用）

        Args:
            indices: 指数列表 [(symbol, weight), ...]

        Returns:
            (IndexStatus列表, 整体趋势)
        """
        from src.data.models.stock import KlineType

        index_statuses: list[IndexStatus] = []
        weighted_scores: list[tuple[float, float]] = []  # (score, weight)

        end_date = date.today()
        start_date = end_date - timedelta(days=300)  # 足够计算 SMA200

        for symbol, weight in indices:
            try:
                # 获取历史 K 线
                klines = self.provider.get_history_kline(
                    symbol,
                    KlineType.DAY,
                    start_date,
                    end_date,
                )

                if not klines or len(klines) < 50:
                    logger.warning(f"指数 {symbol} 数据不足")
                    continue

                # 提取收盘价
                closes = [k.close for k in klines]
                current_price = closes[-1]

                # 计算均线
                sma20 = calc_sma(closes, 20)
                sma50 = calc_sma(closes, 50)
                sma200 = calc_sma(closes, 200) if len(closes) >= 200 else None

                # 判断趋势
                trend_signal = calc_spy_trend(closes)
                if trend_signal == TrendSignal.BULLISH:
                    if sma200 and current_price > sma200 and sma20 and sma20 > sma200:
                        trend = TrendStatus.STRONG_BULLISH
                        score = 2.0
                    else:
                        trend = TrendStatus.BULLISH
                        score = 1.0
                elif trend_signal == TrendSignal.BEARISH:
                    if sma200 and current_price < sma200 and sma20 and sma20 < sma200:
                        trend = TrendStatus.STRONG_BEARISH
                        score = -2.0
                    else:
                        trend = TrendStatus.BEARISH
                        score = -1.0
                else:
                    trend = TrendStatus.NEUTRAL
                    score = 0.0

                index_statuses.append(
                    IndexStatus(
                        symbol=symbol,
                        price=current_price,
                        sma20=sma20,
                        sma50=sma50,
                        sma200=sma200,
                        trend=trend,
                        weight=weight,
                    )
                )
                weighted_scores.append((score, weight))

            except Exception as e:
                logger.error(f"获取指数 {symbol} 趋势失败: {e}")
                continue

        # 计算加权平均趋势
        if weighted_scores:
            total_weight = sum(w for _, w in weighted_scores)
            if total_weight > 0:
                avg_score = sum(s * w for s, w in weighted_scores) / total_weight
            else:
                avg_score = 0.0
        else:
            avg_score = 0.0

        # 映射到趋势状态
        if avg_score >= 1.5:
            overall_trend = TrendStatus.STRONG_BULLISH
        elif avg_score >= 0.5:
            overall_trend = TrendStatus.BULLISH
        elif avg_score <= -1.5:
            overall_trend = TrendStatus.STRONG_BEARISH
        elif avg_score <= -0.5:
            overall_trend = TrendStatus.BEARISH
        else:
            overall_trend = TrendStatus.NEUTRAL

        return index_statuses, overall_trend

    def _get_term_structure_status(
        self,
        config: USMarketConfig,
    ) -> TermStructureStatus | None:
        """获取 VIX 期限结构状态"""
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=5)

            # 获取 VIX
            vix_data = self.provider.get_macro_data(
                config.vix_symbol,
                start_date,
                end_date,
            )

            # 获取 VIX3M
            vix3m_data = self.provider.get_macro_data(
                config.vix3m_symbol,
                start_date,
                end_date,
            )

            if not vix_data or not vix3m_data:
                return None

            vix_value = vix_data[-1].close
            vix3m_value = vix3m_data[-1].close

            if vix_value is None or vix3m_value is None or vix3m_value == 0:
                return None

            ratio = vix_value / vix3m_value
            is_contango = ratio < 1.0  # VIX < VIX3M 为正向结构

            # 判断过滤状态
            if ratio >= config.term_structure_threshold:
                filter_status = FilterStatus.UNFAVORABLE
            elif ratio < 0.85:
                filter_status = FilterStatus.FAVORABLE
            else:
                filter_status = FilterStatus.NEUTRAL

            return TermStructureStatus(
                vix_value=vix_value,
                vix3m_value=vix3m_value,
                ratio=ratio,
                is_contango=is_contango,
                filter_status=filter_status,
            )

        except Exception as e:
            logger.error(f"获取期限结构状态失败: {e}")
            return None

    def _get_pcr_status(
        self,
        symbol: str,
        pcr_range: tuple[float, float],
    ) -> PCRStatus | None:
        """获取 Put/Call Ratio 状态"""
        try:
            pcr = self.provider.get_put_call_ratio(symbol)

            if pcr is None:
                return None

            pcr_low, pcr_high = pcr_range
            if pcr_low <= pcr <= pcr_high:
                filter_status = FilterStatus.NEUTRAL
            elif pcr > pcr_high:
                # 高 PCR 可能是机会（逆向指标）
                filter_status = FilterStatus.OPPORTUNITY
            else:
                filter_status = FilterStatus.UNFAVORABLE

            return PCRStatus(
                symbol=symbol,
                value=pcr,
                filter_status=filter_status,
            )

        except Exception as e:
            logger.error(f"获取 PCR 状态失败: {e}")
            return None
