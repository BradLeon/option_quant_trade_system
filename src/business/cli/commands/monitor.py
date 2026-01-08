"""
Monitor Command - 持仓监控命令

运行三层持仓监控，生成风险预警。

支持两种模式：
1. 文件模式：从 JSON 文件加载持仓数据
2. 账户模式：从真实账户（IBKR/Futu）获取持仓数据
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
from src.engine.account.metrics import calc_capital_metrics


logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--account-type",
    "-a",
    type=click.Choice(["paper", "real"]),
    default=None,
    help="账户类型：paper（模拟）或 real（真实）",
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
    "--positions",
    "-p",
    type=click.Path(exists=True),
    help="持仓数据 JSON 文件路径（与 --account-type 互斥）",
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
    account_type: Optional[str],
    ibkr_only: bool,
    futu_only: bool,
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
      # 从真实 Paper 账户监控
      optrade monitor --account-type paper

      # 仅使用 IBKR 账户
      optrade monitor --account-type paper --ibkr-only

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
        # 选择数据来源：账户模式 vs 文件模式
        if account_type:
            position_list, capital_metrics = _load_from_account(
                account_type, ibkr_only, futu_only
            )
        elif positions:
            position_list = _load_positions(positions)
            capital_metrics = _load_capital(capital)
 
        click.echo(f"📋 持仓数量: {len(position_list)}")
        click.echo()

        # 创建监控管道
        pipeline = MonitoringPipeline()

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
            _output_text(result, verbose)

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


def _load_from_account(
    account_type: str,
    ibkr_only: bool,
    futu_only: bool,
) -> tuple[list[PositionData], CapitalMetrics]:
    """从真实账户加载持仓数据

    Args:
        account_type: "paper" 或 "real"
        ibkr_only: 仅使用 IBKR
        futu_only: 仅使用 Futu

    Returns:
        (持仓列表, 资金指标)
    """
    from src.data.models.account import AccountType as AccType
    from src.data.providers.account_aggregator import AccountAggregator
    from src.data.providers.ibkr_provider import IBKRProvider
    from src.data.providers.futu_provider import FutuProvider
    from src.data.providers.unified_provider import UnifiedDataProvider
    from src.business.monitoring.data_bridge import MonitoringDataBridge

    click.echo(f"📡 连接账户: {account_type}")

    # 初始化 providers
    ibkr = None
    futu = None

    if not futu_only:
        try:
            ibkr = IBKRProvider()
            ibkr.connect()
            click.echo("  ✅ IBKR 连接成功")
        except Exception as e:
            click.echo(f"  ⚠️ IBKR 连接失败: {e}")

    if not ibkr_only:
        try:
            futu = FutuProvider()
            futu.connect()
            click.echo("  ✅ Futu 连接成功")
        except Exception as e:
            click.echo(f"  ⚠️ Futu 连接失败: {e}")

    if not ibkr and not futu:
        raise click.ClickException("无法连接任何券商账户")

    # 创建聚合器
    aggregator = AccountAggregator(
        ibkr_provider=ibkr,
        futu_provider=futu,
    )

    # 获取合并后的组合
    acc_type = AccType.PAPER if account_type == "paper" else AccType.REAL
    click.echo(f"📥 获取 {acc_type.value} 账户持仓...")

    portfolio = aggregator.get_consolidated_portfolio(account_type=acc_type)

    click.echo(f"  原始持仓: {len(portfolio.positions)} 个")

    # 使用 DataBridge 转换持仓
    unified_provider = UnifiedDataProvider(
        ibkr_provider=ibkr,
        futu_provider=futu,
    )
    bridge = MonitoringDataBridge(data_provider=unified_provider, ibkr_provider=ibkr, futu_provider=futu)
    position_list = bridge.convert_positions(portfolio)

    click.echo(f"  转换后持仓: {len(position_list)} 个")

    # 调用 engine 层计算 CapitalMetrics
    capital_metrics = calc_capital_metrics(portfolio)

    # 清理连接
    if ibkr:
        try:
            ibkr.disconnect()
        except Exception:
            pass
    if futu:
        try:
            futu.disconnect()
        except Exception:
            pass

    return position_list, capital_metrics


def _load_positions(path: Optional[str]) -> list[PositionData]:
    """从 JSON 文件加载持仓数据"""
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [PositionData(**p) for p in data]

    # 返回示例数据
    return [
        PositionData(
            position_id="AAPL_180_20250117",
            symbol="AAPL",
            asset_type="option",
            option_type="put",
            quantity=-1,
            entry_price=3.50,
            current_price=2.80,
            strike=180.0,
            expiry="20250117",
            underlying_price=185.0,
            delta=-0.25,
            gamma=0.02,
            theta=0.05,
            vega=-0.15,
            iv=0.28,
            dte=25,
        ),
        PositionData(
            position_id="MSFT_400_20250117",
            symbol="MSFT",
            asset_type="option",
            option_type="put",
            quantity=-2,
            entry_price=4.20,
            current_price=5.50,
            strike=400.0,
            expiry="20250117",
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
        cash_balance=50000.0,
        maintenance_margin=25000.0,
        margin_usage=0.25,
        unrealized_pnl=1500.0,
        realized_pnl=3000.0,
        sharpe_ratio=1.5,
        total_position_value=50000.0,
        kelly_capacity=15000.0,
        kelly_usage=0.67,  # 10000/15000
        peak_equity=105000.0,
        current_drawdown=0.048,  # (105000-100000)/105000
    )


# 指标说明字典
METRIC_EXPLANATIONS = {
    # Position 级指标
    "otm_pct": "OTM% = 虚值百分比，越高越安全。Put=(S-K)/S, Call=(K-S)/S",
    "delta": "|Delta| = 方向性风险，越低风险越小",
    "dte": "DTE = 到期天数，越近风险越高（Gamma 风险）",
    "pnl": "P&L% = 持仓盈亏百分比",
    "gamma_risk_pct": "Gamma Risk% = |Gamma|/保证金，衡量 Gamma 风险暴露",
    "tgr": "TGR = Theta/|Gamma|，时间衰减效率，越高越好",
    "iv_hv": "IV/HV = 隐含/历史波动率比，≥1.2 适合卖方策略",
    "roc": "ROC = 资本回报率，衡量资金使用效率",
    "expected_roc": "Expected ROC = 预期资本回报率（考虑胜率）",
    "win_probability": "Win Prob = 获胜概率，基于价格分布估算",
    "prei": "PREI = 风险暴露指数，越低越好",
    "sas": "SAS = 策略吸引力分数，越高越好",
    # Capital 级指标
    "sharpe": "Sharpe = 夏普比率，风险调整后收益",
    "kelly_usage": "Kelly = Kelly 公式仓位使用率",
    "margin_usage": "Margin = 保证金使用率",
    "drawdown": "Drawdown = 最大回撤",
    # Portfolio 级指标
    "delta_exposure": "Delta = Beta 加权方向性敞口",
    "gamma_exposure": "Gamma = 组合 Gamma 敞口",
    "vega_exposure": "Vega = 波动率敞口",
    "theta_exposure": "Theta = 时间衰减敞口",
    "concentration": "HHI = 集中度指数，越低越分散",
    "iv_hv_quality": "IV/HV = Vega 加权波动率质量",
}


def _get_metric_explanation(alert_type) -> str:
    """根据 AlertType 获取指标说明"""
    # 从 alert_type.value 提取指标名称
    type_to_metric = {
        "otm_pct": "otm_pct",
        "delta_change": "delta",
        "dte_warning": "dte",
        "profit_target": "pnl",
        "stop_loss": "pnl",
        "pnl_target": "pnl",
        "gamma_risk_pct": "gamma_risk_pct",
        "tgr_low": "tgr",  # Portfolio 级 TGR
        "position_tgr": "tgr",  # Position 级 TGR
        "position_iv_hv": "iv_hv",  # Position 级 IV/HV
        "iv_hv_change": "iv_hv",
        "iv_hv_quality": "iv_hv_quality",  # Portfolio 级 IV/HV
        "roc_low": "roc",
        "expected_roc_low": "expected_roc",
        "win_prob_low": "win_probability",
        "prei_high": "prei",
        "sas_score": "sas",
        "sharpe_low": "sharpe",
        "kelly_usage": "kelly_usage",
        "margin_warning": "margin_usage",
        "drawdown": "drawdown",
        "delta_exposure": "delta_exposure",
        "gamma_exposure": "gamma_exposure",
        "vega_exposure": "vega_exposure",
        "theta_exposure": "theta_exposure",
        "concentration": "concentration",
    }
    metric = type_to_metric.get(alert_type.value, "")
    return METRIC_EXPLANATIONS.get(metric, "")


def _print_alerts_group(alerts: list, show_explanation: bool = True) -> None:
    """打印一组预警（用于 Capital/Portfolio 级）"""
    # 按级别排序：RED > YELLOW > GREEN
    level_order = {"red": 0, "yellow": 1, "green": 2}
    sorted_alerts = sorted(alerts, key=lambda a: level_order.get(a.level.value, 3))

    for alert in sorted_alerts:
        level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(alert.level.value, "⚪")
        click.echo(f"  {level_icon} {alert.message}")

        # 显示阈值信息：RED 显示阈值，YELLOW 显示正常范围
        if alert.level.value == "red" and alert.threshold_value is not None:
            click.echo(f"     阈值: {alert.threshold_value}")
        elif alert.level.value == "yellow" and alert.threshold_range:
            click.echo(f"     正常范围: {alert.threshold_range}")

        if alert.suggested_action:
            click.echo(f"     💡 {alert.suggested_action}")

        # 显示指标说明
        if show_explanation:
            explanation = _get_metric_explanation(alert.alert_type)
            if explanation:
                click.echo(f"     📖 {explanation}")


def _output_text(result, verbose: bool = False) -> None:
    """文本格式输出

    按三层监控级别分组展示预警：
    1. Capital 级（资金风险）
    2. Portfolio 级（组合风险）
    3. Position 级（按 position_id 单独展示每个期权合约）
    """
    from src.business.monitoring.models import AlertType

    click.echo(f"📊 监控状态: {result.status.value}")
    click.echo()

    # 预警统计
    click.echo(f"⚠️ 预警统计:")
    click.echo(f"   🔴 红色: {len(result.red_alerts)}")
    click.echo(f"   🟡 黄色: {len(result.yellow_alerts)}")
    click.echo(f"   🟢 绿色: {len(result.green_alerts)}")
    click.echo()

    if not result.alerts:
        click.echo("✅ 无预警，持仓状态正常")
        return

    # 按层级分类 AlertType
    CAPITAL_TYPES = {
        AlertType.MARGIN_UTILIZATION, AlertType.CASH_RATIO,
        AlertType.GROSS_LEVERAGE, AlertType.STRESS_TEST_LOSS,
    }
    PORTFOLIO_TYPES = {
        AlertType.DELTA_EXPOSURE, AlertType.GAMMA_EXPOSURE,
        AlertType.VEGA_EXPOSURE, AlertType.THETA_EXPOSURE,
        AlertType.TGR_LOW, AlertType.CONCENTRATION, AlertType.IV_HV_QUALITY,
    }

    # 分组预警
    capital_alerts = [a for a in result.alerts if a.alert_type in CAPITAL_TYPES]
    portfolio_alerts = [a for a in result.alerts if a.alert_type in PORTFOLIO_TYPES]
    position_alerts = [a for a in result.alerts
                       if a.alert_type not in CAPITAL_TYPES
                       and a.alert_type not in PORTFOLIO_TYPES]

    # Position 级按 position_id 分组（每个期权合约单独展示）
    position_by_id: dict[str, list] = {}
    for alert in position_alerts:
        pos_id = alert.position_id or alert.symbol or "Unknown"
        if pos_id not in position_by_id:
            position_by_id[pos_id] = []
        position_by_id[pos_id].append(alert)

    click.echo("=" * 80)
    click.echo("📋 预警详情")
    click.echo("=" * 80)

    # === Capital 级 ===
    if capital_alerts:
        click.echo()
        click.echo("💰 【Capital 级 - 资金风险】")
        click.echo("-" * 40)
        _print_alerts_group(capital_alerts)

    # === Portfolio 级 ===
    if portfolio_alerts:
        click.echo()
        click.echo("📊 【Portfolio 级 - 组合风险】")
        click.echo("-" * 40)
        _print_alerts_group(portfolio_alerts)

    # === Position 级 ===
    if position_by_id:
        click.echo()
        click.echo("📈 【Position 级 - 持仓风险】")
        click.echo("-" * 40)

        # 按 position_id 排序后输出，每个期权合约单独展示
        for pos_id in sorted(position_by_id.keys()):
            alerts = position_by_id[pos_id]
            click.echo()
            click.echo(f"  📍 {pos_id}")

            # 按级别排序：RED > YELLOW > GREEN
            level_order = {"red": 0, "yellow": 1, "green": 2}
            sorted_alerts = sorted(alerts, key=lambda a: level_order.get(a.level.value, 3))

            for alert in sorted_alerts:
                level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(alert.level.value, "⚪")
                click.echo(f"    {level_icon} {alert.message}")

                # 显示阈值信息：RED 显示阈值，YELLOW 显示正常范围
                if alert.level.value == "red" and alert.threshold_value is not None:
                    click.echo(f"       阈值: {alert.threshold_value}")
                elif alert.level.value == "yellow" and alert.threshold_range:
                    click.echo(f"       正常范围: {alert.threshold_range}")

                if alert.suggested_action:
                    click.echo(f"       💡 {alert.suggested_action}")

                # 显示指标说明
                explanation = _get_metric_explanation(alert.alert_type)
                if explanation:
                    click.echo(f"       📖 {explanation}")

    click.echo()
    click.echo("=" * 80)

    # 调整建议
    if result.suggestions:
        click.echo()
        click.echo("💡 调整建议:")
        click.echo("-" * 80)

        for suggestion in result.suggestions:
            urgency_icon = {
                "immediate": "🚨",
                "soon": "⚡",
                "monitor": "👁️",
            }.get(suggestion.urgency.value, "📌")

            action_str = suggestion.action.value.upper()

            # 构建显示标题：包含策略类型
            display_title = suggestion.symbol
            if suggestion.metadata:
                strategy = suggestion.metadata.get("strategy_type")
                if strategy:
                    display_title = f"{suggestion.symbol} ({strategy})"

            click.echo(f"{urgency_icon} [{display_title}] {action_str}")
            click.echo(f"   原因: {suggestion.reason}")
            if suggestion.details:
                click.echo(f"   详情: {suggestion.details}")
            click.echo()

        click.echo("-" * 80)

    # 详细模式：显示持仓指标
    if verbose and result.positions:
        click.echo()
        click.echo("📈 持仓详情:")
        click.echo("-" * 80)

        for pos in result.positions:
            if pos.is_option:
                option_type = pos.option_type.upper() if pos.option_type else "?"
                delta_str = f"{pos.delta:.2f}" if pos.delta is not None else "N/A"
                dte_str = str(pos.dte) if pos.dte is not None else "N/A"
                click.echo(
                    f"[{pos.symbol}] {option_type} K={pos.strike} "
                    f"DTE={dte_str} Δ={delta_str}"
                )
                if pos.sas is not None and pos.prei is not None and pos.tgr is not None:
                    click.echo(f"   SAS={pos.sas:.1f} PREI={pos.prei:.1f} TGR={pos.tgr:.2f}")
                if pos.iv is not None and pos.hv is not None and pos.iv_hv_ratio is not None:
                    click.echo(f"   IV={pos.iv:.1%} HV={pos.hv:.1%} IV/HV={pos.iv_hv_ratio:.2f}")
            else:
                click.echo(f"[{pos.symbol}] 股票 数量={pos.quantity}")
                if pos.trend_signal:
                    click.echo(f"   趋势={pos.trend_signal} RSI={pos.rsi_zone}")
                if pos.fundamental_score is not None:
                    click.echo(f"   基本面评分={pos.fundamental_score:.1f}")

            click.echo()

        click.echo("-" * 80)

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
            "suggestions": len(result.suggestions),
        },
        "alerts": [],
        "suggestions": [],
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

    for suggestion in result.suggestions:
        output_data["suggestions"].append({
            "position_id": suggestion.position_id,
            "symbol": suggestion.symbol,
            "action": suggestion.action.value,
            "urgency": suggestion.urgency.value,
            "reason": suggestion.reason,
            "details": suggestion.details,
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
