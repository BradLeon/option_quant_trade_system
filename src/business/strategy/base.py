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
    from src.business.screening.pipeline import ScreeningPipeline
    from src.business.monitoring.pipeline import MonitoringPipeline
logger = logging.getLogger(__name__)


class BaseTradeStrategy(ABC):
    """期权策略基类 (包含默认的通用 V9 交易逻辑)

    所有具体的策略版本（如 ShortPutV6, ShortPutV9）必须继承此基类。
    基类默认实现了当前最复杂的 V9 的「寻机-建仓-平仓」闭环。
    如果子版本逻辑有差异，可以通过 Override 具体的方法来实现隔离。

    扩展机制:
    1. 工厂方法: build_screening_pipeline(), build_monitoring_pipeline(), build_position_sizer()
       — 策略可 override 返回自定义管道（如 ComposableScreeningPipeline）
    2. Hook 方法: validate_opportunity(), filter_close_signals()
       — 细粒度定制，无需 override 整个生命周期方法
    3. 生命周期方法: evaluate_positions(), find_opportunities(), generate_entry_signals()
       — 委托给 _default_* 实现，可完全 override
    """

    def __init__(self):
        """初始化策略基类"""
        self._screening_config: Optional["ScreeningConfig"] = None
        self._monitoring_config: Optional["MonitoringConfig"] = None
        self._max_new_positions_per_day: int = 1

        # 性能优化：缓存高频调用的管道实例
        self._screening_pipeline_instance: Optional["ScreeningPipeline"] = None
        self._monitoring_pipeline_instance: Optional["MonitoringPipeline"] = None
        self._position_sizer_instance: Optional[Any] = None

        # evaluate_positions 中保存的持仓快照，供 filter_close_signals 使用
        self._last_positions: List[PositionData] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """策略的唯一标识符名称 (例如 'short_put_v9')"""
        pass

    # ==========================
    # 策略属性
    # ==========================
    @property
    def position_side(self) -> str:
        """默认持仓方向: 'SHORT'。买方策略 override 返回 'LONG'。"""
        return "SHORT"

    # ==========================
    # 组件工厂方法 — 策略可 override 注入不同的管道
    # ==========================
    def build_screening_pipeline(self, data_provider: Any) -> "ScreeningPipeline":
        """构建筛选管道。Override 可返回 ComposableScreeningPipeline 或自定义管道。

        Args:
            data_provider: 数据提供者

        Returns:
            ScreeningPipeline 或兼容接口的实例
        """
        from src.business.config.screening_config import ScreeningConfig
        from src.business.screening.pipeline import ScreeningPipeline

        config = self._screening_config or ScreeningConfig.load(strategy_name=self.name)
        return ScreeningPipeline(config, data_provider)

    def build_monitoring_pipeline(self) -> "MonitoringPipeline":
        """构建监控管道。Override 可返回自定义监控管道。

        Returns:
            MonitoringPipeline 或兼容接口的实例
        """
        from src.business.monitoring.pipeline import MonitoringPipeline
        from src.business.config.monitoring_config import MonitoringConfig

        config = self._monitoring_config or MonitoringConfig.load(strategy_name=self.name)

        # 应用策略版本级阈值覆写
        overrides = self.get_monitoring_overrides()
        if overrides:
            self._apply_monitoring_overrides(config, overrides)

        return MonitoringPipeline(config)

    def build_position_sizer(self) -> Any:
        """构建仓位计算器 — V1 组件已移除，此方法不再可用。"""
        raise NotImplementedError(
            "PositionSizer (V1) has been removed. "
            "Use V2 strategy framework instead."
        )

    # ==========================
    # 策略级 Hook — 细粒度定制
    # ==========================
    def validate_opportunity(self, opp: ContractOpportunity, context: MarketContext) -> bool:
        """策略级风控验证。pipeline 筛选通过后、ranking 前调用。

        返回 False 拒绝该机会。默认: 全部通过。

        Args:
            opp: 通过 pipeline 筛选的合约机会
            context: 当前市场上下文

        Returns:
            True 接受，False 拒绝
        """
        return True

    def filter_close_signals(self, signals: List[TradeSignal], context: MarketContext) -> List[TradeSignal]:
        """后处理平仓信号。monitoring pipeline 转换后调用。

        可添加策略特有的平仓逻辑（如 DTE=0 ITM 强制平仓）。
        默认: 原样返回。

        使用 self._last_positions 获取当前持仓快照。

        Args:
            signals: monitoring pipeline 生成的平仓信号列表
            context: 当前市场上下文

        Returns:
            处理后的平仓信号列表
        """
        return signals

    # ==========================
    # 配置与覆写
    # ==========================
    def get_monitoring_overrides(self) -> dict | None:
        """返回策略版本级的监控阈值覆写（可选）

        子类可覆写此方法，返回字典格式的阈值覆写，
        将被 merge 到 MonitoringConfig.position 中。

        返回 None 表示使用配置文件的默认值。

        示例返回:
            {
                "otm_pct": {"enabled": False},
                "pnl": {"red_below": -2.0},
            }
        """
        return None

    def _apply_monitoring_overrides(self, config: "MonitoringConfig", overrides: dict) -> None:
        """将策略覆写应用到 MonitoringConfig.position 的对应 ThresholdRange 字段"""
        for field_name, field_overrides in overrides.items():
            if hasattr(config.position, field_name):
                threshold = getattr(config.position, field_name)
                for key, value in field_overrides.items():
                    if hasattr(threshold, key):
                        setattr(threshold, key, value)

    def set_configs(
        self,
        screening_config: "ScreeningConfig",
        monitoring_config: "MonitoringConfig",
        strategy_types: List["StrategyType"] = None,
        max_new_positions_per_day: int = 1,
    ) -> None:
        """注入配置（由 BacktestExecutor 调用）

        Args:
            screening_config: 筛选配置
            monitoring_config: 监控配置
            strategy_types: 策略允许操作的期权方向 (如 SHORT_PUT, COVERED_CALL)
            max_new_positions_per_day: 每日最大新开仓数量
        """
        self._screening_config = screening_config
        self._monitoring_config = monitoring_config
        self._strategy_types = strategy_types or []
        self._max_new_positions_per_day = max_new_positions_per_day

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
        return self._default_evaluate_positions(positions, context, data_provider)

    def _default_evaluate_positions(
        self, positions: List[PositionData], context: MarketContext, data_provider: Any = None
    ) -> List[TradeSignal]:
        """evaluate_positions 的默认实现"""
        signals = []
        from src.backtest.engine.trade_simulator import TradeAction

        # 保存持仓快照，供 filter_close_signals 使用
        self._last_positions = list(positions)

        # 1. 使用工厂方法构建监控管道 (带缓存)
        if self._monitoring_pipeline_instance is None:
            self._monitoring_pipeline_instance = self.build_monitoring_pipeline()

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

                    # 从 trigger_alerts 提取结构化 alert_type（透传到 TradeSimulator）
                    primary_alert_type = None
                    if suggestion.trigger_alerts:
                        primary_alert_type = suggestion.trigger_alerts[0].alert_type.value

                    signals.append(
                        TradeSignal(
                            action=action_enum,
                            symbol=suggestion.symbol,
                            quantity=-pos.quantity,  # 反向平仓/展期第一步都是平掉原仓位
                            reason=suggestion.reason,
                            alert_type=primary_alert_type,
                            position_id=pos.position_id,  # 设置 position_id 用于交易执行
                            roll_to_expiry=roll_to_expiry,
                            roll_to_strike=roll_to_strike,
                            priority="high" if suggestion.urgency.value == "immediate" else "normal"
                        )
                    )

        # 4. 调用 hook: 策略级平仓信号后处理
        signals = self.filter_close_signals(signals, context)

        return signals

    def get_position_side(self, opportunity: ContractOpportunity) -> Any:
        """获取开仓方向 (PositionSide)

        读取 position_side 属性来确定方向。
        未来如果是买方策略 (Long Option) 或多腿组合策略，子类只需重写 position_side 属性
        或直接重写 generate_entry_signals 即可。

        Args:
            opportunity: 目标期权合约机会

        Returns:
            PositionSide 枚举 (LONG 或 SHORT)
        """
        from src.engine.models.enums import PositionSide
        if self.position_side == "LONG":
            return PositionSide.LONG
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
        return self._default_find_opportunities(symbols, data_provider, context)

    def _default_find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        """find_opportunities 的默认实现"""
        from src.business.screening.models import MarketType

        # 1. 使用工厂方法构建筛选管道 (带缓存)
        if self._screening_pipeline_instance is None:
            self._screening_pipeline_instance = self.build_screening_pipeline(data_provider)

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

        # 4. 调用 hook: 策略级风控验证
        validated = []
        for opp in all_confirmed:
            if self.validate_opportunity(opp, context):
                validated.append(opp)
            else:
                logger.info(f"validate_opportunity 拒绝: {opp.symbol}")

        if len(validated) != len(all_confirmed):
            logger.info(
                f"validate_opportunity 过滤: {len(all_confirmed)} → {len(validated)}"
            )

        logger.info(f"总计找到 {len(validated)} 个机会")
        return validated

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
    def rank_candidates(self, candidates: List[ContractOpportunity]) -> List[ContractOpportunity]:
        """对候选合约排序（模板方法，子类可覆写选优标准）

        默认实现：按 Expected ROC / Annual ROC 降序排序。
        子类可覆写为 TGR 最优、Sharpe 最优、多因子评分等。
        """
        return sorted(candidates, key=lambda x: getattr(x, 'expected_roc', 0) or x.annual_roc, reverse=True)

    def _build_entry_signal(
        self,
        candidate: ContractOpportunity,
        account_state: Any,
        context: MarketContext,
    ) -> Optional[TradeSignal]:
        """为单个候选合约构建开仓信号（内部方法）

        Args:
            candidate: 候选合约
            account_state: 账户状态 (AccountState)
            context: 市场上下文

        Returns:
            TradeSignal 或 None（仓位为 0 时）
        """
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionQuote, OptionContract, OptionType, Greeks
        from datetime import datetime
        from src.engine.models.enums import PositionSide

        sizer = self._position_sizer_instance
        qty = sizer.calculate_size(candidate, account_state)

        if qty <= 0:
            logger.warning(f"PositionSizer 认为仓位受限无法开仓对于: {candidate.symbol}")
            return None

        try:
            expiration = datetime.strptime(candidate.expiry, "%Y-%m-%d").date()
        except Exception:
            from datetime import date
            expiration = candidate.expiry if isinstance(candidate.expiry, date) else context.current_date

        contract = OptionContract(
            symbol=candidate.symbol,
            underlying=candidate.symbol.split()[0] if " " in candidate.symbol else candidate.symbol,
            option_type=OptionType(candidate.option_type.lower()),
            strike_price=candidate.strike,
            expiry_date=expiration,
            lot_size=candidate.lot_size or 100
        )

        greeks = Greeks(
            delta=candidate.delta,
            gamma=candidate.gamma,
            theta=candidate.theta,
            vega=candidate.vega
        )

        quote_obj = OptionQuote(
            contract=contract,
            timestamp=datetime.combine(context.current_date, datetime.min.time()),
            bid=candidate.bid or candidate.mid_price,
            ask=candidate.ask or candidate.mid_price,
            last_price=candidate.mid_price,
            iv=candidate.iv,
            volume=candidate.volume or 0,
            open_interest=candidate.open_interest or 0,
            greeks=greeks
        )

        side = self.get_position_side(candidate)
        direction = 1 if side == PositionSide.LONG else -1

        return TradeSignal(
            action=TradeAction.OPEN,
            symbol=candidate.symbol,
            quantity=qty * direction,
            reason=f"Top candidate: AnnROC={getattr(candidate, 'expected_roc', candidate.annual_roc):.1%}, IVRank={getattr(candidate, 'underlying_iv_rank', getattr(candidate, 'iv_rank', 0.0)):.1f}%",
            priority="normal",
            quote=quote_obj
        )

    def generate_entry_signals(
        self,
        candidates: List[ContractOpportunity],
        account: "AccountSimulator",
        context: MarketContext
    ) -> List[TradeSignal]:
        """从机会中挑选 top-N 并分配仓位

        遍历排名前 _max_new_positions_per_day 个候选，每个独立计算仓位大小。
        """
        return self._default_generate_entry_signals(candidates, account, context)

    def _default_generate_entry_signals(
        self,
        candidates: List[ContractOpportunity],
        account: "AccountSimulator",
        context: MarketContext
    ) -> List[TradeSignal]:
        """generate_entry_signals 的默认实现"""
        if not candidates:
            return []

        # 使用模板方法排序（子类可覆写选优标准）
        sorted_candidates = self.rank_candidates(candidates)

        # 仓位计算：复用核心底层 PositionSizer，确保风控及 Kelly 公式准确执行
        from src.business.trading.models.decision import AccountState

        # 使用工厂方法构建 Sizer 实例 (带缓存)
        if self._position_sizer_instance is None:
            self._position_sizer_instance = self.build_position_sizer()

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

        max_new = self._max_new_positions_per_day
        signals = []
        for candidate in sorted_candidates[:max_new]:
            signal = self._build_entry_signal(candidate, account_state, context)
            if signal is not None:
                signals.append(signal)

        return signals
