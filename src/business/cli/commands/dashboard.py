"""
Dashboard Command - 实时监控仪表盘

显示完整的监控仪表盘，包括：
- Portfolio健康度（Greeks、TGR、集中度）
- 资金管理（Sharpe、Kelly、Margin、Drawdown）
- 风险热力图（PREI/SAS）
- 今日待办（建议列表）
- 期权持仓明细
- 股票持仓明细
"""

import logging
import os
import sys
import time
from typing import Optional

import click

from src.business.cli.dashboard import DashboardRenderer
from src.business.monitoring.models import CapitalMetrics, MonitorResult, PositionData
from src.business.monitoring.pipeline import MonitoringPipeline

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--account-type",
    "-a",
    type=click.Choice(["paper", "live"]),
    default=None,
    help="账户类型：paper（模拟）或 live（真实）",
)
@click.option(
    "--ibkr-only",
    is_flag=True,
    help="仅使用 IBKR 账户",
)
@click.option(
    "--futu-only",
    is_flag=True,
    help="仅使用 Futu 账户",
)
@click.option(
    "--refresh",
    "-r",
    type=int,
    default=0,
    help="自动刷新间隔（秒），0=不刷新",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
@click.option(
    "--push/--no-push",
    default=False,
    help="是否推送结果到飞书",
)
def dashboard(
    account_type: Optional[str],
    ibkr_only: bool,
    futu_only: bool,
    refresh: int,
    verbose: bool,
    push: bool,
) -> None:
    """实时监控仪表盘

    显示完整的监控看板，包括组合健康度、资金管理、
    风险热力图、待办事项和持仓明细。

    \b
    示例：
      # 使用示例数据
      optrade dashboard

      # 从 Paper 账户获取数据
      optrade dashboard --account-type paper

      # 自动刷新（每30秒）
      optrade dashboard -a paper --refresh 30

      # 仅使用 IBKR 账户
      optrade dashboard -a paper --ibkr-only

      # 推送结果到飞书
      optrade dashboard -a live --push
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        # 创建渲染器
        renderer = DashboardRenderer()

        if refresh > 0:
            # 自动刷新模式
            _run_refresh_loop(
                renderer=renderer,
                account_type=account_type,
                ibkr_only=ibkr_only,
                futu_only=futu_only,
                interval=refresh,
            )
        else:
            # 单次渲染
            result = _get_monitor_result(account_type, ibkr_only, futu_only)
            output = renderer.render(result)
            click.echo(output)

            # 推送结果
            if push:
                _push_result(result)

    except KeyboardInterrupt:
        click.echo("\n👋 已退出仪表盘")
        sys.exit(0)
    except Exception as e:
        logger.exception("仪表盘出错")
        click.echo(f"❌ 错误: {e}", err=True)
        sys.exit(1)


def _run_refresh_loop(
    renderer: DashboardRenderer,
    account_type: Optional[str],
    ibkr_only: bool,
    futu_only: bool,
    interval: int,
) -> None:
    """运行自动刷新循环

    Args:
        renderer: Dashboard渲染器
        account_type: 账户类型
        ibkr_only: 仅IBKR
        futu_only: 仅Futu
        interval: 刷新间隔（秒）
    """
    click.echo(f"🔄 自动刷新模式，间隔 {interval} 秒（按 Ctrl+C 退出）")
    click.echo()

    while True:
        # 清屏
        os.system("clear" if os.name == "posix" else "cls")

        try:
            result = _get_monitor_result(account_type, ibkr_only, futu_only)
            output = renderer.render(result)
            click.echo(output)
            click.echo(f"\n⏱️ 下次刷新: {interval}秒后")
        except Exception as e:
            click.echo(f"⚠️ 刷新出错: {e}")

        time.sleep(interval)


def _get_monitor_result(
    account_type: Optional[str],
    ibkr_only: bool,
    futu_only: bool,
) -> MonitorResult:
    """获取监控结果

    Args:
        account_type: 账户类型
        ibkr_only: 仅IBKR
        futu_only: 仅Futu

    Returns:
        MonitorResult 监控结果
    """
    if account_type:
        position_list, capital_metrics = _load_from_account(
            account_type, ibkr_only, futu_only
        )
    else:
        # 使用示例数据
        position_list = _get_sample_positions()
        capital_metrics = _get_sample_capital()

    # 创建监控管道并运行
    pipeline = MonitoringPipeline()
    result = pipeline.run(
        positions=position_list,
        capital_metrics=capital_metrics,
    )

    return result


def _load_from_account(
    account_type: str,
    ibkr_only: bool,
    futu_only: bool,
) -> tuple[list[PositionData], CapitalMetrics]:
    """从真实账户加载持仓数据

    Args:
        account_type: "paper" 或 "live"
        ibkr_only: 仅使用 IBKR
        futu_only: 仅使用 Futu

    Returns:
        (持仓列表, 资金指标)
    """
    from src.data.models.account import AccountType as AccType
    from src.data.providers.broker_manager import BrokerManager
    from src.data.providers.unified_provider import UnifiedDataProvider
    from src.business.monitoring.data_bridge import MonitoringDataBridge
    from src.engine.account.metrics import calc_capital_metrics

    # 使用 BrokerManager 统一连接
    manager = BrokerManager(account_type=account_type)
    conn = manager.connect(ibkr=not futu_only, futu=not ibkr_only)

    # 记录连接状态
    if conn.ibkr:
        logger.info("IBKR 连接成功")
    elif conn.ibkr_error and not futu_only:
        logger.warning(f"IBKR 连接失败: {conn.ibkr_error}")

    if conn.futu:
        logger.info("Futu 连接成功")
    elif conn.futu_error and not ibkr_only:
        logger.warning(f"Futu 连接失败: {conn.futu_error}")

    if not conn.any_connected:
        raise click.ClickException("无法连接任何券商账户")

    try:
        # 获取聚合器
        aggregator = conn.get_aggregator()

        # 获取合并后的组合
        acc_type = AccType.PAPER if account_type == "paper" else AccType.LIVE
        portfolio = aggregator.get_consolidated_portfolio(account_type=acc_type)

        # 使用 DataBridge 转换持仓
        unified_provider = UnifiedDataProvider(
            ibkr_provider=conn.ibkr,
            futu_provider=conn.futu,
        )
        bridge = MonitoringDataBridge(
            data_provider=unified_provider,
            ibkr_provider=conn.ibkr,
            futu_provider=conn.futu,
        )
        position_list = bridge.convert_positions(portfolio)

        # 调用 engine 层计算 CapitalMetrics
        capital_metrics = calc_capital_metrics(portfolio)

        return position_list, capital_metrics

    finally:
        # 清理连接
        if conn.ibkr:
            try:
                conn.ibkr.disconnect()
            except Exception:
                pass
        if conn.futu:
            try:
                conn.futu.disconnect()
            except Exception:
                pass


def _get_sample_positions() -> list[PositionData]:
    """获取示例持仓数据"""
    return [
        # Option positions
        PositionData(
            position_id="AAPL_PUT_170_20250117",
            symbol="AAPL250117P00170000",
            underlying="AAPL",
            asset_type="option",
            option_type="put",
            quantity=-1,
            entry_price=3.50,
            current_price=2.80,
            strike=170.0,
            expiry="20250117",
            underlying_price=185.0,
            delta=-0.30,
            gamma=0.02,
            theta=0.12,
            vega=0.80,
            iv=0.28,
            hv=0.22,
            iv_hv_ratio=1.27,
            dte=25,
            contract_multiplier=100,
            beta=1.2,
            tgr=0.60,
            roc=0.28,
            prei=45,
            sas=70,
        ),
        PositionData(
            position_id="TSLA_PUT_200_20250117",
            symbol="TSLA250117P00200000",
            underlying="TSLA",
            asset_type="option",
            option_type="put",
            quantity=-1,
            entry_price=5.20,
            current_price=4.80,
            strike=200.0,
            expiry="20250117",
            underlying_price=215.0,
            delta=-0.35,
            gamma=0.03,
            theta=0.15,
            vega=0.95,
            iv=0.45,
            hv=0.38,
            iv_hv_ratio=1.18,
            dte=25,
            contract_multiplier=100,
            beta=2.0,
            tgr=0.50,
            roc=0.32,
            prei=55,
            sas=75,
        ),
        PositionData(
            position_id="SPY_PUT_430_20250110",
            symbol="SPY250110P00430000",
            underlying="SPY",
            asset_type="option",
            option_type="put",
            quantity=-2,
            entry_price=2.80,
            current_price=2.20,
            strike=430.0,
            expiry="20250110",
            underlying_price=445.0,
            delta=-0.25,
            gamma=0.04,
            theta=0.18,
            vega=1.10,
            iv=0.18,
            hv=0.15,
            iv_hv_ratio=1.20,
            dte=18,
            contract_multiplier=100,
            beta=1.0,
            tgr=0.45,
            roc=0.35,
            prei=60,
            sas=85,
        ),
        PositionData(
            position_id="NVDA_CALL_450_20250103",
            symbol="NVDA250103C00450000",
            underlying="NVDA",
            asset_type="option",
            option_type="call",
            quantity=-1,
            entry_price=8.50,
            current_price=12.00,
            strike=450.0,
            expiry="20250103",
            underlying_price=455.0,
            delta=0.55,
            gamma=0.12,
            theta=0.09,
            vega=0.50,
            iv=0.52,
            hv=0.48,
            iv_hv_ratio=1.08,
            dte=7,
            contract_multiplier=100,
            beta=1.8,
            tgr=0.08,
            roc=0.42,
            prei=88,
            sas=40,
        ),
        PositionData(
            position_id="MSFT_CALL_350_20250207",
            symbol="MSFT250207C00350000",
            underlying="MSFT",
            asset_type="option",
            option_type="call",
            quantity=-1,
            entry_price=6.00,
            current_price=5.20,
            strike=350.0,
            expiry="20250207",
            underlying_price=340.0,
            delta=-0.28,
            gamma=0.02,
            theta=0.10,
            vega=0.75,
            iv=0.24,
            hv=0.20,
            iv_hv_ratio=1.20,
            dte=40,
            contract_multiplier=100,
            beta=1.1,
            tgr=0.50,
            roc=0.25,
            prei=50,
            sas=65,
        ),
        # Stock positions
        PositionData(
            position_id="AAPL_STOCK",
            symbol="AAPL",
            asset_type="stock",
            quantity=100,
            entry_price=175.0,
            current_price=185.0,
            unrealized_pnl=1000.0,
            unrealized_pnl_pct=0.057,
            beta=1.2,
            rsi=55,
            trend_signal="bullish",
            support=170.0,
            resistance=195.0,
            fundamental_score=78.5,
        ),
        PositionData(
            position_id="MSFT_STOCK",
            symbol="MSFT",
            asset_type="stock",
            quantity=50,
            entry_price=380.0,
            current_price=340.0,
            unrealized_pnl=-2000.0,
            unrealized_pnl_pct=-0.105,
            beta=1.1,
            rsi=42,
            trend_signal="neutral",
            support=320.0,
            resistance=360.0,
            fundamental_score=82.0,
        ),
    ]


def _push_result(result: MonitorResult) -> None:
    """推送结果到飞书

    Args:
        result: 监控结果
    """
    click.echo()
    click.echo("📤 推送结果到飞书...")

    try:
        from src.business.notification.dispatcher import MessageDispatcher

        dispatcher = MessageDispatcher()
        send_result = dispatcher.send_dashboard_result(result, force=True)

        if send_result.is_success:
            click.echo(f"✅ 推送成功: {send_result.message_id}")
        else:
            click.echo(f"❌ 推送失败: {send_result.error}")

    except Exception as e:
        click.echo(f"❌ 推送出错: {e}", err=True)


def _get_sample_capital() -> CapitalMetrics:
    """获取示例资金数据

    示例数据展示核心风控四大支柱：
    - Margin Utilization: 25% (绿色 < 40%)
    - Cash Ratio: 35% (绿色 > 30%)
    - Gross Leverage: 1.8x (绿色 < 2.0x)
    - Stress Test Loss: 8% (绿色 < 10%)
    """
    return CapitalMetrics(
        total_equity=100000.0,
        cash_balance=35000.0,  # 35% cash ratio
        maintenance_margin=25000.0,
        unrealized_pnl=1500.0,
        realized_pnl=3000.0,
        total_position_value=65000.0,
        # 核心风控四大支柱
        margin_utilization=0.25,  # 25% - GREEN
        cash_ratio=0.35,  # 35% - GREEN
        gross_leverage=1.8,  # 1.8x - GREEN
        stress_test_loss=0.08,  # 8% - GREEN
    )
