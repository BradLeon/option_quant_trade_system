"""Currency conversion utilities.

Provides exchange rate fetching and currency conversion for
multi-broker portfolio consolidation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.providers.unified import UnifiedDataProvider

logger = logging.getLogger(__name__)


class CurrencyConverter:
    """Currency converter with live rate fetching.

    Fetches exchange rates from Yahoo Finance and provides
    currency conversion for portfolio consolidation.

    Example:
        >>> converter = CurrencyConverter()
        >>> converter.refresh_rates()
        >>> usd_amount = converter.convert(1000, "HKD", "USD")
        >>> print(f"1000 HKD = {usd_amount:.2f} USD")
    """

    # Default exchange rates (fallback when live rates unavailable)
    # Rates are expressed as: 1 foreign currency = X USD
    DEFAULT_RATES: dict[str, float] = {
        "USD": 1.0,
        "HKD": 0.128,  # ~7.8 HKD/USD
        "CNY": 0.14,   # ~7.1 CNY/USD
        "EUR": 1.05,   # ~0.95 EUR/USD
        "GBP": 1.27,   # ~0.79 GBP/USD
        "JPY": 0.0067, # ~150 JPY/USD
    }

    # Yahoo Finance forex pair symbols
    FOREX_SYMBOLS: dict[str, str] = {
        "HKD": "HKDUSD=X",
        "CNY": "CNYUSD=X",
        "EUR": "EURUSD=X",
        "GBP": "GBPUSD=X",
        "JPY": "JPYUSD=X",
    }

    def __init__(
        self,
        provider: UnifiedDataProvider | None = None,
        cache_ttl_minutes: int = 5,
    ):
        """Initialize currency converter.

        Args:
            provider: Data provider for fetching live rates.
            cache_ttl_minutes: Cache TTL for exchange rates.
        """
        self._provider = provider
        self._cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self._rates: dict[str, float] = dict(self.DEFAULT_RATES)
        self._last_refresh: datetime | None = None

    def refresh_rates(self) -> bool:
        """Refresh exchange rates from Yahoo Finance.

        Uses yfinance directly for reliable forex data.

        Returns:
            True if rates were refreshed successfully.
        """
        refreshed = False

        try:
            import yfinance as yf

            for currency, symbol in self.FOREX_SYMBOLS.items():
                try:
                    ticker = yf.Ticker(symbol)
                    # Get the most recent price
                    hist = ticker.history(period="1d")
                    if not hist.empty:
                        price = hist["Close"].iloc[-1]
                        if price and price > 0:
                            self._rates[currency] = float(price)
                            logger.debug(f"Updated {currency} rate: {price:.6f}")
                            refreshed = True
                    else:
                        # Try fast_info as fallback
                        fast_info = ticker.fast_info
                        if hasattr(fast_info, "last_price") and fast_info.last_price:
                            self._rates[currency] = float(fast_info.last_price)
                            logger.debug(f"Updated {currency} rate (fast_info): {fast_info.last_price:.6f}")
                            refreshed = True
                except Exception as e:
                    logger.warning(f"Failed to fetch {currency} rate: {e}")

            if refreshed:
                self._last_refresh = datetime.now()

        except ImportError:
            logger.warning("yfinance not installed, using default rates")

        return refreshed

    def get_rate(self, currency: str, to_currency: str = "USD") -> float:
        """Get exchange rate.

        Args:
            currency: Source currency code.
            to_currency: Target currency code (default: USD).

        Returns:
            Exchange rate (1 source = X target).
        """
        # Ensure rates are fresh
        self._ensure_fresh_rates()

        currency = currency.upper()
        to_currency = to_currency.upper()

        if currency == to_currency:
            return 1.0

        # Get rate to USD first
        from_rate = self._rates.get(currency, self.DEFAULT_RATES.get(currency, 1.0))

        # If converting to non-USD, need to convert back
        if to_currency != "USD":
            to_rate = self._rates.get(to_currency, self.DEFAULT_RATES.get(to_currency, 1.0))
            # from_rate is currency→USD, to_rate is to_currency→USD
            # We want currency→to_currency = (currency→USD) / (to_currency→USD)
            if to_rate > 0:
                return from_rate / to_rate
            return from_rate

        return from_rate

    def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str = "USD",
    ) -> float:
        """Convert amount between currencies.

        Args:
            amount: Amount to convert.
            from_currency: Source currency code.
            to_currency: Target currency code (default: USD).

        Returns:
            Converted amount.
        """
        rate = self.get_rate(from_currency, to_currency)
        return amount * rate

    def get_all_rates(self) -> dict[str, float]:
        """Get all current exchange rates (to USD).

        Returns:
            Dictionary of currency codes to USD rates.
        """
        self._ensure_fresh_rates()
        return dict(self._rates)

    def _ensure_fresh_rates(self) -> None:
        """Ensure rates are fresh, refresh if stale."""
        if self._last_refresh is None:
            self.refresh_rates()
            return

        if datetime.now() - self._last_refresh > self._cache_ttl:
            self.refresh_rates()

    def set_provider(self, provider: UnifiedDataProvider) -> None:
        """Set data provider for live rate fetching.

        Args:
            provider: Data provider instance.
        """
        self._provider = provider
        # Reset refresh timestamp to force refresh on next use
        self._last_refresh = None
