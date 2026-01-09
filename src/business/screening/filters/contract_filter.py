"""
Contract Filter - 合约过滤器

第三层筛选：筛选具体期权合约

检查项目：
- DTE 在目标范围内 (25-45天)
- Delta 在目标范围内 (-0.35 ~ -0.15)
- 流动性 (Bid/Ask spread, Open Interest, Volume)
- 策略指标 (SAS >= 50, PREI <= 75, TGR >= 0.05, Sharpe >= 1.0)

架构说明：
- 数据获取：调用 data_layer (UnifiedDataProvider)
- 指标计算：调用 engine_layer (strategy, position 模块)
- 业务逻辑：本模块专注业务判断和编排
"""

import logging
import math
from datetime import date

from src.business.config.screening_config import (
    ContractFilterConfig,
    LiquidityConfig,
    MetricsConfig,
    ScreeningConfig,
)
from src.business.screening.models import (
    ContractOpportunity,
    UnderlyingScore,
)
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.position.option_metrics import calc_sas
from src.engine.position.risk_return import calc_prei, calc_tgr
from src.engine.strategy.short_put import ShortPutStrategy

logger = logging.getLogger(__name__)


class ContractFilter:
    """合约过滤器

    根据配置筛选具体期权合约：
    1. DTE 在目标范围内
    2. Delta 在目标范围内
    3. 流动性满足要求
    4. 策略指标达标（SAS, PREI, TGR, Sharpe）

    架构职责：
    - data_layer: UnifiedDataProvider 提供原始数据
    - engine_layer: strategy/position 模块提供指标计算
    - business_layer: 本模块进行业务判断和编排

    使用方式：
        filter = ContractFilter(config, provider)
        opportunities = filter.evaluate(
            underlying_scores,
            strategy_type="short_put",
        )
    """

    def __init__(
        self,
        config: ScreeningConfig,
        provider: UnifiedDataProvider | None = None,
    ) -> None:
        """初始化合约过滤器

        Args:
            config: 筛选配置
            provider: 统一数据提供者，默认创建新实例
        """
        self.config = config
        self.provider = provider or UnifiedDataProvider()

    def evaluate(
        self,
        underlying_scores: list[UnderlyingScore],
        strategy_type: str = "short_put",
    ) -> list[ContractOpportunity]:
        """评估合约机会

        Args:
            underlying_scores: 通过第二层筛选的标的评分列表
            strategy_type: 策略类型 ("short_put" 或 "covered_call")

        Returns:
            ContractOpportunity 列表
        """
        all_opportunities: list[ContractOpportunity] = []
        filter_config = self.config.contract_filter

        for score in underlying_scores:
            if not score.passed:
                continue

            try:
                opportunities = self._evaluate_underlying(
                    score,
                    strategy_type,
                    filter_config,
                )
                all_opportunities.extend(opportunities)
            except Exception as e:
                logger.error(f"评估 {score.symbol} 合约失败: {e}")

        # 按配置排序
        sort_by = self.config.output.sort_by
        sort_order = self.config.output.sort_order
        max_opps = self.config.output.max_opportunities

        all_opportunities = self._sort_opportunities(
            all_opportunities,
            sort_by,
            sort_order == "desc",
        )

        return all_opportunities[:max_opps]

    def _evaluate_underlying(
        self,
        score: UnderlyingScore,
        strategy_type: str,
        filter_config: ContractFilterConfig,
    ) -> list[ContractOpportunity]:
        """评估单个标的的合约"""
        symbol = score.symbol
        opportunities: list[ContractOpportunity] = []

        # 1. 从 data_layer 获取期权链
        dte_min, dte_max = filter_config.dte_range
        today = date.today()

        chain = self.provider.get_option_chain(
            symbol,
            expiry_start=today,
            expiry_end=None,  # 由 dte_max 过滤
        )

        if chain is None:
            logger.warning(f"{symbol} 无期权链数据")
            return []

        # 2. 筛选 Put 合约（对于 short_put 策略）
        if strategy_type == "short_put":
            contracts = [q.contract for q in chain.puts]
        else:  # covered_call
            contracts = [q.contract for q in chain.calls]

        if not contracts:
            logger.warning(f"{symbol} 无符合条件的合约")
            return []

        # 3. 从 data_layer 获取合约报价（包含 Greeks）
        min_volume = filter_config.liquidity.min_volume
        quotes = self.provider.get_option_quotes_batch(
            contracts,
            min_volume=min_volume,
        )

        if not quotes:
            logger.warning(f"{symbol} 无合约报价数据")
            return []

        # 4. 过滤和评估每个合约
        for quote in quotes:
            opp = self._evaluate_contract(
                quote,
                score,
                strategy_type,
                filter_config,
                dte_min,
                dte_max,
            )
            if opp:
                opportunities.append(opp)

        return opportunities

    def _evaluate_contract(
        self,
        quote,
        underlying_score: UnderlyingScore,
        strategy_type: str,
        filter_config: ContractFilterConfig,
        dte_min: int,
        dte_max: int,
    ) -> ContractOpportunity | None:
        """评估单个合约"""
        contract = quote.contract
        symbol = contract.underlying
        strike = contract.strike_price
        expiry = contract.expiry_date

        # 业务层：计算 DTE
        today = date.today()
        dte = (expiry - today).days

        # 业务层：检查 DTE 范围
        if not (dte_min <= dte <= dte_max):
            return None

        # 获取 Greeks
        greeks = quote.greeks if hasattr(quote, "greeks") else None
        delta = greeks.delta if greeks else None
        gamma = greeks.gamma if greeks else None
        theta = greeks.theta if greeks else None
        vega = greeks.vega if greeks else None
        iv = quote.iv

        # 业务层：检查 Delta 范围（对于 short put，delta 应为负值）
        if delta is not None:
            delta_min, delta_max = filter_config.delta_range
            if not (delta_min <= delta <= delta_max):
                return None

        # 获取价格信息
        bid = quote.bid
        ask = quote.ask
        mid_price = (bid + ask) / 2 if bid and ask else quote.last_price
        open_interest = quote.open_interest
        volume = quote.volume

        # 业务层：检查流动性
        liquidity_config = filter_config.liquidity
        if not self._check_liquidity(
            bid, ask, mid_price, open_interest, volume, liquidity_config
        ):
            return None

        # 获取标的价格
        underlying_price = underlying_score.current_price
        if underlying_price is None:
            return None

        # 业务层：计算 Moneyness
        moneyness = (underlying_price - strike) / strike

        # 调用 engine_layer 计算策略指标
        metrics = self._calc_strategy_metrics(
            spot_price=underlying_price,
            strike_price=strike,
            premium=mid_price or 0,
            volatility=iv or underlying_score.current_iv or 0.20,
            time_to_expiry=dte / 365,
            hv=underlying_score.hv_20 or 0.20,
            dte=dte,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
        )

        # 业务层：检查策略指标
        metrics_config = filter_config.metrics
        if not self._check_metrics(metrics, metrics_config):
            return None

        return ContractOpportunity(
            symbol=symbol,
            expiry=expiry.isoformat(),
            strike=strike,
            option_type="put" if strategy_type == "short_put" else "call",
            bid=bid,
            ask=ask,
            mid_price=mid_price,
            open_interest=open_interest,
            volume=volume,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            iv=iv,
            dte=dte,
            expected_return=metrics.get("expected_return"),
            return_std=metrics.get("return_std"),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            win_probability=metrics.get("win_probability"),
            sas=metrics.get("sas"),
            prei=metrics.get("prei"),
            tgr=metrics.get("tgr"),
            kelly_fraction=metrics.get("kelly_fraction"),
            underlying_price=underlying_price,
            moneyness=moneyness,
        )

    def _check_liquidity(
        self,
        bid: float | None,
        ask: float | None,
        mid_price: float | None,
        open_interest: int | None,
        volume: int | None,
        config: LiquidityConfig,
    ) -> bool:
        """检查流动性（业务层判断）"""
        # Bid/Ask spread 检查
        if bid and ask and mid_price and mid_price > 0:
            spread = (ask - bid) / mid_price
            if spread > config.max_bid_ask_spread:
                return False

        # Open Interest 检查
        if open_interest is not None and open_interest < config.min_open_interest:
            return False

        # Volume 检查（如果有数据）
        if volume is not None and volume < config.min_volume:
            return False

        return True

    def _calc_strategy_metrics(
        self,
        spot_price: float,
        strike_price: float,
        premium: float,
        volatility: float,
        time_to_expiry: float,
        hv: float,
        dte: int,
        delta: float | None,
        gamma: float | None,
        theta: float | None,
        vega: float | None,
    ) -> dict:
        """计算策略指标

        调用 engine_layer 的策略计算模块
        """
        metrics: dict = {}

        if volatility <= 0 or time_to_expiry <= 0:
            return metrics

        try:
            # 调用 engine_layer: ShortPutStrategy
            strategy = ShortPutStrategy(
                spot_price=spot_price,
                strike_price=strike_price,
                premium=premium,
                volatility=volatility,
                time_to_expiry=time_to_expiry,
                hv=hv,
                dte=dte,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
            )

            # 期望收益和标准差
            expected_return = strategy.calc_expected_return()
            return_var = strategy.calc_return_variance()
            return_std = math.sqrt(return_var) if return_var > 0 else 0

            metrics["expected_return"] = expected_return
            metrics["return_std"] = return_std

            # Sharpe Ratio
            if return_std > 0:
                metrics["sharpe_ratio"] = expected_return / return_std
            else:
                metrics["sharpe_ratio"] = 0

            # Win Probability
            metrics["win_probability"] = strategy.calc_win_probability()

            # 调用 engine_layer: calc_sas
            if hv > 0:
                sas = calc_sas(
                    iv=volatility,
                    hv=hv,
                    sharpe_ratio=metrics.get("sharpe_ratio", 0),
                    win_probability=metrics.get("win_probability", 0),
                )
                metrics["sas"] = sas

            # 调用 engine_layer: calc_prei
            if gamma is not None and vega is not None and dte is not None:
                from src.engine.models.position import Position

                position = Position(
                    symbol=f"TEST_{strike_price}P",
                    quantity=1,
                    gamma=gamma,
                    vega=vega,
                    dte=dte,
                    underlying_price=spot_price,
                )
                prei = calc_prei(position)
                metrics["prei"] = prei

            # 调用 engine_layer: calc_tgr
            if theta is not None and gamma is not None and gamma != 0:
                from src.engine.models.position import Position

                position = Position(
                    symbol=f"TEST_{strike_price}P",
                    quantity=1,
                    theta=theta,
                    gamma=gamma,
                )
                tgr = calc_tgr(position)
                metrics["tgr"] = tgr

            # 业务层：Kelly Fraction
            win_prob = metrics.get("win_probability", 0)
            if win_prob > 0 and win_prob < 1 and expected_return != 0:
                max_profit = strategy.calc_max_profit()
                max_loss = strategy.calc_max_loss()
                if max_loss > 0 and max_profit > 0:
                    win_ratio = max_profit / max_loss
                    kelly = (win_prob * (1 + win_ratio) - 1) / win_ratio
                    metrics["kelly_fraction"] = max(0, min(kelly, 0.5))  # 限制最大 50%

        except Exception as e:
            logger.debug(f"计算策略指标失败: {e}")

        return metrics

    def _check_metrics(
        self,
        metrics: dict,
        config: MetricsConfig,
    ) -> bool:
        """检查策略指标是否达标（业务层判断）"""
        # Sharpe Ratio 检查
        sharpe = metrics.get("sharpe_ratio")
        if sharpe is not None and sharpe < config.min_sharpe_ratio:
            return False

        # SAS 检查
        sas = metrics.get("sas")
        if sas is not None and sas < config.min_sas:
            return False

        # PREI 检查
        prei = metrics.get("prei")
        if prei is not None and prei > config.max_prei:
            return False

        # TGR 检查
        tgr = metrics.get("tgr")
        if tgr is not None and tgr < config.min_tgr:
            return False

        # Kelly 检查
        kelly = metrics.get("kelly_fraction")
        if kelly is not None and kelly > config.max_kelly_fraction:
            return False

        return True

    def _sort_opportunities(
        self,
        opportunities: list[ContractOpportunity],
        sort_by: str,
        descending: bool,
    ) -> list[ContractOpportunity]:
        """排序机会列表"""

        def get_sort_key(opp: ContractOpportunity) -> float:
            value = getattr(opp, sort_by, None)
            if value is None:
                return float("-inf") if descending else float("inf")
            return value

        return sorted(opportunities, key=get_sort_key, reverse=descending)
