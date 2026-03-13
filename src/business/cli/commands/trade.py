"""
Trade Command - 交易命令

自动化交易模块的命令行接口。

⚠️  CRITICAL: 仅支持 Paper Trading (模拟账户)

命令:
- trade screen: Screen → Trade 全流程 (开仓)
- trade monitor: Monitor → Trade 全流程 (调仓)
- trade status: 显示交易系统状态
- trade process: 处理信号生成决策
- trade execute: 执行交易决策
- trade orders list: 列出订单
- trade orders cancel: 取消订单

使用示例:
=========

# Screen → Trade (筛选并开仓)
optrade trade screen                                 # 所有市场、所有策略 (dry-run)
optrade trade screen -m us                           # 只筛选 US 市场
optrade trade screen -s short_put                    # 只筛选 Short Put 策略
optrade trade screen -S AAPL -S NVDA                 # 指定标的
optrade trade screen --execute                       # 执行下单
optrade trade screen --execute -y                    # 执行下单，跳过确认
optrade trade screen --skip-market-check             # 跳过市场环境检查

# Monitor → Trade (监控并调仓)
optrade trade monitor                                # IMMEDIATE 级别 (dry-run)
optrade trade monitor -u all                         # 所有级别 (dry-run)
optrade trade monitor --execute                      # 执行下单
optrade trade monitor --execute -y                   # 执行下单，跳过确认
optrade trade monitor -v                             # 详细日志

# 通用选项
--dry-run          仅生成决策，不下单 (默认)
--execute          执行下单 (覆盖 dry-run)
-y, --yes          跳过确认直接执行
--push/--no-push   推送结果到飞书
-v, --verbose      显示详细日志
"""

import json
import logging
import sys
from datetime import datetime
from typing import Optional

import click

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.models.decision import AccountState, DecisionType
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
      screen   Screen → Trade 全流程 (开仓)
      monitor  Monitor → Trade 全流程 (调仓)
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
        order_config = OrderConfig.load()

        # 基本状态
        status_info = {
            "module": "trading",
            "mode": "paper_only",
            "execution_mode": order_config.execution_mode,
            "default_broker": "ibkr",
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


@trade.command("screen")
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
    "--dry-run",
    is_flag=True,
    default=True,
    help="仅生成决策，不下单 (默认)",
)
@click.option(
    "--execute",
    is_flag=True,
    help="执行下单 (覆盖 dry-run)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="跳过确认直接执行",
)
@click.option(
    "--skip-market-check",
    is_flag=True,
    help="跳过市场环境检查（调试用）",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="推送结果到飞书",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
def trade_screen(
    market: str,
    strategy: str,
    symbol: tuple[str, ...],
    dry_run: bool,
    execute: bool,
    yes: bool,
    skip_market_check: bool,
    push: bool,
    verbose: bool,
) -> None:
    """Screen → Trade 全流程

    连接 IBKR Paper Account，运行三层筛选，生成开仓决策并提交订单。

    \b
    默认筛选所有市场 (US+HK)、所有策略 (Short Put + Covered Call)。

    \b
    示例:
      # 默认：筛选所有市场、所有策略 (dry-run)
      optrade trade screen

      # 只筛选 US Short Put
      optrade trade screen -m us -s short_put

      # 指定标的
      optrade trade screen -S AAPL -S NVDA

      # 筛选并执行
      optrade trade screen --execute

      # 跳过市场环境检查
      optrade trade screen --skip-market-check

      # 跳过确认
      optrade trade screen --execute -y
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # execute 覆盖 dry_run
    effective_dry_run = dry_run and not execute

    # 解析市场和策略列表
    markets = ["us", "hk"] if market.lower() == "all" else [market.lower()]
    strategy_strs = ["short_put", "covered_call"] if strategy.lower() == "all" else [strategy.lower()]

    click.echo("\n" + "=" * 60)
    click.echo("📊 Trade Screen (Screen → Trade 全流程)")
    click.echo(f"   市场: {', '.join(m.upper() for m in markets)}")
    click.echo(f"   策略: {', '.join(strategy_strs)}")
    if symbol:
        click.echo(f"   标的: {', '.join(symbol)}")
    click.echo(f"   模式: {'DRY-RUN' if effective_dry_run else '🔴 EXECUTE'}")
    click.echo("=" * 60)

    try:
        # 1. 连接 IBKR Paper Account
        from src.data.providers.broker_manager import BrokerManager
        from src.data.models.account import AccountType as AccType

        click.echo("\n📡 连接 IBKR Paper Account...")
        manager = BrokerManager(account_type="paper")
        conn = manager.connect(ibkr=True, futu=False)

        if not conn.ibkr:
            raise click.ClickException(f"IBKR 连接失败: {conn.ibkr_error}")

        click.echo(f"  ✅ 连接成功")

        # 2. 运行三层筛选 (先筛选，再获取账户状态，避免无机会时浪费时间获取持仓)
        from src.business.config.screening_config import ScreeningConfig
        from src.business.screening.models import MarketType
        from src.business.screening.pipeline import ScreeningPipeline
        from src.business.screening.stock_pool import StockPoolManager
        from src.data.providers.unified_provider import UnifiedDataProvider
        from src.engine.models.enums import StrategyType

        click.echo(f"\n🔍 运行三层筛选...")

        pool_manager = StockPoolManager()
        all_confirmed = []
        all_screen_results = []

        with UnifiedDataProvider(ibkr_provider=conn.ibkr) as provider:
            for mkt in markets:
                market_type = MarketType.US if mkt == "us" else MarketType.HK

                # 确定标的列表
                if symbol:
                    # 用户指定了标的，按市场过滤
                    symbol_list = [s.upper() for s in symbol if _is_market_symbol(s, mkt)]
                    if not symbol_list:
                        continue
                    pool_name = f"自定义 ({len(symbol_list)} 只)"
                else:
                    # 使用默认股票池
                    symbol_list = pool_manager.get_default_pool(market_type)
                    pool_name = pool_manager.get_default_pool_name(market_type)

                for strat_str in strategy_strs:
                    strategy_type = StrategyType.from_string(strat_str)

                    click.echo(f"\n   {mkt.upper()} | {strat_str} | {pool_name} ({len(symbol_list)} 只)")

                    # 创建筛选管道
                    config = ScreeningConfig.load(strat_str)
                    pipeline = ScreeningPipeline(config, provider)
                    screen_result = pipeline.run(
                        symbols=symbol_list,
                        market_type=market_type,
                        strategy_type=strategy_type,
                        skip_market_check=skip_market_check,
                    )

                    # 检查筛选结果
                    if not screen_result.passed:
                        market_status = screen_result.market_status
                        status_str = "不利" if market_status and not market_status.is_favorable else "未知"
                        click.echo(f"      ⚠️  市场环境{status_str}")
                        continue

                    confirmed = screen_result.confirmed or []
                    if confirmed:
                        click.echo(f"      ✅ 确认 {len(confirmed)} 个机会")
                        all_confirmed.extend(confirmed)
                        all_screen_results.append(screen_result)
                    else:
                        click.echo(f"      ❌ 无符合条件的合约")

        # 检查是否有任何机会 (无机会则直接退出，无需获取持仓)
        if not all_confirmed:
            click.echo("\n📋 无符合条件的开仓机会")
            _cleanup_connection(conn)
            return

        click.echo(f"\n📊 共发现 {len(all_confirmed)} 个开仓机会")

        # 3. 获取账户状态 (跳过 Greeks 计算，仅需 NLV/cash/margin 等汇总指标)
        from src.business.trading.account_bridge import portfolio_to_account_state

        aggregator = conn.get_aggregator()
        portfolio = aggregator.get_consolidated_portfolio(
            account_type=AccType.PAPER, fetch_greeks=False
        )
        account_state = portfolio_to_account_state(portfolio, broker="ibkr")

        click.echo(f"\n💰 账户状态:")
        click.echo(f"   NLV: ${account_state.total_equity:,.2f}")
        click.echo(f"   Cash: ${account_state.cash_balance:,.2f}")
        click.echo(f"   Available Margin: ${account_state.available_margin:,.2f}")
        click.echo(f"   Used Margin: ${account_state.used_margin:,.2f}")
        click.echo(f"   Margin Utilization: {account_state.margin_utilization:.1%}")
        click.echo(f"   Cash Ratio: {account_state.cash_ratio:.1%}")
        click.echo(f"   Positions: {account_state.total_position_count}")

        # Debug: Show raw broker summary data
        if verbose and "ibkr" in portfolio.by_broker:
            summary = portfolio.by_broker["ibkr"]
            click.echo(f"\n   [DEBUG] Raw IBKR Summary:")
            click.echo(f"     margin_available: {summary.margin_available}")
            click.echo(f"     buying_power: {summary.buying_power}")
            click.echo(f"     margin_used: {summary.margin_used}")

        # 显示筛选结果详情
        _print_screen_summary(all_confirmed)

        # 4. 生成决策 (使用第一个有结果的 screen_result 作为基础)
        click.echo(f"\n📋 生成决策...")
        trading_pipeline = TradingPipeline()

        # 合并所有 screen_result 的 confirmed 到第一个结果
        merged_screen_result = all_screen_results[0]
        merged_screen_result.confirmed = all_confirmed

        decisions = trading_pipeline.process_signals(
            screen_result=merged_screen_result,
            monitor_result=None,
            account_state=account_state,
        )

        if not decisions:
            click.echo("   ⚠️  无有效决策 (可能被账户风控拒绝)")
            _cleanup_connection(conn)
            return

        # 显示决策
        click.echo(f"\n   生成 {len(decisions)} 个决策:")
        for i, d in enumerate(decisions, 1):
            # 构建合约标识
            opt_type = "PUT" if d.option_type == "put" else "CALL"
            strike_str = f"{d.strike:.0f}" if d.strike and d.strike == int(d.strike) else f"{d.strike}"
            exp_str = d.expiry.replace("-", "") if d.expiry else "N/A"

            click.echo(f"\n   [{i}] {d.decision_type.value.upper()} {d.underlying} {opt_type} K={strike_str} Exp={exp_str}")
            click.echo(f"       Symbol: {d.symbol}")
            click.echo(f"       TradingClass: {d.trading_class or 'N/A'}, ConId: {d.con_id or 'N/A'}")
            click.echo(f"       Qty: {d.quantity}, Price: ${d.limit_price or 0:.2f}")
            click.echo(f"       {d.reason}")

        # 5. 执行或显示
        if effective_dry_run:
            click.echo(f"\n[DRY-RUN] 以上决策不会执行。")
            click.echo("使用 --execute 执行下单。")
        else:
            # 确认
            if not yes:
                click.echo(f"\n⚠️  即将提交 {len(decisions)} 个订单到 IBKR Paper Account")
                if not click.confirm("确认执行?"):
                    click.echo("已取消")
                    _cleanup_connection(conn)
                    return

            click.echo(f"\n📤 提交订单...")
            with trading_pipeline:
                results = trading_pipeline.execute_decisions(
                    decisions, account_state, dry_run=False
                )

            # 显示结果
            success_count = sum(1 for r in results if r.order.status == OrderStatus.SUBMITTED)
            click.echo(f"\n   ✅ 提交成功: {success_count}/{len(results)}")
            for r in results:
                status_icon = "✅" if r.order.status == OrderStatus.SUBMITTED else "❌"
                click.echo(f"   {status_icon} {r.order.symbol}: {r.order.status.value}")
                if r.broker_order_id:
                    click.echo(f"       broker_id: {r.broker_order_id}, broker_status: {r.broker_status}")
                if r.error_message:
                    click.echo(f"       error: {r.error_message}")

        # 推送结果
        if push:
            click.echo(f"\n📤 推送到飞书...")
            if effective_dry_run:
                # Dry-run 模式：推送决策
                _push_trade_decisions(
                    decisions,
                    dry_run=True,
                    command="screen",
                    market=market,
                    strategy=strategy,
                )
            else:
                # 执行模式：推送执行结果
                _push_trade_results(
                    results,
                    command="screen",
                    market=market,
                    strategy=strategy,
                )

        click.echo("\n" + "=" * 60)
        click.echo("✅ 完成")
        click.echo("=" * 60 + "\n")

    except click.ClickException:
        raise
    except Exception as e:
        logger.exception("Trade screen failed")
        click.echo(f"\n❌ 错误: {e}", err=True)
        sys.exit(1)
    finally:
        if "conn" in locals():
            _cleanup_connection(conn)


def _cleanup_connection(conn) -> None:
    """清理 broker 连接"""
    try:
        if conn.ibkr:
            conn.ibkr.disconnect()
    except Exception:
        pass


def _is_market_symbol(symbol: str, market: str) -> bool:
    """判断标的是否属于指定市场"""
    s = symbol.upper()
    if market == "hk":
        return s.endswith(".HK")
    else:  # us
        return not s.endswith(".HK")


def _push_trade_decisions(
    decisions: list,
    dry_run: bool,
    command: str = "screen",
    market: str = "",
    strategy: str = "",
) -> None:
    """推送交易决策到飞书

    Args:
        decisions: 决策列表
        dry_run: 是否为 dry-run 模式
        command: 命令类型 (screen/monitor)
        market: 市场 (us/hk)
        strategy: 策略
    """
    try:
        from src.business.notification.dispatcher import MessageDispatcher

        dispatcher = MessageDispatcher()
        send_result = dispatcher.send_trade_decisions(
            decisions,
            dry_run=dry_run,
            command=command,
            market=market,
            strategy=strategy,
            force=True,
        )

        if send_result.is_success:
            click.echo(f"  ✅ 决策推送成功")
        else:
            click.echo(f"  ⚠️ 决策推送失败: {send_result.error}")

    except Exception as e:
        logger.warning(f"Failed to push decisions: {e}")
        click.echo(f"  ⚠️ 决策推送异常: {e}")


def _push_trade_results(
    results: list,
    command: str = "screen",
    market: str = "",
    strategy: str = "",
) -> None:
    """推送执行结果到飞书

    Args:
        results: 订单记录列表
        command: 命令类型 (screen/monitor)
        market: 市场 (us/hk)
        strategy: 策略
    """
    try:
        from src.business.notification.dispatcher import MessageDispatcher

        dispatcher = MessageDispatcher()
        send_result = dispatcher.send_trade_results(
            results,
            command=command,
            market=market,
            strategy=strategy,
            force=True,
        )

        if send_result.is_success:
            click.echo(f"  ✅ 结果推送成功")
        else:
            click.echo(f"  ⚠️ 结果推送失败: {send_result.error}")

    except Exception as e:
        logger.warning(f"Failed to push results: {e}")
        click.echo(f"  ⚠️ 结果推送异常: {e}")


def _print_screen_summary(confirmed: list, max_show: int = 10) -> None:
    """打印筛选结果的合约详情

    Args:
        confirmed: 确认的合约机会列表 (ContractOpportunity)
        max_show: 最多显示的数量
    """
    click.echo()
    click.echo("=" * 80)
    click.echo(" 📋 筛选结果详情 (按 Expected ROC 排序)")
    click.echo("=" * 80)

    # 按 ROC 排序
    sorted_opps = sorted(confirmed, key=lambda x: x.expected_roc or 0, reverse=True)

    for i, opp in enumerate(sorted_opps[:max_show], 1):
        _print_opportunity_card(opp, i)

    if len(confirmed) > max_show:
        click.echo(f"\n... 还有 {len(confirmed) - max_show} 个机会未显示")

    click.echo()


def _print_opportunity_card(opp, index: int) -> None:
    """打印单个合约机会的详细卡片"""
    opt_type = "CALL" if opp.option_type == "call" else "PUT"
    exp_str = opp.expiry if opp.expiry else "N/A"
    strike_str = f"{opp.strike:.0f}" if opp.strike == int(opp.strike) else f"{opp.strike}"

    # 标题行
    click.echo()
    click.echo(f"┌─ #{index} {opp.symbol} {opt_type} {strike_str} @ {exp_str} (DTE={opp.dte})")
    click.echo("├" + "─" * 79)

    # 核心策略指标行 - 收益指标
    roc_str = f"{opp.expected_roc:.1%}" if opp.expected_roc else "N/A"
    ann_roc_str = f"{opp.annual_roc:.1%}" if opp.annual_roc else "N/A"
    win_str = f"{opp.win_probability:.1%}" if opp.win_probability else "N/A"
    kelly_str = f"{opp.kelly_fraction:.2f}" if opp.kelly_fraction else "N/A"

    click.echo(f"│ 收益: ExpROC={roc_str}  AnnROC={ann_roc_str}  WinP={win_str}  Kelly={kelly_str}")

    # 风险效率指标行
    tgr_str = f"{opp.tgr:.2f}" if opp.tgr else "N/A"
    tm_str = f"{opp.theta_margin_ratio:.4f}" if opp.theta_margin_ratio else "N/A"
    sr_str = f"{opp.sharpe_ratio_annual:.2f}" if opp.sharpe_ratio_annual else "N/A"
    rate_str = f"{opp.premium_rate:.2%}" if opp.premium_rate else "N/A"

    click.echo(f"│ 效率: TGR={tgr_str}  Θ/Margin={tm_str}  Sharpe={sr_str}  PremRate={rate_str}")

    # 合约行情
    price_str = f"{opp.underlying_price:.2f}" if opp.underlying_price else "N/A"
    premium_str = f"{opp.mid_price:.2f}" if opp.mid_price else "N/A"
    bid_str = f"{opp.bid:.2f}" if opp.bid else "N/A"
    ask_str = f"{opp.ask:.2f}" if opp.ask else "N/A"
    iv_str = f"{opp.iv:.1%}" if opp.iv else "N/A"

    click.echo(f"│ 行情: S={price_str}  Premium={premium_str}  Bid/Ask={bid_str}/{ask_str}  IV={iv_str}")

    # Greeks
    delta_str = f"{opp.delta:.3f}" if opp.delta else "N/A"
    gamma_str = f"{opp.gamma:.4f}" if opp.gamma else "N/A"
    theta_str = f"{opp.theta:.3f}" if opp.theta else "N/A"
    oi_str = f"{opp.open_interest}" if opp.open_interest else "N/A"
    otm_str = f"{opp.otm_percent:.1%}" if opp.otm_percent else "N/A"

    click.echo(f"│ Greeks: Δ={delta_str}  Γ={gamma_str}  Θ={theta_str}  OI={oi_str}  OTM={otm_str}")

    # 警告信息
    if opp.warnings:
        click.echo(f"│ ⚠️  {opp.warnings[0]}")

    click.echo("└" + "─" * 79)


@trade.command("monitor")
@click.option(
    "--account-type",
    "-a",
    type=click.Choice(["paper", "live"]),
    default="paper",
    help="账户类型：paper（模拟）或 live（真实）",
)
@click.option(
    "--urgency",
    "-u",
    type=click.Choice(["immediate", "soon", "all"]),
    default="immediate",
    help="处理的紧急级别: immediate(立即), soon(尽快), all(全部)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=True,
    help="仅生成决策，不下单 (默认)",
)
@click.option(
    "--execute",
    is_flag=True,
    help="执行下单 (覆盖 dry-run)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="跳过确认直接执行",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="推送结果到飞书",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
def trade_monitor(
    account_type: str,
    urgency: str,
    dry_run: bool,
    execute: bool,
    yes: bool,
    push: bool,
    verbose: bool,
) -> None:
    """Monitor → Trade 全流程

    连接 IBKR Paper Account，运行三层监控，生成调仓决策并提交订单。

    \b
    示例:
      # 处理 IMMEDIATE 级别建议 (dry-run)
      optrade trade monitor

      # 处理所有建议并执行
      optrade trade monitor --urgency all --execute

      # 跳过确认
      optrade trade monitor --execute -y
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # execute 覆盖 dry_run
    effective_dry_run = dry_run and not execute

    # 转换 account_type 字符串为枚举
    from src.data.models.account import AccountType as AccType
    acc_type_enum = AccType.PAPER if account_type == "paper" else AccType.LIVE
    acc_type_label = "Paper" if account_type == "paper" else "Live"

    click.echo("\n" + "=" * 60)
    click.echo("📊 Trade Monitor (Monitor → Trade 全流程)")
    click.echo(f"   账户类型: {acc_type_label}")
    click.echo(f"   紧急级别: {urgency.upper()}")
    click.echo(f"   模式: {'DRY-RUN' if effective_dry_run else '🔴 EXECUTE'}")
    click.echo("=" * 60)

    try:
        # 1. 连接 IBKR Account
        from src.data.providers.broker_manager import BrokerManager

        click.echo(f"\n📡 连接 IBKR {acc_type_label} Account...")
        manager = BrokerManager(account_type=account_type)
        conn = manager.connect(ibkr=True, futu=False)

        if not conn.ibkr:
            raise click.ClickException(f"IBKR 连接失败: {conn.ibkr_error}")

        click.echo(f"  ✅ 连接成功")

        # 2. 获取真实账户状态和持仓
        from src.business.trading.account_bridge import portfolio_to_account_state
        from src.business.monitoring.data_bridge import MonitoringDataBridge
        from src.data.providers.unified_provider import UnifiedDataProvider
        from src.engine.account.metrics import calc_capital_metrics

        aggregator = conn.get_aggregator()
        portfolio = aggregator.get_consolidated_portfolio(account_type=acc_type_enum)
        account_state = portfolio_to_account_state(portfolio, broker="ibkr")

        click.echo(f"\n💰 账户状态:")
        click.echo(f"   NLV: ${account_state.total_equity:,.2f}")
        click.echo(f"   Cash: ${account_state.cash_balance:,.2f}")
        click.echo(f"   Available Margin: ${account_state.available_margin:,.2f}")
        click.echo(f"   Used Margin: ${account_state.used_margin:,.2f}")
        click.echo(f"   Margin Utilization: {account_state.margin_utilization:.1%}")
        click.echo(f"   Cash Ratio: {account_state.cash_ratio:.1%}")
        click.echo(f"   Positions: {account_state.total_position_count}")

        # Debug: Show raw broker summary data
        if verbose and "ibkr" in portfolio.by_broker:
            summary = portfolio.by_broker["ibkr"]
            click.echo(f"\n   [DEBUG] Raw IBKR Summary:")
            click.echo(f"     margin_available: {summary.margin_available}")
            click.echo(f"     buying_power: {summary.buying_power}")
            click.echo(f"     margin_used: {summary.margin_used}")

        # 3. 运行三层监控
        from src.business.monitoring.pipeline import MonitoringPipeline
        from src.business.monitoring.suggestions import UrgencyLevel

        click.echo(f"\n🔍 运行三层监控...")

        # 转换持仓数据
        unified_provider = UnifiedDataProvider(ibkr_provider=conn.ibkr)
        bridge = MonitoringDataBridge(
            data_provider=unified_provider,
            ibkr_provider=conn.ibkr,
        )
        position_list = bridge.convert_positions(portfolio)
        capital_metrics = calc_capital_metrics(portfolio)

        click.echo(f"   监控 {len(position_list)} 个持仓")

        # 运行监控
        monitor_pipeline = MonitoringPipeline()
        monitor_result = monitor_pipeline.run(
            positions=position_list,
            capital_metrics=capital_metrics,
        )

        click.echo(f"   状态: {monitor_result.status.value}")
        click.echo(f"   预警: 🔴 {len(monitor_result.red_alerts)} 🟡 {len(monitor_result.yellow_alerts)} 🟢 {len(monitor_result.green_alerts)}")

        # 过滤建议
        suggestions = monitor_result.suggestions or []
        if urgency != "all":
            urgency_level = UrgencyLevel.IMMEDIATE if urgency == "immediate" else UrgencyLevel.SOON
            suggestions = [s for s in suggestions if s.urgency == urgency_level]

        click.echo(f"   建议: {len(suggestions)} 个 ({urgency} 级别)")

        if not suggestions:
            click.echo("\n📋 无需调仓的建议")
            _cleanup_connection(conn)
            return

        # 显示建议
        click.echo(f"\n📋 调仓建议:")
        for i, s in enumerate(suggestions, 1):
            urgency_icon = {"immediate": "🚨", "soon": "⚡", "monitor": "👁️"}.get(s.urgency.value, "📌")
            click.echo(f"\n   [{i}] {urgency_icon} {s.action.value.upper()} {s.symbol}")
            click.echo(f"       原因: {s.reason[:60]}...")

        # 4. 生成决策
        click.echo(f"\n📋 生成决策...")
        trading_pipeline = TradingPipeline()
        decisions = trading_pipeline.process_signals(
            screen_result=None,
            monitor_result=monitor_result,
            account_state=account_state,
            suggestions=suggestions,
        )

        # 过滤掉 HOLD 类型
        decisions = [d for d in decisions if d.decision_type != DecisionType.HOLD]

        if not decisions:
            click.echo("   ⚠️  无需执行的决策 (全部为 HOLD 或被过滤)")
            _cleanup_connection(conn)
            return

        # 显示决策
        click.echo(f"\n   生成 {len(decisions)} 个决策:")
        for i, d in enumerate(decisions, 1):
            # 构建合约标识
            opt_type = d.option_type.upper() if d.option_type else "N/A"
            strike_str = f"{d.strike:.0f}" if d.strike and d.strike == int(d.strike) else f"{d.strike or 'N/A'}"
            exp_str = d.expiry.replace("-", "") if d.expiry else "N/A"

            click.echo(f"\n   [{i}] {d.decision_type.value.upper()} {d.underlying or d.symbol} {opt_type} K={strike_str} Exp={exp_str}")
            click.echo(f"       Symbol: {d.symbol}")
            click.echo(f"       Qty: {d.quantity}, Priority: {d.priority.value}")
            if d.limit_price:
                click.echo(f"       Price: ${d.limit_price:.2f}")
            if d.trading_class:
                click.echo(f"       TradingClass: {d.trading_class}")
            if d.roll_to_expiry:
                click.echo(f"       Roll to: {d.roll_to_expiry}")
            click.echo(f"       Reason: {d.reason[:80]}..." if len(d.reason) > 80 else f"       Reason: {d.reason}")

        # 5. 执行或显示
        if effective_dry_run:
            click.echo(f"\n[DRY-RUN] 以上决策不会执行。")
            click.echo("使用 --execute 执行下单。")
        else:
            # 确认
            if not yes:
                click.echo(f"\n⚠️  即将提交 {len(decisions)} 个订单到 IBKR Paper Account")
                if not click.confirm("确认执行?"):
                    click.echo("已取消")
                    _cleanup_connection(conn)
                    return

            click.echo(f"\n📤 提交订单...")
            with trading_pipeline:
                results = trading_pipeline.execute_decisions(
                    decisions, account_state, dry_run=False
                )

            # 显示结果
            success_count = sum(1 for r in results if r.order.status == OrderStatus.SUBMITTED)
            click.echo(f"\n   ✅ 提交成功: {success_count}/{len(results)}")
            for r in results:
                status_icon = "✅" if r.order.status == OrderStatus.SUBMITTED else "❌"
                click.echo(f"   {status_icon} {r.order.symbol}: {r.order.status.value}")
                if r.broker_order_id:
                    click.echo(f"       broker_id: {r.broker_order_id}, broker_status: {r.broker_status}")
                if r.error_message:
                    click.echo(f"       error: {r.error_message}")

        # 推送结果
        if push:
            click.echo(f"\n📤 推送到飞书...")
            if effective_dry_run:
                # Dry-run 模式：推送决策
                _push_trade_decisions(
                    decisions,
                    dry_run=True,
                    command="monitor",
                    market="",  # monitor 不区分市场
                    strategy="",
                )
            else:
                # 执行模式：推送执行结果
                _push_trade_results(
                    results,
                    command="monitor",
                    market="",
                    strategy="",
                )

        click.echo("\n" + "=" * 60)
        click.echo("✅ 完成")
        click.echo("=" * 60 + "\n")

    except click.ClickException:
        raise
    except Exception as e:
        logger.exception("Trade monitor failed")
        click.echo(f"\n❌ 错误: {e}", err=True)
        sys.exit(1)
    finally:
        if "conn" in locals():
            _cleanup_connection(conn)


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
    # dry_run 默认为 True，auto_execute 覆盖 dry_run
    effective_dry_run = dry_run and not auto_execute

    try:
        click.echo("\n===== Processing Trading Signals =====")
        click.echo(f"Source: {source}")
        click.echo(f"Market: {market}")
        click.echo(f"Mode: {'dry-run' if effective_dry_run else 'auto-execute'}")
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

        # 执行或显示
        if not effective_dry_run:
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
            click.echo("[DRY RUN] 以上决策不会执行。")
            click.echo("使用 --auto-execute 自动执行，或手动执行:")
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
    # confirm 参数通过 Click 的 required=True 强制，未传入时命令不会执行

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
                    click.echo(f"    Broker ID: {record.broker_order_id}, Broker Status: {record.broker_status}")

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


# ============================================================================
# Backtest Commands
# ============================================================================


@trade.group()
def backtest() -> None:
    """策略回测

    \b
    回测命令:
      run      运行回测
      report   生成报告
    """
    pass


@backtest.command("run")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    required=True,
    help="回测配置文件路径 (YAML)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="reports/backtest",
    help="输出目录 (默认: reports/backtest)",
)
@click.option(
    "--report/--no-report",
    default=True,
    help="是否生成 HTML 报告",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
def backtest_run(
    config: str,
    output: str,
    report: bool,
    verbose: bool,
) -> None:
    """运行策略回测

    从 YAML 配置文件运行回测，生成 HTML 报告。

    \b
    配置文件示例 (config/backtest/short_put.yaml):
      name: SHORT_PUT_2024
      start_date: 2024-01-01
      end_date: 2024-12-31
      symbols: [AAPL, MSFT, GOOGL]
      strategy_type: short_put
      initial_capital: 100000

    \b
    示例:
      optrade trade backtest run -c config/backtest/short_put.yaml
      optrade trade backtest run -c config.yaml -o reports/my_backtest
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    from pathlib import Path

    try:
        from src.backtest import (
            BacktestConfig,
            BacktestExecutor,
            BacktestMetrics,
            BacktestDashboard,
        )
    except ImportError as e:
        raise click.ClickException(f"Backtest module not available: {e}")

    click.echo("\n" + "=" * 60)
    click.echo("📊 Strategy Backtest")
    click.echo("=" * 60)

    # 1. 加载配置
    click.echo(f"\n📄 加载配置: {config}")
    try:
        bt_config = BacktestConfig.from_yaml(config)
    except Exception as e:
        raise click.ClickException(f"配置加载失败: {e}")

    click.echo(f"   名称: {bt_config.name}")
    click.echo(f"   区间: {bt_config.start_date} ~ {bt_config.end_date}")
    click.echo(f"   标的: {', '.join(bt_config.symbols[:5])}{'...' if len(bt_config.symbols) > 5 else ''}")
    click.echo(f"   策略: {bt_config.strategy_type.value}")
    click.echo(f"   本金: ${bt_config.initial_capital:,.0f}")

    # 2. 创建执行器
    click.echo(f"\n🚀 运行回测...")

    # 进度条
    progress_bar = None

    def progress_callback(current_date, current_day, total_days):
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total_days,
                label="   Progress",
                show_pos=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        executor = BacktestExecutor(
            config=bt_config,
            progress_callback=progress_callback,
        )

        result = executor.run()

        # 关闭进度条
        if progress_bar:
            progress_bar.__exit__(None, None, None)

    except Exception as e:
        if progress_bar:
            progress_bar.__exit__(None, None, None)
        raise click.ClickException(f"回测执行失败: {e}")

    # 3. 计算指标
    click.echo(f"\n📈 计算指标...")
    metrics = BacktestMetrics.from_backtest_result(result)

    # 4. 显示结果摘要
    click.echo(f"\n" + "=" * 60)
    click.echo("📊 回测结果摘要")
    click.echo("=" * 60)

    click.echo(f"\n--- 收益 ---")
    click.echo(f"   总收益:     ${metrics.total_return:,.2f} ({metrics.total_return_pct:.2%})")
    if metrics.annualized_return is not None:
        click.echo(f"   年化收益:   {metrics.annualized_return:.2%}")
    click.echo(f"   最终净值:   ${metrics.final_nlv:,.2f}")

    click.echo(f"\n--- 风险 ---")
    if metrics.max_drawdown is not None:
        click.echo(f"   最大回撤:   {metrics.max_drawdown:.2%}")
    if metrics.volatility is not None:
        click.echo(f"   波动率:     {metrics.volatility:.2%}")

    click.echo(f"\n--- 风险调整收益 ---")
    if metrics.sharpe_ratio is not None:
        click.echo(f"   Sharpe:     {metrics.sharpe_ratio:.2f}")
    if metrics.sortino_ratio is not None:
        click.echo(f"   Sortino:    {metrics.sortino_ratio:.2f}")
    if metrics.calmar_ratio is not None:
        click.echo(f"   Calmar:     {metrics.calmar_ratio:.2f}")

    click.echo(f"\n--- 交易 ---")
    click.echo(f"   总交易数:   {metrics.total_trades}")
    if metrics.win_rate is not None:
        click.echo(f"   胜率:       {metrics.win_rate:.1%}")
    if metrics.profit_factor is not None:
        click.echo(f"   盈亏比:     {metrics.profit_factor:.2f}")

    click.echo(f"\n--- 费用 ---")
    click.echo(f"   佣金:       ${metrics.total_commission:,.2f}")
    click.echo(f"   滑点:       ${metrics.total_slippage:,.2f}")
    click.echo(f"   总费用占比: {metrics.commission_pct:.2%}")

    # 5. 生成报告
    if report:
        click.echo(f"\n📝 生成报告...")
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)

        report_path = output_dir / f"{bt_config.name}_{bt_config.end_date}.html"

        try:
            dashboard = BacktestDashboard(result, metrics)
            dashboard.generate_report(report_path)
            click.echo(f"   ✅ 报告已保存: {report_path}")
        except ImportError:
            click.echo(f"   ⚠️  Plotly 未安装，跳过 HTML 报告")
            click.echo(f"      安装: pip install plotly")
        except Exception as e:
            click.echo(f"   ⚠️  报告生成失败: {e}")

        # 保存 JSON 结果
        json_path = output_dir / f"{bt_config.name}_{bt_config.end_date}.json"
        try:
            with open(json_path, "w") as f:
                json.dump(metrics.to_dict(), f, indent=2, default=str)
            click.echo(f"   ✅ JSON 已保存: {json_path}")
        except Exception as e:
            click.echo(f"   ⚠️  JSON 保存失败: {e}")

    click.echo(f"\n" + "=" * 60)
    click.echo(f"✅ 回测完成 ({result.execution_time_seconds:.1f}s)")
    click.echo("=" * 60 + "\n")


@backtest.command("report")
@click.argument("result_json", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="输出 HTML 路径 (默认与 JSON 同名)",
)
def backtest_report(result_json: str, output: str) -> None:
    """从 JSON 结果生成 HTML 报告

    \b
    示例:
      optrade trade backtest report reports/backtest/SHORT_PUT_2024.json
    """
    from pathlib import Path

    json_path = Path(result_json)

    if output:
        output_path = Path(output)
    else:
        output_path = json_path.with_suffix(".html")

    click.echo(f"\n📝 生成报告: {output_path}")

    try:
        # 加载 JSON
        with open(json_path) as f:
            data = json.load(f)

        # 由于我们只有 metrics，创建一个最小的报告
        # 实际上需要完整的 BacktestResult 来生成完整报告
        click.echo(f"   ⚠️  仅从 JSON 生成报告需要完整的回测结果")
        click.echo(f"   建议使用 'backtest run' 直接生成报告")

    except Exception as e:
        raise click.ClickException(f"报告生成失败: {e}")


@backtest.command("download-macro")
@click.option(
    "--data-dir",
    "-d",
    type=click.Path(),
    required=True,
    help="数据存储目录",
)
@click.option(
    "--start-date",
    "-s",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="开始日期 (YYYY-MM-DD)",
)
@click.option(
    "--end-date",
    "-e",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    required=True,
    help="结束日期 (YYYY-MM-DD)",
)
@click.option(
    "--indicators",
    "-i",
    multiple=True,
    help="指定指标 (可多次使用，默认下载所有)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
def backtest_download_macro(
    data_dir: str,
    start_date,
    end_date,
    indicators: tuple[str, ...],
    verbose: bool,
) -> None:
    """下载宏观数据 (VIX/TNX 等)

    从 yfinance 下载宏观指数历史数据，保存为 Parquet 供回测使用。

    \b
    默认下载指标:
      ^VIX      CBOE 波动率指数
      ^VIX3M    CBOE 3个月波动率指数
      ^TNX      10年期美国国债收益率
      ^TYX      30年期美国国债收益率
      ^IRX      13周美国国债利率
      ^GSPC     S&P 500 指数
      SPY       S&P 500 ETF
      QQQ       NASDAQ-100 ETF

    \b
    示例:
      # 下载所有默认指标
      optrade trade backtest download-macro -d data/backtest -s 2015-01-01 -e 2024-12-31

      # 只下载 VIX 和 TNX
      optrade trade backtest download-macro -d data/backtest -s 2015-01-01 -e 2024-12-31 -i ^VIX -i ^TNX
    """
    from pathlib import Path

    # 配置日志
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        from src.backtest.data.macro_downloader import MacroDownloader, DEFAULT_MACRO_INDICATORS
    except ImportError as e:
        raise click.ClickException(f"MacroDownloader not available: {e}")

    click.echo("\n" + "=" * 60)
    click.echo("📥 Download Macro Data")
    click.echo("=" * 60)

    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    # 确定要下载的指标
    if indicators:
        indicator_list = list(indicators)
    else:
        indicator_list = DEFAULT_MACRO_INDICATORS

    click.echo(f"\n📁 数据目录: {data_path}")
    click.echo(f"📅 日期范围: {start_date.date()} ~ {end_date.date()}")
    click.echo(f"📊 指标列表: {len(indicator_list)} 个")
    for ind in indicator_list[:5]:
        click.echo(f"   - {ind}")
    if len(indicator_list) > 5:
        click.echo(f"   - ... ({len(indicator_list) - 5} more)")

    # 创建下载器
    downloader = MacroDownloader(data_dir=data_path)

    # 进度回调
    def on_progress(indicator: str, current: int, total: int):
        click.echo(f"   [{current}/{total}] Downloading {indicator}...")

    click.echo(f"\n🚀 开始下载...")

    try:
        results = downloader.download_indicators(
            indicators=indicator_list,
            start_date=start_date.date(),
            end_date=end_date.date(),
            on_progress=on_progress,
        )
    except Exception as e:
        raise click.ClickException(f"下载失败: {e}")

    # 显示结果
    click.echo(f"\n" + "=" * 60)
    click.echo("📊 下载结果")
    click.echo("=" * 60)

    total_records = 0
    success_count = 0
    for indicator, count in results.items():
        if count > 0:
            click.echo(f"   ✅ {indicator}: {count} records")
            total_records += count
            success_count += 1
        else:
            click.echo(f"   ❌ {indicator}: failed")

    click.echo(f"\n   总计: {total_records} records ({success_count}/{len(indicator_list)} 成功)")

    # 显示数据范围
    date_range = downloader.get_date_range()
    if date_range:
        click.echo(f"   数据范围: {date_range[0]} ~ {date_range[1]}")

    parquet_path = data_path / "macro_daily.parquet"
    click.echo(f"\n   📁 保存位置: {parquet_path}")

    click.echo(f"\n" + "=" * 60)
    click.echo("✅ 宏观数据下载完成")
    click.echo("=" * 60 + "\n")
