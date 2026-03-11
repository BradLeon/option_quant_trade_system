"""SPY Buy & Hold + SMA200 Timing Benchmark
这是一个仅交易标的（通过 Delta=1 合成模拟）的基准测试策略。
目的在于排查 LEAPS 策略之所以表现差，究竟是因为 SMA 择时信号的问题，还是期权/杠杆本身带来的损耗。

逻辑：
- SMA200 上方：多头满仓 (持有的 Delta 相当于 1:1 持有现货)
- SMA200 下方：清仓，持有现金
- 使用 DTE=99999, Strike=0.01 的期权作为现货代理，lot_size=1
"""

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from src.business.monitoring.models import PositionData
from src.business.screening.models import ContractOpportunity
from src.business.strategy.base import BaseTradeStrategy
from src.business.strategy.models import MarketContext, TradeSignal

logger = logging.getLogger(__name__)

class SpyBuyAndHoldSmaTiming(BaseTradeStrategy):
    def __init__(self):
        super().__init__()
        self.sma_period = 200
        self._signal_invested: bool = False
        self._signal_computed_for_date: Optional[date] = None
        self._pending_exit_to_cash: bool = False
        self._last_eval_date: Optional[date] = None

    @property
    def name(self) -> str:
        return "spy_buy_and_hold_sma_timing"

    @property
    def position_side(self) -> str:
        return "LONG"

    def _compute_sma_signal(self, context: MarketContext, data_provider: Any) -> bool:
        if self._signal_computed_for_date == context.current_date:
            return self._signal_invested

        symbols = list(context.underlying_prices.keys())
        if not symbols:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        symbol = symbols[0]

        from src.data.models.stock import KlineType
        lookback_start = context.current_date - timedelta(days=self.sma_period * 2)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=context.current_date,
        )

        if not klines or len(klines) < self.sma_period:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        prices = [k.close for k in klines]
        from src.engine.position.technical.moving_average import calc_sma
        sma_value = calc_sma(prices, self.sma_period)

        if sma_value is None:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        last_close = prices[-1]
        self._signal_invested = last_close > sma_value
        self._signal_computed_for_date = context.current_date
        return self._signal_invested

    def evaluate_positions(
        self, positions: List[PositionData], context: MarketContext, data_provider: Any = None
    ) -> List[TradeSignal]:
        from src.backtest.engine.trade_simulator import TradeAction

        self._last_eval_date = context.current_date
        self._pending_exit_to_cash = False

        signals: List[TradeSignal] = []
        stock_proxy_positions = [
            p for p in positions
            if (getattr(p, 'asset_type', None) == "stock"
                or (p.option_type and p.option_type.lower() == "call" and (p.quantity or 0) > 0))
        ]

        if not stock_proxy_positions:
            return signals

        invested = self._compute_sma_signal(context, data_provider)

        if not invested:
            self._pending_exit_to_cash = True
            for pos in stock_proxy_positions:
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason="SMA exit: price below SMA, moving to cash (Stock Proxy)",
                        alert_type="sma_exit",
                        position_id=pos.position_id,
                        priority="high",
                    )
                )

        return signals

    def find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        if self._last_eval_date != context.current_date:
            self._pending_exit_to_cash = False

        invested = self._compute_sma_signal(context, data_provider)

        # We only want to open if invested and we aren't about to close
        need_entry = invested and not self._pending_exit_to_cash 

        if not need_entry:
            return []

        opportunities = []
        for symbol in symbols:
            spot = context.underlying_prices.get(symbol)
            if not spot or spot <= 0:
                continue

            # Create a Proxy ContractOpportunity acting as Stock
            opp = ContractOpportunity(
                symbol=symbol,
                expiry=(context.current_date + timedelta(days=9999)).strftime("%Y-%m-%d"),
                strike=0.01,
                option_type="call",
                lot_size=1, # 1 contract = 1 share
                bid=spot,
                ask=spot,
                mid_price=spot,
                open_interest=999999,
                volume=999999,
                delta=1.0,
                gamma=0.0,
                theta=0.0,
                vega=0.0,
                iv=0.0,
                dte=9999,
                underlying_price=spot,
                moneyness=0.0,
                annual_roc=0.0,
                metadata={"source_strategy_type": "long_call", "is_stock_proxy": True},
            )
            opportunities.append(opp)

        return opportunities

    def generate_entry_signals(
        self,
        candidates: List[ContractOpportunity],
        account: Any,
        context: MarketContext,
    ) -> List[TradeSignal]:
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionContract, OptionQuote, OptionType, Greeks
        
        # Prevent reopening if we already hold positions
        if account.position_count > 0:
            return []

        if not candidates:
            return []

        nlv = account.nlv
        cash = account.cash
        if nlv <= 0 or cash <= 0:
            return []

        signals: List[TradeSignal] = []

        for opp in candidates:
            spot = opp.mid_price
            if spot <= 0:
                continue
            
            # Buy with 95% of cash
            available_capital = cash * 0.95
            shares = math.floor(available_capital / spot)

            if shares <= 0:
                continue
                
            expiration = context.current_date + timedelta(days=opp.dte)

            option_contract = OptionContract(
                symbol=f"{opp.symbol}_{expiration.strftime('%y%m%d')}_C_0",
                underlying=opp.symbol,
                option_type=OptionType.CALL,
                strike_price=opp.strike,
                expiry_date=expiration,
                lot_size=opp.lot_size,
            )

            greeks = Greeks(delta=1.0, gamma=0.0, theta=0.0, vega=0.0)

            quote = OptionQuote(
                contract=option_contract,
                timestamp=datetime.combine(context.current_date, datetime.min.time()),
                bid=spot,
                ask=spot,
                last_price=spot,
                iv=0.0,
                volume=99999,
                open_interest=99999,
                greeks=greeks,
            )

            signals.append(
                TradeSignal(
                    action=TradeAction.OPEN,
                    symbol=option_contract.symbol,
                    quantity=shares,
                    reason=f"SMA entry: {shares} shares @ {spot:.2f} (Delta-1 Proxy)",
                    priority="normal",
                    quote=quote,
                )
            )

        return signals
