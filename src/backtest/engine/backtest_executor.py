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

策略层 (V2):
- BacktestStrategyRegistry (策略注册表)
- Strategy.generate_signals() → Signal[] (单入口)
- SignalConverter → TradeSignal (桥接)
- RiskGuard chain (风控过滤)

回测流程:
1. 初始化 DuckDBProvider、V2 Strategy
2. 逐日迭代交易日
3. 每日:
   a. 更新持仓价格 (Position 层更新，Account 层存储)
   b. Strategy.generate_signals() → exit + entry signals
   c. RiskGuard 过滤
   d. SignalConverter → TradeSignal 执行
   e. 处理到期期权
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
from typing import Any, Callable, cast

from src.backtest.config.backtest_config import BacktestConfig, PriceMode
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.position_manager import PositionManager, DataNotFoundError
from src.backtest.engine.trade_simulator import (
    OrderSide,
    TradeAction,
    TradeExecution,
    TradeRecord,
    TradeSimulator,
)
from src.data.models.account import AssetType
from src.business.monitoring.models import PositionData
from src.business.screening.models import ContractOpportunity
from src.business.strategy.models import MarketContext, TradeSignal
from src.backtest.strategy.registry import BacktestStrategyRegistry
from src.backtest.strategy.signal_converter import SignalConverter
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

    # 现金利息
    interest_accrued: float = 0.0

    # 出金
    withdrawal_amount: float = 0.0

    # 策略特定指标 (可选，供可视化使用)
    strategy_metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
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
        if self.interest_accrued:
            d["interest_accrued"] = self.interest_accrued
        if self.withdrawal_amount:
            d["withdrawal_amount"] = self.withdrawal_amount
        if self.strategy_metrics:
            d["strategy_metrics"] = self.strategy_metrics
        return d


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

    # 回测结束时的未平仓持仓 (用于持仓报表)
    open_positions: list[dict] = field(default_factory=list)

    # 执行信息
    execution_time_seconds: float = 0.0
    trading_days: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self, include_details: bool = False) -> dict:
        """转换为字典 (用于序列化)

        Args:
            include_details: 是否包含 trade_records 和 daily_snapshots 详细数据
        """
        result = {
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
        if include_details:
            result["trade_records"] = [t.to_dict() for t in self.trade_records]
            result["daily_snapshots"] = [s.to_dict() for s in self.daily_snapshots]
            result["open_positions"] = self.open_positions
        return result


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
        attribution_collector: Any | None = None,
    ) -> None:
        """初始化回测执行器

        Args:
            config: 回测配置
            data_provider: 数据提供者 (可选，默认根据配置创建)
            progress_callback: 进度回调函数 (current_date, current_day, total_days)
            attribution_collector: 归因数据采集器 (可选，传入 AttributionCollector 实例)
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

        # Account 层: 账户模拟器 (直接持有, margin 从 RiskConfig 读)
        self._account_simulator = AccountSimulator(
            initial_capital=config.initial_capital,
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

        # 初始化 Strategy — 统一使用 V2 注册表
        strategy_name = self._config.strategy_version
        self._strategy = BacktestStrategyRegistry.create(strategy_name)
        self._signal_converter = SignalConverter()

        # Initialize RiskGuard chain (从 RiskConfig 按策略名加载)
        from src.backtest.strategy.risk.account_risk import AccountRiskGuard
        from src.business.trading.config.risk_config import RiskConfig
        risk_config = RiskConfig.load(strategy_name)
        self._risk_guards: list = [
            AccountRiskGuard(risk_config),
        ]
        logger.info(f"Using V2 strategy: {self._strategy.name}")

        # 状态
        self._current_date: date | None = None
        self._position_counter = 0
        self._daily_snapshots: list[DailySnapshot] = []
        self._errors: list[str] = []
        self._last_withdrawal_month: int | None = None  # 出金月份追踪

        # 归因采集
        self._attribution_collector = attribution_collector
        self._last_monitoring_position_data: list[PositionData] = []




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
                import traceback
                error_msg = f"Error on {current_date}: {e}\n{traceback.format_exc()}"
                logger.error(error_msg)
                self._errors.append(error_msg)
                raise e

        # 构建结果
        execution_time = (datetime.now() - start_time).total_seconds()
        result = self._build_result(trading_days, execution_time)

        logger.info(f"Backtest completed in {execution_time:.1f}s")
        logger.info(f"  Final NLV: ${result.final_nlv:,.2f}")
        logger.info(f"  Total Return: {result.total_return_pct:.2%}")
        logger.info(f"  Win Rate: {result.win_rate:.1%}")
        logger.info(f"  Total Trades: {result.total_trades}")

        # 输出期权价格统计
        stats = self._position_manager.price_stats
        logger.info("Option Price Statistics:")
        logger.info(f"  Total queries: {stats.total_queries}")
        logger.info(f"  Successful: {stats.successful} ({stats.success_rate:.1%})")
        logger.info(f"  Missing: {stats.missing} ({stats.missing_rate:.1%})")
        logger.info(f"  Invalid: {stats.invalid} ({stats.invalid_rate:.1%})")

        return result

    @property
    def attribution_collector(self) -> Any | None:
        """获取归因数据采集器"""
        return self._attribution_collector

    def _run_single_day(self, current_date: date) -> None:
        """执行单日回测

        Args:
            current_date: 当前日期
        """
        self._current_date = current_date
        self._position_manager.set_date(current_date)

        # 显示当前回测日期
        logger.info(f"{'='*60}  📅 回测日期: {current_date}  {'='*5}")

        # 更新数据提供者日期
        self._data_provider.set_as_of_date(current_date)

        # 记录前一日 NLV (用于计算当日盈亏)
        prev_nlv = self._account_simulator.nlv

        # 构造当天的 MarketContext
        underlying_prices = {}
        target_symbols = set(self._config.symbols) if self._config.symbols else {"SPY"}
        for pos in self._account_simulator.positions.values():
            if pos.underlying:  # 过滤掉 None (股票持仓没有 underlying)
                target_symbols.add(pos.underlying)
        # Add cash sweep ETF symbol if strategy uses active cash management
        if hasattr(self._strategy, '_cash_sweep_config'):
            _cs_cfg = self._strategy._cash_sweep_config
            if _cs_cfg.enabled:
                target_symbols.add(_cs_cfg.instrument_symbol)
        
        for symbol in target_symbols:
            stock_quote = self._data_provider.get_stock_quote(symbol)
            if stock_quote and stock_quote.close:
                underlying_prices[symbol] = stock_quote.close
            else:
                underlying_prices[symbol] = 0.0
                
        # 从 DuckDB 读取当日 VIX
        vix_value = None
        try:
            vix_data = self._data_provider.get_macro_data("^VIX", current_date, current_date)
            if vix_data:
                vix_value = vix_data[-1].close
        except Exception:
            pass

        market_context = MarketContext(
            current_date=current_date,
            underlying_prices=underlying_prices,
            vix_value=vix_value,
            market_trend=None
        )

        # 1. 更新持仓价格 (Position 层更新，Account 层存储)
        self._position_manager.update_all_positions_market_data(
            self._account_simulator.positions
        )

        trades_opened = 0
        trades_closed = 0

        # V2 策略路径: generate_signals() 单入口
        self._run_v2_strategy_day(current_date, market_context)
        trades_opened = self._v2_trades_opened
        trades_closed = self._v2_trades_closed

        # 6. 处理到期期权 (盘后交收计算)
        self._process_expirations(current_date)

        # 6.5 计提现金利息 (如果策略支持)
        daily_interest = 0.0
        active_strategy = self._strategy
        if hasattr(active_strategy, '_compute_daily_interest'):
            daily_interest = active_strategy._compute_daily_interest(
                cash=self._account_simulator.cash,
                current_date=current_date,
                data_provider=self._data_provider,
            )
            if daily_interest > 0:
                self._account_simulator.accrue_interest(daily_interest)

        # 6.6 处理每月出金 (每月第一个交易日)
        withdrawal_amount = 0.0
        if self._config.monthly_withdrawal > 0 and self._is_new_month(current_date):
            withdrawal_amount = self._account_simulator.withdraw_cash(
                self._config.monthly_withdrawal
            )
            logger.info(
                f"Monthly withdrawal: ${withdrawal_amount:,.2f} on {current_date} "
                f"(cash after: ${self._account_simulator.cash:,.2f})"
            )

        # 7. 记录每日快照
        snapshot = self._take_daily_snapshot(current_date, prev_nlv)
        snapshot.trades_opened = trades_opened
        snapshot.trades_closed = trades_closed
        snapshot.interest_accrued = daily_interest
        snapshot.withdrawal_amount = withdrawal_amount

        # 捕获策略信号元数据 (供可视化使用)
        active_strategy = self._strategy
        if hasattr(active_strategy, '_last_signal_detail') and active_strategy._last_signal_detail:
            snapshot.strategy_metrics = dict(active_strategy._last_signal_detail)

        # 捕获现金利息元数据
        if daily_interest > 0:
            snapshot.strategy_metrics["daily_interest"] = daily_interest
        if hasattr(active_strategy, '_cumulative_interest'):
            snapshot.strategy_metrics["cumulative_interest"] = active_strategy._cumulative_interest
        if hasattr(active_strategy, '_tnx_cache') and current_date in active_strategy._tnx_cache:
            snapshot.strategy_metrics["risk_free_rate"] = active_strategy._tnx_cache[current_date]

        self._daily_snapshots.append(snapshot)

        logger.debug(
            f"{current_date}: NLV=${snapshot.nlv:,.0f}, "
            f"positions={snapshot.position_count}, "
            f"opened={trades_opened}, closed={trades_closed}"
        )

    def _build_market_snapshot(self, current_date: date, market_context: MarketContext) -> "V2MarketSnapshot":
        """Build a V2 MarketSnapshot from the legacy MarketContext."""
        from src.backtest.strategy.models import MarketSnapshot as V2MarketSnapshot

        # TNX risk-free rate
        risk_free_rate = None
        try:
            tnx_data = self._data_provider.get_macro_data("^TNX", current_date, current_date)
            if tnx_data:
                risk_free_rate = tnx_data[-1].close / 100.0  # TNX is in %, convert to decimal
        except Exception:
            pass

        return V2MarketSnapshot(
            date=current_date,
            prices=dict(market_context.underlying_prices),
            vix=market_context.vix_value,
            risk_free_rate=risk_free_rate,
        )

    def _build_portfolio_state(self, current_date: date) -> "V2PortfolioState":
        """Build a V2 PortfolioState from current account state."""
        from src.backtest.strategy.models import (
            PortfolioState as V2PortfolioState,
            PositionView,
            Instrument,
            InstrumentType,
            OptionRight,
        )

        position_views = []
        for pos in self._account_simulator.positions.values():
            if pos.is_closed:
                continue

            # Build Instrument from SimulatedPosition
            if pos.asset_type == AssetType.STOCK or (pos.strike is not None and pos.strike < 1.0 and pos.lot_size == 1):
                # Stock or stock proxy
                instrument = Instrument(
                    type=InstrumentType.STOCK,
                    underlying=pos.underlying or pos.symbol,
                )
            else:
                # Option
                right = None
                if pos.option_type is not None:
                    right = OptionRight.CALL if pos.option_type == OptionType.CALL else OptionRight.PUT
                instrument = Instrument(
                    type=InstrumentType.OPTION,
                    underlying=pos.underlying or pos.symbol,
                    right=right,
                    strike=pos.strike,
                    expiry=pos.expiration,
                    lot_size=pos.lot_size,
                )

            # Compute DTE
            dte = None
            if pos.expiration:
                dte = (pos.expiration - current_date).days

            # Fetch Greeks from PositionManager for option positions
            delta, gamma, theta, vega, iv = None, None, None, None, None
            if pos.asset_type == AssetType.OPTION and pos.expiration:
                try:
                    delta, gamma, theta, vega, iv = self._position_manager._get_greeks(pos)
                except Exception:
                    pass

            position_views.append(PositionView(
                position_id=pos.position_id,
                instrument=instrument,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                entry_date=pos.entry_date,
                current_price=pos.current_price,
                underlying_price=pos.underlying_price,
                unrealized_pnl=pos.unrealized_pnl,
                dte=dte,
                lot_size=pos.lot_size,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
                iv=iv,
            ))

        return V2PortfolioState(
            date=current_date,
            nlv=self._account_simulator.nlv,
            cash=self._account_simulator.cash,
            margin_used=self._account_simulator.margin_used,
            positions=position_views,
        )

    def _run_v2_strategy_day(self, current_date: date, market_context: MarketContext) -> None:
        """Execute a single day using V2 strategy (generate_signals single entry point).

        This builds read-only snapshots, calls the strategy, converts signals,
        and executes trades through the existing engine.
        """
        logger.info("── V2 Strategy ─────────────────────────────────────")

        # 1. Build read-only snapshots
        market = self._build_market_snapshot(current_date, market_context)
        portfolio = self._build_portfolio_state(current_date)

        # 2. Attribution capture (before strategy runs, same timing as legacy path)
        if hasattr(self, "_attribution_collector") and self._attribution_collector:
            pos_data = self._position_manager.get_position_data_for_monitoring(
                positions=self._account_simulator.positions,
                as_of_date=current_date,
            )
            self._last_monitoring_position_data = pos_data
            if pos_data:
                self._attribution_collector.capture_daily(
                    current_date=current_date,
                    position_data_list=pos_data,
                    nlv=self._account_simulator.nlv,
                    cash=self._account_simulator.cash,
                    margin_used=self._account_simulator.margin_used,
                    data_provider=self._data_provider,
                    as_of_date=current_date,
                )

        # 3. Generate signals (single entry point)
        v2_signals = self._strategy.generate_signals(market, portfolio, self._data_provider)
        logger.info(f"  V2 strategy generated {len(v2_signals)} signals")

        # 4. RiskGuard chain filtering
        if v2_signals and self._risk_guards:
            for guard in self._risk_guards:
                before = len(v2_signals)
                v2_signals = guard.check(v2_signals, portfolio, market)
                filtered = before - len(v2_signals)
                if filtered > 0:
                    logger.info(f"  RiskGuard {guard.__class__.__name__} filtered {filtered} signals")

        # 5. Convert V2 Signal → legacy TradeSignal
        trade_signals: list[TradeSignal] = []
        if v2_signals and self._signal_converter:
            trade_signals = self._signal_converter.convert_to_trade_signals(
                v2_signals, market, self._data_provider
            )

        # 5. Execute through existing engine
        self._v2_trades_opened = 0
        self._v2_trades_closed = 0
        trade_index = 0

        # Group combo signals so they can be executed together with spread margin
        combo_groups: dict[str, list[TradeSignal]] = {}
        non_combo_signals: list[TradeSignal] = []
        for signal in trade_signals:
            combo_id = getattr(signal, "_combo_group", None)
            if combo_id and signal.action == TradeAction.OPEN:
                combo_groups.setdefault(combo_id, []).append(signal)
            else:
                non_combo_signals.append(signal)

        # Execute combo groups first (spread margin)
        for combo_id, legs in combo_groups.items():
            if self._execute_combo_open_signals(legs, current_date):
                self._v2_trades_opened += len(legs)
                trade_index += 1

        # Execute remaining signals
        for signal in non_combo_signals:
            if signal.action == TradeAction.OPEN:
                if self._execute_open_signal(signal, current_date):
                    self._v2_trades_opened += 1
                    trade_index += 1
                    if isinstance(signal.quote, ContractOpportunity):
                        self._log_trade_execution(signal, signal.quote, trade_index)
            elif signal.action == TradeAction.CLOSE:
                if self._execute_close_signal(signal, current_date):
                    self._v2_trades_closed += 1
            elif signal.action == TradeAction.ROLL:
                close_success, open_success = self._execute_roll_decision(signal, current_date)
                if close_success:
                    self._v2_trades_closed += 1
                if open_success:
                    self._v2_trades_opened += 1
                    trade_index += 1

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
            # 断言：到期持仓应该是期权持仓，期权字段非空
            assert position.underlying is not None
            assert position.option_type is not None
            assert position.strike is not None
            assert position.expiration is not None

            # 获取标的价格 - 数据缺失时抛出异常，不使用 strike 回退
            underlying = cast(str, position.underlying)
            quote = self._data_provider.get_stock_quote(underlying)
            if quote is None:
                raise DataNotFoundError(
                    f"Stock quote not found for {underlying} "
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

            # 判断是否 ITM
            if position.option_type == OptionType.PUT:
                is_itm = final_price < position.strike
            else:  # OptionType.CALL
                is_itm = final_price > position.strike

            # 根据是否 ITM 处理到期
            if is_itm:
                # ITM 到期：行权（需要处理期权和股票交易）
                self._process_itm_expiration(
                    position, final_price, current_date
                )
            else:
                # OTM 到期：自然到期（仅处理期权交易）
                self._process_otm_expiration(
                    position, final_price, current_date
                )

    def _process_otm_expiration(
        self,
        position,
        final_price: float,
        current_date: date,
    ) -> None:
        """处理 OTM 到期（自然到期）

        Args:
            position: 到期的期权持仓
            final_price: 到期时标的价格
            current_date: 当前日期
        """
        # Trade 层：执行到期处理
        execution = self._trade_simulator.execute_expire(
            symbol=position.symbol,
            underlying=position.underlying,  # type: ignore[arg-type]
            option_type=position.option_type,  # type: ignore[arg-type]
            strike=position.strike,  # type: ignore[arg-type]
            expiration=position.expiration,  # type: ignore[arg-type]
            quantity=position.quantity,
            final_underlying_price=final_price,
            trade_date=current_date,
            lot_size=position.lot_size,
        )

        # Position 层：计算已实现盈亏
        pnl = self._position_manager.calculate_realized_pnl(position, execution)

        # Trade 层：更新 PnL 和 position_id
        self._trade_simulator.update_last_trade_pnl(pnl)
        self._trade_simulator.update_last_trade_position_id(position.position_id)

        # Account 层：移除持仓，更新现金
        success = self._account_simulator.remove_position(
            position_id=position.position_id,
            cash_change=execution.net_amount,
            realized_pnl=pnl,
        )

        if success:
            # 完成持仓关闭
            self._position_manager.finalize_close(position, execution, pnl)

            logger.info(
                f"Position {position.position_id} expired OTM on {current_date}: "
                f"entry_price=${position.entry_price:.4f} -> close_price=${position.close_price:.4f}, "
                f"reason={execution.reason}, PnL: ${pnl:.2f}"
            )

    def _process_itm_expiration(
        self,
        position,
        final_price: float,
        current_date: date,
    ) -> None:
        """处理 ITM 到期（行权）

        Args:
            position: 到期的期权持仓
            final_price: 到期时标的价格
            current_date: 当前日期
        """
        # 1. Trade 层：执行到期处理（期权记录）
        execution = self._trade_simulator.execute_expire(
            symbol=position.symbol,
            underlying=position.underlying,  # type: ignore[arg-type]
            option_type=position.option_type,  # type: ignore[arg-type]
            strike=position.strike,  # type: ignore[arg-type]
            expiration=position.expiration,  # type: ignore[arg-type]
            quantity=position.quantity,
            final_underlying_price=final_price,
            trade_date=current_date,
            lot_size=position.lot_size,
        )

        # 2. Position 层：计算已实现盈亏
        pnl = self._position_manager.calculate_realized_pnl(position, execution)

        # 3. Trade 层：更新 PnL 和 position_id
        # action 已在 execute_expire() 内部根据 ITM/OTM 判断并设置
        self._trade_simulator.update_last_trade_pnl(pnl)
        self._trade_simulator.update_last_trade_position_id(position.position_id)

        # 4. Account 层：移除持仓，更新现金
        success = self._account_simulator.remove_position(
            position_id=position.position_id,
            cash_change=execution.net_amount,
            realized_pnl=pnl,
        )

        if success:
            # 完成持仓关闭
            self._position_manager.finalize_close(position, execution, pnl)

            logger.info(
                f"Position {position.position_id} assigned on {current_date}: "
                f"entry_price=${position.entry_price:.4f} -> close_price=${position.close_price:.4f}, "
                f"reason={execution.reason}, PnL: ${pnl:.2f}"
            )

        # 5. 处理股票交易
        self._handle_option_assignment(position, final_price, current_date)

    def _handle_option_assignment(
        self,
        position,
        final_price: float,
        current_date: date,
    ) -> None:
        """处理期权行权后的股票持仓

        Args:
            position: 到期的期权持仓
            final_price: 到期时标的价格
            current_date: 当前日期
        """
        shares_required = abs(position.quantity) * position.lot_size

        if position.option_type == OptionType.PUT:
            # Short Put ITM 到期：按市价接盘股票(期权价值已在TradeSimulator结算)
            self._handle_short_put_assignment(
                position.underlying,
                shares_required,
                final_price,  # 传入市价而不是行权价
                current_date,
            )
        else:  # OptionType.CALL
            # Short Call ITM 到期：按市价卖出股票
            self._handle_short_call_assignment(
                position.underlying,
                shares_required,
                position.strike,
                final_price,
                current_date,
            )

    def _handle_short_put_assignment(
        self,
        underlying: str,
        shares: int,
        market_price: float,
        trade_date: date,
    ) -> None:
        """处理 Short Put 行权：按市价接盘股票(期权按内在价值平仓)

        Args:
            underlying: 标的代码
            shares: 需要买入的股数
            market_price: 结算市价
            trade_date: 交易日期
        """
        required_cash = shares * market_price

        # 现金不足兜底：跳过股票交易（期权已在 _process_itm_expiration 中按内在价值结算）
        if required_cash > self._account_simulator.cash:
            logger.warning(
                f"Insufficient cash for assignment, skipping stock purchase: "
                f"required=${required_cash:.2f}, available=${self._account_simulator.cash:.2f}, "
                f"underlying={underlying}, shares={shares}"
            )
            return

        # 执行股票买入交易
        execution = self._trade_simulator.execute_stock_trade(
            symbol=underlying,
            side=OrderSide.BUY,
            quantity=shares,
            price=market_price,  # 按市价买入，反映真实最新成本
            trade_date=trade_date,
            reason="assigned_buy",
        )

        # 添加股票持仓到账户（传入现金变动）
        self._account_simulator.add_stock_position(
            symbol=underlying,
            quantity=shares,
            entry_price=market_price,  # 成本为市价
            trade_date=trade_date,
            cash_change=execution.net_amount,  # 现金变动（买入为负）
        )

        logger.info(
            f"Short Put assignment on {trade_date}: "
            f"Bought {shares} shares of {underlying} @ ${market_price:.2f} "
            f"(assignment), cash change: ${execution.net_amount:.2f}"
        )


    def _handle_short_call_assignment(
        self,
        underlying: str,
        shares_required: int,
        strike: float,
        market_price: float,
        trade_date: date,
    ) -> None:
        """处理 Short Call 行权：交割股票

        与 Short Put 对称的设计：
        - _process_itm_expiration 中 execute_expire 已按内在价值结算期权,
          PnL = 权利金 - 内在价值, 完整反映了经济损益
        - 本方法只处理股票交割, 不应产生额外损益

        场景1: Covered Call (有足够持股)
          → 按行权价卖出股票, 股票 PnL = strike - entry_price
        场景2: Naked Call (无持股)
          → 期权内在价值结算已反映全部损失, 无需执行股票买卖
        场景3: 部分持股
          → 卖出已有股票, 缺口部分由期权结算覆盖

        Args:
            underlying: 标的代码
            shares_required: 需要卖出的股数
            strike: 行权价
            market_price: 当前市价
            trade_date: 交易日期
        """
        current_shares = self._account_simulator.get_stock_quantity(underlying)

        if current_shares <= 0:
            # Naked Call: 无股票可交割
            # 期权已按内在价值 (market - strike) 结算, 捕获了全部经济损失
            # 不执行股票买卖, 避免双重计算
            logger.info(
                f"Short Call assignment on {trade_date}: "
                f"Naked Call on {underlying}, no stock delivery needed. "
                f"Option intrinsic value settlement covers the full loss."
            )
            return

        # Covered Call (全部或部分持股): 按行权价卖出股票
        shares_to_sell = min(current_shares, shares_required)

        sell_execution = self._trade_simulator.execute_stock_trade(
            symbol=underlying,
            side=OrderSide.SELL,
            quantity=shares_to_sell,
            price=market_price,  # 修复核心BUG：用市价平仓以抵消期权内在价值的结算，避免被扣两次钱
            trade_date=trade_date,
            reason="assigned_sell",
        )

        # 更新股票持仓
        position_id = f"{underlying}-STOCK"
        remaining_shares = current_shares - shares_to_sell

        if position_id in self._account_simulator.positions:
            position = self._account_simulator.positions[position_id]

            if remaining_shares <= 0:
                # 所有股票已交割
                pnl = (market_price - position.entry_price) * shares_to_sell
                self._account_simulator.remove_position(
                    position_id=position_id,
                    cash_change=sell_execution.net_amount,
                    realized_pnl=pnl,
                )
            else:
                # 还有剩余股票，卖出了部分股票，实现部分盈亏
                pnl = (market_price - position.entry_price) * shares_to_sell
                self._account_simulator.update_stock_position(
                    position_id=position_id,
                    quantity_change=-shares_to_sell,
                    new_price=market_price,
                    cash_change=sell_execution.net_amount,
                    realized_pnl=pnl,
                )

        if shares_to_sell < shares_required:
            uncovered = shares_required - shares_to_sell
            logger.info(
                f"Short Call assignment on {trade_date}: "
                f"Delivered {shares_to_sell} shares of {underlying} @ ${strike:.2f}, "
                f"{uncovered} shares uncovered (settled via option intrinsic value)"
            )
        else:
            logger.info(
                f"Short Call assignment on {trade_date}: "
                f"Delivered {shares_to_sell} shares of {underlying} @ ${strike:.2f} "
                f"(covered call), cash change: ${sell_execution.net_amount:.2f}"
            )


    # Legacy V1 methods (_run_screening, _can_open_new_positions) removed — V2 strategies handle this via generate_signals()

    def _execute_open_signal(
        self,
        signal: TradeSignal,
        trade_date: date,
    ) -> bool:
        """执行开仓决策

        使用重构后的流程:
        1. Trade 层 (TradeSimulator): 计算滑点、手续费、金额 → TradeExecution
        2. Position 层 (PositionTracker): 创建 Position，计算 margin → SimulatedPosition
        3. Account 层 (AccountSimulator): 检查保证金，更新现金

        Args:
            signal: 交易信号 (含 quote 属性)
            trade_date: 交易日期

        Returns:
            是否成功
        """
        try:
            quote = signal.quote
            if not quote:
                logger.error("TradeSignal missing quote attribute for OPEN action")
                return False
                
            underlying = quote.contract.underlying
            # OptionQuote.contract.option_type is an Enum OptionType
            option_type = quote.contract.option_type
            option_type_str = option_type.value
            strike = quote.contract.strike_price
            expiry = quote.contract.expiry_date

            # 1. Trade 层：执行交易，得到 TradeExecution
            mid_price = quote.mid_price or 0.0

            # 检测 stock proxy: strike < 1.0 且 lot_size == 1
            effective_lot_size = quote.contract.lot_size or 100
            is_stock_proxy = (strike < 1.0 and effective_lot_size == 1)

            if is_stock_proxy:
                # Stock proxy → 股票交易路径（正确的手续费 + 无滑点）
                from src.backtest.engine.trade_simulator import OrderSide
                execution = self._trade_simulator.execute_stock_trade(
                    symbol=underlying,  # "SPY"（不是 "SPY_440303_C_0"）
                    side=OrderSide.BUY if signal.quantity > 0 else OrderSide.SELL,
                    quantity=abs(signal.quantity),
                    price=mid_price,
                    trade_date=trade_date,
                    reason=signal.reason or "stock_proxy_open",
                )
            else:
                # 由于传入的 underlying 是诸如 "SPY" 的名字，构建完整的期权合约名称给 symbol
                contract_symbol = f"{underlying}_{expiry}_{strike}_{option_type_str}"

                execution = self._trade_simulator.execute_open(
                    symbol=contract_symbol,
                    underlying=underlying,
                    option_type=option_type,
                    strike=strike,
                    expiration=expiry,
                    quantity=signal.quantity,
                    mid_price=mid_price,
                    trade_date=trade_date,
                    reason=signal.reason or "strategy_open",
                    lot_size=effective_lot_size,
                )

            # 1.5. Trade 层：回填 underlying_price 到交易记录
            try:
                stock_quote = self._data_provider.get_stock_quote(underlying)
                if stock_quote and stock_quote.close:
                    self._trade_simulator.trade_records[-1].underlying_price = stock_quote.close
            except Exception:
                pass  # 非关键路径，失败不影响回测

            # 2. Position 层：基于 TradeExecution 创建持仓对象
            position = self._position_manager.create_position(execution)

            # 2.5. Trade 层：回填 position_id 到开仓交易记录
            self._trade_simulator.update_last_trade_position_id(position.position_id)

            # 3. Account 层：检查保证金，添加持仓
            success = self._account_simulator.add_position(
                position=position,
                cash_change=execution.net_amount,
            )

            # 4. 合并同标的股票仓位（stock proxy 增量加仓 → 合并为单一仓位）
            if is_stock_proxy and success:
                self._account_simulator.merge_stock_positions(underlying)

            return success

        except Exception as e:
            logger.error(f"Failed to execute open decision: {e}")
            return False

    def _execute_combo_open_signals(
        self,
        signals: list[TradeSignal],
        trade_date: date,
    ) -> bool:
        """Execute a combo (spread) open using AccountSimulator.add_combo_position().

        This ensures spread margin is used instead of naked margin per leg.

        Args:
            signals: List of TradeSignals forming the combo (e.g. short put + long put)
            trade_date: Trade date

        Returns:
            True if combo was successfully opened
        """
        try:
            positions = []
            executions = []
            total_cash_change = 0.0

            for signal in signals:
                quote = signal.quote
                if not quote:
                    logger.error("Combo leg missing quote")
                    return False

                underlying = quote.contract.underlying
                option_type = quote.contract.option_type
                strike = quote.contract.strike_price
                expiry = quote.contract.expiry_date
                effective_lot_size = quote.contract.lot_size or 100
                mid_price = quote.mid_price or 0.0

                contract_symbol = f"{underlying}_{expiry}_{strike}_{option_type.value}"

                execution = self._trade_simulator.execute_open(
                    symbol=contract_symbol,
                    underlying=underlying,
                    option_type=option_type,
                    strike=strike,
                    expiration=expiry,
                    quantity=signal.quantity,
                    mid_price=mid_price,
                    trade_date=trade_date,
                    reason=signal.reason or "combo_open",
                    lot_size=effective_lot_size,
                )

                # Backfill underlying_price
                try:
                    stock_quote = self._data_provider.get_stock_quote(underlying)
                    if stock_quote and stock_quote.close:
                        self._trade_simulator.trade_records[-1].underlying_price = stock_quote.close
                except Exception:
                    pass

                position = self._position_manager.create_position(execution)
                self._trade_simulator.update_last_trade_position_id(position.position_id)

                positions.append(position)
                executions.append(execution)
                total_cash_change += execution.net_amount

            # Use combo position for spread margin
            success = self._account_simulator.add_combo_position(
                positions=positions,
                cash_change=total_cash_change,
            )

            if not success:
                # Rollback trade records for failed combo
                for _ in positions:
                    if self._trade_simulator.trade_records:
                        self._trade_simulator.trade_records.pop()
                logger.warning("Combo open failed: insufficient margin")
                return False

            logger.info(
                f"Combo opened ({len(positions)} legs): "
                f"cash_change=${total_cash_change:,.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to execute combo open: {e}")
            return False

    def _log_trade_execution(
        self,
        signal: TradeSignal,
        opportunity: ContractOpportunity | None,
        trade_index: int,
    ) -> None:
        """输出 trade 执行卡片日志

        Args:
            signal: 交易信号
            opportunity: 匹配的筛选机会 (可能为 None)
            trade_index: 当日第几笔交易
        """
        if opportunity is None:
            return

        opp = opportunity
        opt_type = "PUT" if (opp.option_type or "").lower() == "put" else "CALL"
        strike_str = f"{opp.strike:.0f}" if opp.strike == int(opp.strike) else f"{opp.strike}"
        exp_str = opp.expiry or "N/A"

        # 标题行
        header = f"┌─ #{trade_index} {opp.symbol} {opt_type} {strike_str} @ {exp_str} (DTE={opp.dte}) | Qty={signal.quantity}"
        sep = "├" + "─" * 65

        # 收益指标
        roc_str = f"{opp.expected_roc:.1%}" if opp.expected_roc is not None else "N/A"
        ann_roc_str = f"{opp.annual_roc:.1%}" if opp.annual_roc is not None else "N/A"
        win_str = f"{opp.win_probability:.1%}" if opp.win_probability is not None else "N/A"
        kelly_str = f"{opp.kelly_fraction:.2f}" if opp.kelly_fraction is not None else "N/A"
        profit_line = f"│ 收益: ExpROC={roc_str}  AnnROC={ann_roc_str}  WinP={win_str}  Kelly={kelly_str}"

        # 效率指标
        tgr_str = f"{opp.tgr:.2f}" if opp.tgr is not None else "N/A"
        tm_str = f"{opp.theta_margin_ratio:.4f}" if opp.theta_margin_ratio is not None else "N/A"
        sr_str = f"{opp.sharpe_ratio_annual:.2f}" if opp.sharpe_ratio_annual is not None else "N/A"
        rate_str = f"{opp.premium_rate:.2%}" if opp.premium_rate is not None else "N/A"
        eff_line = f"│ 效率: TGR={tgr_str}  Θ/Margin={tm_str}  Sharpe={sr_str}  PremRate={rate_str}"

        # 行情
        price_str = f"{opp.underlying_price:.2f}" if opp.underlying_price is not None else "N/A"
        premium_str = f"{opp.mid_price:.2f}" if opp.mid_price is not None else "N/A"
        bid_str = f"{opp.bid:.2f}" if opp.bid is not None else "N/A"
        ask_str = f"{opp.ask:.2f}" if opp.ask is not None else "N/A"
        iv_str = f"{opp.iv:.1%}" if opp.iv is not None else "N/A"
        mkt_line = f"│ 行情: S={price_str}  Premium={premium_str}  Bid/Ask={bid_str}/{ask_str}  IV={iv_str}"

        # Greeks
        delta_str = f"{opp.delta:.3f}" if opp.delta is not None else "N/A"
        gamma_str = f"{opp.gamma:.4f}" if opp.gamma is not None else "N/A"
        theta_str = f"{opp.theta:.3f}" if opp.theta is not None else "N/A"
        oi_str = f"{opp.open_interest}" if opp.open_interest is not None else "N/A"
        otm_str = f"{opp.otm_percent:.1%}" if opp.otm_percent is not None else "N/A"
        greeks_line = f"│ Greeks: Δ={delta_str}  Γ={gamma_str}  Θ={theta_str}  OI={oi_str}  OTM={otm_str}"

        footer = "└" + "─" * 65

        lines = [header, sep, profit_line, eff_line, mkt_line, greeks_line]

        # 警告信息
        if opp.warnings:
            lines.append(f"│ ⚠️  {opp.warnings[0]}")

        lines.append(footer)

        logger.info("\n".join(lines))

    def _execute_close_signal(
        self,
        signal: TradeSignal,
        trade_date: date,
    ) -> bool:
        """执行平仓决策

        Args:
            signal: 交易决策信号 (带 related_position 或 position_id)
            trade_date: 交易日期

        Returns:
            是否成功
        """
        try:
            # 查找对应持仓
            # 1. 优先使用 related_position
            position = signal.related_position

            # 2. 其次用 position_id 精确匹配
            if not position and signal.position_id:
                position = self._account_simulator.positions.get(signal.position_id)

            # 3. 兜底：用 symbol 匹配（兼容旧逻辑）
            if not position:
                position = self._account_simulator.positions.get(signal.symbol)

            if not position:
                logger.warning(
                    f"Position not found for close signal: "
                    f"position_id={signal.position_id}, symbol={signal.symbol}"
                )
                return False

            # 获取当前期权价格
            option_price = self._get_current_option_price(position)
            if option_price is None:
                option_price = position.current_price

            # 1. Trade 层：模拟交易执行
            if position.is_stock:
                # 股票持仓：使用股票交易路径 (lot_size=1)
                # execute_stock_trade 期望 quantity 为正数，由 side 决定方向
                from src.backtest.engine.trade_simulator import OrderSide
                execution = self._trade_simulator.execute_stock_trade(
                    symbol=position.symbol,
                    side=OrderSide.SELL,
                    quantity=abs(signal.quantity),
                    price=position.current_price,
                    trade_date=trade_date,
                    reason=signal.reason or "strategy_close",
                )
            else:
                # alert_type 为 roll_dte 时，TradeRecord.action 标记为 ROLL 以区分普通平仓
                close_action = "roll" if signal.alert_type == "roll_dte" else "close"
                execution = self._trade_simulator.execute_close(
                    symbol=position.symbol,
                    underlying=position.underlying,  # type: ignore[arg-type]
                    option_type=position.option_type,  # type: ignore[arg-type]
                    strike=position.strike,  # type: ignore[arg-type]
                    expiration=position.expiration,  # type: ignore[arg-type]
                    quantity=signal.quantity,
                    mid_price=option_price,
                    trade_date=trade_date,
                    reason=signal.reason or "strategy_close",
                    lot_size=position.lot_size,
                    alert_type=signal.alert_type,
                    action=close_action,
                )

            # 1.5. Trade 层：回填 underlying_price 到交易记录
            try:
                stock_quote = self._data_provider.get_stock_quote(position.underlying)
                if stock_quote and stock_quote.close:
                    self._trade_simulator.trade_records[-1].underlying_price = stock_quote.close
            except Exception:
                pass

            # 2. 判断是否部分平仓（股票和期权均支持部分平仓）
            close_qty = abs(signal.quantity)
            is_partial_close = close_qty < abs(position.quantity)

            if is_partial_close:
                # 部分平仓：计算减仓部分的已实现盈亏（乘以 lot_size）
                pnl = close_qty * (position.current_price - position.entry_price) * position.lot_size

                # 2.5. Trade 层：回填
                self._trade_simulator.update_last_trade_pnl(pnl)
                self._trade_simulator.update_last_trade_position_id(position.position_id)

                # 3. Account 层：部分减仓，更新现金
                position.quantity -= close_qty
                position.market_value = position.quantity * position.current_price * position.lot_size
                position.unrealized_pnl = position.market_value - (position.quantity * position.entry_price * position.lot_size)
                self._account_simulator._cash += execution.net_amount
                self._account_simulator._realized_pnl_cumulative += pnl
                success = True
            else:
                # 全平仓
                # 2. Position 层：计算已实现盈亏
                pnl = self._position_manager.calculate_realized_pnl(
                    position=position,
                    execution=execution,
                    close_reason=signal.reason or "strategy_close",
                )

                # 2.5. Trade 层：回填 PnL 和 position_id 到交易记录
                self._trade_simulator.update_last_trade_pnl(pnl)
                self._trade_simulator.update_last_trade_position_id(position.position_id)

                # 3. Account 层：移除持仓，更新现金
                success = self._account_simulator.remove_position(
                    position_id=position.position_id,
                    cash_change=execution.net_amount,
                    realized_pnl=pnl,
                )

            if success and not is_partial_close:
                # 完成持仓关闭 (更新持仓字段) — 部分平仓不走此路径
                self._position_manager.finalize_close(
                    position, execution, pnl, signal.reason or "strategy_close"
                )
            elif success and is_partial_close:
                # 部分平仓: 仅累加佣金，不关闭持仓
                position.commission_paid += execution.commission

            return success

        except Exception as e:
            logger.error(f"Failed to execute close decision: {e}")
            return False

    def _execute_roll_decision(
        self,
        decision: TradeSignal,
        trade_date: date,
    ) -> tuple[bool, bool]:
        """执行展期决策 (参考 OrderGenerator.generate_roll)

        展期操作 = 平仓当前合约 + 开仓新合约

        Args:
            decision: ROLL 类型的交易决策信号
            trade_date: 交易日期

        Returns:
            (close_success, open_success) - 平仓和开仓是否成功
        """
        close_success = False
        open_success = False

        try:
            # 验证展期参数
            if not decision.roll_to_expiry:
                logger.warning(f"ROLL decision missing roll_to_expiry: {decision.reason}")
                return False, False

            # ========================================
            # 1. 平仓当前合约 (BUY to close)
            # ========================================
            position = decision.related_position or self._find_position_for_decision(decision)
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
                alert_type=decision.alert_type,
            )

            # 1.5. Trade 层：回填 underlying_price 到平仓记录
            try:
                stock_quote = self._data_provider.get_stock_quote(position.underlying)
                if stock_quote and stock_quote.close:
                    self._trade_simulator.trade_records[-1].underlying_price = stock_quote.close
            except Exception:
                pass

            # 2. Position 层：计算已实现盈亏
            pnl = self._position_manager.calculate_realized_pnl(
                position=position,
                execution=close_execution,
                close_reason=f"roll_to_{decision.roll_to_expiry}",
            )

            # 2.5. Trade 层：回填 PnL 和 position_id 到交易记录
            self._trade_simulator.update_last_trade_pnl(pnl)
            self._trade_simulator.update_last_trade_position_id(position.position_id)

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
            # type: ignore[arg-type] - roll positions always have non-None option fields
            new_symbol = self._build_roll_symbol(
                underlying=position.underlying,  # type: ignore[arg-type]
                expiry=new_expiry,
                strike=new_strike,  # type: ignore[arg-type]
                option_type=position.option_type,  # type: ignore[arg-type]
            )

            # 获取新合约价格
            # type: ignore[arg-type] - roll positions always have non-None option fields
            new_option_price = self._get_option_price_by_params(
                underlying=position.underlying,  # type: ignore[arg-type]
                option_type=position.option_type,  # type: ignore[arg-type]
                strike=new_strike,  # type: ignore[arg-type]
                expiration=new_expiry,  # type: ignore[arg-type]
            )

            if new_option_price is None or new_option_price <= 0:
                logger.warning(
                    f"Cannot get price for new contract {new_symbol}, "
                    f"using roll_credit or estimated price"
                )
                # 基于旧合约价格估价作为回退
                new_option_price = close_price * 1.1

            # 模拟开仓执行
            # type: ignore[arg-type] - roll positions always have non-None option fields
            open_execution = self._trade_simulator.execute_open(
                symbol=new_symbol,
                underlying=position.underlying,  # type: ignore[arg-type]
                option_type=position.option_type,  # type: ignore[arg-type]
                strike=new_strike,  # type: ignore[arg-type]
                expiration=new_expiry,  # type: ignore[arg-type]
                quantity=position.quantity,  # 保持相同数量 (负数 = SELL to open)
                mid_price=new_option_price,
                trade_date=trade_date,
                reason=f"roll_open: new expiry {decision.roll_to_expiry}",
                lot_size=position.lot_size,  # 保持与原持仓相同
            )

            # 开仓 Trade 层：回填 underlying_price 到开仓记录
            try:
                stock_quote = self._data_provider.get_stock_quote(position.underlying)
                if stock_quote and stock_quote.close:
                    self._trade_simulator.trade_records[-1].underlying_price = stock_quote.close
            except Exception:
                pass

            # Position 层: 创建持仓对象
            new_position = self._position_manager.create_position(open_execution)

            # Trade 层: 回填 position_id 到开仓交易记录
            self._trade_simulator.update_last_trade_position_id(new_position.position_id)

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
        decision: Any,
    ) -> SimulatedPosition | None:
        """根据决策查找对应持仓

        Args:
            decision: 交易决策

        Returns:
            SimulatedPosition 或 None
        """
        # 优先: 用 position_id 精确匹配
        if decision.position_id and decision.position_id in self._account_simulator.positions:
            return self._account_simulator.positions[decision.position_id]

        # 次选: 按 underlying + strike + expiry 匹配 (从 Account 层获取持仓)
        for position in self._account_simulator.positions.values():
            if (
                position.underlying == decision.underlying
                and position.strike == decision.strike
                and position.expiration is not None
                and position.expiration.isoformat() == decision.expiry
            ):
                return position

        # 兜底: 按 symbol 匹配 (跳过正股持仓，避免误匹配)
        for position in self._account_simulator.positions.values():
            if decision.underlying in position.symbol and not position.is_stock:
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
                    price = quote.close if quote.close is not None else quote.last_price
                    
                    if price is not None and price <= 0:
                        price = None
                    
                    return price

            return None

        except Exception:
            return None

    def _is_new_month(self, current_date: date) -> bool:
        """判断是否是新月份的第一个交易日"""
        current_month = current_date.year * 12 + current_date.month
        if self._last_withdrawal_month is None or current_month > self._last_withdrawal_month:
            self._last_withdrawal_month = current_month
            return True
        return False

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
            open_positions=self._snapshot_open_positions(),
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

    def _snapshot_open_positions(self) -> list[dict]:
        """快照回测结束时的未平仓持仓

        Returns:
            持仓字典列表 (用于持仓报表)
        """
        positions = []
        for pos in self._account_simulator.positions.values():
            positions.append({
                "position_id": pos.position_id,
                "symbol": pos.symbol,
                "asset_type": pos.asset_type.value if hasattr(pos.asset_type, 'value') else str(pos.asset_type),
                "underlying": pos.underlying,
                "option_type": pos.option_type.value if pos.option_type else None,
                "strike": pos.strike,
                "expiration": pos.expiration.isoformat() if pos.expiration else None,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl,
                "lot_size": pos.lot_size,
            })

        return positions

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
                action=TradeAction.OPEN,
                asset_type=AssetType.OPTION,  # 使用枚举
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
            close_action = TradeAction.CLOSE
            if pos.close_reason == "assigned":
                # 行权（ITM 到期）
                if pos.option_type == OptionType.PUT:
                    close_action = TradeAction.ASSIGN_PUT
                else:  # CALL
                    close_action = TradeAction.ASSIGN_CALL
            elif pos.close_reason and "expire" in pos.close_reason.lower():
                # 自然到期（OTM 或其他）
                close_action = TradeAction.EXPIRE

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
                asset_type=AssetType.OPTION,  # 期权交易
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
