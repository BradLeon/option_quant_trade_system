#!/usr/bin/env python3
"""
独立的期权收入策略回测脚本 (Standalone Options Income Strategy Backtest)

本脚本对三种期权收入策略进行回测并比较:
1. 增强型卖空头: 定期卖SPY/QQQ看跌期权
2. 轮转策略: 卖看跌期权, 被行使后卖覆盖期权
3. 卖空头 + LEAPS多头组合: 70%资本卖空头, 30%买入深虚值长期看涨期权

关键需求:
- 初始资本: $100,000
- 月均收入目标: >= $1,500 ($18,000/年)
- 年回报率: > 5% (固定收益基准)
- 最大回撤: < SPY
- 标的: SPY, QQQ只
- 月初扣除$1,500生活费

使用Black-Scholes模型计算期权价格和希腊人。
如果找不到真实数据, 使用合成数据生成。
"""

import math
import random
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Dict

import numpy as np
import pandas as pd
from scipy.stats import norm
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates

warnings.filterwarnings('ignore')

# ==================== Black-Scholes 期权定价模型 ====================

def norm_pdf(x: float) -> float:
    """标准正态分布概率密度函数"""
    return (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x ** 2)


def norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数"""
    return norm.cdf(x)


def calc_d1(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算Black-Scholes d1"""
    if sigma <= 0 or T <= 0:
        return 0.0
    numerator = math.log(S / K) + (r + 0.5 * sigma ** 2) * T
    denominator = sigma * math.sqrt(T)
    return numerator / denominator


def calc_d2(d1: float, sigma: float, T: float) -> float:
    """计算Black-Scholes d2"""
    if sigma <= 0 or T <= 0:
        return 0.0
    return d1 - sigma * math.sqrt(T)


def bs_call_price(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算欧式看涨期权价格"""
    if T <= 0:
        return max(S - K, 0.0)
    d1 = calc_d1(S, K, r, sigma, T)
    d2 = calc_d2(d1, sigma, T)
    call = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return max(call, 0.0)


def bs_put_price(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算欧式看跌期权价格"""
    if T <= 0:
        return max(K - S, 0.0)
    d1 = calc_d1(S, K, r, sigma, T)
    d2 = calc_d2(d1, sigma, T)
    put = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    return max(put, 0.0)


def bs_call_delta(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看涨期权Delta"""
    if T <= 0:
        return 1.0 if S > K else 0.0
    d1 = calc_d1(S, K, r, sigma, T)
    return norm_cdf(d1)


def bs_put_delta(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看跌期权Delta (负值)"""
    if T <= 0:
        return 0.0 if S > K else -1.0
    d1 = calc_d1(S, K, r, sigma, T)
    return -norm_cdf(-d1)


def bs_call_gamma(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看涨期权Gamma"""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = calc_d1(S, K, r, sigma, T)
    return norm_pdf(d1) / (S * sigma * math.sqrt(T))


def bs_call_theta(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看涨期权日Theta (衰减/天)"""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = calc_d1(S, K, r, sigma, T)
    d2 = calc_d2(d1, sigma, T)
    sqrt_T = math.sqrt(T)
    theta = (
        -S * norm_pdf(d1) * sigma / (2 * sqrt_T) -
        r * K * math.exp(-r * T) * norm_cdf(d2)
    )
    return theta / 365.0


def bs_put_theta(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看跌期权日Theta (衰减/天)"""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = calc_d1(S, K, r, sigma, T)
    d2 = calc_d2(d1, sigma, T)
    sqrt_T = math.sqrt(T)
    theta = (
        -S * norm_pdf(d1) * sigma / (2 * sqrt_T) +
        r * K * math.exp(-r * T) * norm_cdf(-d2)
    )
    return theta / 365.0


def bs_call_vega(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看涨期权Vega (波动率敏感度/1%)"""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = calc_d1(S, K, r, sigma, T)
    return S * norm_pdf(d1) * math.sqrt(T) / 100.0


def bs_win_probability_put(S: float, K: float, r: float, sigma: float, T: float) -> float:
    """计算看跌期权的获利概率 P(ST > K)"""
    if T <= 0:
        return 0.0 if S <= K else 1.0
    d1 = calc_d1(S, K, r, sigma, T)
    d2 = calc_d2(d1, sigma, T)
    # 获利概率 = N(d2)
    return norm_cdf(d2)


# ==================== 合成数据生成器 ====================

@dataclass
class SyntheticDataParams:
    """合成数据参数"""
    symbol: str
    annual_return: float = 0.10  # 年平均回报率
    annual_volatility: float = 0.16  # 年波动率
    dividend_yield: float = 0.01  # 股利收益率
    start_price: float = 100.0
    random_seed: int = 42


class SyntheticDataGenerator:
    """使用几何随机游走生成合成的股票价格数据"""

    def __init__(self, params: SyntheticDataParams):
        self.params = params
        self.daily_return = params.annual_return / 252
        self.daily_vol = params.annual_volatility / math.sqrt(252)
        random.seed(params.random_seed)
        np.random.seed(params.random_seed)

    def generate_prices(self, start_date: datetime, num_days: int) -> pd.DataFrame:
        """生成股票价格时间序列"""
        prices = [self.params.start_price]
        dates = [start_date]

        for i in range(1, num_days):
            # 几何随机游走: S_t = S_{t-1} * exp((μ - σ²/2) + σ*Z)
            Z = np.random.standard_normal()
            drift = self.daily_return - 0.5 * self.daily_vol ** 2
            return_today = drift + self.daily_vol * Z
            price_today = prices[-1] * math.exp(return_today)
            prices.append(price_today)
            dates.append(start_date + timedelta(days=i))

        df = pd.DataFrame({
            'date': dates,
            'close': prices,
        })
        df['close'] = df['close'].round(2)
        return df


# ==================== 期权头寸和交易数据结构 ====================

@dataclass
class OptionPosition:
    """单个期权头寸"""
    position_id: str  # 唯一ID
    symbol: str  # 标的资产 (SPY/QQQ)
    option_type: str  # "CALL" 或 "PUT"
    strike: float  # 行使价
    entry_date: datetime  # 开仓日期
    expiry_date: datetime  # 到期日期
    quantity: int  # 合约数量 (1 = 100股)
    premium_received: float  # 收取的权利金 (每股, 对于卖方为正)
    premium_paid: float  # 支付的权利金 (对于买方)
    current_price: float  # 当前期权价格
    side: str  # "LONG" 或 "SHORT"
    status: str  # "OPEN", "CLOSED", "ASSIGNED", "EXPIRED"
    close_price: Optional[float] = None  # 平仓价格
    close_date: Optional[datetime] = None  # 平仓日期
    pnl: float = 0.0  # 平仓损益
    assignment_price: Optional[float] = None  # 行使时的底层价格

    def dte(self, as_of_date: datetime) -> int:
        """距离到期的天数"""
        return max(0, (self.expiry_date - as_of_date).days)


@dataclass
class StockPosition:
    """持有股票头寸 (轮转策略)"""
    symbol: str
    quantity: int  # 股数
    entry_date: datetime
    entry_price: float
    current_price: float

    def market_value(self) -> float:
        return self.quantity * self.current_price

    def pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.quantity


class PortfolioState:
    """投资组合状态快照"""

    def __init__(self, date: datetime, cash: float, option_positions: List[OptionPosition],
                 stock_positions: Dict[str, StockPosition], nlv: float, margin_used: float):
        self.date = date
        self.cash = cash
        self.option_positions = option_positions
        self.stock_positions = stock_positions
        self.nlv = nlv
        self.margin_used = margin_used
        self.holdings_value = sum(pos.market_value() for pos in stock_positions.values())


# ==================== 波动率模型 ====================

class VolatilityModel:
    """波动率模型 - 简化的IV/HV模型"""

    def __init__(self, base_iv: float = 0.20, hv: float = 0.16):
        """
        base_iv: 隐含波动率基数
        hv: 历史波动率
        """
        self.base_iv = base_iv
        self.hv = hv

    def get_iv(self, dte: int, delta: float) -> float:
        """获取指定DTE和Delta的隐含波动率"""
        # 简化模型: 短期期权IV更高 (term structure)
        # 平值期权IV更高 (smile)
        term_factor = 0.15 + 0.10 * math.exp(-dte / 30.0)  # 期限结构
        smile_factor = 1.0 - 0.1 * (abs(delta) - 0.5) ** 2  # 波动率微笑

        iv = self.base_iv * (term_factor / 0.25) * smile_factor
        return max(0.08, iv)  # 最小8%

    def get_hv(self) -> float:
        """获取历史波动率"""
        return self.hv


# ==================== 策略实现 ====================

class IncomeStrategy:
    """收入策略基类"""

    def __init__(self, name: str, initial_capital: float = 100000.0):
        self.name = name
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.option_positions: List[OptionPosition] = []
        self.stock_positions: Dict[str, StockPosition] = {}
        self.history: List[PortfolioState] = []
        self.trades: List[Dict] = []
        self.position_counter = 0
        self.vol_model = VolatilityModel()
        self.commission_per_contract = 0.65
        self.slippage_pct = 0.001

    def _next_position_id(self) -> str:
        """生成唯一的头寸ID"""
        self.position_counter += 1
        return f"{self.name}_{self.position_counter}"

    def _apply_slippage(self, price: float, is_sell: bool) -> float:
        """应用滑点: 买入价格上升, 卖出价格下降"""
        if is_sell:
            return price * (1 - self.slippage_pct)
        else:
            return price * (1 + self.slippage_pct)

    def _calc_margin_for_short_put(self, strike: float, premium: float, spot_price: float) -> float:
        """计算卖空头期权的保证金需求 (IBKR公式)"""
        # Margin = Premium + Max(20% * Spot - OTM, 10% * Strike)
        otm = max(0, spot_price - strike)
        margin = premium + max(0.20 * spot_price - otm, 0.10 * strike)
        return margin

    def open_short_put(self, symbol: str, spot_price: float, strike: float,
                       dte: int, current_date: datetime, quantity: int = 1) -> bool:
        """开仓卖看跌期权"""
        # 计算权利金
        T = dte / 365.0
        iv = self.vol_model.get_iv(dte, -0.25)
        premium = bs_put_price(spot_price, strike, 0.03, iv, T)
        premium_after_slippage = self._apply_slippage(premium, is_sell=True)

        # 应用手续费
        total_premium = premium_after_slippage * 100 * quantity - self.commission_per_contract * quantity

        # 检查保证金
        margin_per_contract = self._calc_margin_for_short_put(strike, premium_after_slippage, spot_price)
        total_margin = margin_per_contract * 100 * quantity

        if self.cash < total_margin:
            return False  # 保证金不足

        # 创建头寸
        pos = OptionPosition(
            position_id=self._next_position_id(),
            symbol=symbol,
            option_type="PUT",
            strike=strike,
            entry_date=current_date,
            expiry_date=current_date + timedelta(days=dte),
            quantity=quantity,
            premium_received=premium_after_slippage,
            premium_paid=0.0,
            current_price=premium_after_slippage,
            side="SHORT",
            status="OPEN",
        )

        self.option_positions.append(pos)
        self.cash += total_premium  # 收取权利金

        self.trades.append({
            'date': current_date,
            'symbol': symbol,
            'type': 'OPEN_SHORT_PUT',
            'strike': strike,
            'quantity': quantity,
            'premium': premium_after_slippage,
            'margin_used': total_margin,
            'cash_received': total_premium,
        })

        return True

    def open_long_call(self, symbol: str, spot_price: float, strike: float,
                       dte: int, current_date: datetime, quantity: int = 1) -> bool:
        """开仓买看涨期权 (用于LEAPS策略)"""
        T = dte / 365.0
        iv = self.vol_model.get_iv(dte, 0.70)
        premium = bs_call_price(spot_price, strike, 0.03, iv, T)
        premium_after_slippage = self._apply_slippage(premium, is_sell=False)

        # 应用手续费
        total_cost = premium_after_slippage * 100 * quantity + self.commission_per_contract * quantity

        if self.cash < total_cost:
            return False

        pos = OptionPosition(
            position_id=self._next_position_id(),
            symbol=symbol,
            option_type="CALL",
            strike=strike,
            entry_date=current_date,
            expiry_date=current_date + timedelta(days=dte),
            quantity=quantity,
            premium_received=0.0,
            premium_paid=premium_after_slippage,
            current_price=premium_after_slippage,
            side="LONG",
            status="OPEN",
        )

        self.option_positions.append(pos)
        self.cash -= total_cost

        self.trades.append({
            'date': current_date,
            'symbol': symbol,
            'type': 'OPEN_LONG_CALL',
            'strike': strike,
            'quantity': quantity,
            'premium': premium_after_slippage,
            'cash_used': total_cost,
        })

        return True

    def open_short_call(self, symbol: str, spot_price: float, strike: float,
                        dte: int, current_date: datetime, quantity: int = 1) -> bool:
        """开仓卖看涨期权 (轮转策略的覆盖期权)"""
        T = dte / 365.0
        iv = self.vol_model.get_iv(dte, 0.35)
        premium = bs_call_price(spot_price, strike, 0.03, iv, T)
        premium_after_slippage = self._apply_slippage(premium, is_sell=True)

        # 应用手续费
        total_premium = premium_after_slippage * 100 * quantity - self.commission_per_contract * quantity

        pos = OptionPosition(
            position_id=self._next_position_id(),
            symbol=symbol,
            option_type="CALL",
            strike=strike,
            entry_date=current_date,
            expiry_date=current_date + timedelta(days=dte),
            quantity=quantity,
            premium_received=premium_after_slippage,
            premium_paid=0.0,
            current_price=premium_after_slippage,
            side="SHORT",
            status="OPEN",
        )

        self.option_positions.append(pos)
        self.cash += total_premium

        self.trades.append({
            'date': current_date,
            'symbol': symbol,
            'type': 'OPEN_SHORT_CALL',
            'strike': strike,
            'quantity': quantity,
            'premium': premium_after_slippage,
            'cash_received': total_premium,
        })

        return True

    def close_position(self, pos: OptionPosition, close_price: float,
                       current_date: datetime, reason: str = "MANUAL") -> float:
        """平仓期权头寸"""
        if pos.status != "OPEN":
            return 0.0

        close_price_after_slippage = self._apply_slippage(close_price, is_sell=False if pos.side == "SHORT" else True)

        if pos.side == "SHORT":
            # 卖方: 买回
            close_cost = close_price_after_slippage * 100 * pos.quantity + self.commission_per_contract * pos.quantity
            pnl = (pos.premium_received - close_price_after_slippage) * 100 * pos.quantity - 2 * self.commission_per_contract * pos.quantity
            self.cash -= close_cost
        else:
            # 买方: 卖出
            close_proceeds = close_price_after_slippage * 100 * pos.quantity - self.commission_per_contract * pos.quantity
            pnl = (close_price_after_slippage - pos.premium_paid) * 100 * pos.quantity - 2 * self.commission_per_contract * pos.quantity
            self.cash += close_proceeds

        pos.close_price = close_price_after_slippage
        pos.close_date = current_date
        pos.status = "CLOSED"
        pos.pnl = pnl

        self.trades.append({
            'date': current_date,
            'symbol': pos.symbol,
            'type': f'CLOSE_{pos.side}_{pos.option_type}',
            'position_id': pos.position_id,
            'close_price': close_price_after_slippage,
            'pnl': pnl,
            'reason': reason,
        })

        return pnl

    def buy_stock(self, symbol: str, quantity: int, price: float, current_date: datetime) -> bool:
        """购买股票 (轮转策略)"""
        cost = quantity * price * (1 + self.slippage_pct) + self.commission_per_contract * quantity / 100.0

        if self.cash < cost:
            return False

        self.cash -= cost
        self.stock_positions[symbol] = StockPosition(
            symbol=symbol,
            quantity=quantity,
            entry_date=current_date,
            entry_price=price,
            current_price=price,
        )

        self.trades.append({
            'date': current_date,
            'symbol': symbol,
            'type': 'BUY_STOCK',
            'quantity': quantity,
            'price': price,
            'cost': cost,
        })

        return True

    def sell_stock(self, symbol: str, price: float, current_date: datetime) -> Optional[float]:
        """出售股票"""
        if symbol not in self.stock_positions:
            return None

        pos = self.stock_positions[symbol]
        proceeds = pos.quantity * price * (1 - self.slippage_pct) - self.commission_per_contract * pos.quantity / 100.0
        pnl = (price - pos.entry_price) * pos.quantity

        self.cash += proceeds
        del self.stock_positions[symbol]

        self.trades.append({
            'date': current_date,
            'symbol': symbol,
            'type': 'SELL_STOCK',
            'quantity': pos.quantity,
            'price': price,
            'proceeds': proceeds,
            'pnl': pnl,
        })

        return pnl

    def update_option_prices(self, current_date: datetime, prices: Dict[str, float], vol_model: VolatilityModel):
        """更新期权价格"""
        for pos in self.option_positions:
            if pos.status != "OPEN":
                continue

            spot = prices.get(pos.symbol, 0)
            if spot <= 0:
                continue

            dte = pos.dte(current_date)
            if dte <= 0:
                continue

            T = dte / 365.0
            iv = vol_model.get_iv(dte, bs_put_delta(spot, pos.strike, 0.03, vol_model.get_iv(dte, -0.25), T) if pos.option_type == "PUT" else bs_call_delta(spot, pos.strike, 0.03, vol_model.get_iv(dte, 0.35), T))

            if pos.option_type == "PUT":
                pos.current_price = bs_put_price(spot, pos.strike, 0.03, iv, T)
            else:
                pos.current_price = bs_call_price(spot, pos.strike, 0.03, iv, T)

    def update_stock_prices(self, prices: Dict[str, float]):
        """更新股票价格"""
        for symbol, pos in self.stock_positions.items():
            if symbol in prices:
                pos.current_price = prices[symbol]

    def calc_nlv(self, prices: Dict[str, float]) -> float:
        """计算净资产价值"""
        option_value = 0.0
        for pos in self.option_positions:
            if pos.status != "OPEN":
                continue
            if pos.side == "SHORT":
                # 卖方: 未平仓盈利 = (收取权利金 - 当前价格) * 合约量 * 100
                option_value += (pos.premium_received - pos.current_price) * 100 * pos.quantity
            else:
                # 买方: 未平仓盈利 = (当前价格 - 支付权利金) * 合约量 * 100
                option_value += (pos.current_price - pos.premium_paid) * 100 * pos.quantity

        stock_value = sum(pos.market_value() for pos in self.stock_positions.values())

        # 对于买入持有策略, 加上股票市值
        if hasattr(self, 'shares_held') and self.shares_held > 0:
            spot_price = prices.get("SPY", 0)
            if spot_price > 0:
                stock_value += self.shares_held * spot_price

        return max(0, self.cash + option_value + stock_value)

    def calc_margin_usage(self, prices: Dict[str, float]) -> float:
        """计算保证金使用情况"""
        margin_used = 0.0
        for pos in self.option_positions:
            if pos.status != "OPEN" or pos.side != "SHORT":
                continue

            spot = prices.get(pos.symbol, 0)
            if spot <= 0:
                continue

            margin_used += self._calc_margin_for_short_put(pos.strike, pos.current_price, spot) * 100 * pos.quantity

        return margin_used

    def save_snapshot(self, current_date: datetime, prices: Dict[str, float]):
        """保存组合状态快照"""
        nlv = self.calc_nlv(prices)
        margin_used = self.calc_margin_usage(prices)

        snapshot = PortfolioState(
            date=current_date,
            cash=self.cash,
            option_positions=list(self.option_positions),
            stock_positions=dict(self.stock_positions),
            nlv=nlv,
            margin_used=margin_used,
        )
        self.history.append(snapshot)

    def process_day(self, current_date: datetime, prices: Dict[str, float]):
        """处理一天的事件"""
        raise NotImplementedError


class EnhancedShortPutStrategy(IncomeStrategy):
    """策略A: 增强型卖空头"""

    def __init__(self, initial_capital: float = 100000.0):
        super().__init__("ENHANCED_SHORT_PUT", initial_capital)
        self.target_dte = 35  # 目标DTE
        self.min_dte_roll = 21  # 最小DTE时滚转
        self.close_profit_pct = 0.50  # 50%利润时平仓
        self.delta_target = 0.25  # 目标Delta
        self.max_margin_util = 0.70  # 最大保证金使用率 (更保守)

    def process_day(self, current_date: datetime, prices: Dict[str, float]):
        """每日处理"""
        self.update_option_prices(current_date, prices, self.vol_model)

        # 处理到期
        for pos in list(self.option_positions):
            if pos.status != "OPEN":
                continue

            dte = pos.dte(current_date)

            # 到期处理
            if dte <= 0:
                if pos.option_type == "PUT":
                    spot = prices.get(pos.symbol, 0)
                    if spot < pos.strike:
                        # 被行使
                        pnl = pos.premium_received * 100 * pos.quantity
                        pos.status = "ASSIGNED"
                        pos.pnl = pnl
                        pos.assignment_price = spot
                        self.cash -= spot * 100 * pos.quantity
                    else:
                        # 到期无利益
                        pnl = pos.premium_received * 100 * pos.quantity - 2 * self.commission_per_contract * pos.quantity
                        pos.status = "EXPIRED"
                        pos.pnl = pnl
                continue

            # 滚转或平仓
            if dte <= self.min_dte_roll:
                close_price = pos.current_price
                max_loss = (pos.strike - pos.premium_received) * 100 * pos.quantity
                current_loss = (pos.current_price - pos.premium_received) * 100 * pos.quantity

                # 如果已实现50%利润, 平仓
                if pos.premium_received > 0 and close_price <= pos.premium_received * (1 - self.close_profit_pct):
                    self.close_position(pos, close_price, current_date, "PROFIT_TARGET")

            # 检查200%亏损 (止损)
            elif pos.premium_received > 0:
                max_loss = (pos.strike - pos.premium_received) * 100 * pos.quantity
                current_loss = (pos.current_price - pos.premium_received) * 100 * pos.quantity
                if current_loss >= max_loss * 2.0:
                    self.close_position(pos, pos.current_price, current_date, "STOP_LOSS")

        # 开仓新头寸
        margin_limit = self.initial_capital * self.max_margin_util
        margin_used = self.calc_margin_usage(prices)
        margin_avail = margin_limit - margin_used

        for symbol in ["SPY"]:  # 主要在SPY上交易
            spot = prices.get(symbol, 0)
            if spot <= 0 or margin_avail <= 0:
                continue

            # 检查是否需要新头寸
            open_positions = sum(1 for p in self.option_positions
                                if p.status == "OPEN" and p.symbol == symbol and p.option_type == "PUT")

            if open_positions < 2:  # 最多2个开仓头寸
                # 计算行使价 (Delta -0.25 target)
                T = self.target_dte / 365.0
                iv = self.vol_model.get_iv(self.target_dte, -self.delta_target)

                # 二分法找到目标Delta的行使价
                K_low, K_high = spot * 0.85, spot * 0.95
                for _ in range(10):
                    K_mid = (K_low + K_high) / 2.0
                    delta = bs_put_delta(spot, K_mid, 0.03, iv, T)
                    if delta < -self.delta_target:
                        K_low = K_mid
                    else:
                        K_high = K_mid

                strike = (K_low + K_high) / 2.0

                # 计算所需保证金
                premium = bs_put_price(spot, strike, 0.03, iv, T)
                margin_needed = self._calc_margin_for_short_put(strike, premium, spot) * 100

                if margin_needed > 0 and margin_needed <= margin_avail:
                    self.open_short_put(symbol, spot, strike, self.target_dte, current_date, quantity=1)


class WheelStrategy(IncomeStrategy):
    """策略B: 轮转策略"""

    def __init__(self, initial_capital: float = 100000.0):
        super().__init__("WHEEL", initial_capital)
        self.target_dte = 35
        self.put_delta_target = 0.30
        self.call_delta_target = 0.35

    def process_day(self, current_date: datetime, prices: Dict[str, float]):
        """每日处理"""
        self.update_option_prices(current_date, prices, self.vol_model)
        self.update_stock_prices(prices)

        # 处理到期
        for symbol, stock_pos in list(self.stock_positions.items()):
            # 检查覆盖看涨期权是否到期
            for opt_pos in list(self.option_positions):
                if opt_pos.status != "OPEN" or opt_pos.symbol != symbol or opt_pos.option_type != "CALL":
                    continue

                dte = opt_pos.dte(current_date)
                if dte <= 0:
                    spot = prices.get(symbol, 0)
                    if spot >= opt_pos.strike:
                        # 股票被行使, 卖出
                        pnl = opt_pos.premium_received * 100
                        stock_pnl = self.sell_stock(symbol, opt_pos.strike, current_date)
                        opt_pos.status = "ASSIGNED"
                        opt_pos.pnl = pnl + stock_pnl
                    else:
                        opt_pos.status = "EXPIRED"
                        opt_pos.pnl = opt_pos.premium_received * 100

        # 处理看跌期权
        for pos in list(self.option_positions):
            if pos.status != "OPEN" or pos.option_type != "PUT":
                continue

            dte = pos.dte(current_date)

            if dte <= 0:
                spot = prices.get(pos.symbol, 0)
                if spot < pos.strike:
                    # 被行使, 买入股票
                    self.buy_stock(pos.symbol, pos.quantity * 100, pos.strike, current_date)
                    pos.status = "ASSIGNED"
                    pos.pnl = pos.premium_received * 100 * pos.quantity
                else:
                    pos.status = "EXPIRED"
                    pos.pnl = pos.premium_received * 100 * pos.quantity

        # 卖看跌期权
        for symbol in ["SPY"]:
            spot = prices.get(symbol, 0)
            if spot <= 0:
                continue

            # 检查是否需要开新头寸
            open_puts = sum(1 for p in self.option_positions
                           if p.status == "OPEN" and p.symbol == symbol and p.option_type == "PUT")

            if open_puts == 0:
                T = self.target_dte / 365.0
                iv = self.vol_model.get_iv(self.target_dte, -self.put_delta_target)

                K_low, K_high = spot * 0.83, spot * 0.93
                for _ in range(10):
                    K_mid = (K_low + K_high) / 2.0
                    delta = bs_put_delta(spot, K_mid, 0.03, iv, T)
                    if delta < -self.put_delta_target:
                        K_low = K_mid
                    else:
                        K_high = K_mid

                strike = (K_low + K_high) / 2.0
                self.open_short_put(symbol, spot, strike, self.target_dte, current_date, quantity=1)

        # 卖覆盖看涨期权 (只在持有股票时)
        for symbol, stock_pos in self.stock_positions.items():
            spot = prices.get(symbol, 0)

            open_calls = sum(1 for p in self.option_positions
                            if p.status == "OPEN" and p.symbol == symbol and p.option_type == "CALL")

            if open_calls == 0:
                T = self.target_dte / 365.0
                iv = self.vol_model.get_iv(self.target_dte, self.call_delta_target)

                K_low, K_high = spot * 1.02, spot * 1.12
                for _ in range(10):
                    K_mid = (K_low + K_high) / 2.0
                    delta = bs_call_delta(spot, K_mid, 0.03, iv, T)
                    if delta > self.call_delta_target:
                        K_high = K_mid
                    else:
                        K_low = K_mid

                strike = (K_low + K_high) / 2.0
                self.open_short_call(symbol, spot, strike, self.target_dte, current_date, quantity=stock_pos.quantity // 100)


class PutsAndLeapsStrategy(IncomeStrategy):
    """策略C: 卖空头 + LEAPS组合 (70/30)"""

    def __init__(self, initial_capital: float = 100000.0):
        super().__init__("PUTS_AND_LEAPS", initial_capital)
        self.puts_allocation = 0.70
        self.leaps_allocation = 0.30
        self.put_capital = initial_capital * self.puts_allocation
        self.leaps_capital = initial_capital * self.leaps_allocation
        self.target_dte_put = 35
        self.target_dte_leaps = 365
        self.put_delta_target = 0.25
        self.leaps_delta_target = 0.70
        self.max_margin_util = 0.60  # 更保守的保证金使用率
        self.rebalance_frequency = 90  # 季度重平衡
        self.last_rebalance = None
        self.leaps_deployed = False  # 追踪LEAPS是否已部署

    def process_day(self, current_date: datetime, prices: Dict[str, float]):
        """每日处理"""
        self.update_option_prices(current_date, prices, self.vol_model)

        # 处理到期
        for pos in list(self.option_positions):
            if pos.status != "OPEN":
                continue

            dte = pos.dte(current_date)

            if dte <= 0:
                if pos.option_type == "PUT":
                    spot = prices.get(pos.symbol, 0)
                    if spot < pos.strike:
                        pnl = pos.premium_received * 100 * pos.quantity
                        pos.status = "ASSIGNED"
                        pos.pnl = pnl
                        pos.assignment_price = spot
                        self.cash -= spot * 100 * pos.quantity
                    else:
                        pnl = pos.premium_received * 100 * pos.quantity - 2 * self.commission_per_contract * pos.quantity
                        pos.status = "EXPIRED"
                        pos.pnl = pnl
                elif pos.option_type == "CALL":
                    # 长期看涨期权到期 (rare)
                    pnl = -(pos.premium_paid * 100 * pos.quantity)
                    pos.status = "EXPIRED"
                    pos.pnl = pnl
                continue

            # 平仓逻辑
            if pos.option_type == "PUT" and dte <= 21:
                close_price = pos.current_price
                if pos.premium_received > 0 and close_price <= pos.premium_received * 0.5:
                    self.close_position(pos, close_price, current_date, "PROFIT_TARGET")

        # 开仓卖空头 (70%资本配置)
        margin_avail_puts = self.put_capital * self.max_margin_util - sum(
            self._calc_margin_for_short_put(p.strike, p.current_price, prices.get(p.symbol, 0)) * 100 * p.quantity
            for p in self.option_positions if p.status == "OPEN" and p.option_type == "PUT"
        )

        open_puts = sum(1 for p in self.option_positions
                       if p.status == "OPEN" and p.option_type == "PUT")

        if open_puts < 3 and margin_avail_puts > 0:
            for symbol in ["SPY"]:
                spot = prices.get(symbol, 0)
                if spot <= 0:
                    continue

                T = self.target_dte_put / 365.0
                iv = self.vol_model.get_iv(self.target_dte_put, -self.put_delta_target)

                K_low, K_high = spot * 0.85, spot * 0.95
                for _ in range(10):
                    K_mid = (K_low + K_high) / 2.0
                    delta = bs_put_delta(spot, K_mid, 0.03, iv, T)
                    if delta < -self.put_delta_target:
                        K_low = K_mid
                    else:
                        K_high = K_mid

                strike = (K_low + K_high) / 2.0
                premium = bs_put_price(spot, strike, 0.03, iv, T)
                margin_needed = self._calc_margin_for_short_put(strike, premium, spot) * 100

                if margin_needed <= margin_avail_puts:
                    self.open_short_put(symbol, spot, strike, self.target_dte_put, current_date, quantity=1)

        # 买入LEAPS (30%资本配置)
        open_leaps = sum(1 for p in self.option_positions
                        if p.status == "OPEN" and p.option_type == "CALL")

        if not self.leaps_deployed and open_leaps == 0:
            for symbol in ["SPY"]:
                spot = prices.get(symbol, 0)
                if spot <= 0:
                    continue

                # 买入深虚值看涨期权 (Delta 0.70-0.80)
                T = self.target_dte_leaps / 365.0
                iv = self.vol_model.get_iv(self.target_dte_leaps, self.leaps_delta_target)

                # 计算行使价
                K_low, K_high = spot * 0.95, spot * 1.05
                for _ in range(10):
                    K_mid = (K_low + K_high) / 2.0
                    delta = bs_call_delta(spot, K_mid, 0.03, iv, T)
                    if delta < self.leaps_delta_target:
                        K_high = K_mid
                    else:
                        K_low = K_mid

                strike = (K_low + K_high) / 2.0

                # 计算可以买入的数量
                premium = bs_call_price(spot, strike, 0.03, iv, T)
                cost_per_contract = premium * 100 + self.commission_per_contract

                if cost_per_contract > 0 and self.leaps_capital > cost_per_contract:
                    max_quantity = int(self.leaps_capital / cost_per_contract)
                    if max_quantity > 0:
                        self.open_long_call(symbol, spot, strike, self.target_dte_leaps, current_date, quantity=max_quantity)
                        self.leaps_deployed = True

        # 季度重平衡 (简化)
        if self.last_rebalance is None:
            self.last_rebalance = current_date


# ==================== 基准策略 ====================

class BuyAndHoldStrategy(IncomeStrategy):
    """基准: SPY买入持有 + 月提取"""

    def __init__(self, initial_capital: float = 100000.0):
        super().__init__("BUY_AND_HOLD", initial_capital)
        self.shares_held = 0
        self.buy_price = 0
        self.initialized = False

    def process_day(self, current_date: datetime, prices: Dict[str, float]):
        """每日处理"""
        spot = prices.get("SPY", 0)

        if not self.initialized and spot > 0 and self.cash > 0:
            # 初始买入 (仅在第一天)
            self.shares_held = int((self.cash * 0.95) / spot)  # 保留5%现金
            cost = self.shares_held * spot * (1 + self.slippage_pct)
            self.cash -= cost
            self.buy_price = spot
            self.initialized = True

            self.trades.append({
                'date': current_date,
                'symbol': 'SPY',
                'type': 'BUY',
                'quantity': self.shares_held,
                'price': spot,
                'cost': cost,
            })


class FixedIncomeStrategy(IncomeStrategy):
    """基准: 5%年固定收益 (无回撤)"""

    def __init__(self, initial_capital: float = 100000.0):
        super().__init__("FIXED_INCOME", initial_capital)
        self.annual_rate = 0.05

    def process_day(self, current_date: datetime, prices: Dict[str, float]):
        """每日处理"""
        # 计算日利息
        daily_return = (1 + self.annual_rate) ** (1 / 252) - 1
        self.cash *= (1 + daily_return)


# ==================== 回测引擎 ====================

class BacktestEngine:
    """回测引擎"""

    def __init__(self, start_date: datetime, end_date: datetime,
                 initial_capital: float = 100000.0):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.monthly_withdrawal = 1500.0

    def run_backtest(self, strategy: IncomeStrategy, price_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """运行回测"""
        current_date = self.start_date
        last_withdrawal_month = None

        while current_date <= self.end_date:
            # 获取今日价格
            prices = {}
            for symbol, df in price_data.items():
                date_prices = df[df['date'] == current_date]
                if len(date_prices) > 0:
                    prices[symbol] = date_prices.iloc[0]['close']

            if len(prices) == 0:
                current_date += timedelta(days=1)
                continue

            # 处理月初提取 (每月仅一次)
            current_month = (current_date.year, current_date.month)
            if last_withdrawal_month != current_month and current_date.day == 1:
                strategy.cash = max(0, strategy.cash - self.monthly_withdrawal)
                last_withdrawal_month = current_month

            # 处理日事件
            strategy.process_day(current_date, prices)

            # 保存快照
            strategy.save_snapshot(current_date, prices)

            current_date += timedelta(days=1)

        # 生成结果报告
        return self._generate_report(strategy)

    def _generate_report(self, strategy: IncomeStrategy) -> pd.DataFrame:
        """生成回测报告"""
        report_data = []

        for snapshot in strategy.history:
            report_data.append({
                'date': snapshot.date,
                'nlv': snapshot.nlv,
                'cash': snapshot.cash,
                'margin_used': snapshot.margin_used,
            })

        return pd.DataFrame(report_data)


# ==================== 主程序 ====================

def main():
    """主程序"""
    print("=" * 80)
    print("期权收入策略回测系统 (Options Income Strategy Backtest)")
    print("=" * 80)

    # 参数设置
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2024, 12, 31)
    initial_capital = 100000.0

    print(f"\n回测参数:")
    print(f"  起始日期: {start_date.date()}")
    print(f"  结束日期: {end_date.date()}")
    print(f"  初始资本: ${initial_capital:,.0f}")
    print(f"  月提取: $1,500")
    print(f"  回测天数: {(end_date - start_date).days} 天")

    # 生成合成数据
    print("\n生成合成股票数据...")

    spy_gen = SyntheticDataGenerator(SyntheticDataParams(
        symbol="SPY",
        annual_return=0.10,
        annual_volatility=0.16,
        start_price=400.0,
    ))
    spy_data = spy_gen.generate_prices(start_date, (end_date - start_date).days + 1)

    qqq_gen = SyntheticDataGenerator(SyntheticDataParams(
        symbol="QQQ",
        annual_return=0.14,
        annual_volatility=0.20,
        start_price=320.0,
    ))
    qqq_data = qqq_gen.generate_prices(start_date, (end_date - start_date).days + 1)

    print(f"  SPY 数据点: {len(spy_data)}")
    print(f"  QQQ 数据点: {len(qqq_data)}")

    # 准备价格数据字典
    price_data = {
        'SPY': spy_data,
        'QQQ': qqq_data,
    }

    # 初始化引擎
    engine = BacktestEngine(start_date, end_date, initial_capital)

    # 运行三个策略
    print("\n运行策略回测...")

    strategies = [
        EnhancedShortPutStrategy(initial_capital),
        WheelStrategy(initial_capital),
        PutsAndLeapsStrategy(initial_capital),
        BuyAndHoldStrategy(initial_capital),
        FixedIncomeStrategy(initial_capital),
    ]

    results = {}
    for strategy in strategies:
        print(f"  回测 {strategy.name}...", end="", flush=True)
        result = engine.run_backtest(strategy, price_data)
        results[strategy.name] = {
            'result': result,
            'strategy': strategy,
        }
        print(" 完成")

    # 生成汇总报告
    print("\n" + "=" * 80)
    print("策略性能对比")
    print("=" * 80)

    summary_stats = []

    for name, data in results.items():
        result = data['result']
        strategy = data['strategy']

        if len(result) == 0:
            continue

        start_nlv = initial_capital
        end_nlv = result.iloc[-1]['nlv']
        total_return = (end_nlv - start_nlv) / start_nlv
        days = len(result)
        years = days / 365.0
        cagr = (end_nlv / start_nlv) ** (1 / years) - 1 if years > 0 else 0

        # 计算风险指标
        result['daily_return'] = result['nlv'].pct_change()
        sharpe = (result['daily_return'].mean() * 252) / (result['daily_return'].std() * math.sqrt(252)) if result['daily_return'].std() > 0 else 0

        # 最大回撤
        cummax = result['nlv'].cummax()
        drawdown = (result['nlv'] - cummax) / cummax
        max_drawdown = drawdown.min()

        # 月均收入
        monthly_data = result.set_index('date').resample('M')['nlv'].last()
        if len(monthly_data) > 1:
            monthly_returns = monthly_data.pct_change()[1:]
            avg_monthly_income = (monthly_returns.mean() * start_nlv)
        else:
            avg_monthly_income = 0

        summary_stats.append({
            '策略': name,
            '期末资本': f"${end_nlv:,.0f}",
            '总回报': f"{total_return*100:.2f}%",
            '年化收益': f"{cagr*100:.2f}%",
            'Sharpe比率': f"{sharpe:.2f}",
            '最大回撤': f"{max_drawdown*100:.2f}%",
            '月均收入': f"${avg_monthly_income:.0f}",
            '交易数': len(strategy.trades),
        })

    summary_df = pd.DataFrame(summary_stats)
    print("\n")
    print(summary_df.to_string(index=False))

    # 绘制净值曲线
    print("\n绘制净值曲线...")

    fig, ax = plt.subplots(figsize=(14, 7))

    colors = {
        'ENHANCED_SHORT_PUT': '#1f77b4',
        'WHEEL': '#ff7f0e',
        'PUTS_AND_LEAPS': '#2ca02c',
        'BUY_AND_HOLD': '#d62728',
        'FIXED_INCOME': '#9467bd',
    }

    for name, data in results.items():
        result = data['result']
        ax.plot(result['date'], result['nlv'], label=name, linewidth=2, color=colors.get(name, '#000000'))

    ax.set_xlabel('日期', fontsize=12)
    ax.set_ylabel('净资产价值 (NLV)', fontsize=12)
    ax.set_title('期权收入策略回测结果 - 净值曲线对比', fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)
    plt.tight_layout()

    output_file = Path(__file__).parent / "income_strategy_comparison.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"  保存图表: {output_file}")
    plt.close()

    # 生成建议
    print("\n" + "=" * 80)
    print("策略建议")
    print("=" * 80)

    best_strategy = max(summary_stats, key=lambda x: float(x['总回报'].rstrip('%')))

    print(f"\n基于回测结果的推荐:")
    print(f"  最佳策略: {best_strategy['策略']}")
    print(f"  期末资本: {best_strategy['期末资本']}")
    print(f"  年化收益: {best_strategy['年化收益']}")
    print(f"  月均收入: {best_strategy['月均收入']}")

    print(f"\n关键观察:")

    # 分析各策略
    for stat in summary_stats:
        strategy_name = stat['策略']
        total_return = float(stat['总回报'].rstrip('%'))
        monthly_income = float(stat['月均收入'].replace('$', '').replace(',', ''))

        if strategy_name == 'ENHANCED_SHORT_PUT':
            print(f"  - {strategy_name}: {'达到' if monthly_income >= 1500 else '未达到'} $1,500 月收入目标")
        elif strategy_name == 'PUTS_AND_LEAPS':
            print(f"  - {strategy_name}: LEAPS提供向上保护, 提高了长期增长潜力")
        elif strategy_name == 'BUY_AND_HOLD':
            print(f"  - {strategy_name}: 基准参考, 总回报 {total_return:.2f}%")

    print(f"\n回测完成!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
