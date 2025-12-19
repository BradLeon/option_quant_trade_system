#!/usr/bin/env python3
"""Calculation Engine Demo.

Demonstrates the quantitative indicators available in the engine layer.
"""

import argparse
import logging

from src.engine import (
    # Base types
    Position,
    TrendSignal,
    VixZone,
    # Volatility
    calc_hv,
    calc_iv_hv_ratio,
    calc_iv_rank,
    # Returns
    calc_annualized_return,
    calc_expected_return,
    calc_kelly,
    calc_max_drawdown,
    calc_sharpe_ratio,
    calc_win_rate,
    # Sentiment
    calc_pcr,
    calc_spy_trend,
    get_vix_zone,
    interpret_pcr,
    interpret_vix,
    # Fundamental
    evaluate_fundamentals,
    get_analyst_rating,
    # Technical
    calc_rsi,
    calc_support_distance,
    calc_support_level,
    interpret_rsi,
    # Portfolio
    calc_beta_weighted_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_vega,
    calc_prei,
    calc_roc,
    calc_sas,
    calc_tgr,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def demo_volatility():
    """Demonstrate volatility calculations."""
    logger.info("=" * 60)
    logger.info("Volatility Calculations Demo")
    logger.info("=" * 60)

    # Simulated price data (100 days)
    import random

    random.seed(42)
    prices = [100.0]
    for _ in range(99):
        change = random.gauss(0.0005, 0.015)  # ~0.05% daily mean, 1.5% std
        prices.append(prices[-1] * (1 + change))

    # Historical Volatility
    hv = calc_hv(prices, window=20)
    logger.info(f"20-day Historical Volatility: {hv:.2%}")

    # IV/HV Ratio (simulated IV)
    simulated_iv = 0.30
    ratio = calc_iv_hv_ratio(simulated_iv, hv)
    logger.info(f"IV: {simulated_iv:.2%}, HV: {hv:.2%}, IV/HV Ratio: {ratio:.2f}")
    if ratio > 1:
        logger.info("   -> Options are relatively expensive (IV > HV)")
    else:
        logger.info("   -> Options are relatively cheap (IV < HV)")

    # IV Rank
    historical_ivs = [0.20 + random.uniform(-0.05, 0.10) for _ in range(252)]
    current_iv = 0.28
    iv_rank = calc_iv_rank(current_iv, historical_ivs)
    logger.info(f"IV Rank (current IV={current_iv:.2%}): {iv_rank:.1f}%")


def demo_returns():
    """Demonstrate return and risk calculations."""
    logger.info("\n" + "=" * 60)
    logger.info("Return & Risk Calculations Demo")
    logger.info("=" * 60)

    # Simulated trade history
    trades = [150, -80, 200, -50, 180, -100, 250, -60, 120, -90]

    win_rate = calc_win_rate(trades)
    logger.info(f"Win Rate: {win_rate:.1%}")

    avg_win = sum(t for t in trades if t > 0) / sum(1 for t in trades if t > 0)
    avg_loss = abs(sum(t for t in trades if t < 0)) / sum(1 for t in trades if t < 0)
    expected = calc_expected_return(win_rate, avg_win, avg_loss)
    logger.info(f"Expected Return per Trade: ${expected:.2f}")

    kelly = calc_kelly(win_rate, avg_win / avg_loss)
    logger.info(f"Kelly Fraction: {kelly:.1%}")
    logger.info(f"   -> Recommended bet size: {kelly * 100:.1f}% of bankroll")

    # Simulated daily returns
    import random

    random.seed(42)
    daily_returns = [random.gauss(0.0008, 0.012) for _ in range(252)]

    ann_return = calc_annualized_return(daily_returns)
    logger.info(f"Annualized Return: {ann_return:.1%}")

    sharpe = calc_sharpe_ratio(daily_returns)
    logger.info(f"Sharpe Ratio: {sharpe:.2f}")

    # Equity curve for max drawdown
    equity = [100000]
    for r in daily_returns:
        equity.append(equity[-1] * (1 + r))
    max_dd = calc_max_drawdown(equity)
    logger.info(f"Maximum Drawdown: {max_dd:.1%}")


def demo_sentiment():
    """Demonstrate market sentiment indicators."""
    logger.info("\n" + "=" * 60)
    logger.info("Market Sentiment Demo")
    logger.info("=" * 60)

    # VIX interpretation
    for vix_value in [12, 18, 25, 35]:
        zone = get_vix_zone(vix_value)
        signal = interpret_vix(vix_value)
        logger.info(f"VIX = {vix_value}: Zone = {zone.value}, Signal = {signal.value}")

    # SPY Trend
    import random

    random.seed(42)
    uptrend_prices = [400 + i * 0.5 + random.uniform(-2, 2) for i in range(60)]
    trend = calc_spy_trend(uptrend_prices)
    logger.info(f"\nSPY Trend (uptrending prices): {trend.value}")

    downtrend_prices = [450 - i * 0.5 + random.uniform(-2, 2) for i in range(60)]
    trend = calc_spy_trend(downtrend_prices)
    logger.info(f"SPY Trend (downtrending prices): {trend.value}")

    # Put/Call Ratio
    put_vol, call_vol = 850000, 720000
    pcr = calc_pcr(put_vol, call_vol)
    pcr_signal = interpret_pcr(pcr)
    logger.info(f"\nPut/Call Ratio: {pcr:.3f}")
    logger.info(f"PCR Signal (contrarian): {pcr_signal.value}")


def demo_technical():
    """Demonstrate technical indicators."""
    logger.info("\n" + "=" * 60)
    logger.info("Technical Analysis Demo")
    logger.info("=" * 60)

    # RSI calculation
    import random

    random.seed(42)

    # Overbought scenario
    overbought_prices = [100 + i * 0.8 + random.uniform(-1, 1) for i in range(20)]
    rsi = calc_rsi(overbought_prices)
    rsi_signal = interpret_rsi(rsi)
    logger.info(f"RSI (overbought trend): {rsi:.1f} - Signal: {rsi_signal.value}")

    # Oversold scenario
    oversold_prices = [120 - i * 0.8 + random.uniform(-1, 1) for i in range(20)]
    rsi = calc_rsi(oversold_prices)
    rsi_signal = interpret_rsi(rsi)
    logger.info(f"RSI (oversold trend): {rsi:.1f} - Signal: {rsi_signal.value}")

    # Support and Resistance
    prices = [100, 105, 98, 110, 102, 108, 95, 112, 99, 115,
              103, 118, 97, 120, 100, 116, 98, 114, 96, 110]
    support = calc_support_level(prices, window=10)
    current_price = prices[-1]
    distance = calc_support_distance(current_price, support)
    logger.info(f"\nCurrent Price: ${current_price}")
    logger.info(f"Support Level (10-day): ${support}")
    logger.info(f"Distance to Support: {distance:.1%}")


def demo_portfolio():
    """Demonstrate portfolio calculations."""
    logger.info("\n" + "=" * 60)
    logger.info("Portfolio Risk Metrics Demo")
    logger.info("=" * 60)

    # Sample portfolio positions
    positions = [
        Position(
            symbol="AAPL Put",
            quantity=-5,  # Short 5 puts
            delta=0.30,
            gamma=0.02,
            theta=-0.15,
            vega=0.10,
            beta=1.2,
            market_value=250,
        ),
        Position(
            symbol="MSFT Put",
            quantity=-3,
            delta=0.25,
            gamma=0.018,
            theta=-0.12,
            vega=0.08,
            beta=1.1,
            market_value=180,
        ),
        Position(
            symbol="SPY Call",
            quantity=2,
            delta=0.55,
            gamma=0.015,
            theta=-0.08,
            vega=0.12,
            beta=1.0,
            market_value=500,
        ),
    ]

    # Portfolio Greeks
    total_theta = calc_portfolio_theta(positions)
    total_vega = calc_portfolio_vega(positions)
    total_gamma = calc_portfolio_gamma(positions)

    logger.info("Portfolio Greeks:")
    logger.info(f"   Total Theta: ${total_theta:.2f}/day")
    logger.info(f"   Total Vega: ${total_vega:.2f}")
    logger.info(f"   Total Gamma: {total_gamma:.4f}")

    # TGR
    tgr = calc_tgr(total_theta, total_gamma)
    logger.info(f"   Theta/Gamma Ratio: {tgr:.2f}")

    # ROC
    profit = 450
    capital = 5000
    roc = calc_roc(profit, capital)
    logger.info(f"\nReturn on Capital: {roc:.1%}")

    # Strategy Allocation Score
    allocations = [0.40, 0.35, 0.25]  # 3 strategies
    sas = calc_sas(allocations)
    logger.info(f"Strategy Allocation Score: {sas:.1f}/100")

    # Portfolio Risk Exposure Index
    exposures = {
        "delta": 0.3,  # Moderate directional exposure
        "gamma": -0.2,  # Short gamma
        "theta": 0.4,  # Positive theta (selling options)
        "vega": -0.3,  # Short volatility
        "concentration": 0.35,  # Some concentration
    }
    prei = calc_prei(exposures)
    logger.info(f"Portfolio Risk Exposure Index: {prei:.1f}/100")


def main():
    """Run all demos."""
    parser = argparse.ArgumentParser(description="Calculation Engine Demo")
    parser.add_argument(
        "--module",
        choices=["volatility", "returns", "sentiment", "technical", "portfolio", "all"],
        default="all",
        help="Which module to demo",
    )
    args = parser.parse_args()

    logger.info("Option Quant Trade System - Calculation Engine Demo")
    logger.info("=" * 60)

    if args.module in ("volatility", "all"):
        demo_volatility()

    if args.module in ("returns", "all"):
        demo_returns()

    if args.module in ("sentiment", "all"):
        demo_sentiment()

    if args.module in ("technical", "all"):
        demo_technical()

    if args.module in ("portfolio", "all"):
        demo_portfolio()

    logger.info("\n" + "=" * 60)
    logger.info("Demo completed!")


if __name__ == "__main__":
    main()
