"""
Underlying Filter - 标的过滤器

第二层筛选：评估单个标的是否适合期权卖方策略

检查项目：
- IV Rank >= 30% (P1 阻塞，卖方必须卖"贵"的东西)
- IV/HV 比率在合理范围 (P1 阻塞)
- 技术面（RSI、布林带、均线排列）(P2/P3 警告)
- 基本面（可选）(P3 警告)

架构说明：
- 数据获取：调用 data_layer (UnifiedDataProvider)
- 指标计算：调用 engine_layer (technical, volatility 模块)
- 业务逻辑：本模块专注业务判断和编排
"""

import logging
from datetime import date, timedelta

from src.business.config.screening_config import (
    EventCalendarConfig,
    FundamentalConfig,
    ScreeningConfig,
    TechnicalConfig,
)
from src.business.screening.models import (
    FundamentalScore,
    MarketType,
    TechnicalScore,
    UnderlyingScore,
)
from src.data.models.stock import KlineType
from src.data.models.technical import TechnicalData
from src.data.providers.base import DataProvider
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.position.technical.metrics import (
    calc_technical_score,
    calc_technical_signal,
)
from src.engine.position.volatility.metrics import (
    get_iv_hv_ratio,
    get_iv_rank,
)

logger = logging.getLogger(__name__)


class UnderlyingFilter:
    """标的过滤器

    根据配置检查单个标的是否适合开仓：
    1. IV Rank 在合适范围内（>= min_iv_rank）
    2. IV/HV 比率合理（min_iv_hv_ratio <= ratio <= max_iv_hv_ratio）
    3. 技术面信号有利（RSI 企稳、均线排列等）
    4. 基本面检查（可选，如 PE 百分位、分析师评级等）

    架构职责：
    - data_layer: UnifiedDataProvider 提供原始数据
    - engine_layer: technical/volatility 模块提供指标计算
    - business_layer: 本模块进行业务判断和编排

    使用方式：
        filter = UnderlyingFilter(config, provider)
        scores = filter.evaluate(symbols, MarketType.US)
        for score in scores:
            if score.passed:
                # 继续筛选合约
    """

    def __init__(
        self,
        config: ScreeningConfig,
        provider: DataProvider | None = None,
    ) -> None:
        """初始化标的过滤器

        Args:
            config: 筛选配置
            provider: 数据提供者 (DataProvider 或其子类)，默认创建 UnifiedDataProvider
        """
        self.config = config
        self.provider: DataProvider = provider or UnifiedDataProvider()

    def _get_reference_date(self) -> date:
        """获取参考日期（回测兼容）

        在回测模式下，provider 会有 as_of_date 属性，表示当前模拟的日期。
        实盘模式下，使用 date.today()。
        """
        if hasattr(self.provider, "as_of_date"):
            return self.provider.as_of_date
        return date.today()

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

        for idx, symbol in enumerate(symbols, 1):
            try:
                logger.info(f"正在评估标的 {idx}/{len(symbols)}: {symbol}")
                score = self._evaluate_single(symbol, market_type)
                results.append(score)

                # 输出详细评估结果
                self._log_evaluation_result(score)

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

        # 输出汇总统计
        passed = sum(1 for s in results if s.passed)
        failed = len(results) - passed
        logger.info(f"标的评估汇总: 通过={passed}, 淘汰={failed}")

        return results

    def _log_evaluation_result(self, score: UnderlyingScore) -> None:
        """输出单个标的的详细评估结果"""
        status = "PASS" if score.passed else "FAIL"

        # 波动率指标
        iv_rank_str = f"{score.iv_rank:.1f}%" if score.iv_rank is not None else "N/A"
        iv_hv_str = f"{score.iv_hv_ratio:.2f}" if score.iv_hv_ratio is not None else "N/A"
        iv_str = f"{score.current_iv*100:.1f}%" if score.current_iv is not None else "N/A"
        hv_str = f"{score.hv_20*100:.1f}%" if score.hv_20 is not None else "N/A"

        # 技术面指标
        rsi_str = "N/A"
        adx_str = "N/A"
        sma_str = "N/A"
        if score.technical:
            if score.technical.rsi is not None:
                rsi_str = f"{score.technical.rsi:.1f} ({score.technical.rsi_zone})"
            if score.technical.adx is not None:
                # 显示 ADX 和方向指标
                plus_di = score.technical.plus_di
                minus_di = score.technical.minus_di
                if plus_di is not None and minus_di is not None:
                    trend_dir = "↑" if plus_di > minus_di else "↓" if minus_di > plus_di else "→"
                    adx_str = f"{score.technical.adx:.1f}{trend_dir} (+DI={plus_di:.1f}/-DI={minus_di:.1f})"
                else:
                    adx_str = f"{score.technical.adx:.1f}"
            if score.technical.sma_alignment:
                sma_str = score.technical.sma_alignment

        # 价格
        price_str = f"${score.current_price:.2f}" if score.current_price else "N/A"

        # 主日志行
        logger.info(
            f"[{status}] {score.symbol}: "
            f"Price={price_str}, "
            f"IV Rank={iv_rank_str}, "
            f"IV/HV={iv_hv_str} (IV={iv_str}, HV={hv_str}), "
            f"RSI={rsi_str}, ADX={adx_str}, SMA={sma_str}"
        )

        # 淘汰原因
        if score.disqualify_reasons:
            for reason in score.disqualify_reasons:
                logger.info(f"    └─ {reason}")

        # 警告信息
        if score.warnings:
            for warning in score.warnings:
                logger.info(f"    └─ {warning}")

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
        """评估单个标的（内部实现）

        优先级说明：
        - P0/P1 条件阻塞标的选择（disqualify_reasons）
        - P2/P3 条件只警告不阻塞（warnings）

        P1 阻塞条件：
        - IV Rank < 30%（卖方策略必须卖"贵"的东西）
        - 波动率数据缺失
        - IV/HV 比率超出范围（期权相对便宜或可能有特殊事件）
        - 财报日期 < 7天（且不允许跨财报）

        P2/P3 警告条件：
        - RSI 超买/超卖
        - ADX 过高
        - 均线空头排列
        - PE 百分位过高
        - 分析师评级偏低
        - 除息日临近
        """
        filter_config = self.config.underlying_filter
        disqualify_reasons: list[str] = []  # P0/P1 阻塞条件
        warnings: list[str] = []  # P2/P3 警告条件

        # 从 data_layer 获取当前价格
        logger.debug(f"获取 {symbol} 当前价格...")
        current_price = self._get_current_price(symbol)

        # 1. 从 data_layer 获取波动率数据
        logger.debug(f"获取 {symbol} 波动率数据...")
        vol_data = self._get_volatility_data(symbol)
        iv_rank = None
        iv_hv_ratio = None
        hv_20 = None
        current_iv = None

        if vol_data:
            # 调用 engine_layer 计算指标
            iv_rank = get_iv_rank(vol_data)
            iv_hv_ratio = get_iv_hv_ratio(vol_data)
            hv_20 = vol_data.hv
            current_iv = vol_data.iv

            # P1: IV Rank 检查（阻塞，卖方策略必须卖"贵"的东西）
            # 使用动态阈值（与 VIX 挂钩）
            iv_rank_threshold = self._get_dynamic_iv_rank_threshold(market_type)
            if iv_rank is not None and iv_rank < iv_rank_threshold:
                disqualify_reasons.append(
                    f"[P1] IV Rank={iv_rank:.1f}% 不足（<{iv_rank_threshold:.0f}%），"
                    f"期权不够'贵'"
                )

            # P1: IV/HV 比率检查（阻塞）
            if iv_hv_ratio is not None:
                if iv_hv_ratio < filter_config.min_iv_hv_ratio:
                    disqualify_reasons.append(
                        f"[P1] IV/HV={iv_hv_ratio:.2f} 偏低（<{filter_config.min_iv_hv_ratio}），"
                        f"期权相对便宜"
                    )
                elif iv_hv_ratio > filter_config.max_iv_hv_ratio:
                    disqualify_reasons.append(
                        f"[P1] IV/HV={iv_hv_ratio:.2f} 过高（>{filter_config.max_iv_hv_ratio}），"
                        f"可能有特殊事件"
                    )
        else:
            # P1: 波动率数据缺失（阻塞）
            disqualify_reasons.append("[P1] 无法获取波动率数据")

        # 2. 获取技术面评分（P2/P3 只警告）
        logger.debug(f"评估 {symbol} 技术面...")
        technical = self._evaluate_technical(symbol, filter_config.technical)
        tech_warnings = self._check_technical(technical, filter_config.technical)
        warnings.extend(tech_warnings)

        # 3. 获取基本面数据（只获取一次）
        fundamental_data = None
        if filter_config.fundamental.enabled or filter_config.event_calendar.enabled:
            logger.debug(f"获取 {symbol} 基本面数据...")
            fundamental_data = self.provider.get_fundamental(symbol)

        # 4. 评估基本面（P3 只警告）
        fundamental = None
        if filter_config.fundamental.enabled:
            logger.debug(f"评估 {symbol} 基本面...")
            fundamental = self._evaluate_fundamental_with_data(
                symbol, filter_config.fundamental, fundamental_data
            )
            fund_warnings = self._check_fundamental(fundamental, filter_config.fundamental)
            warnings.extend(fund_warnings)

        # 5. 检查事件日历（财报日、除息日）
        earnings_date = None
        ex_dividend_date = None
        days_to_earnings = None
        days_to_ex_dividend = None

        if filter_config.event_calendar.enabled:
            logger.debug(f"检查 {symbol} 事件日历...")
            event_result = self._check_event_calendar_with_data(
                symbol, filter_config.event_calendar, fundamental_data
            )
            if event_result:
                earnings_date = event_result.get("earnings_date")
                ex_dividend_date = event_result.get("ex_dividend_date")
                days_to_earnings = event_result.get("days_to_earnings")
                days_to_ex_dividend = event_result.get("days_to_ex_dividend")
                # P1: 财报日期阻塞
                event_disqualify = event_result.get("disqualify_reasons", [])
                disqualify_reasons.extend(event_disqualify)
                # P2: 除息日警告
                event_warnings = event_result.get("warnings", [])
                warnings.extend(event_warnings)

        # 综合判断：只有 disqualify_reasons 非空才阻塞
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
            earnings_date=earnings_date,
            ex_dividend_date=ex_dividend_date,
            days_to_earnings=days_to_earnings,
            days_to_ex_dividend=days_to_ex_dividend,
            disqualify_reasons=disqualify_reasons,
            warnings=warnings,
        )

    def _get_current_price(self, symbol: str) -> float | None:
        """获取当前价格

        数据来源：UnifiedDataProvider.get_stock_quote()
        """
        try:
            quote = self.provider.get_stock_quote(symbol)
            if quote and hasattr(quote, "close") and quote.close:
                return quote.close
            return None
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格失败: {e}")
            return None

    def _get_current_vix(self, symbol: str) -> float | None:
        """获取当前波动率指数值

        Args:
            symbol: VIX symbol (^VIX for US, ^HSIL for HK)

        Returns:
            当前 VIX 值或 None
        """
        try:
            # 使用统一的参考日期（回测兼容）
            end_date = self._get_reference_date()
            start_date = end_date - timedelta(days=5)

            macro_data = self.provider.get_macro_data(symbol, start_date, end_date)
            if macro_data and len(macro_data) > 0:
                return macro_data[-1].close
            return None
        except Exception as e:
            logger.warning(f"获取 {symbol} VIX 失败: {e}")
            return None

    def _get_dynamic_iv_rank_threshold(self, market_type: MarketType) -> float:
        """计算动态 IV Rank 阈值（与波动率指数挂钩）

        规则：
        - VIX < 15: 返回 20%（低波环境，降低门槛以捕捉机会）
        - VIX 15-20: 返回 25%
        - VIX 20-25: 返回 30%（默认）
        - VIX > 25: 返回 35%（高波环境，提高门槛以保证质量）

        Args:
            market_type: 市场类型

        Returns:
            动态 IV Rank 阈值（0-100 scale）
        """
        # 获取当前波动率指数
        if market_type == MarketType.US:
            vix = self._get_current_vix("^VIX")
        else:
            vix = self._get_current_vix("^HSIL")  # 恒生波幅指数

        if vix is None:
            # 无法获取 VIX，使用配置的默认值
            default_threshold = self.config.underlying_filter.min_iv_rank
            logger.debug(f"无法获取 VIX，使用默认阈值 {default_threshold}%")
            return default_threshold

        # 动态阈值计算
        if vix < 15:
            threshold = 20.0
        elif vix < 20:
            threshold = 25.0
        elif vix < 25:
            threshold = 30.0
        else:
            threshold = 35.0

        logger.debug(f"VIX={vix:.1f} → 动态 IV Rank 阈值={threshold}%")
        return threshold

    def _get_volatility_data(self, symbol: str) -> object | None:
        """获取波动率数据

        数据来源：UnifiedDataProvider.get_stock_volatility() (IBKR)
        """
        try:
            return self.provider.get_stock_volatility(symbol)
        except Exception as e:
            logger.warning(f"获取 {symbol} 波动率数据失败: {e}")
            return None

    def _evaluate_technical(
        self,
        symbol: str,
        config: TechnicalConfig,  # noqa: ARG002
    ) -> TechnicalScore | None:
        """评估技术面

        数据来源：UnifiedDataProvider.get_history_kline()
        指标计算：engine.position.technical.metrics 模块
        """
        try:
            end_date = self._get_reference_date()
            start_date = end_date - timedelta(days=300)  # 足够计算技术指标

            # 从 data_layer 获取 K 线数据
            klines = self.provider.get_history_kline(
                symbol,
                KlineType.DAY,
                start_date,
                end_date,
            )

            if not klines or len(klines) < 50:
                logger.warning(f"{symbol} 历史数据不足")
                return None

            # 构建 TechnicalData（engine_layer 的输入格式）
            tech_data = TechnicalData.from_klines(klines)

            # 调用 engine_layer 计算技术评分和信号
            score = calc_technical_score(tech_data)
            _ = calc_technical_signal(tech_data)  # 信号用于日志/调试

            # 业务层：映射 RSI zone
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

            # 业务层：计算距离支撑位的百分比
            support_distance = None
            if score.support and score.current_price:
                support_distance = (score.current_price - score.support) / score.support * 100

            return TechnicalScore(
                rsi=score.rsi,
                rsi_zone=rsi_zone,
                bb_percent_b=score.bb_percent_b,
                adx=score.adx,
                plus_di=score.plus_di,  # 新增: +DI 方向指数
                minus_di=score.minus_di,  # 新增: -DI 方向指数
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
        """检查技术面是否符合条件（业务层判断）

        注意：技术面检查都是 P2/P3 级别，只返回警告不阻塞。
        """
        warnings: list[str] = []

        if technical is None:
            return warnings  # 技术面数据缺失不作为警告条件

        # P2: RSI 检查（策略区分）
        # Short Put: RSI 25-70, Covered Call: RSI 30-85
        if technical.rsi is not None:
            rsi = technical.rsi

            # RSI > 85: 极度超买，禁止卖 Call（可能逼空）
            if rsi > 85:
                warnings.append(
                    f"[P1] RSI={rsi:.1f} 极度超买（>85），卖 Call 风险极高"
                )
            # RSI < 25: 极度超卖，仅适合 Short Put
            elif rsi < 25:
                warnings.append(
                    f"[P2] RSI={rsi:.1f} 极度超卖（<25），仅适合 Short Put"
                )
            # RSI 25-30: 超卖区，Short Put 可行，Covered Call 需谨慎
            elif rsi < 30:
                warnings.append(
                    f"[P2] RSI={rsi:.1f} 超卖区，Short Put 可行，Covered Call 需谨慎"
                )
            # RSI 70-85: 超买区，Covered Call 仍可行，Short Put 需谨慎
            elif rsi > 70:
                warnings.append(
                    f"[P2] RSI={rsi:.1f} 超买区，Short Put 需谨慎"
                )

        # P2: ADX 检查（趋势过强不利于期权卖方）
        if technical.adx is not None:
            if technical.adx > config.max_adx:
                warnings.append(f"[P2] ADX={technical.adx:.1f} 过高（>{config.max_adx}），趋势过强")
            elif technical.adx >= 25:
                # ADX >= 25 表示趋势市，添加方向信息
                plus_di = technical.plus_di
                minus_di = technical.minus_di
                if plus_di is not None and minus_di is not None:
                    if minus_di > plus_di:
                        # 强下跌趋势: 禁止卖 Put，但允许卖 Call
                        warnings.append(
                            f"[P2] 强下跌趋势 ADX={technical.adx:.1f} "
                            f"(+DI={plus_di:.1f} < -DI={minus_di:.1f})，卖 Put 风险高"
                        )
                    elif plus_di > minus_di:
                        # 强上涨趋势: 禁止卖 Call，但允许卖 Put
                        warnings.append(
                            f"[P2] 强上涨趋势 ADX={technical.adx:.1f} "
                            f"(+DI={plus_di:.1f} > -DI={minus_di:.1f})，卖 Call 风险高"
                        )

        # P3: 均线排列检查
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
                    warnings.append(
                        f"[P3] 均线排列为 {current_alignment}，"
                        f"需至少 {min_alignment}"
                    )

        return warnings

    def _evaluate_fundamental_with_data(
        self,
        symbol: str,
        config: FundamentalConfig,  # noqa: ARG002
        fundamental_data: object | None = None,
    ) -> FundamentalScore | None:
        """评估基本面（使用预获取的数据）

        数据来源：UnifiedDataProvider.get_fundamental() (Yahoo)

        Args:
            symbol: 标的代码
            config: 基本面配置
            fundamental_data: 预获取的基本面数据（如提供则使用，否则重新获取）

        Returns:
            FundamentalScore 或 None
        """
        try:
            # 使用预获取的数据，避免重复调用
            if fundamental_data is None:
                fundamental_data = self.provider.get_fundamental(symbol)

            if fundamental_data is None:
                return None

            fundamental = fundamental_data

            # 提取关键指标
            pe_ratio = getattr(fundamental, "pe_ratio", None)
            revenue_growth = getattr(fundamental, "revenue_growth", None)
            recommendation = getattr(fundamental, "recommendation", None)

            # 业务层：计算 PE 百分位（简化处理）
            pe_percentile = None
            if pe_ratio is not None:
                # 简化假设：PE 在 10-30 之间为正常
                if pe_ratio < 10:
                    pe_percentile = 0.1
                elif pe_ratio > 30:
                    pe_percentile = 0.9
                else:
                    pe_percentile = (pe_ratio - 10) / 20

            # 业务层：映射推荐评级
            rec_map = {
                "strong_buy": "strong_buy",
                "buy": "buy",
                "hold": "hold",
                "sell": "sell",
                "strong_sell": "strong_sell",
            }
            rec = rec_map.get(recommendation, None)

            # 业务层：计算综合评分
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
        """检查基本面是否符合条件（业务层判断）

        注意：基本面检查都是 P3 级别，只返回警告不阻塞。
        """
        warnings: list[str] = []

        if fundamental is None:
            return warnings  # 基本面数据缺失不作为警告条件

        # P3: PE 百分位检查
        if fundamental.pe_percentile is not None:
            if fundamental.pe_percentile > config.max_pe_percentile:
                warnings.append(
                    f"[P3] PE 百分位={fundamental.pe_percentile:.1%} 过高"
                    f"（>{config.max_pe_percentile:.0%}），估值偏贵"
                )

        # P3: 推荐评级检查
        if fundamental.recommendation is not None:
            rec_order = ["strong_buy", "buy", "hold", "sell", "strong_sell"]
            min_rec = config.min_recommendation
            if min_rec in rec_order and fundamental.recommendation in rec_order:
                min_idx = rec_order.index(min_rec)
                current_idx = rec_order.index(fundamental.recommendation)
                if current_idx > min_idx:
                    warnings.append(
                        f"[P3] 分析师评级为 {fundamental.recommendation}，"
                        f"需至少 {min_rec}"
                    )

        return warnings

    def _check_event_calendar_with_data(
        self,
        symbol: str,
        config: EventCalendarConfig,
        fundamental_data: object | None = None,
    ) -> dict | None:
        """检查事件日历（财报日、除息日）（使用预获取的数据）

        检查标的是否有即将发布的财报或除息日。

        优先级说明：
        - P1: 财报日期 < min_days_to_earnings（阻塞，放入 disqualify_reasons）
        - P2: 除息日期 < min_days_to_ex_dividend（警告，放入 warnings）

        数据来源：UnifiedDataProvider.get_fundamental() (包含 earnings_date, ex_dividend_date)

        Args:
            symbol: 标的代码
            config: 事件日历配置
            fundamental_data: 预获取的基本面数据（如提供则使用，否则重新获取）

        Returns:
            包含 earnings_date, ex_dividend_date, days_to_*, disqualify_reasons, warnings 的字典
        """
        result = {
            "earnings_date": None,
            "ex_dividend_date": None,
            "days_to_earnings": None,
            "days_to_ex_dividend": None,
            "disqualify_reasons": [],  # P1 阻塞
            "warnings": [],  # P2 警告
        }

        try:
            # 使用预获取的数据，避免重复调用
            if fundamental_data is None:
                fundamental_data = self.provider.get_fundamental(symbol)

            if fundamental_data is None:
                logger.debug(f"{symbol} 无法获取基本面数据用于事件日历检查")
                return result

            fundamental = fundamental_data

            today = self._get_reference_date()

            # P1: 检查财报日期（阻塞）
            if hasattr(fundamental, "earnings_date") and fundamental.earnings_date:
                earnings_date = fundamental.earnings_date
                result["earnings_date"] = earnings_date

                # 计算距财报天数（只考虑未来的财报）
                if earnings_date >= today:
                    days_to_earnings = (earnings_date - today).days
                    result["days_to_earnings"] = days_to_earnings

                    # 业务层判断：检查是否在黑名单期内
                    if days_to_earnings < config.min_days_to_earnings:
                        # 如果配置允许在财报前到期的合约，这里只记录警告
                        # 实际的合约层面检查在 ContractFilter 中进行
                        if not config.allow_earnings_if_before_expiry:
                            result["disqualify_reasons"].append(
                                f"[P1] 财报日 {earnings_date} 仅剩 {days_to_earnings} 天"
                                f"（<{config.min_days_to_earnings}）"
                            )
                        else:
                            logger.info(
                                f"{symbol} 财报日 {earnings_date} 仅剩 {days_to_earnings} 天，"
                                f"允许合约在财报前到期"
                            )

            # P2: 检查除息日期（只警告，不阻塞）
            if hasattr(fundamental, "ex_dividend_date") and fundamental.ex_dividend_date:
                ex_div_date = fundamental.ex_dividend_date
                result["ex_dividend_date"] = ex_div_date

                # 计算距除息日天数（只考虑未来的除息日）
                if ex_div_date >= today:
                    days_to_ex_div = (ex_div_date - today).days
                    result["days_to_ex_dividend"] = days_to_ex_div

                    # 业务层判断：除息日对 Covered Call 有影响
                    # P2 级别，只警告不阻塞
                    if days_to_ex_div < config.min_days_to_ex_dividend:
                        result["warnings"].append(
                            f"[P2] 除息日 {ex_div_date} 仅剩 {days_to_ex_div} 天"
                            f"（<{config.min_days_to_ex_dividend}），Covered Call 需注意"
                        )

            return result

        except Exception as e:
            logger.warning(f"检查 {symbol} 事件日历失败: {e}")
            return result

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
