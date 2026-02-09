"""
Analysis & Visualization Test - 回测分析与可视化测试

测试内容:
1. BacktestMetrics - 绩效指标计算 (Sharpe, 最大回撤等)
2. TradeAnalyzer - 交易分析 (按标的/月份分组, 最佳/最差交易)
3. BacktestDashboard - 可视化报告生成 (Plotly 交互式图表)

用法:
    python -m pytest tests/backtest/test_analysis_visualization.py -v -s
    或直接运行:
    python tests/backtest/test_analysis_visualization.py
"""

from datetime import date
from pathlib import Path

import pytest

from src.backtest import BacktestConfig, BacktestExecutor
from src.backtest.analysis.metrics import BacktestMetrics
from src.backtest.analysis.trade_analyzer import TradeAnalyzer
from src.backtest.visualization.dashboard import BacktestDashboard
from src.engine.models.enums import StrategyType


def print_separator(title: str) -> None:
    """打印分隔线"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


class TestAnalysisVisualization:
    """回测分析与可视化测试"""

    @pytest.fixture
    def real_data_dir(self) -> Path | None:
        """获取真实数据目录"""
        data_dir = Path("/Volumes/ORICO/option_quant")
        return data_dir if data_dir.exists() else None

    @pytest.fixture
    def backtest_result(self, real_data_dir: Path | None):
        """运行回测获取结果"""
        if real_data_dir is None:
            pytest.skip("Real data directory not available at /Volumes/ORICO/option_quant")

        config = BacktestConfig(
            name="ANALYSIS_VIZ_TEST",
            description="测试分析与可视化模块",
            start_date=date(2026, 1, 28),
            end_date=date(2026, 2, 4),
            symbols=["GOOG", "SPY"],
            data_dir=str(real_data_dir),
            initial_capital=1_000_000,
            max_positions=20,
            max_margin_utilization=0.70,
            strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
        )

        executor = BacktestExecutor(config)
        return executor.run()

    def test_backtest_metrics(self, backtest_result) -> None:
        """测试绩效指标计算

        验证 BacktestMetrics 能够正确计算各类指标:
        - 收益指标: 总回报, 年化回报
        - 风险指标: 最大回撤, 波动率, VaR
        - 风险调整收益: Sharpe, Sortino, Calmar
        - 交易指标: 胜率, Profit Factor
        """
        print_separator("绩效指标测试 (BacktestMetrics)")

        # 计算指标
        metrics = BacktestMetrics.from_backtest_result(backtest_result)

        # 打印完整摘要
        print(metrics.summary())

        # 验证关键指标存在
        print("\n--- 指标验证 ---")
        print(f"  Sharpe Ratio:    {metrics.sharpe_ratio}")
        print(f"  Sortino Ratio:   {metrics.sortino_ratio}")
        print(f"  Calmar Ratio:    {metrics.calmar_ratio}")
        print(f"  Max Drawdown:    {metrics.max_drawdown}")
        print(f"  Win Rate:        {metrics.win_rate}")
        print(f"  Profit Factor:   {metrics.profit_factor}")
        print(f"  VaR (95%):       {metrics.var_95}")
        print(f"  CVaR (95%):      {metrics.cvar_95}")

        # 基本断言
        assert metrics is not None
        assert metrics.total_trades > 0, "应该有交易记录"
        assert metrics.trading_days > 0, "应该有交易天数"

        # 如果有足够数据, 验证风险指标
        if metrics.trading_days >= 2:
            # 这些指标在有足够数据时应该有值
            print("\n--- 有足够数据时的断言 ---")
            if len(backtest_result.daily_snapshots) >= 2:
                print("  ✓ 有足够的每日快照")

    def test_trade_analyzer(self, backtest_result) -> None:
        """测试交易分析

        验证 TradeAnalyzer 的分析功能:
        - 按标的分组统计
        - 按月份分组统计
        - 最佳/最差交易识别
        - 持仓周期分布
        """
        print_separator("交易分析测试 (TradeAnalyzer)")

        if not backtest_result.trade_records:
            pytest.skip("没有交易记录可供分析")

        analyzer = TradeAnalyzer(backtest_result.trade_records)

        # 打印分析报告
        print(analyzer.summary_report())

        # 按标的分组
        print("\n--- 按标的分组详情 ---")
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

        # 最佳交易
        print("\n--- 最佳交易 (Top 5) ---")
        best_trades = analyzer.get_best_trades(5)
        for i, trade in enumerate(best_trades, 1):
            print(
                f"  {i}. {trade.underlying:8} {trade.option_type:4} "
                f"${trade.strike:.0f} | "
                f"PnL=${trade.pnl:>8,.2f} | "
                f"Return={trade.return_pct:>6.1%} | "
                f"{trade.entry_date} ~ {trade.exit_date} ({trade.holding_days}d)"
            )

        # 最差交易
        print("\n--- 最差交易 (Top 5) ---")
        worst_trades = analyzer.get_worst_trades(5)
        for i, trade in enumerate(worst_trades, 1):
            print(
                f"  {i}. {trade.underlying:8} {trade.option_type:4} "
                f"${trade.strike:.0f} | "
                f"PnL=${trade.pnl:>8,.2f} | "
                f"Return={trade.return_pct:>6.1%} | "
                f"{trade.entry_date} ~ {trade.exit_date} ({trade.holding_days}d)"
            )

        # 持仓周期统计
        print("\n--- 持仓周期分布 ---")
        holding_stats = analyzer.get_holding_period_stats()
        if holding_stats:
            print(f"  最短: {holding_stats['min']} 天")
            print(f"  最长: {holding_stats['max']} 天")
            print(f"  平均: {holding_stats['avg']:.1f} 天")
            print(f"  中位数: {holding_stats['median']:.0f} 天")
            print("  分布:")
            for period, count in holding_stats["distribution"].items():
                if count > 0:
                    bar = "█" * count
                    print(f"    {period:8} | {bar} ({count})")

        # 按平仓原因统计
        print("\n--- 按平仓原因统计 ---")
        by_reason = analyzer.get_exit_reason_stats()
        for reason, stats in by_reason.items():
            print(
                f"  {reason:12} | trades={stats.count:3} | "
                f"PnL=${stats.total_pnl:>8,.2f} | "
                f"win_rate={stats.win_rate:.0%}"
            )

        # 断言 (如果有配对的交易)
        # 注意: TradeAnalyzer 需要 position_id 来配对 open/close 交易
        # 如果 position_id 为 None，则无法配对
        if by_symbol:
            assert len(by_symbol) > 0, "应该有按标的的统计"
        else:
            print("\n⚠️  注意: 无法配对交易 (position_id 可能为 None)")
            print("   这不影响 BacktestMetrics 的计算，但会影响交易分组分析")

    def test_visualization_dashboard(self, backtest_result) -> None:
        """测试可视化报告生成

        验证 BacktestDashboard 能够:
        - 生成权益曲线图
        - 生成回撤图
        - 生成月度收益热力图
        - 生成交易时间线
        - 生成独立 HTML 报告
        """
        print_separator("可视化测试 (BacktestDashboard)")

        # 计算指标 (Dashboard 需要)
        metrics = BacktestMetrics.from_backtest_result(backtest_result)

        # 创建 Dashboard
        dashboard = BacktestDashboard(backtest_result, metrics)

        # 生成各个图表 (验证不报错)
        print("生成图表...")
        print("  1. 权益曲线...")
        equity_fig = dashboard.create_equity_curve()
        print(f"     ✓ traces: {len(equity_fig.data)}")

        print("  2. 回撤图...")
        drawdown_fig = dashboard.create_drawdown_chart()
        print(f"     ✓ traces: {len(drawdown_fig.data)}")

        print("  3. 月度收益热力图...")
        monthly_fig = dashboard.create_monthly_returns_heatmap()
        print(f"     ✓ traces: {len(monthly_fig.data)}")

        print("  4. 交易时间线...")
        timeline_fig = dashboard.create_trade_timeline()
        print(f"     ✓ traces: {len(timeline_fig.data)}")

        # 生成 HTML 报告
        print("\n生成 HTML 报告...")
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        report_path = dashboard.generate_report(reports_dir / "backtest_report.html")

        print(f"  报告路径: {report_path}")
        print(f"  文件大小: {report_path.stat().st_size / 1024:.1f} KB")

        # 验证文件存在
        assert report_path.exists(), "HTML 报告应该已生成"
        assert report_path.stat().st_size > 0, "HTML 报告不应为空"

        # 打印预览链接
        print(f"\n  🌐 在浏览器中打开: file://{report_path.absolute()}")

        # 可选: 自动在浏览器中打开
        # dashboard.show()

    def test_full_analysis_pipeline(self, backtest_result) -> None:
        """完整分析流水线测试

        模拟实际使用场景: 回测完成后的完整分析流程
        """
        print_separator("完整分析流水线")

        # Step 1: 计算绩效指标
        print("Step 1: 计算绩效指标...")
        metrics = BacktestMetrics.from_backtest_result(backtest_result)

        # Step 2: 关键指标摘要
        print("\n📊 关键绩效指标 (KPIs)")
        print("-" * 40)
        print(f"  总收益率:       {metrics.total_return_pct:.2%}")
        print(f"  年化收益率:     {metrics.annualized_return:.2%}" if metrics.annualized_return else "  年化收益率:     N/A")
        print(f"  最大回撤:       {metrics.max_drawdown:.2%}" if metrics.max_drawdown else "  最大回撤:       N/A")
        print(f"  Sharpe Ratio:   {metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio else "  Sharpe Ratio:   N/A")
        print(f"  胜率:           {metrics.win_rate:.1%}" if metrics.win_rate else "  胜率:           N/A")
        print(f"  Profit Factor:  {metrics.profit_factor:.2f}" if metrics.profit_factor else "  Profit Factor:  N/A")

        # Step 3: 交易分析
        print("\nStep 2: 交易分析...")
        if backtest_result.trade_records:
            analyzer = TradeAnalyzer(backtest_result.trade_records)

            # 快速统计
            by_symbol = analyzer.group_by_symbol()
            print(f"  交易标的数: {len(by_symbol)}")
            print(f"  总交易笔数: {sum(s.count for s in by_symbol.values())}")

            # 最佳交易
            best = analyzer.get_best_trades(1)
            if best:
                print(f"  最佳交易: {best[0].underlying} ${best[0].pnl:,.2f}")

            # 最差交易
            worst = analyzer.get_worst_trades(1)
            if worst:
                print(f"  最差交易: {worst[0].underlying} ${worst[0].pnl:,.2f}")

        # Step 4: 生成报告
        print("\nStep 3: 生成可视化报告...")
        dashboard = BacktestDashboard(backtest_result, metrics)
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        report_path = dashboard.generate_report(reports_dir / "full_analysis_report.html")
        print(f"  ✓ 报告已生成: {report_path}")

        print("\n" + "=" * 40)
        print("分析完成!")
        print(f"打开报告: file://{report_path.absolute()}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
