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

import logging
from datetime import date, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def demo_yahoo_provider():
    """Demonstrate Yahoo Finance provider usage."""
    from src.data.providers.yahoo_provider import YahooProvider
    from src.data.models.stock import KlineType

    logger.info("=" * 60)
    logger.info("Yahoo Finance Provider Demo")
    logger.info("=" * 60)

    provider = YahooProvider()

    # 1. Get stock quote
    logger.info("\n1. Getting stock quote for AAPL...")
    quote = provider.get_stock_quote("AAPL")
    if quote:
        logger.info(f"   Symbol: {quote.symbol}")
        logger.info(f"   Price: ${quote.close:.2f}")
        logger.info(f"   Volume: {quote.volume:,}")
        logger.info(f"   Change: {quote.change_percent:.2f}%")
        logger.info(f"   Source: {quote.source}")

    # 2. Get historical K-line data
    logger.info("\n2. Getting 30-day historical data for AAPL...")
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    klines = provider.get_history_kline("AAPL", KlineType.DAY, start_date, end_date)
    logger.info(f"   Retrieved {len(klines)} daily bars")
    if klines:
        latest = klines[-1]
        logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")

    # 3. Get fundamental data
    logger.info("\n3. Getting fundamental data for AAPL...")
    fundamental = provider.get_fundamental("AAPL")
    if fundamental:
        logger.info(f"   Market Cap: ${fundamental.market_cap:,.0f}")
        logger.info(f"   P/E Ratio: {fundamental.pe_ratio:.2f}")
        logger.info(f"   EPS: ${fundamental.eps:.2f}")
        logger.info(f"   Dividend Yield: {(fundamental.dividend_yield or 0) * 100:.2f}%")

    # 4. Get macro data (VIX)
    logger.info("\n4. Getting VIX data for last 30 days...")
    vix_data = provider.get_macro_data("^VIX", start_date, end_date)
    logger.info(f"   Retrieved {len(vix_data)} data points")
    if vix_data:
        latest_vix = vix_data[-1]
        logger.info(f"   Latest VIX: {latest_vix.value:.2f}")

    # 5. Get option chain
    logger.info("\n5. Getting option chain for AAPL...")
    chain = provider.get_option_chain(
        "AAPL",
        expiry_start=date.today(),
        expiry_end=date.today() + timedelta(days=45),
    )
    if chain:
        logger.info(f"   Expiry dates: {len(chain.expiry_dates)}")
        logger.info(f"   Calls: {len(chain.calls)}")
        logger.info(f"   Puts: {len(chain.puts)}")
        if chain.expiry_dates:
            logger.info(f"   First expiry: {chain.expiry_dates[0]}")
        # Show sample option quote
        if chain.calls:
            sample_call = chain.calls[0]
            logger.info(f"   Sample Call: {sample_call.contract.underlying} "
                       f"{sample_call.contract.expiry_date} "
                       f"${sample_call.contract.strike_price} C "
                       f"Last: ${sample_call.last_price:.2f}")

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

            # 3. Get option chain
            logger.info("\n3. Getting option chain for AAPL...")
            chain = provider.get_option_chain(
                "AAPL",
                expiry_start=date.today(),
                expiry_end=date.today() + timedelta(days=30),
            )
            if chain:
                logger.info(f"   Expiry dates: {len(chain.expiry_dates)}")
                logger.info(f"   Calls: {len(chain.calls)}")
                logger.info(f"   Puts: {len(chain.puts)}")
                if chain.expiry_dates:
                    logger.info(f"   Expiries: {chain.expiry_dates}")
                # Show sample option with Greeks if available
                if chain.calls:
                    sample = chain.calls[0]
                    logger.info(f"   Sample Call: {sample.contract.underlying} "
                               f"{sample.contract.expiry_date} "
                               f"${sample.contract.strike_price} C")
                    if sample.greeks:
                        g = sample.greeks
                        greeks_str = []
                        if g.delta is not None:
                            greeks_str.append(f"Delta={g.delta:.4f}")
                        if g.gamma is not None:
                            greeks_str.append(f"Gamma={g.gamma:.4f}")
                        if g.theta is not None:
                            greeks_str.append(f"Theta={g.theta:.4f}")
                        if g.vega is not None:
                            greeks_str.append(f"Vega={g.vega:.4f}")
                        if greeks_str:
                            logger.info(f"   Greeks: {' '.join(greeks_str)}")

            # 4. Get option quote for specific contract
            logger.info("\n4. Getting specific option quote...")
            if chain and chain.calls:
                # Use first available call contract
                first_call = chain.calls[0]
                expiry = first_call.contract.expiry_date
                strike = first_call.contract.strike_price
                # Format: AAPL20241220C00150000
                opt_symbol = f"AAPL{expiry.strftime('%Y%m%d')}C{int(strike * 1000):08d}"
                logger.info(f"   Requesting quote for: {opt_symbol}")
                opt_quote = provider.get_option_quote(opt_symbol)
                if opt_quote:
                    if opt_quote.last_price:
                        logger.info(f"   Last: ${opt_quote.last_price:.2f}")
                    else:
                        logger.info("   Last: N/A")
                    if opt_quote.bid and opt_quote.ask:
                        logger.info(f"   Bid/Ask: ${opt_quote.bid:.2f} / ${opt_quote.ask:.2f}")
                    else:
                        logger.info("   Bid/Ask: N/A")
                    if opt_quote.iv:
                        logger.info(f"   IV: {opt_quote.iv:.2%}")
                    if opt_quote.greeks:
                        logger.info(f"   Greeks: Delta={opt_quote.greeks.delta:.4f}")

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


def demo_futu_provider():
    """Demonstrate Futu OpenD provider usage (requires OpenD running).

    Tests with 0700.HK - Tencent Holdings (HK stock).
    """
    from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE
    from src.data.models.stock import KlineType

    logger.info("=" * 60)
    logger.info("Futu OpenD Provider Demo (0700.HK - Tencent)")
    logger.info("=" * 60)

    if not FUTU_AVAILABLE:
        logger.warning("futu-api not installed. Skipping Futu demo.")
        logger.info("Install with: pip install futu-api")
        return

    try:
        with FutuProvider() as provider:
            symbol = "HK.00700"  # Tencent Holdings

            # 1. Get stock quote
            logger.info(f"\n1. Getting stock quote for {symbol} via Futu...")
            quote = provider.get_stock_quote(symbol)
            if quote:
                logger.info(f"   Symbol: {quote.symbol}")
                logger.info(f"   Price: HK${quote.close:.2f}")
                logger.info(f"   Volume: {quote.volume:,}")
                logger.info(f"   Change: {quote.change_percent:.2f}%")
                logger.info(f"   Source: {quote.source}")

            # 2. Get historical data
            logger.info(f"\n2. Getting 10-day historical data for {symbol}...")
            end_date = date.today()
            start_date = end_date - timedelta(days=10)
            klines = provider.get_history_kline(symbol, KlineType.DAY, start_date, end_date)
            logger.info(f"   Retrieved {len(klines)} daily bars")
            if klines:
                latest = klines[-1]
                logger.info(f"   Latest: {latest.timestamp.date()} O:{latest.open:.2f} H:{latest.high:.2f} L:{latest.low:.2f} C:{latest.close:.2f}")

            # 3. Get option chain
            logger.info(f"\n3. Getting option chain for {symbol}...")
            chain = provider.get_option_chain(
                symbol,
                expiry_start=date.today(),
                expiry_end=date.today() + timedelta(days=30),
            )
            if chain:
                logger.info(f"   Underlying: {chain.underlying}")
                logger.info(f"   Expiry dates: {len(chain.expiry_dates)}")
                logger.info(f"   Calls: {len(chain.calls)}")
                logger.info(f"   Puts: {len(chain.puts)}")
                if chain.expiry_dates:
                    logger.info(f"   First expiry: {chain.expiry_dates[0]}")
                # Show sample option quote
                if chain.calls:
                    sample = chain.calls[0]
                    sample_info = (f"   Sample Call: {sample.contract.underlying} "
                                  f"{sample.contract.expiry_date} "
                                  f"HK${sample.contract.strike_price} C")
                    if sample.last_price:
                        sample_info += f" Last: HK${sample.last_price:.2f}"
                    logger.info(sample_info)
                    if sample.greeks and sample.greeks.delta is not None:
                        greeks_info = f"   Greeks: Delta={sample.greeks.delta:.4f}"
                        if sample.iv:
                            greeks_info += f" IV={sample.iv:.2%}"
                        logger.info(greeks_info)

            logger.info("\nFutu demo completed!")

    except Exception as e:
        logger.error(f"Futu demo failed: {e}")
        logger.info("\nTo use Futu provider:")
        logger.info("  1. Download and install Futu OpenD")
        logger.info("  2. Start OpenD and login with your Futu account")
        logger.info("  3. Default connection: 127.0.0.1:11111")
        logger.info("\nNote: Futu account must have HK market permissions.")


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
