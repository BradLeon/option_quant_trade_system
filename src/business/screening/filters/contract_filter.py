"""
Contract Filter - 合约过滤器

第三层筛选：筛选具体期权合约

优先级说明：
- P0 致命条件（必须阻塞）：Expected ROC > 0%, 近价期权成交量 > 5000, ATM Spread < 5%
- P1 核心条件（阻塞）：DTE, Delta, Bid-Ask Spread, Open Interest, TGR
- P2 重要条件（警告）：财报跨越, OTM %, 年化 ROC, SAS, PREI
- P3 参考条件（警告）：Sharpe Ratio, Premium Rate, Win Probability, Theta/Premium, Kelly, Volume
- 排序指标：Theta/Margin（资金效率）

架构说明：
- 数据获取：调用 data_layer (UnifiedDataProvider)
- 指标计算：调用 engine_layer (strategy, position 模块)
- 业务逻辑：本模块专注业务判断和编排
"""

import logging
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
from src.engine.contract.liquidity import (
    calc_bid_ask_spread_ratio,
    is_liquid,
)
from src.engine.contract.metrics import (
    calc_otm_percent,
    calc_theta_premium_ratio,
)
from src.engine.bs.greeks import calc_bs_greeks
from src.engine.models import BSParams
from src.engine.strategy.short_call import ShortCallStrategy
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
        option_types: list[str] | None = None,
        return_rejected: bool = False,
    ) -> list[ContractOpportunity]:
        """评估合约机会

        Args:
            underlying_scores: 通过第二层筛选的标的评分列表
            option_types: 要评估的期权类型列表，如 ["put"], ["call"], 或 None=两者都评估
                - ["put"]: 只评估 PUT（对应 short_put 策略）
                - ["call"]: 只评估 CALL（对应 covered_call 策略）
                - None 或 ["put", "call"]: 评估所有合约
            return_rejected: 是否返回被拒绝的合约（默认 False，只返回通过的）
                - False: 只返回 passed=True 的合约（兼容现有代码）
                - True: 返回所有评估过的合约，便于调试和分析

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
                    filter_config,
                    option_types=option_types,
                )
                all_opportunities.extend(opportunities)
            except Exception as e:
                logger.error(f"评估 {score.symbol} 合约失败: {e}")

        # 根据 return_rejected 参数过滤
        if not return_rejected:
            # 默认只返回通过的合约（兼容现有代码）
            all_opportunities = [o for o in all_opportunities if o.passed]

        # 按配置排序
        sort_by = self.config.output.sort_by
        sort_order = self.config.output.sort_order
        max_opps = self.config.output.max_opportunities

        all_opportunities = self._sort_opportunities(
            all_opportunities,
            sort_by,
            sort_order == "desc",
        )

        # 只有返回通过的合约时才应用数量限制
        if not return_rejected:
            return all_opportunities[:max_opps]

        return all_opportunities

    def _evaluate_underlying(
        self,
        score: UnderlyingScore,
        filter_config: ContractFilterConfig,
        option_types: list[str] | None = None,
    ) -> list[ContractOpportunity]:
        """评估单个标的的合约

        优化：
        - API 层直接过滤：DTE, OTM/ITM, Delta, OI（利用 Futu/IBKR 原生能力）
        - 一次 get_option_chain 调用，同时评估 PUT 和 CALL
        - 应用层只做精细检查（API 不支持的过滤条件）

        Args:
            score: 标的评分
            filter_config: 合约过滤配置
            option_types: 要评估的期权类型，如 ["put"], ["call"], 或 None=两者都评估
        """
        symbol = score.symbol

        # 1. 从 data_layer 获取期权链（利用 API 层过滤，大幅减少返回数据量）
        dte_min, dte_max = filter_config.dte_range
        delta_min, delta_max = filter_config.delta_range
        liquidity_config = filter_config.liquidity
        today = date.today()

        # 确定 option_type 参数（单一类型时传入，否则 None 获取全部）
        types_to_eval = option_types or ["put", "call"]
        api_option_type = types_to_eval[0] if len(types_to_eval) == 1 else None

        # 调用 UnifiedDataProvider，利用 API 原生过滤能力：
        # - Futu: option_type, option_cond_type, open_interest 原生支持
        # - IBKR: expiry_min/max_days, strike_range_pct 原生支持，其他后处理
        # 注意：delta 过滤保留在应用层，因为配置是 |Delta| 绝对值，而 API 需要考虑正负号
        #       PUT delta 是负数，CALL delta 是正数，无法用单一 min/max 表达
        # OTM% 范围过滤 (前置过滤，大幅减少合约数量)
        otm_min, otm_max = filter_config.otm_range

        chain = self.provider.get_option_chain(
            symbol,
            expiry_min_days=dte_min,
            expiry_max_days=dte_max,
            option_type=api_option_type,
            option_cond_type="otm",  # 关键：直接排除 ITM
            open_interest_min=liquidity_config.min_open_interest,  # Futu 原生支持
            otm_pct_min=otm_min,  # OTM% 下限 (如 0.05 = 5%)
            otm_pct_max=otm_max,  # OTM% 上限 (如 0.15 = 15%)
        )

        if chain is None:
            logger.warning(f"{symbol} 无期权链数据")
            return []

        # 2. 根据 option_types 决定评估哪些合约
        all_chain_quotes: list[tuple] = []  # (quote, option_type)

        if "put" in types_to_eval and chain.puts:
            for q in chain.puts:
                all_chain_quotes.append((q, "put"))

        if "call" in types_to_eval and chain.calls:
            for q in chain.calls:
                all_chain_quotes.append((q, "call"))

        if not all_chain_quotes:
            logger.warning(f"{symbol} 无符合条件的合约（API 层过滤后为空）")
            return []

        # ============================================================
        # 3. 应用层精细过滤（API 不支持或需要更精确检查的条件）
        # 注意：大部分过滤已在 API 层完成，此处仅做补充检查
        # ============================================================
        pre_filtered: list[tuple] = []
        stats = {
            "total": len(all_chain_quotes),
            "dte_fail": 0,  # API 层已过滤，这里做双重检查
            "delta_fail": 0,  # IBKR 不支持 delta 过滤，需要应用层检查
            "oi_fail": 0,  # IBKR 不支持 OI 过滤，需要应用层检查
        }

        for q, opt_type in all_chain_quotes:
            contract = q.contract

            # DTE 双重检查（API 层已过滤，这里确保精确）
            dte = (contract.expiry_date - today).days
            if not (dte_min <= dte <= dte_max):
                stats["dte_fail"] += 1
                continue

            # Delta 精细检查（IBKR 不支持 delta 过滤，需要应用层检查）
            # 只在有值时检查，无值则跳过（让评估阶段处理）
            greeks = q.greeks if hasattr(q, "greeks") else None
            delta = greeks.delta if greeks else None
            if delta is not None:
                abs_delta = abs(delta)
                if not (delta_min <= abs_delta <= delta_max):
                    stats["delta_fail"] += 1
                    continue

            # OI 精细检查（IBKR 不支持 OI 过滤，需要应用层检查）
            oi = q.open_interest if hasattr(q, "open_interest") else None
            if oi is not None and oi < liquidity_config.min_open_interest:
                stats["oi_fail"] += 1
                continue

            pre_filtered.append((q, opt_type))

        passed = len(pre_filtered)
        logger.info(
            f"{symbol} API过滤后={stats['total']} -> 应用层精细过滤: "
            f"DTE淘汰{stats['dte_fail']}/Delta淘汰{stats['delta_fail']}/OI淘汰{stats['oi_fail']} -> "
            f"{passed}个通过"
        )

        if not pre_filtered:
            return []

        # ============================================================
        # 4. 只为预过滤后的合约获取详细报价
        # ============================================================
        contracts_to_fetch = [q.contract for q, _ in pre_filtered]
        quotes = self.provider.get_option_quotes_batch(
            contracts_to_fetch,
            min_volume=0,  # 评估阶段再检查
            fetch_margin=True,  # 获取真实保证金用于 ROC 计算
        )

        if not quotes:
            logger.warning(f"{symbol} 无合约报价数据")
            return []

        # 建立 contract -> option_type 映射
        contract_to_type = {
            (q.contract.strike_price, q.contract.expiry_date, q.contract.option_type): opt_type
            for q, opt_type in pre_filtered
        }

        logger.info(f"{symbol} 获取 {len(quotes)} 个报价，开始评估")

        # 5. 评估每个合约（收集所有结果，包括被拒绝的）
        all_evaluated: list[ContractOpportunity] = []
        for quote in quotes:
            # 确定 option_type
            contract = quote.contract
            key = (contract.strike_price, contract.expiry_date, contract.option_type)
            opt_type = contract_to_type.get(key)
            if opt_type is None:
                # 从 contract.option_type 推断
                opt_type = "put" if str(contract.option_type).lower() in ["put", "p"] else "call"

            opp = self._evaluate_contract(
                quote,
                score,
                filter_config,
                dte_min,
                dte_max,
                option_type=opt_type,
            )
            # 输出详细评估日志
            self._log_contract_evaluation(opp)
            all_evaluated.append(opp)

        # 统计评估结果
        passed_count = sum(1 for o in all_evaluated if o.passed)
        rejected_count = len(all_evaluated) - passed_count
        put_count = sum(1 for o in all_evaluated if o.option_type == "put")
        call_count = sum(1 for o in all_evaluated if o.option_type == "call")
        logger.info(
            f"{symbol} 评估完成: {len(all_evaluated)} 个合约 "
            f"(PUT:{put_count}, CALL:{call_count}), "
            f"通过 {passed_count}, 拒绝 {rejected_count}"
        )

        return all_evaluated

    def _evaluate_contract(
        self,
        quote,
        underlying_score: UnderlyingScore,
        filter_config: ContractFilterConfig,
        dte_min: int,
        dte_max: int,
        option_type: str,
    ) -> ContractOpportunity:
        """评估单个合约

        始终返回 ContractOpportunity，用 passed 字段标识是否通过所有 P0/P1 检查。
        这样可以让调用方获取所有评估过的合约，包括被拒绝的，便于调试和分析。

        优先级检查：
        - P0/P1 条件不满足 → passed=False，记录 disqualify_reasons
        - P2/P3 条件不满足 → 记录 warnings（不阻塞）

        Args:
            quote: 合约报价
            underlying_score: 标的评分
            filter_config: 过滤配置
            dte_min: DTE 最小值
            dte_max: DTE 最大值
            option_type: 期权类型 ("put" 或 "call")
        """
        contract = quote.contract
        symbol = contract.underlying
        strike = contract.strike_price
        expiry = contract.expiry_date

        disqualify_reasons: list[str] = []  # P0/P1 阻塞
        warnings: list[str] = []  # P2/P3 警告

        # 业务层：计算 DTE
        today = date.today()
        dte = (expiry - today).days

        # 获取 Greeks
        greeks = quote.greeks if hasattr(quote, "greeks") else None
        delta = greeks.delta if greeks else None
        gamma = greeks.gamma if greeks else None
        theta = greeks.theta if greeks else None
        vega = greeks.vega if greeks else None
        iv = quote.iv

        # 获取价格信息
        bid = quote.bid
        ask = quote.ask
        mid_price = (bid + ask) / 2 if bid and ask else quote.last_price
        open_interest = quote.open_interest
        volume = quote.volume

        # 获取标的价格
        underlying_price = underlying_score.current_price

        # ============================================================
        # 用 BS 模型补算缺失或无效的 Greeks（gamma/theta）
        # 条件：gamma 或 theta 为 None 或 0（Futu API 可能返回 0 而非 None）
        # ============================================================
        gamma_missing = gamma is None or gamma == 0
        theta_missing = theta is None or theta == 0

        if iv and iv > 0 and underlying_price and dte > 0:
            if gamma_missing or theta_missing:
                try:
                    bs_params = BSParams(
                        spot_price=underlying_price,
                        strike_price=strike,
                        risk_free_rate=0.03,
                        volatility=iv,
                        time_to_expiry=dte / 365,
                        is_call=(option_type == "call"),
                    )
                    bs_greeks = calc_bs_greeks(bs_params)

                    old_gamma, old_theta = gamma, theta
                    if gamma_missing and bs_greeks.get("gamma") is not None:
                        gamma = bs_greeks["gamma"]
                    if theta_missing and bs_greeks.get("theta") is not None:
                        theta = bs_greeks["theta"]
                    if (delta is None or delta == 0) and bs_greeks.get("delta") is not None:
                        delta = bs_greeks["delta"]
                    if (vega is None or vega == 0) and bs_greeks.get("vega") is not None:
                        vega = bs_greeks["vega"]

                    logger.debug(
                        f"{symbol} {strike}{option_type[0].upper()}: "
                        f"BS补算 gamma={old_gamma}->{gamma:.6f}, theta={old_theta}->{theta:.6f}"
                    )
                except Exception as e:
                    logger.debug(f"BS Greeks 补算失败: {e}")
        else:
            if gamma_missing or theta_missing:
                logger.debug(
                    f"{symbol} {strike}{option_type[0].upper()}: "
                    f"无法BS补算 (iv={iv}, price={underlying_price}, dte={dte})"
                )

        # ============================================================
        # 阶段 1: P1 基础条件检查（快速检查，早退出）
        # ============================================================

        # P1: DTE 范围检查
        if not (dte_min <= dte <= dte_max):
            disqualify_reasons.append(f"[P1] DTE={dte} 超出范围 ({dte_min}-{dte_max})")

        # P1: Delta 范围检查 - None 视为数据缺失
        # 配置使用 |Delta| 绝对值范围
        delta_min, delta_max = filter_config.delta_range
        if delta is None:
            disqualify_reasons.append("[P1] Delta 数据缺失")
        else:
            abs_delta = abs(delta)
            if not (delta_min <= abs_delta <= delta_max):
                disqualify_reasons.append(f"[P1] |Delta|={abs_delta:.3f} 超出范围 ({delta_min}-{delta_max})")

        # P1: 流动性检查 (Bid-Ask Spread, Open Interest)
        liquidity_config = filter_config.liquidity
        if bid and ask and mid_price and mid_price > 0:
            spread = (ask - bid) / mid_price
            if spread > liquidity_config.max_bid_ask_spread:
                disqualify_reasons.append(f"[P1] Spread={spread:.1%} 过高（>{liquidity_config.max_bid_ask_spread:.0%}）")

        # P1: OI 检查 - None 视为数据缺失
        if open_interest is not None and open_interest < liquidity_config.min_open_interest:
            disqualify_reasons.append(f"[P1] OI={open_interest} 不足（<{liquidity_config.min_open_interest}）")

        # P1: IV 检查 - None 视为数据缺失
        if iv is None or iv <= 0:
            disqualify_reasons.append("[P1] IV 数据缺失")

        if underlying_price is None:
            disqualify_reasons.append("[P1] 无法获取标的价格")

        # 记录 P1 基础条件检查结果（不再早退出，继续计算指标便于调试）
        has_p1_block = len(disqualify_reasons) > 0
        if has_p1_block:
            logger.debug(f"{symbol} {strike}{option_type[0].upper()} {expiry}: P1阻塞 - {disqualify_reasons}")

        # ============================================================
        # 阶段 2: 计算复杂指标（即使 P1 失败也尽量计算，便于调试）
        # ============================================================

        # 业务层：计算 Moneyness
        moneyness = (underlying_price - strike) / strike if underlying_price else None

        # OTM 百分比
        otm_percent = calc_otm_percent(underlying_price, strike, option_type) if underlying_price else None

        # Theta/Premium 比率
        theta_prem_ratio = calc_theta_premium_ratio(theta, mid_price)

        # 提取真实保证金 per-share（如果有）
        margin_per_share = quote.margin.initial_margin if quote.margin else None

        # 策略指标
        metrics = self._calc_strategy_metrics(
            spot_price=underlying_price or 0,
            strike_price=strike,
            premium=mid_price or 0,
            volatility=iv or underlying_score.current_iv or 0.20,
            time_to_expiry=dte / 365 if dte > 0 else 0.01,
            hv=underlying_score.hv_20 or 0.20,
            dte=dte,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            option_type=option_type,
            margin_per_share=margin_per_share,
        )

        # 使用策略类计算的 ROC 指标（基于 IBKR margin 公式）
        annual_roc = metrics.get("roc")  # 年化 Premium ROC
        expected_roc = metrics.get("expected_roc")  # 年化 Expected ROC

        # ============================================================
        # 阶段 3: P0/P1/P2/P3 指标检查
        # ============================================================
        metrics_config = filter_config.metrics
        metrics_issues = self._check_metrics_with_reasons(
            metrics, metrics_config, theta_prem_ratio, annual_roc, expected_roc
        )
        for issue in metrics_issues:
            if issue.startswith("[P0]") or issue.startswith("[P1]"):
                disqualify_reasons.append(issue)
            else:
                warnings.append(issue)

        # P2: OTM 百分比检查
        if otm_percent is not None:
            otm_min, otm_max = filter_config.otm_range
            if not (otm_min <= otm_percent <= otm_max):
                warnings.append(f"[P2] OTM%={otm_percent:.1%} 超出范围 ({otm_min:.0%}-{otm_max:.0%})")

        # P2: 财报跨越检查
        if underlying_score.earnings_date and underlying_score.days_to_earnings is not None:
            if underlying_score.days_to_earnings < dte:
                warnings.append(f"[P2] 跨财报：合约到期({dte}天) > 财报日({underlying_score.days_to_earnings}天)")

        # P3: Volume 检查（警告）- None 也记录警告
        if volume is None:
            warnings.append("[P3] Volume 数据缺失")
        elif volume < liquidity_config.min_volume:
            warnings.append(f"[P3] Volume={volume} 偏低（<{liquidity_config.min_volume}）")

        # 判断是否通过所有 P0/P1 检查
        passed = len(disqualify_reasons) == 0

        # 生成通过原因和推荐仓位（仅 passed=True 时）
        pass_reasons: list[str] = []
        recommended_position: float | None = None
        if passed:
            # 生成关键指标摘要作为通过原因
            if expected_roc is not None:
                pass_reasons.append(f"ExpROC={expected_roc:.1%}")
            sharpe_annual = metrics.get("sharpe_ratio_annual")
            if sharpe_annual is not None:
                pass_reasons.append(f"SR_ann={sharpe_annual:.2f}")
            tgr = metrics.get("tgr")
            if tgr is not None:
                pass_reasons.append(f"TGR={tgr:.2f}")
            premium_rate = metrics.get("premium_rate")
            if premium_rate is not None:
                pass_reasons.append(f"费率={premium_rate:.2%}")
            win_prob = metrics.get("win_probability")
            if win_prob is not None:
                pass_reasons.append(f"胜率={win_prob:.1%}")
            if bid and ask and mid_price and mid_price > 0:
                spread = (ask - bid) / mid_price
                pass_reasons.append(f"Spread={spread:.1%}")
            if open_interest is not None:
                pass_reasons.append(f"OI={open_interest}")

            # 推荐仓位: 1/4 Kelly（保守策略）
            kelly = metrics.get("kelly_fraction")
            if kelly is not None and kelly > 0:
                recommended_position = kelly / 4
            else:
                recommended_position = 0.0

        # 始终返回 ContractOpportunity，用 passed 字段标识是否通过
        return ContractOpportunity(
            symbol=symbol,
            expiry=expiry.isoformat(),
            strike=strike,
            option_type=option_type,
            trading_class=contract.trading_class,  # IBKR 需要 trading_class 来识别 HK 期权
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
            sharpe_ratio_annual=metrics.get("sharpe_ratio_annual"),
            win_probability=metrics.get("win_probability"),
            sas=metrics.get("sas"),
            prei=metrics.get("prei"),
            tgr=metrics.get("tgr"),
            kelly_fraction=metrics.get("kelly_fraction"),
            underlying_price=underlying_price,
            moneyness=moneyness,
            otm_percent=otm_percent,
            theta_premium_ratio=theta_prem_ratio,
            theta_margin_ratio=metrics.get("theta_margin_ratio"),  # 资金效率排序指标
            expected_roc=expected_roc,
            annual_roc=annual_roc,
            premium_rate=metrics.get("premium_rate"),
            disqualify_reasons=disqualify_reasons,
            warnings=warnings,
            passed=passed,
            pass_reasons=pass_reasons,
            recommended_position=recommended_position,
        )

    def _check_liquidity_with_reasons(
        self,
        bid: float | None,
        ask: float | None,
        mid_price: float | None,
        open_interest: int | None,
        volume: int | None,
        config: LiquidityConfig,
    ) -> list[str]:
        """检查流动性，返回问题列表（业务层判断）

        优先级：
        - P1: Bid-Ask Spread, Open Interest
        - P3: Volume Today
        """
        issues: list[str] = []

        # P1: Bid-Ask Spread 检查
        if bid and ask and mid_price and mid_price > 0:
            spread = (ask - bid) / mid_price
            if spread > config.max_bid_ask_spread:
                issues.append(
                    f"[P1] Bid-Ask Spread={spread:.1%} 过高（>{config.max_bid_ask_spread:.0%}）"
                )

        # P1: Open Interest 检查
        if open_interest is not None and open_interest < config.min_open_interest:
            issues.append(
                f"[P1] Open Interest={open_interest} 不足（<{config.min_open_interest}）"
            )

        # P3: Volume 检查（警告）
        if volume is not None and volume < config.min_volume:
            issues.append(
                f"[P3] Volume={volume} 偏低（<{config.min_volume}）"
            )

        return issues

    def _check_liquidity(
        self,
        bid: float | None,
        ask: float | None,
        mid_price: float | None,
        open_interest: int | None,
        volume: int | None,
        config: LiquidityConfig,
    ) -> bool:
        """检查流动性（业务层判断）- 保留兼容性

        使用 engine_layer 的 liquidity 工具函数进行检查。
        """
        # 使用 engine_layer: is_liquid() 进行综合流动性检查
        # 将 max_bid_ask_spread (decimal) 转换为百分比
        max_spread_percent = config.max_bid_ask_spread * 100

        return is_liquid(
            bid=bid,
            ask=ask,
            open_interest=open_interest,
            volume=volume,
            max_spread_percent=max_spread_percent,
            min_open_interest=config.min_open_interest,
            min_volume=config.min_volume,
        )

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
        option_type: str = "put",
        margin_per_share: float | None = None,
    ) -> dict:
        """计算策略指标

        使用 engine_layer 的策略基类 calc_metrics() 统一计算所有指标：
        - put: ShortPutStrategy
        - call: ShortCallStrategy

        Args:
            option_type: 期权类型 ("put" 或 "call")
            margin_per_share: 真实保证金 per-share (来自 Broker API，可选)

        Returns:
            包含所有策略指标的字典
        """
        metrics: dict = {}

        if volatility <= 0 or time_to_expiry <= 0:
            return metrics

        try:
            # 根据 option_type 选择策略类
            if option_type == "put":
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
                    margin_per_share=margin_per_share,
                )
            else:  # option_type == "call"
                strategy = ShortCallStrategy(
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
                    margin_per_share=margin_per_share,
                )

            # 输出真实保证金使用日志（如果有）
            if margin_per_share is not None:
                logger.debug(
                    f"{option_type.upper()} K={strike_price}: 使用真实保证金 {margin_per_share:.2f}/share"
                )

            # 输入参数日志
            logger.debug(
                f"{option_type.upper()} K={strike_price} 输入参数: "
                f"S={spot_price:.2f}, premium={premium:.2f}, IV={volatility:.2%}, "
                f"T={time_to_expiry:.4f}, HV={hv:.2%}, DTE={dte}, "
                f"delta={delta}, gamma={gamma}, theta={theta}, vega={vega}"
            )

            # 使用 calc_metrics() 统一计算所有指标
            strategy_metrics = strategy.calc_metrics()

            # 转换为字典格式
            metrics["expected_return"] = strategy_metrics.expected_return
            metrics["return_std"] = strategy_metrics.return_std
            metrics["sharpe_ratio"] = strategy_metrics.sharpe_ratio
            metrics["sharpe_ratio_annual"] = strategy_metrics.sharpe_ratio_annual
            metrics["win_probability"] = strategy_metrics.win_probability
            metrics["kelly_fraction"] = strategy_metrics.kelly_fraction
            metrics["prei"] = strategy_metrics.prei
            metrics["sas"] = strategy_metrics.sas
            metrics["tgr"] = strategy_metrics.tgr
            metrics["roc"] = strategy_metrics.roc
            metrics["expected_roc"] = strategy_metrics.expected_roc
            metrics["premium_rate"] = strategy_metrics.premium_rate
            metrics["theta_margin_ratio"] = strategy_metrics.theta_margin_ratio

            # 调试日志: 打印所有指标
            strategy_name = "ShortPut" if option_type == "put" else "ShortCall"
            sm = strategy_metrics

            # 格式化辅助函数
            def fmt(v, fmt_str=".4f"):
                return f"{v:{fmt_str}}" if v is not None else "None"

            def fmt_pct(v):
                return f"{v:.2%}" if v is not None else "None"

            logger.debug(
                f"{strategy_name} K={strike_price} dte={dte} 指标详情:\n"
                f"  基础: E[R]={fmt(sm.expected_return)}, Std={fmt(sm.return_std)}, Var={fmt(sm.return_variance)}\n"
                f"  盈亏: MaxProfit={fmt(sm.max_profit, '.2f')}, MaxLoss={fmt(sm.max_loss, '.2f')}, Breakeven={fmt(sm.breakeven, '.2f')}\n"
                f"  概率: WinProb={fmt_pct(sm.win_probability)}\n"
                f"  风险: Sharpe={fmt(sm.sharpe_ratio)}, SharpeAnnual={fmt(sm.sharpe_ratio_annual)}, Kelly={fmt(sm.kelly_fraction)}\n"
                f"  收益: ROC={fmt_pct(sm.roc)}, ExpROC={fmt_pct(sm.expected_roc)}, 费率={fmt_pct(sm.premium_rate)}\n"
                f"  评分: SAS={fmt(sm.sas, '.1f')}, PREI={fmt(sm.prei, '.1f')}, TGR={fmt(sm.tgr)}"
            )

        except Exception as e:
            logger.debug(f"计算策略指标失败: {e}")

        return metrics

    def _check_metrics_with_reasons(
        self,
        metrics: dict,
        config: MetricsConfig,
        theta_prem_ratio: float | None,
        annual_roc: float | None,
        expected_roc: float | None,
    ) -> list[str]:
        """检查策略指标，返回问题列表（业务层判断）

        优先级：
        - P0: Expected ROC
        - P1: TGR
        - P2: Annual ROC
        - P3: Sharpe Ratio, Premium Rate, Win Probability, Theta/Premium, Kelly
              （Sharpe/PremRate 降级原因：卖方收益非正态分布，费率已被 AnnROC 包含）
        """
        issues: list[str] = []

        # === P0: Expected ROC 检查 ===
        if expected_roc is not None and expected_roc <= config.min_expected_roc:
            issues.append(
                f"[P0] Expected ROC={expected_roc:.2%} 不足（需>{config.min_expected_roc:.0%}）"
            )

        # === P1: TGR 检查 ===
        tgr = metrics.get("tgr")
        if tgr is not None and tgr < config.min_tgr:
            issues.append(
                f"[P1] TGR={tgr:.3f} 不足（<{config.min_tgr}）"
            )

        # SAS/PREI 检查已移除 - 这些指标在筛选中意义不大，保留计算用于分析

        # === P2: Annual ROC 检查 ===
        if annual_roc is not None and annual_roc < config.min_annual_roc:
            issues.append(
                f"[P2] Annual ROC={annual_roc:.1%} 不足（<{config.min_annual_roc:.0%}）"
            )

        # === P3: Sharpe Ratio (年化) 检查（参考条件，卖方收益非正态分布）===
        sharpe_annual = metrics.get("sharpe_ratio_annual")
        if sharpe_annual is not None and sharpe_annual < config.min_sharpe_ratio:
            issues.append(
                f"[P3] Sharpe(年化)={sharpe_annual:.2f} 偏低（<{config.min_sharpe_ratio}）"
            )

        # === P3: 费率检查（参考条件，已被 Annual ROC 包含）===
        premium_rate = metrics.get("premium_rate")
        if premium_rate is not None and premium_rate < config.min_premium_rate:
            issues.append(
                f"[P3] 费率={premium_rate:.2%} 偏低（<{config.min_premium_rate:.0%}）"
            )

        # === P3: Win Probability 检查 ===
        win_prob = metrics.get("win_probability")
        if win_prob is not None and win_prob < config.min_win_probability:
            issues.append(
                f"[P3] Win Probability={win_prob:.1%} 偏低（<{config.min_win_probability:.0%}）"
            )

        # === P3: Theta/Premium 检查 ===
        if theta_prem_ratio is not None and theta_prem_ratio < config.min_theta_premium_ratio:
            issues.append(
                f"[P3] Theta/Premium={theta_prem_ratio:.2%}/天 偏低（<{config.min_theta_premium_ratio:.0%}）"
            )

        # === P3: Kelly 检查 ===
        kelly = metrics.get("kelly_fraction")
        if kelly is not None and kelly > config.max_kelly_fraction:
            issues.append(
                f"[P3] Kelly={kelly:.1%} 过高（>{config.max_kelly_fraction:.0%}）"
            )

        return issues

    def _check_metrics(
        self,
        metrics: dict,
        config: MetricsConfig,
    ) -> bool:
        """检查策略指标是否达标（业务层判断）- 保留兼容性"""
        # Sharpe Ratio (年化) 检查
        sharpe_annual = metrics.get("sharpe_ratio_annual")
        if sharpe_annual is not None and sharpe_annual < config.min_sharpe_ratio:
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

    def _log_contract_evaluation(self, opp: ContractOpportunity) -> None:
        """输出单个合约的详细评估结果

        格式参考 validate_contract_filter.py 的 print_contract_brief():
        - 合约标识: 标的 | 方向 | 类型 | 行权价 | 到期日 | DTE | 期权价格
        - 核心数据: Delta, IV, OI, Volume
        - 策略指标: TGR, Sharpe(年化), Expected ROC, 费率
        - 拒绝原因 (FAIL) 或 通过原因+推荐仓位+警告 (PASS)
        """
        status = "PASS" if opp.passed else "FAIL"

        # 合约标识
        direction = "Short"  # 筛选策略都是卖方
        price_str = f"${opp.mid_price:.2f}" if opp.mid_price else "N/A"
        contract_id = (
            f"{opp.symbol} | {direction} {opp.option_type.upper()} | "
            f"K={opp.strike} | Exp={opp.expiry} | DTE={opp.dte} | Price={price_str}"
        )

        # 核心数据
        delta_str = f"Delta={opp.delta:.3f}" if opp.delta is not None else "Delta=N/A"
        iv_str = f"IV={opp.iv:.1%}" if opp.iv is not None else "IV=N/A"
        oi_str = f"OI={opp.open_interest}" if opp.open_interest is not None else "OI=N/A"
        vol_str = f"Vol={opp.volume}" if opp.volume is not None else "Vol=N/A"

        # 策略指标
        tgr_str = f"TGR={opp.tgr:.3f}" if opp.tgr is not None else "TGR=N/A"
        sharpe_str = (
            f"Sharpe(年化)={opp.sharpe_ratio_annual:.2f}"
            if opp.sharpe_ratio_annual is not None
            else "Sharpe(年化)=N/A"
        )
        roc_str = (
            f"E[ROC]={opp.expected_roc:.1%}"
            if opp.expected_roc is not None
            else "E[ROC]=N/A"
        )
        rate_str = (
            f"费率={opp.premium_rate:.2%}"
            if opp.premium_rate is not None
            else "费率=N/A"
        )

        # 输出日志
        logger.info(f"[{status}] {contract_id}")
        logger.info(f"       {delta_str} | {iv_str} | {oi_str} | {vol_str}")
        logger.info(f"       {tgr_str} | {sharpe_str} | {roc_str} | {rate_str}")

        if not opp.passed and opp.disqualify_reasons:
            logger.info(f"       Rejected: {'; '.join(opp.disqualify_reasons)}")
        elif opp.passed:
            if opp.pass_reasons:
                logger.info(f"       Pass: {', '.join(opp.pass_reasons)}")
            if opp.recommended_position is not None:
                logger.info(f"       推荐仓位: {opp.recommended_position:.1%} (1/4 Kelly)")
            if opp.warnings:
                # 只显示前2个警告
                warnings_str = "; ".join(opp.warnings[:2])
                if len(opp.warnings) > 2:
                    warnings_str += f"... (+{len(opp.warnings) - 2} more)"
                logger.info(f"       Warnings: {warnings_str}")

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
