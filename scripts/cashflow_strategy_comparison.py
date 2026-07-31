#!/usr/bin/env python3
"""
现金流策略回测对比 v2 - Cash Flow Strategy Comparison
======================================================

目标: $100,000 本金, ≥$1,500/月收益, 每月出金$1,500, 最大回撤<SPY

修复 v1 的问题:
  1. Short option 策略拆分为两段: 2023-07~2026-02 (有真实期权数据)
  2. LEAPS/Benchmark 保持 2016-06~2026-02 (合成数据)
  3. 修正 BacktestMetrics 属性名 (annualized_return, volatility)
  4. 手动从 daily_snapshots 提取出金数据 (metrics序列化丢失)
  5. 新增 Bull Put Spread 策略 (定义风险, 更适合低回撤目标)

运行:
  cd /path/to/option_quant_trade_system
  uv run python scripts/cashflow_strategy_comparison.py
"""

import json
import logging
import sys
import traceback
from datetime import date
from dataclasses import dataclass
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.pipeline import BacktestPipeline, PipelineResult
from src.engine.models.enums import StrategyType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cashflow_comparison")

# ============================================================
# 配置常量
# ============================================================
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 1_500.0

# 两个日期范围:
# - 短期权策略需要真实期权链数据 (2023-07+)
# - LEAPS/股票策略可以用合成数据 (2016+)
SHORT_OPTION_START = date(2023, 7, 1)   # 真实期权数据起始
SHORT_OPTION_END = date(2026, 2, 1)

LONG_START = date(2016, 6, 1)           # 合成数据起始
LONG_END = date(2026, 2, 1)

DATA_DIR = "/Volumes/ORICO/option_quant"
REPORT_DIR = "reports"
BENCHMARK = "SPY"

# 短期回测的月度出金按比例调整说明:
# $1,500/月 × 31个月 (2023-07 ~ 2026-02) = $46,500
# $1,500/月 × 116个月 (2016-06 ~ 2026-02) = $174,000


# ============================================================
# 策略定义
# ============================================================

@dataclass
class StrategyTestCase:
    name: str
    description: str
    config: BacktestConfig
    result: PipelineResult | None = None
    error: str | None = None


def create_strategy_a_short_put_spy() -> StrategyTestCase:
    """方案A: Short Put on SPY (真实数据期, 2.5年)"""
    config = BacktestConfig(
        name="CASHFLOW_A_SHORT_PUT_SPY",
        description="Short Put SPY - Premium income (real option data)",
        start_date=SHORT_OPTION_START,
        end_date=SHORT_OPTION_END,
        symbols=["SPY"],
        strategy_types=[StrategyType.SHORT_PUT],
        strategy_version="short_options_without_expire_itm_stock_trade",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        max_margin_utilization=0.85,
        max_positions=10,
        max_new_positions_per_day=2,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
        screening_overrides={
            "contract_filter": {
                "dte_range": [14, 45],
                "metrics": {
                    "min_expected_roc": 0.05,
                    "min_tgr": 0.3,
                },
            },
        },
        monitoring_overrides={
            "take_profit": {"enabled": True, "threshold": 0.65},
        },
    )
    return StrategyTestCase(
        name="A: Short Put SPY (2.5yr)",
        description="卖SPY看跌, 85%margin, 65%止盈 [2023-07~2026-02]",
        config=config,
    )


def create_strategy_a2_short_put_qqq() -> StrategyTestCase:
    """方案A2: Short Put on QQQ"""
    config = BacktestConfig(
        name="CASHFLOW_A2_SHORT_PUT_QQQ",
        description="Short Put QQQ - Higher IV premium (real option data)",
        start_date=SHORT_OPTION_START,
        end_date=SHORT_OPTION_END,
        symbols=["QQQ"],
        strategy_types=[StrategyType.SHORT_PUT],
        strategy_version="short_options_without_expire_itm_stock_trade",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        max_margin_utilization=0.85,
        max_positions=10,
        max_new_positions_per_day=2,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
        screening_overrides={
            "contract_filter": {
                "dte_range": [14, 45],
                "metrics": {
                    "min_expected_roc": 0.05,
                    "min_tgr": 0.3,
                },
            },
        },
        monitoring_overrides={
            "take_profit": {"enabled": True, "threshold": 0.65},
        },
    )
    return StrategyTestCase(
        name="A2: Short Put QQQ (2.5yr)",
        description="卖QQQ看跌, IV更高 [2023-07~2026-02]",
        config=config,
    )


def create_strategy_b_wheel() -> StrategyTestCase:
    """方案B: Wheel策略 (允许行权, 真实数据期)"""
    config = BacktestConfig(
        name="CASHFLOW_B_WHEEL",
        description="Wheel Strategy - Sell Put/Call cycle with assignment",
        start_date=SHORT_OPTION_START,
        end_date=SHORT_OPTION_END,
        symbols=["SPY"],
        strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
        strategy_version="short_options_with_expire_itm_stock_trade",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        max_margin_utilization=0.80,
        max_positions=10,
        max_new_positions_per_day=2,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
        screening_overrides={
            "contract_filter": {
                "dte_range": [21, 45],
                "metrics": {
                    "min_expected_roc": 0.05,
                    "min_tgr": 0.3,
                },
            },
        },
    )
    return StrategyTestCase(
        name="B: Wheel SPY (2.5yr)",
        description="Sell Put→持股→Sell Call循环 [2023-07~2026-02]",
        config=config,
    )


def create_strategy_d_bull_put_spread() -> StrategyTestCase:
    """方案D: Bull Put Spread (定义风险, 真实数据期)

    与 naked short put 不同, spread 有明确的最大亏损上限
    更适合追求低回撤的目标
    """
    config = BacktestConfig(
        name="CASHFLOW_D_BULL_PUT_SPREAD",
        description="Bull Put Spread - Defined risk credit spread",
        start_date=SHORT_OPTION_START,
        end_date=SHORT_OPTION_END,
        symbols=["SPY"],
        strategy_types=[StrategyType.SHORT_PUT],
        strategy_version="bull_put_spread",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        max_margin_utilization=0.85,
        max_positions=10,
        max_new_positions_per_day=2,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
    )
    return StrategyTestCase(
        name="D: Bull Put Spread (2.5yr)",
        description="SPY牛市看跌价差, 有限风险 [2023-07~2026-02]",
        config=config,
    )


def create_strategy_c_leaps_vol_target() -> StrategyTestCase:
    """方案C: LEAPS + Vol Target (合成数据, 10年)"""
    config = BacktestConfig(
        name="CASHFLOW_C_LEAPS_VOL",
        description="LEAPS + Volatility Targeting (synthetic data)",
        start_date=LONG_START,
        end_date=LONG_END,
        symbols=["SPY"],
        strategy_types=[StrategyType.LONG_CALL],
        strategy_version="spy_leaps_only_vol_target",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        max_margin_utilization=0.90,
        max_positions=5,
        max_new_positions_per_day=1,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
    )
    return StrategyTestCase(
        name="C: LEAPS+VolTarget (10yr)",
        description="LEAPS Call + 波动率目标 [2016-06~2026-02]",
        config=config,
    )


def create_benchmark_spy_bh() -> StrategyTestCase:
    """基准: SPY Buy & Hold + SMA200"""
    config = BacktestConfig(
        name="BENCHMARK_SPY_BH",
        description="SPY Buy and Hold with SMA200 timing",
        start_date=LONG_START,
        end_date=LONG_END,
        symbols=["SPY"],
        strategy_types=[StrategyType.NOT_OPTION],
        strategy_version="spy_buy_and_hold_sma_timing",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
    )
    return StrategyTestCase(
        name="Benchmark: SPY+SMA200 (10yr)",
        description="SPY买入持有+SMA200择时 [2016-06~2026-02]",
        config=config,
    )


def create_benchmark_spy_bh_short() -> StrategyTestCase:
    """基准: SPY Buy & Hold (短期, 与short option同期对比)"""
    config = BacktestConfig(
        name="BENCHMARK_SPY_BH_SHORT",
        description="SPY Buy and Hold (short period, for option comparison)",
        start_date=SHORT_OPTION_START,
        end_date=SHORT_OPTION_END,
        symbols=["SPY"],
        strategy_types=[StrategyType.NOT_OPTION],
        strategy_version="spy_buy_and_hold_sma_timing",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        data_dir=DATA_DIR,
        benchmark_symbol=BENCHMARK,
        skip_market_check=True,
    )
    return StrategyTestCase(
        name="Benchmark: SPY+SMA (2.5yr)",
        description="SPY买入持有短期基准 [2023-07~2026-02]",
        config=config,
    )


# ============================================================
# 运行与分析
# ============================================================

def run_single(tc: StrategyTestCase) -> StrategyTestCase:
    """运行单个策略"""
    logger.info(f"\n{'='*70}")
    logger.info(f"Running: {tc.name}")
    logger.info(f"{'='*70}")

    try:
        pipeline = BacktestPipeline(tc.config)
        tc.result = pipeline.run(
            skip_data_check=True,
            generate_report=True,
            report_dir=REPORT_DIR,
        )

        m = tc.result.metrics
        bt = tc.result.backtest_result
        logger.info(f"✅ {tc.name}: trades={bt.total_trades}, NLV=${bt.final_nlv:,.0f}, return={bt.total_return_pct:.2%}")
        if m.annualized_return is not None:
            logger.info(f"   Annualized={m.annualized_return:.2%}, MaxDD={m.max_drawdown}, Sharpe={m.sharpe_ratio}")
    except Exception as e:
        tc.error = str(e)
        logger.error(f"❌ {tc.name}: {e}")
        traceback.print_exc()

    return tc


def extract_metrics(tc: StrategyTestCase) -> dict:
    """提取关键指标 (手动计算出金相关指标)"""
    if tc.error or not tc.result:
        return {"name": tc.name, "description": tc.description, "error": tc.error or "No result"}

    m = tc.result.metrics
    bt = tc.result.backtest_result

    # 手动从 daily_snapshots 计算出金总额 (metrics序列化可能丢失)
    total_withdrawn = 0.0
    for snap in bt.daily_snapshots:
        if hasattr(snap, 'withdrawal_amount'):
            total_withdrawn += snap.withdrawal_amount

    # 如果 metrics 有数据就用 metrics 的
    if m.total_withdrawals and m.total_withdrawals > 0:
        total_withdrawn = m.total_withdrawals

    # 时间计算
    total_days = (bt.end_date - bt.start_date).days
    total_months = total_days / 30.44

    # 总价值创造 = 最终NLV + 累计出金 - 初始本金
    total_value_created = bt.final_nlv + total_withdrawn - bt.initial_capital
    monthly_value_created = total_value_created / total_months if total_months > 0 else 0

    # 出金调整后收益率
    wa_return = (bt.final_nlv + total_withdrawn - bt.initial_capital) / bt.initial_capital if bt.initial_capital > 0 else 0

    return {
        "name": tc.name,
        "description": tc.description,
        "period": f"{bt.start_date} ~ {bt.end_date}",
        "months": round(total_months, 1),
        # 收益
        "initial_capital": bt.initial_capital,
        "final_nlv": bt.final_nlv,
        "total_return_pct": bt.total_return_pct,
        "annualized_return_pct": m.annualized_return if m.annualized_return else 0.0,
        # 风险
        "max_drawdown_pct": m.max_drawdown if m.max_drawdown else 0.0,
        "sharpe_ratio": m.sharpe_ratio if m.sharpe_ratio else 0.0,
        "volatility": m.volatility if m.volatility else 0.0,
        # 交易
        "total_trades": bt.total_trades,
        "win_rate": m.win_rate if m.win_rate else 0.0,
        "profit_factor": bt.profit_factor,
        # 现金流 (核心!)
        "total_withdrawals": total_withdrawn,
        "withdrawal_adjusted_return_pct": wa_return,
        "total_value_created": total_value_created,
        "monthly_value_created": monthly_value_created,
        "meets_monthly_target": monthly_value_created >= MONTHLY_WITHDRAWAL,
        # 费用
        "total_fees": bt.total_commission + bt.total_slippage,
    }


def generate_report(test_cases: list[StrategyTestCase]) -> str:
    """生成对比报告"""
    all_m = [extract_metrics(tc) for tc in test_cases]

    # 保存 JSON
    json_path = Path(REPORT_DIR) / "cashflow_comparison_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_m, f, ensure_ascii=False, indent=2, default=str)

    # 文本报告
    lines = []
    lines.append("=" * 90)
    lines.append("  现金流策略回测对比报告  |  Cash Flow Strategy Comparison v2")
    lines.append("=" * 90)
    lines.append(f"  初始资金: ${INITIAL_CAPITAL:,.0f}  |  月度出金: ${MONTHLY_WITHDRAWAL:,.0f}")
    lines.append(f"  短期权策略: {SHORT_OPTION_START} ~ {SHORT_OPTION_END} (真实期权数据)")
    lines.append(f"  LEAPS/基准: {LONG_START} ~ {LONG_END} (含合成数据)")
    lines.append(f"  目标: 月均创值 ≥ ${MONTHLY_WITHDRAWAL:,.0f}")
    lines.append("")

    # 表头
    lines.append("-" * 90)
    lines.append(f"{'策略':<30} {'月数':>5} {'年化':>8} {'MaxDD':>8} {'Sharpe':>7} {'胜率':>6} {'月创值':>10} {'达标':>4}")
    lines.append("-" * 90)

    for d in all_m:
        if d.get("error"):
            lines.append(f"{d['name']:<30} {'ERROR: ' + d['error'][:50]}")
            continue
        ok = "✅" if d["meets_monthly_target"] else "❌"
        ann = d["annualized_return_pct"]
        mdd = d["max_drawdown_pct"]
        sr = d["sharpe_ratio"]
        wr = d["win_rate"]
        mv = d["monthly_value_created"]
        mo = d["months"]
        lines.append(
            f"{d['name']:<30} {mo:>5.0f} {ann:>7.1%} {mdd:>7.1%} {sr:>6.2f} {wr:>5.0%} ${mv:>8,.0f} {ok:>4}"
        )

    lines.append("-" * 90)
    lines.append("")

    # 详细
    lines.append("📊 详细数据:")
    for d in all_m:
        if d.get("error"):
            continue
        lines.append(f"\n  [{d['name']}]  {d['period']}")
        lines.append(f"    终值NLV: ${d['final_nlv']:,.0f}  |  累计出金: ${d['total_withdrawals']:,.0f}  |  总创值: ${d['total_value_created']:,.0f}")
        lines.append(f"    交易: {d['total_trades']}笔  |  费用: ${d['total_fees']:,.0f}  |  出金调整收益: {d['withdrawal_adjusted_return_pct']:.1%}")

    # 结论
    lines.append("\n" + "=" * 90)
    lines.append("📋 结论:")
    valid = [d for d in all_m if not d.get("error") and d["total_trades"] > 0]
    if valid:
        by_sharpe = sorted(valid, key=lambda x: x["sharpe_ratio"], reverse=True)
        by_value = sorted(valid, key=lambda x: x["monthly_value_created"], reverse=True)
        meeting = [d for d in valid if d["meets_monthly_target"]]
        lines.append(f"  Sharpe最优: {by_sharpe[0]['name']} ({by_sharpe[0]['sharpe_ratio']:.2f})")
        lines.append(f"  月创值最高: {by_value[0]['name']} (${by_value[0]['monthly_value_created']:,.0f}/月)")
        if meeting:
            lines.append(f"  ✅ 达标策略: {', '.join(d['name'] for d in meeting)}")
        else:
            lines.append(f"  ⚠️ 无策略达标, 最接近: {by_value[0]['name']} (${by_value[0]['monthly_value_created']:,.0f}/月)")
    else:
        lines.append("  ⚠️ 没有有效的策略结果")
    lines.append("=" * 90)

    summary = "\n".join(lines)

    summary_path = Path(REPORT_DIR) / "cashflow_comparison_summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)

    return summary


# ============================================================
# Main
# ============================================================

def main():
    print("\n" + "=" * 70)
    print("  Cash Flow Strategy Comparison v2")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f}  |  Withdrawal: ${MONTHLY_WITHDRAWAL:,.0f}/mo")
    print("=" * 70 + "\n")

    test_cases = [
        # 短期权策略 (2.5年真实数据)
        create_strategy_a_short_put_spy(),
        create_strategy_a2_short_put_qqq(),
        create_strategy_b_wheel(),
        create_strategy_d_bull_put_spread(),
        # LEAPS策略 (10年含合成数据)
        create_strategy_c_leaps_vol_target(),
        # 基准
        create_benchmark_spy_bh(),
        create_benchmark_spy_bh_short(),
    ]

    for i, tc in enumerate(test_cases, 1):
        logger.info(f"\n[{i}/{len(test_cases)}] {tc.name}")
        run_single(tc)

    logger.info("\n\nGenerating comparison report...")
    summary = generate_report(test_cases)
    print("\n" + summary)

    print("\n📁 报告文件:")
    print(f"  JSON: {REPORT_DIR}/cashflow_comparison_report.json")
    print(f"  摘要: {REPORT_DIR}/cashflow_comparison_summary.txt")
    for tc in test_cases:
        if tc.result and tc.result.report_path:
            print(f"  HTML: {tc.result.report_path}")

    print("\n✅ 完成! 请将 cashflow_comparison_summary.txt 内容分享给 Claude 进行分析。")


if __name__ == "__main__":
    main()
