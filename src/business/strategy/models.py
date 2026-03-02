from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.data.models.option import OptionQuote
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtest.engine.account_simulator import SimulatedPosition
    from src.backtest.engine.trade_simulator import TradeAction

@dataclass
class MarketContext:
    """市场环境上下文
    
    用于向策略传递当前可用的大盘指标、日期等信息，
    供策略在 evaluate_market_environment 和 get_contract_filters 时进行判断。
    """
    current_date: date
    # 支持多标的回测，保存各标的当天的价格
    underlying_prices: dict[str, float] = field(default_factory=dict)
    # 这里可以添加更多宏观或大盘指标，例如 VIX、RSI 等
    # 今后大盘趋势等信息，也都可打包到这里传递给策略
    vix_value: Optional[float] = None
    market_trend: Optional[str] = None
    
@dataclass
class TradeSignal:
    """策略生成的交易指令信号

    统一内部使用的数据结构，通知引擎进行开/平仓操作。
    """
    action: "TradeAction"
    symbol: str  # 要交易的具体期权合约代码
    quantity: int  # 正数为买，负数为卖，与 TradeSimulator 一致
    reason: str  # 记录该信号产生的原因（例如 "DTE<=14 止盈"）
    # 用于交易执行的唯一标识（优先使用此字段定位持仓）
    position_id: Optional[str] = None
    # 当平仓时，这里可指定原持仓，便于追踪
    related_position: Optional["SimulatedPosition"] = None
    # 附带原 quote 信息(主要用于开仓信号)
    quote: Optional[OptionQuote] = None
    # 展期专用信息
    roll_to_expiry: Optional[str] = None
    roll_to_strike: Optional[float] = None
    # 优先级
    priority: str = "normal"
