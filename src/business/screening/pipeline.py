"""
Screening Pipeline - 筛选管道

整合三层筛选器，形成完整的筛选流程：
1. 市场环境过滤 -> 如果不利则中止
2. 标的过滤 -> 筛选合格标的
3. 合约过滤 -> 筛选合格合约

使用方式：
    pipeline = ScreeningPipeline(config, data_provider)
    result = pipeline.run(
        symbols=["AAPL", "MSFT", "GOOGL"],
        market_type=MarketType.US,
        strategy_type="short_put",
    )
"""

import logging
from datetime import datetime
from typing import Protocol

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

logger = logging.getLogger(__name__)


class DataProvider(Protocol):
    """数据提供者接口（统一所有过滤器需要的方法）"""

    # Market Filter 需要
    def get_macro_data(self, indicator: str, start_date, end_date) -> list:
        ...

    def get_stock_volatility(self, symbol: str, include_iv_rank: bool = True) -> object | None:
        ...

    def get_put_call_ratio(self, symbol: str) -> float | None:
        ...

    # Underlying Filter 需要
    def get_stock_quote(self, symbol: str) -> object | None:
        ...

    def get_history_kline(self, symbol: str, ktype, start_date, end_date) -> list:
        ...

    def get_fundamental(self, symbol: str) -> object | None:
        ...

    # Contract Filter 需要
    def get_option_chain(
        self,
        underlying: str,
        expiry_start=None,
        expiry_end=None,
        expiry_min_days: int | None = None,
        expiry_max_days: int | None = None,
        strike_range_pct: float | None = None,
    ) -> object | None:
        ...

    def get_option_quotes_batch(
        self,
        contracts: list,
        min_volume: int | None = None,
        request_delay: float = 0.5,
    ) -> list:
        ...


class ScreeningPipeline:
    """筛选管道

    整合三层筛选器，执行完整的筛选流程。

    流程：
    1. 市场环境评估 - 检查 VIX、大盘趋势、期限结构等
    2. 标的评估 - 检查 IV Rank、技术面、基本面等
    3. 合约评估 - 检查 DTE、Delta、流动性、策略指标等

    每层过滤器都可以独立配置和使用。
    """

    def __init__(
        self,
        config: ScreeningConfig,
        data_provider: DataProvider,
    ) -> None:
        """初始化筛选管道

        Args:
            config: 筛选配置
            data_provider: 数据提供者（需支持所有过滤器的接口）
        """
        self.config = config
        self.provider = data_provider

        # 初始化各层过滤器
        self.market_filter = MarketFilter(config, data_provider)
        self.underlying_filter = UnderlyingFilter(config, data_provider)
        self.contract_filter = ContractFilter(config, data_provider)

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
        opportunities = self.contract_filter.evaluate(
            passed_underlyings,
            strategy_type,
        )

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"筛选完成: {len(opportunities)} 个机会, 耗时 {elapsed:.1f}s"
        )

        return ScreeningResult(
            passed=len(opportunities) > 0,
            strategy_type=strategy_type,
            market_status=market_status,
            opportunities=opportunities,
            underlying_scores=underlying_scores,
            scanned_underlyings=len(symbols),
            passed_underlyings=len(passed_underlyings),
            total_contracts_evaluated=sum(
                1 for s in passed_underlyings if s.passed
            ) * 10,  # 估算值
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
    data_provider: DataProvider | None = None,
) -> ScreeningPipeline:
    """创建筛选管道

    Args:
        strategy: 策略类型 ("short_put" 或 "covered_call")
        data_provider: 数据提供者，如果为 None 则使用默认配置

    Returns:
        ScreeningPipeline 实例
    """
    config = ScreeningConfig.load(strategy)

    if data_provider is None:
        # 默认使用组合数据提供者
        from src.data.manager import create_data_manager

        data_provider = create_data_manager()

    return ScreeningPipeline(config, data_provider)
