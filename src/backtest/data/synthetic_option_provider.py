"""Synthetic Option Chain Fallback Provider.

Decorator over DuckDBProvider that automatically generates BSM-based synthetic
option chains when real historical data is unavailable. All other methods
delegate to the base provider.

When get_option_chain() returns None from the base provider (no parquet data
for that symbol/date), this provider generates a synthetic chain using:
- Black-Scholes pricing with IV estimated from VIX + term structure + skew
- Both calls AND puts (unlike SyntheticLeapsProvider which only generates calls)
- Short to medium-term expiries (weekly + monthly, 7-365 days)

This enables backtesting short_put strategies over date ranges where real
ThetaData option chains are unavailable (before 2023-06).

Validated by scripts/bsm_vs_market_analysis.py:
  MAPE(ATM) < 1.03%, MAPE(OTM) < 1.33%, R² > 0.999, Delta MAE < 0.002
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


class SyntheticOptionFallbackProvider:
    """BSM synthetic option chain fallback provider.

    Wraps a DuckDBProvider. When get_option_chain() returns real data, passes
    it through unchanged. When real data is unavailable (returns None), generates
    a synthetic chain with both calls and puts via Black-Scholes.

    Usage:
        base = DuckDBProvider(data_dir)
        provider = SyntheticOptionFallbackProvider(base)
        # Now use provider as drop-in replacement — identical API
    """

    def __init__(self, base_provider, dividend_yield: float = 0.013):
        self._base = base_provider
        self._dividend_yield = dividend_yield

        # Per-day cache: (symbol, as_of_date) → OptionChain (synthetic only)
        self._synth_cache: dict[tuple[str, date], OptionChain | None] = {}
        # Track which (symbol, date) pairs used synthetic vs real data
        self._synthetic_dates: set[tuple[str, date]] = set()
        # Macro caches
        self._vix_cache: dict[date, float] = {}
        self._tnx_cache: dict[date, float] = {}

    # --- Delegated properties ---

    @property
    def name(self) -> str:
        return f"synthetic_fallback({self._base.name})"

    @property
    def is_available(self) -> bool:
        return self._base.is_available

    # --- Delegated methods (pass-through to base) ---

    def set_as_of_date(self, d: date) -> None:
        if d != self._base._as_of_date:
            self._synth_cache.clear()
        return self._base.set_as_of_date(d)

    def get_stock_quote(self, symbol: str):
        return self._base.get_stock_quote(symbol)

    def get_stock_quotes(self, symbols: list[str]):
        return self._base.get_stock_quotes(symbols)

    def get_history_kline(self, symbol, ktype, start_date, end_date):
        return self._base.get_history_kline(symbol, ktype, start_date, end_date)

    def get_option_quote(self, symbol: str):
        return self._base.get_option_quote(symbol)

    def get_option_quotes_batch(self, contracts, min_volume=None):
        return self._base.get_option_quotes_batch(contracts, min_volume)

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

    # --- Core: option chain with synthetic fallback ---

    def get_option_chain(
        self,
        underlying: str,
        expiry_start: date | None = None,
        expiry_end: date | None = None,
        expiry_min_days: int | None = None,
        expiry_max_days: int | None = None,
        **kwargs,
    ) -> OptionChain | None:
        """Get option chain — real data first, synthetic fallback if unavailable."""
        # Try real data first
        real_chain = self._base.get_option_chain(
            underlying,
            expiry_start=expiry_start,
            expiry_end=expiry_end,
            expiry_min_days=expiry_min_days,
            expiry_max_days=expiry_max_days,
            **kwargs,
        )
        if real_chain is not None:
            return real_chain

        # Real data unavailable — generate synthetic
        underlying = underlying.upper()
        as_of_date = self._base._as_of_date

        # Convert min/max days to dates
        if expiry_min_days is not None and expiry_start is None:
            expiry_start = as_of_date + timedelta(days=expiry_min_days)
        if expiry_max_days is not None and expiry_end is None:
            expiry_end = as_of_date + timedelta(days=expiry_max_days)

        # Build full synthetic chain (cached per day)
        cache_key = (underlying, as_of_date)
        if cache_key not in self._synth_cache:
            self._synth_cache[cache_key] = self._build_full_chain(underlying, as_of_date)
            if self._synth_cache[cache_key] is not None:
                self._synthetic_dates.add(cache_key)

        full_chain = self._synth_cache[cache_key]
        if full_chain is None:
            return None

        # Filter by expiry range
        if expiry_start is None and expiry_end is None:
            return full_chain

        filtered_calls = full_chain.calls
        filtered_puts = full_chain.puts
        filtered_expiries = full_chain.expiry_dates

        if expiry_start is not None:
            filtered_calls = [c for c in filtered_calls if c.contract.expiry_date >= expiry_start]
            filtered_puts = [p for p in filtered_puts if p.contract.expiry_date >= expiry_start]
            filtered_expiries = [e for e in filtered_expiries if e >= expiry_start]
        if expiry_end is not None:
            filtered_calls = [c for c in filtered_calls if c.contract.expiry_date <= expiry_end]
            filtered_puts = [p for p in filtered_puts if p.contract.expiry_date <= expiry_end]
            filtered_expiries = [e for e in filtered_expiries if e <= expiry_end]

        return OptionChain(
            underlying=full_chain.underlying,
            timestamp=full_chain.timestamp,
            expiry_dates=filtered_expiries,
            calls=filtered_calls,
            puts=filtered_puts,
            source=full_chain.source,
        )

    def _build_full_chain(self, underlying: str, as_of_date: date) -> OptionChain | None:
        """Build full synthetic chain covering 7-365 days out."""
        stock_quote = self._base.get_stock_quote(underlying)
        if stock_quote is None:
            logger.warning(f"[SyntheticFallback] No stock quote for {underlying} on {as_of_date}")
            return None
        spot = stock_quote.close

        vix = self._get_vix(as_of_date)
        risk_free_rate = self._get_risk_free_rate(as_of_date)

        logger.debug(
            f"[SyntheticFallback] Generating chain for {underlying} on {as_of_date}: "
            f"spot={spot:.2f} vix={vix:.4f} rfr={risk_free_rate:.4f}"
        )

        return self._generate_chain(
            underlying=underlying,
            spot=spot,
            vix=vix,
            risk_free_rate=risk_free_rate,
            as_of_date=as_of_date,
        )

    def _generate_chain(
        self,
        underlying: str,
        spot: float,
        vix: float,
        risk_free_rate: float,
        as_of_date: date,
    ) -> OptionChain:
        """Generate synthetic option chain with both calls and puts."""
        expiry_start = as_of_date + timedelta(days=7)
        expiry_end = as_of_date + timedelta(days=365)

        # Generate weekly + monthly expiries
        expiries = self._generate_expiries(as_of_date, expiry_start, expiry_end)
        strikes = self._generate_strike_grid(spot)

        calls: list[OptionQuote] = []
        puts: list[OptionQuote] = []
        expiry_dates: list[date] = []
        timestamp = datetime.combine(as_of_date, datetime.min.time())

        for expiry in expiries:
            dte = (expiry - as_of_date).days
            if dte <= 0:
                continue

            T = dte / 365.0
            # Dividend-adjusted spot
            spot_adj = spot * math.exp(-self._dividend_yield * T)

            for strike in strikes:
                moneyness = strike / spot
                iv = self._estimate_iv(vix, dte, moneyness)

                # Generate both call and put
                for is_call in (True, False):
                    params = BSParams(
                        spot_price=spot_adj,
                        strike_price=strike,
                        risk_free_rate=risk_free_rate,
                        volatility=iv,
                        time_to_expiry=T,
                        is_call=is_call,
                    )

                    price = calc_bs_price(params)
                    if price is None or price <= 0:
                        continue

                    greeks_dict = calc_bs_greeks(params)

                    # Realistic bid-ask spread
                    spread = self._estimate_spread(price, moneyness, dte)
                    bid = max(0.01, price - spread / 2)
                    ask = price + spread / 2

                    opt_type = OptionType.CALL if is_call else OptionType.PUT
                    type_char = "C" if is_call else "P"
                    symbol = (
                        f"{underlying}_{expiry.strftime('%y%m%d')}_{type_char}_"
                        f"{strike:.0f}"
                    )

                    contract = OptionContract(
                        symbol=symbol,
                        underlying=underlying,
                        option_type=opt_type,
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

                    if is_call:
                        calls.append(quote)
                    else:
                        puts.append(quote)

            expiry_dates.append(expiry)

        return OptionChain(
            underlying=underlying,
            timestamp=timestamp,
            expiry_dates=sorted(expiry_dates),
            calls=calls,
            puts=puts,
            source="synthetic_bs",
        )

    # --- IV Estimation ---

    def _estimate_iv(self, vix: float, dte: int, moneyness: float) -> float:
        """Estimate implied volatility from VIX.

        Uses the same model as SyntheticLeapsProvider:
        1. Term structure decay: long-dated IV < short-dated VIX
        2. Moneyness skew: OTM puts (high moneyness) have higher IV
        """
        # Term structure: short-dated closer to VIX, long-dated decays
        term_factor = 1.0 - 0.15 * (1 - math.exp(-dte / 180))
        base_iv = vix * term_factor

        # Put skew: OTM puts (moneyness < 1) have higher IV
        # This captures the well-known volatility smile/smirk
        skew = 0.15 * (1.0 - moneyness)

        return max(0.05, base_iv * (1.0 + skew))

    # --- Helpers ---

    def _get_vix(self, as_of_date: date) -> float:
        """Get VIX as decimal (e.g., 0.20 for VIX=20)."""
        if as_of_date in self._vix_cache:
            return self._vix_cache[as_of_date]
        vix_data = self._base.get_macro_data("^VIX", as_of_date - timedelta(days=7), as_of_date)
        if vix_data:
            val = vix_data[-1].value / 100.0
            self._vix_cache[as_of_date] = val
            return val
        logger.warning(f"[SyntheticFallback] No VIX for {as_of_date}, using 0.20")
        self._vix_cache[as_of_date] = 0.20
        return 0.20

    def _get_risk_free_rate(self, as_of_date: date) -> float:
        """Get TNX as decimal rate (e.g., 0.045 for 4.5%)."""
        if as_of_date in self._tnx_cache:
            return self._tnx_cache[as_of_date]
        tnx_data = self._base.get_macro_data("^TNX", as_of_date - timedelta(days=7), as_of_date)
        if tnx_data:
            # TNX index = 10x yield: 45.73 → 4.573% → 0.04573
            val = tnx_data[-1].value / 1000.0
            self._tnx_cache[as_of_date] = val
            return val
        logger.warning(f"[SyntheticFallback] No TNX for {as_of_date}, using 0.04")
        self._tnx_cache[as_of_date] = 0.04
        return 0.04

    def _generate_expiries(
        self, as_of_date: date, expiry_start: date, expiry_end: date
    ) -> list[date]:
        """Generate weekly (first 3 months) + monthly (beyond) expiry dates.

        Weekly expiries are Fridays within the first ~90 days.
        Monthly expiries are 3rd Fridays beyond 90 days.
        """
        expiries = []
        three_months = as_of_date + timedelta(days=90)

        # Weekly expiries (Fridays) for first 90 days
        d = expiry_start
        while d <= min(expiry_end, three_months):
            # Find next Friday
            days_until_friday = (4 - d.weekday()) % 7
            friday = d + timedelta(days=days_until_friday)
            if expiry_start <= friday <= expiry_end and friday > as_of_date:
                expiries.append(friday)
            d = friday + timedelta(days=1)

        # Monthly expiries (3rd Friday) beyond 90 days
        current = date(three_months.year, three_months.month, 1)
        while current <= expiry_end:
            third_fri = self._third_friday(current.year, current.month)
            if three_months < third_fri <= expiry_end and third_fri > as_of_date:
                if third_fri not in expiries:  # avoid duplicates near boundary
                    expiries.append(third_fri)
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        return sorted(expiries)

    @staticmethod
    def _third_friday(year: int, month: int) -> date:
        """3rd Friday of a month."""
        first_day = date(year, month, 1)
        first_friday_offset = (4 - first_day.weekday()) % 7
        first_friday = first_day + timedelta(days=first_friday_offset)
        return first_friday + timedelta(days=14)

    def _generate_strike_grid(self, spot: float) -> list[float]:
        """Generate strike prices around spot.

        Covers 0.75x to 1.20x spot at standard increments:
        - spot < 50:  $1 increments
        - 50-200:     $2.5 increments
        - 200+:       $5 increments
        """
        if spot < 50:
            increment = 1.0
        elif spot < 200:
            increment = 2.5
        else:
            increment = 5.0

        lo = math.floor(spot * 0.75 / increment) * increment
        hi = math.ceil(spot * 1.20 / increment) * increment

        strikes = []
        s = lo
        while s <= hi:
            if s > 0:
                strikes.append(s)
            s = round(s + increment, 2)

        return strikes

    def _estimate_spread(self, price: float, moneyness: float, dte: int) -> float:
        """Estimate bid-ask spread for synthetic quote."""
        base_pct = 0.02
        if moneyness > 1.05 or moneyness < 0.95:  # OTM
            base_pct = 0.04
        elif 0.95 <= moneyness <= 1.05:  # ATM
            base_pct = 0.015

        # Longer dated = wider spread
        dte_factor = 1.0 + 0.2 * min(dte / 365, 1.0)

        spread = price * base_pct * dte_factor
        return max(0.05, spread)

    @property
    def synthetic_usage_summary(self) -> dict:
        """Summary of synthetic data usage for logging/reporting."""
        return {
            "total_synthetic_queries": len(self._synthetic_dates),
            "symbols_with_synthetic": sorted(
                set(s for s, _ in self._synthetic_dates)
            ),
        }
