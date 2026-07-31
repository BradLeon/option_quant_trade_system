#!/usr/bin/env python3
"""
Short Put QQQ 参数优化 - Parameter Grid Search
================================================

在 A2 (Short Put QQQ, Sharpe=1.25) 基础上做参数网格搜索,
寻找最优参数组合。

搜索维度:
  1. DTE 范围: 短期(7-30) vs 中期(14-45) vs 长期(21-60)
  2. 止盈阈值: 50% vs 65% vs 80%
  3. Margin利用率: 70% vs 85% vs 95%
  4. 每日最大新仓: 1 vs 2 vs 3
  5. Min Expected ROC: 0.03 vs 0.05 vs 0.08

共 3×3×3×3×3 = 243 个组合, 预计运行 20-40 分钟。

运行:
  cd /path/to/option_quant_trade_system
  uv run python scripts/optimize_short_put_qqq.py

输出:
  reports/qqq_optimization_results.json
  reports/qqq_optimization_summary.txt
"""

import json
import logging
import sys
import time
import traceback
from datetime import date
from itertools import product
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.pipeline import BacktestPipeline
from src.engine.models.enums import StrategyType

logging.basicConfig(
    level=logging.WARNING,  # 抑制INFO日志, 加速运行
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("optimizer")
logger.setLevel(logging.INFO)

# ============================================================
# 固定参数
# ============================================================
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 1_500.0
START_DATE = date(2023, 7, 1)
END_DATE = date(2026, 2, 1)
DATA_DIR = "/Volumes/ORICO/option_quant"
REPORT_DIR = "reports"
SYMBOL = "QQQ"
TOTAL_MONTHS = (END_DATE - START_DATE).days / 30.44

# ============================================================
# 参数网格
# ============================================================
PARAM_GRID = {
    "dte_range": [
        [7, 30],      # 短期: 快速周转
        [14, 45],      # 中期: baseline (A2当前值)
        [21, 60],      # 长期: 更多时间价值
    ],
    "take_profit": [
        0.50,          # 激进: 50%利润就跑
        0.65,          # baseline (A2当前值)
        0.80,          # 保守: 等更多利润
    ],
    "margin_util": [
        0.70,          # 保守
        0.85,          # baseline (A2当前值)
        0.95,          # 激进
    ],
    "max_new_per_day": [
        1,             # 保守
        2,             # baseline (A2当前值)
        3,             # 激进
    ],
    "min_expected_roc": [
        0.03,          # 宽松: 更多交易机会
        0.05,          # baseline (A2当前值)
        0.08,          # 严格: 只做高收益合约
    ],
}


def run_backtest(params: dict, index: int, total: int) -> dict:
    """运行单个参数组合的回测"""
    param_str = (
        f"DTE={params['dte_range']}, TP={params['take_profit']:.0%}, "
        f"Margin={params['margin_util']:.0%}, NewPos={params['max_new_per_day']}, "
        f"ROC={params['min_expected_roc']}"
    )

    config = BacktestConfig(
        name=f"OPT_{index:03d}",
        start_date=START_DATE,
        end_date=END_DATE,
        symbols=[SYMBOL],
        strategy_types=[StrategyType.SHORT_PUT],
        strategy_version="short_options_without_expire_itm_stock_trade",
        initial_capital=INITIAL_CAPITAL,
        monthly_withdrawal=MONTHLY_WITHDRAWAL,
        max_margin_utilization=params["margin_util"],
        max_positions=10,
        max_new_positions_per_day=params["max_new_per_day"],
        data_dir=DATA_DIR,
        benchmark_symbol="SPY",
        skip_market_check=True,
        screening_overrides={
            "contract_filter": {
                "dte_range": params["dte_range"],
                "metrics": {
                    "min_expected_roc": params["min_expected_roc"],
                    "min_tgr": 0.3,
                },
            },
        },
        monitoring_overrides={
            "take_profit": {
                "enabled": True,
                "threshold": params["take_profit"],
            },
        },
    )

    try:
        pipeline = BacktestPipeline(config)
        result = pipeline.run(skip_data_check=True, generate_report=False)

        m = result.metrics
        bt = result.backtest_result

        # 手动计算出金
        total_withdrawn = sum(
            s.withdrawal_amount for s in bt.daily_snapshots
            if hasattr(s, 'withdrawal_amount')
        )
        total_value_created = bt.final_nlv + total_withdrawn - bt.initial_capital
        monthly_value = total_value_created / TOTAL_MONTHS if TOTAL_MONTHS > 0 else 0

        metrics = {
            "index": index,
            "params": params,
            "param_str": param_str,
            # 收益
            "final_nlv": bt.final_nlv,
            "total_return_pct": bt.total_return_pct,
            "annualized_return": m.annualized_return or 0.0,
            # 风险
            "max_drawdown": m.max_drawdown or 0.0,
            "sharpe_ratio": m.sharpe_ratio or 0.0,
            "volatility": m.volatility or 0.0,
            # 交易
            "total_trades": bt.total_trades,
            "win_rate": m.win_rate or 0.0,
            "profit_factor": bt.profit_factor,
            # 现金流
            "total_withdrawals": total_withdrawn,
            "total_value_created": total_value_created,
            "monthly_value_created": monthly_value,
            "meets_target": monthly_value >= MONTHLY_WITHDRAWAL,
            # 费用
            "total_fees": bt.total_commission + bt.total_slippage,
            # 综合评分 (自定义)
            "score": _compute_score(m, monthly_value, bt),
        }

        status = "✅" if monthly_value >= MONTHLY_WITHDRAWAL else "⚠️"
        logger.info(
            f"[{index:3d}/{total}] {status} Sharpe={m.sharpe_ratio or 0:.2f} "
            f"DD={m.max_drawdown or 0:.1%} MV=${monthly_value:,.0f} "
            f"Trades={bt.total_trades} | {param_str}"
        )
        return metrics

    except Exception as e:
        logger.warning(f"[{index:3d}/{total}] ❌ {param_str}: {e}")
        return {
            "index": index,
            "params": params,
            "param_str": param_str,
            "error": str(e),
            "score": -999,
        }


def _compute_score(metrics, monthly_value: float, bt) -> float:
    """综合评分: 兼顾收益、风险、现金流稳定性

    Score = Sharpe × 40 + (月创值/目标) × 30 + (1 - MaxDD) × 20 + 胜率 × 10
    满分约 100
    """
    sharpe = metrics.sharpe_ratio or 0
    max_dd = metrics.max_drawdown or 0
    win_rate = metrics.win_rate or 0
    value_ratio = min(monthly_value / MONTHLY_WITHDRAWAL, 3.0) if MONTHLY_WITHDRAWAL > 0 else 0

    # 惩罚: 如果交易数太少 (<50), 说明策略太保守
    trade_penalty = min(bt.total_trades / 100, 1.0)  # 100笔交易时满分

    score = (
        sharpe * 40
        + value_ratio * 30
        + (1 - min(max_dd, 1.0)) * 20
        + win_rate * 10
    ) * trade_penalty

    return round(score, 2)


def main():
    start_time = time.time()

    # 生成所有参数组合
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    all_combos = list(product(*values))
    total = len(all_combos)

    logger.info(f"=" * 70)
    logger.info(f"  Short Put QQQ 参数优化")
    logger.info(f"  参数组合数: {total}")
    logger.info(f"  预计耗时: {total * 5 / 60:.0f}~{total * 15 / 60:.0f} 分钟")
    logger.info(f"=" * 70)

    results = []
    for i, combo in enumerate(all_combos, 1):
        params = dict(zip(keys, combo))
        result = run_backtest(params, i, total)
        results.append(result)

    elapsed = time.time() - start_time

    # 排序: 按综合评分
    valid = [r for r in results if "error" not in r]
    valid.sort(key=lambda x: x["score"], reverse=True)

    # 保存完整结果
    json_path = Path(REPORT_DIR) / "qqq_optimization_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    # 生成摘要
    lines = []
    lines.append("=" * 100)
    lines.append("  Short Put QQQ 参数优化结果  |  Parameter Optimization Results")
    lines.append("=" * 100)
    lines.append(f"  总组合数: {total}  |  有效: {len(valid)}  |  失败: {total - len(valid)}")
    lines.append(f"  运行耗时: {elapsed/60:.1f} 分钟  |  平均: {elapsed/total:.1f}秒/组合")
    lines.append("")

    # TOP 20
    lines.append(f"  {'TOP 20 参数组合 (按综合评分排序)':}")
    lines.append("-" * 100)
    lines.append(
        f"{'#':>3} {'Score':>6} {'Sharpe':>7} {'年化':>7} {'MaxDD':>7} "
        f"{'胜率':>5} {'月创值':>9} {'交易':>5} {'达标':>4}  参数"
    )
    lines.append("-" * 100)

    for rank, r in enumerate(valid[:20], 1):
        ok = "✅" if r["meets_target"] else "❌"
        lines.append(
            f"{rank:>3} {r['score']:>6.1f} {r['sharpe_ratio']:>6.2f} "
            f"{r['annualized_return']:>6.1%} {r['max_drawdown']:>6.1%} "
            f"{r['win_rate']:>4.0%} ${r['monthly_value_created']:>7,.0f} "
            f"{r['total_trades']:>5} {ok:>4}  {r['param_str']}"
        )

    lines.append("-" * 100)

    # 最优参数分析
    if valid:
        best = valid[0]
        lines.append("")
        lines.append(f"🏆 最优参数组合 (Score={best['score']:.1f}):")
        lines.append(f"  {best['param_str']}")
        lines.append(f"  Sharpe={best['sharpe_ratio']:.2f}, 年化={best['annualized_return']:.1%}, "
                     f"MaxDD={best['max_drawdown']:.1%}")
        lines.append(f"  月创值=${best['monthly_value_created']:,.0f}, 胜率={best['win_rate']:.0%}, "
                     f"交易={best['total_trades']}笔")
        lines.append(f"  终值NLV=${best['final_nlv']:,.0f}, 出金=${best['total_withdrawals']:,.0f}, "
                     f"费用=${best['total_fees']:,.0f}")

    # 参数敏感性分析
    lines.append("")
    lines.append("📊 参数敏感性 (各参数的平均Sharpe):")
    for key in keys:
        lines.append(f"\n  [{key}]")
        for val in PARAM_GRID[key]:
            subset = [r for r in valid if r["params"][key] == val]
            if subset:
                avg_sharpe = sum(r["sharpe_ratio"] for r in subset) / len(subset)
                avg_mv = sum(r["monthly_value_created"] for r in subset) / len(subset)
                avg_dd = sum(r["max_drawdown"] for r in subset) / len(subset)
                lines.append(
                    f"    {str(val):>12}: Sharpe={avg_sharpe:.2f}, "
                    f"月创值=${avg_mv:,.0f}, MaxDD={avg_dd:.1%} (n={len(subset)})"
                )

    # 达标率
    meeting = [r for r in valid if r["meets_target"]]
    lines.append(f"\n  达标率: {len(meeting)}/{len(valid)} ({len(meeting)/len(valid)*100:.0f}%)")

    lines.append("\n" + "=" * 100)

    summary = "\n".join(lines)
    summary_path = Path(REPORT_DIR) / "qqq_optimization_summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)

    print("\n" + summary)
    print(f"\n📁 结果文件:")
    print(f"  JSON: {json_path}")
    print(f"  摘要: {summary_path}")
    print(f"\n✅ 优化完成! 请将 qqq_optimization_summary.txt 分享给 Claude 分析。")


if __name__ == "__main__":
    main()
