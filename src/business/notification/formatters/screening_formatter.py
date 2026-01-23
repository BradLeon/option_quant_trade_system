"""
Screening Formatter - 筛选结果格式化器

将筛选结果格式化为推送消息。
"""

from collections import defaultdict
from typing import Any

from src.business.notification.channels.feishu import FeishuCardBuilder
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    ScreeningResult,
)
from src.engine.models.enums import StrategyType

# 默认最大推送机会数
DEFAULT_MAX_OPPORTUNITIES = 10


class ScreeningFormatter:
    """筛选结果格式化器

    将 ScreeningResult 转换为飞书卡片消息。
    """

    def __init__(
        self,
        templates: dict[str, str] | None = None,
        max_opportunities: int = DEFAULT_MAX_OPPORTUNITIES,
    ) -> None:
        """初始化格式化器

        Args:
            templates: 消息模板配置
            max_opportunities: 最多推送的机会数量
        """
        self.templates = templates or {}
        self.max_opportunities = max_opportunities

    def _diversify_opportunities(
        self,
        opportunities: list[ContractOpportunity],
        max_count: int,
    ) -> list[ContractOpportunity]:
        """在多个标的中分散选取机会

        采用轮询策略：按标的分组，然后轮流从每个标的中选取，
        直到达到 max_count 或所有机会都被选完。

        Args:
            opportunities: 原始机会列表（已按 expected_roc 排序）
            max_count: 最大选取数量

        Returns:
            分散选取后的机会列表
        """
        if len(opportunities) <= max_count:
            return opportunities

        # 按标的分组，保持每个标的内部的排序
        by_symbol: dict[str, list[ContractOpportunity]] = defaultdict(list)
        for opp in opportunities:
            by_symbol[opp.symbol].append(opp)

        # 轮询选取
        result: list[ContractOpportunity] = []
        symbols = list(by_symbol.keys())
        indices = {s: 0 for s in symbols}  # 每个标的当前选取位置

        while len(result) < max_count:
            added_this_round = False
            for symbol in symbols:
                if len(result) >= max_count:
                    break
                idx = indices[symbol]
                if idx < len(by_symbol[symbol]):
                    result.append(by_symbol[symbol][idx])
                    indices[symbol] = idx + 1
                    added_this_round = True

            # 如果这轮没有新增，说明所有标的都选完了
            if not added_this_round:
                break

        return result

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
        strategy_name = "Short Put" if result.strategy_type == StrategyType.SHORT_PUT else "Covered Call"
        title = self.templates.get(
            "screening_opportunity_title",
            f"📈 {strategy_name} 开仓机会",
        ).format(strategy=strategy_name)

        # 构建市场状态描述
        market_status_text = self._format_market_status(result.market_status)

        # 使用 confirmed（两步都通过的合约）
        # Double Confirmation: 只有两次筛选都通过的合约才推送
        confirmed_opportunities = result.confirmed if result.confirmed else []

        # 在多个标的中分散选取，避免集中在同一只股票
        diversified = self._diversify_opportunities(
            confirmed_opportunities,
            self.max_opportunities,
        )

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
                "theta_margin_ratio": opp.theta_margin_ratio,  # 资金效率排序指标
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
            for opp in diversified
        ]

        return FeishuCardBuilder.create_opportunity_card(
            title=title,
            opportunities=opportunities_data,
            market_status=market_status_text,
            max_opportunities=self.max_opportunities,
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
                "策略类型": result.strategy_type.value,
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
        - 有确认机会: format_opportunity (使用 confirmed)
        - 无机会: format_no_opportunity
        - 市场不利: format_market_unfavorable

        Args:
            result: 筛选结果

        Returns:
            飞书卡片数据
        """
        if result.rejection_reason and "市场环境" in result.rejection_reason:
            return self.format_market_unfavorable(result)
        elif result.confirmed:
            # Double Confirmation: 只有两步都通过的才推送
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
