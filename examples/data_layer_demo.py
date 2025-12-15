#!/usr/bin/env python
"""Data Layer Demo - demonstrates usage of the data layer components.

This script shows how to:
1. Fetch stock quotes from different providers (Yahoo, IBKR, Futu)
2. Get historical K-line data
3. Retrieve option chain and option quotes
4. Get fundamental and macro data
5. Export data to QuantConnect-compatible CSV format

Usage:
    python examples/data_layer_demo.py              # Run all available demos
    python examples/data_layer_demo.py --yahoo      # Yahoo Finance only
    python examples/data_layer_demo.py --ibkr       # IBKR TWS only (requires TWS running)
    python examples/data_layer_demo.py --futu       # Futu OpenD only (requires OpenD running)

Note:
    - IBKR demo requires TWS or IB Gateway running locally
    - Futu demo requires OpenD gateway running locally
"""

import codecs
import logging
import sys
from datetime import date, timedelta
from pathlib import Path


class UnicodeDecodeFormatter(logging.Formatter):
    """Custom formatter that decodes Unicode escape sequences in log messages.

    Only decodes strings that contain \\uXXXX patterns (from IBKR API),
    leaves properly encoded UTF-8 strings (from Futu API) unchanged.
    """

    def format(self, record):
        # Only decode if string contains \uXXXX escape patterns
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            # Check if string contains unicode escape sequences like \u5e02
            if '\\u' in record.msg:
                try:
                    # Decode unicode_escape to properly display Chinese characters
                    record.msg = codecs.decode(record.msg, 'unicode_escape')
                except (UnicodeDecodeError, ValueError):
                    # If decoding fails, keep original message
                    pass
        return super().format(record)


# Configure logging with custom formatter for Unicode support
handler = logging.StreamHandler(stream=sys.stdout)
handler.setFormatter(UnicodeDecodeFormatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))
logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)
logger = logging.getLogger(__name__)

# Enable DEBUG for providers to see raw data
logging.getLogger("src.data.providers.ibkr_provider").setLevel(logging.DEBUG)
logging.getLogger("src.data.providers.futu_provider").setLevel(logging.DEBUG)
logging.getLogger("src.data.providers.yahoo_provider").setLevel(logging.DEBUG)


def demo_yahoo_provider():
    """Demonstrate Yahoo Finance provider usage.

    Tests with:
    - 0700.HK - Tencent Holdings (HK stock)
    - AAPL - Apple Inc (US stock)
    """
    from src.data.providers.yahoo_provider import YahooProvider
    from src.data.models.stock import KlineType

    logger.info("=" * 60)
    logger.info("Yahoo Finance Provider Demo")
    logger.info("=" * 60)

    provider = YahooProvider()
    end_date = date.today()
    start_date = end_date - timedelta(days=10)

    # Store for export demo
    klines, fundamental, chain = None, None, None

    # ============================================================
    # Part A: Hong Kong Market - Tencent (0700.HK)
    # ============================================================
    logger.info("\n" + "=" * 40)
    logger.info("Part A: Hong Kong Market - Tencent (0700.HK)")
    logger.info("=" * 40)

    hk_symbol = "0700.HK"

    # A1. Get stock quote
    logger.info(f"\nA1. Getting stock quote for {hk_symbol}...")
    hk_quote = provider.get_stock_quote(hk_symbol)
    if hk_quote:
        logger.info(f"   Symbol: {hk_quote.symbol}")
        logger.info(f"   Price: HK${hk_quote.close:.2f}" if hk_quote.close else "   Price: N/A")
        logger.info(f"   Volume: {hk_quote.volume:,}" if hk_quote.volume else "   Volume: N/A")
        if hk_quote.change_percent is not None:
            logger.info(f"   Change: {hk_quote.change_percent:.2f}%")
        logger.info(f"   Source: {hk_quote.source}")
    else:
        logger.warning(f"   No quote available for {hk_symbol}")

    # A2. Get historical data
    logger.info(f"\nA2. Getting 10-day historical data for {hk_symbol}...")
    hk_klines = provider.get_history_kline(hk_symbol, KlineType.DAY, start_date, end_date)
    logger.info(f"   Retrieved {len(hk_klines)} daily bars")
    if hk_klines:
        latest = hk_klines[-1]
        logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")

    # A3. Get fundamental data for HK stock
    logger.info(f"\nA3. Getting fundamental data for {hk_symbol}...")
    hk_fundamental = provider.get_fundamental(hk_symbol)
    if hk_fundamental:
        logger.info("   --- Valuation ---")
        if hk_fundamental.market_cap:
            logger.info(f"   Market Cap: HK${hk_fundamental.market_cap:,.0f}")
        if hk_fundamental.pe_ratio:
            logger.info(f"   P/E Ratio: {hk_fundamental.pe_ratio:.2f}")
        if hk_fundamental.eps:
            logger.info(f"   EPS: HK${hk_fundamental.eps:.2f}")
        if hk_fundamental.dividend_yield:
            # Note: yfinance returns dividend_yield as a percentage value
            logger.info(f"   Dividend Yield: {hk_fundamental.dividend_yield:.2f}%")
        logger.info("   --- Growth ---")
        if hk_fundamental.revenue_growth is not None:
            logger.info(f"   Revenue Growth: {hk_fundamental.revenue_growth * 100:.2f}%")
        if hk_fundamental.earnings_growth is not None:
            logger.info(f"   Earnings Growth: {hk_fundamental.earnings_growth * 100:.2f}%")
        logger.info("   --- Analyst Ratings ---")
        if hk_fundamental.recommendation:
            logger.info(f"   Recommendation: {hk_fundamental.recommendation.upper()}")
        if hk_fundamental.recommendation_mean:
            rating_map = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Underperform", 5: "Sell"}
            rating_label = rating_map.get(round(hk_fundamental.recommendation_mean), "N/A")
            logger.info(f"   Recommendation Mean: {hk_fundamental.recommendation_mean:.2f} ({rating_label})")
        if hk_fundamental.analyst_count:
            logger.info(f"   Analyst Count: {hk_fundamental.analyst_count}")
        if hk_fundamental.target_price:
            logger.info(f"   Target Price: HK${hk_fundamental.target_price:.2f}")
    else:
        logger.warning(f"   No fundamental data available for {hk_symbol}")

    # A4. Get option chain (Yahoo may not have HK options)
    logger.info(f"\nA4. Getting option chain for {hk_symbol}...")
    hk_chain = provider.get_option_chain(
        hk_symbol,
        expiry_start=date.today(),
        expiry_end=date.today() + timedelta(days=45),
    )
    if hk_chain and (hk_chain.calls or hk_chain.puts):
        logger.info(f"   Underlying: {hk_chain.underlying}")
        logger.info(f"   Expiry dates: {len(hk_chain.expiry_dates)}")
        logger.info(f"   Calls: {len(hk_chain.calls)}, Puts: {len(hk_chain.puts)}")
        if hk_chain.expiry_dates:
            logger.info(f"   Expiries: {hk_chain.expiry_dates[:3]}...")

        # A5. Display option quotes (Yahoo already includes quote data in option chain)
        if hk_chain.calls:
            logger.info(f"\nA5. Option quotes for {hk_symbol}...")
            # Select contracts near ATM
            if hk_quote and hk_quote.close:
                underlying_price = hk_quote.close
            else:
                strikes = [c.contract.strike_price for c in hk_chain.calls]
                underlying_price = (min(strikes) + max(strikes)) / 2

            all_calls = sorted(hk_chain.calls, key=lambda c: abs(c.contract.strike_price - underlying_price))
            selected_quotes = all_calls[:5]
            logger.info(f"   Selecting {len(selected_quotes)} contracts near ATM (underlying=HK${underlying_price:.2f})")
            _display_option_quotes(selected_quotes, currency="HK$")
    else:
        logger.info("   No option chain available for HK market (Yahoo may not support HK options)")

    # ============================================================
    # Part B: US Market - Apple (AAPL)
    # ============================================================
    logger.info("\n" + "=" * 40)
    logger.info("Part B: US Market - Apple (AAPL)")
    logger.info("=" * 40)

    us_symbol = "AAPL"

    # B1. Get stock quote
    logger.info(f"\nB1. Getting stock quote for {us_symbol}...")
    us_quote = provider.get_stock_quote(us_symbol)
    if us_quote:
        logger.info(f"   Symbol: {us_quote.symbol}")
        logger.info(f"   Price: ${us_quote.close:.2f}" if us_quote.close else "   Price: N/A")
        logger.info(f"   Volume: {us_quote.volume:,}" if us_quote.volume else "   Volume: N/A")
        if us_quote.change_percent is not None:
            logger.info(f"   Change: {us_quote.change_percent:.2f}%")
        logger.info(f"   Source: {us_quote.source}")
    else:
        logger.warning(f"   No quote available for {us_symbol}")

    # B2. Get historical data
    logger.info(f"\nB2. Getting 10-day historical data for {us_symbol}...")
    klines = provider.get_history_kline(us_symbol, KlineType.DAY, start_date, end_date)
    logger.info(f"   Retrieved {len(klines)} daily bars")
    if klines:
        latest = klines[-1]
        logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")

    # B3. Get fundamental data
    logger.info(f"\nB3. Getting fundamental data for {us_symbol}...")
    fundamental = provider.get_fundamental(us_symbol)
    if fundamental:
        logger.info("   --- Valuation ---")
        if fundamental.market_cap:
            logger.info(f"   Market Cap: ${fundamental.market_cap:,.0f}")
        if fundamental.pe_ratio:
            logger.info(f"   P/E Ratio: {fundamental.pe_ratio:.2f}")
        if fundamental.eps:
            logger.info(f"   EPS: ${fundamental.eps:.2f}")
        if fundamental.dividend_yield:
            # Note: yfinance returns dividend_yield as a percentage value (e.g., 0.37 means 0.37%)
            logger.info(f"   Dividend Yield: {fundamental.dividend_yield:.2f}%")
        logger.info("   --- Growth ---")
        if fundamental.revenue_growth is not None:
            logger.info(f"   Revenue Growth: {fundamental.revenue_growth * 100:.2f}%")
        if fundamental.earnings_growth is not None:
            logger.info(f"   Earnings Growth: {fundamental.earnings_growth * 100:.2f}%")
        logger.info("   --- Analyst Ratings ---")
        if fundamental.recommendation:
            logger.info(f"   Recommendation: {fundamental.recommendation.upper()}")
        if fundamental.recommendation_mean:
            # 1=Strong Buy, 2=Buy, 3=Hold, 4=Underperform, 5=Sell
            rating_map = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Underperform", 5: "Sell"}
            rating_label = rating_map.get(round(fundamental.recommendation_mean), "N/A")
            logger.info(f"   Recommendation Mean: {fundamental.recommendation_mean:.2f} ({rating_label})")
        if fundamental.analyst_count:
            logger.info(f"   Analyst Count: {fundamental.analyst_count}")
        if fundamental.target_price:
            logger.info(f"   Target Price: ${fundamental.target_price:.2f}")

    # B4. Get option chain
    # Note: Yahoo Finance option data has limitations:
    # - Bid/Ask: Often 0 outside US market hours (9:30 AM - 4:00 PM ET)
    # - Open Interest: May be 0 for near-expiry options
    # - IV: Cannot be calculated without bid/ask spread
    # - Greeks: Not provided (always None)
    logger.info(f"\nB4. Getting option chain for {us_symbol}...")
    logger.info("   (Note: Bid/Ask may be 0 outside US market hours)")
    chain = provider.get_option_chain(
        us_symbol,
        expiry_start=date.today(),
        expiry_end=date.today() + timedelta(days=45),
    )
    if chain:
        logger.info(f"   Underlying: {chain.underlying}")
        logger.info(f"   Expiry dates: {len(chain.expiry_dates)}")
        logger.info(f"   Calls: {len(chain.calls)}, Puts: {len(chain.puts)}")
        if chain.expiry_dates:
            logger.info(f"   Expiries: {chain.expiry_dates[:3]}...")

        # B5. Display option quotes (Yahoo already includes quote data in option chain)
        if chain.calls:
            logger.info(f"\nB5. Option quotes for {us_symbol}...")
            # Select contracts near ATM
            if us_quote and us_quote.close:
                underlying_price = us_quote.close
            else:
                strikes = [c.contract.strike_price for c in chain.calls]
                underlying_price = (min(strikes) + max(strikes)) / 2

            all_calls = sorted(chain.calls, key=lambda c: abs(c.contract.strike_price - underlying_price))
            selected_quotes = all_calls[:5]
            logger.info(f"   Selecting {len(selected_quotes)} contracts near ATM (underlying=${underlying_price:.2f})")
            _display_option_quotes(selected_quotes, currency="$")
    else:
        logger.warning("   No option chain available")

    # ============================================================
    # Part C: Macro Data - VIX and Put/Call Ratio
    # ============================================================
    logger.info("\n" + "=" * 40)
    logger.info("Part C: Macro Data - VIX and Put/Call Ratio")
    logger.info("=" * 40)

    # C1. Get VIX data
    logger.info("\nC1. Getting VIX data (last 10 days)...")
    vix_data = provider.get_macro_data("^VIX", start_date, end_date)
    logger.info(f"   Retrieved {len(vix_data)} data points")
    if vix_data:
        latest_vix = vix_data[-1]
        logger.info(f"   Latest VIX: {latest_vix.value:.2f}")
        # VIX interpretation
        if latest_vix.value < 15:
            sentiment = "Low volatility (complacency)"
        elif latest_vix.value < 20:
            sentiment = "Normal volatility"
        elif latest_vix.value < 30:
            sentiment = "Elevated volatility (caution)"
        else:
            sentiment = "High volatility (fear)"
        logger.info(f"   Interpretation: {sentiment}")

    # C2. Calculate Put/Call Ratio (from SPY options)
    logger.info("\nC2. Calculating Put/Call Ratio (from SPY options)...")
    pcr = provider.get_put_call_ratio("SPY")
    if pcr is not None:
        logger.info(f"   SPY Put/Call Ratio: {pcr:.3f}")
        # PCR interpretation
        if pcr < 0.7:
            sentiment = "Bullish sentiment (more calls than puts)"
        elif pcr < 1.0:
            sentiment = "Neutral sentiment"
        else:
            sentiment = "Bearish sentiment (more puts than calls)"
        logger.info(f"   Interpretation: {sentiment}")
    else:
        logger.warning("   Could not calculate Put/Call Ratio")

    # C3. Get 10-Year Treasury Yield
    logger.info("\nC3. Getting 10-Year Treasury Yield (last 10 days)...")
    tnx_data = provider.get_macro_data("^TNX", start_date, end_date)
    logger.info(f"   Retrieved {len(tnx_data)} data points")
    if tnx_data:
        latest_tnx = tnx_data[-1]
        logger.info(f"   Latest 10Y Yield: {latest_tnx.value:.2f}%")

    logger.info("\nYahoo Finance demo completed!")
    return klines, fundamental, chain


def demo_ibkr_provider():
    """Demonstrate IBKR provider usage (requires TWS/Gateway running).

    Tests with AAPL - Apple Inc (US stock).
    """
    from src.data.providers.ibkr_provider import IBKRProvider, IBKR_AVAILABLE
    from src.data.models.stock import KlineType

    logger.info("=" * 60)
    logger.info("IBKR TWS Provider Demo (AAPL - US Market)")
    logger.info("=" * 60)

    if not IBKR_AVAILABLE:
        logger.warning("ib_async not installed. Skipping IBKR demo.")
        logger.info("Install with: pip install ib_async")
        return

    try:
        with IBKRProvider() as provider:
            # 1. Get stock quote
            logger.info("\n1. Getting stock quote for AAPL via IBKR...")
            quote = provider.get_stock_quote("AAPL")
            if quote:
                logger.info(f"   Symbol: {quote.symbol}")
                price = quote.close
                if price and not (price != price):  # Check for NaN
                    logger.info(f"   Price: ${price:.2f}")
                else:
                    logger.info("   Price: N/A (market data subscription required)")
                # bid/ask stored as private attributes
                bid = getattr(quote, "_bid", None)
                ask = getattr(quote, "_ask", None)
                if bid and ask and not (bid != bid):  # Check for NaN
                    logger.info(f"   Bid/Ask: ${bid:.2f} / ${ask:.2f}")
                logger.info(f"   Source: {quote.source}")

            # 2. Get historical data
            logger.info("\n2. Getting 10-day historical data for AAPL...")
            end_date = date.today()
            start_date = end_date - timedelta(days=10)
            klines = provider.get_history_kline("AAPL", KlineType.DAY, start_date, end_date)
            logger.info(f"   Retrieved {len(klines)} daily bars")
            if klines:
                latest = klines[-1]
                logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")

            # 3. Get option chain (structure only, no market data)
            logger.info("\n3. Getting option chain structure for AAPL...")
            logger.info("   Filters: 15-45 days to expiry (default), ±20% strike range (default)")
            chain = provider.get_option_chain("AAPL")  # Using defaults
            if chain:
                logger.info(f"   Expiry dates: {len(chain.expiry_dates)}")
                logger.info(f"   Calls: {len(chain.calls)}")
                logger.info(f"   Puts: {len(chain.puts)}")
                if chain.expiry_dates:
                    logger.info(f"   Expiries: {chain.expiry_dates}")
                # Show sample contracts (no market data yet)
                if chain.calls:
                    sample = chain.calls[0]
                    logger.info(f"   Sample Call: {sample.contract.symbol} "
                               f"(strike=${sample.contract.strike_price}, "
                               f"expiry={sample.contract.expiry_date})")

            # 4. Fetch market data for selected contracts using batch API
            logger.info("\n4. Fetching market data for option contracts...")
            if chain and chain.calls:
                # Get underlying price from quote, or use middle of strike range
                if quote and quote.close:
                    underlying_price = quote.close
                else:
                    strikes = [c.contract.strike_price for c in chain.calls]
                    underlying_price = (min(strikes) + max(strikes)) / 2

                # Select contracts around ATM for better liquidity
                # Sort by strike distance from underlying price
                all_calls = sorted(chain.calls, key=lambda c: abs(c.contract.strike_price - underlying_price))
                # Take 10 contracts nearest to ATM
                selected_contracts = [c.contract for c in all_calls[:10]]
                logger.info(f"   Selecting {len(selected_contracts)} contracts near ATM (underlying=${underlying_price:.2f})...")

                quotes = provider.get_option_quotes_batch(selected_contracts)

                logger.info(f"   Received {len(quotes)} quotes")

                # Count contracts with different types of data
                with_price = sum(1 for q in quotes if q.last_price or q.bid or q.ask)
                with_greeks = sum(1 for q in quotes if q.greeks and q.greeks.delta is not None)
                logger.info(f"   Summary: {with_price} with price data, {with_greeks} with Greeks")

                for q in quotes:
                    # Build detail parts - price info
                    price_parts = []
                    if q.last_price is not None:
                        price_parts.append(f"Last=${q.last_price:.2f}")
                    if q.bid is not None and q.ask is not None:
                        price_parts.append(f"Bid/Ask=${q.bid:.2f}/${q.ask:.2f}")
                    elif q.bid is not None:
                        price_parts.append(f"Bid=${q.bid:.2f}")
                    elif q.ask is not None:
                        price_parts.append(f"Ask=${q.ask:.2f}")
                    if q.volume is not None and q.volume > 0:
                        price_parts.append(f"Vol={q.volume}")

                    # Greeks info
                    greeks_parts = []
                    if q.iv is not None:
                        greeks_parts.append(f"IV={q.iv:.2%}")
                    if q.greeks:
                        if q.greeks.delta is not None:
                            greeks_parts.append(f"Δ={q.greeks.delta:.3f}")
                        if q.greeks.gamma is not None:
                            greeks_parts.append(f"Γ={q.greeks.gamma:.4f}")
                        if q.greeks.theta is not None:
                            greeks_parts.append(f"Θ={q.greeks.theta:.3f}")
                        if q.greeks.vega is not None:
                            greeks_parts.append(f"V={q.greeks.vega:.3f}")

                    # Build output
                    all_parts = price_parts + greeks_parts
                    if all_parts:
                        logger.info(f"   {q.contract.symbol}: {', '.join(all_parts)}")
                    else:
                        logger.info(f"   {q.contract.symbol}: (no data - illiquid or not calculated)")

            logger.info("\nIBKR demo completed!")

    except Exception as e:
        logger.error(f"IBKR demo failed: {e}")
        logger.info("\nTo use IBKR provider:")
        logger.info("  1. Start TWS or IB Gateway")
        logger.info("  2. Enable API connections in settings (API -> Settings)")
        logger.info("  3. Check 'Enable ActiveX and Socket Clients'")
        logger.info("  4. Use port 7497 (paper) or 7496 (live)")
        logger.info("\nNote: Real-time market data requires subscription.")
        logger.info("      Historical data is available without subscription.")


def _display_option_quotes(quotes: list, currency: str = "$", provider: str = ""):
    """Helper to display option quotes with contract details.

    Note on Yahoo Finance limitations:
    - Bid/Ask: Often 0 outside market hours (9:30 AM - 4:00 PM ET)
    - Open Interest: May be 0 for near-expiry options (positions closed)
    - Implied Volatility: Cannot be calculated without bid/ask, shows near-zero
    - Greeks: Not provided by Yahoo Finance (always None)
    """
    if not quotes:
        logger.info("   No quotes available")
        return

    # Count contracts with different types of data
    with_price = sum(1 for q in quotes if q.last_price or q.bid or q.ask)
    with_greeks = sum(1 for q in quotes if q.greeks and q.greeks.delta is not None)
    with_oi = sum(1 for q in quotes if q.open_interest and q.open_interest > 0)
    with_iv = sum(1 for q in quotes if q.iv and q.iv > 0.01)  # IV > 1% is meaningful

    logger.info(f"   Summary: {with_price} with price, {with_oi} with OI, {with_iv} with IV, {with_greeks} with Greeks")

    for q in quotes:
        # Contract details
        contract_info = (f"{q.contract.symbol} "
                        f"({q.contract.option_type.value.upper()} "
                        f"strike={currency}{q.contract.strike_price:.2f} "
                        f"exp={q.contract.expiry_date})")

        # Price info
        price_parts = []
        if q.last_price is not None and q.last_price > 0:
            price_parts.append(f"Last={currency}{q.last_price:.2f}")
        # Only show bid/ask if they have meaningful values
        if q.bid is not None and q.ask is not None:
            if q.bid > 0 or q.ask > 0:
                price_parts.append(f"Bid/Ask={currency}{q.bid:.2f}/{currency}{q.ask:.2f}")
            else:
                price_parts.append("Bid/Ask=N/A")  # Zero during non-trading hours
        if q.volume is not None and q.volume > 0:
            price_parts.append(f"Vol={int(q.volume)}")
        if q.open_interest is not None:
            if q.open_interest > 0:
                price_parts.append(f"OI={q.open_interest}")
            else:
                price_parts.append("OI=N/A")

        # Greeks info
        greeks_parts = []
        if q.iv is not None:
            # IV near zero (< 1%) is usually invalid/unavailable
            if q.iv > 0.01:
                greeks_parts.append(f"IV={q.iv:.2%}")
            else:
                greeks_parts.append("IV=N/A")
        if q.greeks:
            if q.greeks.delta is not None:
                greeks_parts.append(f"Δ={q.greeks.delta:.3f}")
            if q.greeks.gamma is not None:
                greeks_parts.append(f"Γ={q.greeks.gamma:.4f}")
            if q.greeks.theta is not None:
                greeks_parts.append(f"Θ={q.greeks.theta:.3f}")
            if q.greeks.vega is not None:
                greeks_parts.append(f"V={q.greeks.vega:.3f}")

        # Build output
        all_parts = price_parts + greeks_parts
        if all_parts:
            logger.info(f"   {contract_info}: {', '.join(all_parts)}")
        else:
            logger.info(f"   {contract_info}: (no market data)")


def demo_futu_provider():
    """Demonstrate Futu OpenD provider usage (requires OpenD running).

    Tests with:
    - HK.00700 - Tencent Holdings (HK stock)
    - US.AAPL - Apple Inc (US stock)
    """
    from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE
    from src.data.models.stock import KlineType

    logger.info("=" * 60)
    logger.info("Futu OpenD Provider Demo")
    logger.info("=" * 60)

    if not FUTU_AVAILABLE:
        logger.warning("futu-api not installed. Skipping Futu demo.")
        logger.info("Install with: pip install futu-api")
        return

    try:
        with FutuProvider() as provider:
            # ============================================================
            # Part A: Hong Kong Market - Tencent (HK.00700)
            # ============================================================
            logger.info("\n" + "=" * 40)
            logger.info("Part A: Hong Kong Market - Tencent (HK.00700)")
            logger.info("=" * 40)

            hk_symbol = "HK.00700"

            # A1. Get stock quote
            logger.info(f"\nA1. Getting stock quote for {hk_symbol}...")
            quote = provider.get_stock_quote(hk_symbol)
            if quote:
                logger.info(f"   Symbol: {quote.symbol}")
                logger.info(f"   Price: HK${quote.close:.2f}" if quote.close else "   Price: N/A")
                logger.info(f"   Volume: {quote.volume:,}" if quote.volume else "   Volume: N/A")
                if quote.change_percent is not None:
                    logger.info(f"   Change: {quote.change_percent:.2f}%")
                logger.info(f"   Source: {quote.source}")

            # A2. Get historical data
            logger.info(f"\nA2. Getting 10-day historical data for {hk_symbol}...")
            end_date = date.today()
            start_date = end_date - timedelta(days=10)
            klines = provider.get_history_kline(hk_symbol, KlineType.DAY, start_date, end_date)
            logger.info(f"   Retrieved {len(klines)} daily bars")
            if klines:
                latest = klines[-1]
                logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")

            # A3. Get option chain (Futu限制: 时间跨度不能超过30天)
            logger.info(f"\nA3. Getting option chain for {hk_symbol}...")
            chain = provider.get_option_chain(
                hk_symbol,
                expiry_start=date.today(),
                expiry_end=date.today() + timedelta(days=30),
            )
            if chain:
                logger.info(f"   Underlying: {chain.underlying}")
                logger.info(f"   Expiry dates: {len(chain.expiry_dates)}")
                logger.info(f"   Calls: {len(chain.calls)}, Puts: {len(chain.puts)}")
                if chain.expiry_dates:
                    logger.info(f"   Expiries: {chain.expiry_dates[:3]}...")

                # A4. Fetch market data for selected option contracts
                if chain.calls:
                    logger.info(f"\nA4. Fetching market data for HK option contracts...")
                    # Select contracts near ATM
                    if quote and quote.close:
                        underlying_price = quote.close
                    else:
                        strikes = [c.contract.strike_price for c in chain.calls]
                        underlying_price = (min(strikes) + max(strikes)) / 2

                    all_calls = sorted(chain.calls, key=lambda c: abs(c.contract.strike_price - underlying_price))
                    selected_contracts = [c.contract for c in all_calls[:5]]
                    logger.info(f"   Selecting {len(selected_contracts)} contracts near ATM (underlying=HK${underlying_price:.2f})")

                    quotes = provider.get_option_quotes_batch(selected_contracts)
                    _display_option_quotes(quotes, currency="HK$")
            else:
                logger.info("   No option chain available for HK market")

            # ============================================================
            # Part B: US Market - Apple (US.AAPL)
            # ============================================================
            logger.info("\n" + "=" * 40)
            logger.info("Part B: US Market - Apple (US.AAPL)")
            logger.info("=" * 40)

            us_symbol = "US.AAPL"
            us_quote = None

            # B1. Get stock quote (may fail without US market subscription)
            logger.info(f"\nB1. Getting stock quote for {us_symbol}...")
            try:
                us_quote = provider.get_stock_quote(us_symbol)
                if us_quote:
                    logger.info(f"   Symbol: {us_quote.symbol}")
                    logger.info(f"   Price: ${us_quote.close:.2f}" if us_quote.close else "   Price: N/A")
                    logger.info(f"   Volume: {us_quote.volume:,}" if us_quote.volume else "   Volume: N/A")
                    if us_quote.change_percent is not None:
                        logger.info(f"   Change: {us_quote.change_percent:.2f}%")
                    logger.info(f"   Source: {us_quote.source}")
                else:
                    logger.warning("   No stock quote available (skipping, will use strike range for ATM)")
            except Exception as e:
                logger.warning(f"   Stock quote failed: {e} (skipping)")

            # B2. Get historical data (may fail without US market subscription)
            logger.info(f"\nB2. Getting 10-day historical data for {us_symbol}...")
            try:
                us_klines = provider.get_history_kline(us_symbol, KlineType.DAY, start_date, end_date)
                logger.info(f"   Retrieved {len(us_klines)} daily bars")
                if us_klines:
                    latest = us_klines[-1]
                    logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")
            except Exception as e:
                logger.warning(f"   Historical data failed: {e} (skipping)")

            # B3. Get option chain (Futu限制: 时间跨度不能超过30天)
            # Note: Option chain API may work even without stock quote permission
            logger.info(f"\nB3. Getting option chain for {us_symbol}...")
            us_chain = provider.get_option_chain(
                us_symbol,
                expiry_start=date.today(),
                expiry_end=date.today() + timedelta(days=30),
            )
            if us_chain:
                logger.info(f"   Underlying: {us_chain.underlying}")
                logger.info(f"   Expiry dates: {len(us_chain.expiry_dates)}")
                logger.info(f"   Calls: {len(us_chain.calls)}, Puts: {len(us_chain.puts)}")
                if us_chain.expiry_dates:
                    logger.info(f"   Expiries: {us_chain.expiry_dates[:3]}...")

                # B4. Fetch market data for selected option contracts
                if us_chain.calls:
                    logger.info(f"\nB4. Fetching market data for US option contracts...")
                    # Select contracts near ATM - use strike range if no stock quote
                    strikes = [c.contract.strike_price for c in us_chain.calls]
                    if us_quote and us_quote.close:
                        underlying_price = us_quote.close
                    else:
                        # Estimate ATM from strike range (middle of range)
                        underlying_price = (min(strikes) + max(strikes)) / 2
                        logger.info(f"   (No stock quote, estimating ATM from strike range)")

                    all_calls = sorted(us_chain.calls, key=lambda c: abs(c.contract.strike_price - underlying_price))
                    selected_contracts = [c.contract for c in all_calls[:5]]
                    logger.info(f"   Selecting {len(selected_contracts)} contracts near ATM (est. underlying=${underlying_price:.2f})")

                    us_quotes = provider.get_option_quotes_batch(selected_contracts)
                    _display_option_quotes(us_quotes, currency="$")
            else:
                logger.info("   No option chain available (may need US options subscription)")

            logger.info("\nFutu demo completed!")

    except Exception as e:
        logger.error(f"Futu demo failed: {e}")
        import traceback
        traceback.print_exc()
        logger.info("\nTo use Futu provider:")
        logger.info("  1. Download and install Futu OpenD")
        logger.info("  2. Start OpenD and login with your Futu account")
        logger.info("  3. Default connection: 127.0.0.1:11111")
        logger.info("\nNote: Different markets require different subscriptions:")
        logger.info("  - HK market: Basic Futu account")
        logger.info("  - US market: US market data subscription")


def demo_csv_export(klines, fundamental, chain):
    """Demonstrate CSV export functionality."""
    from src.data.formatters.csv_exporter import CSVExporter

    logger.info("\n" + "=" * 60)
    logger.info("CSV Export Demo")
    logger.info("=" * 60)

    output_dir = Path("data/export")
    exporter = CSVExporter(output_dir=output_dir)

    # Export K-line data
    if klines:
        logger.info("\n1. Exporting K-line data...")
        kline_path = exporter.export_klines("AAPL", klines)
        logger.info(f"   Exported to: {kline_path}")

    # Export fundamental data
    if fundamental:
        logger.info("\n2. Exporting fundamental data...")
        fund_path = exporter.export_fundamentals("AAPL", [fundamental])
        logger.info(f"   Exported to: {fund_path}")

    # Export option chain
    if chain and (chain.calls or chain.puts):
        logger.info("\n3. Exporting option chain...")
        opt_path = exporter.export_option_chain("AAPL", chain)
        logger.info(f"   Exported to: {opt_path}")


def main():
    """Run demos based on command line arguments."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Data Layer Demo - Test different data providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/data_layer_demo.py              # Run all available demos
  python examples/data_layer_demo.py --yahoo      # Yahoo Finance only
  python examples/data_layer_demo.py --ibkr       # IBKR TWS only (AAPL)
  python examples/data_layer_demo.py --futu       # Futu OpenD only (0700.HK)
  python examples/data_layer_demo.py --ibkr --futu  # Both IBKR and Futu
        """
    )
    parser.add_argument(
        "--yahoo", action="store_true",
        help="Run Yahoo Finance demo (AAPL)"
    )
    parser.add_argument(
        "--ibkr", action="store_true",
        help="Run IBKR TWS demo - requires TWS/Gateway running (AAPL)"
    )
    parser.add_argument(
        "--futu", action="store_true",
        help="Run Futu OpenD demo - requires OpenD running (0700.HK Tencent)"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Run CSV export demo (requires --yahoo)"
    )
    args = parser.parse_args()

    # If no specific provider selected, run Yahoo by default
    run_all = not (args.yahoo or args.ibkr or args.futu)

    logger.info("Option Quant Trade System - Data Layer Demo")
    logger.info("=" * 60)

    klines, fundamental, chain = None, None, None

    try:
        # Yahoo Finance demo
        if args.yahoo or run_all:
            klines, fundamental, chain = demo_yahoo_provider()

        # IBKR demo
        if args.ibkr or run_all:
            demo_ibkr_provider()

        # Futu demo
        if args.futu or run_all:
            demo_futu_provider()

        # CSV export demo
        if args.export and klines:
            demo_csv_export(klines, fundamental, chain)

        logger.info("\n" + "=" * 60)
        logger.info("Demo completed!")

    except KeyboardInterrupt:
        logger.info("\nDemo interrupted by user.")
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    main()
