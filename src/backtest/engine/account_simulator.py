"""
Account Simulator - 账户模拟器

模拟回测过程中的账户状态，包括:
- 现金余额追踪
- 保证金计算 (使用 Reg T 公式)
- NLV (净清算价值) 计算
- 每日权益快照

注意: 手续费由 TradeSimulator 计算，AccountSimulator 仅接收并记录总手续费。

Usage:
    simulator = AccountSimulator(initial_capital=100_000)

    # 开仓 (手续费由 TradeSimulator 计算后传入)
    simulator.open_position(position, total_commission=1.30)

    # 更新持仓市值
    simulator.update_position_value(position_id, new_market_value, new_margin)

    # 平仓 (手续费由 TradeSimulator 计算后传入)
    pnl = simulator.close_position(position_id, close_price, close_date, total_commission=1.30)

    # 获取账户状态
    state = simulator.get_account_state()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.business.trading.models.decision import AccountState
from src.data.models.margin import calc_reg_t_margin_short_put, calc_reg_t_margin_short_call
from src.data.models.option import OptionType

logger = logging.getLogger(__name__)


@dataclass
class SimulatedPosition:
    """模拟持仓

    记录单个期权持仓的所有信息。
    """

    position_id: str
    symbol: str  # 期权合约标识
    underlying: str  # 标的代码
    option_type: OptionType  # 期权类型 (CALL/PUT)
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
        if self.option_type == OptionType.PUT:
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
            option_type=OptionType.PUT,
            strike=150,
            expiration=date(2024, 3, 15),
            quantity=-1,  # 负数=卖出
            entry_price=3.50,
            entry_date=date(2024, 2, 1),
        )
        simulator.open_position(pos, total_commission=1.00)  # 1 张合约，手续费由 TradeSimulator 计算

        # 每日更新
        simulator.update_position_value("001", current_price=2.00, underlying_price=155)

        # 平仓
        pnl = simulator.close_position("001", close_price=1.00, close_date=date(2024, 3, 1), total_commission=1.00)
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

    def add_position(
        self,
        position: SimulatedPosition,
        cash_change: float,
    ) -> bool:
        """添加持仓 (简化版本，Position 字段已由 PositionTracker 设置)

        这是 open_position 的新版本，供重构后的 PositionTracker 使用。
        Position 层负责计算 position 的字段，Account 层只负责：
        1. 检查保证金
        2. 更新现金 (直接使用传入的 cash_change，不重新计算)
        3. 存储持仓

        Args:
            position: 持仓信息 (字段已由 PositionTracker 填充)
            cash_change: 现金变动 (已由 Trade 层计算，即 TradeExecution.net_amount)

        Returns:
            是否成功添加持仓
        """
        # 检查是否有足够的保证金
        if position.margin_required > self.available_margin:
            logger.warning(
                f"Insufficient margin for {position.symbol}: "
                f"required={position.margin_required:.2f}, available={self.available_margin:.2f}"
            )
            return False

        # 直接使用传入的 cash_change，不重新计算
        self._cash += cash_change

        # 添加到持仓
        self._positions[position.position_id] = position

        logger.debug(
            f"Added position {position.position_id}: "
            f"{position.quantity} {position.symbol} @ {position.entry_price:.2f}, "
            f"cash_change={cash_change:.2f}"
        )

        return True

    def remove_position(
        self,
        position_id: str,
        cash_change: float,
        realized_pnl: float,
    ) -> bool:
        """移除持仓 (简化版本，Position 字段已由 PositionTracker 设置)

        这是 close_position 的新版本，供重构后的 PositionTracker 使用。
        Position 层负责计算 realized_pnl 和更新 position 字段，Account 层只负责：
        1. 更新现金 (直接使用传入的 cash_change，不重新计算)
        2. 更新累计已实现盈亏
        3. 移动持仓到 closed_positions

        Args:
            position_id: 持仓 ID
            cash_change: 现金变动 (已由 Trade 层计算)
            realized_pnl: 已实现盈亏 (已由 Position 层计算)

        Returns:
            是否成功移除持仓
        """
        if position_id not in self._positions:
            logger.warning(f"Position not found: {position_id}")
            return False

        position = self._positions[position_id]

        # 直接使用传入的 cash_change，不重新计算
        self._cash += cash_change

        # 更新累计已实现盈亏
        self._realized_pnl_cumulative += realized_pnl

        # 移动到已平仓列表
        self._closed_positions.append(position)
        del self._positions[position_id]

        logger.debug(
            f"Removed position {position_id}: "
            f"cash_change={cash_change:.2f}, realized_pnl={realized_pnl:.2f}"
        )

        return True

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

        if position.option_type == OptionType.PUT:
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
