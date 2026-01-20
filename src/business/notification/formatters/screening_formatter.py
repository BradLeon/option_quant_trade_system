"""
Screening Formatter - 筛选结果格式化器

将筛选结果格式化为推送消息。
"""

from typing import Any

from src.business.notification.channels.feishu import FeishuCardBuilder
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    ScreeningResult,
)


class ScreeningFormatter:
    """筛选结果格式化器

    将 ScreeningResult 转换为飞书卡片消息。
    """

    def __init__(
        self,
        templates: dict[str, str] | None = None,
    ) -> None:
        """初始化格式化器

        Args:
            templates: 消息模板配置
        """
        self.templates = templates or {}

    def format_opportunity(
        self,
        result: ScreeningResult,
    ) -> dict[str, Any]:
        """格式化机会消息

        Args:
            result: 筛选结果

        Returns:
            飞书卡片数据
        """
        strategy_name = "Short Put" if result.strategy_type == "short_put" else "Covered Call"
        title = self.templates.get(
            "screening_opportunity_title",
            f"📈 {strategy_name} 开仓机会",
        ).format(strategy=strategy_name)

        # 构建市场状态描述
        market_status_text = self._format_market_status(result.market_status)

        # 构建机会列表（只包含通过筛选的合约）
        # 注意：result.opportunities 包含所有评估的合约（含被拒绝的），需要过滤
        passed_opportunities = [opp for opp in result.opportunities if opp.passed]

        opportunities_data = [
            {
                # 基础信息
                "symbol": opp.symbol,
                "strike": opp.strike,
                "expiry": opp.expiry,
                "dte": opp.dte,
                "option_type": opp.option_type,
                # 策略指标
                "recommended_position": opp.recommended_position,
                "expected_roc": opp.expected_roc,
                "sharpe_ratio": opp.sharpe_ratio,
                "premium_rate": opp.premium_rate,
                "win_probability": opp.win_probability,
                "annual_roc": opp.annual_roc,
                # 风险指标
                "tgr": opp.tgr,
                "sas": opp.sas,
                "prei": opp.prei,
                "kelly_fraction": opp.kelly_fraction,
                "theta_premium_ratio": opp.theta_premium_ratio,
                # 行情数据
                "underlying_price": opp.underlying_price,
                "mid_price": opp.mid_price,
                "moneyness": opp.moneyness,
                "bid": opp.bid,
                "ask": opp.ask,
                "volume": opp.volume,
                "iv": opp.iv,
                # Greeks
                "delta": opp.delta,
                "gamma": opp.gamma,
                "theta": opp.theta,
                "vega": opp.vega,
                "open_interest": opp.open_interest,
                "otm_percent": opp.otm_percent,
                # 警告信息
                "warnings": opp.warnings,
            }
            for opp in passed_opportunities
        ]

        return FeishuCardBuilder.create_opportunity_card(
            title=title,
            opportunities=opportunities_data,
            market_status=market_status_text,
        )

    def format_no_opportunity(
        self,
        result: ScreeningResult,
    ) -> dict[str, Any]:
        """格式化无机会消息

        Args:
            result: 筛选结果

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "screening_no_opportunity_title",
            "📊 筛选完成 - 暂无机会",
        )

        message = f"扫描了 {result.scanned_underlyings} 个标的，{result.passed_underlyings} 个通过筛选，暂无符合条件的合约。"

        return FeishuCardBuilder.create_alert_card(
            title=title,
            level="grey",
            message=message,
            details={
                "扫描标的": str(result.scanned_underlyings),
                "通过标的": str(result.passed_underlyings),
                "策略类型": result.strategy_type,
            },
        )

    def format_market_unfavorable(
        self,
        result: ScreeningResult,
    ) -> dict[str, Any]:
        """格式化市场不利消息

        Args:
            result: 筛选结果

        Returns:
            飞书卡片数据
        """
        title = self.templates.get(
            "market_unfavorable_title",
            "⚠️ 市场环境不利 - 建议观望",
        )

        reasons = result.rejection_reason or "未知原因"
        message = f"市场环境评估不通过，建议暂停开仓操作。\n\n**原因**: {reasons}"

        details = {}
        if result.market_status:
            ms = result.market_status
            if ms.volatility_index:
                details["VIX"] = f"{ms.volatility_index.value:.1f}"
            details["趋势"] = ms.overall_trend.value

        return FeishuCardBuilder.create_alert_card(
            title=title,
            level="yellow",
            message=message,
            details=details if details else None,
            suggestion="等待市场环境改善后再考虑开仓",
        )

    def format(self, result: ScreeningResult) -> dict[str, Any]:
        """格式化筛选结果

        根据结果自动选择合适的格式：
        - 有机会: format_opportunity
        - 无机会: format_no_opportunity
        - 市场不利: format_market_unfavorable

        Args:
            result: 筛选结果

        Returns:
            飞书卡片数据
        """
        if result.rejection_reason and "市场环境" in result.rejection_reason:
            return self.format_market_unfavorable(result)
        elif result.passed and result.opportunities:
            return self.format_opportunity(result)
        else:
            return self.format_no_opportunity(result)

    def _format_market_status(self, ms: MarketStatus | None) -> str:
        """格式化市场状态描述"""
        if ms is None:
            return "市场状态未知"

        parts = []

        # VIX
        if ms.volatility_index:
            vix = ms.volatility_index.value
            parts.append(f"VIX={vix:.1f}")

        # 趋势
        trend_map = {
            "strong_bullish": "强多头 🟢",
            "bullish": "多头 🟢",
            "neutral": "中性 ⚪",
            "bearish": "空头 🔴",
            "strong_bearish": "强空头 🔴",
        }
        parts.append(f"趋势: {trend_map.get(ms.overall_trend.value, ms.overall_trend.value)}")

        # 期限结构
        if ms.term_structure:
            ts = ms.term_structure
            structure = "正向" if ts.is_contango else "反向"
            parts.append(f"期限结构: {structure} ({ts.ratio:.2f})")

        return " | ".join(parts)
