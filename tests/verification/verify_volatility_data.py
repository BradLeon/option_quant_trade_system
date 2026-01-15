#!/usr/bin/env python3
"""Volatility Data Verification Script.

Verifies the accuracy of volatility data by comparing API results against
ground truth from external sources (Futu screenshots).

This script tests two layers:
1. Data Layer (Provider): IV from option chain, HV from prices, PCR from volumes
2. Engine Layer: calc_hv, get_iv, calc_iv_rank, calc_iv_percentile, calc_pcr

Usage:
    python tests/verification/verify_volatility_data.py
    python tests/verification/verify_volatility_data.py --provider futu
    python tests/verification/verify_volatility_data.py --engine-only
"""

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


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

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data.providers import UnifiedDataProvider
from src.data.models.option import OptionQuote, OptionChain
from src.data.models.stock import StockVolatility, KlineType

# Engine layer imports - metrics from StockVolatility model
from src.engine.position.volatility.metrics import (
    get_iv as metrics_get_iv,
    get_hv as metrics_get_hv,
    get_iv_rank as metrics_get_iv_rank,
    get_iv_percentile as metrics_get_iv_percentile,
    get_pcr as metrics_get_pcr,
    evaluate_volatility,
)
# Legacy calculation functions (for fallback when StockVolatility not available)
from src.engine.position.volatility import (
    calc_hv,
    get_iv,
    calc_iv_rank,
    calc_iv_percentile,
)
from src.engine.account.sentiment.pcr import calc_pcr


@dataclass
class ComparisonResult:
    """Result of a single metric comparison."""

    metric: str
    expected: Any
    actual: Any
    diff_percent: float | None
    status: str  # MATCH, DIFF, MISSING, SKIP


@dataclass
class VerificationReport:
    """Complete verification report for a symbol."""

    symbol: str
    timestamp: str
    source: str
    comparisons: list[ComparisonResult]
    total_metrics: int
    matched: int
    different: int
    missing: int
    skipped: int


@dataclass
class EngineTestResult:
    """Result of an engine layer test."""

    function_name: str
    input_symbol: str
    expected: Any
    actual: Any
    passed: bool
    message: str


# Ground truth data extracted from Futu screenshots
# Date: 2025-12-18
GROUND_TRUTH = {
     "9988.HK": {
        "iv": 0.4329,  # 21.93% (ATM option IV)
        "hv": 0.4022,  # 18.39% (20-day HV)
        "iv_rank": 10,  # IV Rank (0-100)
        "iv_percentile": 0.47,  # 4% (IV Percentile)
        "pcr": 1.22,  # Put/Call Ratio
    },
    "0700.HK": {
        "iv": 0.2147,  # 21.93% (ATM option IV)
        "hv": 0.2103,  # 18.39% (20-day HV)
        "iv_rank": 10,  # IV Rank (0-100)
        "iv_percentile": 0.143,  # 4% (IV Percentile)
        "pcr": 0.92,  # Put/Call Ratio
    },
    "TSLA": {
        "iv": 0.458,  # 54.69% (ATM option IV)
        "hv": 0.3592,  # 41.28% (20-day HV)
        "iv_rank": 7,  # IV Rank (0-100)
        "iv_percentile": 0.13,  # 18% (IV Percentile)
        "pcr": 0.80,  # Put/Call Ratio
    }
}

# Tolerance levels for different metrics
TOLERANCE = {
    "iv": 0.15,  # 15% tolerance for IV (can vary intraday)
    "hv": 0.10,  # 10% tolerance for HV
    "pcr": 0.20,  # 20% tolerance for PCR (volatile)
    "iv_rank": 0.30,  # 30% tolerance for IV Rank
    "iv_percentile": 0.30,  # 30% tolerance for IV Percentile
}


def format_percent(value: float | None) -> str:
    """Format a value as percentage."""
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def format_value(value: Any, metric: str) -> str:
    """Format a value for display."""
    if value is None:
        return "N/A"
    if metric in ("iv", "hv", "iv_percentile"):
        return format_percent(value)
    if metric == "iv_rank":
        return f"{value:.1f}"
    if metric == "pcr":
        return f"{value:.2f}"
    return str(value)


def calculate_diff_percent(expected: Any, actual: Any) -> float | None:
    """Calculate percentage difference between expected and actual values."""
    if expected is None or actual is None:
        return None
    if expected == 0:
        if actual == 0:
            return 0.0
        return float("inf")
    return (actual - expected) / abs(expected) * 100


def compare_metric(
    metric: str, expected: Any, actual: Any, tolerance: float
) -> ComparisonResult:
    """Compare a single metric and return the result."""
    diff = calculate_diff_percent(expected, actual)

    if actual is None:
        status = "MISSING"
    elif expected is None:
        status = "SKIP"
    elif diff is None:
        status = "MISSING"
    elif abs(diff) <= tolerance * 100:
        status = "MATCH"
    else:
        status = "DIFF"

    return ComparisonResult(
        metric=metric,
        expected=expected,
        actual=actual,
        diff_percent=diff,
        status=status,
    )


def get_atm_iv(option_chain: OptionChain, spot_price: float) -> float | None:
    """Get ATM (at-the-money) option IV.

    Returns the average IV of ATM call and put options.
    """
    if not option_chain:
        return None

    atm_call, atm_put = option_chain.get_atm_options(spot_price)

    ivs = []
    if atm_call and atm_call.iv is not None:
        ivs.append(atm_call.iv)
    if atm_put and atm_put.iv is not None:
        ivs.append(atm_put.iv)

    if not ivs:
        return None

    return sum(ivs) / len(ivs)


def calc_pcr_from_chain(option_chain: OptionChain) -> float | None:
    """Calculate Put/Call Ratio from option chain volumes."""
    if not option_chain:
        return None

    total_put_volume = sum(
        p.volume for p in option_chain.puts if p.volume is not None
    )
    total_call_volume = sum(
        c.volume for c in option_chain.calls if c.volume is not None
    )

    return calc_pcr(total_put_volume, total_call_volume)


def verify_symbol(symbol: str, provider: UnifiedDataProvider) -> tuple[VerificationReport, dict]:
    """Verify volatility data for a single symbol.

    Returns:
        Tuple of (VerificationReport, cached data for engine tests)
    """
    print(f"\nFetching volatility data for {symbol}...")
    cached_data = {}

    expected_data = GROUND_TRUTH.get(symbol, {})
    comparisons = []
    source = "unknown"
    atm_iv = None
    hv = None
    pcr = None
    spot_price = None

    # Method 1: Try using get_stock_volatility() API (IBKR provides direct IV/HV)
    stock_vol = None
    if hasattr(provider, 'get_stock_volatility'):
        stock_vol = provider.get_stock_volatility(symbol)

    if stock_vol is not None:
        print(f"  Using get_stock_volatility() API (source: {stock_vol.source})")
        atm_iv = stock_vol.iv
        hv = stock_vol.hv
        pcr = stock_vol.pcr
        source = stock_vol.source
        print(f"  IV (30d): {format_percent(atm_iv)}")
        print(f"  HV (30d): {format_percent(hv)}")
        if pcr is not None:
            print(f"  PCR: {pcr:.2f}")
        cached_data["stock_volatility"] = stock_vol
        cached_data["atm_iv"] = atm_iv
        cached_data["hv"] = hv
    else:
        print(f"  get_stock_volatility() not available, using fallback method")

        # Fallback Method: Calculate from option chain and historical prices

        # 1. Fetch current stock quote for spot price
        quote = provider.get_stock_quote(symbol)
        if not quote:
            print(f"  WARNING: Could not fetch stock quote for {symbol}")
        else:
            spot_price = quote.close  # 'close' contains the last/current price
            print(f"  Spot price: {spot_price}")
            source = quote.source

        # 2. Fetch option chain for IV and PCR
        option_chain = provider.get_option_chain(symbol)
        if not option_chain:
            print(f"  WARNING: Could not fetch option chain for {symbol}")
        else:
            print(f"  Option chain: {len(option_chain.calls)} calls, {len(option_chain.puts)} puts")
            source = option_chain.source

            # Get ATM IV
            if spot_price:
                atm_iv = get_atm_iv(option_chain, spot_price)
                print(f"  ATM IV: {format_percent(atm_iv)}")

            # Calculate PCR
            pcr = calc_pcr_from_chain(option_chain)
            print(f"  PCR: {pcr:.2f}" if pcr else "  PCR: N/A")

            # Cache for engine tests
            cached_data["option_chain"] = option_chain
            cached_data["spot_price"] = spot_price
            cached_data["atm_iv"] = atm_iv

        # 3. Fetch historical prices for HV calculation
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=60)  # Fetch 60 days to ensure 30 trading days
        klines = provider.get_history_kline(
            symbol, ktype=KlineType.DAY, start_date=start_date, end_date=end_date
        )
        if not klines or len(klines) < 21:
            print(f"  WARNING: Insufficient historical data for HV (got {len(klines) if klines else 0} days)")
        else:
            prices = [k.close for k in klines]
            hv = calc_hv(prices, window=20)
            print(f"  HV (20d): {format_percent(hv)}")
            cached_data["prices"] = prices
            cached_data["hv"] = hv

    # Compare metrics
    # IV
    comparisons.append(compare_metric(
        "iv", expected_data.get("iv"), atm_iv, TOLERANCE["iv"]
    ))

    # HV
    comparisons.append(compare_metric(
        "hv", expected_data.get("hv"), hv, TOLERANCE["hv"]
    ))

    # PCR
    comparisons.append(compare_metric(
        "pcr", expected_data.get("pcr"), pcr, TOLERANCE["pcr"]
    ))

    # IV Rank and IV Percentile - get from StockVolatility if available
    iv_rank = None
    iv_percentile = None
    if stock_vol is not None:
        iv_rank = stock_vol.iv_rank
        iv_percentile = stock_vol.iv_percentile
        if iv_rank is not None:
            print(f"  IV Rank: {iv_rank:.1f}")
        if iv_percentile is not None:
            print(f"  IV Percentile: {format_percent(iv_percentile)}")

    if iv_rank is not None:
        comparisons.append(compare_metric(
            "iv_rank", expected_data.get("iv_rank"), iv_rank, TOLERANCE["iv_rank"]
        ))
    else:
        comparisons.append(ComparisonResult(
            metric="iv_rank",
            expected=expected_data.get("iv_rank"),
            actual=None,
            diff_percent=None,
            status="SKIP",  # Requires historical IV data
        ))

    if iv_percentile is not None:
        comparisons.append(compare_metric(
            "iv_percentile", expected_data.get("iv_percentile"), iv_percentile, TOLERANCE["iv_percentile"]
        ))
    else:
        comparisons.append(ComparisonResult(
            metric="iv_percentile",
            expected=expected_data.get("iv_percentile"),
            actual=None,
            diff_percent=None,
            status="SKIP",  # Requires historical IV data
        ))

    # Count results
    matched = sum(1 for c in comparisons if c.status == "MATCH")
    different = sum(1 for c in comparisons if c.status == "DIFF")
    missing = sum(1 for c in comparisons if c.status == "MISSING")
    skipped = sum(1 for c in comparisons if c.status == "SKIP")

    report = VerificationReport(
        symbol=symbol,
        timestamp=datetime.now().isoformat(),
        source=source,
        comparisons=comparisons,
        total_metrics=len(comparisons),
        matched=matched,
        different=different,
        missing=missing,
        skipped=skipped,
    )

    return report, cached_data


def print_report(report: VerificationReport) -> None:
    """Print a formatted verification report to console."""
    print("\n" + "=" * 80)
    print(f"=== Volatility Data Verification Report ===")
    print("=" * 80)
    print(f"Symbol: {report.symbol}")
    print(f"Timestamp: {report.timestamp}")
    print(f"Source: {report.source}")
    print("-" * 80)
    print(
        f"{'Metric':<20} | {'Expected':<12} | {'Actual':<12} | {'Diff%':<10} | {'Status':<8}"
    )
    print("-" * 80)

    # Sort by status: DIFF first, then MISSING, then SKIP, then MATCH
    status_order = {"DIFF": 0, "MISSING": 1, "SKIP": 2, "MATCH": 3}
    sorted_comparisons = sorted(
        report.comparisons, key=lambda x: status_order.get(x.status, 99)
    )

    for comp in sorted_comparisons:
        expected_str = format_value(comp.expected, comp.metric)
        actual_str = format_value(comp.actual, comp.metric)
        diff_str = f"{comp.diff_percent:+.2f}%" if comp.diff_percent is not None else "N/A"

        # Color-code status
        if comp.status == "MATCH":
            status_str = f"\033[92m{comp.status}\033[0m"  # Green
        elif comp.status == "DIFF":
            status_str = f"\033[91m{comp.status}\033[0m"  # Red
        elif comp.status == "MISSING":
            status_str = f"\033[93m{comp.status}\033[0m"  # Yellow
        else:
            status_str = f"\033[94m{comp.status}\033[0m"  # Blue for SKIP

        print(
            f"{comp.metric:<20} | {expected_str:<12} | {actual_str:<12} | {diff_str:<10} | {status_str:<8}"
        )

    print("-" * 80)
    print(f"\nSummary:")
    print(f"  Total metrics: {report.total_metrics}")
    print(f"  \033[92mMatched (within tolerance): {report.matched}\033[0m")
    print(f"  \033[91mDifferent (>tolerance): {report.different}\033[0m")
    print(f"  \033[93mMissing (API returned None): {report.missing}\033[0m")
    print(f"  \033[94mSkipped (requires historical data): {report.skipped}\033[0m")


def verify_engine_layer(symbol: str, cached_data: dict) -> list[EngineTestResult]:
    """Verify engine layer functions work correctly.

    Uses the new metrics module that extracts data from StockVolatility model.
    This mirrors how fundamental/metrics.py uses Fundamental model.

    Tests:
    1. metrics_get_hv() - HV from StockVolatility
    2. metrics_get_iv() - IV from StockVolatility
    3. metrics_get_iv_rank() - IV Rank from StockVolatility
    4. metrics_get_iv_percentile() - IV Percentile from StockVolatility
    5. metrics_get_pcr() - PCR from StockVolatility
    6. evaluate_volatility() - Overall volatility score

    Args:
        symbol: Stock symbol.
        cached_data: Data cached from data layer tests.

    Returns:
        List of test results.
    """
    results = []
    ground_truth = GROUND_TRUTH.get(symbol, {})

    # Get StockVolatility from cached data
    stock_vol = cached_data.get("stock_volatility")

    # Test 1: metrics_get_hv()
    hv = metrics_get_hv(stock_vol)
    expected_hv = ground_truth.get("hv")
    if hv is not None and expected_hv is not None:
        diff = abs(hv - expected_hv) / expected_hv if expected_hv != 0 else 0
        passed = diff <= 0.25  # 25% tolerance (IBKR uses 30-day, ground truth may use 20-day)
        results.append(EngineTestResult(
            function_name="metrics_get_hv()",
            input_symbol=symbol,
            expected=f"{expected_hv*100:.2f}%",
            actual=f"{hv*100:.2f}%",
            passed=passed,
            message=f"HV: {hv*100:.2f}% from StockVolatility (diff: {diff*100:.1f}%)"
        ))
    elif hv is not None:
        results.append(EngineTestResult(
            function_name="metrics_get_hv()",
            input_symbol=symbol,
            expected="N/A",
            actual=f"{hv*100:.2f}%",
            passed=True,
            message=f"HV: {hv*100:.2f}% (no ground truth to compare)"
        ))
    else:
        results.append(EngineTestResult(
            function_name="metrics_get_hv()",
            input_symbol=symbol,
            expected=f"{expected_hv*100:.2f}%" if expected_hv else "N/A",
            actual="N/A",
            passed=False,
            message="HV not available in StockVolatility"
        ))

    # Test 2: metrics_get_iv()
    iv = metrics_get_iv(stock_vol)
    expected_iv = ground_truth.get("iv")
    if iv is not None and expected_iv is not None:
        diff = abs(iv - expected_iv) / expected_iv if expected_iv != 0 else 0
        passed = diff <= 0.20  # 20% tolerance
        results.append(EngineTestResult(
            function_name="metrics_get_iv()",
            input_symbol=symbol,
            expected=f"{expected_iv*100:.2f}%",
            actual=f"{iv*100:.2f}%",
            passed=passed,
            message=f"IV: {iv*100:.2f}% from StockVolatility (diff: {diff*100:.1f}%)"
        ))
    elif iv is not None:
        results.append(EngineTestResult(
            function_name="metrics_get_iv()",
            input_symbol=symbol,
            expected="N/A",
            actual=f"{iv*100:.2f}%",
            passed=True,
            message=f"IV: {iv*100:.2f}% (no ground truth to compare)"
        ))
    else:
        results.append(EngineTestResult(
            function_name="metrics_get_iv()",
            input_symbol=symbol,
            expected=f"{expected_iv*100:.2f}%" if expected_iv else "N/A",
            actual="N/A",
            passed=False,
            message="IV not available in StockVolatility"
        ))

    # Test 3: metrics_get_iv_rank()
    iv_rank = metrics_get_iv_rank(stock_vol)
    expected_iv_rank = ground_truth.get("iv_rank")
    if iv_rank is not None and expected_iv_rank is not None:
        diff = abs(iv_rank - expected_iv_rank) / expected_iv_rank if expected_iv_rank != 0 else 0
        passed = diff <= 0.30  # 30% tolerance
        results.append(EngineTestResult(
            function_name="metrics_get_iv_rank()",
            input_symbol=symbol,
            expected=f"{expected_iv_rank:.1f}",
            actual=f"{iv_rank:.1f}",
            passed=passed,
            message=f"IV Rank: {iv_rank:.1f} from StockVolatility (diff: {diff*100:.1f}%)"
        ))
    elif iv_rank is not None:
        results.append(EngineTestResult(
            function_name="metrics_get_iv_rank()",
            input_symbol=symbol,
            expected="N/A",
            actual=f"{iv_rank:.1f}",
            passed=True,
            message=f"IV Rank: {iv_rank:.1f} (no ground truth to compare)"
        ))
    else:
        results.append(EngineTestResult(
            function_name="metrics_get_iv_rank()",
            input_symbol=symbol,
            expected=f"{expected_iv_rank:.1f}" if expected_iv_rank else "N/A",
            actual="N/A",
            passed=False,
            message="IV Rank not available in StockVolatility"
        ))

    # Test 4: metrics_get_iv_percentile()
    iv_percentile = metrics_get_iv_percentile(stock_vol)
    expected_iv_pctl = ground_truth.get("iv_percentile")
    if iv_percentile is not None and expected_iv_pctl is not None:
        diff = abs(iv_percentile - expected_iv_pctl) / expected_iv_pctl if expected_iv_pctl != 0 else 0
        passed = diff <= 0.30  # 30% tolerance
        results.append(EngineTestResult(
            function_name="metrics_get_iv_percentile()",
            input_symbol=symbol,
            expected=f"{expected_iv_pctl*100:.1f}%",
            actual=f"{iv_percentile*100:.1f}%",
            passed=passed,
            message=f"IV Percentile: {iv_percentile*100:.1f}% from StockVolatility (diff: {diff*100:.1f}%)"
        ))
    elif iv_percentile is not None:
        results.append(EngineTestResult(
            function_name="metrics_get_iv_percentile()",
            input_symbol=symbol,
            expected="N/A",
            actual=f"{iv_percentile*100:.1f}%",
            passed=True,
            message=f"IV Percentile: {iv_percentile*100:.1f}% (no ground truth to compare)"
        ))
    else:
        results.append(EngineTestResult(
            function_name="metrics_get_iv_percentile()",
            input_symbol=symbol,
            expected=f"{expected_iv_pctl*100:.1f}%" if expected_iv_pctl else "N/A",
            actual="N/A",
            passed=False,
            message="IV Percentile not available in StockVolatility"
        ))

    # Test 5: metrics_get_pcr()
    pcr = metrics_get_pcr(stock_vol)
    expected_pcr = ground_truth.get("pcr")
    if pcr is not None and expected_pcr is not None:
        diff = abs(pcr - expected_pcr) / expected_pcr if expected_pcr != 0 else 0
        passed = diff <= 0.25  # 25% tolerance
        results.append(EngineTestResult(
            function_name="metrics_get_pcr()",
            input_symbol=symbol,
            expected=f"{expected_pcr:.2f}",
            actual=f"{pcr:.2f}",
            passed=passed,
            message=f"PCR: {pcr:.2f} from StockVolatility (diff: {diff*100:.1f}%)"
        ))
    elif pcr is not None:
        results.append(EngineTestResult(
            function_name="metrics_get_pcr()",
            input_symbol=symbol,
            expected="N/A",
            actual=f"{pcr:.2f}",
            passed=True,
            message=f"PCR: {pcr:.2f} (no ground truth to compare)"
        ))
    else:
        results.append(EngineTestResult(
            function_name="metrics_get_pcr()",
            input_symbol=symbol,
            expected=f"{expected_pcr:.2f}" if expected_pcr else "N/A",
            actual="N/A",
            passed=False,
            message="PCR not available in StockVolatility"
        ))

    # Test 6: evaluate_volatility() - Overall score
    if stock_vol is not None:
        vol_score = evaluate_volatility(stock_vol)
        passed = vol_score is not None and 0 <= vol_score.score <= 100
        results.append(EngineTestResult(
            function_name="evaluate_volatility()",
            input_symbol=symbol,
            expected="0-100 score",
            actual=f"{vol_score.score:.1f} ({vol_score.rating.value})",
            passed=passed,
            message=f"Score: {vol_score.score:.1f}, Rating: {vol_score.rating.value} for option selling"
        ))
    else:
        results.append(EngineTestResult(
            function_name="evaluate_volatility()",
            input_symbol=symbol,
            expected="N/A",
            actual="N/A",
            passed=False,
            message="StockVolatility not available for evaluation"
        ))

    return results


def print_engine_report(symbol: str, results: list[EngineTestResult]) -> tuple[int, int]:
    """Print engine layer test results."""
    print(f"\n{'='*80}")
    print(f"=== Engine Layer Tests for {symbol} ===")
    print("=" * 80)
    print(f"{'Function':<25} | {'Status':<8} | {'Details'}")
    print("-" * 80)

    passed_count = 0
    for result in results:
        if result.passed:
            status = "\033[92mPASS\033[0m"
            passed_count += 1
        else:
            status = "\033[91mFAIL\033[0m"

        print(f"{result.function_name:<25} | {status:<8} | {result.message}")

    print("-" * 80)
    print(f"Summary: {passed_count}/{len(results)} tests passed")
    return passed_count, len(results)


def save_report(reports: list[VerificationReport], output_dir: Path) -> str:
    """Save reports to JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"volatility_verification_{timestamp}.json"
    filepath = output_dir / filename

    data = {
        "timestamp": datetime.now().isoformat(),
        "reports": [],
    }

    for report in reports:
        report_dict = {
            "symbol": report.symbol,
            "timestamp": report.timestamp,
            "source": report.source,
            "summary": {
                "total_metrics": report.total_metrics,
                "matched": report.matched,
                "different": report.different,
                "missing": report.missing,
                "skipped": report.skipped,
            },
            "comparisons": [
                {
                    "metric": c.metric,
                    "expected": c.expected,
                    "actual": c.actual,
                    "diff_percent": c.diff_percent,
                    "status": c.status,
                }
                for c in report.comparisons
            ],
        }
        data["reports"].append(report_dict)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return str(filepath)


def test_provider_availability() -> dict[str, bool]:
    """Test which providers are available."""
    availability = {"yahoo": True}

    # Test Futu
    try:
        from src.data.providers.futu_provider import FutuProvider, FUTU_AVAILABLE
        if FUTU_AVAILABLE:
            try:
                with FutuProvider() as p:
                    availability["futu"] = p.is_available
            except Exception:
                availability["futu"] = False
        else:
            availability["futu"] = False
    except ImportError:
        availability["futu"] = False

    # Test IBKR
    try:
        from src.data.providers.ibkr_provider import IBKRProvider, IBKR_AVAILABLE
        if IBKR_AVAILABLE:
            try:
                with IBKRProvider() as p:
                    availability["ibkr"] = p.is_available
            except Exception:
                availability["ibkr"] = False
        else:
            availability["ibkr"] = False
    except ImportError:
        availability["ibkr"] = False

    return availability


def get_provider(name: str):
    """Get a provider instance by name."""
    if name == "yahoo":
        from src.data.providers.yahoo_provider import YahooProvider
        return YahooProvider()
    elif name == "futu":
        from src.data.providers.futu_provider import FutuProvider
        return FutuProvider()
    elif name == "ibkr":
        from src.data.providers.ibkr_provider import IBKRProvider
        return IBKRProvider()
    elif name == "unified":
        return UnifiedDataProvider()
    else:
        raise ValueError(f"Unknown provider: {name}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Verify volatility data accuracy")
    parser.add_argument(
        "--provider",
        choices=["yahoo", "futu", "ibkr", "unified"],
        default="unified",
        help="Provider to test (default: unified)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Symbols to test (default: all ground truth symbols)"
    )
    parser.add_argument(
        "--engine-only",
        action="store_true",
        help="Only run engine layer tests (skip data layer verification)"
    )
    parser.add_argument(
        "--skip-engine",
        action="store_true",
        help="Skip engine layer tests"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging from providers"
    )
    args = parser.parse_args()

    # Configure logging based on verbose flag
    # Use UnicodeSafeFormatter to decode Unicode escape sequences from ib_async
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(UnicodeSafeFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.root.handlers = []
    logging.root.addHandler(handler)
    logging.root.setLevel(log_level)

    print("=" * 80)
    print("Volatility Data Verification Test")
    print("=" * 80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Tolerance: IV=15%, HV=10%, PCR=20%")

    symbols = args.symbols if args.symbols else list(GROUND_TRUTH.keys())
    print(f"Symbols to verify: {symbols}")

    all_reports = []
    cached_data_by_symbol = {}
    total_passed = 0
    total_tests = 0

    # =========================================================================
    # Phase 1: Data Layer Tests
    # =========================================================================
    if not args.engine_only:
        print("\n" + "=" * 80)
        print("Phase 1: Data Layer Tests")
        print("=" * 80)

        try:
            provider = get_provider(args.provider)

            # Handle context managers for Futu/IBKR
            if hasattr(provider, '__enter__'):
                provider.__enter__()

            for symbol in symbols:
                if symbol not in GROUND_TRUTH:
                    print(f"Warning: No ground truth for {symbol}, skipping")
                    continue
                report, cached_data = verify_symbol(symbol, provider)
                all_reports.append(report)
                cached_data_by_symbol[symbol] = cached_data
                print_report(report)

            if hasattr(provider, '__exit__'):
                provider.__exit__(None, None, None)

        except Exception as e:
            print(f"Error testing provider: {e}")
            import traceback
            traceback.print_exc()

        # Save reports
        logs_dir = project_root / "logs"
        logs_dir.mkdir(exist_ok=True)

        if all_reports:
            saved_path = save_report(all_reports, logs_dir)
            print(f"\n\033[94mReport saved to: {saved_path}\033[0m")

        # Print data layer summary
        print("\n" + "=" * 80)
        print("=== Data Layer Summary ===")
        print("=" * 80)

        if all_reports:
            total_matched = sum(r.matched for r in all_reports)
            total_metrics = sum(r.total_metrics - r.skipped for r in all_reports)
            overall_rate = total_matched / total_metrics * 100 if total_metrics > 0 else 0
            print(f"Match rate: {overall_rate:.1f}% ({total_matched}/{total_metrics} excluding skipped)")

    # =========================================================================
    # Phase 2: Engine Layer Tests
    # =========================================================================
    if not args.skip_engine:
        print("\n" + "=" * 80)
        print("Phase 2: Engine Layer Tests")
        print("=" * 80)

        # If engine-only, need to fetch data first
        if args.engine_only:
            print(f"\nFetching data using {args.provider} provider...")
            provider = get_provider(args.provider)
            if hasattr(provider, '__enter__'):
                provider.__enter__()

            for symbol in symbols:
                _, cached_data = verify_symbol(symbol, provider)
                cached_data_by_symbol[symbol] = cached_data

            if hasattr(provider, '__exit__'):
                provider.__exit__(None, None, None)

        # Run engine layer tests
        for symbol in symbols:
            cached_data = cached_data_by_symbol.get(symbol, {})
            if not cached_data:
                print(f"\n\033[93mSkipping engine tests for {symbol}: No cached data\033[0m")
                continue

            results = verify_engine_layer(symbol, cached_data)
            passed, total = print_engine_report(symbol, results)
            total_passed += passed
            total_tests += total

        # Print engine layer summary
        print("\n" + "=" * 80)
        print("=== Engine Layer Summary ===")
        print("=" * 80)
        if total_tests > 0:
            engine_rate = total_passed / total_tests * 100
            print(f"Engine Tests: {engine_rate:.1f}% pass rate ({total_passed}/{total_tests})")
        else:
            print("No engine tests executed")

    # =========================================================================
    # Final Summary
    # =========================================================================
    print("\n" + "=" * 80)
    print("=== FINAL SUMMARY ===")
    print("=" * 80)
    if not args.engine_only and all_reports:
        total_matched = sum(r.matched for r in all_reports)
        total_metrics = sum(r.total_metrics - r.skipped for r in all_reports)
        overall_rate = total_matched / total_metrics * 100 if total_metrics > 0 else 0
        print(f"Data Layer: {overall_rate:.1f}% match rate ({total_matched}/{total_metrics})")
    if not args.skip_engine and total_tests > 0:
        engine_rate = total_passed / total_tests * 100
        print(f"Engine Layer: {total_passed}/{total_tests} tests passed ({engine_rate:.1f}%)")


if __name__ == "__main__":
    main()
