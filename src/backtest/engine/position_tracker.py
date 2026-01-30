"""
Position Tracker - 持仓追踪器

负责回测过程中的持仓管理：
- 持仓状态追踪
- SimulatedPosition 到 PositionData 的转换
- 持仓 P&L 计算
- 与 MonitoringPipeline 的集成

Usage:
    tracker = PositionTracker(data_provider)

    # 开仓
    tracker.open_position(position, commission=0.65)

    # 获取 PositionData 列表用于监控
    position_data_list = tracker.get_position_data_for_monitoring()

    # 运行监控
    result = monitoring_pipeline.run(position_data_list)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Literal

from src.backtest.engine.account_simulator import (
    AccountSimulator,
    EquitySnapshot,
    SimulatedPosition,
)
from src.business.monitoring.models import PositionData
from src.business.trading.models.decision import AccountState
from src.data.providers.base import DataProvider
from src.engine.models.enums import StrategyType

logger = logging.getLogger(__name__)


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


@dataclass
class TradeRecord:
    """交易记录"""

    trade_id: str
    position_id: str
    symbol: str
    underlying: str
    option_type: Literal["call", "put"]
    strike: float
    expiration: date
    quantity: int
    price: float
    trade_date: date
    action: Literal["open", "close", "expire"]
    commission: float = 0.0
    pnl: float | None = None  # 仅平仓时有
    reason: str | None = None  # 平仓原因


class PositionTracker:
    """持仓追踪器

    整合 AccountSimulator，提供更高级的持仓管理和分析功能。

    主要职责：
    1. 持仓生命周期管理 (开仓/平仓/到期)
    2. 持仓数据转换 (SimulatedPosition -> PositionData)
    3. P&L 统计和分析
    4. 交易记录管理
    """

    def __init__(
        self,
        data_provider: DataProvider,
        initial_capital: float = 100_000.0,
        max_margin_utilization: float = 0.70,
    ) -> None:
        """初始化持仓追踪器

        Args:
            data_provider: 数据提供者 (用于获取 Greeks 等)
            initial_capital: 初始资金
            max_margin_utilization: 最大保证金使用率
        """
        self._data_provider = data_provider
        self._account = AccountSimulator(
            initial_capital=initial_capital,
            max_margin_utilization=max_margin_utilization,
        )

        # 交易记录
        self._trade_records: list[TradeRecord] = []
        self._trade_counter = 0

        # 当前日期
        self._current_date: date | None = None

    @property
    def account(self) -> AccountSimulator:
        """底层账户模拟器"""
        return self._account

    @property
    def positions(self) -> dict[str, SimulatedPosition]:
        """当前持仓"""
        return self._account.positions

    @property
    def position_count(self) -> int:
        """持仓数量"""
        return self._account.position_count

    @property
    def trade_records(self) -> list[TradeRecord]:
        """所有交易记录"""
        return self._trade_records

    def set_date(self, d: date) -> None:
        """设置当前日期"""
        self._current_date = d

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
        success = self._account.open_position(position, commission)

        if success:
            # 记录交易
            self._trade_counter += 1
            trade = TradeRecord(
                trade_id=f"T{self._trade_counter:06d}",
                position_id=position.position_id,
                symbol=position.symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=position.strike,
                expiration=position.expiration,
                quantity=position.quantity,
                price=position.entry_price,
                trade_date=position.entry_date,
                action="open",
                commission=commission * abs(position.quantity),
            )
            self._trade_records.append(trade)

            logger.info(
                f"Opened: {position.quantity} {position.symbol} "
                f"@ {position.entry_price:.2f}"
            )

        return success

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
            close_price: 平仓价格
            close_date: 平仓日期
            close_reason: 平仓原因
            commission: 手续费

        Returns:
            已实现盈亏
        """
        if position_id not in self._account.positions:
            return None

        position = self._account.positions[position_id]

        realized_pnl = self._account.close_position(
            position_id, close_price, close_date, close_reason, commission
        )

        if realized_pnl is not None:
            # 记录交易
            self._trade_counter += 1
            trade = TradeRecord(
                trade_id=f"T{self._trade_counter:06d}",
                position_id=position_id,
                symbol=position.symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=position.strike,
                expiration=position.expiration,
                quantity=-position.quantity,  # 平仓方向相反
                price=close_price,
                trade_date=close_date,
                action="close",
                commission=commission * abs(position.quantity),
                pnl=realized_pnl,
                reason=close_reason,
            )
            self._trade_records.append(trade)

            logger.info(
                f"Closed: {position_id} @ {close_price:.2f}, "
                f"PnL: {realized_pnl:.2f}, reason: {close_reason}"
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
        if position_id not in self._account.positions:
            return None

        position = self._account.positions[position_id]

        realized_pnl = self._account.expire_position(
            position_id, expire_date, final_underlying_price
        )

        if realized_pnl is not None:
            # 判断到期方式
            if position.option_type == "put":
                is_itm = final_underlying_price < position.strike
            else:
                is_itm = final_underlying_price > position.strike

            close_reason = "assigned" if is_itm else "expired_worthless"

            # 记录交易
            self._trade_counter += 1
            trade = TradeRecord(
                trade_id=f"T{self._trade_counter:06d}",
                position_id=position_id,
                symbol=position.symbol,
                underlying=position.underlying,
                option_type=position.option_type,
                strike=position.strike,
                expiration=position.expiration,
                quantity=-position.quantity,
                price=0.0 if not is_itm else abs(position.strike - final_underlying_price),
                trade_date=expire_date,
                action="expire",
                commission=0.0,
                pnl=realized_pnl,
                reason=close_reason,
            )
            self._trade_records.append(trade)

            logger.info(
                f"Expired: {position_id}, {close_reason}, "
                f"PnL: {realized_pnl:.2f}"
            )

        return realized_pnl

    def update_positions_from_market(self) -> None:
        """从市场数据更新所有持仓价格

        使用 data_provider 获取当前期权价格和标的价格。
        """
        for pos_id, position in self._account.positions.items():
            try:
                # 获取标的报价
                stock_quote = self._data_provider.get_stock_quote(position.underlying)
                if stock_quote:
                    underlying_price = stock_quote.close or stock_quote.last or position.strike
                else:
                    underlying_price = position.strike

                # 获取期权报价
                # 需要从 option chain 中找到对应的期权
                option_price = self._get_option_price(
                    underlying=position.underlying,
                    option_type=position.option_type,
                    strike=position.strike,
                    expiration=position.expiration,
                )

                if option_price is not None:
                    position.update_market_value(option_price, underlying_price)
                else:
                    # 如果找不到期权价格，使用内在价值估算
                    if position.option_type == "put":
                        intrinsic = max(0, position.strike - underlying_price)
                    else:
                        intrinsic = max(0, underlying_price - position.strike)
                    position.update_market_value(intrinsic, underlying_price)

            except Exception as e:
                logger.warning(f"Failed to update position {pos_id}: {e}")

    def _get_option_price(
        self,
        underlying: str,
        option_type: Literal["call", "put"],
        strike: float,
        expiration: date,
    ) -> float | None:
        """从期权链获取期权价格

        Args:
            underlying: 标的代码
            option_type: 期权类型
            strike: 行权价
            expiration: 到期日

        Returns:
            期权价格 (close price)
        """
        try:
            chain = self._data_provider.get_option_chain(
                underlying=underlying,
                expiry_start=expiration,
                expiry_end=expiration,
            )

            if chain is None:
                return None

            contracts = chain.puts if option_type == "put" else chain.calls

            for contract in contracts:
                if (
                    contract.strike == strike
                    and contract.expiry.date() == expiration
                ):
                    return contract.close if hasattr(contract, 'close') else contract.last

            return None

        except Exception as e:
            logger.warning(f"Failed to get option price: {e}")
            return None

    def get_position_data_for_monitoring(
        self,
        as_of_date: date | None = None,
    ) -> list[PositionData]:
        """获取用于监控的持仓数据列表

        将 SimulatedPosition 转换为 PositionData，填充 Greeks 等信息。

        Args:
            as_of_date: 日期 (用于计算 DTE)

        Returns:
            PositionData 列表
        """
        position_data_list: list[PositionData] = []
        ref_date = as_of_date or self._current_date or date.today()

        for pos_id, position in self._account.positions.items():
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
        """将 SimulatedPosition 转换为 PositionData

        Args:
            position: 模拟持仓
            ref_date: 参考日期

        Returns:
            PositionData
        """
        # 计算 DTE
        dte = (position.expiration - ref_date).days

        # 获取 Greeks (如果可用)
        delta, gamma, theta, vega, iv = self._get_greeks(position)

        # 计算 moneyness 和 OTM%
        underlying_price = position.underlying_price or position.strike
        moneyness = (underlying_price - position.strike) / position.strike

        if position.option_type == "put":
            # Put: OTM% = (S - K) / S (正数=OTM)
            otm_pct = (underlying_price - position.strike) / underlying_price if underlying_price > 0 else 0.0
        else:
            # Call: OTM% = (K - S) / S (正数=OTM)
            otm_pct = (position.strike - underlying_price) / underlying_price if underlying_price > 0 else 0.0

        # 计算盈亏百分比
        entry_value = abs(position.quantity * position.entry_price * position.lot_size)
        unrealized_pnl_pct = (
            position.unrealized_pnl / entry_value if entry_value > 0 else 0.0
        )

        # 构建期权 symbol (用于显示)
        expiry_str = position.expiration.strftime("%Y%m%d")
        option_symbol = (
            f"{position.underlying} "
            f"{expiry_str} "
            f"{position.strike:.1f}{position.option_type[0].upper()}"
        )

        # 推断策略类型
        if position.option_type == "put" and position.is_short:
            strategy_type = StrategyType.SHORT_PUT
        elif position.option_type == "call" and position.is_short:
            strategy_type = StrategyType.SHORT_CALL
        elif position.option_type == "put" and not position.is_short:
            strategy_type = StrategyType.LONG_PUT
        else:
            strategy_type = StrategyType.LONG_CALL

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
            # 期权专用字段
            underlying=position.underlying,
            option_type=position.option_type,
            strike=position.strike,
            expiry=expiry_str,
            dte=dte,
            contract_multiplier=position.lot_size,
            moneyness=moneyness,
            otm_pct=otm_pct,
            # Greeks
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            iv=iv,
            # 标的价格
            underlying_price=position.underlying_price,
            # 策略信息
            strategy_type=strategy_type,
            # 保证金
            margin=position.margin_required,
        )

    def _get_greeks(
        self,
        position: SimulatedPosition,
    ) -> tuple[float | None, float | None, float | None, float | None, float | None]:
        """获取持仓的 Greeks

        尝试从 DataProvider 获取，如果失败则返回 None。

        Args:
            position: 持仓

        Returns:
            (delta, gamma, theta, vega, iv)
        """
        try:
            chain = self._data_provider.get_option_chain(
                underlying=position.underlying,
                expiry_start=position.expiration,
                expiry_end=position.expiration,
            )

            if chain is None:
                return None, None, None, None, None

            contracts = chain.puts if position.option_type == "put" else chain.calls

            for contract in contracts:
                if (
                    contract.strike == position.strike
                    and contract.expiry.date() == position.expiration
                ):
                    greeks = contract.greeks if hasattr(contract, 'greeks') else None
                    if greeks:
                        # 调整 delta 方向 (空头取反)
                        raw_delta = greeks.delta if greeks.delta is not None else None
                        position_delta = raw_delta * position.quantity if raw_delta else None

                        # 其他 Greeks 也要乘以数量
                        position_gamma = greeks.gamma * abs(position.quantity) if greeks.gamma else None
                        position_theta = greeks.theta * position.quantity if greeks.theta else None
                        position_vega = greeks.vega * abs(position.quantity) if greeks.vega else None

                        return (
                            position_delta,
                            position_gamma,
                            position_theta,
                            position_vega,
                            greeks.iv if hasattr(greeks, 'iv') else None,
                        )

            return None, None, None, None, None

        except Exception as e:
            logger.debug(f"Failed to get Greeks for {position.symbol}: {e}")
            return None, None, None, None, None

    def get_position_pnl(self, position_id: str) -> PositionPnL | None:
        """获取单个持仓的盈亏信息

        Args:
            position_id: 持仓 ID

        Returns:
            PositionPnL
        """
        # 检查活跃持仓
        if position_id in self._account.positions:
            pos = self._account.positions[position_id]
            ref_date = self._current_date or date.today()

            entry_value = abs(pos.quantity * pos.entry_price * pos.lot_size)
            unrealized_pnl_pct = pos.unrealized_pnl / entry_value if entry_value > 0 else 0.0

            return PositionPnL(
                position_id=pos.position_id,
                symbol=pos.symbol,
                underlying=pos.underlying,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                current_price=pos.current_price,
                quantity=pos.quantity,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                commission_paid=pos.commission_paid,
                dte=(pos.expiration - ref_date).days,
                days_held=(ref_date - pos.entry_date).days,
                is_closed=False,
            )

        # 检查已平仓持仓
        for pos in self._account.closed_positions:
            if pos.position_id == position_id:
                entry_value = abs(pos.quantity * pos.entry_price * pos.lot_size)
                realized_pnl_pct = (
                    pos.realized_pnl / entry_value if entry_value > 0 and pos.realized_pnl else 0.0
                )

                return PositionPnL(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    underlying=pos.underlying,
                    entry_date=pos.entry_date,
                    entry_price=pos.entry_price,
                    current_price=pos.close_price or 0.0,
                    quantity=pos.quantity,
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    commission_paid=pos.commission_paid,
                    dte=0,
                    days_held=(pos.close_date - pos.entry_date).days if pos.close_date else 0,
                    is_closed=True,
                    close_date=pos.close_date,
                    close_price=pos.close_price,
                    close_reason=pos.close_reason,
                    realized_pnl=pos.realized_pnl,
                    realized_pnl_pct=realized_pnl_pct,
                )

        return None

    def get_positions_by_underlying(self) -> dict[str, list[SimulatedPosition]]:
        """按标的分组持仓

        Returns:
            {underlying: [positions]}
        """
        grouped: dict[str, list[SimulatedPosition]] = {}
        for pos in self._account.positions.values():
            if pos.underlying not in grouped:
                grouped[pos.underlying] = []
            grouped[pos.underlying].append(pos)
        return grouped

    def get_expiring_positions(self, days_ahead: int = 7) -> list[SimulatedPosition]:
        """获取即将到期的持仓

        Args:
            days_ahead: 未来多少天内到期

        Returns:
            持仓列表
        """
        ref_date = self._current_date or date.today()
        cutoff = ref_date.toordinal() + days_ahead

        return [
            pos
            for pos in self._account.positions.values()
            if pos.expiration.toordinal() <= cutoff
        ]

    def check_expirations(self) -> list[SimulatedPosition]:
        """检查当天到期的持仓

        Returns:
            到期的持仓列表
        """
        ref_date = self._current_date or date.today()
        return [
            pos
            for pos in self._account.positions.values()
            if pos.expiration == ref_date
        ]

    def get_account_state(self) -> AccountState:
        """获取账户状态"""
        return self._account.get_account_state()

    def take_snapshot(self, snapshot_date: date) -> EquitySnapshot:
        """记录权益快照"""
        return self._account.take_snapshot(snapshot_date)

    def get_trade_summary(self) -> dict:
        """获取交易摘要

        Returns:
            交易统计信息
        """
        open_trades = [t for t in self._trade_records if t.action == "open"]
        close_trades = [t for t in self._trade_records if t.action in ("close", "expire")]

        # 统计盈亏
        winning_trades = [t for t in close_trades if t.pnl and t.pnl > 0]
        losing_trades = [t for t in close_trades if t.pnl and t.pnl < 0]

        total_pnl = sum(t.pnl or 0 for t in close_trades)
        total_commission = sum(t.commission for t in self._trade_records)

        win_rate = len(winning_trades) / len(close_trades) if close_trades else 0.0

        return {
            "total_trades": len(self._trade_records),
            "open_trades": len(open_trades),
            "close_trades": len(close_trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_commission": total_commission,
            "net_pnl": total_pnl - total_commission,
        }

    @property
    def nlv(self) -> float:
        """当前净清算价值"""
        return self._account.nlv

    @property
    def cash(self) -> float:
        """当前现金"""
        return self._account.cash

    @property
    def realized_pnl(self) -> float:
        """累计已实现盈亏"""
        return self._account.realized_pnl

    @property
    def unrealized_pnl(self) -> float:
        """当前未实现盈亏"""
        return self._account.unrealized_pnl

    @property
    def equity_snapshots(self) -> list[EquitySnapshot]:
        """权益快照列表"""
        return self._account.equity_snapshots

    def reset(self) -> None:
        """重置追踪器"""
        self._account.reset()
        self._trade_records.clear()
        self._trade_counter = 0
        self._current_date = None
