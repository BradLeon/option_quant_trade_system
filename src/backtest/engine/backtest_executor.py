"""
Backtest Executor - 回测执行器

执行完整的回测流程，整合:
- ScreeningPipeline (寻找开仓机会)
- MonitoringPipeline (监控现有持仓)
- DecisionEngine (生成交易决策)
- PositionTracker (追踪持仓和账户)
- TradeSimulator (模拟交易执行)

回测流程:
1. 初始化 DuckDBProvider、各 Pipeline
2. 逐日迭代交易日
3. 每日:
   a. 更新持仓价格
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

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.account_simulator import SimulatedPosition
from src.backtest.engine.position_tracker import PositionTracker, TradeRecord
from src.backtest.engine.trade_simulator import TradeSimulator, TradeExecution
from src.business.config.monitoring_config import MonitoringConfig
from src.business.config.screening_config import ScreeningConfig
from src.business.monitoring.models import PositionData
from src.business.monitoring.pipeline import MonitoringPipeline
from src.business.monitoring.suggestions import ActionType, PositionSuggestion
from src.business.screening.models import ContractOpportunity, MarketType, ScreeningResult
from src.business.screening.pipeline import ScreeningPipeline
from src.business.trading.decision.engine import DecisionEngine
from src.business.trading.models.decision import AccountState, DecisionType, TradingDecision
from src.data.providers.unified_provider import UnifiedDataProvider
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
    strategy_type: StrategyType
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
            "strategy_type": self.strategy_type.value,
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

        # 初始化持仓追踪器
        self._position_tracker = PositionTracker(
            data_provider=self._data_provider,
            initial_capital=config.initial_capital,
            max_margin_utilization=config.max_margin_utilization,
        )

        # 初始化交易模拟器
        self._trade_simulator = TradeSimulator(
            slippage_pct=config.slippage_pct,
            commission_per_contract=config.commission_per_contract,
        )

        # 初始化 Pipelines
        self._screening_pipeline: ScreeningPipeline | None = None
        self._monitoring_pipeline: MonitoringPipeline | None = None
        self._decision_engine: DecisionEngine | None = None

        # 状态
        self._current_date: date | None = None
        self._position_counter = 0
        self._daily_snapshots: list[DailySnapshot] = []
        self._errors: list[str] = []

    def _init_pipelines(self) -> None:
        """初始化 Pipeline 组件"""
        # Screening Pipeline
        try:
            screening_config = ScreeningConfig.load(
                self._config.strategy_type.value
            )
            # 创建 UnifiedDataProvider 包装 DuckDBProvider
            unified_provider = UnifiedDataProvider(
                us_provider=self._data_provider,
                hk_provider=None,
            )
            self._screening_pipeline = ScreeningPipeline(
                config=screening_config,
                provider=unified_provider,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize ScreeningPipeline: {e}")
            self._screening_pipeline = None

        # Monitoring Pipeline
        try:
            monitoring_config = MonitoringConfig.load()
            self._monitoring_pipeline = MonitoringPipeline(config=monitoring_config)
        except Exception as e:
            logger.warning(f"Failed to initialize MonitoringPipeline: {e}")
            self._monitoring_pipeline = None

        # Decision Engine
        try:
            self._decision_engine = DecisionEngine()
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
        logger.info(f"  Strategy: {self._config.strategy_type.value}")
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
        self._position_tracker.set_date(current_date)

        # 更新数据提供者日期
        self._data_provider.set_as_of_date(current_date)

        # 记录前一日 NLV (用于计算当日盈亏)
        prev_nlv = self._position_tracker.nlv

        # 1. 更新持仓价格
        self._position_tracker.update_positions_from_market()

        # 2. 处理到期期权
        self._process_expirations(current_date)

        # 3. 运行监控 (如果有持仓)
        suggestions: list[PositionSuggestion] = []
        if self._position_tracker.position_count > 0 and self._monitoring_pipeline:
            suggestions = self._run_monitoring()

        # 4. 运行筛选 (寻找新机会)
        screen_result: ScreeningResult | None = None
        if self._can_open_new_positions() and self._screening_pipeline:
            screen_result = self._run_screening(current_date)

        # 5. 生成并执行决策
        trades_opened = 0
        trades_closed = 0

        if self._decision_engine:
            account_state = self._position_tracker.get_account_state()
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
                    # Roll = Close + Open
                    if self._execute_close_decision(decision, current_date):
                        trades_closed += 1
                    # TODO: 实现 roll 的开仓部分

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
        """
        expiring = self._position_tracker.check_expirations()

        for position in expiring:
            try:
                # 获取标的价格
                quote = self._data_provider.get_stock_quote(position.underlying)
                if quote:
                    final_price = quote.close or quote.last or position.strike
                else:
                    final_price = position.strike

                # 处理到期
                pnl = self._position_tracker.expire_position(
                    position.position_id,
                    current_date,
                    final_price,
                )

                if pnl is not None:
                    logger.info(
                        f"Position {position.position_id} expired on {current_date}, "
                        f"PnL: ${pnl:.2f}"
                    )

            except Exception as e:
                logger.error(f"Error processing expiration for {position.position_id}: {e}")

    def _run_monitoring(self) -> list[PositionSuggestion]:
        """运行持仓监控

        Returns:
            调整建议列表
        """
        if not self._monitoring_pipeline:
            return []

        try:
            # 获取持仓数据
            position_data = self._position_tracker.get_position_data_for_monitoring(
                as_of_date=self._current_date
            )

            if not position_data:
                return []

            # 运行监控
            result = self._monitoring_pipeline.run(
                positions=position_data,
                nlv=self._position_tracker.nlv,
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
        """运行筛选寻找新机会

        Args:
            current_date: 当前日期

        Returns:
            筛选结果
        """
        if not self._screening_pipeline:
            return None

        try:
            result = self._screening_pipeline.run(
                symbols=self._config.symbols,
                market_type=MarketType.US,  # TODO: 支持 HK
                strategy_type=self._config.strategy_type,
                skip_market_check=True,  # 回测中跳过市场环境检查
            )

            return result

        except Exception as e:
            logger.warning(f"Screening failed: {e}")
            return None

    def _can_open_new_positions(self) -> bool:
        """检查是否可以开新仓

        Returns:
            True 如果可以开新仓
        """
        # 检查持仓数量限制
        if self._position_tracker.position_count >= self._config.max_positions:
            return False

        # 检查保证金使用率
        account_state = self._position_tracker.get_account_state()
        if account_state.margin_utilization >= self._config.max_margin_utilization:
            return False

        return True

    def _execute_open_decision(
        self,
        decision: TradingDecision,
        trade_date: date,
    ) -> bool:
        """执行开仓决策

        Args:
            decision: 交易决策
            trade_date: 交易日期

        Returns:
            是否成功
        """
        try:
            # 解析期权信息
            underlying = decision.underlying
            option_type = decision.option_type or "put"
            strike = decision.strike or 0.0
            expiry = date.fromisoformat(decision.expiry) if decision.expiry else trade_date

            # 模拟交易执行
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
            )

            # 创建模拟持仓
            self._position_counter += 1
            position = SimulatedPosition(
                position_id=f"P{self._position_counter:06d}",
                symbol=decision.symbol,
                underlying=underlying,
                option_type=option_type,
                strike=strike,
                expiration=expiry,
                quantity=decision.quantity,
                entry_price=execution.fill_price,
                entry_date=trade_date,
                lot_size=decision.contract_multiplier or 100,
            )

            # 添加到持仓追踪器
            success = self._position_tracker.open_position(
                position,
                commission=execution.commission / abs(decision.quantity) if decision.quantity else 0,
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

            # 模拟交易执行
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

            # 平仓
            pnl = self._position_tracker.close_position(
                position.position_id,
                close_price=execution.fill_price,
                close_date=trade_date,
                close_reason=decision.reason or "monitor_signal",
                commission=execution.commission / abs(position.quantity) if position.quantity else 0,
            )

            return pnl is not None

        except Exception as e:
            logger.error(f"Failed to execute close decision: {e}")
            return False

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
        # 尝试按 underlying + strike + expiry 匹配
        for position in self._position_tracker.positions.values():
            if (
                position.underlying == decision.underlying
                and position.strike == decision.strike
                and position.expiration.isoformat() == decision.expiry
            ):
                return position

        # 尝试按 symbol 匹配
        for position in self._position_tracker.positions.values():
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

            contracts = chain.puts if position.option_type == "put" else chain.calls

            for contract in contracts:
                if (
                    contract.strike == position.strike
                    and contract.expiry.date() == position.expiration
                ):
                    return contract.close if hasattr(contract, 'close') else contract.last

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
        equity_snapshot = self._position_tracker.take_snapshot(current_date)

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
        # 交易统计
        trade_summary = self._position_tracker.get_trade_summary()

        # 计算盈亏相关指标
        winning_trades = trade_summary["winning_trades"]
        losing_trades = trade_summary["losing_trades"]
        total_trades = winning_trades + losing_trades

        # 计算 profit factor
        gross_profit = sum(
            t.pnl for t in self._position_tracker.trade_records
            if t.pnl and t.pnl > 0
        )
        gross_loss = abs(sum(
            t.pnl for t in self._position_tracker.trade_records
            if t.pnl and t.pnl < 0
        ))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # 总回报
        final_nlv = self._position_tracker.nlv
        total_return = final_nlv - self._config.initial_capital
        total_return_pct = total_return / self._config.initial_capital

        return BacktestResult(
            config_name=self._config.name,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
            strategy_type=self._config.strategy_type,
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
            trade_records=self._position_tracker.trade_records,
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
            strategy_type=self._config.strategy_type,
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

    def reset(self) -> None:
        """重置执行器状态"""
        self._position_tracker.reset()
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
