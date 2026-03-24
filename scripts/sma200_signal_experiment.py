"""A/B 实验: 简化信号 (单一 SMA200 二元) vs 当前 7 点评分系统

论文 "Leverage for the Long Run" (Gayed 2016) 核心策略:
  - Close > MA200 → 杠杆多头
  - Close < MA200 → T-Bills

对比三个变体:
  A) leaps_v2_cash_sweep (默认): 7 点评分 + vol_target + SHV cash sweep
  B) sma_leaps: 纯 SMA200 二元信号 + LEAPS (论文 LRS 思路)
  C) leaps_v2_cash_sweep + 平坦 position_map: 7 点评分但去掉分档，score≥2 统一 2x

实验目的: 验证复杂评分系统是否比简单 SMA200 信号带来超额收益。
"""

import logging
from datetime import date

logging.basicConfig(level=logging.WARNING)
logging.getLogger("src.backtest.pipeline").setLevel(logging.INFO)

from src.backtest import BacktestConfig, BacktestPipeline
from src.strategy.signals.momentum import MomentumConfig

# 回测参数
SYMBOL = "QQQ"
START = date(2016, 6, 1)
END = date(2026, 3, 1)
CAPITAL = 1_000_000
DATA_DIR = "/Volumes/ORICO/option_quant"  # 使用真实期权数据

# 平坦 position_map: score≥2 统一 2.0 (去掉分档效应)
FLAT_MAP = {0: 0.0, 1: 0.0, 2: 2.0, 3: 2.0, 4: 2.0, 5: 2.0, 6: 2.0, 7: 2.0}

configs = {
    "A) 7pt + vol_target (default)": {
        "strategy_version": "leaps_v2_cash_sweep",
        "strategy_kwargs": {},
    },
    "B) SMA200 binary (paper LRS)": {
        "strategy_version": "sma_leaps",
        "strategy_kwargs": {},
    },
    "C) 7pt flat map (no grading)": {
        "strategy_version": "leaps_v2_cash_sweep",
        "strategy_kwargs": {"momentum": MomentumConfig(position_map=FLAT_MAP, entry_min_score=2)},
    },
}

results = {}
for label, cfg in configs.items():
    print(f"\n{'='*60}")
    print(f"  Running: {label}")
    print(f"{'='*60}")

    config = BacktestConfig(
        name=f"SMA_EXP_{label[:1]}",
        start_date=START,
        end_date=END,
        symbols=[SYMBOL],
        initial_capital=CAPITAL,
        strategy_version=cfg["strategy_version"],
        strategy_kwargs=cfg["strategy_kwargs"],
        data_dir=DATA_DIR,
    )

    result = BacktestPipeline(config).run(
        skip_data_check=True,
        generate_report=False,
    )
    results[label] = result

# 汇总对比
print(f"\n{'='*70}")
print(f"  信号简化实验: {SYMBOL} {START} ~ {END}  (初始 ${CAPITAL:,.0f})")
print(f"{'='*70}")
header = f"{'策略':<35} {'总收益':>10} {'年化':>8} {'最大回撤':>10} {'Sharpe':>8} {'Calmar':>8} {'交易数':>8}"
print(header)
print("-" * len(header))

for label, r in results.items():
    m = r.metrics
    total_ret = m.total_return_pct if m.total_return_pct else 0
    ann_ret = m.annualized_return if m.annualized_return else 0
    max_dd = m.max_drawdown if m.max_drawdown else 0
    sharpe = m.sharpe_ratio if m.sharpe_ratio else 0
    calmar = m.calmar_ratio if m.calmar_ratio else 0
    trades = r.backtest_result.total_trades if r.backtest_result else 0
    print(
        f"{label:<35} {total_ret:>9.1%} {ann_ret:>7.1%} {max_dd:>9.1%} "
        f"{sharpe:>8.2f} {calmar:>8.2f} {trades:>8}"
    )

print(f"\n论文核心观点: 简单 MA200 信号 + 杠杆 > 复杂信号 + 无杠杆")
print(f"验证问题: 7 点分档评分 vs 二元信号，在 LEAPS 杠杆下孰优孰劣？")
