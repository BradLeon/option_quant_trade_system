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
    from src.strategy.registry import BacktestStrategyRegistry

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
    from src.strategy.registry import BacktestStrategyRegistry
    from src.strategy.risk_guards.account_risk import AccountRiskGuard
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

        # Record snapshot (even in dry-run — portfolio state is real IBKR data)
        try:
            from src.business.trading.models.snapshot import LiveDailySnapshot
            from src.business.trading.snapshot_store import LiveSnapshotStore

            snapshot = LiveDailySnapshot.from_execution_result(
                result, strategy_name, symbols, account,
            )
            LiveSnapshotStore().save(snapshot)
            click.echo(
                f"  [snapshot] NLV=${snapshot.nlv:,.0f}, "
                f"positions={snapshot.position_count}"
            )
        except Exception as snap_err:
            click.echo(f"  [snapshot] 记录失败: {snap_err}")

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


@strategy.command("report")
@click.option(
    "-s", "--strategy-name",
    default=None,
    help="策略名称 (不指定时列出所有策略)",
)
@click.option(
    "--start",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="起始日期 (e.g., 2026-01-01)",
)
@click.option(
    "--end",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="结束日期 (e.g., 2026-06-30)",
)
@click.option(
    "--html",
    "html_path",
    default=None,
    help="输出 HTML 报告路径 (e.g., reports/live_perf.html)",
)
@click.option(
    "--benchmark",
    default=None,
    help="基准标的 (e.g., SPY) — 计算 Alpha/Beta/Correlation",
)
@click.option(
    "--list", "list_all",
    is_flag=True,
    default=False,
    help="列出所有有快照数据的策略",
)
def report(
    strategy_name: str | None,
    start: object | None,
    end: object | None,
    html_path: str | None,
    benchmark: str | None,
    list_all: bool,
) -> None:
    """查看策略绩效报告

    \b
    示例:
      # 列出所有策略
      optrade strategy report --list

      # 查看绩效摘要
      optrade strategy report -s leaps_v2_cash_sweep

      # 指定日期范围 + HTML 报告
      optrade strategy report -s leaps_v2_cash_sweep --start 2026-01-01 --html reports/perf.html

      # 与 SPY 做基准对比
      optrade strategy report -s leaps_v2_cash_sweep --benchmark SPY
    """
    from src.business.trading.snapshot_store import LiveSnapshotStore

    store = LiveSnapshotStore()

    # --list: show all strategies
    if list_all or strategy_name is None:
        strategies = store.get_strategies()
        if not strategies:
            click.echo("\n暂无快照数据。运行 'optrade strategy run' 开始记录。")
            return
        click.echo(f"\n已有快照的策略 ({len(strategies)} 个):")
        click.echo("=" * 50)
        for name in strategies:
            snaps = store.load(name)
            if snaps:
                click.echo(
                    f"  {name:30s}  {snaps[0].date} ~ {snaps[-1].date}  "
                    f"({len(snaps)} days)"
                )
        click.echo()
        return

    # Load snapshots
    start_date = start.date() if start else None  # type: ignore[union-attr]
    end_date = end.date() if end else None  # type: ignore[union-attr]
    snapshots = store.load(strategy_name, start_date, end_date)

    if not snapshots:
        click.echo(f"\n策略 '{strategy_name}' 无快照数据。")
        return

    if len(snapshots) < 2:
        click.echo(f"\n策略 '{strategy_name}' 仅有 {len(snapshots)} 天数据，至少需要 2 天。")
        return

    # Convert to metrics
    from src.business.trading.performance.metrics_adapter import (
        compute_live_metrics,
    )

    initial_capital = snapshots[0].nlv
    risk_free_rate = snapshots[-1].risk_free_rate or 0.04
    metrics = compute_live_metrics(
        snapshots,
        config_name=strategy_name,
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
    )

    # Print summary
    click.echo(f"\n{metrics.summary()}")

    # Benchmark comparison
    if benchmark:
        _print_benchmark_comparison(snapshots, benchmark, metrics)

    # HTML report
    if html_path:
        _generate_html_report(snapshots, metrics, html_path, strategy_name)


def _print_benchmark_comparison(
    snapshots: list,
    benchmark: str,
    metrics: object,
) -> None:
    """Print benchmark comparison (Alpha, Beta, Correlation)."""
    try:
        import numpy as np
        import yfinance as yf

        start = snapshots[0].date
        end = snapshots[-1].date

        ticker = yf.Ticker(benchmark)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat())
        if hist.empty or len(hist) < 2:
            click.echo(f"\n  基准 {benchmark} 无数据")
            return

        bench_returns = hist["Close"].pct_change().dropna().values

        # Strategy daily returns
        strat_returns = []
        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1].nlv
            curr = snapshots[i].nlv
            if prev > 0:
                strat_returns.append((curr - prev) / prev)

        # Align lengths (use min length)
        n = min(len(strat_returns), len(bench_returns))
        if n < 5:
            click.echo(f"\n  数据点不足 ({n})，无法计算基准对比")
            return

        sr = np.array(strat_returns[:n])
        br = np.array(bench_returns[:n])

        correlation = float(np.corrcoef(sr, br)[0, 1])
        beta = float(np.cov(sr, br)[0, 1] / np.var(br)) if np.var(br) > 0 else 0.0
        ann_strat = float(np.mean(sr) * 252)
        ann_bench = float(np.mean(br) * 252)
        alpha = ann_strat - beta * ann_bench

        bench_total = float((1 + br).prod() - 1)

        click.echo(f"\n--- Benchmark: {benchmark} ---")
        click.echo(f"  {benchmark} Return:   {bench_total:.2%}")
        click.echo(f"  Beta:            {beta:.3f}")
        click.echo(f"  Alpha (ann):     {alpha:.2%}")
        click.echo(f"  Correlation:     {correlation:.3f}")

    except ImportError:
        click.echo("\n  需要 yfinance: uv add yfinance")
    except Exception as e:
        click.echo(f"\n  基准对比失败: {e}")


def _generate_html_report(
    snapshots: list,
    metrics: object,
    html_path: str,
    strategy_name: str,
) -> None:
    """Generate HTML report using Plotly."""
    try:
        from pathlib import Path

        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        dates = [s.date for s in snapshots]
        nlvs = [s.nlv for s in snapshots]
        cash_values = [s.cash for s in snapshots]
        position_counts = [s.position_count for s in snapshots]
        vix_values = [s.vix for s in snapshots if s.vix is not None]
        vix_dates = [s.date for s in snapshots if s.vix is not None]

        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=["NLV Curve", "Cash & Positions", "VIX"],
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.5, 0.3, 0.2],
        )

        # NLV
        fig.add_trace(
            go.Scatter(x=dates, y=nlvs, name="NLV", line=dict(color="blue")),
            row=1, col=1,
        )
        # Initial capital line
        fig.add_hline(
            y=snapshots[0].nlv, line_dash="dash", line_color="gray",
            annotation_text="Initial",
        )

        # Cash
        fig.add_trace(
            go.Scatter(x=dates, y=cash_values, name="Cash", line=dict(color="green")),
            row=2, col=1,
        )
        fig.add_trace(
            go.Bar(x=dates, y=position_counts, name="Positions", opacity=0.5),
            row=2, col=1,
        )

        # VIX
        if vix_values:
            fig.add_trace(
                go.Scatter(
                    x=vix_dates, y=vix_values, name="VIX",
                    line=dict(color="red"),
                ),
                row=3, col=1,
            )

        m = metrics  # type: ignore[assignment]
        title = (
            f"{strategy_name} | "
            f"Return: {m.total_return_pct:.2%} | "  # type: ignore[attr-defined]
            f"Sharpe: {m.sharpe_ratio:.2f}" if m.sharpe_ratio else f"{strategy_name}"  # type: ignore[attr-defined]
        )
        fig.update_layout(
            title=title,
            height=800,
            showlegend=True,
            template="plotly_white",
        )

        output = Path(html_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(output))
        click.echo(f"\n  HTML 报告已生成: {output.resolve()}")

    except ImportError:
        click.echo("\n  需要 plotly: uv add plotly")
    except Exception as e:
        click.echo(f"\n  HTML 报告生成失败: {e}")


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
