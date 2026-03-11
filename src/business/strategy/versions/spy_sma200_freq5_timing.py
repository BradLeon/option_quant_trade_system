"""SPY SMA50/200 Golden Cross Timing Strategy

Delta-1 股票代理 + SMA50/SMA200 金叉死叉择时:
- SMA50 > SMA200 (金叉): 满仓
- SMA50 < SMA200 (死叉): 清仓持现
- 仅每 5 个交易日检查，减少信号噪声

金叉/死叉相比 price>SMA200 的优势:
- SMA50 本身是平滑后的信号，比单日 close 稳定得多
- 大幅减少均线附近的 whipsaw（SMA50 穿越 SMA200 频率远低于 price 穿越 SMA200）
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

DECISION_FREQUENCY = 5


class SpySma200Freq5Timing(BaseTradeStrategy):
    """SPY SMA50/200 金叉死叉 + Freq=5 择时策略

    - SMA50 > SMA200 (金叉) + 决策日：满仓 (Delta-1 股票代理)
    - SMA50 < SMA200 (死叉) + 决策日：清仓持现
    - 非决策日：保持现有仓位不变
    """

    def __init__(self):
        super().__init__()
        self.sma_short_period = 50
        self.sma_long_period = 200
        self.decision_frequency = DECISION_FREQUENCY

        self._signal_invested: bool = False
        self._signal_computed_for_date: Optional[date] = None
        self._pending_exit_to_cash: bool = False
        self._last_eval_date: Optional[date] = None
        self._trading_day_count: int = 0

    @property
    def name(self) -> str:
        return "spy_sma200_freq5_timing"

    @property
    def position_side(self) -> str:
        return "LONG"

    # ==========================================
    # SMA 信号
    # ==========================================
    def _compute_sma_signal(self, context: MarketContext, data_provider: Any) -> bool:
        """计算 SMA50/SMA200 金叉死叉信号

        Returns:
            True = 金叉 (SMA50 > SMA200), False = 死叉 (SMA50 < SMA200)
        """
        if self._signal_computed_for_date == context.current_date:
            return self._signal_invested

        symbols = list(context.underlying_prices.keys())
        if not symbols:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        symbol = symbols[0]

        from src.data.models.stock import KlineType

        lookback_start = context.current_date - timedelta(days=self.sma_long_period * 2)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=context.current_date,
        )

        if not klines or len(klines) < self.sma_long_period:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        prices = [k.close for k in klines]
        from src.engine.position.technical.moving_average import calc_sma

        sma_short = calc_sma(prices, self.sma_short_period)
        sma_long = calc_sma(prices, self.sma_long_period)
        if sma_short is None or sma_long is None:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        self._signal_invested = sma_short > sma_long

        logger.debug(
            f"SMA cross signal: {symbol} SMA{self.sma_short_period}={sma_short:.2f} vs "
            f"SMA{self.sma_long_period}={sma_long:.2f} → "
            f"{'GOLDEN CROSS' if self._signal_invested else 'DEATH CROSS'} (day#{self._trading_day_count})"
        )

        self._signal_computed_for_date = context.current_date
        return self._signal_invested

    def _is_decision_day(self) -> bool:
        return self._trading_day_count % self.decision_frequency == 0

    # ==========================================
    # evaluate_positions
    # ==========================================
    def evaluate_positions(
        self,
        positions: List[PositionData],
        context: MarketContext,
        data_provider: Any = None,
    ) -> List[TradeSignal]:
        from src.backtest.engine.trade_simulator import TradeAction

        self._last_eval_date = context.current_date
        self._trading_day_count += 1
        self._pending_exit_to_cash = False

        signals: List[TradeSignal] = []
        stock_positions = [
            p
            for p in positions
            if (getattr(p, 'asset_type', None) == "stock"
                or (p.option_type and p.option_type.lower() == "call" and (p.quantity or 0) > 0))
        ]

        if not stock_positions:
            return signals

        invested = self._compute_sma_signal(context, data_provider)

        # 只在决策日允许平仓
        if not invested and self._is_decision_day():
            self._pending_exit_to_cash = True
            for pos in stock_positions:
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason=f"Death cross (freq={self.decision_frequency}): SMA50 < SMA200, moving to cash",
                        alert_type="sma_exit",
                        position_id=pos.position_id,
                        priority="high",
                    )
                )
            logger.info(
                f"SMA EXIT (day#{self._trading_day_count}): "
                f"closing {len(stock_positions)} positions"
            )

        return signals

    # ==========================================
    # find_opportunities
    # ==========================================
    def find_opportunities(
        self,
        symbols: List[str],
        data_provider: Any,
        context: MarketContext,
    ) -> List[ContractOpportunity]:
        # 补偿: evaluate_positions 未被调用时推进计数器
        if self._last_eval_date != context.current_date:
            self._trading_day_count += 1
            self._pending_exit_to_cash = False

        invested = self._compute_sma_signal(context, data_provider)

        # 只在决策日 + 信号看多 + 无待平仓 时开仓
        if not invested or self._pending_exit_to_cash or not self._is_decision_day():
            return []

        opportunities = []
        for symbol in symbols:
            spot = context.underlying_prices.get(symbol)
            if not spot or spot <= 0:
                continue

            opp = ContractOpportunity(
                symbol=symbol,
                expiry=(context.current_date + timedelta(days=9999)).strftime("%Y-%m-%d"),
                strike=0.01,
                option_type="call",
                lot_size=1,
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

    # ==========================================
    # generate_entry_signals
    # ==========================================
    def generate_entry_signals(
        self,
        candidates: List[ContractOpportunity],
        account: Any,
        context: MarketContext,
    ) -> List[TradeSignal]:
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import Greeks, OptionContract, OptionQuote, OptionType

        # 已有持仓则不重复开仓
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
                    reason=f"Golden cross (freq={self.decision_frequency}): {shares} shares @ {spot:.2f}",
                    priority="normal",
                    quote=quote,
                )
            )

        return signals
