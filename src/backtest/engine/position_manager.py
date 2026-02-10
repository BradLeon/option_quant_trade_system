"""
Position Manager - 持仓管理器

纯持仓生命周期管理，不包装 AccountSimulator。

主要职责：
1. 基于 TradeExecution 创建 SimulatedPosition
2. 计算持仓级字段 (margin, market_value, realized_pnl)
3. 更新持仓市场数据 (从 DataProvider 获取)
4. 转换 SimulatedPosition → PositionData (监控用)

不负责：
- 存储持仓 (由 AccountSimulator 负责)
- 账户状态管理 (由 AccountSimulator 负责)
- 交易记录 (由 TradeSimulator 负责)

Usage:
    manager = PositionManager(data_provider, price_mode=PriceMode.OPEN)

    # 创建持仓 (不注册到账户)
    position = manager.create_position(execution)

    # 计算 PnL
    realized_pnl = manager.calculate_realized_pnl(position, close_execution)

    # 更新市场数据
    manager.update_position_market_data(position)
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from src.backtest.config.backtest_config import PriceMode
from src.backtest.engine.account_simulator import (
    SimulatedPosition,
)
from src.backtest.engine.trade_simulator import TradeExecution
from src.business.monitoring.models import PositionData
from src.data.models import StockQuote
from src.data.models.option import OptionType
from src.data.providers.base import DataProvider
from src.engine.models.enums import StrategyType

logger = logging.getLogger(__name__)


class DataNotFoundError(Exception):
    """数据未找到异常

    当回测所需的市场数据缺失时抛出，而不是使用不合理的回退值。
    """

    pass


@dataclass
class PositionPnL:
    """持仓盈亏统计"""

    position_id: str
    symbol: str
    underlying: str
    entry_date: date
    entry_price: float
    current_price: float
    quantity: int

    # P&L
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    commission_paid: float = 0.0

    # 到期相关
    dte: int | None = None
    days_held: int = 0

    # 平仓信息 (如已平仓)
    is_closed: bool = False
    close_date: date | None = None
    close_price: float | None = None
    close_reason: str | None = None
    realized_pnl: float | None = None
    realized_pnl_pct: float | None = None


class PositionManager:
    """持仓管理器 - 纯持仓生命周期管理，不包装账户

    职责：
    1. 基于 TradeExecution 创建 SimulatedPosition
    2. 计算持仓级字段 (margin, market_value)
    3. 计算已实现盈亏
    4. 更新持仓市场数据
    5. 转换 SimulatedPosition → PositionData (监控用)
    """

    def __init__(
        self,
        data_provider: DataProvider,
        price_mode: PriceMode = PriceMode.OPEN,
    ) -> None:
        """初始化持仓管理器

        Args:
            data_provider: 数据提供者 (用于获取价格和 Greeks)
            price_mode: 价格模式 (OPEN/CLOSE/MID)
        """
        self._data_provider = data_provider
        self._price_mode = price_mode
        self._position_counter = 0
        self._current_date: date | None = None

    def set_date(self, d: date) -> None:
        """设置当前日期"""
        self._current_date = d

    def _generate_position_id(self) -> str:
        """生成唯一的持仓 ID"""
        self._position_counter += 1
        return f"P{self._position_counter:08d}"

    def _estimate_margin(self, position: SimulatedPosition) -> float:
        """估算持仓保证金

        使用 Reg T 公式计算保证金。

        Args:
            position: 持仓信息

        Returns:
            保证金金额
        """
        from src.data.models.margin import (
            calc_reg_t_margin_short_call,
            calc_reg_t_margin_short_put,
        )

        abs_qty = abs(position.quantity)
        underlying_price = position.underlying_price or position.strike
        option_price = position.current_price or position.entry_price

        if position.is_short:
            # Margin functions return per-share margin, multiply by qty * lot_size
            if position.option_type == OptionType.PUT:
                per_share_margin = calc_reg_t_margin_short_put(
                    underlying_price=underlying_price,
                    strike=position.strike,
                    premium=option_price,
                )
            else:  # CALL
                per_share_margin = calc_reg_t_margin_short_call(
                    underlying_price=underlying_price,
                    strike=position.strike,
                    premium=option_price,
                )
            return per_share_margin * abs_qty * position.lot_size
        else:
            # Long positions: margin = premium paid (already settled)
            return 0.0

    def create_position(
        self,
        execution: TradeExecution,
    ) -> SimulatedPosition:
        """基于交易执行创建持仓对象

        仅创建持仓对象，不注册到账户。
        BacktestExecutor 负责调用 AccountSimulator.add_position()。

        Args:
            execution: 交易执行记录

        Returns:
            创建的 SimulatedPosition
        """
        position_id = self._generate_position_id()

        # execution.quantity 已经是有符号的: 负数=卖出, 正数=买入
        position = SimulatedPosition(
            position_id=position_id,
            symbol=execution.symbol,
            underlying=execution.underlying,
            option_type=execution.option_type,
            strike=execution.strike,
            expiration=execution.expiration,
            quantity=execution.quantity,  # 直接使用，已经是有符号
            entry_price=execution.fill_price,
            entry_date=execution.trade_date,
            lot_size=execution.lot_size,
        )

        # Position 层职责: 计算持仓字段
        position.current_price = execution.fill_price
        # market_value = -gross_amount (gross_amount 是现金流视角，market_value 是持仓视角)
        position.market_value = -execution.gross_amount
        position.commission_paid = execution.commission
        position.margin_required = self._estimate_margin(position)

        logger.info(
            f"Created position: {execution.quantity} {execution.symbol} "
            f"@ {execution.fill_price:.2f}, margin={position.margin_required:.2f}"
        )

        return position

    def calculate_realized_pnl(
        self,
        position: SimulatedPosition,
        execution: TradeExecution,
        close_reason: str | None = None,
    ) -> float:
        """计算已实现盈亏

        仅计算 PnL，不修改持仓状态。
        BacktestExecutor 负责调用 AccountSimulator.remove_position()。

        Args:
            position: 持仓
            execution: 平仓/到期的交易执行记录
            close_reason: 平仓原因 (可选)

        Returns:
            已实现盈亏
        """
        # PnL = (close_price - entry_price) * quantity * lot_size - total_commission
        # SHORT (qty<0): 当 close < entry 时盈利
        # LONG (qty>0): 当 close > entry 时盈利
        realized_pnl = (
            (execution.fill_price - position.entry_price)
            * position.quantity
            * position.lot_size
        )
        realized_pnl -= position.commission_paid + execution.commission

        return realized_pnl

    def finalize_close(
        self,
        position: SimulatedPosition,
        execution: TradeExecution,
        realized_pnl: float,
        close_reason: str | None = None,
    ) -> None:
        """完成持仓关闭，更新持仓字段

        在 AccountSimulator.remove_position() 成功后调用。

        Args:
            position: 持仓
            execution: 平仓执行记录
            realized_pnl: 已实现盈亏
            close_reason: 平仓原因
        """
        reason = close_reason if close_reason is not None else execution.reason

        position.is_closed = True
        position.close_date = execution.trade_date
        position.close_price = execution.fill_price
        position.close_reason = reason
        position.realized_pnl = realized_pnl
        position.commission_paid += execution.commission

        logger.info(
            f"Finalized close: {position.position_id} @ {execution.fill_price:.2f}, "
            f"PnL: {realized_pnl:.2f}, reason: {reason}"
        )

    def update_position_market_data(
        self,
        position: SimulatedPosition,
    ) -> None:
        """从市场数据更新单个持仓价格

        Args:
            position: 持仓

        Raises:
            DataNotFoundError: 当关键市场数据缺失时
        """
        # 获取标的报价
        stock_quote = self._data_provider.get_stock_quote(position.underlying)
        if stock_quote is None:
            raise DataNotFoundError(
                f"Stock quote not found for {position.underlying} "
                f"on {self._current_date}"
            )

        # 根据 price_mode 获取价格
        underlying_price = self._get_price_by_mode(stock_quote)
        if underlying_price is None or underlying_price <= 0:
            raise DataNotFoundError(
                f"Invalid underlying price for {position.underlying}: "
                f"mode={self._price_mode.value}, quote={stock_quote}"
            )

        # 获取期权报价
        option_price = self._get_option_price(
            underlying=position.underlying,
            option_type=position.option_type,
            strike=position.strike,
            expiration=position.expiration,
        )

        if option_price is not None:
            position.update_market_value(option_price, underlying_price)
        else:
            # 期权价格缺失时使用内在价值
            if position.option_type == OptionType.PUT:
                intrinsic = max(0, position.strike - underlying_price)
            else:
                intrinsic = max(0, underlying_price - position.strike)

            logger.warning(
                f"Option price not found for {position.underlying} "
                f"{position.option_type.value} K={position.strike} exp={position.expiration} "
                f"on {self._current_date}, using intrinsic value: {intrinsic:.2f}"
            )
            position.update_market_value(intrinsic, underlying_price)

    def update_all_positions_market_data(
        self,
        positions: dict[str, SimulatedPosition],
    ) -> None:
        """更新所有持仓的市场数据

        Args:
            positions: 持仓字典 (从 AccountSimulator.positions 获取)
        """
        for position in positions.values():
            self.update_position_market_data(position)

    def _get_price_by_mode(self, quote: StockQuote) -> float | None:
        """根据 price_mode 获取价格"""
        if self._price_mode == PriceMode.OPEN:
            return quote.open
        elif self._price_mode == PriceMode.CLOSE:
            return quote.close
        elif self._price_mode == PriceMode.MID:
            if quote.open and quote.close:
                return (quote.open + quote.close) / 2
            return quote.close
        return quote.close

    def _get_option_price(
        self,
        underlying: str,
        option_type: OptionType,
        strike: float,
        expiration: date,
    ) -> float | None:
        """从期权链获取期权价格"""
        try:
            chain = self._data_provider.get_option_chain(
                underlying=underlying,
                expiry_start=expiration,
                expiry_end=expiration,
            )

            if chain is None:
                return None

            contracts = chain.puts if option_type == OptionType.PUT else chain.calls

            for quote in contracts:
                if (
                    quote.contract.strike_price == strike
                    and quote.contract.expiry_date == expiration
                ):
                    if self._price_mode == PriceMode.OPEN:
                        open_price = getattr(quote, "open", None)
                        if open_price is not None and open_price > 0:
                            return open_price
                        return quote.last_price

                    elif self._price_mode == PriceMode.MID:
                        if (
                            quote.bid
                            and quote.ask
                            and quote.bid > 0
                            and quote.ask > 0
                        ):
                            return (quote.bid + quote.ask) / 2
                        return quote.last_price

                    else:  # CLOSE
                        close_price = getattr(quote, "close", None)
                        if close_price is not None and close_price > 0:
                            return close_price
                        return quote.last_price

            return None

        except Exception as e:
            logger.warning(f"Failed to get option price: {e}")
            return None

    def get_position_data_for_monitoring(
        self,
        positions: dict[str, SimulatedPosition],
        as_of_date: date | None = None,
    ) -> list[PositionData]:
        """获取用于监控的持仓数据列表

        Args:
            positions: 持仓字典 (从 AccountSimulator.positions 获取)
            as_of_date: 日期 (用于计算 DTE)

        Returns:
            PositionData 列表
        """
        position_data_list: list[PositionData] = []
        ref_date = as_of_date or self._current_date or date.today()

        for pos_id, position in positions.items():
            try:
                position_data = self._convert_to_position_data(position, ref_date)
                position_data_list.append(position_data)
            except Exception as e:
                logger.warning(f"Failed to convert position {pos_id}: {e}")

        return position_data_list

    def _convert_to_position_data(
        self,
        position: SimulatedPosition,
        ref_date: date,
    ) -> PositionData:
        """将 SimulatedPosition 转换为 PositionData"""
        # 计算 DTE
        dte = (position.expiration - ref_date).days

        # 获取 Greeks
        delta, gamma, theta, vega, iv = self._get_greeks(position)

        # 计算 moneyness 和 OTM%
        underlying_price = position.underlying_price or position.strike
        moneyness = (underlying_price - position.strike) / position.strike

        if position.option_type == OptionType.PUT:
            otm_pct = (
                (underlying_price - position.strike) / underlying_price
                if underlying_price > 0
                else 0.0
            )
        else:
            otm_pct = (
                (position.strike - underlying_price) / underlying_price
                if underlying_price > 0
                else 0.0
            )

        # 计算盈亏百分比
        entry_value = abs(position.quantity * position.entry_price * position.lot_size)
        unrealized_pnl_pct = (
            position.unrealized_pnl / entry_value if entry_value > 0 else 0.0
        )

        # 构建期权 symbol
        expiry_str = position.expiration.strftime("%Y%m%d")
        option_symbol = (
            f"{position.underlying} "
            f"{expiry_str} "
            f"{position.strike:.1f}{position.option_type.value[0].upper()}"
        )

        # 推断策略类型
        # 注意: StrategyType 枚举只有 SHORT_PUT, NAKED_CALL, COVERED_CALL 等
        # 没有 LONG_PUT/LONG_CALL (长期权一般不作为独立策略)
        if position.option_type == OptionType.PUT and position.is_short:
            strategy_type = StrategyType.SHORT_PUT
        elif position.option_type == OptionType.CALL and position.is_short:
            strategy_type = StrategyType.NAKED_CALL  # 裸卖 Call
        else:
            # 长期权标记为 UNKNOWN
            strategy_type = StrategyType.UNKNOWN

        return PositionData(
            position_id=position.position_id,
            symbol=option_symbol,
            asset_type="option",
            quantity=position.quantity,
            entry_price=position.entry_price,
            current_price=position.current_price,
            market_value=position.market_value,
            unrealized_pnl=position.unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            currency="USD",
            broker="backtest",
            timestamp=datetime.now(),
            underlying=position.underlying,
            option_type=position.option_type.value,
            strike=position.strike,
            expiry=expiry_str,
            dte=dte,
            contract_multiplier=position.lot_size,
            moneyness=moneyness,
            otm_pct=otm_pct,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            iv=iv,
            underlying_price=position.underlying_price,
            strategy_type=strategy_type,
            margin=position.margin_required,
        )

    def _get_greeks(
        self,
        position: SimulatedPosition,
    ) -> tuple[float | None, float | None, float | None, float | None, float | None]:
        """获取持仓的 Greeks"""
        try:
            chain = self._data_provider.get_option_chain(
                underlying=position.underlying,
                expiry_start=position.expiration,
                expiry_end=position.expiration,
            )

            if chain is None:
                return None, None, None, None, None

            contracts = (
                chain.puts if position.option_type == OptionType.PUT else chain.calls
            )

            for quote in contracts:
                if (
                    quote.contract.strike_price == position.strike
                    and quote.contract.expiry_date == position.expiration
                ):
                    greeks = quote.greeks if hasattr(quote, "greeks") else None
                    if greeks:
                        raw_delta = greeks.delta if greeks.delta is not None else None
                        position_delta = (
                            raw_delta * position.quantity if raw_delta else None
                        )
                        position_gamma = (
                            greeks.gamma * abs(position.quantity) if greeks.gamma else None
                        )
                        position_theta = (
                            greeks.theta * position.quantity if greeks.theta else None
                        )
                        position_vega = (
                            greeks.vega * abs(position.quantity) if greeks.vega else None
                        )

                        return (
                            position_delta,
                            position_gamma,
                            position_theta,
                            position_vega,
                            quote.iv,
                        )

            return None, None, None, None, None

        except Exception as e:
            logger.debug(f"Failed to get Greeks for {position.symbol}: {e}")
            return None, None, None, None, None

    def get_expiring_positions(
        self,
        positions: dict[str, SimulatedPosition],
        days_ahead: int = 7,
    ) -> list[SimulatedPosition]:
        """获取即将到期的持仓

        Args:
            positions: 持仓字典
            days_ahead: 未来多少天内到期

        Returns:
            持仓列表
        """
        ref_date = self._current_date or date.today()
        cutoff = ref_date.toordinal() + days_ahead

        return [
            pos for pos in positions.values() if pos.expiration.toordinal() <= cutoff
        ]

    def check_expirations(
        self,
        positions: dict[str, SimulatedPosition],
    ) -> list[SimulatedPosition]:
        """检查当天到期的持仓

        Args:
            positions: 持仓字典

        Returns:
            到期的持仓列表
        """
        ref_date = self._current_date or date.today()
        return [pos for pos in positions.values() if pos.expiration == ref_date]

    def get_positions_by_underlying(
        self,
        positions: dict[str, SimulatedPosition],
    ) -> dict[str, list[SimulatedPosition]]:
        """按标的分组持仓

        Args:
            positions: 持仓字典

        Returns:
            {underlying: [positions]}
        """
        grouped: dict[str, list[SimulatedPosition]] = {}
        for pos in positions.values():
            if pos.underlying not in grouped:
                grouped[pos.underlying] = []
            grouped[pos.underlying].append(pos)
        return grouped

    def get_position_pnl(
        self,
        position: SimulatedPosition,
        closed_positions: list[SimulatedPosition] | None = None,
    ) -> PositionPnL:
        """获取单个持仓的盈亏信息

        Args:
            position: 持仓
            closed_positions: 已关闭持仓列表 (可选)

        Returns:
            PositionPnL
        """
        ref_date = self._current_date or date.today()

        if not position.is_closed:
            entry_value = abs(
                position.quantity * position.entry_price * position.lot_size
            )
            unrealized_pnl_pct = (
                position.unrealized_pnl / entry_value if entry_value > 0 else 0.0
            )

            return PositionPnL(
                position_id=position.position_id,
                symbol=position.symbol,
                underlying=position.underlying,
                entry_date=position.entry_date,
                entry_price=position.entry_price,
                current_price=position.current_price,
                quantity=position.quantity,
                unrealized_pnl=position.unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                commission_paid=position.commission_paid,
                dte=(position.expiration - ref_date).days,
                days_held=(ref_date - position.entry_date).days,
                is_closed=False,
            )
        else:
            entry_value = abs(
                position.quantity * position.entry_price * position.lot_size
            )
            realized_pnl_pct = (
                position.realized_pnl / entry_value
                if entry_value > 0 and position.realized_pnl
                else 0.0
            )

            return PositionPnL(
                position_id=position.position_id,
                symbol=position.symbol,
                underlying=position.underlying,
                entry_date=position.entry_date,
                entry_price=position.entry_price,
                current_price=position.close_price or 0.0,
                quantity=position.quantity,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
                commission_paid=position.commission_paid,
                dte=0,
                days_held=(
                    (position.close_date - position.entry_date).days
                    if position.close_date
                    else 0
                ),
                is_closed=True,
                close_date=position.close_date,
                close_price=position.close_price,
                close_reason=position.close_reason,
                realized_pnl=position.realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
            )

    def reset(self) -> None:
        """重置管理器状态"""
        self._position_counter = 0
        self._current_date = None
