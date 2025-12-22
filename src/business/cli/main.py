"""
CLI Main Entry Point - 命令行主入口

使用 Click 库构建命令行工具。
"""

import click

from src.business.cli.commands.screen import screen
from src.business.cli.commands.monitor import monitor
from src.business.cli.commands.notify import notify


@click.group()
@click.version_option(version="0.1.0", prog_name="optrade")
def cli() -> None:
    """期权量化交易系统 - 业务层命令行工具

    提供开仓筛选、持仓监控、通知推送等功能。
    """
    pass


# 注册子命令
cli.add_command(screen)
cli.add_command(monitor)
cli.add_command(notify)


if __name__ == "__main__":
    cli()
