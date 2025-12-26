"""Test HK data availability across different providers.

Test symbols:
- 800125.HK: VHSI (Hang Seng Volatility Index)
- 800000.HK: HSI (Hang Seng Index)
- ^HSI: HSI via Yahoo Finance
- HSTECH.HK: Hang Seng TECH Index

Providers:
- Yahoo Finance
- IBKR (requires TWS/Gateway running)
- Futu (requires OpenD running)

Usage:
    python tests/debug_hk_data_sources.py
"""
import argparse
import json
import logging
import re
import sys


class UnicodeSafeFormatter(logging.Formatter):
    """Formatter that properly displays Unicode characters from escaped strings.

    The ib_async library sometimes logs error messages with Unicode escape sequences
    (e.g., \\u8bf7\\u6c42) instead of actual Unicode characters. This formatter
    decodes those escape sequences to display readable Chinese text.
    """

    # Pattern to match Unicode escape sequences like \u4e2d or \u0041
    _unicode_escape_pattern = re.compile(r"\\u([0-9a-fA-F]{4})")

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        # Check if the message contains Unicode escape sequences
        if "\\u" in message:
            try:
                # Replace each \uXXXX with the actual Unicode character
                message = self._unicode_escape_pattern.sub(
                    lambda m: chr(int(m.group(1), 16)), message
                )
            except (ValueError, OverflowError):
                pass  # Keep original if decoding fails
        return message


from datetime import date, timedelta


def test_yahoo_provider():
    """Test Yahoo Finance provider for HK symbols."""
    print("\n" + "=" * 60)
    print("YAHOO FINANCE PROVIDER")
    print("=" * 60)

    try:
        from src.data.providers.yahoo_provider import YahooProvider
        from src.data.models.stock import KlineType

        provider = YahooProvider()
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        # Symbols to test
        symbols = [
            ("800125.HK", "VHSI (Hang Seng Volatility Index)"),
            ("800000.HK", "HSI (Hang Seng Index) - alternative"),
            ("^HSI", "HSI (Yahoo standard)"),
            ("^VHSI", "VHSI (Yahoo caret format)"),
            ("HSTECH.HK", "Hang Seng TECH Index"),
            ("2800.HK", "Tracker Fund ETF"),
            ("3032.HK", "HSTECH ETF"),
        ]

        for symbol, desc in symbols:
            print(f"\n[{symbol}] {desc}")
            try:
                klines = provider.get_history_kline(symbol, KlineType.DAY, start_date, end_date)
                if klines:
                    latest = klines[-1]
                    print(f"    Status: OK")
                    print(f"    Latest Close: {latest.close}")
                    print(f"    Date: {latest.timestamp}")
                    print(f"    Data Points: {len(klines)}")
                else:
                    print(f"    Status: NO DATA (empty result)")
            except Exception as e:
                print(f"    Status: FAILED - {type(e).__name__}: {e}")

            try:
                pcr = provider.get_put_call_ratio(symbol)
                print(f"    Status: OK")
                print(f"    PCR: {pcr}")
            except Exception as e:
                print(f"    Status: FAILED - {type(e).__name__}: {e}")

    except ImportError as e:
        print(f"Yahoo provider not available: {e}")


def test_ibkr_provider():
    """Test IBKR provider for HK symbols."""
    print("\n" + "=" * 60)
    print("IBKR PROVIDER")
    print("=" * 60)

    try:
        from src.data.providers.ibkr_provider import IBKRProvider, IBKR_AVAILABLE
        from src.data.models.stock import KlineType

        if not IBKR_AVAILABLE:
            print("IBKR library (ib_insync) not installed.")
            return

        print("\nConnecting to IBKR...")

        # Use context manager pattern for proper connection
        with IBKRProvider() as provider:
            if not provider.is_available:
                print("IBKR not available. Please start TWS/IB Gateway.")
                return

            print("Connected!")

            end_date = date.today()
            start_date = end_date - timedelta(days=30)

            # Symbols to test
            symbols = [
                ("800125.HK", "VHSI Index"),
                ("800000.HK", "HSI Index"),
                ("HSI.HK", "HSI Index"),
                ("2800.HK", "Tracker Fund ETF"),
                ("3032.HK", "HSTECH ETF"),
            ]

            for symbol, desc in symbols:
                print(f"\n[{symbol}] {desc}")
                try:
                    klines = provider.get_history_kline(
                        symbol, KlineType.DAY, start_date, end_date
                    )
                    if klines:
                        latest = klines[-1]
                        print(f"    Status: OK")
                        print(f"    Latest Close: {latest.close}")
                        print(f"    Date: {latest.timestamp}")
                        print(f"    Data Points: {len(klines)}")
                    else:
                        print(f"    Status: NO DATA (empty result)")
                except Exception as e:
                    print(f"    Status: FAILED - {type(e).__name__}: {e}")

            # Test volatility data from 2800.HK
            for symbol, desc in symbols:
                print(f"\n[{symbol}, {desc}] Stock Volatility (IV/HV/PCR)")

                try:
                    vol = provider.get_stock_volatility(symbol)
                    if vol:
                        print(f"    Status: OK")
                        iv_pct = f"{vol.iv * 100:.2f}%" if vol.iv else "N/A"
                        hv_pct = f"{vol.hv * 100:.2f}%" if vol.hv else "N/A"
                        print(f"    IV (30-day): {iv_pct}")
                        print(f"    HV (30-day): {hv_pct}")
                        print(f"    IV Rank: {vol.iv_rank}")
                        print(f"    PCR: {vol.pcr}")
                    else:
                        print(f"    Status: NO DATA")
                except Exception as e:
                    print(f"    Status: FAILED - {type(e).__name__}: {e}")

    except ImportError as e:
        print(f"IBKR provider not available: {e}")
    except Exception as e:
        print(f"IBKR connection error: {e}")


def test_futu_provider():
    """Test Futu provider for HK symbols."""
    print("\n" + "=" * 60)
    print("FUTU PROVIDER")
    print("=" * 60)

    try:
        from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE
        from src.data.models.stock import KlineType

        if not FUTU_AVAILABLE:
            print("Futu library (futu-api) not installed.")
            return

        print("\nConnecting to Futu OpenD...")

        # Use context manager pattern for proper connection
        with FutuProvider() as provider:
            if not provider.is_available:
                print("Futu not available. Please start OpenD.")
                return

            print("Connected!")

            end_date = date.today()
            start_date = end_date - timedelta(days=30)

            # Symbols to test
            symbols = [
                ("800125.HK", "VHSI (Hang Seng Volatility Index)"),
                ("800000.HK", "HSI (Hang Seng Index)"),
                ("2800.HK", "Tracker Fund ETF"),
                ("3032.HK", "HSTECH ETF"),
            ]

            for symbol, desc in symbols:
                print(f"\n[{symbol}] {desc}")
                try:
                    klines = provider.get_history_kline(
                        symbol, KlineType.DAY, start_date, end_date
                    )
                    if klines:
                        latest = klines[-1]
                        print(f"    Status: OK")
                        print(f"    Latest Close: {latest.close}")
                        print(f"    Date: {latest.timestamp}")
                        print(f"    Data Points: {len(klines)}")
                    else:
                        print(f"    Status: NO DATA (empty result)")
                except Exception as e:
                    print(f"    Status: FAILED - {type(e).__name__}: {e}")

    except ImportError as e:
        print(f"Futu provider not available: {e}")
    except Exception as e:
        print(f"Futu connection error: {e}")



def main():


    log_level = logging.DEBUG 
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(UnicodeSafeFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.root.handlers = []
    logging.root.addHandler(handler)
    logging.root.setLevel(log_level)


    print("=" * 60)
    print("HK DATA SOURCE AVAILABILITY TEST")
    print(f"Date: {date.today()}")
    print("=" * 60)

    print("\nTesting symbols:")
    print("  - 800125.HK: VHSI (Hang Seng Volatility Index)")
    print("  - 800000.HK: HSI (Hang Seng Index)")
    print("  - ^HSI: HSI via Yahoo standard format")
    print("  - HSTECH.HK: Hang Seng TECH Index")

    test_yahoo_provider()
    test_ibkr_provider()
    #test_futu_provider()

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
