"""B-S Synthetic LEAPS Option Chain Provider.

Decorator over DuckDBProvider that intercepts get_option_chain() to generate
synthetic LEAPS contracts using Black-Scholes pricing. All other methods
delegate to the base provider.

IV estimation uses VIX + term structure decay + moneyness skew.
Useful for backtesting LEAPS strategies over 10+ years where historical
option chain data is unavailable (ThetaData free tier only covers 2023-06+).
"""

import logging
import math
from datetime import date, datetime, timedelta

from src.data.models.option import (
    Greeks,
    OptionChain,
    OptionContract,
    OptionQuote,
    OptionType,
)
from src.engine.bs.core import calc_bs_price
from src.engine.bs.greeks import calc_bs_greeks
from src.engine.models.bs_params import BSParams

logger = logging.getLogger(__name__)



class SyntheticLeapsProvider:
    """B-S synthetic LEAPS option chain provider.

    Wraps a DuckDBProvider, intercepting only get_option_chain() to generate
    synthetic call contracts via Black-Scholes. All other methods delegate
    to the base provider unchanged.

    IV Estimation Model:
        1. Term structure decay: long-dated IV < short-dated VIX
           base_iv = vix * (1 - 0.15 * (1 - exp(-dte/180)))
        2. Moneyness skew: ITM calls (low moneyness) have slightly higher IV
           skew = 0.15 * (1 - moneyness)

    Args:
        base_provider: DuckDBProvider instance for stock/macro data
        dividend_yield: Annual dividend yield for spot adjustment (default 1.3% for SPY)
    """

    def __init__(
        self,
        base_provider,
        dividend_yield: float = 0.013,
    ):
        self._base = base_provider
        self._dividend_yield = dividend_yield

        # Per-day cache: (symbol, as_of_date) → full OptionChain (all expiries)
        # Cleared when as_of_date changes via set_as_of_date()
        self._chain_cache: dict[tuple[str, date], OptionChain | None] = {}
        # Cache VIX/TNX per date to avoid repeated macro lookups
        self._vix_cache: dict[date, float] = {}
        self._tnx_cache: dict[date, float] = {}

    # --- Delegated properties ---

    @property
    def name(self) -> str:
        return f"synthetic_leaps({self._base.name})"

    @property
    def is_available(self) -> bool:
        return self._base.is_available

    # --- Delegated methods (pass-through to base) ---

    def set_as_of_date(self, d: date) -> None:
        # Clear date-sensitive caches when date changes
        if d != self._base._as_of_date:
            self._chain_cache.clear()
        return self._base.set_as_of_date(d)

    def get_stock_quote(self, symbol: str):
        return self._base.get_stock_quote(symbol)

    def get_stock_quotes(self, symbols: list[str]):
        return self._base.get_stock_quotes(symbols)

    def get_history_kline(self, symbol, ktype, start_date, end_date):
        return self._base.get_history_kline(symbol, ktype, start_date, end_date)

    def get_option_quote(self, symbol: str):
        return self._base.get_option_quote(symbol)

    # NOTE: get_option_quotes_batch intentionally NOT delegated.
    # LeapsContractSelector checks hasattr(dp, 'get_option_quotes_batch')
    # to decide whether to fetch quotes separately. For synthetic data,
    # get_option_chain() already returns full quotes (price, greeks, bid/ask),
    # so the selector should use the chain directly (the `else` branch).

    def get_fundamental(self, symbol: str):
        return self._base.get_fundamental(symbol)

    def get_macro_data(self, indicator: str, start_date: date, end_date: date):
        return self._base.get_macro_data(indicator, start_date, end_date)

    def get_stock_volatility(self, symbol: str):
        return self._base.get_stock_volatility(symbol)

    def check_macro_blackout(self, target_date=None, blackout_days=2, blackout_events=None):
        return self._base.check_macro_blackout(target_date, blackout_days, blackout_events)

    def get_trading_days(self, start_date: date, end_date: date, symbol: str | None = None):
        return self._base.get_trading_days(start_date, end_date, symbol)

    def normalize_symbol(self, symbol: str) -> str:
        return self._base.normalize_symbol(symbol)

    # --- Core: synthetic option chain generation ---

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
        expiry_min_days: int | None = None,
        expiry_max_days: int | None = None,
        **kwargs,
    ) -> OptionChain | None:
        """Generate synthetic LEAPS option chain using B-S model.

        Caches the full chain per (symbol, as_of_date) and filters by expiry
        range in-memory. This avoids re-computing B-S pricing on every call
        within the same trading day (position updates, screening, monitoring
        all hit this method).
        """
        underlying = underlying.upper()
        as_of_date = self._base._as_of_date

        # Convert min/max days to dates
        if expiry_min_days is not None and expiry_start is None:
            expiry_start = as_of_date + timedelta(days=expiry_min_days)
        if expiry_max_days is not None and expiry_end is None:
            expiry_end = as_of_date + timedelta(days=expiry_max_days)

        # Look up full chain from cache (or generate once)
        cache_key = (underlying, as_of_date)
        if cache_key not in self._chain_cache:
            self._chain_cache[cache_key] = self._build_full_chain(underlying, as_of_date)

        full_chain = self._chain_cache[cache_key]
        if full_chain is None:
            return None

        # Filter by expiry range in-memory
        if expiry_start is None and expiry_end is None:
            return full_chain

        filtered_calls = full_chain.calls
        filtered_expiries = full_chain.expiry_dates

        if expiry_start is not None:
            filtered_calls = [c for c in filtered_calls if c.contract.expiry_date >= expiry_start]
            filtered_expiries = [e for e in filtered_expiries if e >= expiry_start]
        if expiry_end is not None:
            filtered_calls = [c for c in filtered_calls if c.contract.expiry_date <= expiry_end]
            filtered_expiries = [e for e in filtered_expiries if e <= expiry_end]

        return OptionChain(
            underlying=full_chain.underlying,
            timestamp=full_chain.timestamp,
            expiry_dates=filtered_expiries,
            calls=filtered_calls,
            puts=[],
            source=full_chain.source,
        )

    def _build_full_chain(self, underlying: str, as_of_date: date) -> OptionChain | None:
        """Build the full synthetic chain for all expiries (cached once per day)."""
        stock_quote = self._base.get_stock_quote(underlying)
        if stock_quote is None:
            logger.warning(f"No stock quote for {underlying} on {as_of_date}")
            return None
        spot = stock_quote.close

        vix = self._get_vix(as_of_date)
        risk_free_rate = self._get_risk_free_rate(as_of_date)

        # Generate wide range: 30 to 600 days out (covers all possible queries)
        expiry_start = as_of_date + timedelta(days=30)
        expiry_end = as_of_date + timedelta(days=600)

        return self._generate_synthetic_chain(
            underlying=underlying,
            spot=spot,
            vix=vix,
            risk_free_rate=risk_free_rate,
            as_of_date=as_of_date,
            expiry_start=expiry_start,
            expiry_end=expiry_end,
        )

    def _generate_synthetic_chain(
        self,
        underlying: str,
        spot: float,
        vix: float,
        risk_free_rate: float,
        as_of_date: date,
        expiry_start: date,
        expiry_end: date,
    ) -> OptionChain:
        """Generate synthetic LEAPS call option chain."""
        # Generate expiry dates (monthly 3rd Friday)
        expiries = self._generate_monthly_expiries(as_of_date, expiry_start, expiry_end)

        # Generate strike grid
        strikes = self._generate_strike_grid(spot)

        calls: list[OptionQuote] = []
        expiry_dates: list[date] = []
        timestamp = datetime.combine(as_of_date, datetime.min.time())

        for expiry in expiries:
            dte = (expiry - as_of_date).days
            if dte <= 0:
                continue

            T = dte / 365.0
            # Dividend-adjusted spot for B-S pricing
            spot_adj = spot * math.exp(-self._dividend_yield * T)

            for strike in strikes:
                moneyness = strike / spot
                iv = self._estimate_iv(vix, dte, moneyness)

                params = BSParams(
                    spot_price=spot_adj,
                    strike_price=strike,
                    risk_free_rate=risk_free_rate,
                    volatility=iv,
                    time_to_expiry=T,
                    is_call=True,
                )

                price = calc_bs_price(params)
                if price is None or price <= 0:
                    continue

                greeks_dict = calc_bs_greeks(params)

                # Build bid/ask with realistic spread
                spread = self._estimate_spread(price, moneyness, dte)
                bid = max(0.01, price - spread / 2)
                ask = price + spread / 2

                # Generate option symbol: UNDERLYING_YYMMDD_C_STRIKE
                symbol = (
                    f"{underlying}_{expiry.strftime('%y%m%d')}_C_"
                    f"{strike:.0f}"
                )

                contract = OptionContract(
                    symbol=symbol,
                    underlying=underlying,
                    option_type=OptionType.CALL,
                    strike_price=strike,
                    expiry_date=expiry,
                    lot_size=100,
                )

                quote = OptionQuote(
                    contract=contract,
                    timestamp=timestamp,
                    last_price=price,
                    bid=bid,
                    ask=ask,
                    volume=500,
                    open_interest=1000,
                    iv=iv,
                    greeks=Greeks(
                        delta=greeks_dict.get("delta"),
                        gamma=greeks_dict.get("gamma"),
                        theta=greeks_dict.get("theta"),
                        vega=greeks_dict.get("vega"),
                        rho=greeks_dict.get("rho"),
                    ),
                    source="synthetic_bs",
                    open=price,
                    high=price * 1.01,
                    low=price * 0.99,
                    close=price,
                )

                calls.append(quote)

            expiry_dates.append(expiry)

        return OptionChain(
            underlying=underlying,
            timestamp=timestamp,
            expiry_dates=sorted(expiry_dates),
            calls=calls,
            puts=[],  # LEAPS strategy only needs calls
            source="synthetic_bs",
        )

    # --- IV Estimation ---

    def _estimate_iv(self, vix: float, dte: int, moneyness: float) -> float:
        """Estimate implied volatility from VIX.

        Args:
            vix: Current VIX value (already decimal, e.g. 0.20 for VIX=20)
            dte: Days to expiration
            moneyness: strike / spot (< 1 = ITM call)

        Returns:
            Annualized implied volatility as decimal
        """
        # 1. Term structure decay: long-dated IV < short-dated VIX
        #    Empirically, 1Y IV ≈ 85% of VIX for equity indices
        term_factor = 1.0 - 0.15 * (1 - math.exp(-dte / 180))
        base_iv = vix * term_factor

        # 2. Moneyness skew: ITM calls (low moneyness) have slightly higher IV
        #    Deep ITM call (moneyness=0.85) → skew ≈ +2.25%
        skew = 0.15 * (1.0 - moneyness)

        return base_iv * (1.0 + skew)

    # --- Helpers ---

    def _get_vix(self, as_of_date: date) -> float:
        """Get VIX value for the given date, returned as decimal (e.g., 0.20)."""
        if as_of_date in self._vix_cache:
            return self._vix_cache[as_of_date]
        vix_data = self._base.get_macro_data("^VIX", as_of_date - timedelta(days=7), as_of_date)
        if vix_data:
            val = vix_data[-1].value / 100.0
            self._vix_cache[as_of_date] = val
            return val
        logger.warning(f"No VIX data for {as_of_date}, using default 0.20")
        self._vix_cache[as_of_date] = 0.20
        return 0.20

    def _get_risk_free_rate(self, as_of_date: date) -> float:
        """Get 10Y Treasury yield as decimal (e.g., 0.045 for 4.5%)."""
        if as_of_date in self._tnx_cache:
            return self._tnx_cache[as_of_date]
        tnx_data = self._base.get_macro_data("^TNX", as_of_date - timedelta(days=7), as_of_date)
        if tnx_data:
            val = tnx_data[-1].value / 1000.0
            self._tnx_cache[as_of_date] = val
            return val
        logger.warning(f"No TNX data for {as_of_date}, using default 0.04")
        self._tnx_cache[as_of_date] = 0.04
        return 0.04

    def _generate_monthly_expiries(
        self,
        as_of_date: date,
        expiry_start: date,
        expiry_end: date,
    ) -> list[date]:
        """Generate monthly option expiry dates (3rd Friday of each month)."""
        expiries = []
        # Start from expiry_start month
        current = date(expiry_start.year, expiry_start.month, 1)

        while current <= expiry_end:
            third_friday = self._third_friday(current.year, current.month)
            if expiry_start <= third_friday <= expiry_end and third_friday > as_of_date:
                expiries.append(third_friday)
            # Move to next month
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        return sorted(expiries)

    @staticmethod
    def _third_friday(year: int, month: int) -> date:
        """Calculate the 3rd Friday of a given month."""
        # Find the first day of the month
        first_day = date(year, month, 1)
        # weekday(): Monday=0, Friday=4
        first_friday_offset = (4 - first_day.weekday()) % 7
        first_friday = first_day + timedelta(days=first_friday_offset)
        # Third Friday = first Friday + 14 days
        return first_friday + timedelta(days=14)

    def _generate_strike_grid(self, spot: float) -> list[float]:
        """Generate strike prices as a dense, evenly-spaced grid around spot.

        The grid covers [spot*0.70, spot*1.15] at standard increments:
        - spot < 50: $1
        - 50 <= spot < 200: $2.5
        - spot >= 200: $5

        This ensures that any standard strike opened on a previous day
        will still appear in today's grid despite small spot movements.
        """
        if spot < 50:
            increment = 1.0
        elif spot < 200:
            increment = 2.5
        else:
            increment = 5.0

        lo = math.floor(spot * 0.70 / increment) * increment
        hi = math.ceil(spot * 1.15 / increment) * increment

        strikes = []
        s = lo
        while s <= hi:
            if s > 0:
                strikes.append(s)
            s = round(s + increment, 2)

        return strikes

    def _estimate_spread(self, price: float, moneyness: float, dte: int) -> float:
        """Estimate bid-ask spread for synthetic quote.

        LEAPS have wider spreads than short-dated options.
        Deep ITM options have tighter spreads relative to price.
        """
        # Base spread: ~2% of price for ATM, wider for OTM
        base_pct = 0.02
        if moneyness > 1.05:  # OTM
            base_pct = 0.04
        elif moneyness < 0.90:  # Deep ITM
            base_pct = 0.015

        # LEAPS spread widening: longer-dated = wider
        dte_factor = 1.0 + 0.3 * min(dte / 365, 1.5)

        spread = price * base_pct * dte_factor
        # Minimum spread: $0.05
        return max(0.05, spread)
