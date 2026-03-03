"""
Screening Pipeline - 筛选管道

整合三层筛选器，形成完整的筛选流程：
1. 市场环境过滤 -> 如果不利则中止
2. 标的过滤 -> 筛选合格标的
3. 合约过滤 -> 筛选合格合约

架构说明：
- 数据获取：通过 UnifiedDataProvider 统一获取
- 指标计算：各 Filter 调用 engine_layer
- 业务逻辑：Pipeline 负责流程编排

使用方式：
    pipeline = ScreeningPipeline(config, provider)
    result = pipeline.run(
        symbols=["AAPL", "MSFT", "GOOGL"],
        market_type=MarketType.US,
        strategy_type=StrategyType.SHORT_PUT,
    )
"""

import logging
from datetime import date, datetime

from src.business.config.screening_config import (
    ScreeningConfig,
    ContractFilterConfig,
    UnderlyingFilterConfig,
)
from src.business.screening.filters.contract_filter import ContractFilter
from src.business.screening.filters.market_filter import MarketFilter
from src.business.screening.filters.underlying_filter import UnderlyingFilter
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    MarketType,
    ScreeningResult,
    UnderlyingScore,
)
from src.data.models.option import OptionContract, OptionType
from src.data.providers.base import DataProvider
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.models.enums import StrategyType

logger = logging.getLogger(__name__)


class ScreeningPipeline:
    """筛选管道

    整合三层筛选器，执行完整的筛选流程。

    流程：
    1. 市场环境评估 - 检查 VIX、大盘趋势、期限结构等
    2. 标的评估 - 检查 IV Rank、技术面、基本面等
    3. 合约评估 - 检查 DTE、Delta、流动性、策略指标等

    架构职责：
    - data_layer: UnifiedDataProvider 统一提供数据
    - engine_layer: 各 Filter 内部调用计算模块
    - business_layer: Pipeline 编排筛选流程
    """

    def __init__(
        self,
        config: ScreeningConfig,
        provider: DataProvider | None = None,
        kelly_fraction: float = 0.25,
    ) -> None:
        """初始化筛选管道

        Args:
            config: 筛选配置
            provider: 数据提供者 (DataProvider 或其子类)，默认创建 UnifiedDataProvider
            kelly_fraction: Kelly 仓位系数 (默认 0.25 = 1/4 Kelly)
        """
        self.config = config
        self.provider: DataProvider = provider or UnifiedDataProvider()

        # 初始化各层过滤器，共享同一个 provider
        self.market_filter = MarketFilter(config, self.provider)
        self.underlying_filter = UnderlyingFilter(config, self.provider)
        self.contract_filter = ContractFilter(config, self.provider, kelly_fraction=kelly_fraction)

    def run(
        self,
        symbols: list[str],
        market_type: MarketType,
        strategy_type: StrategyType = StrategyType.SHORT_PUT,
        skip_market_check: bool = False,
    ) -> ScreeningResult:
        """执行完整筛选流程

        Args:
            symbols: 待筛选标的列表
            market_type: 市场类型 (US/HK)
            strategy_type: 策略类型 (StrategyType.SHORT_PUT 或 StrategyType.COVERED_CALL)
            skip_market_check: 是否跳过市场环境检查（调试用）

        Returns:
            ScreeningResult: 筛选结果
        """
        logger.info(
            f"开始筛选: 市场={market_type.value}, 策略={strategy_type.value}, "
            f"标的数量={len(symbols)}"
        )
        start_time = datetime.now()

        # 获取方向特定的合约筛选参数
        contract_filter_config = self.config.get_contract_filter(strategy_type)
        underlying_filter_config = self.config.get_underlying_filter(strategy_type)
        market_filter_config = self.config.get_market_filter(strategy_type)

        logger.debug(
            f"方向 {strategy_type.value} 使用 Delta 范围: {contract_filter_config.delta_range}"
        )

        # 1. 市场环境评估
        market_status: MarketStatus | None = None
        if not skip_market_check:
            logger.info("Step 1: 评估市场环境...")
            market_status = self.market_filter.evaluate(market_type, filter_config=market_filter_config)

            # 输出详细市场状态
            self._log_market_status(market_status)

            if not market_status.is_favorable:
                logger.warning(
                    f"市场环境不利: {', '.join(market_status.unfavorable_reasons)}"
                )
                return ScreeningResult(
                    passed=False,
                    strategy_type=strategy_type,
                    market_status=market_status,
                    scanned_underlyings=0,
                    rejection_reason="市场环境不利: "
                    + "; ".join(market_status.unfavorable_reasons),
                )

            logger.info("✅ 市场环境有利，继续筛选")
        else:
            logger.info("Step 1: 跳过市场环境检查")

        # 2. 标的评估
        logger.info(f"Step 2: 评估标的 ({len(symbols)} 个)...")
        overall_trend = market_status.overall_trend if market_status else None
        underlying_scores = self.underlying_filter.evaluate(
            symbols, market_type,
            trend_status=overall_trend,
            strategy_type=strategy_type,
            filter_config=underlying_filter_config,  # 传入方向特定的配置
        )

        passed_underlyings = [s for s in underlying_scores if s.passed]
        logger.info(
            f"标的筛选完成: {len(passed_underlyings)}/{len(symbols)} 通过"
        )

        if not passed_underlyings:
            return ScreeningResult(
                passed=False,
                strategy_type=strategy_type,
                market_status=market_status,
                underlying_scores=underlying_scores,
                scanned_underlyings=len(symbols),
                passed_underlyings=0,
                rejection_reason="无标的通过筛选",
            )

        # 按评分排序
        passed_underlyings = self.underlying_filter.sort_by_score(passed_underlyings)

        # 3. 合约评估
        logger.info(f"Step 3: 评估合约 ({len(passed_underlyings)} 个标的)...")

        # 根据策略类型确定要评估的期权类型
        if strategy_type == StrategyType.SHORT_PUT:
            option_types = ["put"]
        elif strategy_type == StrategyType.COVERED_CALL:
            option_types = ["call"]
        else:
            option_types = None  # 评估所有类型

        # 使用方向特定的合约筛选参数
        all_evaluated = self.contract_filter.evaluate(
            passed_underlyings,
            option_types=option_types,
            return_rejected=True,
            filter_config=contract_filter_config,  # 传入方向特定的配置
        )

        # 统计实际评估数量并筛选出通过的（Step1 候选）
        total_evaluated = len(all_evaluated)
        candidates = [o for o in all_evaluated if o.passed]

        logger.info(
            f"Step 3 完成: {len(candidates)}/{total_evaluated} 个候选"
        )

        # 4. 二次确认 - 重新获取数据并评估候选合约
        confirmed: list[ContractOpportunity] = []
        if candidates:
            logger.info(f"Step 4: 二次确认 ({len(candidates)} 个候选)...")

            confirmed = self._confirm_candidates(
                candidates=candidates,
                passed_underlyings=passed_underlyings,
                option_types=option_types,
                market_type=market_type,
                filter_config=contract_filter_config,  # 传入方向特定的配置
            )

            logger.info(f"确认完成: {len(confirmed)}/{len(candidates)} 通过")

            # 输出确认结果详情
            for c in candidates:
                key = (c.symbol, c.expiry, c.strike, c.option_type)
                is_confirmed = any(
                    (x.symbol, x.expiry, x.strike, x.option_type) == key
                    for x in confirmed
                )
                status = "✅" if is_confirmed else "❌"
                logger.debug(
                    f"   {status} {c.symbol} {c.option_type.upper()} {c.strike} "
                    f"@{c.expiry} (E[ROC]={c.expected_roc:.1%})"
                )

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"筛选完成: {len(confirmed)} 个确认机会, 耗时 {elapsed:.1f}s"
        )

        return ScreeningResult(
            passed=len(confirmed) > 0,
            strategy_type=strategy_type,
            market_status=market_status,
            opportunities=all_evaluated,  # 返回所有评估的合约，便于显示淘汰原因
            underlying_scores=underlying_scores,
            scanned_underlyings=len(symbols),
            passed_underlyings=len(passed_underlyings),
            total_contracts_evaluated=total_evaluated,
            qualified_contracts=len(confirmed),  # 使用确认后的数量
            candidates=candidates,  # Step1 候选
            confirmed=confirmed,  # 两步都通过
        )

    def run_market_only(self, market_type: MarketType) -> MarketStatus:
        """仅执行市场环境评估

        Args:
            market_type: 市场类型

        Returns:
            MarketStatus: 市场状态
        """
        return self.market_filter.evaluate(market_type)

    def run_underlying_only(
        self,
        symbols: list[str],
        market_type: MarketType,
    ) -> list[UnderlyingScore]:
        """仅执行标的评估

        Args:
            symbols: 标的列表
            market_type: 市场类型

        Returns:
            UnderlyingScore 列表
        """
        return self.underlying_filter.evaluate(symbols, market_type)

    def _log_market_status(self, status: MarketStatus) -> None:
        """输出详细的市场状态日志

        Args:
            status: 市场状态
        """
        market_name = "美股" if status.market_type == MarketType.US else "港股"
        status_icon = "✅" if status.is_favorable else "❌"

        logger.info(f"{'─' * 50}")
        logger.info(f"📊 {market_name}市场环境评估 {status_icon}")
        logger.info(f"{'─' * 50}")

        # 波动率指数
        if status.volatility_index:
            vi = status.volatility_index
            pct_str = f" (百分位 {vi.percentile:.0%})" if vi.percentile else ""
            logger.info(f"   波动率: {vi.symbol}={vi.value:.2f}{pct_str} [{vi.status.value}]")

        # 期限结构（仅美股）
        if status.term_structure:
            ts = status.term_structure
            structure = "Contango(正向)" if ts.is_contango else "Backwardation(反向)"
            logger.info(
                f"   期限结构: VIX={ts.vix_value:.2f} / VIX3M={ts.vix3m_value:.2f} "
                f"= {ts.ratio:.3f} [{structure}]"
            )

        # 大盘趋势
        if status.trend_indices:
            logger.info(f"   大盘趋势: {status.overall_trend.value}")
            for idx in status.trend_indices:
                sma_info = ""
                if idx.sma50:
                    above_sma50 = ">" if idx.price > idx.sma50 else "<"
                    sma_info = f" {above_sma50} SMA50({idx.sma50:.2f})"
                logger.info(f"      - {idx.symbol}: {idx.price:.2f}{sma_info} [{idx.trend.value}]")

        # Put/Call Ratio
        if status.pcr:
            logger.info(f"   PCR: {status.pcr.symbol}={status.pcr.value:.3f} [{status.pcr.filter_status.value}]")

        # 宏观事件
        if status.macro_events:
            me = status.macro_events
            if me.is_in_blackout:
                events = ", ".join(me.event_names) if me.event_names else "未知事件"
                logger.info(f"   宏观事件: ⚠️ 黑名单期间 ({events})")
            elif me.upcoming_events:
                events = ", ".join(me.event_names)
                logger.info(f"   宏观事件: {len(me.upcoming_events)} 个即将到来 ({events})")
            else:
                logger.info("   宏观事件: ✓ 无重大事件")

        # 不利因素
        if status.unfavorable_reasons:
            logger.info("   不利因素:")
            for reason in status.unfavorable_reasons:
                logger.info(f"      ❌ {reason}")

        logger.info(f"{'─' * 50}")

    def _confirm_candidates(
        self,
        candidates: list[ContractOpportunity],
        passed_underlyings: list[UnderlyingScore],
        option_types: list[str] | None,
        market_type: MarketType,
        filter_config: "ContractFilterConfig" = None,
    ) -> list[ContractOpportunity]:
        """二次确认候选合约

        只重新获取候选合约的最新行情并评估，不获取整个期权链。

        Args:
            candidates: Step1 候选合约列表
            passed_underlyings: 通过标的筛选的标的列表
            option_types: 期权类型列表
            market_type: 市场类型
            filter_config: 方向特定的合约筛选配置

        Returns:
            两步都通过的合约列表
        """
        if not candidates:
            return []

        # 使用传入的配置或默认配置
        if filter_config is None:
            filter_config = self.config.contract_filter

        # 1. 构建 OptionContract 列表（只包含候选合约）
        contracts_to_fetch: list[OptionContract] = []
        contract_to_candidate: dict[tuple, ContractOpportunity] = {}

        for c in candidates:
            # 构建 OptionContract
            opt_type = OptionType.PUT if c.option_type == "put" else OptionType.CALL
            expiry_date = date.fromisoformat(c.expiry)
            contract = OptionContract(
                symbol=f"{c.symbol}_{c.expiry}_{c.strike}_{c.option_type}",  # 标识用
                underlying=c.symbol,
                option_type=opt_type,
                strike_price=c.strike,
                expiry_date=expiry_date,
                trading_class=c.trading_class,  # IBKR 需要 trading_class 来识别 HK 期权
            )
            contracts_to_fetch.append(contract)
            # 记录映射关系
            key = (c.symbol, c.expiry, c.strike, c.option_type)
            contract_to_candidate[key] = c

        logger.info(f"二次确认: 获取 {len(contracts_to_fetch)} 个候选合约的最新行情...")

        # 2. 批量获取候选合约的最新行情（不获取整个期权链）
        quotes = self.provider.get_option_quotes_batch(
            contracts_to_fetch,
            min_volume=0,
            fetch_margin=True,
        )

        if not quotes:
            logger.warning("二次确认: 无法获取候选合约行情")
            return []

        logger.info(f"二次确认: 获取到 {len(quotes)} 个合约报价，开始评估...")

        # 3. 构建 symbol -> UnderlyingScore 映射
        underlying_map = {s.symbol: s for s in passed_underlyings}

        # 4. 评估每个合约
        dte_min, dte_max = filter_config.dte_range

        confirmed: list[ContractOpportunity] = []
        for quote in quotes:
            contract = quote.contract
            symbol = contract.underlying
            opt_type = "put" if contract.option_type == OptionType.PUT else "call"
            expiry_str = contract.expiry_date.isoformat()
            key = (symbol, expiry_str, contract.strike_price, opt_type)

            # 获取对应的 UnderlyingScore
            underlying_score = underlying_map.get(symbol)
            if not underlying_score:
                logger.warning(f"二次确认: 未找到 {symbol} 的标的评分")
                continue

            # 调用 contract_filter 的评估方法
            opp = self.contract_filter._evaluate_contract(
                quote=quote,
                underlying_score=underlying_score,
                filter_config=filter_config,
                dte_min=dte_min,
                dte_max=dte_max,
                option_type=opt_type,
            )

            # 输出评估结果
            self.contract_filter._log_contract_evaluation(opp)

            if opp.passed:
                confirmed.append(opp)

        return confirmed


# 便捷函数
def create_pipeline(
    strategy: StrategyType | str = StrategyType.SHORT_PUT,
    provider: DataProvider | None = None,
) -> ScreeningPipeline:
    """创建筛选管道

    Args:
        strategy: 策略类型 (StrategyType 枚举或字符串，如 "short_put")
        provider: 数据提供者 (DataProvider 或其子类)，默认创建 UnifiedDataProvider

    Returns:
        ScreeningPipeline 实例
    """
    # StrategyType 继承 str，可以直接用于文件名
    strategy_str = strategy.value if isinstance(strategy, StrategyType) else strategy
    config = ScreeningConfig.load(strategy_str)

    if provider is None:
        provider = UnifiedDataProvider()

    return ScreeningPipeline(config, provider)
