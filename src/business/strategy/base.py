from abc import ABC, abstractmethod
from typing import List, Any, TYPE_CHECKING, Optional
import logging

from src.business.screening.models import ContractOpportunity
from src.business.monitoring.models import PositionData
from src.business.strategy.models import MarketContext, TradeSignal

if TYPE_CHECKING:
    from src.backtest.engine.account_simulator import AccountSimulator
    from src.business.config.screening_config import ScreeningConfig
    from src.business.config.monitoring_config import MonitoringConfig

logger = logging.getLogger(__name__)


class BaseOptionStrategy(ABC):
    """期权策略基类 (包含默认的通用 V9 交易逻辑)

    所有具体的策略版本（如 ShortPutV6, ShortPutV9）必须继承此基类。
    基类默认实现了当前最复杂的 V9 的「寻机-建仓-平仓」闭环。
    如果子版本逻辑有差异，可以通过 Override 具体的方法来实现隔离。
    """

    def __init__(self):
        """初始化策略基类"""
        self._screening_config: Optional["ScreeningConfig"] = None
        self._monitoring_config: Optional["MonitoringConfig"] = None
        
        # 性能优化：缓存高频调用的管道实例
        self._screening_pipeline_instance = None
        self._monitoring_pipeline_instance = None
        self._position_sizer_instance = None

    @property
    @abstractmethod
    def name(self) -> str:
        """策略的唯一标识符名称 (例如 'short_put_v9')"""
        pass

    def set_configs(
        self,
        screening_config: "ScreeningConfig",
        monitoring_config: "MonitoringConfig",
        strategy_types: List["StrategyType"] = None
    ) -> None:
        """注入配置（由 BacktestExecutor 调用）

        Args:
            screening_config: 筛选配置
            monitoring_config: 监控配置
            strategy_types: 策略允许操作的期权方向 (如 SHORT_PUT, COVERED_CALL)
        """
        self._screening_config = screening_config
        self._monitoring_config = monitoring_config
        self._strategy_types = strategy_types or []

    # ==========================
    # 阶段 1：平仓监控与风控决策
    # ==========================
    def evaluate_positions(
        self, positions: List[PositionData], context: MarketContext, data_provider: Any = None
    ) -> List[TradeSignal]:
        """评估当前所有持仓，产生风控或止盈止损平仓信号

        默认实现 (V9 规则):
        1. DTE <= 14 且盈利 >= 70% 止盈
        2. DTE <= 21 且盈利 >= 80% 止盈
        3. PnL <= -200% 或单边风险暴露过大时止损
        4. 否则等待到期：ITM 行权接盘股票，OTM 价值归零
        """
        signals = []
        from src.backtest.engine.trade_simulator import TradeAction
        from src.business.monitoring.pipeline import MonitoringPipeline
        from src.business.config.monitoring_config import MonitoringConfig

        # 1. 使用注入的配置或从 YAML 加载监控配置 (带缓存)
        if self._monitoring_pipeline_instance is None:
            config = self._monitoring_config or MonitoringConfig.load(strategy_name=self.name)
            self._monitoring_pipeline_instance = MonitoringPipeline(config)

        # 2. 运行监控管道获取持仓调整建议
        vix = context.vix_value
        result = self._monitoring_pipeline_instance.run(
            positions=positions,
            vix=vix,
            as_of_date=context.current_date,
            data_provider=data_provider,
        )

        # 3. 将平仓建议转换为 TradeSignal
        for suggestion in result.suggestions:
            if suggestion.action.value in ["close", "roll", "take_profit", "reduce", "hedge", "adjust"]:
                # 优先适用 position_id 匹配，因为不同引擎/环境生成的 symbol 格式（如背测连线vs实盘IB）可能不一致
                pos = next((p for p in positions if p.position_id == getattr(suggestion, 'position_id', None)), None)
                if not pos:
                    pos = next((p for p in positions if p.symbol == suggestion.symbol), None)
                    
                if pos:
                    # 如果动作为 TAKE_PROFIT (止盈), REDUCE (减仓) 等，本质上都是执行 CLOSE 单操作
                    # 这里简单将其归类为买入平仓操作
                    # 展期维持在 ROLL
                    if suggestion.action.value in ["close", "take_profit", "reduce", "hedge", "adjust"]:
                        action_enum = TradeAction.CLOSE
                    else:
                        action_enum = TradeAction.ROLL

                    roll_to_expiry = suggestion.metadata.get("suggested_expiry") if action_enum == TradeAction.ROLL else None
                    roll_to_strike = suggestion.metadata.get("suggested_strike") if action_enum == TradeAction.ROLL else None

                    signals.append(
                        TradeSignal(
                            action=action_enum,
                            symbol=suggestion.symbol,
                            quantity=-pos.quantity,  # 反向平仓/展期第一步都是平掉原仓位
                            reason=suggestion.reason,
                            position_id=pos.position_id,  # 设置 position_id 用于交易执行
                            roll_to_expiry=roll_to_expiry,
                            roll_to_strike=roll_to_strike,
                            priority="high" if suggestion.urgency.value == "immediate" else "normal"
                        )
                    )

        return signals

    def get_position_side(self, opportunity: ContractOpportunity) -> Any:
        """获取开仓方向 (PositionSide)
        
        基类默认实现：返回 PositionSide.SHORT (卖出期权)。
        未来如果是买方策略 (Long Option) 或多腿组合策略，子类只需重写此方法
        或直接重写 generate_entry_signals 即可。
        
        Args:
            opportunity: 目标期权合约机会
            
        Returns:
            PositionSide 枚举 (LONG 或 SHORT)
        """
        from src.engine.models.enums import PositionSide
        return PositionSide.SHORT

    # ==========================
    # 阶段 2：开仓条件与标的筛选
    # ==========================
    def find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        """寻找市面上的开仓机会（支持多交易方向）

        默认实现 (V9 规则):
        利用代码实例化的 ScreeningConfig，执行严格的 IV Rank 和技术形态过滤。

        支持多交易方向:
        - 从配置中读取 strategy_types 列表
        - 为每个方向运行独立的筛选 Pipeline
        - 合并所有确认的机会
        """
        from src.business.config.screening_config import ScreeningConfig
        from src.business.screening.pipeline import ScreeningPipeline
        from src.business.screening.models import MarketType
        from src.engine.models.enums import StrategyType

        # 1. 使用注入的配置或从 YAML 加载配置并初始化 Pipeline (带缓存)
        if self._screening_pipeline_instance is None:
            config = self._screening_config or ScreeningConfig.load(strategy_name=self.name)
            self._screening_pipeline_instance = ScreeningPipeline(config, data_provider)

        # 2. 获取支持的策略类型
        target_types = self._get_strategy_types()

        # 3. 为每个方向运行筛选
        all_confirmed = []

        for stype in target_types:
            try:
                logger.info(f"正在筛选 {stype.value} 方向的机会...")
                result = self._screening_pipeline_instance.run(
                    symbols=symbols,
                    market_type=MarketType.US,
                    strategy_type=stype,
                    skip_market_check=False
                )
                if result and result.confirmed:
                    # 将策略类型附加到 opportunity 以便于后续识别
                    for opp in result.confirmed:
                        opp.metadata["source_strategy_type"] = stype.value
                    all_confirmed.extend(result.confirmed)
                    logger.info(f"{stype.value} 方向找到 {len(result.confirmed)} 个机会")
            except Exception as e:
                logger.error(f"Strategy {self.name} screening failed for {stype.value}: {e}")

        logger.info(f"总计找到 {len(all_confirmed)} 个机会")
        return all_confirmed

    def _get_strategy_types(self) -> List["StrategyType"]:
        """获取支持的策略类型列表

        优先级:
        1. 通过 set_configs() 注入的 _strategy_types
        2. 从 ScreeningConfig.strategy_types 读取
        3. 默认返回 [StrategyType.SHORT_PUT]

        Returns:
            策略类型列表
        """
        from src.engine.models.enums import StrategyType

        # 优先使用注入的策略类型
        if self._strategy_types:
            return self._strategy_types

        # 从配置中获取
        if self._screening_config:
            type_strs = getattr(
                self._screening_config,
                "strategy_types",
                ["short_put"]
            )
            return [StrategyType(t) for t in type_strs]

        # 默认只支持 SHORT_PUT
        return [StrategyType.SHORT_PUT]

    # ==========================
    # 阶段 3：建仓信号生成
    # ==========================
    def generate_entry_signals(
        self, 
        candidates: List[ContractOpportunity], 
        account: "AccountSimulator",
        context: MarketContext
    ) -> List[TradeSignal]:
        """从机会中挑选并分配仓位（替代老的 DecisionEngine）

        默认实现 (V9 规则):
        选择 Expected ROC 即 Annual ROC 最高的一个合约进行交易，分配 25% 购买力。
        """
        if not candidates:
            return []
            
        # V9 选优逻辑：按 AnnROC 排序取最高
        # 确保 candidates 按照期望收益率降序排序（通常由 Pipeline 的 OutputConfig 控制，但为了安全再排一次）
        sorted_candidates = sorted(candidates, key=lambda x: getattr(x, 'expected_roc', 0) or x.annual_roc, reverse=True)
        best_candidate = sorted_candidates[0]
        
        # 仓位计算：复用核心底层 PositionSizer，确保风控及 Kelly 公式准确执行
        from src.business.trading.decision.position_sizer import PositionSizer
        from src.business.trading.models.decision import AccountState
        from src.business.trading.config.decision_config import DecisionConfig
        
        # 加载决策配置（内含策略匹配的 risk_config），并缓存 Sizer 实例以提升性能
        if self._position_sizer_instance is None:
            decision_config = DecisionConfig.load(strategy_name=self.name)
            self._position_sizer_instance = PositionSizer(config=decision_config)
            
        sizer = self._position_sizer_instance
        
        margin_util = account.margin_used / account.nlv if account.nlv > 0 else 0.0
        cash_ratio = account.cash / account.nlv if account.nlv > 0 else 0.0
        
        account_state = AccountState(
            broker="backtest",
            account_type="paper",
            total_equity=account.nlv,
            cash_balance=account.cash,
            available_margin=account.available_margin,
            used_margin=account.margin_used,
            margin_utilization=margin_util,
            cash_ratio=cash_ratio,
            gross_leverage=0.0,
            total_position_count=account.position_count
        )
        
        qty = sizer.calculate_size(best_candidate, account_state)
        
        if qty <= 0:
            logger.warning(f"PositionSizer 认为仓位受限无法开仓对于: {best_candidate.symbol}")
            return []
            
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionQuote, OptionContract, OptionType, Greeks
        from datetime import datetime
        from src.engine.models.enums import PositionSide

        # 构造临时的 OptionQuote 以满足执行引擎的需要
        # format of expiry in ContractOpportunity is mostly ISO string or similar
        try:
            expiration = datetime.strptime(best_candidate.expiry, "%Y-%m-%d").date()
        except Exception:
            # Fallback if it's already a date or different format
            from datetime import date
            expiration = best_candidate.expiry if isinstance(best_candidate.expiry, date) else context.current_date

        contract = OptionContract(
            symbol=best_candidate.symbol,
            underlying=best_candidate.symbol.split()[0] if " " in best_candidate.symbol else best_candidate.symbol,
            option_type=OptionType(best_candidate.option_type.lower()),
            strike_price=best_candidate.strike,
            expiry_date=expiration,
            lot_size=best_candidate.lot_size or 100
        )
        
        greeks = Greeks(
            delta=best_candidate.delta,
            gamma=best_candidate.gamma,
            theta=best_candidate.theta,
            vega=best_candidate.vega
        )

        quote_obj = OptionQuote(
            contract=contract,
            timestamp=datetime.combine(context.current_date, datetime.min.time()),
            bid=best_candidate.bid or best_candidate.mid_price,
            ask=best_candidate.ask or best_candidate.mid_price,
            last_price=best_candidate.mid_price,
            iv=best_candidate.iv,
            volume=best_candidate.volume or 0,
            open_interest=best_candidate.open_interest or 0,
            greeks=greeks
        )

        side = self.get_position_side(best_candidate)
        direction = 1 if side == PositionSide.LONG else -1

        return [
            TradeSignal(
                action=TradeAction.OPEN,
                symbol=best_candidate.symbol,
                quantity=qty * direction,  # 动态应用开仓方向
                reason=f"Top candidate: AnnROC={getattr(best_candidate, 'expected_roc', best_candidate.annual_roc):.1%}, IVRank={getattr(best_candidate, 'underlying_iv_rank', getattr(best_candidate, 'iv_rank', 0.0)):.1f}%",
                priority="normal",
                quote=quote_obj
            )
        ]
