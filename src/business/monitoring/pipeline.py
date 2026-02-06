"""
Monitoring Pipeline - 监控管道

整合三层监控器，形成完整的监控流程：
1. Portfolio 级监控
2. Position 级监控
3. Capital 级监控

使用方式：
    pipeline = MonitoringPipeline(config)
    result = pipeline.run(positions, capital_metrics)
"""

import logging
from datetime import datetime
from typing import Optional

from src.business.config.monitoring_config import MonitoringConfig
from src.business.monitoring.models import (
    Alert,
    AlertLevel,
    CapitalMetrics,
    MonitorResult,
    MonitorStatus,
    PortfolioMetrics,
    PositionData,
)
from src.business.monitoring.monitors.capital_monitor import CapitalMonitor
from src.business.monitoring.monitors.portfolio_monitor import PortfolioMonitor
from src.business.monitoring.monitors.position_monitor import PositionMonitor
from src.business.monitoring.suggestions import SuggestionGenerator
from src.engine.portfolio.metrics import calc_portfolio_metrics

logger = logging.getLogger(__name__)


class MonitoringPipeline:
    """监控管道

    整合三层监控器，执行完整的监控流程。

    流程：
    1. Portfolio 级监控 - 组合 Greeks、Beta 加权 Delta、TGR、集中度
    2. Position 级监控 - 单个持仓的风险指标
    3. Capital 级监控 - 资金层面的风险指标

    每层监控器都可以独立配置和使用。
    """

    def __init__(
        self,
        config: Optional[MonitoringConfig] = None,
        suggestion_generator: Optional[SuggestionGenerator] = None,
    ) -> None:
        """初始化监控管道

        Args:
            config: 监控配置，如果为 None 则使用默认配置
            suggestion_generator: 建议生成器，如果为 None 则创建默认实例
        """
        self.config = config or MonitoringConfig.load()

        # 初始化各层监控器
        self.portfolio_monitor = PortfolioMonitor(self.config)
        self.position_monitor = PositionMonitor(self.config)
        self.capital_monitor = CapitalMonitor(self.config)

        # 建议生成器
        self.suggestion_generator = suggestion_generator or SuggestionGenerator()

    def run(
        self,
        positions: list[PositionData],
        capital_metrics: Optional[CapitalMetrics] = None,
        vix: Optional[float] = None,
        market_sentiment: Optional[dict] = None,
        nlv: Optional[float] = None,
    ) -> MonitorResult:
        """执行完整监控流程

        Args:
            positions: 持仓数据列表
            capital_metrics: 资金指标（可选）
            vix: 当前 VIX 值，用于市场环境调整（可选）
            market_sentiment: 市场情绪数据（可选）
            nlv: 账户净值，用于计算 NLV 归一化百分比指标（可选）
                如果未提供，尝试从 capital_metrics.total_equity 获取

        Returns:
            MonitorResult: 监控结果
        """
        logger.info(f"开始监控: {len(positions)} 个持仓")
        start_time = datetime.now()

        all_alerts: list[Alert] = []
        portfolio_metrics: Optional[PortfolioMetrics] = None

        # 1. Portfolio 级监控
        if positions:
            logger.info("Step 1: 执行组合级监控...")

            # DEBUG: 打印每个持仓的关键字段
            logger.debug("=" * 60)
            logger.debug("Position Details for calc_portfolio_metrics:")
            for pos in positions:
                asset_type = "OPT" if pos.is_option else "STK"
                logger.debug(
                    f"  {pos.symbol[:25]:<25} {asset_type} qty={pos.quantity:>6.0f} "
                    f"delta={pos.delta} gamma={pos.gamma} theta={pos.theta} vega={pos.vega} "
                    f"mult={pos.contract_multiplier} und_price={pos.underlying_price} beta={pos.beta}"
                )
            logger.debug("=" * 60)

            # 获取 NLV（优先使用传入参数，其次从 capital_metrics 获取）
            effective_nlv = nlv
            if effective_nlv is None and capital_metrics and capital_metrics.total_equity:
                effective_nlv = capital_metrics.total_equity

            # 从 positions 构建 IV/HV 比率映射表
            position_iv_hv_ratios: dict[str, float] = {}
            for pos in positions:
                if pos.iv_hv_ratio is not None:
                    position_iv_hv_ratios[pos.symbol] = pos.iv_hv_ratio

            # 调用 engine 层计算组合指标
            # PositionData 已具备 greeks 和 beta 属性，可直接传入
            portfolio_metrics = calc_portfolio_metrics(
                positions,  # type: ignore[arg-type]
                nlv=effective_nlv,
                position_iv_hv_ratios=position_iv_hv_ratios if position_iv_hv_ratios else None,
            )

            # DEBUG: 打印计算结果
            logger.debug(f"calc_portfolio_metrics result:")
            logger.debug(f"  total_delta={portfolio_metrics.total_delta}")
            logger.debug(f"  beta_weighted_delta={portfolio_metrics.beta_weighted_delta}")
            logger.debug(f"  beta_weighted_delta_pct={portfolio_metrics.beta_weighted_delta_pct}")
            logger.debug(f"  total_gamma={portfolio_metrics.total_gamma}")
            logger.debug(f"  gamma_pct={portfolio_metrics.gamma_pct}")
            logger.debug(f"  total_theta={portfolio_metrics.total_theta}")
            logger.debug(f"  theta_pct={portfolio_metrics.theta_pct}")
            logger.debug(f"  total_vega={portfolio_metrics.total_vega}")
            logger.debug(f"  vega_pct={portfolio_metrics.vega_pct}")
            logger.debug(f"  portfolio_tgr={portfolio_metrics.portfolio_tgr}")
            logger.debug(f"  concentration_hhi={portfolio_metrics.concentration_hhi}")
            logger.debug(f"  vega_weighted_iv_hv={portfolio_metrics.vega_weighted_iv_hv}")
            logger.debug(f"  NLV used={effective_nlv}")

            # 将计算好的指标传给 monitor 做阈值检查
            portfolio_alerts = self.portfolio_monitor.evaluate(portfolio_metrics)
            all_alerts.extend(portfolio_alerts)
            logger.info(f"组合级预警: {len(portfolio_alerts)} 个")

            # 打印组合级预警详情
            for alert in portfolio_alerts:
                level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(alert.level.value, "⚪")
                value_str = f"{alert.current_value:.4f}" if alert.current_value is not None else "N/A"
                threshold_str = alert.threshold_range or (f"{alert.threshold_value:.4f}" if alert.threshold_value else "N/A")
                logger.info(
                    f"  {level_icon} [Portfolio] {alert.alert_type.value}: "
                    f"{alert.message} (当前={value_str}, 阈值={threshold_str})"
                )

        # 2. Position 级监控
        if positions:
            logger.info("Step 2: 执行持仓级监控...")
            position_alerts = self.position_monitor.evaluate(positions)
            all_alerts.extend(position_alerts)
            logger.info(f"持仓级预警: {len(position_alerts)} 个")

            # 打印持仓级预警详情
            for alert in position_alerts:
                level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(alert.level.value, "⚪")
                symbol_str = alert.symbol or "N/A"
                value_str = f"{alert.current_value:.4f}" if alert.current_value is not None else "N/A"
                threshold_str = alert.threshold_range or (f"{alert.threshold_value:.4f}" if alert.threshold_value else "N/A")
                logger.info(
                    f"  {level_icon} [{symbol_str}] {alert.alert_type.value}: "
                    f"{alert.message} (当前={value_str}, 阈值={threshold_str})"
                )

        # 3. Capital 级监控
        if capital_metrics:
            logger.info("Step 3: 执行资金级监控...")
            capital_alerts = self.capital_monitor.evaluate(capital_metrics)
            all_alerts.extend(capital_alerts)
            logger.info(f"资金级预警: {len(capital_alerts)} 个")

            # 打印资金级预警详情
            for alert in capital_alerts:
                level_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(alert.level.value, "⚪")
                value_str = f"{alert.current_value:.4f}" if alert.current_value is not None else "N/A"
                threshold_str = alert.threshold_range or (f"{alert.threshold_value:.4f}" if alert.threshold_value else "N/A")
                logger.info(
                    f"  {level_icon} [Capital] {alert.alert_type.value}: "
                    f"{alert.message} (当前={value_str}, 阈值={threshold_str})"
                )

        # 确定整体状态
        overall_status = self._determine_overall_status(all_alerts)

        # 4. 生成调整建议
        logger.info("Step 4: 生成调整建议...")
        temp_result = MonitorResult(
            status=overall_status,
            alerts=all_alerts,
        )
        suggestions = self.suggestion_generator.generate(
            monitor_result=temp_result,
            positions=positions,
            vix=vix,
        )
        logger.info(f"生成建议: {len(suggestions)} 个")

        # 打印建议详情
        for suggestion in suggestions:
            urgency_icon = {
                "immediate": "🚨",
                "soon": "⚡",
                "monitor": "👀",
            }.get(suggestion.urgency.value, "📋")
            action_str = suggestion.action.value.upper()
            logger.info(
                f"  {urgency_icon} [{suggestion.symbol}] {action_str}: "
                f"{suggestion.reason}"
            )
            if suggestion.details:
                logger.info(f"      └─ {suggestion.details}")

        # 统计
        positions_at_risk = len(set(
            a.position_id for a in all_alerts
            if a.level == AlertLevel.RED and a.position_id
        ))
        positions_opportunity = len(set(
            a.position_id for a in all_alerts
            if a.level == AlertLevel.GREEN and a.position_id
        ))

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"监控完成: 状态={overall_status.value}, "
            f"预警={len(all_alerts)} 个, 建议={len(suggestions)} 个, "
            f"耗时 {elapsed:.2f}s"
        )

        return MonitorResult(
            status=overall_status,
            alerts=all_alerts,
            positions=positions,
            suggestions=suggestions,
            portfolio_metrics=portfolio_metrics,
            capital_metrics=capital_metrics,
            market_sentiment=market_sentiment,
            total_positions=len(positions),
            positions_at_risk=positions_at_risk,
            positions_opportunity=positions_opportunity,
        )

    def _determine_overall_status(self, alerts: list[Alert]) -> MonitorStatus:
        """确定整体状态"""
        if any(a.level == AlertLevel.RED for a in alerts):
            return MonitorStatus.RED
        elif any(a.level == AlertLevel.YELLOW for a in alerts):
            return MonitorStatus.YELLOW
        else:
            return MonitorStatus.GREEN

    def run_portfolio_only(
        self,
        positions: list[PositionData],
        nlv: Optional[float] = None,
    ) -> tuple[list[Alert], PortfolioMetrics]:
        """仅执行组合级监控

        Args:
            positions: 持仓数据列表
            nlv: 账户净值，用于计算 NLV 归一化百分比指标（可选）

        Returns:
            (预警列表, 组合指标)
        """
        # 从 positions 构建 IV/HV 比率映射表
        position_iv_hv_ratios: dict[str, float] = {}
        for pos in positions:
            if pos.iv_hv_ratio is not None:
                position_iv_hv_ratios[pos.symbol] = pos.iv_hv_ratio

        portfolio_metrics = calc_portfolio_metrics(
            positions,  # type: ignore[arg-type]
            nlv=nlv,
            position_iv_hv_ratios=position_iv_hv_ratios if position_iv_hv_ratios else None,
        )
        alerts = self.portfolio_monitor.evaluate(portfolio_metrics)
        return alerts, portfolio_metrics

    def run_position_only(
        self,
        positions: list[PositionData],
    ) -> list[Alert]:
        """仅执行持仓级监控

        Args:
            positions: 持仓数据列表

        Returns:
            预警列表
        """
        return self.position_monitor.evaluate(positions)

    def run_capital_only(
        self,
        capital_metrics: CapitalMetrics,
    ) -> list[Alert]:
        """仅执行资金级监控

        Args:
            capital_metrics: 资金指标

        Returns:
            预警列表
        """
        return self.capital_monitor.evaluate(capital_metrics)


# 便捷函数
def create_monitoring_pipeline(
    config_path: Optional[str] = None,
) -> MonitoringPipeline:
    """创建监控管道

    Args:
        config_path: 配置文件路径，如果为 None 则使用默认配置

    Returns:
        MonitoringPipeline 实例
    """
    if config_path:
        config = MonitoringConfig.from_yaml(config_path)
    else:
        config = MonitoringConfig.load()

    return MonitoringPipeline(config)
