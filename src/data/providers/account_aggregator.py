"""Multi-broker account aggregator.

Consolidates positions and cash from multiple brokers (IBKR, Futu)
into a unified portfolio view with currency conversion.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
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

                # Assign margin to IBKR positions
                if ibkr_summary and ibkr_summary.margin_used:
                    self._assign_position_margins(ibkr_positions, ibkr_summary.margin_used)

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

                # Assign margin to Futu positions
                if futu_summary and futu_summary.margin_used:
                    self._assign_position_margins(futu_positions, futu_summary.margin_used)

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

        # Merge positions and convert to base currency
        merged_positions = self._merge_positions(positions, base_currency)

        # Calculate totals in base currency
        total_value = self._calc_total_value(positions, cash_balances, base_currency)
        total_pnl = self._calc_total_pnl(positions, base_currency)

        logger.info(f"Consolidated portfolio: {len(positions)} raw -> {len(merged_positions)} merged positions, "
                   f"total value={total_value:.2f} {base_currency}, "
                   f"unrealized P&L={total_pnl:.2f} {base_currency}")

        return ConsolidatedPortfolio(
            positions=merged_positions,
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

    def _assign_position_margins(
        self,
        positions: list[AccountPosition],
        margin_used: float,
    ) -> None:
        """Assign margin to positions proportionally by market value.

        Distributes the account-level margin_used to individual positions
        based on their market_value proportion.

        Args:
            positions: List of positions to assign margin to.
            margin_used: Total margin used for these positions.
        """
        if not margin_used or margin_used <= 0:
            return

        # Calculate total market value (use absolute value)
        total_mv = sum(abs(p.market_value) for p in positions)
        if total_mv == 0:
            return

        # Assign margin proportionally
        for pos in positions:
            pos.margin = margin_used * abs(pos.market_value) / total_mv

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to a canonical form for merging.

        Handles different broker formats:
        - IBKR: "9988.HK", "0700.HK", "AAPL"
        - Futu: "HK.09988", "HK.00700", "US.AAPL"

        Returns:
            Normalized symbol like "9988", "700", "AAPL"
        """
        symbol = symbol.upper()

        # Remove market prefix (Futu format: "HK.09988", "US.AAPL")
        if symbol.startswith(("US.", "HK.", "SH.", "SZ.")):
            symbol = symbol.split(".", 1)[1]

        # Remove market suffix (IBKR format: "9988.HK")
        if symbol.endswith((".HK", ".SH", ".SZ")):
            symbol = symbol.rsplit(".", 1)[0]

        # Remove leading zeros for HK stocks (09988 -> 9988)
        if re.match(r"^0+\d+$", symbol):
            symbol = symbol.lstrip("0")

        return symbol

    def _convert_position_currency(
        self,
        pos: AccountPosition,
        base_currency: str,
    ) -> AccountPosition:
        """Convert position values to base currency.

        Currency conversion rules for Greeks (based on their mathematical definitions):
        - Delta (∂C/∂S): No conversion - dimensionless ratio (currency/currency cancels)
        - Gamma (∂Δ/∂S): Divide by rate - unit is 1/currency
        - Theta (∂C/∂t): Multiply by rate - unit is currency/day
        - Vega (∂C/∂σ): Multiply by rate - unit is currency/%
        - Rho (∂C/∂r): Multiply by rate - unit is currency/%

        Args:
            pos: Original position.
            base_currency: Target currency.

        Returns:
            New position with converted values.
        """
        if pos.currency == base_currency:
            return pos

        # Create a copy to avoid modifying original
        converted = deepcopy(pos)

        # Get the conversion rate (e.g., HKD→USD: rate ≈ 0.128)
        rate = self._converter.get_rate(pos.currency, base_currency)

        # Price fields: multiply by rate (HKD → USD)
        converted.market_value = pos.market_value * rate
        converted.unrealized_pnl = pos.unrealized_pnl * rate
        converted.realized_pnl = pos.realized_pnl * rate
        converted.avg_cost = pos.avg_cost * rate

        # Convert underlying_price for strategy calculations
        if pos.underlying_price is not None:
            converted.underlying_price = pos.underlying_price * rate

        # Convert strike for strategy calculations (critical for HK options!)
        if pos.strike is not None:
            converted.strike = pos.strike * rate

        if pos.gamma is not None and converted.underlying_price is not None:
            #   → "股价每上涨 1 港币，Delta 增加 0.0067"   → "股价每上涨 1 美元，Delta 增加 0.0067 × 7.77 = 0.052"  
            converted.gamma = pos.gamma / rate
        if pos.theta is not None:
            # "每过1天，期权价格下跌 0.0819 港币"  -> "每过1天，期权价格下跌 0.0105 美元"   
            converted.theta = pos.theta * rate
        if pos.vega is not None:
           # "IV每上升1%，期权价格上涨 0.3664 港币"  → "IV每上升1%，期权价格上涨 0.0471 美元"      
            converted.vega = pos.vega * rate

        converted.currency = base_currency

        return converted

    def _merge_positions(
        self,
        positions: list[AccountPosition],
        base_currency: str,
    ) -> list[AccountPosition]:
        """Merge positions with the same underlying across brokers.

        Only merges stock positions. Options are kept separate due to
        different strikes/expiries.

        Args:
            positions: List of positions to merge.
            base_currency: Currency for converted values.

        Returns:
            List of merged positions.
        """
        # First convert all positions to base currency
        converted_positions = [
            self._convert_position_currency(p, base_currency) for p in positions
        ]

        # Separate stocks and options
        stocks: dict[str, list[AccountPosition]] = {}
        options: list[AccountPosition] = []

        for pos in converted_positions:
            if pos.asset_type == AssetType.OPTION:
                options.append(pos)
            else:
                # Group stocks by normalized symbol
                norm_symbol = self._normalize_symbol(pos.symbol)
                if norm_symbol not in stocks:
                    stocks[norm_symbol] = []
                stocks[norm_symbol].append(pos)

        # Merge stocks with same symbol
        merged: list[AccountPosition] = []
        for norm_symbol, pos_list in stocks.items():
            if len(pos_list) == 1:
                # Single position, keep as is (preserve original symbol with market suffix)
                merged.append(pos_list[0])
            else:
                # Multiple positions, merge them (use first position's symbol)
                merged_pos = self._merge_stock_positions(pos_list[0].symbol, pos_list)
                merged.append(merged_pos)

        # Add options (not merged)
        merged.extend(options)

        return merged

    def _merge_stock_positions(
        self,
        symbol: str,
        positions: list[AccountPosition],
    ) -> AccountPosition:
        """Merge multiple stock positions into one.

        Args:
            symbol: Normalized symbol.
            positions: List of positions to merge.

        Returns:
            Merged position.
        """
        total_qty = sum(p.quantity for p in positions)
        total_market_value = sum(p.market_value for p in positions)
        total_unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        total_realized_pnl = sum(p.realized_pnl for p in positions)

        # Weighted average cost
        total_cost = sum(p.avg_cost * p.quantity for p in positions)
        avg_cost = total_cost / total_qty if total_qty != 0 else 0

        # Sum margins from all positions
        total_margin = sum(p.margin for p in positions if p.margin is not None)
        merged_margin = total_margin if total_margin > 0 else None

        # Use first position as base
        base = positions[0]
        brokers = list(set(p.broker for p in positions))

        return AccountPosition(
            symbol=symbol,
            asset_type=AssetType.STOCK,
            market=base.market,
            quantity=total_qty,
            avg_cost=avg_cost,
            market_value=total_market_value,
            unrealized_pnl=total_unrealized_pnl,
            realized_pnl=total_realized_pnl,
            currency=base.currency,  # Already converted to base
            delta=1.0,  # Stock delta is always 1
            margin=merged_margin,  # Sum of margins from all brokers
            broker="+".join(brokers),  # e.g., "ibkr+futu"
            last_updated=datetime.now(),
        )

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
                    pos.underlying_price = greeks.get("underlying_price")

                    # Fallback: If underlying_price still None, try Futu
                    if pos.underlying_price is None and self._futu:
                        try:
                            # Convert underlying code to Futu symbol format
                            # underlying is like "700" or "9988"
                            futu_symbol = f"HK.{int(underlying):05d}"  # "700" → "HK.00700"
                            quote = self._futu.get_stock_quote(futu_symbol)
                            if quote and quote.close:
                                pos.underlying_price = quote.close
                                logger.info(f"Got underlying_price from Futu for {pos.symbol}: {pos.underlying_price}")
                        except Exception as e:
                            logger.debug(f"Could not fetch underlying price from Futu for {underlying}: {e}")

                    logger.info(f"Updated Greeks for {pos.symbol}: delta={pos.delta}, "
                               f"iv={pos.iv}, undPrice={pos.underlying_price}")
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
