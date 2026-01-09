"""
Screen Command - 开仓筛选命令

运行三层筛选漏斗，找出符合条件的开仓机会。
"""

import json
import logging
import sys
from datetime import datetime
from typing import Optional

import click

from src.business.screening.models import MarketType
from src.business.screening.pipeline import ScreeningPipeline
from src.business.notification.dispatcher import MessageDispatcher


logger = logging.getLogger(__name__)


# 默认标的列表
DEFAULT_US_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
DEFAULT_HK_SYMBOLS = ["2800.HK", "3033.HK", "0700.HK", "9988.HK", "9618.HK"]


@click.command()
@click.option(
    "--market",
    "-m",
    type=click.Choice(["us", "hk"], case_sensitive=False),
    default="us",
    help="市场类型：us (美股) 或 hk (港股)",
)
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(["short_put", "covered_call"], case_sensitive=False),
    default="short_put",
    help="策略类型：short_put 或 covered_call",
)
@click.option(
    "--symbols",
    "-S",
    multiple=True,
    help="要筛选的标的（可多次指定）。不指定则使用默认列表",
)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="筛选配置文件路径",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="是否推送结果到飞书",
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
def screen(
    market: str,
    strategy: str,
    symbols: tuple[str, ...],
    config: Optional[str],
    push: bool,
    output: str,
    verbose: bool,
) -> None:
    """运行开仓筛选

    三层漏斗筛选：市场环境 → 标的 → 合约

    \b
    示例：
      # 使用默认配置筛选美股
      optrade screen

      # 筛选港股 Short Put 机会
      optrade screen -m hk -s short_put

      # 指定标的并推送结果
      optrade screen -S AAPL -S MSFT --push

      # JSON 格式输出
      optrade screen -o json
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # 解析参数
    market_type = MarketType.US if market.lower() == "us" else MarketType.HK

    # 确定标的列表
    if symbols:
        symbol_list = list(symbols)
    else:
        symbol_list = DEFAULT_US_SYMBOLS if market_type == MarketType.US else DEFAULT_HK_SYMBOLS

    click.echo(f"📊 开始筛选 - {market.upper()} 市场 | {strategy} 策略")
    click.echo(f"📋 标的列表: {', '.join(symbol_list)}")
    click.echo("-" * 50)

    try:
        # 创建筛选管道
        pipeline = ScreeningPipeline(config_path=config)

        # 运行筛选
        result = pipeline.run(
            symbols=symbol_list,
            market_type=market_type,
            strategy_type=strategy,
        )

        # 输出结果
        if output == "json":
            _output_json(result)
        else:
            _output_text(result)

        # 推送结果
        if push:
            _push_result(result)

        # 设置退出码
        if result.passed and result.opportunities:
            sys.exit(0)  # 有机会
        else:
            sys.exit(1)  # 无机会

    except Exception as e:
        logger.exception("筛选过程出错")
        click.echo(f"❌ 错误: {e}", err=True)
        sys.exit(2)


def _output_text(result) -> None:
    """文本格式输出"""
    click.echo()

    # 市场状态
    if result.market_status:
        ms = result.market_status
        click.echo("📈 市场状态:")
        if ms.volatility_index:
            click.echo(f"   VIX: {ms.volatility_index.value:.1f}")
        click.echo(f"   趋势: {ms.overall_trend.value}")
        click.echo()

    # 筛选统计
    click.echo(f"📊 筛选统计:")
    click.echo(f"   扫描标的: {result.scanned_underlyings}")
    click.echo(f"   通过标的: {result.passed_underlyings}")
    click.echo(f"   发现机会: {len(result.opportunities)}")
    click.echo()

    # 机会列表
    if result.opportunities:
        click.echo("✅ 开仓机会:")
        click.echo("-" * 80)
        click.echo(f"{'标的':<10} {'行权价':<10} {'到期日':<12} {'DTE':<6} {'SAS':<8} {'Delta':<8} {'Sharpe':<8}")
        click.echo("-" * 80)

        for opp in result.opportunities:
            click.echo(
                f"{opp.symbol:<10} "
                f"{opp.strike:<10.2f} "
                f"{opp.expiry:<12} "
                f"{opp.dte:<6} "
                f"{(opp.sas or 0):<8.2f} "
                f"{(opp.delta or 0):<8.3f} "
                f"{(opp.sharpe_ratio or 0):<8.2f}"
            )
        click.echo("-" * 80)
    else:
        click.echo("❌ 未发现符合条件的开仓机会")
        if result.rejection_reason:
            click.echo(f"   原因: {result.rejection_reason}")


def _output_json(result) -> None:
    """JSON 格式输出"""
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "passed": result.passed,
        "market_status": None,
        "statistics": {
            "scanned_underlyings": result.scanned_underlyings,
            "passed_underlyings": result.passed_underlyings,
            "opportunities_count": len(result.opportunities),
        },
        "opportunities": [],
        "rejection_reason": result.rejection_reason,
    }

    # 市场状态
    if result.market_status:
        ms = result.market_status
        output_data["market_status"] = {
            "volatility_index": ms.volatility_index.value if ms.volatility_index else None,
            "overall_trend": ms.overall_trend.value,
            "term_structure": {
                "is_contango": ms.term_structure.is_contango,
                "ratio": ms.term_structure.ratio,
            } if ms.term_structure else None,
        }

    # 机会列表
    for opp in result.opportunities:
        output_data["opportunities"].append({
            "symbol": opp.symbol,
            "strike": opp.strike,
            "expiry": opp.expiry,
            "dte": opp.dte,
            "sas": opp.sas,
            "delta": opp.delta,
            "sharpe_ratio": opp.sharpe_ratio,
            "annual_return": opp.annual_return,
        })

    click.echo(json.dumps(output_data, indent=2, ensure_ascii=False))


def _push_result(result) -> None:
    """推送结果到飞书"""
    click.echo()
    click.echo("📤 推送结果到飞书...")

    try:
        dispatcher = MessageDispatcher()
        send_result = dispatcher.send_screening_result(result, force=True)

        if send_result.is_success:
            click.echo(f"✅ 推送成功: {send_result.message_id}")
        else:
            click.echo(f"❌ 推送失败: {send_result.error}")

    except Exception as e:
        click.echo(f"❌ 推送出错: {e}", err=True)
