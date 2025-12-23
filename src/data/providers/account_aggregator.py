"""Multi-broker account aggregator.

Consolidates positions and cash from multiple brokers (IBKR, Futu)
into a unified portfolio view with currency conversion.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.data.currency import CurrencyConverter
from src.data.models import (
    AccountCash,
    AccountPosition,
    AccountSummary,
    AccountType,
    AssetType,
    ConsolidatedPortfolio,
)

if TYPE_CHECKING:
    from src.data.providers.futu_provider import FutuProvider
    from src.data.providers.ibkr_provider import IBKRProvider
    from src.data.providers.unified_provider import UnifiedDataProvider

logger = logging.getLogger(__name__)


class AccountAggregator:
    """Multi-broker account aggregator.

    Combines positions and cash from IBKR and Futu brokers
    into a unified view with currency conversion.

    Example:
        >>> from src.data.providers import IBKRProvider, FutuProvider, UnifiedDataProvider
        >>> from src.data.providers.account_aggregator import AccountAggregator
        >>> with IBKRProvider() as ibkr, FutuProvider() as futu:
        ...     unified = UnifiedDataProvider(ibkr_provider=ibkr, futu_provider=futu)
        ...     aggregator = AccountAggregator(ibkr, futu, unified_provider=unified)
        ...     portfolio = aggregator.get_consolidated_portfolio()
        ...     print(f"Total value: ${portfolio.total_value_usd:,.2f}")
    """

    def __init__(
        self,
        ibkr_provider: IBKRProvider | None = None,
        futu_provider: FutuProvider | None = None,
        currency_converter: CurrencyConverter | None = None,
        unified_provider: UnifiedDataProvider | None = None,
    ):
        """Initialize account aggregator.

        Args:
            ibkr_provider: IBKR provider instance.
            futu_provider: Futu provider instance.
            currency_converter: Currency converter instance.
            unified_provider: Unified provider for fetching option Greeks with routing.
        """
        self._ibkr = ibkr_provider
        self._futu = futu_provider
        self._converter = currency_converter or CurrencyConverter()
        self._unified = unified_provider

    def get_consolidated_portfolio(
        self,
        account_type: AccountType = AccountType.PAPER,
        base_currency: str = "USD",
        refresh_rates: bool = True,
    ) -> ConsolidatedPortfolio:
        """Get consolidated portfolio from all brokers.

        Combines positions and cash from IBKR and Futu,
        converting all values to the base currency.

        Args:
            account_type: Real or paper account.
            base_currency: Target currency for aggregation.
            refresh_rates: Whether to refresh exchange rates before conversion.

        Returns:
            ConsolidatedPortfolio with all positions and summaries.
        """
        if refresh_rates:
            self._converter.refresh_rates()

        positions: list[AccountPosition] = []
        cash_balances: list[AccountCash] = []
        by_broker: dict[str, AccountSummary] = {}

        # Determine if we should use centralized Greeks fetching via UnifiedProvider
        # If UnifiedProvider is available, disable provider-level Greeks fetching
        # to use routing rules for better provider selection
        use_unified_greeks = self._unified is not None
        fetch_greeks_in_provider = not use_unified_greeks

        # Collect from IBKR
        if self._ibkr and self._ibkr.is_available:
            try:
                ibkr_positions = self._ibkr.get_positions(
                    account_type, fetch_greeks=fetch_greeks_in_provider
                )
                ibkr_cash = self._ibkr.get_cash_balances(account_type)
                ibkr_summary = self._ibkr.get_account_summary(account_type)

                positions.extend(ibkr_positions)
                cash_balances.extend(ibkr_cash)
                if ibkr_summary:
                    by_broker["ibkr"] = ibkr_summary

                logger.info(f"Collected {len(ibkr_positions)} positions, "
                           f"{len(ibkr_cash)} cash entries from IBKR")
            except Exception as e:
                logger.error(f"Error collecting from IBKR: {e}")

        # Collect from Futu
        if self._futu and self._futu.is_available:
            try:
                futu_positions = self._futu.get_positions(
                    account_type, fetch_greeks=fetch_greeks_in_provider
                )
                futu_cash = self._futu.get_cash_balances(account_type)
                futu_summary = self._futu.get_account_summary(account_type)

                positions.extend(futu_positions)
                cash_balances.extend(futu_cash)
                if futu_summary:
                    by_broker["futu"] = futu_summary

                logger.info(f"Collected {len(futu_positions)} positions, "
                           f"{len(futu_cash)} cash entries from Futu")
            except Exception as e:
                logger.error(f"Error collecting from Futu: {e}")

        # Fetch Greeks using UnifiedProvider with routing rules
        # This uses intelligent routing: HK options → IBKR > Futu, US options → IBKR > Futu > Yahoo
        if use_unified_greeks and positions:
            try:
                self._unified.fetch_option_greeks_for_positions(positions)
            except Exception as e:
                logger.warning(f"Error fetching Greeks via UnifiedProvider: {e}")

        # Calculate totals in base currency
        total_value = self._calc_total_value(positions, cash_balances, base_currency)
        total_pnl = self._calc_total_pnl(positions, base_currency)

        logger.info(f"Consolidated portfolio: {len(positions)} positions, "
                   f"total value={total_value:.2f} {base_currency}, "
                   f"unrealized P&L={total_pnl:.2f} {base_currency}")

        return ConsolidatedPortfolio(
            positions=positions,
            cash_balances=cash_balances,
            total_value_usd=total_value,
            total_unrealized_pnl_usd=total_pnl,
            by_broker=by_broker,
            exchange_rates=self._converter.get_all_rates(),
            timestamp=datetime.now(),
        )

    def _calc_total_value(
        self,
        positions: list[AccountPosition],
        cash_balances: list[AccountCash],
        base_currency: str,
    ) -> float:
        """Calculate total portfolio value in base currency.

        Args:
            positions: List of positions.
            cash_balances: List of cash balances.
            base_currency: Target currency.

        Returns:
            Total value in base currency.
        """
        total = 0.0

        # Sum position market values
        for pos in positions:
            value = self._converter.convert(
                pos.market_value,
                pos.currency,
                base_currency,
            )
            total += value

        # Sum cash balances
        for cash in cash_balances:
            value = self._converter.convert(
                cash.balance,
                cash.currency,
                base_currency,
            )
            total += value

        return total

    def _calc_total_pnl(
        self,
        positions: list[AccountPosition],
        base_currency: str,
    ) -> float:
        """Calculate total unrealized P&L in base currency.

        Args:
            positions: List of positions.
            base_currency: Target currency.

        Returns:
            Total unrealized P&L in base currency.
        """
        total_pnl = 0.0

        for pos in positions:
            pnl = self._converter.convert(
                pos.unrealized_pnl,
                pos.currency,
                base_currency,
            )
            total_pnl += pnl

        return total_pnl

    def get_positions_by_symbol(
        self,
        account_type: AccountType = AccountType.PAPER,
    ) -> dict[str, list[AccountPosition]]:
        """Get positions grouped by symbol.

        Useful for identifying positions in the same underlying
        across different brokers.

        Args:
            account_type: Real or paper account.

        Returns:
            Dictionary mapping symbol to list of positions.
        """
        portfolio = self.get_consolidated_portfolio(account_type)
        positions_by_symbol: dict[str, list[AccountPosition]] = {}

        for pos in portfolio.positions:
            # Normalize symbol for grouping
            symbol = pos.symbol.upper()
            # Remove market prefixes for grouping
            if symbol.startswith(("US.", "HK.", "SH.", "SZ.")):
                symbol = symbol.split(".", 1)[1]

            if symbol not in positions_by_symbol:
                positions_by_symbol[symbol] = []
            positions_by_symbol[symbol].append(pos)

        return positions_by_symbol

    def get_total_exposure_by_market(
        self,
        account_type: AccountType = AccountType.PAPER,
        base_currency: str = "USD",
    ) -> dict[str, float]:
        """Get total exposure by market.

        Args:
            account_type: Real or paper account.
            base_currency: Target currency for values.

        Returns:
            Dictionary mapping market to total exposure.
        """
        portfolio = self.get_consolidated_portfolio(account_type)
        exposure: dict[str, float] = {}

        for pos in portfolio.positions:
            market = pos.market.value
            value = self._converter.convert(
                pos.market_value,
                pos.currency,
                base_currency,
            )

            if market not in exposure:
                exposure[market] = 0.0
            exposure[market] += value

        return exposure
