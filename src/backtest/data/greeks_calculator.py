"""
Greeks Calculator - 基于 Black-Scholes 模型计算 IV 和 Greeks

从 EOD 数据计算隐含波动率和希腊字母，无需订阅 ThetaData STANDARD。

计算公式:
    IV: 使用 Brent 方法求解 BS_price(σ) = market_price
    Delta: ∂V/∂S = N(d1) for call, N(d1) - 1 for put
    Gamma: ∂²V/∂S² = φ(d1) / (S * σ * √T)
    Theta: ∂V/∂t (time decay per day)
    Vega: ∂V/∂σ = S * φ(d1) * √T
    Rho: ∂V/∂r = K * T * e^(-rT) * N(d2) for call

Usage:
    from src.backtest.data.greeks_calculator import GreeksCalculator

    calc = GreeksCalculator()

    # 计算单个期权的 IV 和 Greeks
    result = calc.calculate(
        option_price=5.50,
        spot=100.0,
        strike=105.0,
        tte=30/365,  # 30 days to expiry
        rate=0.05,
        is_call=True
    )
    print(f"IV: {result.iv:.2%}, Delta: {result.delta:.4f}")

    # 批量计算 (从 OptionEOD + StockEOD)
    enriched = calc.enrich_options(options_eod, stock_eod_map, rate=0.045)
"""

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

from scipy.optimize import brentq
from scipy.stats import norm

logger = logging.getLogger(__name__)


@dataclass
class GreeksResult:
    """Greeks 计算结果"""

    # 隐含波动率
    iv: float

    # 一阶 Greeks
    delta: float
    gamma: float
    theta: float  # 每日 theta (负值表示时间损耗)
    vega: float   # 每 1% IV 变化的价值变化
    rho: float

    # 计算状态
    is_valid: bool = True
    error_msg: str | None = None


@dataclass
class OptionWithGreeks:
    """期权数据 + 计算的 Greeks"""

    # 合约信息
    symbol: str
    expiration: date
    strike: float
    option_type: Literal["call", "put"]  # Call 或 Put
    date: date

    # 价格数据
    bid: float
    ask: float
    close: float
    volume: int

    # 标的价格
    underlying_price: float

    # Greeks (计算得出)
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float

    # 辅助字段
    mid_price: float
    dte: int  # days to expiry
    moneyness: float  # S/K


class GreeksCalculator:
    """Black-Scholes Greeks 计算器

    支持从 EOD 数据计算 IV 和 Greeks，无需付费数据订阅。

    Features:
        - IV 求解: Brent 方法，收敛快速稳定
        - Greeks 计算: Delta, Gamma, Theta, Vega, Rho
        - 批量处理: 从 OptionEOD + StockEOD 批量计算
        - 异常处理: 深度 OTM/ITM 期权的边界情况

    Note:
        - Theta 返回每日值 (已除以 365)
        - Vega 返回每 1% IV 变化的价值 (已除以 100)
    """

    # IV 求解边界
    IV_MIN = 0.001  # 0.1%
    IV_MAX = 5.0    # 500%

    # 最小时间价值 (避免除零)
    MIN_TTE = 1 / 365  # 1 day

    def __init__(self, dividend_yield: float = 0.0):
        """初始化计算器

        Args:
            dividend_yield: 股息率 (默认 0，适用于大多数个股期权)
        """
        self.q = dividend_yield

    def calculate(
        self,
        option_price: float,
        spot: float,
        strike: float,
        tte: float,
        rate: float,
        is_call: bool,
    ) -> GreeksResult:
        """计算单个期权的 IV 和 Greeks

        Args:
            option_price: 期权价格 (mid price)
            spot: 标的现价
            strike: 行权价
            tte: 到期时间 (年化，如 30天 = 30/365)
            rate: 无风险利率 (如 0.05 = 5%)
            is_call: True = Call, False = Put

        Returns:
            GreeksResult 包含 IV 和所有 Greeks
        """
        # 参数验证
        if option_price <= 0:
            return GreeksResult(
                iv=0, delta=0, gamma=0, theta=0, vega=0, rho=0,
                is_valid=False, error_msg="Invalid option price <= 0"
            )

        if spot <= 0 or strike <= 0:
            return GreeksResult(
                iv=0, delta=0, gamma=0, theta=0, vega=0, rho=0,
                is_valid=False, error_msg="Invalid spot or strike <= 0"
            )

        # 确保最小 TTE
        tte = max(tte, self.MIN_TTE)

        # 计算内在价值
        if is_call:
            intrinsic = max(0, spot - strike)
        else:
            intrinsic = max(0, strike - spot)

        # 检查套利边界
        time_value = option_price - intrinsic
        if time_value < -0.01:  # 允许小误差
            return GreeksResult(
                iv=0, delta=1.0 if is_call else -1.0, gamma=0, theta=0, vega=0, rho=0,
                is_valid=False, error_msg=f"Price below intrinsic value (TV={time_value:.4f})"
            )

        # 求解 IV
        try:
            iv = self._solve_iv(option_price, spot, strike, tte, rate, is_call)
        except ValueError as e:
            # IV 求解失败，返回边界值
            logger.debug(f"IV solve failed: {e}")
            return GreeksResult(
                iv=0, delta=0, gamma=0, theta=0, vega=0, rho=0,
                is_valid=False, error_msg=str(e)
            )

        # 计算 Greeks
        greeks = self._calculate_greeks(spot, strike, tte, rate, iv, is_call)

        return GreeksResult(
            iv=iv,
            delta=greeks["delta"],
            gamma=greeks["gamma"],
            theta=greeks["theta"],
            vega=greeks["vega"],
            rho=greeks["rho"],
            is_valid=True,
        )

    def _solve_iv(
        self,
        option_price: float,
        spot: float,
        strike: float,
        tte: float,
        rate: float,
        is_call: bool,
    ) -> float:
        """使用 Brent 方法求解隐含波动率

        Args:
            option_price: 期权市场价格
            spot: 标的现价
            strike: 行权价
            tte: 到期时间 (年)
            rate: 无风险利率
            is_call: Call/Put

        Returns:
            隐含波动率

        Raises:
            ValueError: 无法求解 IV
        """

        def objective(vol: float) -> float:
            """目标函数: BS价格 - 市场价格"""
            return self._bs_price(spot, strike, tte, rate, vol, is_call) - option_price

        # 检查边界值
        price_at_min = self._bs_price(spot, strike, tte, rate, self.IV_MIN, is_call)
        price_at_max = self._bs_price(spot, strike, tte, rate, self.IV_MAX, is_call)

        if option_price < price_at_min:
            # 价格低于最低 IV 对应的价格
            # 添加详细信息帮助调试
            moneyness = spot / strike
            intrinsic = max(0, spot - strike) if is_call else max(0, strike - spot)
            otm_itm = "ITM" if (is_call and spot > strike) or (not is_call and spot < strike) else "OTM"
            raise ValueError(
                f"Price too low for IV solve: price={option_price:.4f} < min_bs={price_at_min:.4f}, "
                f"spot={spot:.2f}, strike={strike:.2f}, tte={tte:.4f}, "
                f"{'CALL' if is_call else 'PUT'} {otm_itm}, moneyness={moneyness:.2%}, intrinsic={intrinsic:.2f}"
            )

        if option_price > price_at_max:
            # 价格高于最高 IV 对应的价格
            moneyness = spot / strike
            otm_itm = "ITM" if (is_call and spot > strike) or (not is_call and spot < strike) else "OTM"
            raise ValueError(
                f"Price too high for IV solve: price={option_price:.4f} > max_bs={price_at_max:.4f}, "
                f"spot={spot:.2f}, strike={strike:.2f}, tte={tte:.4f}, "
                f"{'CALL' if is_call else 'PUT'} {otm_itm}, moneyness={moneyness:.2%}"
            )

        # Brent 方法求解
        try:
            iv = brentq(objective, self.IV_MIN, self.IV_MAX, xtol=1e-6, maxiter=100)
            return iv
        except ValueError as e:
            raise ValueError(f"Brent solver failed: {e}")

    def _bs_price(
        self,
        spot: float,
        strike: float,
        tte: float,
        rate: float,
        vol: float,
        is_call: bool,
    ) -> float:
        """Black-Scholes 期权定价

        Args:
            spot: 标的现价 (S)
            strike: 行权价 (K)
            tte: 到期时间 (T, 年)
            rate: 无风险利率 (r)
            vol: 波动率 (σ)
            is_call: Call/Put

        Returns:
            理论期权价格
        """
        d1, d2 = self._d1_d2(spot, strike, tte, rate, vol)

        if is_call:
            price = (
                spot * math.exp(-self.q * tte) * norm.cdf(d1)
                - strike * math.exp(-rate * tte) * norm.cdf(d2)
            )
        else:
            price = (
                strike * math.exp(-rate * tte) * norm.cdf(-d2)
                - spot * math.exp(-self.q * tte) * norm.cdf(-d1)
            )

        return price

    def _d1_d2(
        self,
        spot: float,
        strike: float,
        tte: float,
        rate: float,
        vol: float,
    ) -> tuple[float, float]:
        """计算 d1 和 d2"""
        sqrt_t = math.sqrt(tte)
        d1 = (
            math.log(spot / strike) + (rate - self.q + 0.5 * vol * vol) * tte
        ) / (vol * sqrt_t)
        d2 = d1 - vol * sqrt_t
        return d1, d2

    def _calculate_greeks(
        self,
        spot: float,
        strike: float,
        tte: float,
        rate: float,
        vol: float,
        is_call: bool,
    ) -> dict[str, float]:
        """计算所有 Greeks

        Returns:
            包含 delta, gamma, theta, vega, rho 的字典
        """
        d1, d2 = self._d1_d2(spot, strike, tte, rate, vol)
        sqrt_t = math.sqrt(tte)

        # N(d1), N(d2), φ(d1)
        nd1 = norm.cdf(d1)
        nd2 = norm.cdf(d2)
        phi_d1 = norm.pdf(d1)

        # Delta
        if is_call:
            delta = math.exp(-self.q * tte) * nd1
        else:
            delta = math.exp(-self.q * tte) * (nd1 - 1)

        # Gamma (same for call and put)
        gamma = math.exp(-self.q * tte) * phi_d1 / (spot * vol * sqrt_t)

        # Vega (same for call and put)
        # 返回每 1% IV 变化的价值
        vega = spot * math.exp(-self.q * tte) * phi_d1 * sqrt_t / 100

        # Theta (per day)
        if is_call:
            theta = (
                -spot * math.exp(-self.q * tte) * phi_d1 * vol / (2 * sqrt_t)
                - rate * strike * math.exp(-rate * tte) * nd2
                + self.q * spot * math.exp(-self.q * tte) * nd1
            ) / 365
        else:
            theta = (
                -spot * math.exp(-self.q * tte) * phi_d1 * vol / (2 * sqrt_t)
                + rate * strike * math.exp(-rate * tte) * norm.cdf(-d2)
                - self.q * spot * math.exp(-self.q * tte) * norm.cdf(-d1)
            ) / 365

        # Rho (per 1% rate change)
        if is_call:
            rho = strike * tte * math.exp(-rate * tte) * nd2 / 100
        else:
            rho = -strike * tte * math.exp(-rate * tte) * norm.cdf(-d2) / 100

        return {
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "rho": rho,
        }

    def enrich_option( 
        self,
        option_price: float,
        spot: float,
        strike: float,
        expiration: date,
        as_of_date: date,
        rate: float,
        is_call: bool,
        symbol: str = "",
        bid: float = 0,
        ask: float = 0,
        volume: int = 0,
    ) -> OptionWithGreeks | None:
        """从原始数据创建带 Greeks 的期权对象

        Args:
            option_price: 期权价格 (建议用 mid)
            spot: 标的现价
            strike: 行权价
            expiration: 到期日
            as_of_date: 数据日期
            rate: 无风险利率
            is_call: Call/Put
            symbol: 标的代码
            bid: 买价
            ask: 卖价
            volume: 成交量

        Returns:
            OptionWithGreeks 或 None (计算失败时)
        """
        # 计算 DTE
        dte = (expiration - as_of_date).days
        if dte <= 0:
            return None

        tte = dte / 365.0

        # 计算 Greeks
        result = self.calculate(option_price, spot, strike, tte, rate, is_call)

        if not result.is_valid:
            return None

        return OptionWithGreeks(
            symbol=symbol,
            expiration=expiration,
            strike=strike,
            option_type="call" if is_call else "put",
            date=as_of_date,
            bid=bid,
            ask=ask,
            close=option_price,
            volume=volume,
            underlying_price=spot,
            iv=result.iv,
            delta=result.delta,
            gamma=result.gamma,
            theta=result.theta,
            vega=result.vega,
            rho=result.rho,
            mid_price=option_price,
            dte=dte,
            moneyness=spot / strike,
        )

    def enrich_options_batch(
        self,
        options: list,
        stock_prices: dict[date, float],
        rate: float = 0.045,
    ) -> list[OptionWithGreeks]:
        """批量计算期权的 Greeks

        Args:
            options: OptionEOD 列表
            stock_prices: {date: close_price} 标的价格字典
            rate: 无风险利率

        Returns:
            OptionWithGreeks 列表 (过滤掉计算失败的)
        """
        results = []
        failed_count = 0

        for opt in options:
            # 获取对应日期的标的价格
            spot = stock_prices.get(opt.date)
            if spot is None:
                failed_count += 1
                continue

            # 计算 mid price
            if opt.bid > 0 and opt.ask > 0:
                mid_price = (opt.bid + opt.ask) / 2
            elif opt.close > 0:
                mid_price = opt.close
            else:
                failed_count += 1
                continue

            # 计算 Greeks
            enriched = self.enrich_option(
                option_price=mid_price,
                spot=spot,
                strike=opt.strike,
                expiration=opt.expiration,
                as_of_date=opt.date,
                rate=rate,
                is_call=(opt.option_type == "call"),
                symbol=opt.symbol,
                bid=opt.bid,
                ask=opt.ask,
                volume=opt.volume,
            )

            if enriched:
                results.append(enriched)
            else:
                failed_count += 1

        if failed_count > 0:
            logger.info(
                f"Greeks calculation: {len(results)} success, {failed_count} failed"
            )

        return results
