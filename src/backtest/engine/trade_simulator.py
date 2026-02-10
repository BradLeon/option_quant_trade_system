"""
Trade Simulator - 交易模拟器

模拟回测中的交易执行，包括:
- 滑点模型 (可配置百分比)
- 手续费模型 (每张合约)
- 交易执行记录生成

Usage:
    simulator = TradeSimulator(
        slippage_pct=0.001,
        commission_per_contract=0.65,
    )

    # 模拟开仓执行
    execution = simulator.execute_open(
        symbol="AAPL 20240315 150P",
        underlying="AAPL",
        option_type=OptionType.PUT,
        strike=150.0,
        expiration=date(2024, 3, 15),
        quantity=-1,  # 卖出
        mid_price=3.50,
        trade_date=date(2024, 2, 1),
    )

    print(f"Executed at {execution.fill_price} with slippage {execution.slippage}")
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from uuid import uuid4

from src.data.models.option import OptionType

logger = logging.getLogger(__name__)


class CloseReasonType(str, Enum):
    """结构化平仓原因类型"""

    EXPIRED_WORTHLESS = "expired_worthless"  # OTM到期
    EXPIRED_ITM = "expired_itm"  # ITM到期/被指派
    PROFIT_TARGET = "profit_target"  # 止盈
    STOP_LOSS = "stop_loss"  # 止损（通用）
    STOP_LOSS_DELTA = "stop_loss_delta"  # Delta止损
    STOP_LOSS_OTM = "stop_loss_otm"  # OTM止损
    TIME_EXIT = "time_exit"  # DTE/时间退出
    ROLL = "roll"  # 展期平仓
    MANUAL_CLOSE = "manual_close"  # 手动/其他平仓
    UNKNOWN = "unknown"  # 未知


class OrderSide(str, Enum):
    """订单方向"""

    BUY = "buy"
    SELL = "sell"


class ExecutionStatus(str, Enum):
    """执行状态"""

    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"


@dataclass
class TradeRecord:
    """交易记录

    记录每笔交易的关键信息，在 Trade 层创建。
    """

    trade_id: str
    execution_id: str  # 关联到 TradeExecution
    symbol: str
    underlying: str
    option_type: OptionType
    strike: float
    expiration: date
    trade_date: date
    action: str  # "open", "close", "expire"
    quantity: int  # 有符号数量
    price: float  # 成交价
    commission: float
    gross_amount: float  # 成交金额（不含费用）
    net_amount: float  # 净金额（含费用）
    pnl: float | None = None  # 已实现盈亏（仅平仓/到期时）
    reason: str | None = None
    close_reason_type: CloseReasonType | None = None  # 结构化平仓原因
    position_id: str | None = None  # 可选，由 Position 层填充


@dataclass
class TradeExecution:
    """交易执行记录

    记录单笔交易的所有执行细节。
    """

    # 基本信息
    execution_id: str
    trade_date: date
    timestamp: datetime = field(default_factory=datetime.now)

    # 合约信息
    symbol: str = ""
    underlying: str = ""
    option_type: OptionType = OptionType.PUT  # 期权类型 (CALL/PUT)
    strike: float = 0.0
    expiration: date = field(default_factory=date.today)

    # 订单信息
    side: OrderSide = OrderSide.SELL  # 仅用于显示/日志
    quantity: int = 0  # 有符号: 负数=卖出, 正数=买入

    # 价格信息
    order_price: float = 0.0  # 下单价格 (mid price)
    fill_price: float = 0.0  # 成交价格 (含滑点)
    slippage: float = 0.0  # 滑点金额
    slippage_pct: float = 0.0  # 滑点百分比

    # 费用
    commission: float = 0.0  # 手续费

    # 金额
    gross_amount: float = 0.0  # 成交金额 (不含费用)
    net_amount: float = 0.0  # 净金额 (含费用)

    # 状态
    status: ExecutionStatus = ExecutionStatus.FILLED

    # 额外信息
    lot_size: int = 100
    reason: str = ""  # 交易原因

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "trade_date": self.trade_date.isoformat(),
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "underlying": self.underlying,
            "option_type": self.option_type.value,  # OptionType enum -> str
            "strike": self.strike,
            "expiration": self.expiration.isoformat(),
            "side": self.side.value,
            "quantity": self.quantity,
            "order_price": self.order_price,
            "fill_price": self.fill_price,
            "slippage": self.slippage,
            "slippage_pct": self.slippage_pct,
            "commission": self.commission,
            "gross_amount": self.gross_amount,
            "net_amount": self.net_amount,
            "status": self.status.value,
            "lot_size": self.lot_size,
            "reason": self.reason,
        }


@dataclass
class SlippageModel:
    """滑点模型

    支持多种滑点计算方式：
    - 固定百分比
    - 基于波动率
    - 基于期权价格的分层滑点
    """

    # 基础滑点百分比
    base_pct: float = 0.001  # 0.1%

    # 是否根据期权价格调整
    # 低价期权 (<$1) 通常有更大的 bid-ask spread
    adjust_for_price: bool = True

    # 价格分层滑点
    # 期权价格 < $0.50: 使用 low_price_pct
    # 期权价格 $0.50-$5: 使用 base_pct
    # 期权价格 > $5: 使用 high_price_pct
    low_price_pct: float = 0.05  # 5% for cheap options
    high_price_pct: float = 0.002  # 0.2% for expensive options

    def calculate(self, mid_price: float, side: OrderSide) -> tuple[float, float]:
        """计算滑点

        Args:
            mid_price: 中间价
            side: 买卖方向

        Returns:
            (fill_price, slippage_amount)
        """
        if mid_price <= 0:
            return mid_price, 0.0

        # 确定滑点百分比
        if self.adjust_for_price:
            if mid_price < 0.50:
                pct = self.low_price_pct
            elif mid_price > 5.0:
                pct = self.high_price_pct
            else:
                pct = self.base_pct
        else:
            pct = self.base_pct

        # 计算滑点金额
        slippage = mid_price * pct

        # 应用滑点 (买入加价，卖出降价)
        if side == OrderSide.BUY:
            fill_price = mid_price + slippage
        else:
            fill_price = mid_price - slippage

        # 确保价格非负
        fill_price = max(0, fill_price)

        return fill_price, slippage


@dataclass
class CommissionModel:
    """手续费模型 - 基于 IBKR 真实费率

    IBKR 费率结构:
    - Option: 每张 $0.65，每笔最低 $1.00
    - Stock: 每股 $0.005，每笔最低 $1.00

    支持两种计费方式：
    - 期权：按合约数量计费
    - 股票：按股数计费 (covered call 被 assign 时)
    """

    # ===== 期权费用 =====
    option_per_contract: float = 0.65  # 每张合约费用
    option_min_per_order: float = 1.00  # 每笔最低费用

    # ===== 股票费用 =====
    stock_per_share: float = 0.005  # 每股费用
    stock_min_per_order: float = 1.00  # 每笔最低费用

    # ===== 通用设置 =====
    # 最高手续费 (0 = 无上限)
    max_commission: float = 0.0

    def calculate_option(self, contracts: int) -> float:
        """计算期权手续费

        Args:
            contracts: 合约数量 (绝对值)

        Returns:
            手续费金额
        """
        qty = abs(contracts)
        if qty == 0:
            return 0.0

        commission = qty * self.option_per_contract

        # 应用每笔最低费用
        commission = max(commission, self.option_min_per_order)

        # 应用最高手续费
        if self.max_commission > 0:
            commission = min(commission, self.max_commission)

        return commission

    def calculate_stock(self, shares: int) -> float:
        """计算股票手续费

        Args:
            shares: 股数 (绝对值)

        Returns:
            手续费金额
        """
        qty = abs(shares)
        if qty == 0:
            return 0.0

        commission = qty * self.stock_per_share

        # 应用每笔最低费用
        commission = max(commission, self.stock_min_per_order)

        # 应用最高手续费
        if self.max_commission > 0:
            commission = min(commission, self.max_commission)

        return commission

    @classmethod
    def ibkr_tiered(cls) -> "CommissionModel":
        """创建 IBKR Tiered 定价模型

        Returns:
            IBKR 标准费率的 CommissionModel
        """
        return cls(
            option_per_contract=0.65,
            option_min_per_order=1.00,
            stock_per_share=0.005,
            stock_min_per_order=1.00,
        )

    @classmethod
    def zero_commission(cls) -> "CommissionModel":
        """创建零佣金模型 (用于测试)

        Returns:
            零佣金的 CommissionModel
        """
        return cls(
            option_per_contract=0.0,
            option_min_per_order=0.0,
            stock_per_share=0.0,
            stock_min_per_order=0.0,
        )


class TradeSimulator:
    """交易模拟器

    模拟交易执行过程，包括滑点和手续费计算。

    Usage:
        simulator = TradeSimulator()

        # 执行开仓
        execution = simulator.execute_open(
            symbol="AAPL 20240315 150P",
            underlying="AAPL",
            option_type=OptionType.PUT,
            strike=150.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            mid_price=3.50,
            trade_date=date(2024, 2, 1),
        )

        # 执行平仓
        close_execution = simulator.execute_close(
            symbol="AAPL 20240315 150P",
            underlying="AAPL",
            option_type=OptionType.PUT,
            strike=150.0,
            expiration=date(2024, 3, 15),
            quantity=1,  # 买回
            mid_price=1.00,
            trade_date=date(2024, 3, 1),
        )
    """

    def __init__(
        self,
        slippage_pct: float = 0.001,
        commission_per_contract: float = 0.65,
        slippage_model: SlippageModel | None = None,
        commission_model: CommissionModel | None = None,
        lot_size: int = 100,
    ) -> None:
        """初始化交易模拟器

        Args:
            slippage_pct: 滑点百分比 (如果未提供 slippage_model)
            commission_per_contract: 每张合约手续费 (如果未提供 commission_model)
            slippage_model: 自定义滑点模型
            commission_model: 自定义手续费模型
            lot_size: 每张合约对应股数 (默认 100)
        """
        self._slippage_model = slippage_model or SlippageModel(base_pct=slippage_pct)
        self._commission_model = commission_model or CommissionModel(option_per_contract=commission_per_contract)
        self._lot_size = lot_size

        # 执行记录
        self._executions: list[TradeExecution] = []
        self._execution_counter = 0

        # 交易记录 (Trade 层职责)
        self._trade_records: list[TradeRecord] = []
        self._trade_counter = 0

    @property
    def executions(self) -> list[TradeExecution]:
        """所有执行记录"""
        return self._executions

    @property
    def trade_records(self) -> list[TradeRecord]:
        """所有交易记录"""
        return self._trade_records

    @property
    def slippage_model(self) -> SlippageModel:
        """滑点模型"""
        return self._slippage_model

    @property
    def commission_model(self) -> CommissionModel:
        """手续费模型"""
        return self._commission_model

    def execute_open(
        self,
        symbol: str,
        underlying: str,
        option_type: OptionType,
        strike: float,
        expiration: date,
        quantity: int,
        mid_price: float,
        trade_date: date,
        reason: str = "screening_signal",
        action: str = "open",  # 交易类型: open, close
        lot_size: int | None = None,  # 每张合约对应股数，None 则使用默认值
    ) -> TradeExecution:
        """执行开仓

        Args:
            symbol: 期权合约代码
            underlying: 标的代码
            option_type: 期权类型 (OptionType.PUT/CALL)
            strike: 行权价
            expiration: 到期日
            quantity: 数量 (正数=买入, 负数=卖出)
            mid_price: 中间价
            trade_date: 交易日期
            reason: 交易原因
            action: 交易类型 (open/close)
            lot_size: 每张合约对应股数 (可选，默认使用模拟器配置)

        Returns:
            TradeExecution
        """
        side = OrderSide.BUY if quantity > 0 else OrderSide.SELL

        # 使用传入的 lot_size 或默认值
        effective_lot_size = lot_size if lot_size is not None else self._lot_size

        # 计算滑点
        fill_price, slippage = self._slippage_model.calculate(mid_price, side)
        slippage_pct = slippage / mid_price if mid_price > 0 else 0.0

        # 计算手续费 (按合约张数，取绝对值)
        commission = self._commission_model.calculate_option(abs(quantity))

        # 计算金额
        # gross_amount = -quantity * fill_price * lot_size
        # 卖出 (qty<0): -(-1) * price * 100 = +price*100 (收取权利金)
        # 买入 (qty>0): -(+1) * price * 100 = -price*100 (支付权利金)
        gross_amount = -quantity * fill_price * effective_lot_size

        # 净金额 = 成交金额 - 手续费
        net_amount = gross_amount - commission

        # 生成执行记录
        self._execution_counter += 1
        execution = TradeExecution(
            execution_id=f"E{self._execution_counter:08d}",
            trade_date=trade_date,
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            side=side,
            quantity=quantity,  # 有符号: 负数=卖出, 正数=买入
            order_price=mid_price,
            fill_price=fill_price,
            slippage=slippage,
            slippage_pct=slippage_pct,
            commission=commission,
            gross_amount=gross_amount,
            net_amount=net_amount,
            status=ExecutionStatus.FILLED,
            lot_size=effective_lot_size,
            reason=reason,
        )

        self._executions.append(execution)

        # 创建交易记录 (Trade 层职责)
        self._trade_counter += 1
        trade_record = TradeRecord(
            trade_id=f"T{self._trade_counter:06d}",
            execution_id=execution.execution_id,
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            trade_date=trade_date,
            action=action,
            quantity=quantity,  # 有符号
            price=fill_price,
            commission=commission,
            gross_amount=gross_amount,
            net_amount=net_amount,
            reason=reason,
            close_reason_type=self._infer_close_reason_type(reason, action),
        )
        self._trade_records.append(trade_record)

        logger.debug(
            f"Executed {action.upper()}: {side.value} {abs(quantity)} {symbol} "
            f"@ {fill_price:.4f} (mid={mid_price:.4f}, slip={slippage:.4f}), "
            f"commission={commission:.2f}"
        )

        return execution

    def execute_close(
        self,
        symbol: str,
        underlying: str,
        option_type: OptionType,
        strike: float,
        expiration: date,
        quantity: int,
        mid_price: float,
        trade_date: date,
        reason: str = "take_profit",
        lot_size: int | None = None,
    ) -> TradeExecution:
        """执行平仓

        Args:
            symbol: 期权合约代码
            underlying: 标的代码
            option_type: 期权类型 (OptionType.PUT/CALL)
            strike: 行权价
            expiration: 到期日
            quantity: 数量 (与开仓相反方向)
            mid_price: 中间价
            trade_date: 交易日期
            reason: 平仓原因
            lot_size: 每张合约对应股数 (可选，默认使用模拟器配置)

        Returns:
            TradeExecution
        """
        # 平仓与开仓使用相同逻辑，但 action 为 "close"
        return self.execute_open(
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            quantity=quantity,
            mid_price=mid_price,
            trade_date=trade_date,
            reason=reason,
            action="close",
            lot_size=lot_size,
        )

    def execute_expire(
        self,
        symbol: str,
        underlying: str,
        option_type: OptionType,
        strike: float,
        expiration: date,
        quantity: int,
        final_underlying_price: float,
        trade_date: date,
        lot_size: int | None = None,
    ) -> TradeExecution:
        """执行到期

        到期时无滑点和手续费。

        Args:
            symbol: 期权合约代码
            underlying: 标的代码
            option_type: 期权类型 (OptionType.PUT/CALL)
            strike: 行权价
            expiration: 到期日
            quantity: 数量
            final_underlying_price: 到期时标的价格
            trade_date: 到期日期
            lot_size: 每张合约对应股数 (可选，默认使用模拟器配置)

        Returns:
            TradeExecution
        """
        # 使用传入的 lot_size 或默认值
        effective_lot_size = lot_size if lot_size is not None else self._lot_size

        # 判断是否 ITM
        if option_type == OptionType.PUT:
            is_itm = final_underlying_price < strike
            intrinsic_value = max(0, strike - final_underlying_price)
        else:
            is_itm = final_underlying_price > strike
            intrinsic_value = max(0, final_underlying_price - strike)

        side = OrderSide.BUY if quantity > 0 else OrderSide.SELL

        # 到期时的"价格"是内在价值
        fill_price = intrinsic_value

        # 计算金额
        gross_amount = -quantity * fill_price * effective_lot_size

        # 计算手续费 (根据 ITM/OTM 不同)
        if is_itm:
            # ITM: 行权涉及股票交易 (买入/卖出 lot_size 股)
            shares = abs(quantity) * effective_lot_size
            commission = self._commission_model.calculate_stock(shares)
            reason = "assigned"
        else:
            # OTM: 价值归零，无交易
            commission = 0.0
            reason = "expired_worthless"

        net_amount = gross_amount - commission

        # 生成执行记录
        self._execution_counter += 1
        execution = TradeExecution(
            execution_id=f"E{self._execution_counter:08d}",
            trade_date=trade_date,
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            side=side,
            quantity=quantity,  # 有符号
            order_price=fill_price,
            fill_price=fill_price,
            slippage=0.0,
            slippage_pct=0.0,
            commission=commission,
            gross_amount=gross_amount,
            net_amount=net_amount,
            status=ExecutionStatus.FILLED,
            lot_size=effective_lot_size,
            reason=reason,
        )

        self._executions.append(execution)

        # 创建交易记录 (Trade 层职责)
        self._trade_counter += 1
        trade_record = TradeRecord(
            trade_id=f"T{self._trade_counter:06d}",
            execution_id=execution.execution_id,
            symbol=symbol,
            underlying=underlying,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
            trade_date=trade_date,
            action="expire",
            quantity=quantity,  # 保持原始符号
            price=fill_price,
            commission=commission,  # ITM: stock commission, OTM: 0
            gross_amount=gross_amount,
            net_amount=net_amount,
            reason=reason,
            close_reason_type=(
                CloseReasonType.EXPIRED_ITM if is_itm
                else CloseReasonType.EXPIRED_WORTHLESS
            ),
        )
        self._trade_records.append(trade_record)

        logger.debug(
            f"Executed EXPIRE: {symbol} {reason}, "
            f"intrinsic={intrinsic_value:.4f}, gross={gross_amount:.2f}"
        )

        return execution

    def get_total_slippage(self) -> float:
        """获取总滑点损失"""
        return sum(e.slippage * abs(e.quantity) * e.lot_size for e in self._executions)

    def get_total_commission(self) -> float:
        """获取总手续费"""
        return sum(e.commission for e in self._executions)

    def get_execution_summary(self) -> dict:
        """获取执行摘要"""
        total_trades = len(self._executions)
        open_trades = len([e for e in self._executions if "open" in e.reason or "signal" in e.reason])
        close_trades = total_trades - open_trades

        return {
            "total_trades": total_trades,
            "open_trades": open_trades,
            "close_trades": close_trades,
            "total_slippage": self.get_total_slippage(),
            "total_commission": self.get_total_commission(),
            "avg_slippage_pct": (
                sum(e.slippage_pct for e in self._executions) / total_trades
                if total_trades > 0 else 0.0
            ),
        }

    def clear_executions(self) -> None:
        """清空执行记录"""
        self._executions.clear()
        self._execution_counter = 0

    def clear_trade_records(self) -> None:
        """清空交易记录"""
        self._trade_records.clear()
        self._trade_counter = 0

    def reset(self) -> None:
        """重置模拟器"""
        self.clear_executions()
        self.clear_trade_records()

    def update_last_trade_pnl(self, pnl: float) -> None:
        """更新最后一条交易记录的 PnL

        用于在平仓时回填已实现盈亏。

        Args:
            pnl: 已实现盈亏
        """
        if self._trade_records:
            self._trade_records[-1].pnl = pnl

    @staticmethod
    def _infer_close_reason_type(reason: str, action: str) -> CloseReasonType | None:
        """从 reason 字符串推断结构化平仓类型"""
        if action == "open":
            return None
        if action == "expire":
            if "assigned" in reason:
                return CloseReasonType.EXPIRED_ITM
            return CloseReasonType.EXPIRED_WORTHLESS
        # action == "close"
        r = reason.lower()
        if "profit" in r or "止盈" in reason:
            return CloseReasonType.PROFIT_TARGET
        if "delta" in r or "DELTA" in reason:
            return CloseReasonType.STOP_LOSS_DELTA
        if "otm" in r or "OTM" in reason:
            return CloseReasonType.STOP_LOSS_OTM
        if "stop" in r or "loss" in r or "止损" in reason or "触发止损" in reason or "无条件平仓" in reason:
            return CloseReasonType.STOP_LOSS
        if "dte" in r or "time" in r:
            return CloseReasonType.TIME_EXIT
        if "roll" in r:
            return CloseReasonType.ROLL
        if "close" in r or "平仓" in reason:
            return CloseReasonType.MANUAL_CLOSE
        return CloseReasonType.UNKNOWN

    def update_last_trade_position_id(self, position_id: str) -> None:
        """更新最后一条交易记录的 position_id

        用于将 TradeRecord 关联到具体持仓。

        Args:
            position_id: 持仓 ID
        """
        if self._trade_records:
            self._trade_records[-1].position_id = position_id
