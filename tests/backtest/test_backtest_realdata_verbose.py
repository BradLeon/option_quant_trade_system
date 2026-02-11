"""
Verbose Pipeline Test - 详细打印 Screening/Monitoring 过程

使用真实 DuckDB 数据运行回测，打印 Pipeline 详细过程。

用法:
    python -m pytest tests/backtest/test_pipeline_verbose.py -v -s
    或直接运行:
    python tests/backtest/test_pipeline_verbose.py
"""

import logging
import sys
from datetime import date
from pathlib import Path

import pytest

from src.backtest import BacktestConfig, BacktestExecutor
from src.engine.models.enums import StrategyType


def setup_verbose_logging() -> None:
    """配置详细日志输出

    为关键模块启用 DEBUG 级别日志，以便观察 Pipeline 执行过程。
    """
    # 创建格式化器
    formatter = logging.Formatter(
        "%(asctime)s | %(name)-50s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # 创建控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # 为关键模块配置日志
    modules = [
        # Backtest 模块
        "src.backtest.engine.backtest_executor",
        "src.backtest.engine.position_manager",
        "src.backtest.engine.trade_simulator",
        "src.backtest.data.duckdb_provider",
        # Screening Pipeline
        "src.business.screening.pipeline",
        "src.business.screening.filters.market_filter",
        "src.business.screening.filters.underlying_filter",
        "src.business.screening.filters.contract_filter",
        # Monitoring Pipeline
        "src.business.monitoring.pipeline",
        "src.business.monitoring.monitors.portfolio_monitor",
        "src.business.monitoring.monitors.position_monitor",
        "src.business.monitoring.monitors.capital_monitor",
        # Decision Engine
        "src.business.trading.decision.engine",
    ]

    for module in modules:
        module_logger = logging.getLogger(module)
        module_logger.setLevel(logging.DEBUG)
        # 避免重复添加 handler
        if not module_logger.handlers:
            module_logger.addHandler(console_handler)
        # 防止日志传播到根 logger
        module_logger.propagate = False


def print_separator(title: str) -> None:
    """打印分隔线"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


class TestPipelineVerbose:
    """详细输出 Pipeline 过程的测试类"""

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        """每个测试前配置日志"""
        setup_verbose_logging()

    @pytest.fixture
    def real_data_dir(self) -> Path | None:
        """获取真实数据目录"""
        data_dir = Path("/Volumes/ORICO/option_quant")
        return data_dir if data_dir.exists() else None

    def test_backtest_with_verbose_pipeline(self, real_data_dir: Path | None) -> None:
        """运行多策略组合回测并打印详细 Pipeline 过程

        使用真实数据 (GOOG, SPY) 运行约 1 周的回测，
        同时运行 SHORT_PUT 和 COVERED_CALL 两种策略，
        在同一账户下组合交易。
        """
        if real_data_dir is None:
            pytest.skip("Real data directory not available at /Volumes/ORICO/option_quant")

        print_separator("回测配置 - 多策略组合 (SHORT_PUT + COVERED_CALL)")

        config = BacktestConfig(
            name="MULTI_STRATEGY_TEST",
            description="测试多策略组合回测 (SHORT_PUT + COVERED_CALL)",
            start_date=date(2026, 1, 28),  # 需要 21 天历史数据计算 HV
            end_date=date(2026, 2, 4),
            symbols=["GOOG", "SPY"],
            data_dir=str(real_data_dir),
            initial_capital=1_000_000,  # 100万美元，容纳更多交易
            max_positions=20,  # 增加持仓数以容纳多策略
            max_margin_utilization=0.70,
            strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
        )

        strategies_str = ", ".join(st.value for st in config.strategy_types)
        print(f"名称: {config.name}")
        print(f"日期范围: {config.start_date} ~ {config.end_date}")
        print(f"标的: {config.symbols}")
        print(f"初始资金: ${config.initial_capital:,.0f}")
        print(f"最大持仓数: {config.max_positions}")
        print(f"策略类型: {strategies_str}")
        print(f"数据目录: {config.data_dir}")

        print_separator("开始回测 - Pipeline 详细过程输出")

        executor = BacktestExecutor(config)
        result = executor.run()

        strategies_str = ", ".join(st.value.upper() for st in result.strategy_types)
        print_separator(f"回测结果摘要 - {strategies_str}")

        print(f"策略类型: {strategies_str}")
        print(f"交易天数: {result.trading_days}")
        print(f"总交易数: {result.total_trades}")
        print(f"胜率: {result.win_rate:.1%}")
        print(f"最终 NLV: ${result.final_nlv:,.2f}")
        print(f"总收益: ${result.total_return:,.2f} ({result.total_return_pct:.2%})")
        print(f"Profit Factor: {result.profit_factor:.2f}")
        print(f"总手续费: ${result.total_commission:,.2f}")
        print(f"总滑点: ${result.total_slippage:,.2f}")
        print(f"执行时间: {result.execution_time_seconds:.1f}s")

        # 打印每日快照摘要
        if result.daily_snapshots:
            print_separator(f"每日快照 - {strategies_str}")
            for snapshot in result.daily_snapshots[:5]:  # 只显示前5天
                print(
                    f"  {snapshot.date}: NLV=${snapshot.nlv:,.0f}, "
                    f"positions={snapshot.position_count}, "
                    f"opened={snapshot.trades_opened}, "
                    f"closed={snapshot.trades_closed}"
                )
            if len(result.daily_snapshots) > 5:
                print(f"  ... (共 {len(result.daily_snapshots)} 天)")

        # 打印交易记录摘要
        if result.trade_records:
            print_separator(f"交易记录 - {strategies_str}")
            print(
                f"  {'日期':12} | {'操作':6} | {'标的':6} | {'类型':4} | "
                f"{'行权价':>8} | {'到期日':10} | {'数量':>5} | "
                f"{'价格':>8} | {'金额':>10} | {'盈亏':>10}"
            )
            print("  " + "-" * 110)
            for record in result.trade_records[:20]:  # 显示前20条
                pnl_str = f"${record.pnl:,.2f}" if record.pnl is not None else "-"
                # 从 symbol 中提取关键信息
                underlying = record.underlying
                option_type = record.option_type.value.upper()  # PUT or CALL
                print(
                    f"  {record.trade_date} | {record.action:6} | {underlying:6} | {option_type:4} | "
                    f"${record.strike:>7.2f} | {record.expiration} | "
                    f"{record.quantity:>5} | ${record.price:>7.2f} | "
                    f"${record.gross_amount:>9.2f} | {pnl_str:>10}"
                )
            if len(result.trade_records) > 20:
                print(f"  ... (共 {len(result.trade_records)} 条)")

        assert result is not None
        assert result.trading_days > 0


if __name__ == "__main__":
    # 直接运行时也配置日志
    setup_verbose_logging()
    pytest.main([__file__, "-v", "-s"])
