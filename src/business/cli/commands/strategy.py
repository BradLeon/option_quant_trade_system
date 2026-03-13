"""
CLI Strategy Command — Run V2 strategies in live trading mode.

Enables seamless deployment of backtest strategies to live paper trading:
- Same strategy code, zero modification
- Data from IBKR/Yahoo instead of DuckDB
- Execution via TradingPipeline → IBKR Paper
- Structured execution trace displayed step-by-step

Usage:
    optrade strategy list
    optrade strategy run -s short_put_with_assignment -S SPY
    optrade strategy run -s sma_stock -S SPY -a live --execute
"""

import logging

import click

logger = logging.getLogger(__name__)


@click.group()
def strategy() -> None:
    """V2 策略实盘执行 (Paper Trading)"""
    pass


@strategy.command("list")
def list_strategies() -> None:
    """列出所有可用的 V2 策略"""
    from src.backtest.strategy.registry import BacktestStrategyRegistry

    strategies = BacktestStrategyRegistry.get_available_strategies()
    click.echo(f"\n可用策略 ({len(strategies)} 个):")
    click.echo("=" * 50)
    for name in strategies:
        click.echo(f"  {name}")
    click.echo()


@strategy.command("run")
@click.option(
    "-s", "--strategy-name",
    required=True,
    help="策略名称 (使用 'strategy list' 查看可用策略)",
)
@click.option(
    "-S", "--symbol",
    multiple=True,
    required=True,
    help="标的代码 (可多个, e.g., -S SPY -S AAPL)",
)
@click.option(
    "-a", "--account",
    type=click.Choice(["paper", "live"], case_sensitive=False),
    default="paper",
    show_default=True,
    help="账户类型: paper (端口 7497) 或 live (端口 7496)",
)
@click.option(
    "--execute",
    is_flag=True,
    default=False,
    help="实际下单 (默认 dry-run 仅显示信号)",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="推送结果到飞书",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    default=False,
    help="显示详细调试日志 (DEBUG level)",
)
def run(
    strategy_name: str,
    symbol: tuple[str, ...],
    account: str,
    execute: bool,
    push: bool,
    verbose: bool,
) -> None:
    """执行 V2 策略 (默认 dry-run 模式)

    \b
    示例:
      # Dry-run (Paper 账户, 默认)
      optrade strategy run -s short_put_with_assignment -S SPY

      # 实际下单到 IBKR Paper
      optrade strategy run -s short_put_with_assignment -S SPY --execute
    """
    from src.backtest.strategy.registry import BacktestStrategyRegistry
    from src.backtest.strategy.risk.account_risk import AccountRiskGuard
    from src.business.trading.config.risk_config import RiskConfig
    from src.business.trading.live_executor import LiveStrategyExecutor
    from src.business.trading.pipeline import TradingPipeline
    from src.data.models.account import AccountType
    from src.data.providers.account_aggregator import AccountAggregator

    # Configure logging
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
    else:
        logging.basicConfig(level=logging.WARNING)

    symbols = list(symbol)
    dry_run = not execute
    account_type = AccountType.PAPER if account == "paper" else AccountType.LIVE

    # Load RiskConfig (唯一配置源, 按策略名加载覆盖)
    risk_config = RiskConfig.load(strategy_name)

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  策略: {strategy_name}")
    click.echo(f"  标的: {', '.join(symbols)}")
    click.echo(f"  账户: {account.upper()}")
    click.echo(f"  模式: {'EXECUTE' if execute else 'DRY-RUN'}")
    click.echo(
        f"  风控: max_margin={risk_config.max_margin_utilization:.0%}, "
        f"max_positions={risk_config.max_positions}"
    )
    click.echo(f"{'=' * 60}")

    # 1. Create strategy instance
    try:
        strat = BacktestStrategyRegistry.create(strategy_name)
    except Exception as e:
        click.echo(f"\n错误: 无法创建策略 '{strategy_name}': {e}", err=True)
        available = BacktestStrategyRegistry.get_available_strategies()
        click.echo(f"可用策略: {', '.join(available[:10])}...", err=True)
        raise SystemExit(1)

    click.echo(f"\n  [init] 策略已创建: {strat.name}")

    # 2. Create data provider
    try:
        from src.data.providers.ibkr_provider import IBKRProvider

        ibkr_provider = IBKRProvider(account_type=account_type)
        ibkr_provider.connect()
        data_provider = ibkr_provider
        click.echo(f"  [init] IBKR 已连接 ({account.upper()}, port {ibkr_provider._port})")
    except Exception as e:
        click.echo(f"\n错误: IBKR 连接失败: {e}", err=True)
        click.echo("请确认 TWS/Gateway 已启动且端口配置正确", err=True)
        raise SystemExit(1)

    # 3. Create account aggregator
    try:
        aggregator = AccountAggregator(ibkr_provider=ibkr_provider)
    except Exception as e:
        click.echo(f"\n错误: 账户聚合器创建失败: {e}", err=True)
        raise SystemExit(1)

    # 4. Create risk guards (从 RiskConfig 读参数)
    risk_guards = [
        AccountRiskGuard(risk_config),
    ]

    # 5. Run executor (always dry_run first to generate signals via data provider)
    try:
        pipeline = TradingPipeline(risk_config=risk_config)

        executor = LiveStrategyExecutor(
            strategy=strat,
            data_provider=data_provider,
            account_aggregator=aggregator,
            trading_pipeline=pipeline,
            symbols=symbols,
            risk_guards=risk_guards,
        )

        # Phase A: Generate signals (uses IBKRProvider for data)
        result = executor.run_once(dry_run=True)

        # Phase B: If --execute and there are decisions, disconnect data
        # provider first to free the IBKR connection, then connect
        # TradingPipeline to execute orders.
        if execute and result.decisions_count > 0:
            # Show decisions before execution
            for d in executor.last_decisions:
                click.echo(
                    f"  [exec] 待执行: {d.decision_type.value} {d.symbol} "
                    f"qty={d.quantity} price={d.limit_price}"
                )

            ibkr_provider.disconnect()
            click.echo("  [exec] 数据连接已释放，连接交易通道...")
            try:
                pipeline.connect()
                orders = pipeline.execute_decisions(
                    executor.last_decisions,
                    executor.last_account_state,
                    dry_run=False,
                )
                result.orders = orders

                # Show gap if some decisions were blocked
                n_decisions = len(executor.last_decisions)
                n_orders = len(orders)
                if n_orders < n_decisions:
                    click.echo(
                        f"  [exec] {n_decisions - n_orders} 个决策被风控阻断，"
                        f"使用 -v 查看详情"
                    )
                result.trace.record(
                    "execution", "ok", mode="LIVE",
                    orders=[
                        f"{o.order.side.value} {o.order.quantity} {o.order.symbol} → {o.order.status.value}"
                        for o in orders
                    ],
                )
            except Exception as e:
                result.trace.record("execution", "error", reason=str(e))
                result.errors.append(str(e))
            finally:
                pipeline.disconnect()

        # Render structured execution trace
        click.echo(result.trace.format_text())

        # Summary
        mode = "DRY-RUN" if dry_run else "EXECUTE"
        click.echo(f"\n{'─' * 60}")
        click.echo(
            f"  [{mode}] 信号: {result.signals_generated} → "
            f"风控后: {result.signals_after_risk} → "
            f"决策: {result.decisions_count} → "
            f"订单: {len(result.orders)}"
        )
        click.echo(f"{'─' * 60}")

        if result.errors:
            click.echo(f"\n  错误:")
            for err in result.errors:
                click.echo(f"    - {err}")

        click.echo()

        # Push to Feishu
        if push:
            _push_strategy_result(
                result,
                strategy_name=strategy_name,
                symbols=symbols,
                account=account,
                dry_run=dry_run,
            )

    except Exception as e:
        click.echo(f"\n错误: 策略执行失败: {e}", err=True)
        logger.exception("Strategy execution failed")
        raise SystemExit(1)
    finally:
        try:
            ibkr_provider.disconnect()
        except Exception:
            pass


def _push_strategy_result(
    result: object,
    strategy_name: str,
    symbols: list[str],
    account: str,
    dry_run: bool,
) -> None:
    """推送策略执行结果到飞书"""
    try:
        from src.business.notification.dispatcher import MessageDispatcher

        click.echo("📤 推送到飞书...")
        dispatcher = MessageDispatcher()
        send_result = dispatcher.send_strategy_result(
            result,
            strategy_name=strategy_name,
            symbols=symbols,
            account=account,
            dry_run=dry_run,
            force=True,
        )
        if send_result.is_success:
            click.echo("✅ 推送成功")
        else:
            click.echo(f"⚠️ 推送失败: {send_result.error}")
    except Exception as e:
        click.echo(f"⚠️ 推送异常: {e}")
