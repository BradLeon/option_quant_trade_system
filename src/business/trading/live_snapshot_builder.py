"""Live Snapshot Builder — Build MarketSnapshot & PortfolioState from live data.

Mirrors BacktestExecutor._build_market_snapshot() / _build_portfolio_state()
but sources data from real-time IBKR/Yahoo providers instead of DuckDB.

Usage:
    builder = LiveSnapshotBuilder(data_provider, symbols=["SPY", "AAPL"])
    market = builder.build_market_snapshot()
    portfolio = builder.build_portfolio_state(consolidated_portfolio)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from src.data.models.account import AccountPosition, AssetType, ConsolidatedPortfolio
from src.strategy.models import (
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    PositionView,
)
from src.business.trading.account_bridge import portfolio_to_account_state

logger = logging.getLogger(__name__)


class LiveSnapshotBuilder:
    """Build read-only snapshots from live market data and IBKR account.

    Provides the same MarketSnapshot / PortfolioState interfaces that
    strategies expect, but populated from real-time data instead of
    historical DuckDB queries.
    """

    def __init__(
        self,
        data_provider: Any,
        symbols: list[str],
    ) -> None:
        """Initialize builder.

        Args:
            data_provider: Live DataProvider (UnifiedDataProvider / IBKRProvider / YahooProvider)
            symbols: List of underlying symbols to track prices for
        """
        self._dp = data_provider
        self._symbols = symbols

    def build_market_snapshot(self) -> MarketSnapshot:
        """Build MarketSnapshot from live market data.

        Fetches real-time stock quotes for all tracked symbols,
        plus VIX and risk-free rate from macro data.
        """
        prices: dict[str, float] = {}

        # Fetch stock prices
        for symbol in self._symbols:
            try:
                price = self._get_stock_price(symbol)
                if price and price > 0:
                    prices[symbol] = price
                else:
                    logger.warning(f"No valid price for {symbol}")
            except Exception as e:
                logger.warning(f"Failed to get quote for {symbol}: {e}")

        # Fetch VIX
        vix = self._get_vix()

        # Fetch risk-free rate (10Y Treasury yield)
        risk_free_rate = self._get_risk_free_rate()

        return MarketSnapshot(
            date=date.today(),
            prices=prices,
            vix=vix,
            risk_free_rate=risk_free_rate,
        )

    def build_portfolio_state(
        self,
        portfolio: ConsolidatedPortfolio,
    ) -> PortfolioState:
        """Build PortfolioState from IBKR account data.

        Converts each AccountPosition to a PositionView with Instrument,
        and extracts account-level metrics (NLV, cash, margin).

        Args:
            portfolio: ConsolidatedPortfolio from AccountAggregator
        """
        positions: list[PositionView] = []

        for ap in portfolio.positions:
            # Skip cash entries
            if ap.asset_type == AssetType.CASH:
                continue

            try:
                pv = self._account_position_to_view(ap)
                positions.append(pv)
            except Exception as e:
                logger.warning(
                    f"Failed to convert position {ap.symbol}: {e}"
                )

        # Get account-level metrics via existing bridge
        account_state = portfolio_to_account_state(portfolio)

        return PortfolioState(
            date=date.today(),
            nlv=account_state.total_equity,
            cash=account_state.cash_balance,
            margin_used=account_state.used_margin,
            positions=positions,
        )

    def _account_position_to_view(self, ap: AccountPosition) -> PositionView:
        """Convert a single AccountPosition to PositionView."""
        instrument = self._make_instrument(ap)
        position_id = self._make_position_id(ap, instrument)
        current_price = self._calc_per_unit_price(ap)
        dte = self._calc_dte(ap)

        return PositionView(
            position_id=position_id,
            instrument=instrument,
            quantity=int(ap.quantity),
            entry_price=ap.avg_cost,
            entry_date=date.today(),  # IBKR doesn't expose open date
            current_price=current_price,
            underlying_price=ap.underlying_price or 0.0,
            unrealized_pnl=ap.unrealized_pnl,
            delta=ap.delta,
            gamma=ap.gamma,
            theta=ap.theta,
            vega=ap.vega,
            iv=ap.iv,
            dte=dte,
            lot_size=ap.contract_multiplier or 100,
        )

    def _make_instrument(self, ap: AccountPosition) -> Instrument:
        """Create Instrument from AccountPosition."""
        if ap.asset_type == AssetType.OPTION:
            right = None
            if ap.option_type:
                right = (
                    OptionRight.CALL
                    if ap.option_type.lower() in ("call", "c")
                    else OptionRight.PUT
                )

            expiry = None
            if ap.expiry:
                try:
                    # Handle both YYYY-MM-DD and YYYYMMDD formats
                    exp_str = ap.expiry.replace("-", "")
                    expiry = datetime.strptime(exp_str, "%Y%m%d").date()
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid expiry format: {ap.expiry}")

            return Instrument(
                type=InstrumentType.OPTION,
                underlying=ap.underlying or ap.symbol,
                right=right,
                strike=ap.strike,
                expiry=expiry,
                lot_size=ap.contract_multiplier or 100,
            )
        else:
            return Instrument(
                type=InstrumentType.STOCK,
                underlying=ap.symbol,
                lot_size=1,
            )

    def _make_position_id(
        self, ap: AccountPosition, instrument: Instrument
    ) -> str:
        """Generate position_id matching Instrument.symbol format.

        This ensures EXIT signals from strategy can reference positions
        by the same ID format used when building PortfolioState.
        """
        return instrument.symbol

    def _calc_per_unit_price(self, ap: AccountPosition) -> float:
        """Calculate per-unit price from AccountPosition.

        For options: market_value / (abs(quantity) * multiplier)
        For stocks: market_value / abs(quantity)
        """
        qty = abs(ap.quantity)
        if qty == 0:
            return 0.0

        if ap.asset_type == AssetType.OPTION:
            multiplier = ap.contract_multiplier or 100
            return abs(ap.market_value) / (qty * multiplier)
        else:
            return abs(ap.market_value) / qty

    def _calc_dte(self, ap: AccountPosition) -> int | None:
        """Calculate days to expiration."""
        if not ap.expiry:
            return None
        try:
            exp_str = ap.expiry.replace("-", "")
            exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
            return max(0, (exp_date - date.today()).days)
        except (ValueError, AttributeError):
            return None

    def _get_stock_price(self, symbol: str) -> float | None:
        """Get stock price with multiple fallbacks.

        Priority: last → close → prev_close → high → low → kline close.
        Handles non-market-hours where IBKR streaming data may be NaN.
        """
        # Try real-time quote first
        try:
            quote = self._dp.get_stock_quote(symbol)
            if quote:
                # Try multiple price fields in priority order
                for field in ("close", "prev_close", "high", "low", "open"):
                    val = getattr(quote, field, None)
                    if val is not None and val > 0:
                        return val
        except Exception:
            pass

        # Fallback: last kline close (works outside market hours)
        try:
            from src.data.models.stock import KlineType

            today = date.today()
            start = today - timedelta(days=5)
            klines = self._dp.get_history_kline(
                symbol=symbol, ktype=KlineType.DAY,
                start_date=start, end_date=today,
            )
            if klines:
                return klines[-1].close
        except Exception:
            pass

        return None

    def _get_vix(self) -> float | None:
        """Fetch current VIX value via macro data (index, not stock)."""
        return self._get_index_value("^VIX")

    def _get_risk_free_rate(self) -> float | None:
        """Fetch current risk-free rate (10Y Treasury yield).

        IBKR TNX = yield × 10 (e.g. TNX=42.5 means 4.25%).
        Yahoo ^TNX = yield directly (e.g. 4.25 means 4.25%).
        Returns as decimal (e.g. 0.0425).
        """
        value = self._get_index_value("^TNX")
        if value is not None:
            if value > 20:
                # IBKR convention: TNX = yield × 10
                return value / 1000.0
            else:
                # Yahoo convention: ^TNX = yield directly
                return value / 100.0
        return None

    def _get_index_value(self, indicator: str) -> float | None:
        """Fetch index value (VIX, TNX, etc.) via macro data.

        Uses get_macro_data which handles IBKR index contracts (secType=IND)
        rather than get_stock_quote (which only works for stocks).
        """
        try:
            today = date.today()
            start = today - timedelta(days=7)
            macro_data = self._dp.get_macro_data(indicator, start, today)
            if macro_data:
                return macro_data[-1].value
        except Exception as e:
            logger.warning(f"Failed to get {indicator}: {e}")
        return None
