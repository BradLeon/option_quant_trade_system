"""
Trade Command - 交易命令

自动化交易模块的命令行接口。

⚠️  CRITICAL: 仅支持 Paper Trading (模拟账户)

命令:
- trade status: 显示交易系统状态
- trade process: 处理信号生成决策
- trade execute: 执行交易决策
- trade orders list: 列出订单
- trade orders cancel: 取消订单
"""

import json
import logging
from datetime import datetime
from typing import Optional

import click

from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.config.order_config import OrderConfig
from src.business.trading.models.decision import AccountState
from src.business.trading.models.order import OrderStatus
from src.business.trading.pipeline import TradingPipeline

logger = logging.getLogger(__name__)


def _get_mock_account_state() -> AccountState:
    """获取模拟账户状态 (用于演示)"""
    return AccountState(
        broker="ibkr",
        account_type="paper",
        total_equity=100000.0,
        cash_balance=50000.0,
        available_margin=40000.0,
        used_margin=10000.0,
        margin_utilization=0.10,
        cash_ratio=0.50,
        gross_leverage=1.5,
        total_position_count=5,
        option_position_count=3,
        stock_position_count=2,
        exposure_by_underlying={},
        timestamp=datetime.now(),
    )


@click.group()
def trade() -> None:
    """交易模块 - 信号处理与订单执行

    ⚠️  仅支持模拟账户 (Paper Trading)

    \b
    命令:
      status   显示交易系统状态
      process  处理信号生成决策
      execute  执行交易决策
      orders   订单管理
    """
    pass


@trade.command()
@click.option("--verbose", "-v", is_flag=True, help="显示详细信息")
@click.option("--json", "as_json", is_flag=True, help="JSON 格式输出")
def status(verbose: bool, as_json: bool) -> None:
    """显示交易系统状态"""
    try:
        pipeline = TradingPipeline()

        # 获取配置
        decision_config = DecisionConfig.load()
        order_config = OrderConfig.load()

        # 基本状态
        status_info = {
            "module": "trading",
            "mode": "paper_only",
            "execution_mode": order_config.execution_mode,
            "default_broker": decision_config.default_broker,
            "open_orders": len(pipeline.get_open_orders()),
            "timestamp": datetime.now().isoformat(),
        }

        # 尝试连接获取更多信息
        try:
            pipeline.connect()
            system_status = pipeline.get_system_status()
            status_info.update(system_status)
            pipeline.disconnect()
        except Exception as e:
            status_info["connection_error"] = str(e)

        if as_json:
            click.echo(json.dumps(status_info, indent=2))
        else:
            click.echo("\n===== Trading System Status =====")
            click.echo(f"Mode: {status_info['mode'].upper()}")
            click.echo(f"Execution: {status_info['execution_mode']}")
            click.echo(f"Default Broker: {status_info['default_broker']}")
            click.echo(f"Open Orders: {status_info['open_orders']}")

            if "connection_error" in status_info:
                click.echo(f"Connection: FAILED - {status_info['connection_error']}")
            elif status_info.get("connected"):
                click.echo(f"Connection: OK ({status_info.get('broker')})")
            else:
                click.echo("Connection: Not connected")

            click.echo(f"Timestamp: {status_info['timestamp']}")
            click.echo("=================================\n")

    except Exception as e:
        logger.exception("Failed to get status")
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@trade.command()
@click.option(
    "--source",
    type=click.Choice(["screen", "monitor", "both"]),
    default="both",
    help="信号来源",
)
@click.option("--dry-run", is_flag=True, default=True, help="仅生成决策，不执行")
@click.option("--auto-execute", is_flag=True, help="自动执行（适合 crontab）")
@click.option(
    "--market",
    "-m",
    type=click.Choice(["us", "hk", "all"]),
    default="all",
    help="市场",
)
@click.option("--json", "as_json", is_flag=True, help="JSON 格式输出")
def process(
    source: str,
    dry_run: bool,
    auto_execute: bool,
    market: str,
    as_json: bool,
) -> None:
    """处理交易信号并生成决策

    \b
    默认仅生成决策 (dry-run)，使用 --auto-execute 自动执行。

    \b
    示例:
      optrade trade process              # 生成决策，不执行
      optrade trade process --auto-execute  # 生成并自动执行
    """
    # TODO dry_run根本没用上？
    try:
        click.echo("\n===== Processing Trading Signals =====")
        click.echo(f"Source: {source}")
        click.echo(f"Market: {market}")
        click.echo(f"Mode: {'auto-execute' if auto_execute else 'dry-run'}")
        click.echo("")

        # 模拟账户状态
        account_state = _get_mock_account_state()

        # 创建 pipeline
        pipeline = TradingPipeline()

        # 这里应该从 Screen 和 Monitor 获取实际数据
        # 目前使用空数据演示
        
        decisions = pipeline.process_signals(
            screen_result=None,
            monitor_result=None,
            account_state=account_state,
        )

        if not decisions:
            click.echo("No decisions generated from signals.")
            click.echo("======================================\n")
            return

        # 显示决策
        click.echo(f"Generated {len(decisions)} decision(s):\n")

        for i, d in enumerate(decisions, 1):
            click.echo(f"  [{i}] {d.decision_id}")
            click.echo(f"      Type: {d.decision_type.value.upper()}")
            click.echo(f"      Symbol: {d.symbol}")
            click.echo(f"      Quantity: {d.quantity}")
            click.echo(f"      Price: {d.limit_price}")
            click.echo(f"      Priority: {d.priority.value}")
            click.echo(f"      Reason: {d.reason[:50]}...")
            click.echo("")

        # 执行
        if auto_execute:
            click.echo("Executing decisions...")
            try:
                with pipeline:
                    results = pipeline.execute_decisions(
                        decisions, account_state, dry_run=False
                    )
                click.echo(f"Executed {len(results)} order(s)")
            except Exception as e:
                click.echo(f"Execution failed: {e}", err=True)
        else:
            click.echo("Dry-run mode: decisions not executed.")
            click.echo("Use --auto-execute to execute, or:")
            click.echo("  optrade trade execute -d <decision_id> --confirm")

        click.echo("\n======================================\n")

    except Exception as e:
        logger.exception("Failed to process signals")
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@trade.command()
@click.option("--decision-id", "-d", help="执行指定决策")
@click.option("--all-pending", is_flag=True, help="执行所有待执行决策")
@click.option("--confirm", is_flag=True, required=True, help="确认执行")
def execute(
    decision_id: Optional[str],
    all_pending: bool,
    confirm: bool,
) -> None:
    """执行交易决策

    \b
    必须使用 --confirm 确认执行。

    \b
    示例:
      optrade trade execute -d DEC-xxx --confirm
      optrade trade execute --all-pending --confirm
    """
    # TODO confirm参数根本没用上？

    if not decision_id and not all_pending:
        click.echo("Error: Must specify --decision-id or --all-pending", err=True)
        raise SystemExit(1)

    try:
        click.echo("\n===== Executing Trading Decision =====")
        click.echo(f"Decision ID: {decision_id or 'all-pending'}")
        click.echo("⚠️  PAPER TRADING ONLY")
        click.echo("")

        pipeline = TradingPipeline()
        account_state = _get_mock_account_state()

        # 获取待执行决策
        # 实际实现应该从存储中读取
        decisions = pipeline.get_pending_decisions()

        if decision_id:
            decisions = [d for d in decisions if d.decision_id == decision_id]

        if not decisions:
            click.echo("No pending decisions found.")
            click.echo("Run 'optrade trade process' first to generate decisions.")
            return

        # 执行
        with pipeline:
            results = pipeline.execute_decisions(decisions, account_state)

        click.echo(f"\nExecuted {len(results)} order(s):")
        for record in results:
            order = record.order
            click.echo(f"  - {order.order_id}: {order.symbol} {order.status.value}")

        click.echo("\n======================================\n")

    except Exception as e:
        logger.exception("Failed to execute")
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@trade.group()
def orders() -> None:
    """订单管理"""
    pass


@orders.command("list")
@click.option(
    "--status",
    type=click.Choice(["open", "filled", "cancelled", "all"]),
    default="open",
    help="订单状态过滤",
)
@click.option("--days", type=int, default=7, help="查询天数")
@click.option("--json", "as_json", is_flag=True, help="JSON 格式输出")
def list_orders(status: str, days: int, as_json: bool) -> None:
    """列出订单"""
    try:
        pipeline = TradingPipeline()

        if status == "open":
            records = pipeline.get_open_orders()
        else:
            records = pipeline.get_recent_orders(days)
            if status != "all":
                status_enum = OrderStatus(status)
                records = [r for r in records if r.order.status == status_enum]

        if as_json:
            output = [r.to_dict() for r in records]
            click.echo(json.dumps(output, indent=2))
            return

        click.echo(f"\n===== Orders ({status}) =====")

        if not records:
            click.echo("No orders found.")
        else:
            for record in records:
                order = record.order
                click.echo(f"\n  Order: {order.order_id}")
                click.echo(f"    Symbol: {order.symbol}")
                click.echo(f"    Side: {order.side.value.upper()}")
                click.echo(f"    Qty: {order.quantity}")
                click.echo(f"    Status: {order.status.value}")
                click.echo(f"    Created: {order.created_at.strftime('%Y-%m-%d %H:%M')}")
                if record.broker_order_id:
                    click.echo(f"    Broker ID: {record.broker_order_id}")

        click.echo("\n==============================\n")

    except Exception as e:
        logger.exception("Failed to list orders")
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@orders.command()
@click.argument("order_id")
@click.option("--confirm", is_flag=True, required=True, help="确认取消")
def cancel(order_id: str, confirm: bool) -> None:
    """取消订单"""
    try:
        click.echo(f"\n===== Cancelling Order =====")
        click.echo(f"Order ID: {order_id}")

        pipeline = TradingPipeline()

        with pipeline:
            success = pipeline.cancel_order(order_id)

        if success:
            click.echo("Order cancelled successfully.")
        else:
            click.echo("Failed to cancel order.")

        click.echo("\n=============================\n")

    except Exception as e:
        logger.exception("Failed to cancel order")
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
