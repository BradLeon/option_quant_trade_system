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

    # 添加持仓
    simulator.add_position(position, cash_change=200.0)

    # 添加股票持仓
    simulator.add_stock_position(symbol="AAPL", quantity=100, entry_price=100.0,
                                trade_date=date(2024, 3, 1), cash_change=-10000.0)

    # 移除持仓
    pnl = simulator.remove_position(position_id, cash_change=-150.0, realized_pnl=50.0)

    # 获取账户状态
    state = simulator.get_account_state()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.business.trading.models.decision import AccountState
from src.data.models.account import AssetType
from src.data.models.margin import calc_reg_t_margin_short_put, calc_reg_t_margin_short_call
from src.data.models.option import OptionType

logger = logging.getLogger(__name__)


@dataclass
class SimulatedPosition:
    """模拟持仓

    记录单个持仓（期权或股票）的所有信息。
    """

    # 必填字段
    position_id: str
    symbol: str  # 期权合约标识或股票代码
    asset_type: AssetType  # STOCK | OPTION
    quantity: int  # 正数=多头, 负数=空头
    entry_price: float  # 开仓价格
    entry_date: date

    # 可选字段（期权专用）
    underlying: str | None = None  # 标的代码（期权专用）
    option_type: OptionType | None = None  # 期权类型 (CALL/PUT)，股票为 None
    strike: float | None = None  # 行权价，股票为 None
    expiration: date | None = None  # 到期日，股票为 None
    lot_size: int = 100  # 期权：每张合约对应股数（默认100），股票：1

    # 当前市值相关
    current_price: float = 0.0  # 当前价格（期权价格或股票价格）
    underlying_price: float = 0.0  # 当前标的价格（期权专用）
    market_value: float = 0.0  # 当前市值 (quantity * current_price * lot_size)
    margin_required: float = 0.0  # 保证金需求（股票为 0）

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
    def is_short_option(self) -> bool:
        """是否空头期权（需要计算保证金）"""
        return self.quantity < 0 and self.asset_type == AssetType.OPTION

    @property
    def is_stock(self) -> bool:
        """是否股票持仓"""
        return self.asset_type == AssetType.STOCK

    @property
    def is_option(self) -> bool:
        """是否期权持仓"""
        return self.asset_type == AssetType.OPTION

    @property
    def notional_value(self) -> float:
        """名义价值 = |quantity| * strike * lot_size（期权专用）"""
        if self.is_stock or self.strike is None:
            return 0.0  # 股票没有名义价值概念
        return abs(self.quantity) * self.strike * self.lot_size

    def update_market_value(
        self,
        current_price: float,
        underlying_price: float = 0.0,
    ) -> None:
        """更新市值

        Args:
            current_price: 当前价格（期权价格 per share 或股票价格 per share）
            underlying_price: 当前标的价格（期权专用，股票不需要）
        """
        self.current_price = current_price
        if self.is_option:
            self.underlying_price = underlying_price

        # 市值 = quantity * price * lot_size
        # 多头: 正值, 空头: 负值
        self.market_value = self.quantity * current_price * self.lot_size

        # 计算未实现盈亏
        entry_value = self.quantity * self.entry_price * self.lot_size
        self.unrealized_pnl = self.market_value - entry_value

        # 计算保证金（仅期权空头需要，股票为 0）
        if self.is_stock:
            # 股票不占用保证金
            self.margin_required = 0.0
        elif self.is_short_option:
            # 只对期权空头计算保证金
            self._calculate_margin(underlying_price)
        else:
            self.margin_required = 0.0

    def _calculate_margin(self, underlying_price: float) -> None:
        """计算保证金需求 (Reg T) - 仅期权持仓调用"""
        # 确保只在期权持仓时调用
        if self.strike is None or self.option_type is None:
            self.margin_required = 0.0
            return

        if self.option_type == OptionType.PUT:
            margin_per_share = calc_reg_t_margin_short_put(
                underlying_price=underlying_price,
                strike=self.strike,
                premium=self.current_price,
            )
        else:  # OptionType.CALL
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

    持仓市值更新:
    - 由 PositionManager 负责，通过 update_position_market_data() 直接更新 SimulatedPosition
    - BacktestExecutor 每日调用 position_manager.update_all_positions_market_data()

    Usage:
        simulator = AccountSimulator(initial_capital=100_000)

        # 添加期权持仓 (由 PositionManager 创建)
        pos = SimulatedPosition(
            position_id="001",
            symbol="AAPL 20240315 150P",
            asset_type=AssetType.OPTION,
            underlying="AAPL",
            option_type=OptionType.PUT,
            strike=150,
            expiration=date(2024, 3, 15),
            quantity=-1,  # 负数=卖出
            entry_price=3.50,
            entry_date=date(2024, 2, 1),
            lot_size=100,
        )
        simulator.add_position(pos, cash_change=350.0)

        # 添加股票持仓
        simulator.add_stock_position(
            symbol="AAPL",
            quantity=100,
            entry_price=100.0,
            trade_date=date(2024, 3, 1),
            cash_change=-10000.0,
        )

        # 移除持仓
        pnl = simulator.remove_position("001", cash_change=-150.0, realized_pnl=50.0)

        # 获取账户状态
        state = simulator.get_account_state()
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
        1. 检查保证金（期权持仓）
        2. 更新现金 (直接使用传入的 cash_change，不重新计算)
        3. 存储持仓

        Args:
            position: 持仓信息 (字段已由 PositionTracker 填充)
            cash_change: 现金变动 (已由 Trade 层计算，即 TradeExecution.net_amount)

        Returns:
            是否成功添加持仓
        """
        # 股票不占用保证金，跳过保证金检查
        if position.is_stock:
            # 直接更新现金和持仓
            self._cash += cash_change
            self._positions[position.position_id] = position
            logger.debug(
                f"Added stock position {position.position_id}: "
                f"{position.quantity} {position.symbol} @ {position.entry_price:.2f}, "
                f"cash_change={cash_change:.2f}"
            )
            return True

        # 检查是否有足够的保证金（仅期权持仓）
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

    def add_stock_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        trade_date: date,
        cash_change: float = 0.0,  # 默认现金变动为 0
    ) -> str:
        """添加股票持仓

        Args:
            symbol: 股票代码
            quantity: 数量（正数=多头，负数=空头）
            entry_price: 开仓价格
            trade_date: 开仓日期
            cash_change: 现金变动（由调用方传入）

        Returns:
            持仓 ID（格式：{symbol}-STOCK）

        Raises:
            ValueError: 现金不足时抛出异常
        """
        position_id = f"{symbol}-STOCK"

        # 检查现金是否足够（买入时 cash_change < 0，允许融资买入或行权强制买入，只记录警告）
        if cash_change < 0 and abs(cash_change) > self._cash:
            required = abs(cash_change)
            available = self._cash
            logger.warning(
                f"Margin utilized (Negative Cash): buying {abs(quantity)} {symbol} @ ${entry_price:.2f}. "
                f"required=${required:.2f}, available=${available:.2f}"
            )

        # 如果已有同 symbol 的股票持仓，累加数量并重算加权平均成本
        if position_id in self._positions:
            existing = self._positions[position_id]
            old_qty = existing.quantity
            total_qty = old_qty + quantity
            if total_qty != 0:
                avg_price = (old_qty * existing.entry_price
                             + quantity * entry_price) / total_qty
            else:
                avg_price = entry_price
            existing.quantity = total_qty
            existing.entry_price = avg_price
            existing.current_price = entry_price
            existing.market_value = total_qty * entry_price
            existing.unrealized_pnl = total_qty * (entry_price - avg_price)
            self._cash += cash_change

            logger.debug(
                f"Accumulated stock position {position_id}: "
                f"{old_qty} + {quantity} = {total_qty} {symbol}, "
                f"avg_price=${avg_price:.2f}, cash_change=${cash_change:.2f}"
            )
            return position_id

        # 创建新股票持仓
        position = SimulatedPosition(
            position_id=position_id,
            symbol=symbol,
            asset_type=AssetType.STOCK,
            quantity=quantity,
            entry_price=entry_price,
            entry_date=trade_date,
            lot_size=1,  # 股票 lot_size = 1
            margin_required=0.0,  # 股票不占用保证金
            current_price=entry_price,
            market_value=quantity * entry_price,
            unrealized_pnl=0.0,
        )

        # 添加持仓
        self._positions[position_id] = position
        # 更新现金
        self._cash += cash_change

        logger.debug(
            f"Added stock position {position_id}: "
            f"{quantity} {symbol} @ ${entry_price:.2f}, cash_change=${cash_change:.2f}"
        )

        return position_id

    def update_stock_position(
        self,
        position_id: str,
        quantity_change: int,
        new_price: float,
        cash_change: float,
    ) -> None:
        """更新现有股票持仓的数量和市值

        Args:
            position_id: 持仓 ID（格式：{symbol}-STOCK）
            quantity_change: 数量变化（正数=增加，负数=减少）
            new_price: 新价格（用于更新市值）
            cash_change: 现金变动
        """
        if position_id not in self._positions:
            logger.warning(f"Stock position not found: {position_id}")
            return

        position = self._positions[position_id]

        # 更新数量
        position.quantity += quantity_change
        position.current_price = new_price
        position.market_value = position.quantity * new_price

        # 更新未实现盈亏
        entry_value = position.quantity * position.entry_price
        position.unrealized_pnl = position.market_value - entry_value

        # 更新现金
        self._cash += cash_change

        # 如果数量变为 0，移除持仓
        if position.quantity == 0:
            # 移动到已平仓列表
            self._closed_positions.append(position)
            del self._positions[position_id]
            logger.debug(f"Stock position {position_id} closed (quantity=0)")
        else:
            logger.debug(
                f"Updated stock position {position_id}: "
                f"quantity_change={quantity_change}, new_price=${new_price:.2f}, "
                f"cash_change=${cash_change:.2f}"
            )

    def get_stock_position(self, symbol: str) -> SimulatedPosition | None:
        """获取股票持仓

        Args:
            symbol: 股票代码

        Returns:
            股票持仓对象，不存在则返回 None
        """
        position_id = f"{symbol}-STOCK"
        return self._positions.get(position_id)

    def get_stock_quantity(self, symbol: str) -> int:
        """获取股票持仓数量

        Args:
            symbol: 股票代码

        Returns:
            持仓数量（0 表示无持仓）
        """
        position = self.get_stock_position(symbol)
        return position.quantity if position else 0

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
        # 只计算期权持仓的保证金，股票不占用保证金
        margin_used = sum(pos.margin_required for pos in self._positions.values() if pos.is_option)
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
            # 股票使用 symbol，期权使用 underlying
            underlying = pos.underlying if pos.underlying else pos.symbol
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
            option_position_count=sum(1 for pos in self._positions.values() if pos.is_option),
            stock_position_count=sum(1 for pos in self._positions.values() if pos.is_stock),
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
        """已用保证金（仅期权持仓，股票不占用保证金）"""
        return sum(pos.margin_required for pos in self._positions.values() if pos.is_option)

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

        # 股票不占用保证金
        if position.is_stock:
            return 0.0

        # 只对期权持仓计算保证金
        if position.strike is None or position.option_type is None:
            return 0.0

        # 使用开仓价格和当前标的价格估算
        underlying_price = position.underlying_price or position.strike

        if position.option_type == OptionType.PUT:
            margin_per_share = calc_reg_t_margin_short_put(
                underlying_price=underlying_price,
                strike=position.strike,
                premium=position.entry_price,
            )
        else:  # OptionType.CALL
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
