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
        strategy_type="short_put",
    )
"""

import logging
from datetime import datetime

from src.business.config.screening_config import ScreeningConfig
from src.business.screening.filters.contract_filter import ContractFilter
from src.business.screening.filters.market_filter import MarketFilter
from src.business.screening.filters.underlying_filter import UnderlyingFilter
from src.business.screening.models import (
    MarketStatus,
    MarketType,
    ScreeningResult,
    UnderlyingScore,
)
from src.data.providers.unified_provider import UnifiedDataProvider

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
        provider: UnifiedDataProvider | None = None,
    ) -> None:
        """初始化筛选管道

        Args:
            config: 筛选配置
            provider: 统一数据提供者，默认创建新实例
        """
        self.config = config
        self.provider = provider or UnifiedDataProvider()

        # 初始化各层过滤器，共享同一个 provider
        self.market_filter = MarketFilter(config, self.provider)
        self.underlying_filter = UnderlyingFilter(config, self.provider)
        self.contract_filter = ContractFilter(config, self.provider)

    def run(
        self,
        symbols: list[str],
        market_type: MarketType,
        strategy_type: str = "short_put",
        skip_market_check: bool = False,
    ) -> ScreeningResult:
        """执行完整筛选流程

        Args:
            symbols: 待筛选标的列表
            market_type: 市场类型 (US/HK)
            strategy_type: 策略类型 ("short_put" 或 "covered_call")
            skip_market_check: 是否跳过市场环境检查（调试用）

        Returns:
            ScreeningResult: 筛选结果
        """
        logger.info(
            f"开始筛选: 市场={market_type.value}, 策略={strategy_type}, "
            f"标的数量={len(symbols)}"
        )
        start_time = datetime.now()

        # 1. 市场环境评估
        market_status: MarketStatus | None = None
        if not skip_market_check:
            logger.info("Step 1: 评估市场环境...")
            market_status = self.market_filter.evaluate(market_type)

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

            logger.info("市场环境有利，继续筛选")
        else:
            logger.info("Step 1: 跳过市场环境检查")

        # 2. 标的评估
        logger.info(f"Step 2: 评估标的 ({len(symbols)} 个)...")
        underlying_scores = self.underlying_filter.evaluate(symbols, market_type)

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
        if strategy_type == "short_put":
            option_types = ["put"]
        elif strategy_type == "covered_call":
            option_types = ["call"]
        else:
            option_types = None  # 评估所有类型

        # 使用 return_rejected=True 获取所有评估的合约（包括被拒绝的）
        all_evaluated = self.contract_filter.evaluate(
            passed_underlyings,
            option_types=option_types,
            return_rejected=True,
        )

        # 统计实际评估数量并筛选出通过的
        total_evaluated = len(all_evaluated)
        opportunities = [o for o in all_evaluated if o.passed]

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"筛选完成: {len(opportunities)}/{total_evaluated} 个机会, 耗时 {elapsed:.1f}s"
        )

        return ScreeningResult(
            passed=len(opportunities) > 0,
            strategy_type=strategy_type,
            market_status=market_status,
            opportunities=all_evaluated,  # 返回所有评估的合约，便于显示淘汰原因
            underlying_scores=underlying_scores,
            scanned_underlyings=len(symbols),
            passed_underlyings=len(passed_underlyings),
            total_contracts_evaluated=total_evaluated,  # 使用实际评估数量
            qualified_contracts=len(opportunities),
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


# 便捷函数
def create_pipeline(
    strategy: str = "short_put",
    provider: UnifiedDataProvider | None = None,
) -> ScreeningPipeline:
    """创建筛选管道

    Args:
        strategy: 策略类型 ("short_put" 或 "covered_call")
        provider: 统一数据提供者，如果为 None 则创建默认实例

    Returns:
        ScreeningPipeline 实例
    """
    config = ScreeningConfig.load(strategy)

    if provider is None:
        provider = UnifiedDataProvider()

    return ScreeningPipeline(config, provider)
