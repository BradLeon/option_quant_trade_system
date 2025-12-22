"""
Monitor Command - 持仓监控命令

运行三层持仓监控，生成风险预警。
"""

import json
import logging
import sys
from datetime import datetime
from typing import Optional

import click

from src.business.monitoring.models import CapitalMetrics, PositionData
from src.business.monitoring.pipeline import MonitoringPipeline
from src.business.notification.dispatcher import MessageDispatcher


logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--positions",
    "-p",
    type=click.Path(exists=True),
    help="持仓数据 JSON 文件路径",
)
@click.option(
    "--capital",
    "-C",
    type=click.Path(exists=True),
    help="资金数据 JSON 文件路径",
)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="监控配置文件路径",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="是否推送预警到飞书",
)
@click.option(
    "--level",
    "-l",
    type=click.Choice(["all", "red", "yellow", "green"]),
    default="all",
    help="要显示的预警级别",
)
@click.option(
    "--output",
    "-o",
    type=click.Choice(["text", "json"]),
    default="text",
    help="输出格式",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
def monitor(
    positions: Optional[str],
    capital: Optional[str],
    config: Optional[str],
    push: bool,
    level: str,
    output: str,
    verbose: bool,
) -> None:
    """运行持仓监控

    三层监控：组合级 → 持仓级 → 资金级

    \b
    示例：
      # 使用示例数据运行监控
      optrade monitor

      # 从文件加载持仓数据
      optrade monitor -p positions.json -C capital.json

      # 只显示红色预警并推送
      optrade monitor -l red --push

      # JSON 格式输出
      optrade monitor -o json
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    click.echo("🔍 开始持仓监控")
    click.echo("-" * 50)

    try:
        # 加载数据
        position_list = _load_positions(positions)
        capital_metrics = _load_capital(capital)

        click.echo(f"📋 持仓数量: {len(position_list)}")
        click.echo()

        # 创建监控管道
        pipeline = MonitoringPipeline(config_path=config)

        # 运行监控
        result = pipeline.run(
            positions=position_list,
            capital_metrics=capital_metrics,
        )

        # 过滤预警级别
        if level != "all":
            result.alerts = [a for a in result.alerts if a.level.value == level]

        # 输出结果
        if output == "json":
            _output_json(result)
        else:
            _output_text(result)

        # 推送预警
        if push and result.alerts:
            _push_result(result)

        # 设置退出码
        if result.red_alerts:
            sys.exit(2)  # 有红色预警
        elif result.yellow_alerts:
            sys.exit(1)  # 有黄色预警
        else:
            sys.exit(0)  # 正常

    except Exception as e:
        logger.exception("监控过程出错")
        click.echo(f"❌ 错误: {e}", err=True)
        sys.exit(3)


def _load_positions(path: Optional[str]) -> list[PositionData]:
    """加载持仓数据"""
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [PositionData(**p) for p in data]

    # 返回示例数据
    return [
        PositionData(
            symbol="AAPL",
            position_type="short_put",
            quantity=-1,
            entry_price=3.50,
            current_price=2.80,
            strike=180.0,
            expiry="2025-01-17",
            underlying_price=185.0,
            delta=-0.25,
            gamma=0.02,
            theta=0.05,
            vega=-0.15,
            iv=0.28,
            dte=25,
        ),
        PositionData(
            symbol="MSFT",
            position_type="short_put",
            quantity=-2,
            entry_price=4.20,
            current_price=5.50,
            strike=400.0,
            expiry="2025-01-17",
            underlying_price=395.0,
            delta=-0.40,
            gamma=0.03,
            theta=0.08,
            vega=-0.20,
            iv=0.32,
            dte=25,
        ),
    ]


def _load_capital(path: Optional[str]) -> CapitalMetrics:
    """加载资金数据"""
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CapitalMetrics(**data)

    # 返回示例数据
    return CapitalMetrics(
        total_equity=100000.0,
        available_cash=50000.0,
        margin_used=25000.0,
        margin_available=75000.0,
        unrealized_pnl=1500.0,
        realized_pnl=3000.0,
        daily_pnl=200.0,
        max_drawdown=0.05,
        current_drawdown=0.02,
        sharpe_ratio=1.5,
        kelly_fraction=0.15,
        current_kelly_usage=0.10,
    )


def _output_text(result) -> None:
    """文本格式输出"""
    click.echo(f"📊 监控状态: {result.status.value}")
    click.echo()

    # 预警统计
    click.echo(f"⚠️ 预警统计:")
    click.echo(f"   🔴 红色: {len(result.red_alerts)}")
    click.echo(f"   🟡 黄色: {len(result.yellow_alerts)}")
    click.echo(f"   🟢 绿色: {len(result.green_alerts)}")
    click.echo()

    # 预警详情
    if result.alerts:
        click.echo("📋 预警详情:")
        click.echo("-" * 80)

        for alert in result.alerts:
            level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(alert.level.value, "⚪")
            symbol_str = f"[{alert.symbol}] " if alert.symbol else ""
            click.echo(f"{level_icon} {symbol_str}{alert.message}")

            if alert.current_value is not None and alert.threshold_value is not None:
                click.echo(f"   当前值: {alert.current_value:.2f} | 阈值: {alert.threshold_value:.2f}")

            if alert.suggested_action:
                click.echo(f"   建议: {alert.suggested_action}")

            click.echo()

        click.echo("-" * 80)
    else:
        click.echo("✅ 无预警，持仓状态正常")

    # 摘要
    if result.summary:
        click.echo()
        click.echo(f"📝 摘要: {result.summary}")


def _output_json(result) -> None:
    """JSON 格式输出"""
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "status": result.status.value,
        "statistics": {
            "total_alerts": len(result.alerts),
            "red_alerts": len(result.red_alerts),
            "yellow_alerts": len(result.yellow_alerts),
            "green_alerts": len(result.green_alerts),
        },
        "alerts": [],
        "summary": result.summary,
    }

    for alert in result.alerts:
        output_data["alerts"].append({
            "level": alert.level.value,
            "type": alert.alert_type.value,
            "symbol": alert.symbol,
            "message": alert.message,
            "current_value": alert.current_value,
            "threshold_value": alert.threshold_value,
            "suggested_action": alert.suggested_action,
        })

    click.echo(json.dumps(output_data, indent=2, ensure_ascii=False))


def _push_result(result) -> None:
    """推送预警到飞书"""
    click.echo()
    click.echo("📤 推送预警到飞书...")

    try:
        dispatcher = MessageDispatcher()
        send_results = dispatcher.send_monitoring_result(result, force=True)

        success_count = sum(1 for r in send_results if r.is_success)
        click.echo(f"✅ 推送完成: {success_count}/{len(send_results)} 条成功")

    except Exception as e:
        click.echo(f"❌ 推送出错: {e}", err=True)
