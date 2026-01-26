"""
Account State Analyzer - 账户状态分析

分析账户状态，判断是否可以开仓。

核心指标 (四大支柱):
- Margin Utilization: < 70% 可开仓
- Cash Ratio: > 10% 可开仓
- Gross Leverage: < 4.0x 可开仓
"""

import logging
from typing import Any

from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.models.decision import AccountState

logger = logging.getLogger(__name__)


class AccountStateAnalyzer:
    """账户状态分析器

    分析账户状态，判断是否可以开新仓位。

    Usage:
        analyzer = AccountStateAnalyzer()
        can_open, reasons = analyzer.can_open_position(account_state)
        available = analyzer.get_available_capital(account_state)
    """

    def __init__(self, config: DecisionConfig | None = None) -> None:
        """初始化账户状态分析器

        Args:
            config: 决策配置
        """
        self._config = config or DecisionConfig.load()

    def can_open_position(
        self,
        account_state: AccountState,
        required_margin: float = 0.0,
    ) -> tuple[bool, list[str]]:
        """检查是否可以开新仓

        Args:
            account_state: 账户状态
            required_margin: 预计需要的保证金

        Returns:
            (can_open, rejection_reasons)
        """
        reasons = []

        # 检查 Margin Utilization
        if account_state.margin_utilization >= self._config.max_margin_utilization:
            reasons.append(
                f"Margin utilization too high: "
                f"{account_state.margin_utilization:.1%} >= "
                f"{self._config.max_margin_utilization:.1%}"
            )

        # 检查 Cash Ratio
        if account_state.cash_ratio < self._config.min_cash_ratio:
            reasons.append(
                f"Insufficient cash buffer: "
                f"{account_state.cash_ratio:.1%} < "
                f"{self._config.min_cash_ratio:.1%}"
            )

        # 检查 Gross Leverage
        if account_state.gross_leverage >= self._config.max_gross_leverage:
            reasons.append(
                f"Leverage limit exceeded: "
                f"{account_state.gross_leverage:.1f}x >= "
                f"{self._config.max_gross_leverage:.1f}x"
            )

        # 检查持仓数量限制
        if (
            account_state.option_position_count
            >= self._config.max_total_option_positions
        ):
            reasons.append(
                f"Option position limit reached: "
                f"{account_state.option_position_count} >= "
                f"{self._config.max_total_option_positions}"
            )

        # 检查预计保证金
        if required_margin > 0:
            nlv = account_state.total_equity
            projected_margin = account_state.used_margin + required_margin
            projected_utilization = projected_margin / nlv if nlv > 0 else 1.0

            max_projected = self._config.max_projected_margin_utilization
            if projected_utilization >= max_projected:
                reasons.append(
                    f"Projected margin too high: "
                    f"{projected_utilization:.1%} >= {max_projected:.0%}"
                )

        can_open = len(reasons) == 0

        if not can_open:
            logger.info(
                f"Cannot open position: {', '.join(reasons)}"
            )

        return can_open, reasons

    def get_available_capital_for_opening(
        self, account_state: AccountState
    ) -> float:
        """获取可用于开仓的资金

        计算在保持风控指标安全的前提下，最多可以使用多少资金开仓。

        Args:
            account_state: 账户状态

        Returns:
            可用资金
        """
        nlv = account_state.total_equity
        if nlv <= 0:
            return 0.0

        # 基于保证金使用率计算
        max_margin_utilization = self._config.max_margin_utilization
        current_margin = account_state.used_margin
        max_total_margin = nlv * max_margin_utilization
        margin_headroom = max(0, max_total_margin - current_margin)

        # 基于现金比例计算
        min_cash_ratio = self._config.min_cash_ratio
        current_cash = account_state.cash_balance
        min_required_cash = nlv * min_cash_ratio
        cash_headroom = max(0, current_cash - min_required_cash)

        # 取较小值
        available = min(margin_headroom, cash_headroom)

        logger.debug(
            f"Available capital: {available:.2f} "
            f"(margin_headroom={margin_headroom:.2f}, "
            f"cash_headroom={cash_headroom:.2f})"
        )

        return available

    def check_underlying_exposure(
        self,
        account_state: AccountState,
        underlying: str,
        additional_notional: float = 0.0,
    ) -> tuple[bool, str | None]:
        """检查标的暴露

        Args:
            account_state: 账户状态
            underlying: 标的符号
            additional_notional: 额外增加的名义价值

        Returns:
            (is_within_limit, rejection_reason)
        """
        nlv = account_state.total_equity
        if nlv <= 0:
            return False, "NLV is zero or negative"

        current_exposure = account_state.exposure_by_underlying.get(underlying, 0.0)
        total_exposure = current_exposure + additional_notional
        exposure_pct = total_exposure / nlv

        max_pct = self._config.max_notional_pct_per_underlying

        if exposure_pct >= max_pct:
            return False, (
                f"Underlying {underlying} exposure too high: "
                f"{exposure_pct:.1%} >= {max_pct:.1%}"
            )

        return True, None

    def get_account_health_summary(
        self, account_state: AccountState
    ) -> dict[str, Any]:
        """获取账户健康状况摘要

        Args:
            account_state: 账户状态

        Returns:
            健康状况摘要
        """
        can_open, reasons = self.can_open_position(account_state)
        available_capital = self.get_available_capital_for_opening(account_state)

        return {
            "can_open_position": can_open,
            "rejection_reasons": reasons,
            "available_capital": available_capital,
            "margin_utilization": account_state.margin_utilization,
            "cash_ratio": account_state.cash_ratio,
            "gross_leverage": account_state.gross_leverage,
            "option_position_count": account_state.option_position_count,
            "limits": {
                "max_margin_utilization": self._config.max_margin_utilization,
                "min_cash_ratio": self._config.min_cash_ratio,
                "max_gross_leverage": self._config.max_gross_leverage,
                "max_option_positions": self._config.max_total_option_positions,
            },
        }
