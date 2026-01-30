"""
Account Simulator - 账户模拟器

模拟回测过程中的账户状态，包括:
- 现金余额追踪
- 保证金计算 (使用 Reg T 公式)
- NLV (净清算价值) 计算
- 每日权益快照

Usage:
    simulator = AccountSimulator(initial_capital=100_000)

    # 开仓
    simulator.open_position(position)

    # 更新持仓市值
    simulator.update_position_value(position_id, new_market_value, new_margin)

    # 平仓
    pnl = simulator.close_position(position_id, close_price, close_date)

    # 获取账户状态
    state = simulator.get_account_state()
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from src.business.trading.models.decision import AccountState
from src.data.models.margin import calc_reg_t_margin_short_put, calc_reg_t_margin_short_call

logger = logging.getLogger(__name__)


@dataclass
class SimulatedPosition:
    """模拟持仓

    记录单个期权持仓的所有信息。
    """

    position_id: str
    symbol: str  # 期权合约标识
    underlying: str  # 标的代码
    option_type: Literal["call", "put"]
    strike: float
    expiration: date
    quantity: int  # 正数=多头, 负数=空头
    entry_price: float  # 开仓价格 (每张合约)
    entry_date: date
    lot_size: int = 100  # 每张合约对应的股数

    # 当前市值相关
    current_price: float = 0.0  # 当前期权价格
    underlying_price: float = 0.0  # 当前标的价格
    market_value: float = 0.0  # 当前市值 (quantity * current_price * lot_size)
    margin_required: float = 0.0  # 保证金需求

    # P&L
    unrealized_pnl: float = 0.0
    commission_paid: float = 0.0

    # 状态
    is_closed: bool = False
    close_date: date | None = None
    close_price: float | None = None
    close_reason: str | None = None
    realized_pnl: float | None = None

    @property
    def is_short(self) -> bool:
        """是否空头"""
        return self.quantity < 0

    @property
    def notional_value(self) -> float:
        """名义价值 = |quantity| * strike * lot_size"""
        return abs(self.quantity) * self.strike * self.lot_size

    def update_market_value(
        self,
        current_price: float,
        underlying_price: float,
    ) -> None:
        """更新市值

        Args:
            current_price: 当前期权价格 (per share)
            underlying_price: 当前标的价格
        """
        self.current_price = current_price
        self.underlying_price = underlying_price

        # 市值 = quantity * price * lot_size
        # 多头: 正值, 空头: 负值
        self.market_value = self.quantity * current_price * self.lot_size

        # 计算未实现盈亏
        entry_value = self.quantity * self.entry_price * self.lot_size
        self.unrealized_pnl = self.market_value - entry_value

        # 计算保证金 (仅空头需要)
        if self.is_short:
            self._calculate_margin(underlying_price)
        else:
            self.margin_required = 0.0

    def _calculate_margin(self, underlying_price: float) -> None:
        """计算保证金需求 (Reg T)"""
        if self.option_type == "put":
            margin_per_share = calc_reg_t_margin_short_put(
                underlying_price=underlying_price,
                strike=self.strike,
                premium=self.current_price,
            )
        else:
            margin_per_share = calc_reg_t_margin_short_call(
                underlying_price=underlying_price,
                strike=self.strike,
                premium=self.current_price,
            )

        self.margin_required = margin_per_share * abs(self.quantity) * self.lot_size


@dataclass
class EquitySnapshot:
    """每日权益快照"""

    date: date
    cash: float
    positions_value: float  # 持仓市值总和
    margin_used: float
    nlv: float  # Net Liquidation Value
    unrealized_pnl: float
    realized_pnl_cumulative: float
    position_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "cash": self.cash,
            "positions_value": self.positions_value,
            "margin_used": self.margin_used,
            "nlv": self.nlv,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl_cumulative": self.realized_pnl_cumulative,
            "position_count": self.position_count,
        }


class AccountSimulator:
    """账户模拟器

    模拟回测过程中的账户状态变化。

    账户模型:
    - NLV = Cash + Positions Market Value (for long positions)
           = Cash - Positions Market Value (for short positions)
    - Available Margin = NLV * max_margin_utilization - Margin Used
    - Cash 会因为开仓 (收取权利金) 和平仓 (支付权利金) 而变化

    对于 SHORT PUT:
    - 开仓: Cash += Premium (收取权利金)
    - 平仓: Cash -= Close Price (买回合约)
    - 到期无价值: 不需要额外操作
    - 被行权: Cash -= Strike * Quantity (被迫买入股票)

    Usage:
        simulator = AccountSimulator(initial_capital=100_000)

        # 卖出 1 张 PUT
        pos = SimulatedPosition(
            position_id="001",
            underlying="AAPL",
            option_type="put",
            strike=150,
            expiration=date(2024, 3, 15),
            quantity=-1,  # 负数=卖出
            entry_price=3.50,
            entry_date=date(2024, 2, 1),
        )
        simulator.open_position(pos, commission=0.65)

        # 每日更新
        simulator.update_position_value("001", current_price=2.00, underlying_price=155)

        # 平仓
        pnl = simulator.close_position("001", close_price=1.00, close_date=date(2024, 3, 1))
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        max_margin_utilization: float = 0.70,
        broker: str = "backtest",
    ) -> None:
        """初始化账户模拟器

        Args:
            initial_capital: 初始资金
            max_margin_utilization: 最大保证金使用率
            broker: 券商名称 (用于 AccountState)
        """
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._max_margin_utilization = max_margin_utilization
        self._broker = broker

        # 持仓管理
        self._positions: dict[str, SimulatedPosition] = {}
        self._closed_positions: list[SimulatedPosition] = []

        # 累计已实现盈亏
        self._realized_pnl_cumulative = 0.0

        # 每日快照
        self._equity_snapshots: list[EquitySnapshot] = []

        # 当前日期
        self._current_date: date | None = None

    @property
    def cash(self) -> float:
        """当前现金"""
        return self._cash

    @property
    def positions(self) -> dict[str, SimulatedPosition]:
        """当前持仓"""
        return self._positions

    @property
    def position_count(self) -> int:
        """持仓数量"""
        return len(self._positions)

    def open_position(
        self,
        position: SimulatedPosition,
        commission: float = 0.65,
    ) -> bool:
        """开仓

        Args:
            position: 持仓信息
            commission: 手续费

        Returns:
            是否成功开仓
        """
        # 检查是否有足够的保证金
        required_margin = self._estimate_margin(position)

        if required_margin > self.available_margin:
            logger.warning(
                f"Insufficient margin for {position.symbol}: "
                f"required={required_margin:.2f}, available={self.available_margin:.2f}"
            )
            return False

        # 计算开仓现金流
        # 卖出期权: 收取权利金
        # 买入期权: 支付权利金
        premium_flow = -position.quantity * position.entry_price * position.lot_size
        total_commission = commission * abs(position.quantity)

        self._cash += premium_flow - total_commission

        # 记录手续费
        position.commission_paid = total_commission

        # 初始化市值
        position.current_price = position.entry_price
        position.market_value = position.quantity * position.entry_price * position.lot_size
        position.margin_required = required_margin

        # 添加到持仓
        self._positions[position.position_id] = position

        logger.debug(
            f"Opened position {position.position_id}: "
            f"{position.quantity} {position.symbol} @ {position.entry_price:.2f}, "
            f"cash_flow={premium_flow:.2f}, commission={total_commission:.2f}"
        )

        return True

    def close_position(
        self,
        position_id: str,
        close_price: float,
        close_date: date,
        close_reason: str = "manual",
        commission: float = 0.65,
    ) -> float | None:
        """平仓

        Args:
            position_id: 持仓 ID
            close_price: 平仓价格 (per share)
            close_date: 平仓日期
            close_reason: 平仓原因
            commission: 手续费

        Returns:
            已实现盈亏，失败返回 None
        """
        if position_id not in self._positions:
            logger.warning(f"Position not found: {position_id}")
            return None

        position = self._positions[position_id]

        # 计算平仓现金流
        # SHORT 平仓 (买回): 支付权利金 → cash 减少
        # LONG 平仓 (卖出): 收取权利金 → cash 增加
        # 使用 -quantity 使得: SHORT (qty<0) → 支付, LONG (qty>0) → 收取
        close_flow = -position.quantity * close_price * position.lot_size
        total_commission = commission * abs(position.quantity)

        self._cash += close_flow - total_commission

        # 计算已实现盈亏
        # PnL = (close_price - entry_price) * quantity * lot_size - commissions
        # SHORT (qty<0): 当 close < entry 时盈利 (负*负=正)
        # LONG (qty>0): 当 close > entry 时盈利 (正*正=正)
        realized_pnl = (close_price - position.entry_price) * position.quantity * position.lot_size
        realized_pnl -= (position.commission_paid + total_commission)

        # 更新持仓信息
        position.is_closed = True
        position.close_date = close_date
        position.close_price = close_price
        position.close_reason = close_reason
        position.realized_pnl = realized_pnl
        position.commission_paid += total_commission

        # 更新累计已实现盈亏
        self._realized_pnl_cumulative += realized_pnl

        # 移动到已平仓列表
        self._closed_positions.append(position)
        del self._positions[position_id]

        logger.debug(
            f"Closed position {position_id}: "
            f"close_price={close_price:.2f}, realized_pnl={realized_pnl:.2f}"
        )

        return realized_pnl

    def expire_position(
        self,
        position_id: str,
        expire_date: date,
        final_underlying_price: float,
    ) -> float | None:
        """期权到期处理

        Args:
            position_id: 持仓 ID
            expire_date: 到期日
            final_underlying_price: 到期时标的价格

        Returns:
            已实现盈亏
        """
        if position_id not in self._positions:
            return None

        position = self._positions[position_id]

        # 判断是否 ITM
        if position.option_type == "put":
            is_itm = final_underlying_price < position.strike
        else:  # call
            is_itm = final_underlying_price > position.strike

        if is_itm:
            # ITM: 被行权
            return self._handle_assignment(position, expire_date, final_underlying_price)
        else:
            # OTM: 到期无价值
            return self.close_position(
                position_id,
                close_price=0.0,
                close_date=expire_date,
                close_reason="expired_worthless",
                commission=0.0,  # 到期不收手续费
            )

    def _handle_assignment(
        self,
        position: SimulatedPosition,
        expire_date: date,
        final_underlying_price: float,
    ) -> float:
        """处理期权被行权

        SHORT PUT 被行权: 以 strike 价格买入股票
        SHORT CALL 被行权: 以 strike 价格卖出股票

        简化处理: 假设立即以市价平仓股票
        """
        # 计算行权损益
        if position.option_type == "put" and position.is_short:
            # 被迫买入股票，然后立即卖出
            # 损失 = (Strike - Market) * Quantity * LotSize
            assignment_loss = (position.strike - final_underlying_price) * abs(position.quantity) * position.lot_size
        elif position.option_type == "call" and position.is_short:
            # 被迫卖出股票 (假设有现金覆盖)
            assignment_loss = (final_underlying_price - position.strike) * abs(position.quantity) * position.lot_size
        else:
            assignment_loss = 0.0

        # 关闭期权持仓
        # 期权价值 = 内在价值
        if position.option_type == "put":
            intrinsic_value = max(0, position.strike - final_underlying_price)
        else:
            intrinsic_value = max(0, final_underlying_price - position.strike)

        realized_pnl = self.close_position(
            position.position_id,
            close_price=intrinsic_value,
            close_date=expire_date,
            close_reason="assigned",
            commission=0.0,
        )

        if realized_pnl is not None:
            # 减去行权损失 (已包含在平仓计算中)
            logger.debug(
                f"Position {position.position_id} assigned: "
                f"assignment_loss={assignment_loss:.2f}, realized_pnl={realized_pnl:.2f}"
            )

        return realized_pnl or 0.0

    def update_position_value(
        self,
        position_id: str,
        current_price: float,
        underlying_price: float,
    ) -> None:
        """更新持仓市值

        Args:
            position_id: 持仓 ID
            current_price: 当前期权价格
            underlying_price: 当前标的价格
        """
        if position_id not in self._positions:
            return

        self._positions[position_id].update_market_value(current_price, underlying_price)

    def update_all_positions(
        self,
        price_func,
    ) -> None:
        """更新所有持仓市值

        Args:
            price_func: 获取价格的函数 (position_id) -> (option_price, underlying_price)
        """
        for pos_id, position in self._positions.items():
            try:
                option_price, underlying_price = price_func(pos_id)
                position.update_market_value(option_price, underlying_price)
            except Exception as e:
                logger.warning(f"Failed to update position {pos_id}: {e}")

    def take_snapshot(self, snapshot_date: date) -> EquitySnapshot:
        """记录每日权益快照

        Args:
            snapshot_date: 快照日期

        Returns:
            EquitySnapshot
        """
        self._current_date = snapshot_date

        # 计算各项指标
        positions_value = sum(pos.market_value for pos in self._positions.values())
        margin_used = sum(pos.margin_required for pos in self._positions.values())
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self._positions.values())

        # NLV = Cash + Positions Value
        # 注意: 对于空头持仓，market_value 是负数
        nlv = self._cash + positions_value

        snapshot = EquitySnapshot(
            date=snapshot_date,
            cash=self._cash,
            positions_value=positions_value,
            margin_used=margin_used,
            nlv=nlv,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_cumulative=self._realized_pnl_cumulative,
            position_count=len(self._positions),
        )

        self._equity_snapshots.append(snapshot)
        return snapshot

    def get_account_state(self) -> AccountState:
        """获取当前账户状态

        Returns:
            AccountState 实例，与实盘格式一致
        """
        positions_value = sum(pos.market_value for pos in self._positions.values())
        margin_used = sum(pos.margin_required for pos in self._positions.values())
        nlv = self._cash + positions_value

        # 计算各项比例
        margin_utilization = margin_used / nlv if nlv > 0 else 0.0
        cash_ratio = self._cash / nlv if nlv > 0 else 1.0

        # 计算杠杆 (名义价值 / NLV)
        total_notional = sum(pos.notional_value for pos in self._positions.values())
        gross_leverage = total_notional / nlv if nlv > 0 else 0.0

        # 按标的计算暴露
        exposure_by_underlying: dict[str, float] = {}
        for pos in self._positions.values():
            underlying = pos.underlying
            if underlying not in exposure_by_underlying:
                exposure_by_underlying[underlying] = 0.0
            exposure_by_underlying[underlying] += pos.notional_value

        return AccountState(
            broker=self._broker,
            account_type="paper",
            total_equity=nlv,
            cash_balance=self._cash,
            available_margin=self.available_margin,
            used_margin=margin_used,
            margin_utilization=margin_utilization,
            cash_ratio=cash_ratio,
            gross_leverage=gross_leverage,
            total_position_count=len(self._positions),
            option_position_count=len(self._positions),
            stock_position_count=0,
            exposure_by_underlying=exposure_by_underlying,
            timestamp=datetime.now(),
        )

    @property
    def nlv(self) -> float:
        """当前净清算价值"""
        positions_value = sum(pos.market_value for pos in self._positions.values())
        return self._cash + positions_value

    @property
    def margin_used(self) -> float:
        """已用保证金"""
        return sum(pos.margin_required for pos in self._positions.values())

    @property
    def available_margin(self) -> float:
        """可用保证金"""
        max_margin = self.nlv * self._max_margin_utilization
        return max(0, max_margin - self.margin_used)

    @property
    def equity_snapshots(self) -> list[EquitySnapshot]:
        """所有权益快照"""
        return self._equity_snapshots

    @property
    def closed_positions(self) -> list[SimulatedPosition]:
        """已平仓持仓"""
        return self._closed_positions

    @property
    def realized_pnl(self) -> float:
        """累计已实现盈亏"""
        return self._realized_pnl_cumulative

    @property
    def unrealized_pnl(self) -> float:
        """当前未实现盈亏"""
        return sum(pos.unrealized_pnl for pos in self._positions.values())

    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self._realized_pnl_cumulative + self.unrealized_pnl

    def _estimate_margin(self, position: SimulatedPosition) -> float:
        """估算开仓所需保证金"""
        if not position.is_short:
            return 0.0

        # 使用开仓价格和当前标的价格估算
        underlying_price = position.underlying_price or position.strike

        if position.option_type == "put":
            margin_per_share = calc_reg_t_margin_short_put(
                underlying_price=underlying_price,
                strike=position.strike,
                premium=position.entry_price,
            )
        else:
            margin_per_share = calc_reg_t_margin_short_call(
                underlying_price=underlying_price,
                strike=position.strike,
                premium=position.entry_price,
            )

        return margin_per_share * abs(position.quantity) * position.lot_size

    def reset(self) -> None:
        """重置账户状态"""
        self._cash = self._initial_capital
        self._positions.clear()
        self._closed_positions.clear()
        self._realized_pnl_cumulative = 0.0
        self._equity_snapshots.clear()
        self._current_date = None
