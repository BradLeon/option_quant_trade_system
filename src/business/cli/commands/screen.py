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

from src.business.config.screening_config import ScreeningConfig
from src.business.screening.models import MarketType
from src.business.screening.pipeline import ScreeningPipeline
from src.business.screening.stock_pool import StockPoolManager, StockPoolError
from src.business.notification.dispatcher import MessageDispatcher
from src.data.providers.unified_provider import UnifiedDataProvider


logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--market",
    "-m",
    type=click.Choice(["us", "hk", "all"], case_sensitive=False),
    default="all",
    help="市场：us, hk, 或 all (默认筛选所有市场)",
)
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(["short_put", "covered_call", "all"], case_sensitive=False),
    default="all",
    help="策略：short_put, covered_call, 或 all (默认筛选所有策略)",
)
@click.option(
    "--symbol",
    "-S",
    multiple=True,
    help="指定标的（可多次指定）。不指定则使用股票池",
)
@click.option(
    "--pool",
    "-p",
    type=str,
    help="股票池名称。不指定则使用对应市场的默认池",
)
@click.option(
    "--list-pools",
    is_flag=True,
    help="列出所有可用的股票池",
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
@click.option(
    "--skip-market-check",
    is_flag=True,
    help="跳过市场环境检查（调试用）",
)
def screen(
    market: str,
    strategy: str,
    symbol: tuple[str, ...],
    pool: Optional[str],
    list_pools: bool,
    push: bool,
    output: str,
    verbose: bool,
    skip_market_check: bool,
) -> None:
    """运行开仓筛选

    默认筛选所有市场 (US+HK)、所有策略 (Short Put + Covered Call)、所有股票池。

    \b
    示例：
      # 默认：筛选所有市场、所有策略、所有股票池
      optrade screen

      # 只筛选美股
      optrade screen -m us

      # 只筛选 Short Put 策略
      optrade screen -s short_put

      # 指定单个标的
      optrade screen -S AAPL

      # 组合使用
      optrade screen -m hk -s covered_call -S 9988.HK
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # 创建股票池管理器
    pool_manager = StockPoolManager()

    # 处理 --list-pools 选项
    if list_pools:
        _list_available_pools(pool_manager)
        sys.exit(0)

    # 解析市场和策略列表
    markets = ["us", "hk"] if market.lower() == "all" else [market.lower()]
    strategies = ["short_put", "covered_call"] if strategy.lower() == "all" else [strategy.lower()]

    click.echo("=" * 60)
    click.echo(f"📊 开仓筛选")
    click.echo(f"   市场: {', '.join(m.upper() for m in markets)}")
    click.echo(f"   策略: {', '.join(strategies)}")
    if skip_market_check:
        click.echo("   ⏭️  跳过市场环境检查")
    click.echo("=" * 60)

    # 创建 Provider（共享）
    provider = UnifiedDataProvider()

    all_results = []
    total_opportunities = 0

    try:
        for mkt in markets:
            market_type = MarketType.US if mkt == "us" else MarketType.HK

            # 确定标的列表
            if symbol:
                # 用户指定了标的，按市场过滤
                symbol_list = [s for s in symbol if _is_market_symbol(s, mkt)]
                if not symbol_list:
                    continue
                pool_name = None
            elif pool:
                try:
                    symbol_list = pool_manager.load_pool(pool)
                    pool_name = pool
                except StockPoolError as e:
                    click.echo(f"❌ 错误: {e}", err=True)
                    continue
            else:
                # 使用默认股票池
                pool_name = pool_manager.get_default_pool_name(market_type)
                symbol_list = pool_manager.get_default_pool(market_type)

            for strat in strategies:
                click.echo()
                click.echo("-" * 60)
                click.echo(f"🔍 {mkt.upper()} | {strat} | {len(symbol_list)} 只标的")
                click.echo("-" * 60)

                # 加载策略配置
                screening_config = ScreeningConfig.load(strat)

                # 创建筛选管道
                pipeline = ScreeningPipeline(screening_config, provider)

                # 运行筛选
                result = pipeline.run(
                    symbols=symbol_list,
                    market_type=market_type,
                    strategy_type=strat,
                    skip_market_check=skip_market_check,
                )

                # 统计
                qualified = [o for o in result.opportunities if o.passed] if result.opportunities else []
                total_opportunities += len(qualified)
                all_results.append({
                    "market": mkt,
                    "strategy": strat,
                    "result": result,
                    "qualified": qualified,
                })

                # 简要输出
                if qualified:
                    click.echo(f"   ✅ 发现 {len(qualified)} 个机会")
                    for opp in qualified[:3]:
                        click.echo(f"      - {opp.symbol} {opp.option_type.upper()}{opp.strike:.0f} "
                                   f"DTE={opp.dte} ROC={opp.expected_roc:.1%}" if opp.expected_roc else "")
                    if len(qualified) > 3:
                        click.echo(f"      ... 还有 {len(qualified) - 3} 个")
                else:
                    reason = result.rejection_reason or "无符合条件的合约"
                    click.echo(f"   ❌ {reason}")

        # 汇总输出
        click.echo()
        click.echo("=" * 60)
        click.echo(f"📊 筛选完成 - 共发现 {total_opportunities} 个机会")
        click.echo("=" * 60)

        if output == "json":
            _output_json_all(all_results)
        elif total_opportunities > 0:
            _output_text_summary(all_results)

        # 推送结果
        if push and total_opportunities > 0:
            for item in all_results:
                if item["qualified"]:
                    _push_result(item["result"])

        # 设置退出码
        sys.exit(0 if total_opportunities > 0 else 1)

    except Exception as e:
        logger.exception("筛选过程出错")
        click.echo(f"❌ 错误: {e}", err=True)
        sys.exit(2)


def _is_market_symbol(symbol: str, market: str) -> bool:
    """判断标的是否属于指定市场"""
    if market == "hk":
        return symbol.endswith(".HK")
    else:  # us
        return not symbol.endswith(".HK")


def _output_text(result) -> None:
    """文本格式输出"""
    click.echo()
    click.echo("=" * 80)
    click.echo(" 📊 筛选结果")
    click.echo("=" * 80)

    # Layer 1: 市场状态
    click.echo()
    click.echo("-" * 40)
    click.echo(" Layer 1: 市场环境")
    click.echo("-" * 40)
    if result.market_status:
        ms = result.market_status
        status_icon = "✅" if ms.is_favorable else "❌"
        click.echo(f"   状态: {status_icon} {'有利' if ms.is_favorable else '不利'}")
        if ms.volatility_index:
            vi = ms.volatility_index
            percentile_str = f" (百分位 {vi.percentile:.0%})" if vi.percentile else ""
            click.echo(f"   波动率: {vi.symbol}={vi.value:.1f}{percentile_str}")
        click.echo(f"   趋势: {ms.overall_trend.value}")
        if ms.term_structure:
            ts = ms.term_structure
            structure = "Contango" if ts.is_contango else "Backwardation"
            click.echo(f"   期限结构: {structure} (ratio={ts.ratio:.3f})")
        if ms.unfavorable_reasons:
            click.echo("   不利因素:")
            for reason in ms.unfavorable_reasons:
                click.echo(f"     - {reason}")
    else:
        click.echo("   ⏭️  已跳过")

    # Layer 2: 标的评估
    click.echo()
    click.echo("-" * 40)
    click.echo(" Layer 2: 标的评估")
    click.echo("-" * 40)
    click.echo(f"   扫描: {result.scanned_underlyings} 个")
    click.echo(f"   通过: {result.passed_underlyings} 个 ({result.passed_underlyings/max(1,result.scanned_underlyings)*100:.1f}%)")

    # 显示标的评分详情
    if result.underlying_scores:
        passed = [s for s in result.underlying_scores if s.passed]
        failed = [s for s in result.underlying_scores if not s.passed]

        if failed:
            click.echo("   淘汰标的:")
            for s in failed[:5]:
                reasons = ", ".join(s.disqualify_reasons) if s.disqualify_reasons else "未知原因"
                click.echo(f"     - {s.symbol}: {reasons}")
            if len(failed) > 5:
                click.echo(f"     ... 还有 {len(failed)-5} 个")

        if passed:
            click.echo("   通过标的 (按评分排序):")
            sorted_passed = sorted(passed, key=lambda x: x.composite_score, reverse=True)
            for i, s in enumerate(sorted_passed[:5], 1):
                iv_rank_str = f"IV Rank={s.iv_rank:.0f}%" if s.iv_rank else "IV=N/A"
                rsi_str = f"RSI={s.technical.rsi:.0f}" if s.technical and s.technical.rsi else ""
                click.echo(f"     {i}. {s.symbol} (score={s.composite_score:.1f}) - {iv_rank_str} {rsi_str}")

    # Layer 3: 合约筛选
    click.echo()
    click.echo("-" * 40)
    click.echo(" Layer 3: 合约筛选")
    click.echo("-" * 40)

    qualified = [o for o in result.opportunities if o.passed] if result.opportunities else []
    total_opps = len(result.opportunities) if result.opportunities else 0

    click.echo(f"   评估: {result.total_contracts_evaluated} 个合约")
    click.echo(f"   合格: {len(qualified)} 个")

    # 机会列表
    if qualified:
        click.echo()
        click.echo("=" * 80)
        click.echo(" ✅ 开仓机会 (按 ROC 排序)")
        click.echo("=" * 80)
        click.echo(f"{'标的':<8} {'到期':<8} {'类型':<6} {'行权价':<10} {'DTE':<5} {'OTM%':<7} {'Delta':<7} {'ROC':<8} {'SR':<6}")
        click.echo("-" * 80)

        # 按 expected_roc 排序
        sorted_opps = sorted(qualified, key=lambda x: x.expected_roc or 0, reverse=True)

        for opp in sorted_opps[:15]:
            exp_str = opp.expiry[5:] if opp.expiry else "N/A"
            opt_type = "PUT" if opp.option_type == "put" else "CALL"
            otm_str = f"{opp.otm_percent*100:.1f}%" if opp.otm_percent else "N/A"
            delta_str = f"{opp.delta:.2f}" if opp.delta else "N/A"
            roc_str = f"{opp.expected_roc*100:.1f}%" if opp.expected_roc else "N/A"
            sr_str = f"{opp.sharpe_ratio_annual:.2f}" if opp.sharpe_ratio_annual else "N/A"

            click.echo(
                f"{opp.symbol:<8} "
                f"{exp_str:<8} "
                f"{opt_type:<6} "
                f"{opp.strike:<10.0f} "
                f"{opp.dte:<5} "
                f"{otm_str:<7} "
                f"{delta_str:<7} "
                f"{roc_str:<8} "
                f"{sr_str:<6}"
            )

            # 显示警告
            if opp.warnings:
                click.echo(f"         ⚠️ {opp.warnings[0]}")

        if len(qualified) > 15:
            click.echo(f"... 还有 {len(qualified)-15} 个机会")

        click.echo("-" * 80)
    else:
        click.echo()
        click.echo("❌ 未发现符合条件的开仓机会")
        if result.rejection_reason:
            click.echo(f"   原因: {result.rejection_reason}")

        # 显示淘汰原因统计
        if result.opportunities:
            rejected = [o for o in result.opportunities if not o.passed]
            if rejected:
                # 统计淘汰原因
                reason_counts: dict[str, int] = {}
                for opp in rejected:
                    for reason in opp.disqualify_reasons:
                        # 提取原因类别 (如 "[P1] Delta" -> "Delta")
                        if "]" in reason:
                            category = reason.split("]")[1].strip().split("=")[0].split(" ")[0]
                        else:
                            category = reason.split("=")[0].strip()
                        reason_counts[category] = reason_counts.get(category, 0) + 1

                click.echo(f"   淘汰原因分布 ({len(rejected)} 个合约):")
                for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1])[:8]:
                    click.echo(f"     - {reason}: {count}")

                # 显示几个具体例子
                click.echo("   示例:")
                for o in rejected[:3]:
                    if o.disqualify_reasons:
                        click.echo(f"     - {o.symbol} {o.option_type.upper()}{o.strike:.0f}: {o.disqualify_reasons[0]}")

    click.echo()


def _output_json(result) -> None:
    """JSON 格式输出"""
    # 过滤出通过的机会
    qualified = [o for o in result.opportunities if o.passed] if result.opportunities else []

    output_data = {
        "timestamp": datetime.now().isoformat(),
        "passed": result.passed,
        "market_status": None,
        "statistics": {
            "scanned_underlyings": result.scanned_underlyings,
            "passed_underlyings": result.passed_underlyings,
            "total_evaluated": result.total_contracts_evaluated,
            "opportunities_count": len(qualified),
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

    # 机会列表（只包含通过的）
    for opp in qualified:
        output_data["opportunities"].append({
            "symbol": opp.symbol,
            "strike": opp.strike,
            "expiry": opp.expiry,
            "dte": opp.dte,
            "sas": opp.sas,
            "delta": opp.delta,
            "sharpe_ratio": opp.sharpe_ratio,
            "expected_roc": opp.expected_roc,
        })

    click.echo(json.dumps(output_data, indent=2, ensure_ascii=False))


def _output_json_all(all_results: list[dict]) -> None:
    """JSON 格式输出所有结果"""
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "results": [],
    }

    for item in all_results:
        result = item["result"]
        qualified = item["qualified"]
        output_data["results"].append({
            "market": item["market"],
            "strategy": item["strategy"],
            "opportunities_count": len(qualified),
            "opportunities": [
                {
                    "symbol": opp.symbol,
                    "strike": opp.strike,
                    "expiry": opp.expiry,
                    "dte": opp.dte,
                    "option_type": opp.option_type,
                    "delta": opp.delta,
                    "expected_roc": opp.expected_roc,
                }
                for opp in qualified
            ],
        })

    click.echo(json.dumps(output_data, indent=2, ensure_ascii=False))


def _output_text_summary(all_results: list[dict]) -> None:
    """文本格式汇总输出"""
    click.echo()
    click.echo("=" * 80)
    click.echo(" ✅ 开仓机会汇总")
    click.echo("=" * 80)

    for item in all_results:
        qualified = item["qualified"]
        if not qualified:
            continue

        click.echo()
        click.echo(f"📌 {item['market'].upper()} | {item['strategy']}")
        click.echo("-" * 80)
        click.echo(f"{'标的':<8} {'到期':<10} {'类型':<6} {'行权价':<10} {'DTE':<5} {'Delta':<7} {'ROC':<8}")
        click.echo("-" * 80)

        # 按 ROC 排序
        sorted_opps = sorted(qualified, key=lambda x: x.expected_roc or 0, reverse=True)

        for opp in sorted_opps[:10]:
            exp_str = opp.expiry if opp.expiry else "N/A"
            opt_type = "PUT" if opp.option_type == "put" else "CALL"
            delta_str = f"{opp.delta:.2f}" if opp.delta else "N/A"
            roc_str = f"{opp.expected_roc:.1%}" if opp.expected_roc else "N/A"

            click.echo(
                f"{opp.symbol:<8} "
                f"{exp_str:<10} "
                f"{opt_type:<6} "
                f"{opp.strike:<10.0f} "
                f"{opp.dte:<5} "
                f"{delta_str:<7} "
                f"{roc_str:<8}"
            )

        if len(qualified) > 10:
            click.echo(f"... 还有 {len(qualified) - 10} 个")

    click.echo()


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


def _list_available_pools(pool_manager: StockPoolManager) -> None:
    """列出所有可用的股票池"""
    click.echo("📦 可用股票池:")
    click.echo("-" * 60)

    # 美股池
    click.echo("\n🇺🇸 美股 (US):")
    us_pools = pool_manager.list_pools_by_market(MarketType.US)
    for pool_name in us_pools:
        try:
            info = pool_manager.get_pool_info(pool_name)
            default_marker = " (默认)" if pool_name == pool_manager.get_default_pool_name(MarketType.US) else ""
            click.echo(f"   {pool_name:<20} - {info['count']:>3} 只 | {info['description']}{default_marker}")
        except StockPoolError:
            pass

    # 港股池
    click.echo("\n🇭🇰 港股 (HK):")
    hk_pools = pool_manager.list_pools_by_market(MarketType.HK)
    for pool_name in hk_pools:
        try:
            info = pool_manager.get_pool_info(pool_name)
            default_marker = " (默认)" if pool_name == pool_manager.get_default_pool_name(MarketType.HK) else ""
            click.echo(f"   {pool_name:<20} - {info['count']:>3} 只 | {info['description']}{default_marker}")
        except StockPoolError:
            pass

    click.echo("\n" + "-" * 60)
    click.echo("使用方式: optrade screen --pool <pool_name>")
