"""A/B 回测: 入场 hysteresis (entry_min_score) 对比

对比 entry_min_score=2 (无滞后，原版行为) vs entry_min_score=3 (默认新值)
"""

import logging
import sys
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
STRATEGY = "leaps_v2_cash_sweep"

configs = {
    "baseline (entry_min=2)": MomentumConfig(entry_min_score=2),
    "hysteresis (entry_min=3)": MomentumConfig(entry_min_score=3),
    "hysteresis (entry_min=4)": MomentumConfig(entry_min_score=4),
}

results = {}
for label, momentum_cfg in configs.items():
    print(f"\n{'='*60}")
    print(f"  Running: {label}")
    print(f"{'='*60}")

    config = BacktestConfig(
        name=f"HYSTERESIS_{momentum_cfg.entry_min_score}",
        start_date=START,
        end_date=END,
        symbols=[SYMBOL],
        initial_capital=CAPITAL,
        strategy_version=STRATEGY,
        strategy_kwargs={"momentum": momentum_cfg},
    )

    result = BacktestPipeline(config).run(
        skip_data_check=True,
        generate_report=False,
    )
    results[label] = result

# 汇总对比
print(f"\n{'='*60}")
print(f"  A/B 对比: {SYMBOL} {START} ~ {END}")
print(f"{'='*60}")
print(f"{'策略':<30} {'总收益':>10} {'最大回撤':>10} {'Sharpe':>8} {'Calmar':>8} {'交易数':>8}")
print("-" * 80)

for label, r in results.items():
    m = r.metrics
    total_ret = m.total_return_pct if m.total_return_pct else 0
    max_dd = m.max_drawdown if m.max_drawdown else 0
    sharpe = m.sharpe_ratio if m.sharpe_ratio else 0
    calmar = m.calmar_ratio if m.calmar_ratio else 0
    trades = r.backtest_result.total_trades if r.backtest_result else 0
    print(f"{label:<30} {total_ret:>9.1%} {max_dd:>9.1%} {sharpe:>8.2f} {calmar:>8.2f} {trades:>8}")
