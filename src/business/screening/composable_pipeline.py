"""
Composable Screening Pipeline - 可组合的筛选管道

策略从组件库中挑选 Check 组件来构建自定义管道。
与 ScreeningPipeline.run() 返回相同的 ScreeningResult 类型，
保证与 BaseTradeStrategy._default_find_opportunities() 兼容。

使用示例:
    from src.business.screening.components import (
        VIXRangeCheck, IVRankCheck, DTERangeCheck, DeltaRangeCheck, LiquidityCheck,
    )
    from src.business.screening.composable_pipeline import ComposableScreeningPipeline

    pipeline = ComposableScreeningPipeline(
        market_checks=[VIXRangeCheck(vix_range=(12, 28))],
        underlying_checks=[IVRankCheck(min_iv_rank=30)],
        contract_checks=[
            DTERangeCheck(dte_range=(21, 45)),
            DeltaRangeCheck(delta_range=(0.15, 0.30)),
            LiquidityCheck(min_oi=100, max_spread=0.10),
        ],
        data_provider=provider,
    )
    result = pipeline.run(symbols=["AAPL", "MSFT"], market_type=MarketType.US, strategy_type=StrategyType.SHORT_PUT)
"""

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from src.business.screening.models import (
    ContractOpportunity,
    MarketType,
    ScreeningResult,
    UnderlyingScore,
)
from src.engine.models.enums import StrategyType

if TYPE_CHECKING:
    from src.business.screening.components import MarketCheck, UnderlyingCheck, ContractCheck
    from src.data.providers.base import DataProvider

logger = logging.getLogger(__name__)


class ComposableScreeningPipeline:
    """可组合的筛选管道

    通过组合 Check 组件来构建自定义筛选管道。
    每个 Check 组件是独立的小类，可以自由搭配。

    与 ScreeningPipeline 返回相同的 ScreeningResult 类型，
    确保与 BaseTradeStrategy 中的调用代码兼容。

    执行流程:
    1. 运行 market_checks（任一失败则中止）
    2. 对每个 symbol 运行 underlying_checks（全部通过才保留）
    3. 获取期权链，对每个合约运行 contract_checks
    4. 返回 ScreeningResult（与 ScreeningPipeline 相同格式）
    """

    def __init__(
        self,
        market_checks: list["MarketCheck"] | None = None,
        underlying_checks: list["UnderlyingCheck"] | None = None,
        contract_checks: list["ContractCheck"] | None = None,
        data_provider: "DataProvider" = None,
        option_chain_params: dict | None = None,
    ):
        """初始化可组合筛选管道

        Args:
            market_checks: 市场级检查组件列表
            underlying_checks: 标的级检查组件列表
            contract_checks: 合约级检查组件列表
            data_provider: 数据提供者
            option_chain_params: 获取期权链的额外参数（如 dte_range, otm_pct_range 等）
        """
        self.market_checks = market_checks or []
        self.underlying_checks = underlying_checks or []
        self.contract_checks = contract_checks or []
        self.data_provider = data_provider
        self.option_chain_params = option_chain_params or {}

    def run(
        self,
        symbols: list[str],
        market_type: MarketType | str = MarketType.US,
        strategy_type: StrategyType = StrategyType.SHORT_PUT,
        skip_market_check: bool = False,
    ) -> ScreeningResult:
        """执行筛选流程

        Args:
            symbols: 待筛选标的列表
            market_type: 市场类型
            strategy_type: 策略类型
            skip_market_check: 是否跳过市场环境检查

        Returns:
            ScreeningResult: 筛选结果
        """
        market_type_str = market_type.value if isinstance(market_type, MarketType) else market_type

        logger.info(
            f"ComposablePipeline: 市场={market_type_str}, 策略={strategy_type.value}, "
            f"标的={len(symbols)}, checks=({len(self.market_checks)}M/{len(self.underlying_checks)}U/{len(self.contract_checks)}C)"
        )
        start_time = datetime.now()

        # 1. 市场环境检查
        if not skip_market_check and self.market_checks:
            logger.info("Step 1: 运行市场级检查...")
            for check in self.market_checks:
                passed, reason = check.check(market_type_str, self.data_provider)
                if not passed:
                    logger.warning(f"市场检查未通过: {reason}")
                    return ScreeningResult(
                        passed=False,
                        strategy_type=strategy_type,
                        scanned_underlyings=0,
                        rejection_reason=reason,
                    )
                logger.info(f"  ✓ {type(check).__name__}: {reason}")
        else:
            logger.info("Step 1: 跳过市场检查")

        # 2. 标的检查
        logger.info(f"Step 2: 运行标的级检查 ({len(symbols)} 个标的)...")
        passed_symbols = []
        underlying_scores = []

        for symbol in symbols:
            symbol_passed = True
            disqualify_reasons = []

            for check in self.underlying_checks:
                passed, reason = check.check(symbol, self.data_provider)
                if not passed:
                    symbol_passed = False
                    disqualify_reasons.append(reason)
                    break  # 第一个失败即淘汰

            score = UnderlyingScore(
                symbol=symbol,
                market_type=MarketType(market_type_str) if isinstance(market_type_str, str) else market_type,
                passed=symbol_passed,
                disqualify_reasons=disqualify_reasons,
            )
            underlying_scores.append(score)

            if symbol_passed:
                passed_symbols.append(symbol)
                logger.debug(f"  ✓ {symbol}")
            else:
                logger.info(f"  ✗ {symbol}: {disqualify_reasons[0] if disqualify_reasons else '未知'}")

        logger.info(f"标的检查完成: {len(passed_symbols)}/{len(symbols)} 通过")

        if not passed_symbols:
            return ScreeningResult(
                passed=False,
                strategy_type=strategy_type,
                underlying_scores=underlying_scores,
                scanned_underlyings=len(symbols),
                passed_underlyings=0,
                rejection_reason="无标的通过筛选",
            )

        # 3. 合约检查
        logger.info(f"Step 3: 运行合约级检查...")
        all_opportunities = []
        confirmed = []

        for symbol in passed_symbols:
            opps = self._evaluate_contracts_for_symbol(symbol, strategy_type)
            all_opportunities.extend(opps)
            confirmed.extend([o for o in opps if o.passed])

        total_evaluated = len(all_opportunities)
        logger.info(f"合约检查完成: {len(confirmed)}/{total_evaluated} 通过")

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"ComposablePipeline 完成: {len(confirmed)} 个机会, 耗时 {elapsed:.1f}s")

        return ScreeningResult(
            passed=len(confirmed) > 0,
            strategy_type=strategy_type,
            opportunities=all_opportunities,
            underlying_scores=underlying_scores,
            scanned_underlyings=len(symbols),
            passed_underlyings=len(passed_symbols),
            total_contracts_evaluated=total_evaluated,
            qualified_contracts=len(confirmed),
            candidates=confirmed,
            confirmed=confirmed,
        )

    def _evaluate_contracts_for_symbol(
        self,
        symbol: str,
        strategy_type: StrategyType,
    ) -> list[ContractOpportunity]:
        """获取期权链并评估合约

        复用 DataProvider.get_option_chain() 获取数据，
        然后对每个合约运行 contract_checks。

        Args:
            symbol: 标的代码
            strategy_type: 策略类型

        Returns:
            评估后的 ContractOpportunity 列表
        """
        from src.data.models.option import OptionType

        # 确定期权类型
        if strategy_type in (StrategyType.SHORT_PUT, StrategyType.LONG_PUT):
            option_type = "put"
        elif strategy_type in (StrategyType.COVERED_CALL, StrategyType.NAKED_CALL, StrategyType.LONG_CALL):
            option_type = "call"
        else:
            option_type = None

        # 构建期权链查询参数
        chain_params = {
            "option_type": option_type,
            "option_cond_type": "otm",
        }
        chain_params.update(self.option_chain_params)

        try:
            chain = self.data_provider.get_option_chain(symbol, **chain_params)
        except Exception as e:
            logger.warning(f"{symbol}: 获取期权链失败: {e}")
            return []

        if chain is None:
            return []

        # 获取标的当前价格
        ref_date = _get_reference_date(self.data_provider)

        opportunities = []
        quotes = chain.puts + chain.calls if hasattr(chain, 'puts') and hasattr(chain, 'calls') else []

        # 如果 chain 直接返回 quotes 列表
        if not quotes and hasattr(chain, '__iter__'):
            quotes = list(chain)

        for quote in quotes:
            contract = quote.contract
            opt_type = "put" if contract.option_type == OptionType.PUT else "call"

            # 过滤方向
            if option_type and opt_type != option_type:
                continue

            # 计算 DTE
            expiry_date = contract.expiry_date
            dte = (expiry_date - ref_date).days if expiry_date else 0

            # 构建 ContractOpportunity
            opp = ContractOpportunity(
                symbol=symbol,
                expiry=expiry_date.isoformat() if expiry_date else "",
                strike=contract.strike_price,
                option_type=opt_type,
                dte=dte,
                bid=quote.bid,
                ask=quote.ask,
                mid_price=(quote.bid + quote.ask) / 2 if quote.bid and quote.ask else quote.last_price,
                open_interest=quote.open_interest,
                volume=quote.volume,
                delta=quote.greeks.delta if quote.greeks else None,
                gamma=quote.greeks.gamma if quote.greeks else None,
                theta=quote.greeks.theta if quote.greeks else None,
                vega=quote.greeks.vega if quote.greeks else None,
                iv=quote.iv,
                underlying_price=None,  # 将在后续填充
                lot_size=getattr(contract, 'lot_size', 100),
            )

            # 运行所有合约级检查
            disqualify_reasons = []
            for check in self.contract_checks:
                passed, reason = check.check(opp)
                if not passed:
                    disqualify_reasons.append(reason)

            opp.passed = len(disqualify_reasons) == 0
            opp.disqualify_reasons = disqualify_reasons

            opportunities.append(opp)

        return opportunities


def _get_reference_date(data_provider) -> date:
    """获取参考日期（回测兼容）"""
    if hasattr(data_provider, "as_of_date"):
        return data_provider.as_of_date
    return date.today()
