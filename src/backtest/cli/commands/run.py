"""
Run Command - 运行回测 Pipeline

完整流程：数据收集 → 回测执行 → 绩效计算 → 报告生成

Usage:
    uv run backtest run \
        --name "SHORT_PUT_TEST" \
        --start 2025-12-01 \
        --end 2026-02-01 \
        --symbols GOOG --symbols SPY \
        --capital 1000000
"""

import logging
import sys
from datetime import date
from pathlib import Path

import click

from src.engine.models.enums import StrategyType


logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--name",
    "-n",
    required=True,
    help="回测名称",
)
@click.option(
    "--start",
    "-s",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="开始日期 (YYYY-MM-DD)",
)
@click.option(
    "--end",
    "-e",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="结束日期 (YYYY-MM-DD)",
)
@click.option(
    "--symbols",
    "-S",
    required=True,
    multiple=True,
    help="标的列表 (可多次指定)",
)
@click.option(
    "--data-dir",
    "-d",
    default="/Volumes/ORICO/option_quant",
    type=click.Path(exists=False),
    help="数据目录 (默认: /Volumes/ORICO/option_quant)",
)
@click.option(
    "--capital",
    "-c",
    default=1_000_000,
    type=int,
    help="初始资金 (默认: 1,000,000)",
)
@click.option(
    "--strategy",
    type=click.Choice(["short_put", "covered_call", "all"], case_sensitive=False),
    default="all",
    help="策略类型 (默认: all)",
)
@click.option(
    "--max-positions",
    default=20,
    type=int,
    help="最大持仓数 (默认: 20)",
)
@click.option(
    "--skip-download",
    is_flag=True,
    help="跳过数据下载检查",
)
@click.option(
    "--no-report",
    is_flag=True,
    help="不生成 HTML 报告",
)
@click.option(
    "--report-dir",
    default="reports",
    type=click.Path(),
    help="报告输出目录 (默认: reports)",
)
@click.option(
    "--check-only",
    is_flag=True,
    help="仅检查数据缺口，不运行回测",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="详细输出",
)
def run(
    name: str,
    start,
    end,
    symbols: tuple[str, ...],
    data_dir: str,
    capital: int,
    strategy: str,
    max_positions: int,
    skip_download: bool,
    no_report: bool,
    report_dir: str,
    check_only: bool,
    verbose: bool,
) -> None:
    """运行回测 Pipeline

    自动完成数据收集、回测执行、绩效计算和报告生成。

    \b
    示例:
        # 完整运行
        uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG -S SPY

        # 仅检查数据
        uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG --check-only

        # 跳过数据下载
        uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download
    """
    # 设置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # 验证数据目录
    data_path = Path(data_dir)
    if not data_path.exists():
        click.echo(f"Error: Data directory not found: {data_dir}", err=True)
        click.echo("Please ensure the external drive is connected.", err=True)
        sys.exit(1)

    # 解析日期
    start_date: date = start.date()
    end_date: date = end.date()

    if start_date >= end_date:
        click.echo("Error: Start date must be before end date.", err=True)
        sys.exit(1)

    # 解析策略类型
    strategy_types: list[StrategyType] = []
    if strategy == "short_put":
        strategy_types = [StrategyType.SHORT_PUT]
    elif strategy == "covered_call":
        strategy_types = [StrategyType.COVERED_CALL]
    else:  # all
        strategy_types = [StrategyType.SHORT_PUT, StrategyType.COVERED_CALL]

    # 创建配置
    from src.backtest.config.backtest_config import BacktestConfig

    config = BacktestConfig(
        name=name,
        description=f"Backtest via CLI: {name}",
        start_date=start_date,
        end_date=end_date,
        symbols=list(symbols),
        data_dir=str(data_path),
        initial_capital=capital,
        max_positions=max_positions,
        strategy_types=strategy_types,
    )

    # 创建 Pipeline
    from src.backtest.pipeline import BacktestPipeline

    pipeline = BacktestPipeline(config)

    # 仅检查数据
    if check_only:
        pipeline.print_data_status()
        return

    # 运行 Pipeline
    try:
        result = pipeline.run(
            skip_data_check=skip_download,
            generate_report=not no_report,
            report_dir=report_dir,
            verbose=verbose,
        )

        # 打印结果摘要
        click.echo("\n" + "=" * 60)
        click.echo("Backtest Results")
        click.echo("=" * 60)
        click.echo(f"Name: {name}")
        click.echo(f"Period: {start_date} ~ {end_date}")
        click.echo(f"Symbols: {list(symbols)}")
        click.echo()

        metrics = result.metrics
        click.echo(f"Total Return: {metrics.total_return_pct:.2%}")

        if metrics.annualized_return:
            click.echo(f"Annualized Return: {metrics.annualized_return:.2%}")
        if metrics.max_drawdown:
            click.echo(f"Max Drawdown: {metrics.max_drawdown:.2%}")
        if metrics.sharpe_ratio:
            click.echo(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
        if metrics.win_rate:
            click.echo(f"Win Rate: {metrics.win_rate:.1%}")

        if result.benchmark_result:
            br = result.benchmark_result
            excess = br.strategy_total_return - br.benchmark_total_return
            click.echo()
            click.echo(f"vs SPY: {br.strategy_total_return:.2%} vs {br.benchmark_total_return:.2%}")
            click.echo(f"Excess Return: {excess:.2%}")

        if result.attribution_summary:
            summary = result.attribution_summary
            click.echo()
            click.echo("Attribution:")
            click.echo(f"  Delta PnL: ${summary.get('delta_pnl', 0):,.0f}")
            click.echo(f"  Gamma PnL: ${summary.get('gamma_pnl', 0):,.0f}")
            click.echo(f"  Theta PnL: ${summary.get('theta_pnl', 0):,.0f}")
            click.echo(f"  Vega PnL:  ${summary.get('vega_pnl', 0):,.0f}")
            click.echo(f"  Residual:  ${summary.get('residual', 0):,.0f}")

        if result.report_path:
            click.echo()
            click.echo(f"Report: {result.report_path}")
            click.echo(f"Open: file://{result.report_path.absolute()}")

        click.echo("=" * 60)

    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)
    except Exception as e:
        click.echo(f"\nError: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
