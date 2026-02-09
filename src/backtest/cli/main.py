"""
Backtest CLI Main Entry Point - 回测命令行主入口

Usage:
    uv run backtest --help
    uv run backtest run --help
"""

import click

from src.backtest.cli.commands.run import run


@click.group()
@click.version_option(version="0.1.0", prog_name="backtest")
def cli() -> None:
    """回测系统命令行工具

    提供数据收集、回测执行、绩效计算和报告生成功能。

    \b
    示例:
        # 运行完整回测
        backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG

        # 仅检查数据状态
        backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG --check-only
    """
    pass


# 注册子命令
cli.add_command(run)


def main() -> None:
    """CLI 入口函数"""
    cli()


if __name__ == "__main__":
    main()
