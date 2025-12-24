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

logger = logging.getLogger(__name__)


class AccountAggregator:
    """Multi-broker account aggregator.

    Combines positions and cash from IBKR and Futu brokers
    into a unified view with currency conversion.

    For option positions, Greeks are fetched as follows:
    - IBKR options: Greeks are fetched directly via IBKR's get_positions()
    - Futu options: Greeks are fetched via IBKR (Futu requires extra subscription)

    Example:
        >>> from src.data.providers import IBKRProvider, FutuProvider
        >>> from src.data.providers.account_aggregator import AccountAggregator
        >>> with IBKRProvider() as ibkr, FutuProvider() as futu:
        ...     aggregator = AccountAggregator(ibkr, futu)
        ...     portfolio = aggregator.get_consolidated_portfolio()
        ...     print(f"Total value: ${portfolio.total_value_usd:,.2f}")
    """

    def __init__(
        self,
        ibkr_provider: IBKRProvider | None = None,
        futu_provider: FutuProvider | None = None,
        currency_converter: CurrencyConverter | None = None,
    ):
        """Initialize account aggregator.

        Args:
            ibkr_provider: IBKR provider instance.
            futu_provider: Futu provider instance.
            currency_converter: Currency converter instance.
        """
        self._ibkr = ibkr_provider
        self._futu = futu_provider
        self._converter = currency_converter or CurrencyConverter()

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
        futu_option_positions: list[AccountPosition] = []

        # Collect from IBKR - always fetch Greeks directly (IBKR's get_positions works well)
        if self._ibkr and self._ibkr.is_available:
            try:
                ibkr_positions = self._ibkr.get_positions(
                    account_type, fetch_greeks=True
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

        # Collect from Futu - don't fetch Greeks (Futu requires extra subscription)
        if self._futu and self._futu.is_available:
            try:
                futu_positions = self._futu.get_positions(
                    account_type, fetch_greeks=False
                )
                futu_cash = self._futu.get_cash_balances(account_type)
                futu_summary = self._futu.get_account_summary(account_type)

                # Collect Futu option positions for Greeks fetching via IBKR
                for pos in futu_positions:
                    if pos.asset_type == AssetType.OPTION:
                        futu_option_positions.append(pos)

                positions.extend(futu_positions)
                cash_balances.extend(futu_cash)
                if futu_summary:
                    by_broker["futu"] = futu_summary

                logger.info(f"Collected {len(futu_positions)} positions, "
                           f"{len(futu_cash)} cash entries from Futu")
            except Exception as e:
                logger.error(f"Error collecting from Futu: {e}")

        # Fetch Greeks for Futu option positions via IBKR
        # Futu doesn't provide Greeks without extra subscription, so we use IBKR
        if futu_option_positions and self._ibkr and self._ibkr.is_available:
            self._fetch_greeks_for_futu_options(futu_option_positions)

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

    def _fetch_greeks_for_futu_options(
        self,
        futu_options: list[AccountPosition],
    ) -> None:
        """Fetch Greeks for Futu option positions via IBKR.

        Futu doesn't provide Greeks data without extra subscription,
        so we use IBKR's fetch_greeks_for_hk_option() method to get Greeks.

        Args:
            futu_options: List of Futu option positions to fetch Greeks for.
        """
        if not self._ibkr or not self._ibkr.is_available:
            logger.warning("Cannot fetch Greeks for Futu options: IBKR not available")
            return

        logger.info(f"Fetching Greeks for {len(futu_options)} Futu option positions via IBKR")

        for pos in futu_options:
            try:
                # Use the underlying field which contains IBKR-compatible stock code
                # (e.g., "9988" for ALB, "700" for TCH)
                underlying = pos.underlying
                strike = pos.strike
                expiry = pos.expiry  # Should be in YYYYMMDD format
                option_type = pos.option_type  # "call" or "put"

                if not all([underlying, strike, expiry, option_type]):
                    logger.debug(f"Missing option details for {pos.symbol}: "
                                f"underlying={underlying}, strike={strike}, expiry={expiry}, type={option_type}")
                    continue

                logger.info(f"Fetching Greeks for {pos.symbol} via IBKR: "
                           f"underlying={underlying}, strike={strike}, expiry={expiry}, type={option_type}")

                # Fetch Greeks via IBKR
                greeks = self._ibkr.fetch_greeks_for_hk_option(
                    underlying=underlying,
                    strike=strike,
                    expiry=expiry,
                    option_type=option_type,
                )

                if greeks:
                    pos.delta = greeks.get("delta")
                    pos.gamma = greeks.get("gamma")
                    pos.theta = greeks.get("theta")
                    pos.vega = greeks.get("vega")
                    pos.iv = greeks.get("iv")
                    logger.info(f"Updated Greeks for {pos.symbol}: delta={pos.delta}, iv={pos.iv}")
                else:
                    logger.warning(f"No Greeks returned for {pos.symbol}")

            except Exception as e:
                logger.warning(f"Error fetching Greeks for Futu option {pos.symbol}: {e}")

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
