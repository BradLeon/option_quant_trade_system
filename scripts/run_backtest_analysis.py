#!/usr/bin/env python3
"""
回测分析与可视化脚本

功能:
1. 运行回测 (2025-12-01 ~ 2026-01-02)
2. 与 SPY 基准比较
3. 生成完整 HTML 报告 (含交易记录表格)

用法:
    python scripts/run_backtest_analysis.py
"""

from datetime import date
from pathlib import Path

from src.backtest import BacktestConfig, BacktestExecutor
from src.backtest.analysis.metrics import BacktestMetrics
from src.backtest.analysis.trade_analyzer import TradeAnalyzer
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.optimization.benchmark import BenchmarkComparison
from src.backtest.visualization.dashboard import BacktestDashboard
from src.engine.models.enums import StrategyType


def print_separator(title: str) -> None:
    """打印分隔线"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def main():
    """主函数"""
    # 检查数据目录
    data_dir = Path("/Volumes/ORICO/option_quant")
    if not data_dir.exists():
        print("❌ 数据目录不存在: /Volumes/ORICO/option_quant")
        print("   请确保外部硬盘已连接")
        return

    print_separator("回测配置")

    # 回测配置
    config = BacktestConfig(
        name="ANALYSIS_VIZ_TEST",
        description="测试分析与可视化模块 (含 Benchmark)",
        start_date=date(2025, 12, 1),
        end_date=date(2026, 2, 2),
        symbols=["GOOG","SPY"],
        data_dir=str(data_dir),
        initial_capital=1_000_000,
        max_positions=20,
        max_margin_utilization=0.70,
        strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
        # 调整 DTE 范围以匹配现有期权数据 (数据只有 ≤30 天 DTE)
        screening_overrides={
            "contract_filter": {
                "dte_range": [7, 30],
                "optimal_dte_range": [14, 25],
            }
        },
    )

    print(f"  策略名称: {config.name}")
    print(f"  回测周期: {config.start_date} ~ {config.end_date}")
    print(f"  标的: {config.symbols}")
    print(f"  策略类型: {[s.name for s in config.strategy_types]}")
    print(f"  初始资金: ${config.initial_capital:,}")

    # 运行回测
    print_separator("运行回测")
    executor = BacktestExecutor(config)
    result = executor.run()

    print(f"✅ 回测完成:")
    print(f"   交易日数: {result.trading_days}")
    print(f"   总交易笔数: {result.total_trades}")
    print(f"   最终净值: ${result.final_nlv:,.2f}")

    # 计算绩效指标
    print_separator("绩效指标")
    metrics = BacktestMetrics.from_backtest_result(result)

    print(f"  总收益率:     {metrics.total_return_pct:.2%}")
    print(f"  年化收益率:   {metrics.annualized_return:.2%}" if metrics.annualized_return else "  年化收益率:   N/A")
    print(f"  最大回撤:     {metrics.max_drawdown:.2%}" if metrics.max_drawdown else "  最大回撤:     N/A")
    print(f"  Sharpe Ratio: {metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio else "  Sharpe Ratio: N/A")
    print(f"  Sortino Ratio: {metrics.sortino_ratio:.2f}" if metrics.sortino_ratio else "  Sortino Ratio: N/A")
    print(f"  Calmar Ratio: {metrics.calmar_ratio:.2f}" if metrics.calmar_ratio else "  Calmar Ratio: N/A")
    print(f"  胜率:         {metrics.win_rate:.1%}" if metrics.win_rate else "  胜率:         N/A")
    print(f"  Profit Factor: {metrics.profit_factor:.2f}" if metrics.profit_factor else "  Profit Factor: N/A")
    print(f"  P/L Ratio:    {metrics.profit_loss_ratio:.2f}" if metrics.profit_loss_ratio else "  P/L Ratio:    N/A")
    print(f"  VaR (95%):    {metrics.var_95:.2%}" if metrics.var_95 else "  VaR (95%):    N/A")
    print(f"  CVaR (95%):   {metrics.cvar_95:.2%}" if metrics.cvar_95 else "  CVaR (95%):   N/A")

    # Benchmark 比较
    print_separator("Benchmark 比较 (SPY)")

    # 创建数据提供者
    data_provider = DuckDBProvider(str(data_dir))

    # 运行 benchmark 比较
    benchmark = BenchmarkComparison(result)
    benchmark_result = benchmark.compare_with_spy(data_provider)

    print(f"  策略总收益:   {benchmark_result.strategy_total_return:.2%}")
    print(f"  基准总收益:   {benchmark_result.benchmark_total_return:.2%}")
    print(f"  超额收益:     {benchmark_result.strategy_total_return - benchmark_result.benchmark_total_return:.2%}")
    print(f"  Alpha:        {benchmark_result.alpha:.4f}" if benchmark_result.alpha else "  Alpha:        N/A")
    print(f"  Beta:         {benchmark_result.beta:.2f}" if benchmark_result.beta else "  Beta:         N/A")
    print(f"  Information Ratio: {benchmark_result.information_ratio:.2f}" if benchmark_result.information_ratio else "  Information Ratio: N/A")
    print(f"  日胜率:       {benchmark_result.daily_win_rate:.1%}")
    print(f"  跑赢天数:     {benchmark_result.outperformance_days}")
    print(f"  跑输天数:     {benchmark_result.underperformance_days}")

    # 交易分析
    print_separator("交易分析")

    if result.trade_records:
        analyzer = TradeAnalyzer(result.trade_records)

        # 按标的分组
        print("--- 按标的分组 ---")
        by_symbol = analyzer.group_by_symbol()
        for symbol, stats in sorted(by_symbol.items(), key=lambda x: x[1].total_pnl, reverse=True):
            pf_str = f"{stats.profit_factor:.2f}" if stats.profit_factor else "N/A"
            print(
                f"  {symbol:8} | trades={stats.count:3} | "
                f"win={stats.winning}/{stats.losing} | "
                f"PnL=${stats.total_pnl:>10,.2f} | "
                f"win_rate={stats.win_rate:.0%} | "
                f"PF={pf_str}"
            )

        # 最佳/最差交易
        print("\n--- 最佳交易 (Top 3) ---")
        for i, trade in enumerate(analyzer.get_best_trades(3), 1):
            print(
                f"  {i}. {trade.underlying:8} {trade.option_type:4} "
                f"${trade.strike:.0f} | "
                f"PnL=${trade.pnl:>8,.2f} | "
                f"{trade.entry_date} ~ {trade.exit_date}"
            )

        print("\n--- 最差交易 (Top 3) ---")
        for i, trade in enumerate(analyzer.get_worst_trades(3), 1):
            print(
                f"  {i}. {trade.underlying:8} {trade.option_type:4} "
                f"${trade.strike:.0f} | "
                f"PnL=${trade.pnl:>8,.2f} | "
                f"{trade.entry_date} ~ {trade.exit_date}"
            )
    else:
        print("  没有交易记录")

    # 生成可视化报告
    print_separator("生成 HTML 报告")

    # 创建 Dashboard (传入 benchmark_result)
    dashboard = BacktestDashboard(
        result=result,
        metrics=metrics,
        benchmark_result=benchmark_result,
    )

    # 生成报告
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    report_path = dashboard.generate_report(reports_dir / "backtest_report.html")

    print(f"✅ 报告已生成: {report_path}")
    print(f"   文件大小: {report_path.stat().st_size / 1024:.1f} KB")

    # 打印交易记录表格 (文本版)
    print_separator("交易记录")
    print(f"{'日期':<12} {'操作':<6} {'标的':<8} {'类型':<5} {'行权价':>10} {'到期日':<12} {'DTE':>4} {'数量':>6} {'价格':>10} {'净额':>12} {'盈亏':>12}  {'原因'}")
    print("-" * 140)

    for record in sorted(result.trade_records, key=lambda r: r.trade_date):
        option_type = getattr(record, "option_type", None)
        option_type_str = option_type.name if hasattr(option_type, "name") else str(option_type) if option_type else "N/A"
        strike = getattr(record, "strike", None)
        strike_str = f"${strike:.2f}" if strike else "N/A"
        expiry = getattr(record, "expiration", None)
        expiry_str = expiry.isoformat() if expiry else "N/A"

        # 计算 DTE (Days To Expiration)
        if expiry:
            dte = (expiry - record.trade_date).days
            dte_str = str(dte)
        else:
            dte_str = "-"

        pnl_str = f"${record.pnl:,.2f}" if record.pnl else "-"
        net_amount = getattr(record, "net_amount", 0)

        # Reason (仅 CLOSE/ROLL/EXPIRE 显示)
        action = record.action.upper()
        reason = getattr(record, "reason", None)
        if action in ("CLOSE", "ROLL", "EXPIRE") and reason:
            reason_str = reason
        else:
            reason_str = "-"

        print(
            f"{record.trade_date!s:<12} "
            f"{action:<6} "
            f"{getattr(record, 'underlying', 'N/A'):<8} "
            f"{option_type_str:<5} "
            f"{strike_str:>10} "
            f"{expiry_str:<12} "
            f"{dte_str:>4} "
            f"{record.quantity:>6} "
            f"${record.price:>9,.2f} "
            f"${net_amount:>11,.2f} "
            f"{pnl_str:>12}  "
            f"{reason_str}"
        )

    print("-" * 140)
    print(f"总交易笔数: {len(result.trade_records)}")

    # 打开报告
    print_separator("完成")
    print(f"🌐 在浏览器中打开报告:")
    print(f"   file://{report_path.absolute()}")


if __name__ == "__main__":
    main()
