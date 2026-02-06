"""
Backtest Executor - 回测执行器

执行完整的回测流程，协调三层组件架构:

组件架构 (BacktestExecutor 直接访问所有组件):
┌─────────────────────────────────────────────────────────────────────┐
│ BacktestExecutor (协调者)                                            │
│ - 协调三层组件                                                       │
│ - 控制回测流程                                                       │
│ - 可以直接访问任意组件                                                │
└─────────────────────────────────────────────────────────────────────┘
        ↓                    ↓                    ↓
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Trade 层    │    │ Position 层     │    │ Account 层      │
│ TradeSimu-  │    │ PositionManager │    │ AccountSimulator│
│ lator       │    │                 │    │                 │
│             │    │ - 创建持仓      │    │ - 现金管理      │
│ - 滑点计算  │    │ - 计算 margin   │    │ - 保证金检查    │
│ - 手续费    │    │ - 计算 PnL      │    │ - 持仓存储      │
│ - 交易记录  │    │ - 市场数据更新  │    │ - 权益快照      │
└─────────────┘    └─────────────────┘    └─────────────────┘

整合其他 Pipeline:
- ScreeningPipeline (寻找开仓机会)
- MonitoringPipeline (监控现有持仓)
- DecisionEngine (生成交易决策)

回测流程:
1. 初始化 DuckDBProvider、各 Pipeline
2. 逐日迭代交易日
3. 每日:
   a. 更新持仓价格 (Position 层更新，Account 层存储)
   b. 处理到期期权
   c. 运行 Monitoring 检查现有持仓
   d. 运行 Screening 寻找新机会
   e. 生成并执行交易决策
   f. 记录每日快照
4. 生成回测结果

Usage:
    from src.backtest import BacktestConfig, DuckDBProvider
    from src.backtest.engine import BacktestExecutor

    config = BacktestConfig.from_yaml("config/backtest/short_put.yaml")
    executor = BacktestExecutor(config)
    result = executor.run()
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from src.backtest.config.backtest_config import BacktestConfig, PriceMode
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.position_manager import PositionManager, DataNotFoundError
from src.backtest.engine.trade_simulator import TradeSimulator, TradeExecution, TradeRecord
from src.business.config.config_mode import ConfigMode
from src.business.config.monitoring_config import MonitoringConfig
from src.business.config.screening_config import ScreeningConfig
from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.config.risk_config import RiskConfig
from src.business.monitoring.models import PositionData
from src.business.monitoring.pipeline import MonitoringPipeline
from src.business.monitoring.suggestions import ActionType, PositionSuggestion
from src.business.screening.models import ContractOpportunity, MarketType, ScreeningResult
from src.business.screening.pipeline import ScreeningPipeline
from src.business.trading.decision.engine import DecisionEngine
from src.business.trading.models.decision import AccountState, DecisionType, TradingDecision
from src.data.models.option import OptionType
from src.engine.models.enums import StrategyType

logger = logging.getLogger(__name__)


@dataclass
class DailySnapshot:
    """每日快照"""

    date: date
    nlv: float
    cash: float
    positions_value: float
    margin_used: float
    unrealized_pnl: float
    realized_pnl_cumulative: float
    position_count: int

    # 当日活动
    trades_opened: int = 0
    trades_closed: int = 0
    trades_expired: int = 0
    daily_pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "nlv": self.nlv,
            "cash": self.cash,
            "positions_value": self.positions_value,
            "margin_used": self.margin_used,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl_cumulative": self.realized_pnl_cumulative,
            "position_count": self.position_count,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "trades_expired": self.trades_expired,
            "daily_pnl": self.daily_pnl,
        }


@dataclass
class BacktestResult:
    """回测结果"""

    # 基本信息
    config_name: str
    start_date: date
    end_date: date
    strategy_types: list[StrategyType]  # 支持多策略组合
    symbols: list[str]

    # 账户信息
    initial_capital: float
    final_nlv: float
    total_return: float
    total_return_pct: float

    # 交易统计
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float

    # 费用统计
    total_commission: float
    total_slippage: float

    # 时间序列
    daily_snapshots: list[DailySnapshot] = field(default_factory=list)
    trade_records: list[TradeRecord] = field(default_factory=list)
    executions: list[TradeExecution] = field(default_factory=list)

    # 执行信息
    execution_time_seconds: float = 0.0
    trading_days: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "config_name": self.config_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "strategy_types": [st.value for st in self.strategy_types],
            "symbols": self.symbols,
            "initial_capital": self.initial_capital,
            "final_nlv": self.final_nlv,
            "total_return": self.total_return,
            "total_return_pct": self.total_return_pct,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_commission": self.total_commission,
            "total_slippage": self.total_slippage,
            "execution_time_seconds": self.execution_time_seconds,
            "trading_days": self.trading_days,
            "errors": self.errors,
        }


class BacktestExecutor:
    """回测执行器

    整合所有回测组件，执行完整的策略回测。

    Usage:
        config = BacktestConfig.from_yaml("config/backtest/short_put.yaml")
        executor = BacktestExecutor(config)
        result = executor.run()
    """

    def __init__(
        self,
        config: BacktestConfig,
        data_provider: DuckDBProvider | None = None,
        progress_callback: Callable[[date, int, int], None] | None = None,
    ) -> None:
        """初始化回测执行器

        Args:
            config: 回测配置
            data_provider: 数据提供者 (可选，默认根据配置创建)
            progress_callback: 进度回调函数 (current_date, current_day, total_days)
        """
        self._config = config
        self._progress_callback = progress_callback

        # 初始化数据提供者
        self._data_provider = data_provider or DuckDBProvider(
            data_dir=config.data_dir,
            as_of_date=config.start_date,
        )

        # ========================================
        # 三层组件 (平等对待，BacktestExecutor 直接访问)
        # ========================================

        # Position 层: 持仓管理器 (不包装 Account)
        self._position_manager = PositionManager(
            data_provider=self._data_provider,
            price_mode=PriceMode(config.price_mode),
        )

        # Account 层: 账户模拟器 (直接持有)
        self._account_simulator = AccountSimulator(
            initial_capital=config.initial_capital,
            max_margin_utilization=config.max_margin_utilization,
        )

        # Trade 层: 交易模拟器 (使用 IBKR 真实费率)
        from src.backtest.engine.trade_simulator import CommissionModel

        commission_model = CommissionModel(
            option_per_contract=config.option_commission_per_contract,
            option_min_per_order=config.option_commission_min_per_order,
            stock_per_share=config.stock_commission_per_share,
            stock_min_per_order=config.stock_commission_min_per_order,
        )
        self._trade_simulator = TradeSimulator(
            slippage_pct=config.slippage_pct,
            commission_model=commission_model,
        )

        # 初始化 Pipelines (每个策略类型一个 ScreeningPipeline)
        self._screening_pipelines: dict[StrategyType, ScreeningPipeline] = {}
        self._monitoring_pipeline: MonitoringPipeline | None = None
        self._decision_engine: DecisionEngine | None = None

        # 状态
        self._current_date: date | None = None
        self._position_counter = 0
        self._daily_snapshots: list[DailySnapshot] = []
        self._errors: list[str] = []

    def _init_pipelines(self) -> None:
        """初始化 Pipeline 组件

        使用 BACKTEST 模式加载所有配置，并应用 BacktestConfig 中的覆盖。
        为每个策略类型创建独立的 ScreeningPipeline。
        """
        # Screening Pipelines (每个策略类型一个)
        # DuckDBProvider 实现了完整的 DataProvider 接口，可直接使用
        for strategy_type in self._config.strategy_types:
            try:
                # 使用 BACKTEST 模式加载配置
                screening_config = ScreeningConfig.load(
                    strategy=strategy_type.value,
                    mode=ConfigMode.BACKTEST,
                )
                # 应用 BacktestConfig 中的自定义覆盖
                if self._config.screening_overrides:
                    screening_config = ScreeningConfig.from_dict(
                        self._config.screening_overrides,
                        mode=ConfigMode.BACKTEST,
                    )
                pipeline = ScreeningPipeline(
                    config=screening_config,
                    provider=self._data_provider,  # DuckDBProvider 直接作为 DataProvider
                )
                self._screening_pipelines[strategy_type] = pipeline
                logger.info(f"ScreeningPipeline for {strategy_type.value} initialized with BACKTEST mode")
            except Exception as e:
                logger.warning(f"Failed to initialize ScreeningPipeline for {strategy_type.value}: {e}")

        # Monitoring Pipeline
        try:
            # 使用 BACKTEST 模式加载配置
            monitoring_config = MonitoringConfig.load(mode=ConfigMode.BACKTEST)
            # 应用 BacktestConfig 中的自定义覆盖
            if self._config.monitoring_overrides:
                monitoring_config = MonitoringConfig.from_dict(
                    self._config.monitoring_overrides,
                    mode=ConfigMode.BACKTEST,
                )
            self._monitoring_pipeline = MonitoringPipeline(config=monitoring_config)
            logger.info("MonitoringPipeline initialized with BACKTEST mode")
        except Exception as e:
            logger.warning(f"Failed to initialize MonitoringPipeline: {e}")
            self._monitoring_pipeline = None

        # Risk Config (用于 DecisionEngine)
        try:
            # 使用 BACKTEST 模式加载 RiskConfig
            risk_config = RiskConfig.load(mode=ConfigMode.BACKTEST)
            # 应用 BacktestConfig 中的自定义覆盖
            if self._config.risk_overrides:
                risk_config = RiskConfig.from_dict(
                    self._config.risk_overrides,
                    mode=ConfigMode.BACKTEST,
                )
            self._risk_config = risk_config
            logger.info(
                f"RiskConfig loaded with BACKTEST mode: "
                f"max_notional_pct={risk_config.max_notional_pct_per_underlying:.0%}"
            )
        except Exception as e:
            logger.warning(f"Failed to load RiskConfig: {e}")
            self._risk_config = RiskConfig()  # 使用默认值

        # Decision Engine
        try:
            # 使用 BACKTEST 模式创建 DecisionConfig，传入已加载的 RiskConfig
            decision_config = DecisionConfig.load(
                mode=ConfigMode.BACKTEST,
                risk_config=self._risk_config,
            )
            self._decision_engine = DecisionEngine(config=decision_config)
            logger.info(
                f"DecisionEngine initialized with BACKTEST mode: "
                f"max_notional_pct={decision_config.max_notional_pct_per_underlying:.0%}"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize DecisionEngine: {e}")
            self._decision_engine = None

    def run(self) -> BacktestResult:
        """执行回测

        Returns:
            BacktestResult
        """
        start_time = datetime.now()

        logger.info(f"Starting backtest: {self._config.name}")
        logger.info(f"  Period: {self._config.start_date} to {self._config.end_date}")
        logger.info(f"  Symbols: {', '.join(self._config.symbols)}")
        strategies_str = ", ".join(st.value for st in self._config.strategy_types)
        logger.info(f"  Strategies: {strategies_str}")
        logger.info(f"  Initial Capital: ${self._config.initial_capital:,.0f}")

        # 初始化 Pipelines
        self._init_pipelines()

        # 获取交易日列表
        trading_days = self._data_provider.get_trading_days(
            self._config.start_date,
            self._config.end_date,
        )

        if not trading_days:
            logger.error("No trading days found in date range")
            return self._build_empty_result(start_time)

        logger.info(f"Trading days: {len(trading_days)}")

        # 逐日执行
        total_days = len(trading_days)
        for i, current_date in enumerate(trading_days):
            try:
                self._run_single_day(current_date)

                # 进度回调
                if self._progress_callback:
                    self._progress_callback(current_date, i + 1, total_days)

            except Exception as e:
                error_msg = f"Error on {current_date}: {e}"
                logger.error(error_msg)
                self._errors.append(error_msg)

        # 构建结果
        execution_time = (datetime.now() - start_time).total_seconds()
        result = self._build_result(trading_days, execution_time)

        logger.info(f"Backtest completed in {execution_time:.1f}s")
        logger.info(f"  Final NLV: ${result.final_nlv:,.2f}")
        logger.info(f"  Total Return: {result.total_return_pct:.2%}")
        logger.info(f"  Win Rate: {result.win_rate:.1%}")
        logger.info(f"  Total Trades: {result.total_trades}")

        return result

    def _run_single_day(self, current_date: date) -> None:
        """执行单日回测

        Args:
            current_date: 当前日期
        """
        self._current_date = current_date
        self._position_manager.set_date(current_date)

        # 更新数据提供者日期
        self._data_provider.set_as_of_date(current_date)

        # 记录前一日 NLV (用于计算当日盈亏)
        prev_nlv = self._account_simulator.nlv

        # 1. 更新持仓价格 (Position 层更新，Account 层存储)
        self._position_manager.update_all_positions_market_data(
            self._account_simulator.positions
        )

        # 2. 处理到期期权
        self._process_expirations(current_date)

        # 3. 运行监控 (如果有持仓)
        suggestions: list[PositionSuggestion] = []
        if self._account_simulator.position_count > 0 and self._monitoring_pipeline:
            suggestions = self._run_monitoring()

        # 4. 运行筛选 (寻找新机会)
        screen_result: ScreeningResult | None = None
        if self._can_open_new_positions() and self._screening_pipelines:
            screen_result = self._run_screening(current_date)

        # 5. 生成并执行决策
        trades_opened = 0
        trades_closed = 0

        if self._decision_engine:
            account_state = self._account_simulator.get_account_state()
            decisions = self._decision_engine.process_batch(
                screen_result=screen_result,
                account_state=account_state,
                suggestions=suggestions,
            )

            # 执行决策
            for decision in decisions:
                if decision.decision_type == DecisionType.OPEN:
                    if self._execute_open_decision(decision, current_date):
                        trades_opened += 1
                elif decision.decision_type == DecisionType.CLOSE:
                    if self._execute_close_decision(decision, current_date):
                        trades_closed += 1
                elif decision.decision_type == DecisionType.ROLL:
                    # Roll = Close + Open (参考 OrderGenerator.generate_roll)
                    closed, opened = self._execute_roll_decision(decision, current_date)
                    if closed:
                        trades_closed += 1
                    if opened:
                        trades_opened += 1

        # 6. 记录每日快照
        snapshot = self._take_daily_snapshot(current_date, prev_nlv)
        snapshot.trades_opened = trades_opened
        snapshot.trades_closed = trades_closed
        self._daily_snapshots.append(snapshot)

        logger.debug(
            f"{current_date}: NLV=${snapshot.nlv:,.0f}, "
            f"positions={snapshot.position_count}, "
            f"opened={trades_opened}, closed={trades_closed}"
        )

    def _process_expirations(self, current_date: date) -> None:
        """处理到期期权

        Args:
            current_date: 当前日期

        Raises:
            DataNotFoundError: 当无法获取到期时的标的价格时抛出
        """
        # Position 层: 检查到期 (从 Account 层获取持仓)
        expiring = self._position_manager.check_expirations(
            self._account_simulator.positions
        )

        for position in expiring:
            # 获取标的价格 - 数据缺失时抛出异常，不使用 strike 回退
            quote = self._data_provider.get_stock_quote(position.underlying)
            if quote is None:
                raise DataNotFoundError(
                    f"Stock quote not found for {position.underlying} "
                    f"on expiration date {current_date}"
                )

            # 根据 price_mode 获取价格
            price_mode = PriceMode(self._config.price_mode)
            if price_mode == PriceMode.OPEN:
                final_price = quote.open
            elif price_mode == PriceMode.MID:
                final_price = (quote.open + quote.close) / 2 if quote.open and quote.close else quote.close
            else:
                final_price = quote.close

            if final_price is None or final_price <= 0:
                raise DataNotFoundError(
                    f"Invalid price for {position.underlying} on {current_date}: "
                    f"mode={price_mode.value}, quote={quote}"
                )

            # 1. Trade 层：执行到期处理
            execution = self._trade_simulator.execute_expire(
                symbol=position.symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=position.strike,
                expiration=position.expiration,
                quantity=position.quantity,  # 有符号
                final_underlying_price=final_price,
                trade_date=current_date,
                lot_size=position.lot_size,
            )

            # 2. Position 层：计算已实现盈亏
            pnl = self._position_manager.calculate_realized_pnl(position, execution)

            # 3. Account 层：移除持仓，更新现金
            success = self._account_simulator.remove_position(
                position_id=position.position_id,
                cash_change=execution.net_amount,
                realized_pnl=pnl,
            )

            if success:
                # 完成持仓关闭 (更新持仓字段)
                self._position_manager.finalize_close(position, execution, pnl)

                logger.info(
                    f"Position {position.position_id} expired on {current_date}: "
                    f"entry_price=${position.entry_price:.4f} -> close_price=${position.close_price:.4f}, "
                    f"reason={execution.reason}, PnL: ${pnl:.2f}"
                )

    def _run_monitoring(self) -> list[PositionSuggestion]:
        """运行持仓监控

        Returns:
            调整建议列表
        """
        if not self._monitoring_pipeline:
            return []

        try:
            # Position 层: 转换持仓数据 (从 Account 层获取)
            position_data = self._position_manager.get_position_data_for_monitoring(
                positions=self._account_simulator.positions,
                as_of_date=self._current_date,
            )

            if not position_data:
                return []

            # 运行监控 (Account 层提供 NLV)
            result = self._monitoring_pipeline.run(
                positions=position_data,
                nlv=self._account_simulator.nlv,
            )

            # 只返回需要行动的建议
            actionable = [
                s for s in result.suggestions
                if s.action not in (ActionType.HOLD, ActionType.MONITOR, ActionType.REVIEW)
            ]

            return actionable

        except Exception as e:
            logger.warning(f"Monitoring failed: {e}")
            return []

    def _run_screening(self, current_date: date) -> ScreeningResult | None:
        """运行所有策略的筛选，寻找新机会

        为每个策略类型运行对应的 ScreeningPipeline，
        然后合并所有结果到一个 ScreeningResult。

        Args:
            current_date: 当前日期

        Returns:
            合并后的筛选结果 (包含所有策略的机会)
        """
        if not self._screening_pipelines:
            return None

        all_opportunities: list[ContractOpportunity] = []

        # 为每个策略类型运行筛选
        for strategy_type, pipeline in self._screening_pipelines.items():
            try:
                result = pipeline.run(
                    symbols=self._config.symbols,
                    market_type=MarketType.US,  # TODO: 支持 HK
                    strategy_type=strategy_type,
                    skip_market_check=True,  # 回测中跳过市场环境检查
                )

                if result and result.opportunities:
                    all_opportunities.extend(result.opportunities)
                    logger.debug(
                        f"[{strategy_type.value}] Found {len(result.opportunities)} opportunities"
                    )

            except Exception as e:
                logger.warning(f"Screening failed for {strategy_type.value}: {e}")

        # 如果没有机会，返回 None
        if not all_opportunities:
            return None

        # 创建合并后的 ScreeningResult
        # 使用第一个策略类型作为代表 (仅用于满足 dataclass 要求)
        primary_strategy = self._config.strategy_types[0]
        return ScreeningResult(
            passed=True,
            strategy_type=primary_strategy,
            opportunities=all_opportunities,
            confirmed=all_opportunities,  # DecisionEngine 使用 confirmed 字段
            scanned_underlyings=len(self._config.symbols),
            qualified_contracts=len(all_opportunities),
        )

    def _can_open_new_positions(self) -> bool:
        """检查是否可以开新仓

        Returns:
            True 如果可以开新仓
        """
        # 检查持仓数量限制 (Account 层)
        if self._account_simulator.position_count >= self._config.max_positions:
            return False

        # 检查保证金使用率 (Account 层)
        account_state = self._account_simulator.get_account_state()
        if account_state.margin_utilization >= self._config.max_margin_utilization:
            return False

        return True

    def _execute_open_decision(
        self,
        decision: TradingDecision,
        trade_date: date,
    ) -> bool:
        """执行开仓决策

        使用重构后的流程:
        1. Trade 层 (TradeSimulator): 计算滑点、手续费、金额 → TradeExecution
        2. Position 层 (PositionTracker): 创建 Position，计算 margin → SimulatedPosition
        3. Account 层 (AccountSimulator): 检查保证金，更新现金

        Args:
            decision: 交易决策
            trade_date: 交易日期

        Returns:
            是否成功
        """
        try:
            # 解析期权信息
            underlying = decision.underlying
            # 转换 option_type 字符串到 OptionType 枚举
            option_type_str = decision.option_type or "put"
            option_type = OptionType(option_type_str.lower())
            strike = decision.strike or 0.0
            expiry = date.fromisoformat(decision.expiry) if decision.expiry else trade_date

            # 1. Trade 层：执行交易，得到 TradeExecution
            mid_price = decision.limit_price or 0.0
            execution = self._trade_simulator.execute_open(
                symbol=decision.symbol,
                underlying=underlying,
                option_type=option_type,
                strike=strike,
                expiration=expiry,
                quantity=decision.quantity,
                mid_price=mid_price,
                trade_date=trade_date,
                reason="screening_signal",
                lot_size=decision.contract_multiplier,  # 直接传入，None 时使用默认值
            )

            # 2. Position 层：基于 TradeExecution 创建持仓对象
            position = self._position_manager.create_position(execution)

            # 3. Account 层：检查保证金，添加持仓
            success = self._account_simulator.add_position(
                position=position,
                cash_change=execution.net_amount,
            )

            return success

        except Exception as e:
            logger.error(f"Failed to execute open decision: {e}")
            return False

    def _execute_close_decision(
        self,
        decision: TradingDecision,
        trade_date: date,
    ) -> bool:
        """执行平仓决策

        Args:
            decision: 交易决策
            trade_date: 交易日期

        Returns:
            是否成功
        """
        try:
            # 查找对应持仓
            position = self._find_position_for_decision(decision)
            if not position:
                logger.warning(f"Position not found for close decision: {decision.symbol}")
                return False

            # 获取当前期权价格
            option_price = self._get_current_option_price(position)
            if option_price is None:
                option_price = position.current_price

            # 1. Trade 层：模拟交易执行
            execution = self._trade_simulator.execute_close(
                symbol=position.symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=position.strike,
                expiration=position.expiration,
                quantity=-position.quantity,  # 平仓方向相反
                mid_price=option_price,
                trade_date=trade_date,
                reason=decision.reason or "monitor_signal",
            )

            # 2. Position 层：计算已实现盈亏
            pnl = self._position_manager.calculate_realized_pnl(
                position=position,
                execution=execution,
                close_reason=decision.reason or "monitor_signal",
            )

            # 3. Account 层：移除持仓，更新现金
            success = self._account_simulator.remove_position(
                position_id=position.position_id,
                cash_change=execution.net_amount,
                realized_pnl=pnl,
            )

            if success:
                # 完成持仓关闭 (更新持仓字段)
                self._position_manager.finalize_close(
                    position, execution, pnl, decision.reason or "monitor_signal"
                )

            return success

        except Exception as e:
            logger.error(f"Failed to execute close decision: {e}")
            return False

    def _execute_roll_decision(
        self,
        decision: TradingDecision,
        trade_date: date,
    ) -> tuple[bool, bool]:
        """执行展期决策 (参考 OrderGenerator.generate_roll)

        展期操作 = 平仓当前合约 + 开仓新合约

        Args:
            decision: ROLL 类型的交易决策
                - symbol/expiry/strike: 当前合约信息
                - roll_to_expiry: 新到期日
                - roll_to_strike: 新行权价 (None 表示保持不变)
                - quantity: 平仓数量
            trade_date: 交易日期

        Returns:
            (close_success, open_success) - 平仓和开仓是否成功
        """
        close_success = False
        open_success = False

        try:
            # 验证展期参数
            if not decision.roll_to_expiry:
                logger.warning(f"ROLL decision missing roll_to_expiry: {decision.decision_id}")
                return False, False

            # ========================================
            # 1. 平仓当前合约 (BUY to close)
            # ========================================
            position = self._find_position_for_decision(decision)
            if not position:
                logger.warning(f"Position not found for roll decision: {decision.symbol}")
                return False, False

            # 获取当前期权价格
            close_price = self._get_current_option_price(position)
            if close_price is None:
                close_price = position.current_price
            if close_price is None or close_price <= 0:
                # 使用 entry_price 作为最后的回退（保守估计）
                logger.warning(
                    f"No valid close price found for {position.symbol}, "
                    f"using entry_price={position.entry_price} as fallback"
                )
                close_price = position.entry_price

            # 1. Trade 层：模拟平仓执行
            close_execution = self._trade_simulator.execute_close(
                symbol=position.symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=position.strike,
                expiration=position.expiration,
                quantity=-position.quantity,  # BUY to close
                mid_price=close_price,
                trade_date=trade_date,
                reason=f"roll_close: {decision.reason or 'rolling to new expiry'}",
            )

            # 2. Position 层：计算已实现盈亏
            pnl = self._position_manager.calculate_realized_pnl(
                position=position,
                execution=close_execution,
                close_reason=f"roll_to_{decision.roll_to_expiry}",
            )

            # 3. Account 层：移除持仓
            close_success = self._account_simulator.remove_position(
                position_id=position.position_id,
                cash_change=close_execution.net_amount,
                realized_pnl=pnl,
            )

            if close_success:
                self._position_manager.finalize_close(
                    position, close_execution, pnl, f"roll_to_{decision.roll_to_expiry}"
                )
            if not close_success:
                logger.error(f"Failed to close position for roll: {position.position_id}")
                return False, False

            logger.info(
                f"Roll close: {position.symbol} @ {close_execution.fill_price:.2f}, "
                f"PnL: ${pnl:.2f}"
            )

            # ========================================
            # 2. 开仓新合约 (SELL to open)
            # ========================================
            new_expiry = date.fromisoformat(decision.roll_to_expiry)
            new_strike = decision.roll_to_strike or position.strike  # 默认保持行权价不变

            # 构建新合约 symbol
            new_symbol = self._build_roll_symbol(
                underlying=position.underlying,
                expiry=new_expiry,
                strike=new_strike,
                option_type=position.option_type,
            )

            # 获取新合约价格
            new_option_price = self._get_option_price_by_params(
                underlying=position.underlying,
                option_type=position.option_type,
                strike=new_strike,
                expiration=new_expiry,
            )

            if new_option_price is None or new_option_price <= 0:
                logger.warning(
                    f"Cannot get price for new contract {new_symbol}, "
                    f"using roll_credit or estimated price"
                )
                # 使用 roll_credit 估算或基于旧合约价格估算
                new_option_price = decision.roll_credit or close_price * 1.1

            # 模拟开仓执行
            open_execution = self._trade_simulator.execute_open(
                symbol=new_symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=new_strike,
                expiration=new_expiry,
                quantity=position.quantity,  # 保持相同数量 (负数 = SELL to open)
                mid_price=new_option_price,
                trade_date=trade_date,
                reason=f"roll_open: new expiry {decision.roll_to_expiry}",
                lot_size=position.lot_size,  # 保持与原持仓相同
            )

            # Position 层: 创建持仓对象
            new_position = self._position_manager.create_position(open_execution)

            # Account 层: 添加持仓
            open_success = self._account_simulator.add_position(
                position=new_position,
                cash_change=open_execution.net_amount,
            )
            if open_success:
                logger.info(
                    f"Roll open: {new_symbol} @ {open_execution.fill_price:.2f}, "
                    f"qty={new_position.quantity}"
                )
            else:
                logger.error(f"Failed to open new position for roll: {new_symbol}")

            return close_success, open_success

        except Exception as e:
            logger.error(f"Failed to execute roll decision: {e}")
            return close_success, open_success

    def _build_roll_symbol(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        option_type: OptionType,
    ) -> str:
        """构建展期新合约的 symbol

        格式: UNDERLYING YYMMDDCP00STRIKE (OCC 格式)
        示例: MSFT 250228P00380000
        """
        # 转换日期格式: date -> YYMMDD
        expiry_short = expiry.strftime("%y%m%d")

        # 期权类型: PUT -> P, CALL -> C
        opt_char = "P" if option_type == OptionType.PUT else "C"

        # 行权价: 填充到 8 位 (整数部分 5 位 + 小数部分 3 位)
        strike_str = f"{int(strike * 1000):08d}"

        # 获取纯 underlying (去除 .HK 等后缀)
        pure_underlying = underlying.split(".")[0] if "." in underlying else underlying

        return f"{pure_underlying} {expiry_short}{opt_char}{strike_str}"

    def _get_option_price_by_params(
        self,
        underlying: str,
        option_type: OptionType,
        strike: float,
        expiration: date,
    ) -> float | None:
        """根据参数获取期权价格

        Args:
            underlying: 标的代码
            option_type: 期权类型 (OptionType.PUT/CALL)
            strike: 行权价
            expiration: 到期日

        Returns:
            期权价格或 None
        """
        try:
            chain = self._data_provider.get_option_chain(
                underlying=underlying,
                expiry_start=expiration,
                expiry_end=expiration,
            )

            if chain is None:
                return None

            contracts = chain.puts if option_type == OptionType.PUT else chain.calls

            # 根据 price_mode 获取价格
            price_mode = PriceMode(self._config.price_mode)

            for contract in contracts:
                if (
                    contract.contract.strike_price == strike
                    and contract.contract.expiry_date == expiration
                ):
                    if price_mode == PriceMode.OPEN:
                        return contract.open or contract.last_price
                    elif price_mode == PriceMode.MID:
                        if contract.bid and contract.ask:
                            return (contract.bid + contract.ask) / 2
                        return contract.last_price
                    else:  # CLOSE
                        return contract.close or contract.last_price

            return None

        except Exception as e:
            logger.warning(f"Failed to get option price: {e}")
            return None

    def _find_position_for_decision(
        self,
        decision: TradingDecision,
    ) -> SimulatedPosition | None:
        """根据决策查找对应持仓

        Args:
            decision: 交易决策

        Returns:
            SimulatedPosition 或 None
        """
        # 尝试按 underlying + strike + expiry 匹配 (从 Account 层获取持仓)
        for position in self._account_simulator.positions.values():
            if (
                position.underlying == decision.underlying
                and position.strike == decision.strike
                and position.expiration.isoformat() == decision.expiry
            ):
                return position

        # 尝试按 symbol 匹配
        for position in self._account_simulator.positions.values():
            if decision.underlying in position.symbol:
                return position

        return None

    def _get_current_option_price(
        self,
        position: SimulatedPosition,
    ) -> float | None:
        """获取期权当前价格

        Args:
            position: 持仓

        Returns:
            期权价格
        """
        try:
            chain = self._data_provider.get_option_chain(
                underlying=position.underlying,
                expiry_start=position.expiration,
                expiry_end=position.expiration,
            )

            if chain is None:
                return None

            contracts = chain.puts if position.option_type == OptionType.PUT else chain.calls

            for quote in contracts:
                # OptionQuote.contract 包含合约信息
                contract = quote.contract
                if (
                    contract.strike_price == position.strike
                    and contract.expiry_date == position.expiration
                ):
                    # 优先使用 close 价格，否则使用 last_price
                    return quote.close if quote.close is not None else quote.last_price

            return None

        except Exception:
            return None

    def _take_daily_snapshot(
        self,
        current_date: date,
        prev_nlv: float,
    ) -> DailySnapshot:
        """记录每日快照

        Args:
            current_date: 当前日期
            prev_nlv: 前一日 NLV

        Returns:
            DailySnapshot
        """
        # Account 层: 记录快照
        equity_snapshot = self._account_simulator.take_snapshot(current_date)

        return DailySnapshot(
            date=current_date,
            nlv=equity_snapshot.nlv,
            cash=equity_snapshot.cash,
            positions_value=equity_snapshot.positions_value,
            margin_used=equity_snapshot.margin_used,
            unrealized_pnl=equity_snapshot.unrealized_pnl,
            realized_pnl_cumulative=equity_snapshot.realized_pnl_cumulative,
            position_count=equity_snapshot.position_count,
            daily_pnl=equity_snapshot.nlv - prev_nlv,
        )

    def _build_result(
        self,
        trading_days: list[date],
        execution_time: float,
    ) -> BacktestResult:
        """构建回测结果

        Args:
            trading_days: 交易日列表
            execution_time: 执行时间 (秒)

        Returns:
            BacktestResult
        """
        # 从 AccountSimulator 的已平仓持仓计算交易统计
        closed_positions = self._account_simulator.closed_positions

        winning_trades = sum(
            1 for p in closed_positions
            if p.realized_pnl is not None and p.realized_pnl > 0
        )
        losing_trades = sum(
            1 for p in closed_positions
            if p.realized_pnl is not None and p.realized_pnl <= 0
        )
        total_trades = winning_trades + losing_trades

        # 计算 profit factor
        gross_profit = sum(
            p.realized_pnl for p in closed_positions
            if p.realized_pnl is not None and p.realized_pnl > 0
        )
        gross_loss = abs(sum(
            p.realized_pnl for p in closed_positions
            if p.realized_pnl is not None and p.realized_pnl < 0
        ))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # 总回报 (Account 层)
        final_nlv = self._account_simulator.nlv
        total_return = final_nlv - self._config.initial_capital
        total_return_pct = total_return / self._config.initial_capital

        # 使用 TradeSimulator 记录的所有交易 (包括未平仓的开仓记录)
        # TradeSimulator 在每次 execute_open/execute_close/execute_expire 时都会创建记录
        trade_records = self._trade_simulator.trade_records

        return BacktestResult(
            config_name=self._config.name,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
            strategy_types=self._config.strategy_types,
            symbols=self._config.symbols,
            initial_capital=self._config.initial_capital,
            final_nlv=final_nlv,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=winning_trades / total_trades if total_trades > 0 else 0.0,
            profit_factor=profit_factor,
            total_commission=self._trade_simulator.get_total_commission(),
            total_slippage=self._trade_simulator.get_total_slippage(),
            daily_snapshots=self._daily_snapshots,
            trade_records=trade_records,
            executions=self._trade_simulator.executions,
            execution_time_seconds=execution_time,
            trading_days=len(trading_days),
            errors=self._errors,
        )

    def _build_empty_result(self, start_time: datetime) -> BacktestResult:
        """构建空结果 (无交易日时)

        Args:
            start_time: 开始时间

        Returns:
            BacktestResult
        """
        execution_time = (datetime.now() - start_time).total_seconds()

        return BacktestResult(
            config_name=self._config.name,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
            strategy_types=self._config.strategy_types,
            symbols=self._config.symbols,
            initial_capital=self._config.initial_capital,
            final_nlv=self._config.initial_capital,
            total_return=0.0,
            total_return_pct=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            total_commission=0.0,
            total_slippage=0.0,
            execution_time_seconds=execution_time,
            trading_days=0,
            errors=["No trading days found in date range"],
        )

    def get_equity_curve(self) -> list[tuple[date, float]]:
        """获取权益曲线

        Returns:
            [(date, nlv), ...]
        """
        return [(s.date, s.nlv) for s in self._daily_snapshots]

    def get_drawdown_curve(self) -> list[tuple[date, float]]:
        """获取回撤曲线

        Returns:
            [(date, drawdown_pct), ...]
        """
        if not self._daily_snapshots:
            return []

        max_nlv = self._daily_snapshots[0].nlv
        drawdowns = []

        for snapshot in self._daily_snapshots:
            max_nlv = max(max_nlv, snapshot.nlv)
            drawdown = (max_nlv - snapshot.nlv) / max_nlv if max_nlv > 0 else 0.0
            drawdowns.append((snapshot.date, drawdown))

        return drawdowns

    def _generate_trade_records(
        self,
        closed_positions: list[SimulatedPosition],
    ) -> list[TradeRecord]:
        """从已平仓持仓生成 TradeRecord

        为每个已平仓持仓生成开仓和平仓两条记录。

        Args:
            closed_positions: 已平仓持仓列表

        Returns:
            TradeRecord 列表 (按日期排序)
        """
        trade_records = []
        for pos in closed_positions:
            # === 1. 生成开仓记录 ===
            # 计算开仓金额
            # 空头卖出: 收取权利金 (正现金流)
            # 多头买入: 支付权利金 (负现金流)
            entry_gross = pos.entry_price * abs(pos.quantity) * pos.lot_size
            if pos.is_short:
                entry_gross = entry_gross  # 卖出收取权利金
            else:
                entry_gross = -entry_gross  # 买入支付权利金

            open_record = TradeRecord(
                trade_id=f"TR-{pos.position_id}-OPEN",
                execution_id=f"EX-{pos.position_id}-OPEN",
                symbol=pos.symbol,
                underlying=pos.underlying,
                option_type=pos.option_type,
                strike=pos.strike,
                expiration=pos.expiration,
                trade_date=pos.entry_date,
                action="open",
                quantity=pos.quantity,  # 原始数量 (负=卖出, 正=买入)
                price=pos.entry_price,
                commission=pos.commission_paid / 2,  # 开平仓手续费平分
                gross_amount=entry_gross,
                net_amount=entry_gross - pos.commission_paid / 2,
                pnl=None,  # 开仓无盈亏
                position_id=pos.position_id,
            )
            trade_records.append(open_record)

            # === 2. 生成平仓记录 ===
            if pos.close_date is None or pos.close_price is None:
                continue

            # 计算平仓金额
            # 空头买回: 支付权利金 (负现金流)
            # 多头卖出: 收取权利金 (正现金流)
            close_gross = pos.close_price * abs(pos.quantity) * pos.lot_size
            if pos.is_short:
                close_gross = -close_gross  # 买回支付权利金
            else:
                close_gross = close_gross  # 卖出收取权利金

            # 判断平仓类型
            close_action = "close"
            if pos.close_reason and "expire" in pos.close_reason.lower():
                close_action = "expire"

            close_record = TradeRecord(
                trade_id=f"TR-{pos.position_id}-CLOSE",
                execution_id=f"EX-{pos.position_id}-CLOSE",
                symbol=pos.symbol,
                underlying=pos.underlying,
                option_type=pos.option_type,
                strike=pos.strike,
                expiration=pos.expiration,
                trade_date=pos.close_date,
                action=close_action,
                quantity=-pos.quantity,  # 平仓方向相反
                price=pos.close_price,
                commission=pos.commission_paid / 2,  # 开平仓手续费平分
                gross_amount=close_gross,
                net_amount=close_gross - pos.commission_paid / 2,
                pnl=pos.realized_pnl,
                reason=pos.close_reason,
                position_id=pos.position_id,
            )
            trade_records.append(close_record)

        # 按日期排序
        trade_records.sort(key=lambda r: r.trade_date)
        return trade_records

    def reset(self) -> None:
        """重置执行器状态"""
        self._position_manager.reset()
        self._account_simulator.reset()
        self._trade_simulator.reset()
        self._daily_snapshots.clear()
        self._errors.clear()
        self._position_counter = 0
        self._current_date = None


def run_backtest(
    config_path: str,
    progress_callback: Callable[[date, int, int], None] | None = None,
) -> BacktestResult:
    """运行回测的便捷函数

    Args:
        config_path: 配置文件路径
        progress_callback: 进度回调

    Returns:
        BacktestResult
    """
    config = BacktestConfig.from_yaml(config_path)
    executor = BacktestExecutor(config, progress_callback=progress_callback)
    return executor.run()
