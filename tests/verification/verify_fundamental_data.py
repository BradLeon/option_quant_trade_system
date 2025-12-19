#!/usr/bin/env python3
"""Fundamental Data Verification Script.

Verifies the accuracy and completeness of fundamental data by comparing
API results against ground truth from external sources (IBKR, Futu, etc.).

This script tests two layers:
1. Data Layer (Provider): Raw fundamental data from API
2. Engine Layer: Calculated metrics from fundamental data

Usage:
    python tests/verification/verify_fundamental_data.py
    python tests/verification/verify_fundamental_data.py --provider yahoo
    python tests/verification/verify_fundamental_data.py --all-providers
    python tests/verification/verify_fundamental_data.py --engine-only
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data.providers import UnifiedDataProvider
from src.data.providers.yahoo_provider import YahooProvider

# Engine layer imports
from src.engine import (
    evaluate_fundamentals,
    get_analyst_rating,
    get_pe,
    get_profit_margin,
    get_revenue_growth,
    is_fundamentally_strong,
    RatingSignal,
)


@dataclass
class ComparisonResult:
    """Result of a single field comparison."""

    field: str
    expected: Any
    actual: Any
    diff_percent: float | None
    status: str  # MATCH, DIFF, MISSING, EXTRA


@dataclass
class VerificationReport:
    """Complete verification report for a symbol."""

    symbol: str
    timestamp: str
    source: str
    comparisons: list[ComparisonResult]
    total_fields: int
    matched: int
    different: int
    missing: int
    extra: int


# Ground truth data extracted from screenshots (IBKR, Futu)
# Date: 2025-12-18
GROUND_TRUTH = {
    "0700.HK": {
        # Price & Volume
        "market_cap": 5446.3e9,  # HKD (5,446.3B)
        "fifty_two_week_high": 683,
        "fifty_two_week_low": 364.8,
        # Valuation
        "pe_ratio": 23.1,  # PE (excl special)
        "pb_ratio": 4.2,
        "ps_ratio": 6.76,
        "eps": 25.83,  # EPS (excl non-recurring)
        # Financial Strength
        "current_ratio": 1.36,
        "quick_ratio": 1.4,
        "debt_to_equity": 34.92,
        # Revenue & Profit
        "revenue": 805919.6e6,  # HKD
        "profit": 240620e6,  # Net Income HKD
        # Margins (as decimals)
        "gross_margin": 0.555,  # 55.5%
        "operating_margin": 0.333,  # 33.3%
        "profit_margin": 0.304,  # 30.4%
        # Management Efficiency
        "roa": 0.117,  # 11.7%
        "roe": 0.209,  # 20.9%
        # Growth
        "revenue_growth": 0.118,  # 11.8%
        "earnings_growth": 0.163,  # 16.3%
        # Analyst Ratings
        "analyst_count": 40,
        "recommendation_mean": 1.15,  # Strong Buy = 1
        "target_price": 727.20,
        "beta": 1.090,
    },
    "TSLA": {
        # Price & Volume
        "market_cap": 1.55e12,  # USD (1.55T)
        "fifty_two_week_high": 495.280,
        "fifty_two_week_low": 214.250,
        "shares_outstanding": 3.326e9,  # 33.26亿
        # Valuation
        "pe_ratio": 322.25,  # PE TTM
        "pb_ratio": 19.432,
        "ps_ratio": 16.35,
        "beta": 1.82,
        "eps": 1.5,  # EPS (excl non-recurring)
        # Financial Strength
        "current_ratio": 2.07,
        "quick_ratio": 1.7,
        "debt_to_equity": 9.63,
        # Revenue & Profit
        "revenue": 95633e6,  # USD
        "profit": 5268e6,  # Net Income USD
        # Margins (as decimals)
        "gross_margin": 0.17,  # 17%
        "operating_margin": 0.047,  # 4.7%
        "profit_margin": 0.056,  # 5.6%
        # Management Efficiency
        "roa": 0.042,  # 4.2%
        "roe": 0.07,  # 7%
        # Growth
        "revenue_growth": 0.116,  # 11.6%
        "earnings_growth": -0.373,  # -37.3%
        # Analyst Ratings
        "recommendation_mean": 2.69, 
        "analyst_count": 55,
        "target_price": 378.69,
    },
}

# Tolerance levels for different field types
TOLERANCE = {
    "default": 0.05,  # 5% tolerance
    "volatile": 0.10,  # 10% for volatile metrics
    "exact": 0.01,  # 1% for exact matches
}

# Fields that are more volatile and need higher tolerance
VOLATILE_FIELDS = {
    "beta",
    "recommendation_mean",
    "earnings_growth",
    "revenue_growth",
    "target_price",
}


def format_value(value: Any, field: str) -> str:
    """Format a value for display."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        # Format large numbers
        if abs(value) >= 1e12:
            return f"{value/1e12:.2f}T"
        elif abs(value) >= 1e9:
            return f"{value/1e9:.2f}B"
        elif abs(value) >= 1e6:
            return f"{value/1e6:.2f}M"
        # Format percentages (stored as decimals)
        elif field in (
            "gross_margin",
            "operating_margin",
            "profit_margin",
            "roa",
            "roe",
            "revenue_growth",
            "earnings_growth",
            "dividend_yield",
        ):
            return f"{value*100:.2f}%"
        else:
            return f"{value:.4f}"
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


def compare_field(
    field: str, expected: Any, actual: Any, tolerance: float
) -> ComparisonResult:
    """Compare a single field and return the result."""
    diff = calculate_diff_percent(expected, actual)

    if actual is None:
        status = "MISSING"
    elif expected is None:
        status = "EXTRA"
    elif diff is None:
        status = "MISSING"
    elif abs(diff) <= tolerance * 100:
        status = "MATCH"
    else:
        status = "DIFF"

    return ComparisonResult(
        field=field,
        expected=expected,
        actual=actual,
        diff_percent=diff,
        status=status,
    )


def verify_symbol(symbol: str, provider: UnifiedDataProvider) -> VerificationReport:
    """Verify fundamental data for a single symbol."""
    print(f"\nFetching fundamental data for {symbol}...")
    fundamental = provider.get_fundamental(symbol)

    if not fundamental:
        print(f"ERROR: Could not fetch fundamental data for {symbol}")
        return VerificationReport(
            symbol=symbol,
            timestamp=datetime.now().isoformat(),
            source="N/A",
            comparisons=[],
            total_fields=0,
            matched=0,
            different=0,
            missing=len(GROUND_TRUTH.get(symbol, {})),
            extra=0,
        )

    expected_data = GROUND_TRUTH.get(symbol, {})
    comparisons = []

    # Get all fields from both expected and actual
    all_fields = set(expected_data.keys())

    # Add actual fields that we track in ground truth
    actual_dict = {
        "market_cap": fundamental.market_cap,
        "pe_ratio": fundamental.pe_ratio,
        "pb_ratio": fundamental.pb_ratio,
        "ps_ratio": fundamental.ps_ratio,
        "eps": fundamental.eps,
        "revenue": fundamental.revenue,
        "profit": fundamental.profit,
        "gross_margin": fundamental.gross_margin,
        "operating_margin": fundamental.operating_margin,
        "profit_margin": fundamental.profit_margin,
        "current_ratio": fundamental.current_ratio,
        "quick_ratio": fundamental.quick_ratio,
        "debt_to_equity": fundamental.debt_to_equity,
        "roa": fundamental.roa,
        "roe": fundamental.roe,
        "beta": fundamental.beta,
        "fifty_two_week_high": fundamental.fifty_two_week_high,
        "fifty_two_week_low": fundamental.fifty_two_week_low,
        "shares_outstanding": fundamental.shares_outstanding,
        "revenue_growth": fundamental.revenue_growth,
        "earnings_growth": fundamental.earnings_growth,
        "analyst_count": fundamental.analyst_count,
        "recommendation_mean": fundamental.recommendation_mean,
        "target_price": fundamental.target_price,
        "dividend_yield": fundamental.dividend_yield,
        "avg_volume": fundamental.avg_volume,
    }

    # Compare each field
    for field in sorted(all_fields):
        expected = expected_data.get(field)
        actual = actual_dict.get(field)

        # Determine tolerance
        if field in VOLATILE_FIELDS:
            tol = TOLERANCE["volatile"]
        else:
            tol = TOLERANCE["default"]

        result = compare_field(field, expected, actual, tol)
        comparisons.append(result)

    # Count results
    matched = sum(1 for c in comparisons if c.status == "MATCH")
    different = sum(1 for c in comparisons if c.status == "DIFF")
    missing = sum(1 for c in comparisons if c.status == "MISSING")
    extra = sum(1 for c in comparisons if c.status == "EXTRA")

    return VerificationReport(
        symbol=symbol,
        timestamp=datetime.now().isoformat(),
        source=fundamental.source,
        comparisons=comparisons,
        total_fields=len(comparisons),
        matched=matched,
        different=different,
        missing=missing,
        extra=extra,
    )


def print_report(report: VerificationReport) -> None:
    """Print a formatted verification report to console."""
    print("\n" + "=" * 80)
    print(f"=== Fundamental Data Verification Report ===")
    print("=" * 80)
    print(f"Symbol: {report.symbol}")
    print(f"Timestamp: {report.timestamp}")
    print(f"Source: {report.source}")
    print("-" * 80)
    print(
        f"{'Field':<25} | {'Expected':<15} | {'Actual':<15} | {'Diff%':<10} | {'Status':<8}"
    )
    print("-" * 80)

    # Sort by status: DIFF first, then MISSING, then MATCH
    status_order = {"DIFF": 0, "MISSING": 1, "EXTRA": 2, "MATCH": 3}
    sorted_comparisons = sorted(
        report.comparisons, key=lambda x: status_order.get(x.status, 99)
    )

    for comp in sorted_comparisons:
        expected_str = format_value(comp.expected, comp.field)
        actual_str = format_value(comp.actual, comp.field)
        diff_str = f"{comp.diff_percent:+.2f}%" if comp.diff_percent is not None else "N/A"

        # Color-code status (using ANSI codes)
        if comp.status == "MATCH":
            status_str = f"\033[92m{comp.status}\033[0m"  # Green
        elif comp.status == "DIFF":
            status_str = f"\033[91m{comp.status}\033[0m"  # Red
        elif comp.status == "MISSING":
            status_str = f"\033[93m{comp.status}\033[0m"  # Yellow
        else:
            status_str = comp.status

        print(
            f"{comp.field:<25} | {expected_str:<15} | {actual_str:<15} | {diff_str:<10} | {status_str:<8}"
        )

    print("-" * 80)
    print(f"\nSummary:")
    print(f"  Total fields checked: {report.total_fields}")
    print(f"  \033[92mMatched (within tolerance): {report.matched}\033[0m")
    print(f"  \033[91mDifferent (>tolerance): {report.different}\033[0m")
    print(f"  \033[93mMissing (API returned None): {report.missing}\033[0m")
    print(f"  Extra: {report.extra}")

    match_rate = (
        report.matched / report.total_fields * 100 if report.total_fields > 0 else 0
    )
    print(f"\n  Match rate: {match_rate:.1f}%")


def save_report(reports: list[VerificationReport], output_dir: Path) -> str:
    """Save reports to JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"fundamental_verification_{timestamp}.json"
    filepath = output_dir / filename

    # Convert reports to serializable format
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
                "total_fields": report.total_fields,
                "matched": report.matched,
                "different": report.different,
                "missing": report.missing,
                "extra": report.extra,
                "match_rate": (
                    report.matched / report.total_fields * 100
                    if report.total_fields > 0
                    else 0
                ),
            },
            "comparisons": [
                {
                    "field": c.field,
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
    availability = {"yahoo": True}  # Yahoo is always available

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


# ============================================================================
# Engine Layer Verification
# ============================================================================

@dataclass
class EngineTestResult:
    """Result of an engine layer test."""
    function_name: str
    input_symbol: str
    expected: Any
    actual: Any
    passed: bool
    message: str


def verify_engine_layer(symbol: str, fundamental) -> list[EngineTestResult]:
    """Verify engine layer functions work correctly with fundamental data.

    Tests:
    1. get_pe() - extracts PE ratio correctly
    2. get_revenue_growth() - extracts revenue growth correctly
    3. get_profit_margin() - extracts profit margin correctly
    4. get_analyst_rating() - converts recommendation to rating signal
    5. evaluate_fundamentals() - calculates FundamentalScore
    6. is_fundamentally_strong() - returns boolean based on score

    Args:
        symbol: Stock symbol.
        fundamental: Fundamental data from provider.

    Returns:
        List of test results.
    """
    results = []
    ground_truth = GROUND_TRUTH.get(symbol, {})

    # Test 1: get_pe()
    pe = get_pe(fundamental)
    expected_pe = ground_truth.get("pe_ratio")
    if pe is not None and expected_pe is not None:
        diff = abs(pe - expected_pe) / expected_pe if expected_pe != 0 else 0
        passed = diff <= 0.10  # 10% tolerance
        results.append(EngineTestResult(
            function_name="get_pe()",
            input_symbol=symbol,
            expected=expected_pe,
            actual=pe,
            passed=passed,
            message=f"Extracted PE: {pe:.2f} (expected: {expected_pe:.2f}, diff: {diff*100:.1f}%)"
        ))
    elif pe is None:
        results.append(EngineTestResult(
            function_name="get_pe()",
            input_symbol=symbol,
            expected=expected_pe,
            actual=None,
            passed=False,
            message="PE extraction returned None"
        ))

    # Test 2: get_revenue_growth()
    growth = get_revenue_growth(fundamental)
    expected_growth = ground_truth.get("revenue_growth")
    if growth is not None and expected_growth is not None:
        diff = abs(growth - expected_growth) / abs(expected_growth) if expected_growth != 0 else 0
        passed = diff <= 0.20  # 20% tolerance for growth metrics
        results.append(EngineTestResult(
            function_name="get_revenue_growth()",
            input_symbol=symbol,
            expected=f"{expected_growth*100:.1f}%",
            actual=f"{growth*100:.1f}%",
            passed=passed,
            message=f"Extracted growth: {growth*100:.1f}% (expected: {expected_growth*100:.1f}%)"
        ))
    elif growth is None:
        results.append(EngineTestResult(
            function_name="get_revenue_growth()",
            input_symbol=symbol,
            expected=expected_growth,
            actual=None,
            passed=False,
            message="Revenue growth extraction returned None"
        ))

    # Test 3: get_profit_margin()
    margin = get_profit_margin(fundamental)
    expected_margin = ground_truth.get("profit_margin")
    if margin is not None and expected_margin is not None:
        diff = abs(margin - expected_margin) / expected_margin if expected_margin != 0 else 0
        passed = diff <= 0.15  # 15% tolerance
        results.append(EngineTestResult(
            function_name="get_profit_margin()",
            input_symbol=symbol,
            expected=f"{expected_margin*100:.1f}%",
            actual=f"{margin*100:.1f}%",
            passed=passed,
            message=f"Extracted margin: {margin*100:.1f}% (expected: {expected_margin*100:.1f}%)"
        ))
    elif margin is None:
        results.append(EngineTestResult(
            function_name="get_profit_margin()",
            input_symbol=symbol,
            expected=expected_margin,
            actual=None,
            passed=False,
            message="Profit margin extraction returned None"
        ))

    # Test 4: get_analyst_rating()
    rating = get_analyst_rating(fundamental)
    expected_rec = ground_truth.get("recommendation_mean")
    # Determine expected rating based on recommendation_mean
    if expected_rec is not None:
        if expected_rec <= 1.5:
            expected_rating = RatingSignal.STRONG_BUY
        elif expected_rec <= 2.5:
            expected_rating = RatingSignal.BUY
        elif expected_rec <= 3.5:
            expected_rating = RatingSignal.HOLD
        elif expected_rec <= 4.5:
            expected_rating = RatingSignal.SELL
        else:
            expected_rating = RatingSignal.STRONG_SELL

        passed = rating == expected_rating
        results.append(EngineTestResult(
            function_name="get_analyst_rating()",
            input_symbol=symbol,
            expected=expected_rating.value,
            actual=rating.value,
            passed=passed,
            message=f"Rating: {rating.value} (expected: {expected_rating.value} from rec_mean={expected_rec:.2f})"
        ))
    else:
        results.append(EngineTestResult(
            function_name="get_analyst_rating()",
            input_symbol=symbol,
            expected="N/A",
            actual=rating.value,
            passed=True,  # Can't validate without ground truth
            message=f"Rating: {rating.value} (no ground truth to compare)"
        ))

    # Test 5: evaluate_fundamentals()
    score = evaluate_fundamentals(fundamental)
    # Score should be a FundamentalScore object with valid values
    passed = (
        score is not None and
        0 <= score.score <= 100 and
        score.rating is not None
    )
    results.append(EngineTestResult(
        function_name="evaluate_fundamentals()",
        input_symbol=symbol,
        expected="FundamentalScore with valid score (0-100)",
        actual=f"score={score.score:.1f}, rating={score.rating.value}" if score else "None",
        passed=passed,
        message=f"Score: {score.score:.1f}/100, Rating: {score.rating.value}" if score else "Failed to evaluate"
    ))

    # Test 6: is_fundamentally_strong()
    is_strong = is_fundamentally_strong(fundamental)
    # This should return a boolean based on score >= 65
    expected_strong = score.score >= 65.0 if score else False
    passed = is_strong == expected_strong
    results.append(EngineTestResult(
        function_name="is_fundamentally_strong()",
        input_symbol=symbol,
        expected=expected_strong,
        actual=is_strong,
        passed=passed,
        message=f"Is strong: {is_strong} (score={score.score:.1f}, threshold=65)"
    ))

    return results


def print_engine_report(symbol: str, results: list[EngineTestResult]) -> None:
    """Print engine layer test results."""
    print(f"\n{'='*80}")
    print(f"=== Engine Layer Tests for {symbol} ===")
    print("=" * 80)
    print(f"{'Function':<30} | {'Status':<8} | {'Details'}")
    print("-" * 80)

    passed_count = 0
    for result in results:
        if result.passed:
            status = "\033[92mPASS\033[0m"
            passed_count += 1
        else:
            status = "\033[91mFAIL\033[0m"

        print(f"{result.function_name:<30} | {status:<8} | {result.message}")

    print("-" * 80)
    print(f"Summary: {passed_count}/{len(results)} tests passed")
    return passed_count, len(results)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Verify fundamental data accuracy")
    parser.add_argument(
        "--provider",
        choices=["yahoo", "futu", "ibkr", "unified"],
        default="unified",
        help="Provider to test (default: unified)"
    )
    parser.add_argument(
        "--all-providers",
        action="store_true",
        help="Test all available providers"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Symbols to test (default: all ground truth symbols)"
    )
    parser.add_argument(
        "--engine-only",
        action="store_true",
        help="Only run engine layer tests (skip provider comparison)"
    )
    parser.add_argument(
        "--skip-engine",
        action="store_true",
        help="Skip engine layer tests"
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Fundamental Data Verification Test")
    print("=" * 80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Tolerance: 5% (default), 10% (volatile fields)")

    symbols = args.symbols if args.symbols else list(GROUND_TRUTH.keys())
    print(f"Symbols to verify: {symbols}")

    # Determine providers to test
    if args.all_providers:
        print("\nChecking provider availability...")
        availability = test_provider_availability()
        providers_to_test = [p for p, avail in availability.items() if avail]
        print(f"Available providers: {providers_to_test}")
        unavailable = [p for p, avail in availability.items() if not avail]
        if unavailable:
            print(f"Unavailable providers: {unavailable}")
    else:
        providers_to_test = [args.provider]

    all_reports = {}
    fundamentals_cache = {}  # Cache fundamental data for engine tests
    total_passed = 0
    total_tests = 0
    engine_rate = 0.0

    # =========================================================================
    # Phase 1: Data Layer (Provider) Tests
    # =========================================================================
    if not args.engine_only:
        print("\n" + "=" * 80)
        print("Phase 1: Data Layer (Provider) Tests")
        print("=" * 80)

        for provider_name in providers_to_test:
            print(f"\n{'='*80}")
            print(f"Testing Provider: {provider_name.upper()}")
            print("=" * 80)

            try:
                provider = get_provider(provider_name)

                # Handle context managers for Futu/IBKR
                if hasattr(provider, '__enter__'):
                    provider.__enter__()

                reports = []
                for symbol in symbols:
                    if symbol not in GROUND_TRUTH:
                        print(f"Warning: No ground truth for {symbol}, skipping")
                        continue
                    report = verify_symbol(symbol, provider)
                    reports.append(report)
                    print_report(report)

                    # Cache fundamental data for engine tests
                    fundamental = provider.get_fundamental(symbol)
                    if fundamental:
                        fundamentals_cache[symbol] = fundamental

                all_reports[provider_name] = reports

                if hasattr(provider, '__exit__'):
                    provider.__exit__(None, None, None)

            except Exception as e:
                print(f"Error testing {provider_name}: {e}")
                import traceback
                traceback.print_exc()
                continue

        # Save reports
        logs_dir = project_root / "logs"
        logs_dir.mkdir(exist_ok=True)

        # Combine all provider reports
        combined_reports = []
        for provider_name, reports in all_reports.items():
            for report in reports:
                report.source = f"{provider_name}:{report.source}"
                combined_reports.append(report)

        if combined_reports:
            saved_path = save_report(combined_reports, logs_dir)
            print(f"\n\033[94mReport saved to: {saved_path}\033[0m")

        # Print provider summary
        print("\n" + "=" * 80)
        print("=== Data Layer Summary ===")
        print("=" * 80)

        for provider_name, reports in all_reports.items():
            if reports:
                total_matched = sum(r.matched for r in reports)
                total_fields = sum(r.total_fields for r in reports)
                overall_rate = total_matched / total_fields * 100 if total_fields > 0 else 0
                print(f"{provider_name}: {overall_rate:.1f}% match rate ({total_matched}/{total_fields})")

        # List all different fields across all symbols
        diff_fields = []
        missing_fields = []
        for reports in all_reports.values():
            for report in reports:
                for comp in report.comparisons:
                    if comp.status == "DIFF":
                        diff_fields.append((report.symbol, comp.field, comp.diff_percent))
                    elif comp.status == "MISSING":
                        missing_fields.append((report.symbol, comp.field))

        if diff_fields:
            print("\nFields with significant differences:")
            for symbol, field, diff in diff_fields:
                print(f"  - {symbol}.{field}: {diff:+.2f}%")

        if missing_fields:
            print("\nFields missing from API:")
            for symbol, field in missing_fields:
                print(f"  - {symbol}.{field}")

    # =========================================================================
    # Phase 2: Engine Layer Tests
    # =========================================================================
    if not args.skip_engine:
        print("\n" + "=" * 80)
        print("Phase 2: Engine Layer Tests")
        print("=" * 80)

        # If engine-only, need to fetch fundamental data first
        if args.engine_only:
            print(f"\nFetching fundamental data using {args.provider} provider...")
            provider = get_provider(args.provider)
            if hasattr(provider, '__enter__'):
                provider.__enter__()

            for symbol in symbols:
                fundamental = provider.get_fundamental(symbol)
                if fundamental:
                    fundamentals_cache[symbol] = fundamental
                    print(f"  {symbol}: OK")
                else:
                    print(f"  {symbol}: FAILED to fetch")

            if hasattr(provider, '__exit__'):
                provider.__exit__(None, None, None)

        # Run engine layer tests
        total_passed = 0
        total_tests = 0

        for symbol in symbols:
            fundamental = fundamentals_cache.get(symbol)
            if fundamental is None:
                print(f"\n\033[93mSkipping engine tests for {symbol}: No fundamental data\033[0m")
                continue

            results = verify_engine_layer(symbol, fundamental)
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
            print("No engine tests executed (no fundamental data available)")

    # =========================================================================
    # Final Summary
    # =========================================================================
    print("\n" + "=" * 80)
    print("=== FINAL SUMMARY ===")
    print("=" * 80)
    if not args.engine_only and all_reports:
        for provider_name, reports in all_reports.items():
            if reports:
                total_matched = sum(r.matched for r in reports)
                total_fields = sum(r.total_fields for r in reports)
                overall_rate = total_matched / total_fields * 100 if total_fields > 0 else 0
                print(f"Data Layer ({provider_name}): {overall_rate:.1f}% match rate")
    if not args.skip_engine and total_tests > 0:
        print(f"Engine Layer: {total_passed}/{total_tests} tests passed ({engine_rate:.1f}%)")


if __name__ == "__main__":
    main()
