"""
Market Filter - 市场环境过滤器

第一层筛选：判断市场环境是否适合期权卖方策略

检查项目：
- VIX/波动率指数状态
- 大盘趋势（SPY/QQQ 或 2800.HK/3033.HK）
- 期限结构（VIX/VIX3M，仅美股）
- Put/Call Ratio

架构说明：
- 数据获取：调用 data_layer (UnifiedDataProvider)
- 指标计算：调用 engine_layer (sentiment 模块)
- 业务逻辑：本模块专注业务判断和编排
"""

import logging
from datetime import date, timedelta

from src.business.config.screening_config import (
    HKMarketConfig,
    MacroEventConfig,
    ScreeningConfig,
    USMarketConfig,
)
from src.business.screening.models import (
    FilterStatus,
    IndexStatus,
    MacroEventStatus,
    MarketStatus,
    MarketType,
    TermStructureStatus,
    TrendStatus,
    VolatilityIndexStatus,
    VolatilityStatus,
)
from src.data.models.stock import KlineType
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.account.sentiment import (
    calc_sma,
    calc_spy_trend,
    calc_term_structure,
    calc_vix_percentile,
    get_vix_zone,
)
from src.engine.models.enums import TermStructure, TrendSignal

logger = logging.getLogger(__name__)


class MarketFilter:
    """市场环境过滤器

    根据配置检查市场环境是否适合开仓：
    1. 波动率指数在合适范围内
    2. 大盘趋势不为强空头
    3. 期限结构（美股）处于正常状态
    4. PCR 在合理范围内

    架构职责：
    - data_layer: UnifiedDataProvider 提供原始数据
    - engine_layer: sentiment 模块提供指标计算
    - business_layer: 本模块进行业务判断和编排

    使用方式：
        filter = MarketFilter(config, provider)
        status = filter.evaluate(MarketType.US)
        if status.is_favorable:
            # 继续筛选
    """

    def __init__(
        self,
        config: ScreeningConfig,
        provider: UnifiedDataProvider | None = None,
    ) -> None:
        """初始化市场过滤器

        Args:
            config: 筛选配置
            provider: 统一数据提供者，默认创建新实例
        """
        self.config = config
        self.provider = provider or UnifiedDataProvider()

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
        macro_config = self.config.market_filter.macro_events
        unfavorable_reasons: list[str] = []

        # 1. 检查 VIX
        vix_status = self._get_vix_status(us_config)

        # 2. 检查大盘趋势
        trend_indices, overall_trend = self._get_us_trend_status(us_config)

        # 3. 检查期限结构
        term_structure = self._get_term_structure_status(us_config)

        # 4. 检查宏观事件
        macro_status = self._check_macro_events(macro_config)

        # 评估是否有利
        is_favorable = True

        # 宏观事件黑名单检查（最高优先级）
        if macro_status and macro_status.is_in_blackout:
            is_favorable = False
            event_names = ", ".join(macro_status.event_names[:3])
            unfavorable_reasons.append(
                f"宏观事件黑名单期: {event_names} 将于 {macro_status.blackout_days} 天内发布"
            )

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
            # 检查 percentile 超出范围的情况
            elif vix_status.percentile is not None:
                pct_low, pct_high = us_config.vix_percentile_range
                if vix_status.percentile < pct_low:
                    unfavorable_reasons.append(
                        f"VIX Percentile={vix_status.percentile*100:.1f}% 偏低"
                        f"（<{pct_low*100:.0f}%），历史低位"
                    )
                elif vix_status.percentile > pct_high:
                    unfavorable_reasons.append(
                        f"VIX Percentile={vix_status.percentile*100:.1f}% 过高"
                        f"（>{pct_high*100:.0f}%），恐慌情绪"
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

        # PCR 已删除: 0.8-1.2 是常态震荡无过滤价值，数据质量不稳定

        return MarketStatus(
            market_type=MarketType.US,
            is_favorable=is_favorable,
            volatility_index=vix_status,
            trend_indices=trend_indices,
            overall_trend=overall_trend,
            term_structure=term_structure,
            pcr=None,  # PCR 已删除
            macro_events=macro_status,
            unfavorable_reasons=unfavorable_reasons,
        )

    def _evaluate_hk_market(self) -> MarketStatus:
        """评估港股市场环境"""
        hk_config = self.config.market_filter.hk_market
        macro_config = self.config.market_filter.macro_events
        unfavorable_reasons: list[str] = []

        # 1. 检查波动率（使用 VHSI - 恒生波动率指数）
        vol_status = self._get_hk_volatility_status(hk_config)

        # 2. 检查大盘趋势
        trend_indices, overall_trend = self._get_hk_trend_status(hk_config)

        # 3. 检查宏观事件（复用 US 逻辑，FOMC 对全球市场有影响）
        macro_status = None
        if hk_config.check_us_macro_events:
            macro_status = self._check_macro_events(macro_config)

        # 评估是否有利
        is_favorable = True

        # 宏观事件黑名单检查
        if macro_status and macro_status.is_in_blackout:
            is_favorable = False
            event_names = ", ".join(macro_status.event_names[:3])
            unfavorable_reasons.append(
                f"US宏观事件黑名单期: {event_names} 将于 {macro_status.blackout_days} 天内发布"
            )

        # 波动率检查 (VHSI)
        if vol_status and vol_status.filter_status == FilterStatus.UNFAVORABLE:
            is_favorable = False
            if vol_status.value < hk_config.vhsi_range[0]:
                unfavorable_reasons.append(
                    f"VHSI={vol_status.value:.1f} 偏低（<{hk_config.vhsi_range[0]}），"
                    f"权利金不足"
                )
            elif vol_status.value > hk_config.vhsi_range[1]:
                unfavorable_reasons.append(
                    f"VHSI={vol_status.value:.1f} 过高（>{hk_config.vhsi_range[1]}），"
                    f"风险过大"
                )
            # 检查 percentile 超出范围的情况
            elif vol_status.percentile is not None:
                pct_low, pct_high = hk_config.vhsi_percentile_range
                if vol_status.percentile < pct_low:
                    unfavorable_reasons.append(
                        f"VHSI Percentile={vol_status.percentile*100:.1f}% 偏低"
                        f"（<{pct_low*100:.0f}%），历史低位"
                    )
                elif vol_status.percentile > pct_high:
                    unfavorable_reasons.append(
                        f"VHSI Percentile={vol_status.percentile*100:.1f}% 过高"
                        f"（>{pct_high*100:.0f}%），恐慌情绪"
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
            macro_events=macro_status,  # 复用 US 宏观事件检查
            unfavorable_reasons=unfavorable_reasons,
        )

    def _get_vix_status(self, config: USMarketConfig) -> VolatilityIndexStatus | None:
        """获取 VIX 状态

        数据来源：UnifiedDataProvider.get_macro_data()
        指标计算：engine.sentiment.vix 模块
        """
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=365)

            # 从 data_layer 获取 VIX 历史数据
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

            # 调用 engine_layer 计算百分位
            historical_values = [d.close for d in macro_data if d.close is not None]
            percentile = calc_vix_percentile(current_vix, historical_values)
            if percentile is not None:
                percentile = percentile / 100.0  # 转为 0-1 范围

            # 调用 engine_layer 判断 VIX 区域
            vix_zone = get_vix_zone(current_vix)

            # 映射到业务层 VolatilityStatus
            zone_to_status = {
                "low": VolatilityStatus.LOW,
                "normal": VolatilityStatus.NORMAL,
                "elevated": VolatilityStatus.HIGH,
                "high": VolatilityStatus.HIGH,
                "extreme": VolatilityStatus.EXTREME,
            }
            status = zone_to_status.get(vix_zone.value, VolatilityStatus.NORMAL)

            # 业务层判断：是否在配置范围内
            vix_low, vix_high = config.vix_range
            if vix_low <= current_vix <= vix_high:
                filter_status = FilterStatus.FAVORABLE
            else:
                filter_status = FilterStatus.UNFAVORABLE

            # 额外检查百分位范围
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
        """获取港股波动率状态

        数据来源：Yahoo Finance VHSI (^HSIL) - 恒生波动率指数
        类似 VIX，通过 get_macro_data() 获取历史数据并计算百分位
        """
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=365)

            # 从 Yahoo Finance 获取 VHSI 历史数据
            macro_data = self.provider.get_macro_data(
                config.vhsi_symbol,  # ^HSIL
                start_date,
                end_date,
            )

            if not macro_data:
                logger.warning(f"无法获取 VHSI ({config.vhsi_symbol}) 数据")
                return None

            current_vhsi = macro_data[-1].close if macro_data else None
            if current_vhsi is None:
                return None

            # 计算百分位
            historical_values = [d.close for d in macro_data if d.close is not None]
            percentile = calc_vix_percentile(current_vhsi, historical_values)
            if percentile is not None:
                percentile = percentile / 100.0  # 转为 0-1 范围

            # 判断 VHSI 区域 (复用 VIX 区域逻辑)
            vhsi_zone = get_vix_zone(current_vhsi)
            zone_to_status = {
                "low": VolatilityStatus.LOW,
                "normal": VolatilityStatus.NORMAL,
                "elevated": VolatilityStatus.HIGH,
                "high": VolatilityStatus.HIGH,
                "extreme": VolatilityStatus.EXTREME,
            }
            status = zone_to_status.get(vhsi_zone.value, VolatilityStatus.NORMAL)

            # 业务层判断：是否在配置范围内
            vhsi_low, vhsi_high = config.vhsi_range
            if vhsi_low <= current_vhsi <= vhsi_high:
                filter_status = FilterStatus.FAVORABLE
            else:
                filter_status = FilterStatus.UNFAVORABLE

            # 额外检查百分位范围
            if percentile is not None:
                pct_low, pct_high = config.vhsi_percentile_range
                if not (pct_low <= percentile <= pct_high):
                    filter_status = FilterStatus.UNFAVORABLE

            return VolatilityIndexStatus(
                symbol=config.vhsi_symbol,
                value=current_vhsi,
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

        数据来源：UnifiedDataProvider.get_history_kline()
        指标计算：engine.sentiment.trend 模块

        Args:
            indices: 指数列表 [(symbol, weight), ...]

        Returns:
            (IndexStatus列表, 整体趋势)
        """
        index_statuses: list[IndexStatus] = []
        weighted_scores: list[tuple[float, float]] = []  # (score, weight)

        end_date = date.today()
        start_date = end_date - timedelta(days=300)  # 足够计算 SMA200

        for symbol, weight in indices:
            try:
                # 从 data_layer 获取历史 K 线
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

                # 调用 engine_layer 计算均线
                sma20 = calc_sma(closes, 20)
                sma50 = calc_sma(closes, 50)
                sma200 = calc_sma(closes, 200) if len(closes) >= 200 else None

                # 调用 engine_layer 判断趋势
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

        # 业务层：计算加权平均趋势
        if weighted_scores:
            total_weight = sum(w for _, w in weighted_scores)
            if total_weight > 0:
                avg_score = sum(s * w for s, w in weighted_scores) / total_weight
            else:
                avg_score = 0.0
        else:
            avg_score = 0.0

        # 业务层：映射到趋势状态
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
        """获取 VIX 期限结构状态

        数据来源：UnifiedDataProvider.get_macro_data()
        指标计算：engine.sentiment.term_structure 模块
        """
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=5)

            # 从 data_layer 获取 VIX 和 VIX3M 数据
            vix_data = self.provider.get_macro_data(
                config.vix_symbol,
                start_date,
                end_date,
            )

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

            # 调用 engine_layer 计算期限结构
            ts_result = calc_term_structure(vix_value, vix3m_value)
            if ts_result is None:
                return None

            # 业务层判断过滤状态
            if ts_result.ratio >= config.term_structure_threshold:
                filter_status = FilterStatus.UNFAVORABLE
            elif ts_result.state == TermStructure.CONTANGO:
                filter_status = FilterStatus.FAVORABLE
            else:
                filter_status = FilterStatus.NEUTRAL

            return TermStructureStatus(
                vix_value=ts_result.vix,
                vix3m_value=ts_result.vix3m,
                ratio=ts_result.ratio,
                is_contango=(ts_result.state == TermStructure.CONTANGO),
                filter_status=filter_status,
            )

        except Exception as e:
            logger.error(f"获取期限结构状态失败: {e}")
            return None

    # _get_pcr_status 已删除: PCR 0.8-1.2 是常态震荡无过滤价值

    def _check_macro_events(
        self,
        config: MacroEventConfig,
    ) -> MacroEventStatus | None:
        """检查宏观事件黑名单期

        检查未来 N 天内是否有重大宏观事件（FOMC、CPI、NFP等）。
        如果有，建议暂停新开仓。

        数据来源：UnifiedDataProvider.check_macro_blackout()

        Args:
            config: 宏观事件配置

        Returns:
            MacroEventStatus 或 None（如果检查失败或未启用）
        """
        if not config.enabled:
            logger.debug("宏观事件检查已禁用")
            return None

        try:
            # 调用 data_layer 检查黑名单期
            is_in_blackout, events = self.provider.check_macro_blackout(
                target_date=date.today(),
                blackout_days=config.blackout_days,
                blackout_events=config.blackout_events,
            )

            if is_in_blackout:
                event_info = [f"{e.name} ({e.event_date})" for e in events[:3]]
                logger.warning(
                    f"宏观事件黑名单期: {', '.join(event_info)}"
                )

            return MacroEventStatus(
                is_in_blackout=is_in_blackout,
                upcoming_events=events,
                blackout_days=config.blackout_days,
            )

        except Exception as e:
            logger.error(f"检查宏观事件失败: {e}")
            # 失败时采用 fail-open 策略，不阻止开仓
            return MacroEventStatus(
                is_in_blackout=False,
                upcoming_events=[],
                blackout_days=config.blackout_days,
            )
