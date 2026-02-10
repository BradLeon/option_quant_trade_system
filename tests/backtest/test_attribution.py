#!/usr/bin/env python3
"""
归因模块验证脚本

使用真实回测数据端到端验证归因模块的正确性:
1. 运行回测 (带 AttributionCollector)
2. 验证 PositionSnapshot / PortfolioSnapshot 采集
3. 验证 PnL 归因分解 (delta + gamma + theta + vega + residual ≈ actual)
4. 验证切片归因
5. 验证 Attribution Charts 生成

用法:
    python tests/backtest/test_attribution.py
"""

import sys
import traceback
from datetime import date
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ============================================================
# Helpers
# ============================================================

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    """断言检查，打印结果"""
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  [PASS] {name}")
    else:
        FAIL_COUNT += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def approx_eq(a: float, b: float, abs_tol: float = 0.01) -> bool:
    return abs(a - b) <= abs_tol


def section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


# ============================================================
# Step 0: 环境检查
# ============================================================

def check_environment() -> Path:
    """检查数据目录"""
    data_dir = Path("/Volumes/ORICO/option_quant")
    if not data_dir.exists():
        print("数据目录不存在: /Volumes/ORICO/option_quant")
        print("请确保外部硬盘已连接")
        sys.exit(1)
    return data_dir


# ============================================================
# Step 1: 运行回测 (带 AttributionCollector)
# ============================================================

def run_backtest_with_attribution(data_dir: Path):
    """运行回测并返回结果 + collector"""
    from src.backtest import BacktestConfig, BacktestExecutor
    from src.backtest.attribution.collector import AttributionCollector
    from src.engine.models.enums import StrategyType

    config = BacktestConfig(
        name="ATTRIBUTION_VALIDATION",
        description="验证归因模块",
        start_date=date(2025, 12, 1),
        end_date=date(2026, 2, 2),
        symbols=["GOOG", "SPY"],
        data_dir=str(data_dir),
        initial_capital=1_000_000,
        max_positions=20,
        max_margin_utilization=0.70,
        strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
        screening_overrides={
            "contract_filter": {
                "dte_range": [7, 30],
                "optimal_dte_range": [14, 25],
            }
        },
    )

    collector = AttributionCollector()
    executor = BacktestExecutor(config, attribution_collector=collector)
    result = executor.run()

    print(f"  回测完成: {result.trading_days} 交易日, {result.total_trades} 笔交易")
    print(f"  最终净值: ${result.final_nlv:,.2f}")
    print(f"  采集持仓快照: {len(collector.position_snapshots)} 条")
    print(f"  采集组合快照: {len(collector.portfolio_snapshots)} 条")

    return result, collector


# ============================================================
# Step 2: 验证数据采集
# ============================================================

def verify_collector(result, collector):
    """验证 AttributionCollector 采集的数据"""
    pos_snaps = collector.position_snapshots
    port_snaps = collector.portfolio_snapshots

    # 组合快照数 > 0
    check("组合快照非空", len(port_snaps) > 0, f"实际={len(port_snaps)}")

    # 组合快照数应约等于交易日数
    check(
        "组合快照数 ≈ 交易日数",
        abs(len(port_snaps) - result.trading_days) <= 2,
        f"快照={len(port_snaps)}, 交易日={result.trading_days}",
    )

    # 有持仓快照
    check("持仓快照非空", len(pos_snaps) > 0, f"实际={len(pos_snaps)}")

    # PortfolioSnapshot 字段检查
    ps = port_snaps[-1]
    check("NLV > 0", ps.nlv > 0, f"NLV={ps.nlv}")
    check("cash >= 0", ps.cash >= 0, f"cash={ps.cash}")

    # PositionSnapshot 字段检查 (优先取字段最完整的快照)
    snap_with_greeks = next(
        (s for s in pos_snaps if s.delta is not None and s.iv is not None), None
    ) or next(
        (s for s in pos_snaps if s.delta is not None), None
    )
    if snap_with_greeks:
        s = snap_with_greeks
        check("PositionSnapshot.underlying 非空", bool(s.underlying))
        check("PositionSnapshot.delta 有值", s.delta is not None, f"delta={s.delta}")
        check("PositionSnapshot.lot_size > 0", s.lot_size > 0, f"lot_size={s.lot_size}")
        check("PositionSnapshot.underlying_price > 0", s.underlying_price > 0)

        # iv 可能为 None (部分数据源不提供)，仅统计而非强制要求
        iv_count = sum(1 for ss in pos_snaps if ss.iv is not None and ss.iv > 0)
        check(
            "有 IV 数据的快照占比 > 0",
            iv_count > 0,
            f"有IV={iv_count}/{len(pos_snaps)}",
        )

        def _fmt(v, fmt=".4f"):
            return f"{v:{fmt}}" if v is not None else "None"

        print(f"\n  示例快照: {s.underlying} {s.option_type} ${s.strike}")
        print(f"    date={s.date}, qty={s.quantity}, underlying_price={s.underlying_price:.2f}")
        print(f"    iv={_fmt(s.iv)}, delta={_fmt(s.delta)}, gamma={_fmt(s.gamma)}, theta={_fmt(s.theta)}, vega={_fmt(s.vega)}")
        print(f"    market_value={s.market_value:.2f}, entry_price={s.entry_price}")
    else:
        check("至少一条快照有 Greeks", False, "所有快照 delta 均为 None")


# ============================================================
# Step 3: 验证 PnL 归因
# ============================================================

def verify_pnl_attribution(collector, result):
    """验证 PnL 归因分解"""
    from src.backtest.attribution.pnl_attribution import PnLAttributionEngine

    engine = PnLAttributionEngine(
        position_snapshots=collector.position_snapshots,
        portfolio_snapshots=collector.portfolio_snapshots,
        trade_records=result.trade_records,
    )

    # --- Daily Attribution ---
    daily = engine.compute_all_daily()
    check("Daily attribution 非空", len(daily) > 0, f"实际={len(daily)} 天")

    # 逐日检查分解恒等式: actual = delta + gamma + theta + vega + residual
    max_mismatch = 0.0
    all_match = True
    for da in daily:
        for pa in da.position_attributions:
            greek_sum = pa.delta_pnl + pa.gamma_pnl + pa.theta_pnl + pa.vega_pnl + pa.residual
            mismatch = abs(pa.actual_pnl - greek_sum)
            max_mismatch = max(max_mismatch, mismatch)
            if mismatch > 0.01:
                all_match = False

    check(
        "分解恒等式 (actual = sum + residual)",
        all_match,
        f"最大误差={max_mismatch:.6f}",
    )

    # 累计归因 PnL vs 回测总收益
    cum_attribution_pnl = sum(d.total_pnl for d in daily)
    actual_total_return = result.final_nlv - result.initial_capital

    # 有些天可能没有持仓数据（首日等），允许一定偏差
    if actual_total_return != 0:
        coverage = cum_attribution_pnl / actual_total_return
        check(
            "累计归因 PnL vs 总收益覆盖率",
            abs(coverage) > 0.3,  # 至少覆盖 30%（有些天可能无持仓）
            f"归因PnL=${cum_attribution_pnl:,.2f}, 总收益=${actual_total_return:,.2f}, 覆盖={coverage:.1%}",
        )
    else:
        print("  [SKIP] 总收益为 0, 跳过覆盖率检查")

    # 打印归因摘要
    summary = engine.attribution_summary()
    print(f"\n  归因摘要:")
    print(f"    trading_days:        {summary['trading_days']}")
    print(f"    total_pnl:           ${summary['total_pnl']:,.2f}")
    print(f"    delta_pnl:           ${summary['delta_pnl']:,.2f} ({summary['delta_pnl_pct']:.1%})")
    print(f"    gamma_pnl:           ${summary['gamma_pnl']:,.2f} ({summary['gamma_pnl_pct']:.1%})")
    print(f"    theta_pnl:           ${summary['theta_pnl']:,.2f} ({summary['theta_pnl_pct']:.1%})")
    print(f"    vega_pnl:            ${summary['vega_pnl']:,.2f} ({summary['vega_pnl_pct']:.1%})")
    print(f"    residual:            ${summary['residual']:,.2f} ({summary['residual_pct']:.1%})")
    print(f"    attribution_coverage: {summary['attribution_coverage']:.1%}")

    # 打印每日 Top-3 贡献因子
    print(f"\n  最佳 3 天:")
    for da in engine.get_best_days(3):
        print(f"    {da.date}: total=${da.total_pnl:,.2f} (D={da.delta_pnl:,.0f} G={da.gamma_pnl:,.0f} T={da.theta_pnl:,.0f} V={da.vega_pnl:,.0f})")

    print(f"\n  最差 3 天:")
    for da in engine.get_worst_days(3):
        print(f"    {da.date}: total=${da.total_pnl:,.2f} (D={da.delta_pnl:,.0f} G={da.gamma_pnl:,.0f} T={da.theta_pnl:,.0f} V={da.vega_pnl:,.0f})")

    # --- Trade Attribution ---
    trades = engine.compute_trade_attributions()
    check("Trade attribution 非空", len(trades) > 0, f"实际={len(trades)} 笔")

    if trades:
        print(f"\n  交易级别归因 ({len(trades)} 笔):")
        for ta in sorted(trades, key=lambda t: t.total_pnl, reverse=True)[:5]:
            print(
                f"    {ta.underlying:6} {ta.option_type:4} ${ta.strike:>7.1f} | "
                f"PnL=${ta.total_pnl:>8,.2f} | "
                f"D={ta.delta_pnl:>7,.0f} G={ta.gamma_pnl:>6,.0f} T={ta.theta_pnl:>7,.0f} V={ta.vega_pnl:>6,.0f} R={ta.residual:>6,.0f} | "
                f"{ta.holding_days}d"
            )

    return engine, daily, trades


# ============================================================
# Step 4: 验证切片归因
# ============================================================

def verify_slice_attribution(trades):
    """验证多维切片归因"""
    from src.backtest.attribution.slice_attribution import SliceAttributionEngine

    engine = SliceAttributionEngine(
        trade_attributions=trades,
        position_snapshots=[],
    )

    # by underlying
    by_underlying = engine.by_underlying()
    check("by_underlying 有结果", len(by_underlying) > 0)
    total_pnl = sum(s.total_pnl for s in by_underlying.values())
    trade_pnl = sum(t.total_pnl for t in trades)
    check(
        "by_underlying PnL 求和一致",
        approx_eq(total_pnl, trade_pnl, 0.1),
        f"切片合计=${total_pnl:,.2f}, 交易合计=${trade_pnl:,.2f}",
    )
    print(f"\n  按标的切片:")
    for label, stats in sorted(by_underlying.items(), key=lambda x: x[1].total_pnl, reverse=True):
        print(f"    {label:8} | trades={stats.trade_count:2} | PnL=${stats.total_pnl:>10,.2f} | win={stats.win_rate:.0%}")

    # by option type
    by_type = engine.by_option_type()
    check("by_option_type 有结果", len(by_type) > 0)
    print(f"\n  按期权类型切片:")
    for label, stats in by_type.items():
        print(f"    {label:12} | trades={stats.trade_count:2} | PnL=${stats.total_pnl:>10,.2f} | win={stats.win_rate:.0%}")

    # by exit reason
    by_exit = engine.by_exit_reason()
    check("by_exit_reason 有结果", len(by_exit) > 0)
    print(f"\n  按平仓原因切片:")
    for label, stats in by_exit.items():
        print(f"    {label:20} | trades={stats.trade_count:2} | PnL=${stats.total_pnl:>10,.2f} | win={stats.win_rate:.0%}")

    # by IV regime
    by_iv = engine.by_entry_iv_regime()
    if by_iv:
        print(f"\n  按 IV Regime 切片:")
        for label, stats in by_iv.items():
            print(f"    {label:8} | trades={stats.trade_count:2} | PnL=${stats.total_pnl:>10,.2f} | win={stats.win_rate:.0%}")


# ============================================================
# Step 5: 验证可视化
# ============================================================

def verify_charts(daily, trades, collector):
    """验证归因图表生成"""
    try:
        from src.backtest.visualization.attribution_charts import (
            AttributionCharts,
            PLOTLY_AVAILABLE,
        )
    except ImportError:
        print("  [SKIP] plotly 未安装, 跳过图表验证")
        return

    if not PLOTLY_AVAILABLE:
        print("  [SKIP] plotly 未安装, 跳过图表验证")
        return

    charts = AttributionCharts(
        daily_attributions=daily,
        trade_attributions=trades,
        portfolio_snapshots=collector.portfolio_snapshots,
    )

    # 逐一验证图表生成
    fig = charts.create_pnl_waterfall()
    check("PnL Waterfall 图表", fig is not None and len(fig.data) > 0)

    fig = charts.create_cumulative_attribution()
    check("Cumulative Attribution 图表", fig is not None and len(fig.data) > 0)

    fig = charts.create_daily_attribution_bar()
    check("Daily Attribution Bar 图表", fig is not None and len(fig.data) > 0)

    fig = charts.create_greeks_exposure_timeline()
    check("Greeks Exposure 图表", fig is not None and len(fig.data) > 0)

    # slice comparison
    from src.backtest.attribution.slice_attribution import SliceAttributionEngine
    slice_engine = SliceAttributionEngine(trades, [])
    by_underlying = slice_engine.by_underlying()
    if by_underlying:
        fig = charts.create_slice_comparison(by_underlying)
        check("Slice Comparison 图表", fig is not None and len(fig.data) > 0)


# ============================================================
# Step 6: 回归验证 - 不带 collector 回测行为不变
# ============================================================

def verify_regression(data_dir: Path):
    """验证不传 attribution_collector 时回测行为不变"""
    from src.backtest import BacktestConfig, BacktestExecutor
    from src.engine.models.enums import StrategyType

    config = BacktestConfig(
        name="REGRESSION_CHECK",
        description="回归验证",
        start_date=date(2025, 12, 1),
        end_date=date(2025, 12, 15),  # 短周期即可
        symbols=["GOOG"],
        data_dir=str(data_dir),
        initial_capital=1_000_000,
        strategy_types=[StrategyType.SHORT_PUT],
        screening_overrides={
            "contract_filter": {
                "dte_range": [7, 30],
                "optimal_dte_range": [14, 25],
            }
        },
    )

    # 不传 attribution_collector
    executor = BacktestExecutor(config)
    result = executor.run()
    check("回归: 不带 collector 回测正常", result is not None and result.trading_days > 0)
    check("回归: executor.attribution_collector is None", executor.attribution_collector is None)


# ============================================================
# Main
# ============================================================

def main():
    section("归因模块验证 (真实数据)")

    # Step 0
    data_dir = check_environment()

    # Step 1
    section("Step 1: 运行回测 (带 AttributionCollector)")
    result, collector = run_backtest_with_attribution(data_dir)

    if result.total_trades == 0:
        print("\n  回测无交易, 无法验证归因。请调整回测参数。")
        sys.exit(1)

    # Step 2
    section("Step 2: 验证数据采集")
    verify_collector(result, collector)

    # Step 3
    section("Step 3: 验证 PnL 归因")
    engine, daily, trades = verify_pnl_attribution(collector, result)

    # Step 4
    section("Step 4: 验证切片归因")
    if trades:
        verify_slice_attribution(trades)
    else:
        print("  [SKIP] 无交易归因, 跳过切片验证")

    # Step 5
    section("Step 5: 验证图表生成")
    verify_charts(daily, trades, collector)

    # Step 6
    section("Step 6: 回归验证")
    verify_regression(data_dir)

    # 汇总
    section("验证结果")
    total = PASS_COUNT + FAIL_COUNT
    print(f"  PASS: {PASS_COUNT}/{total}")
    print(f"  FAIL: {FAIL_COUNT}/{total}")

    if FAIL_COUNT > 0:
        print(f"\n  有 {FAIL_COUNT} 项未通过，请检查上方 [FAIL] 条目。")
        sys.exit(1)
    else:
        print(f"\n  全部通过!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n运行出错: {e}")
        traceback.print_exc()
        sys.exit(1)
