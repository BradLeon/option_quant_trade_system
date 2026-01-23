"""
Position Sizer - 仓位计算

使用 Kelly 公式计算仓位大小。

公式: position = kelly_fraction × 0.25 × available_capital / notional_per_contract
"""

import logging
import math

from src.business.screening.models import ContractOpportunity
from src.business.trading.config.decision_config import DecisionConfig
from src.business.trading.models.decision import AccountState

logger = logging.getLogger(__name__)


class PositionSizer:
    """仓位计算器

    使用 Kelly 公式计算仓位大小。

    Usage:
        sizer = PositionSizer()
        size = sizer.calculate_size(opportunity, account_state)
    """

    def __init__(self, config: DecisionConfig | None = None) -> None:
        """初始化仓位计算器

        Args:
            config: 决策配置
        """
        self._config = config or DecisionConfig.load()

    def calculate_size(
        self,
        opportunity: ContractOpportunity,
        account_state: AccountState,
        max_allocation_pct: float | None = None,
    ) -> int:
        """计算仓位大小

        Args:
            opportunity: 合约机会
            account_state: 账户状态
            max_allocation_pct: 最大分配比例 (覆盖配置)

        Returns:
            合约数量 (正整数)
        """
        max_pct = max_allocation_pct or self._config.max_notional_pct_per_underlying
        max_contracts = self._config.max_contracts_per_underlying
        kelly_scale = self._config.kelly_fraction

        nlv = account_state.total_equity
        if nlv <= 0:
            logger.warning("NLV is zero or negative, returning 0")
            return 0

        # 获取可用资金
        available_margin = account_state.available_margin
        available_cash = account_state.cash_balance

        # 计算每张合约的名义价值
        strike = opportunity.strike or 0
        # TODO，不要使用固定的100，要用OptionContract.lot_size or Position.contract_multiplier
        multiplier = 100  # 标准期权乘数
        notional_per_contract = strike * multiplier

        if notional_per_contract <= 0:
            logger.warning("Notional per contract is zero, returning 0")
            return 0

        # === Kelly 仓位计算 ===
        kelly_fraction = opportunity.kelly_fraction or 0.5

        # 使用 1/4 Kelly (保守)
        adjusted_kelly = kelly_fraction * kelly_scale

        # Kelly 建议的资金量
        kelly_capital = nlv * adjusted_kelly

        # === 约束条件 ===

        # 1. 最大分配比例限制
        max_capital = nlv * max_pct

        # 2. 可用保证金限制 (假设保证金率 20%)
        margin_rate = 0.20
        margin_per_contract = notional_per_contract * margin_rate
        max_by_margin = (available_margin * 0.8) / margin_per_contract if margin_per_contract > 0 else 0

        # 3. 合约数量限制
        max_by_count = max_contracts

        # 计算最终合约数
        capital_to_use = min(kelly_capital, max_capital)
        contracts_by_capital = capital_to_use / notional_per_contract

        # 取所有限制的最小值
        final_contracts = min(
            contracts_by_capital,
            max_by_margin,
            max_by_count,
        )

        # 向下取整
        result = max(0, math.floor(final_contracts))

        logger.debug(
            f"Position sizing for {opportunity.symbol}: "
            f"kelly={kelly_fraction:.2f}, "
            f"adjusted_kelly={adjusted_kelly:.2f}, "
            f"kelly_capital={kelly_capital:.2f}, "
            f"contracts_by_capital={contracts_by_capital:.1f}, "
            f"max_by_margin={max_by_margin:.1f}, "
            f"max_by_count={max_by_count}, "
            f"result={result}"
        )

        return result

    def calculate_with_details(
        self,
        opportunity: ContractOpportunity,
        account_state: AccountState,
    ) -> dict:
        """计算仓位大小并返回详细信息

        Args:
            opportunity: 合约机会
            account_state: 账户状态

        Returns:
            包含计算细节的字典
        """
        nlv = account_state.total_equity
        strike = opportunity.strike or 0
        multiplier = 100
        notional_per_contract = strike * multiplier

        kelly_fraction = opportunity.kelly_fraction or 0.5
        adjusted_kelly = kelly_fraction * self._config.kelly_fraction

        kelly_capital = nlv * adjusted_kelly
        max_capital = nlv * self._config.max_notional_pct_per_underlying

        margin_rate = 0.20
        margin_per_contract = notional_per_contract * margin_rate

        result = self.calculate_size(opportunity, account_state)

        return {
            "contracts": result,
            "input": {
                "symbol": opportunity.symbol,
                "strike": strike,
                "kelly_fraction": kelly_fraction,
                "nlv": nlv,
                "available_margin": account_state.available_margin,
            },
            "calculation": {
                "notional_per_contract": notional_per_contract,
                "margin_per_contract": margin_per_contract,
                "adjusted_kelly": adjusted_kelly,
                "kelly_capital": kelly_capital,
                "max_capital": max_capital,
            },
            "limits": {
                "max_contracts": self._config.max_contracts_per_underlying,
                "max_allocation_pct": self._config.max_notional_pct_per_underlying,
                "kelly_scale": self._config.kelly_fraction,
            },
        }
