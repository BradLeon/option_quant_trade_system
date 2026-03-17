"""CLI Strategy Command — Run V2 strategies in live trading mode.

Usage:
    optrade strategy list
    optrade strategy run -s short_put_with_assignment -S SPY
    optrade strategy run -s sma_stock -S SPY --execute --push
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
    from src.business.trading.risk.daily_limits_guard import DailyLimitsGuard
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
    account_type = AccountType.PAPER if account == "paper" else AccountType.LIVE

    # Load RiskConfig
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

    # 1. Create strategy
    try:
        strat = BacktestStrategyRegistry.create(strategy_name)
    except Exception as e:
        click.echo(f"\n错误: 无法创建策略 '{strategy_name}': {e}", err=True)
        available = BacktestStrategyRegistry.get_available_strategies()
        click.echo(f"可用策略: {', '.join(available[:10])}...", err=True)
        raise SystemExit(1)

    click.echo(f"\n  [init] 策略已创建: {strat.name}")

    # 2. Connect IBKR for data
    try:
        from src.data.providers.ibkr_provider import IBKRProvider

        ibkr_provider = IBKRProvider(account_type=account_type)
        ibkr_provider.connect()
        data_provider = ibkr_provider
        click.echo(
            f"  [init] IBKR 已连接 ({account.upper()}, "
            f"port {ibkr_provider._port})"
        )
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

    # 4. Create pipeline + risk guards
    pipeline = TradingPipeline(risk_config=risk_config)

    risk_guards = [
        AccountRiskGuard(risk_config),
        DailyLimitsGuard(
            order_store=pipeline.order_store,
        ),
    ]

    # 5. Create executor
    executor = LiveStrategyExecutor(
        strategy=strat,
        data_provider=data_provider,
        account_aggregator=aggregator,
        trading_pipeline=pipeline,
        symbols=symbols,
        risk_guards=risk_guards,
    )

    try:
        # Phase A: Plan (uses IBKRProvider for data)
        result, plan = executor.plan()

        # Phase B: Execute if requested
        if execute and (plan.orders or plan.roll_pairs):
            # Show planned orders
            for order in plan.orders:
                click.echo(
                    f"  [exec] 待执行: {order.decision_type} "
                    f"{order.side.value} {order.quantity} {order.symbol} "
                    f"price={order.limit_price}"
                )
            for close_ord, open_ord in plan.roll_pairs:
                click.echo(
                    f"  [exec] ROLL: close {close_ord.symbol} "
                    f"→ open {open_ord.symbol}"
                )

            # Disconnect data, connect trading
            ibkr_provider.disconnect()
            click.echo("  [exec] 数据连接已释放，连接交易通道...")

            try:
                pipeline.connect()
                orders = executor.execute(plan)
                result.orders = orders

                n_orders = len(orders)
                n_planned = len(plan.orders) + len(plan.roll_pairs) * 2
                if n_orders < n_planned:
                    click.echo(
                        f"  [exec] {n_planned - n_orders} 个订单被风控阻断"
                    )

                result.trace.record(
                    "execution", "ok", mode="LIVE",
                    orders=[
                        f"{o.order.side.value} {o.order.quantity} "
                        f"{o.order.symbol} → {o.order.status.value}"
                        for o in orders
                    ],
                )
            except Exception as e:
                result.trace.record("execution", "error", reason=str(e))
                result.errors.append(str(e))
            finally:
                pipeline.disconnect()

        # Render trace
        click.echo(result.trace.format_text())

        # Summary
        mode = "DRY-RUN" if not execute else "EXECUTE"
        click.echo(f"\n{'─' * 60}")
        click.echo(
            f"  [{mode}] 信号: {result.signals_generated} → "
            f"风控后: {result.signals_after_risk} → "
            f"订单: {result.orders_planned} → "
            f"成交: {len(result.orders)}"
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
                dry_run=not execute,
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

        click.echo("推送到飞书...")
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
            click.echo("推送成功")
        else:
            click.echo(f"推送失败: {send_result.error}")
    except Exception as e:
        click.echo(f"推送异常: {e}")
