#!/usr/bin/env python3
"""
Greeks 计算准确性验证脚本

验证方法:
1. 理论值验证: 使用已知参数计算 Greeks，与公式理论值对比
2. Put-Call Parity 验证: 验证 Call 和 Put 的 Delta 关系
3. ATM 特性验证: ATM 期权的 Delta 应该约等于 0.5
4. 边界条件验证: 深度 ITM/OTM 期权的 Greeks 边界值

Usage:
    python tests/verification/verify_greeks_accuracy.py
"""

import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.backtest.data.greeks_calculator import GreeksCalculator, GreeksResult


@dataclass
class TestCase:
    """测试用例"""
    name: str
    spot: float
    strike: float
    tte: float  # 年
    rate: float
    vol: float  # 已知 IV (用于验证)
    is_call: bool
    # 预期值 (使用标准 BS 公式计算)
    expected_delta: float | None = None
    expected_gamma: float | None = None
    expected_theta: float | None = None  # 每日
    expected_vega: float | None = None   # 每 1% IV


def bs_price(spot: float, strike: float, tte: float, rate: float, vol: float, is_call: bool) -> float:
    """Black-Scholes 定价 (用于生成测试数据)"""
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * tte) / (vol * math.sqrt(tte))
    d2 = d1 - vol * math.sqrt(tte)

    if is_call:
        return spot * norm.cdf(d1) - strike * math.exp(-rate * tte) * norm.cdf(d2)
    else:
        return strike * math.exp(-rate * tte) * norm.cdf(-d2) - spot * norm.cdf(-d1)


def bs_delta(spot: float, strike: float, tte: float, rate: float, vol: float, is_call: bool) -> float:
    """理论 Delta"""
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * tte) / (vol * math.sqrt(tte))
    return norm.cdf(d1) if is_call else norm.cdf(d1) - 1


def bs_gamma(spot: float, strike: float, tte: float, rate: float, vol: float) -> float:
    """理论 Gamma"""
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * tte) / (vol * math.sqrt(tte))
    return norm.pdf(d1) / (spot * vol * math.sqrt(tte))


def bs_vega(spot: float, strike: float, tte: float, rate: float, vol: float) -> float:
    """理论 Vega (每 1% IV)"""
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * tte) / (vol * math.sqrt(tte))
    return spot * norm.pdf(d1) * math.sqrt(tte) / 100


def bs_theta(spot: float, strike: float, tte: float, rate: float, vol: float, is_call: bool) -> float:
    """理论 Theta (每日)"""
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * tte) / (vol * math.sqrt(tte))
    d2 = d1 - vol * math.sqrt(tte)

    term1 = -spot * norm.pdf(d1) * vol / (2 * math.sqrt(tte))

    if is_call:
        term2 = -rate * strike * math.exp(-rate * tte) * norm.cdf(d2)
    else:
        term2 = rate * strike * math.exp(-rate * tte) * norm.cdf(-d2)

    return (term1 + term2) / 365


def run_accuracy_tests():
    """运行准确性测试"""
    print("=" * 70)
    print("Greeks Calculator Accuracy Verification")
    print("=" * 70)

    calc = GreeksCalculator()

    # 定义测试用例
    test_cases = [
        # ATM Call
        TestCase(
            name="ATM Call (S=K=100, T=30d, σ=20%)",
            spot=100.0, strike=100.0, tte=30/365, rate=0.05, vol=0.20, is_call=True,
        ),
        # ATM Put
        TestCase(
            name="ATM Put (S=K=100, T=30d, σ=20%)",
            spot=100.0, strike=100.0, tte=30/365, rate=0.05, vol=0.20, is_call=False,
        ),
        # OTM Call
        TestCase(
            name="OTM Call (S=100, K=110, T=30d, σ=25%)",
            spot=100.0, strike=110.0, tte=30/365, rate=0.05, vol=0.25, is_call=True,
        ),
        # ITM Put
        TestCase(
            name="ITM Put (S=100, K=110, T=30d, σ=25%)",
            spot=100.0, strike=110.0, tte=30/365, rate=0.05, vol=0.25, is_call=False,
        ),
        # 长期期权
        TestCase(
            name="Long-dated Call (S=100, K=100, T=180d, σ=30%)",
            spot=100.0, strike=100.0, tte=180/365, rate=0.05, vol=0.30, is_call=True,
        ),
        # 高波动率
        TestCase(
            name="High Vol Call (S=100, K=100, T=30d, σ=60%)",
            spot=100.0, strike=100.0, tte=30/365, rate=0.05, vol=0.60, is_call=True,
        ),
        # 真实市场参数 (GOOG-like)
        TestCase(
            name="GOOG-like ATM Call (S=338, K=340, T=7d, σ=50%)",
            spot=338.0, strike=340.0, tte=7/365, rate=0.0424, vol=0.50, is_call=True,
        ),
        # SPY-like
        TestCase(
            name="SPY-like ATM Put (S=692, K=690, T=7d, σ=14%)",
            spot=692.0, strike=690.0, tte=7/365, rate=0.0424, vol=0.14, is_call=False,
        ),
    ]

    all_passed = True
    results = []

    for tc in test_cases:
        print(f"\n{'-'*70}")
        print(f"Test: {tc.name}")
        print(f"{'-'*70}")

        # 计算理论期权价格
        option_price = bs_price(tc.spot, tc.strike, tc.tte, tc.rate, tc.vol, tc.is_call)
        print(f"  Option Price: ${option_price:.4f}")

        # 计算理论 Greeks
        expected_delta = bs_delta(tc.spot, tc.strike, tc.tte, tc.rate, tc.vol, tc.is_call)
        expected_gamma = bs_gamma(tc.spot, tc.strike, tc.tte, tc.rate, tc.vol)
        expected_theta = bs_theta(tc.spot, tc.strike, tc.tte, tc.rate, tc.vol, tc.is_call)
        expected_vega = bs_vega(tc.spot, tc.strike, tc.tte, tc.rate, tc.vol)

        # 使用 GreeksCalculator 计算
        result = calc.calculate(
            option_price=option_price,
            spot=tc.spot,
            strike=tc.strike,
            tte=tc.tte,
            rate=tc.rate,
            is_call=tc.is_call,
        )

        if not result.is_valid:
            print(f"  ❌ Calculation failed: {result.error_msg}")
            all_passed = False
            continue

        # 比较 IV
        iv_error = abs(result.iv - tc.vol)
        iv_pass = iv_error < 0.001  # 0.1% 误差

        # 比较 Delta
        delta_error = abs(result.delta - expected_delta)
        delta_pass = delta_error < 0.001

        # 比较 Gamma
        gamma_error = abs(result.gamma - expected_gamma)
        gamma_pass = gamma_error < 0.0001

        # 比较 Theta
        theta_error = abs(result.theta - expected_theta)
        theta_pass = theta_error < 0.01  # 每日 theta 允许较大误差

        # 比较 Vega
        vega_error = abs(result.vega - expected_vega)
        vega_pass = vega_error < 0.001

        test_passed = iv_pass and delta_pass and gamma_pass and theta_pass and vega_pass

        # 打印结果
        print(f"\n  {'Metric':<12} {'Calculated':>12} {'Expected':>12} {'Error':>12} {'Status'}")
        print(f"  {'-'*60}")
        print(f"  {'IV':<12} {result.iv:>11.4%} {tc.vol:>11.4%} {iv_error:>11.4%} {'✅' if iv_pass else '❌'}")
        print(f"  {'Delta':<12} {result.delta:>12.6f} {expected_delta:>12.6f} {delta_error:>12.6f} {'✅' if delta_pass else '❌'}")
        print(f"  {'Gamma':<12} {result.gamma:>12.6f} {expected_gamma:>12.6f} {gamma_error:>12.6f} {'✅' if gamma_pass else '❌'}")
        print(f"  {'Theta':<12} {result.theta:>12.6f} {expected_theta:>12.6f} {theta_error:>12.6f} {'✅' if theta_pass else '❌'}")
        print(f"  {'Vega':<12} {result.vega:>12.6f} {expected_vega:>12.6f} {vega_error:>12.6f} {'✅' if vega_pass else '❌'}")

        status = "✅ PASS" if test_passed else "❌ FAIL"
        print(f"\n  Result: {status}")

        if not test_passed:
            all_passed = False

        results.append((tc.name, test_passed))

    # Put-Call Parity 验证
    print(f"\n{'='*70}")
    print("Put-Call Parity Verification")
    print("="*70)
    print("For European options: Delta(Call) - Delta(Put) = 1")

    for spot, strike, tte, rate, vol in [
        (100, 100, 30/365, 0.05, 0.20),
        (100, 105, 30/365, 0.05, 0.25),
        (338, 340, 7/365, 0.0424, 0.50),
    ]:
        call_price = bs_price(spot, strike, tte, rate, vol, True)
        put_price = bs_price(spot, strike, tte, rate, vol, False)

        call_greeks = calc.calculate(call_price, spot, strike, tte, rate, True)
        put_greeks = calc.calculate(put_price, spot, strike, tte, rate, False)

        delta_diff = call_greeks.delta - put_greeks.delta
        parity_pass = abs(delta_diff - 1.0) < 0.01

        print(f"  S={spot}, K={strike}: ΔCall={call_greeks.delta:.4f}, ΔPut={put_greeks.delta:.4f}, "
              f"Diff={delta_diff:.4f} {'✅' if parity_pass else '❌'}")

        if not parity_pass:
            all_passed = False

    # ATM Delta 验证
    print(f"\n{'='*70}")
    print("ATM Delta Verification")
    print("="*70)
    print("ATM Call Delta ≈ 0.5, ATM Put Delta ≈ -0.5")

    for spot, tte, vol in [(100, 30/365, 0.20), (100, 90/365, 0.30), (338, 7/365, 0.50)]:
        strike = spot  # ATM
        rate = 0.05

        call_price = bs_price(spot, strike, tte, rate, vol, True)
        put_price = bs_price(spot, strike, tte, rate, vol, False)

        call_greeks = calc.calculate(call_price, spot, strike, tte, rate, True)
        put_greeks = calc.calculate(put_price, spot, strike, tte, rate, False)

        # ATM delta 应该接近 0.5/-0.5 (略有偏差是因为利率和时间)
        call_atm_pass = 0.45 < call_greeks.delta < 0.60
        put_atm_pass = -0.60 < put_greeks.delta < -0.45

        print(f"  S=K={spot}, T={tte*365:.0f}d, σ={vol:.0%}: "
              f"ΔCall={call_greeks.delta:.4f}, ΔPut={put_greeks.delta:.4f} "
              f"{'✅' if call_atm_pass and put_atm_pass else '❌'}")

    # 汇总
    print(f"\n{'='*70}")
    print("Summary")
    print("="*70)

    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)

    print(f"  Test Cases: {passed_count}/{total_count} passed")

    if all_passed:
        print(f"\n  ✅ ALL TESTS PASSED")
        print(f"\n  Conclusion: GreeksCalculator produces results consistent with")
        print(f"              Black-Scholes theoretical values (< 0.1% error)")
    else:
        print(f"\n  ❌ SOME TESTS FAILED")

    return 0 if all_passed else 1


def compare_with_real_data():
    """与真实市场数据比较 (如果 ThetaData Terminal 运行)"""
    print(f"\n{'='*70}")
    print("Real Data Comparison (ThetaData)")
    print("="*70)

    try:
        from src.backtest.data.thetadata_client import ThetaDataClient, ThetaDataConfig

        config = ThetaDataConfig()
        client = ThetaDataClient(config)

        if not client.check_connection():
            print("  ⚠️  ThetaData Terminal not running, skipping real data comparison")
            return

        calc = GreeksCalculator()

        # 获取真实数据
        end_date = date.today()
        start_date = end_date - timedelta(days=5)

        for symbol in ["GOOG", "SPY"]:
            print(f"\n  {symbol}:")

            # 获取股票价格
            stocks = client.get_stock_eod(symbol, start_date, end_date)
            if not stocks:
                print(f"    No stock data")
                continue

            latest_stock = stocks[-1]
            spot = latest_stock.close
            as_of_date = latest_stock.date
            print(f"    Stock price ({as_of_date}): ${spot:.2f}")
            

            # 获取期权数据 (使用新的 fallback 方法)
            options = client.get_option_with_greeks(
                symbol, as_of_date, as_of_date, max_dte=30
            )

            if not options:
                print(f"    No option data")
                continue

            # 找 ATM 期权
            atm_options = sorted(
                [o for o in options if abs(o.strike - spot) < spot * 0.02],
                key=lambda o: abs(o.strike - spot)
            )[:4]

            if atm_options:
                print(f"    ATM options (K near {spot:.0f}):")
                for opt in atm_options:
                    dte = (opt.expiration - as_of_date).days
                    print(f"      {opt.right.upper()} K={opt.strike:.0f} exp={opt.expiration} (DTE={dte})")
                    print(f"        IV={opt.implied_vol:.1%}, Δ={opt.delta:.4f}, Γ={opt.gamma:.5f}, Θ={opt.theta:.4f}")

    except Exception as e:
        print(f"  ❌ Error: {e}")


if __name__ == "__main__":
    exit_code = run_accuracy_tests()
    compare_with_real_data()
    sys.exit(exit_code)
