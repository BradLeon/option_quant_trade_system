#!/usr/bin/env python3
"""Validation script for ContractFilter - US and HK markets.

This script validates:
1. DTE and Delta range
2. Liquidity (Bid-Ask Spread, Open Interest, Volume)
3. Strategy metrics (Sharpe Annual, TGR, SAS, PREI)
4. Expected ROC, Annual ROC, Win Probability

Usage:
    python tests/business/screening/validate_contract_filter.py

    # US market only
    python tests/business/screening/validate_contract_filter.py --market us

    # Single symbol
    python tests/business/screening/validate_contract_filter.py --symbol NVDA
"""

import argparse
import logging
import os
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from pathlib import Path

import yaml

# Configure logging for debug mode
def setup_logging(debug: bool = False):
    """Setup logging with optional debug mode."""
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ib_insync").setLevel(logging.WARNING if not debug else logging.INFO)

from src.business.config.screening_config import ScreeningConfig
from src.business.screening.filters.contract_filter import ContractFilter
from src.business.screening.filters.underlying_filter import UnderlyingFilter
from src.business.screening.models import (
    ContractOpportunity,
    MarketType,
    UnderlyingScore,
)
from src.data.providers.unified_provider import UnifiedDataProvider


def print_header(title: str, char: str = "=") -> None:
    """Print section header."""
    width = 70
    print()
    print(char * width)
    print(f"  {title}")
    print(char * width)


def print_subheader(title: str) -> None:
    """Print subsection header."""
    print()
    print(f"--- {title} ---")


def status_icon(passed: bool) -> str:
    """Return icon for pass/fail status."""
    return "[PASS]" if passed else "[FAIL]"


def warn_icon() -> str:
    """Return warning icon."""
    return "[WARN]"


def format_value(value, fmt: str = ".2f", suffix: str = "") -> str:
    """Format a value or return N/A if None."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:{fmt}}{suffix}"
    return str(value)


def format_percent(value: float | None) -> str:
    """Format a decimal value as percentage (0.21 -> '21.0%')."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def load_stock_pools() -> dict:
    """Load stock pools from YAML config."""
    config_path = Path(__file__).parent.parent.parent.parent / "config" / "screening" / "stock_pools.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_symbols_for_market(market: str) -> list[str]:
    """Get symbol list for a market."""
    pools = load_stock_pools()

    if market == "us":
        us_pools = pools.get("us_pools", {})
        default_pool = pools.get("defaults", {}).get("us", "us_default")
        return us_pools.get(default_pool, {}).get("symbols", [])
    elif market == "hk":
        hk_pools = pools.get("hk_pools", {})
        default_pool = pools.get("defaults", {}).get("hk", "hk_default")
        return hk_pools.get(default_pool, {}).get("symbols", [])

    return []


def print_contract_summary(opp: ContractOpportunity, config: ScreeningConfig) -> None:
    """Print contract opportunity summary."""
    cf_config = config.contract_filter

    print()
    print(f"  Contract:         {opp.symbol} {opp.expiry} {opp.option_type.upper()}{opp.strike}")
    print()

    # DTE
    dte_min, dte_max = cf_config.dte_range
    dte_pass = dte_min <= opp.dte <= dte_max
    print(f"  DTE:              {opp.dte} days {status_icon(dte_pass)} ({dte_min}-{dte_max})")

    # Delta (配置使用 |Delta| 绝对值范围)
    delta_min, delta_max = cf_config.delta_range
    abs_delta = abs(opp.delta) if opp.delta is not None else None
    delta_pass = abs_delta is not None and delta_min <= abs_delta <= delta_max
    print(f"  Delta:            {format_value(opp.delta, '.3f')} (|Delta|={format_value(abs_delta, '.3f')}) {status_icon(delta_pass)} ({delta_min}-{delta_max})")

    print()

    # Liquidity
    liq_config = cf_config.liquidity
    spread = opp.bid_ask_spread
    spread_pass = spread is not None and spread <= liq_config.max_bid_ask_spread
    print(f"  Bid-Ask Spread:   {format_percent(spread)} {status_icon(spread_pass)} (<{liq_config.max_bid_ask_spread:.0%})")

    oi_pass = opp.open_interest is not None and opp.open_interest >= liq_config.min_open_interest
    print(f"  Open Interest:    {opp.open_interest or 'N/A'} {status_icon(oi_pass)} (>={liq_config.min_open_interest})")

    vol_pass = opp.volume is not None and opp.volume >= liq_config.min_volume
    vol_icon = status_icon(vol_pass) if vol_pass else warn_icon()
    print(f"  Volume:           {opp.volume or 'N/A'} {vol_icon} (>={liq_config.min_volume})")

    print()

    # Strategy Metrics
    met_config = cf_config.metrics

    # Expected ROC (P0)
    exp_roc_pass = opp.expected_roc is not None and opp.expected_roc > met_config.min_expected_roc
    print(f"  Expected ROC:     {format_percent(opp.expected_roc)} {status_icon(exp_roc_pass)} (>{met_config.min_expected_roc:.0%})")

    # Annual ROC (P2)
    ann_roc_pass = opp.annual_roc is not None and opp.annual_roc >= met_config.min_annual_roc
    ann_roc_icon = status_icon(ann_roc_pass) if ann_roc_pass else warn_icon()
    print(f"  Annual ROC:       {format_percent(opp.annual_roc)} {ann_roc_icon} (>={met_config.min_annual_roc:.0%})")

    # Sharpe Ratio Annual (P1) - 年化夏普比率
    sharpe_pass = opp.sharpe_ratio_annual is not None and opp.sharpe_ratio_annual >= met_config.min_sharpe_ratio
    print(f"  Sharpe (年化):    {format_value(opp.sharpe_ratio_annual, '.2f')} {status_icon(sharpe_pass)} (>={met_config.min_sharpe_ratio})")

    # TGR (P1)
    tgr_pass = opp.tgr is not None and opp.tgr >= met_config.min_tgr
    print(f"  TGR:              {format_value(opp.tgr, '.3f')} {status_icon(tgr_pass)} (>={met_config.min_tgr})")

    # Premium Rate (P1) - 费率
    rate_pass = opp.premium_rate is not None and opp.premium_rate >= met_config.min_premium_rate
    print(f"  费率:             {format_percent(opp.premium_rate)} {status_icon(rate_pass)} (>={met_config.min_premium_rate:.0%})")

    print()

    # Win Probability (P3)
    wp_pass = opp.win_probability is not None and opp.win_probability >= met_config.min_win_probability
    wp_icon = status_icon(wp_pass) if wp_pass else warn_icon()
    print(f"  Win Probability:  {format_percent(opp.win_probability)} {wp_icon} (>={met_config.min_win_probability:.0%})")

    # Theta/Premium (P3)
    tp_pass = opp.theta_premium_ratio is not None and opp.theta_premium_ratio >= met_config.min_theta_premium_ratio
    tp_icon = status_icon(tp_pass) if tp_pass else warn_icon()
    print(f"  Theta/Premium:    {format_percent(opp.theta_premium_ratio)}/day {tp_icon} (>={met_config.min_theta_premium_ratio:.0%})")

    # SAS (P2)
    sas_pass = opp.sas is not None and opp.sas >= met_config.min_sas
    sas_icon = status_icon(sas_pass) if sas_pass else warn_icon()
    print(f"  SAS:              {format_value(opp.sas, '.1f')} {sas_icon} (>={met_config.min_sas})")

    # Kelly (P3)
    kelly_pass = opp.kelly_fraction is None or opp.kelly_fraction <= met_config.max_kelly_fraction
    kelly_icon = status_icon(kelly_pass) if kelly_pass else warn_icon()
    print(f"  Kelly Fraction:   {format_percent(opp.kelly_fraction)} {kelly_icon} (<={met_config.max_kelly_fraction:.0%})")

    print()
    print("-" * 50)
    print(f"  Result:           {status_icon(True)} PASSED")

    # 通过原因和推荐仓位
    if opp.pass_reasons:
        print()
        print("  通过原因:")
        print(f"    {', '.join(opp.pass_reasons)}")

    if opp.recommended_position is not None:
        print()
        print(f"  📊 推荐仓位:      {opp.recommended_position:.1%} (1/4 Kelly)")

    if opp.warnings:
        print()
        print("  Warnings (P2/P3):")
        for warning in opp.warnings:
            print(f"    - {warning}")


def print_contract_brief(opp: ContractOpportunity) -> None:
    """Print brief contract info for rejected/all contracts display."""
    status = "[PASS]" if opp.passed else "[FAIL]"

    # 完整合约标识: 标的 | 方向 | 类型 | 行权价 | 到期日 | 期权价格
    direction = "Short"  # 目前筛选策略都是卖方（Short Put / Short Call）
    price_str = f"${opp.mid_price:.2f}" if opp.mid_price else "N/A"
    contract_id = (
        f"{opp.symbol} | {direction} {opp.option_type.upper()} | "
        f"K={opp.strike} | Exp={opp.expiry} | DTE={opp.dte} | Price={price_str}"
    )

    # Core metrics
    delta_str = f"Delta={opp.delta:.3f}" if opp.delta is not None else "Delta=N/A"
    iv_str = f"IV={opp.iv:.1%}" if opp.iv is not None else "IV=N/A"
    oi_str = f"OI={opp.open_interest}" if opp.open_interest is not None else "OI=N/A"
    vol_str = f"Vol={opp.volume}" if opp.volume is not None else "Vol=N/A"

    # Strategy metrics (使用业务过滤检查的指标)
    tgr_str = f"TGR={opp.tgr:.3f}" if opp.tgr is not None else "TGR=N/A"
    sharpe_str = f"Sharpe(年化)={opp.sharpe_ratio_annual:.2f}" if opp.sharpe_ratio_annual is not None else "Sharpe(年化)=N/A"
    roc_str = f"E[ROC]={opp.expected_roc:.1%}" if opp.expected_roc is not None else "E[ROC]=N/A"
    rate_str = f"费率={opp.premium_rate:.2%}" if opp.premium_rate is not None else "费率=N/A"

    print(f"  {status} {contract_id}")
    print(f"         {delta_str} | {iv_str} | {oi_str} | {vol_str}")
    print(f"         {tgr_str} | {sharpe_str} | {roc_str} | {rate_str}")

    if not opp.passed and opp.disqualify_reasons:
        print(f"         Rejected: {'; '.join(opp.disqualify_reasons)}")

    if opp.passed:
        # 显示通过原因和推荐仓位
        if opp.pass_reasons:
            print(f"         ✓ Pass: {', '.join(opp.pass_reasons)}")
        if opp.recommended_position is not None:
            print(f"         📊 推荐仓位: {opp.recommended_position:.1%} (1/4 Kelly)")
        if opp.warnings:
            print(f"         ⚠️ Warnings: {'; '.join(opp.warnings[:2])}")  # Show first 2 warnings


def print_evaluation_summary(all_contracts: list[ContractOpportunity]) -> None:
    """Print evaluation summary with rejection breakdown."""
    passed = [o for o in all_contracts if o.passed]
    rejected = [o for o in all_contracts if not o.passed]

    print(f"\n  --- Evaluation Summary ---")
    print(f"  Total evaluated: {len(all_contracts)}")
    print(f"  Passed: {len(passed)}")
    print(f"  Rejected: {len(rejected)}")

    if rejected:
        # Count rejection reasons
        reason_counts: dict[str, int] = {}
        for opp in rejected:
            for reason in opp.disqualify_reasons:
                # Extract reason category (e.g., "[P1] Delta" -> "Delta")
                if "]" in reason:
                    category = reason.split("]")[1].strip().split("=")[0].split(" ")[0]
                else:
                    category = reason.split("=")[0].strip()
                reason_counts[category] = reason_counts.get(category, 0) + 1

        print(f"\n  Rejection breakdown:")
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count}")


def validate_contracts(
    symbol: str,
    market_type: MarketType,
    config: ScreeningConfig,
    provider: UnifiedDataProvider,
    underlying_filter: UnderlyingFilter,
    contract_filter: ContractFilter,
    max_display: int = 3,
    debug: bool = False,
) -> dict:
    """Validate contracts for a single underlying.

    简化流程：
    1. 评估标的
    2. 调用 contract_filter.evaluate()（内部会获取期权链和报价）
    3. 显示结果
    """
    print_header(f"CONTRACT VALIDATION - {symbol}")

    # Step 1: Evaluate underlying
    print("\n  Step 1: Evaluating underlying...")
    underlying_score = underlying_filter.evaluate_single(symbol, market_type)

    if not underlying_score.passed:
        print(f"\n  Underlying FAILED: {underlying_score.disqualify_reasons}")
        return {"symbol": symbol, "passed": False, "opportunities": []}

    print(f"  Underlying PASSED (IV Rank={format_value(underlying_score.iv_rank, '.1f')}%)")
    print(f"  Current Price: ${format_value(underlying_score.current_price, '.2f')}")

    # Step 2: Evaluate contracts using contract_filter
    # contract_filter 内部会自动获取期权链和报价
    # 重构后：一次调用同时评估 PUT 和 CALL，避免重复获取期权链
    print("\n  Step 2: Evaluating contracts (PUT + CALL)...")

    # Enable detailed evaluation logging
    import logging
    cf_logger = logging.getLogger("src.business.screening.filters.contract_filter")
    original_level = cf_logger.level
    cf_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # 一次性评估所有合约（PUT 和 CALL）
    all_contracts = contract_filter.evaluate(
        [underlying_score],
        option_types=None,  # None = 评估 PUT 和 CALL
        return_rejected=True,  # Get all evaluated contracts
    )

    # Restore logging level
    cf_logger.setLevel(original_level)

    # 分类统计
    all_put_contracts = [o for o in all_contracts if o.option_type == "put"]
    all_call_contracts = [o for o in all_contracts if o.option_type == "call"]
    passed_contracts = [o for o in all_contracts if o.passed]
    rejected_contracts = [o for o in all_contracts if not o.passed]

    # Show evaluation summary with rejection breakdown
    put_passed = sum(1 for o in all_put_contracts if o.passed)
    call_passed = sum(1 for o in all_call_contracts if o.passed)

    print(f"\n  Evaluation Results:")
    print(f"    PUT: {len(all_put_contracts)} evaluated, {put_passed} passed")
    print(f"    CALL: {len(all_call_contracts)} evaluated, {call_passed} passed")
    print(f"    Total: {len(all_contracts)} evaluated, {len(passed_contracts)} passed")

    # Print all contracts (brief format) - 不省略，全部显示
    if all_contracts:
        print_subheader(f"All Evaluated Contracts ({len(all_contracts)})")
        for opp in all_contracts:
            print_contract_brief(opp)
            print()

    # Print evaluation summary with rejection breakdown
    print_evaluation_summary(all_contracts)

    # Display detailed info for passed contracts
    if passed_contracts:
        print_subheader(f"Qualified Contracts ({len(passed_contracts)})")
        for i, opp in enumerate(passed_contracts[:max_display]):
            print_subheader(f"Contract {i+1}/{len(passed_contracts)}")
            print_contract_summary(opp, config)

    return {
        "symbol": symbol,
        "passed": len(passed_contracts) > 0,
        "opportunities": passed_contracts,
        "all_contracts": all_contracts,
        "underlying_score": underlying_score,
    }


def main():
    """Run contract filter validation."""
    parser = argparse.ArgumentParser(description="Validate ContractFilter for US and HK markets")
    parser.add_argument(
        "--market",
        choices=["us", "hk", "both"],
        default="us",
        help="Market to validate (default: us)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Validate specific symbol only"
    )
    parser.add_argument(
        "--max-display",
        type=int,
        default=3,
        help="Max contracts to display per symbol (default: 3)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()

    # Setup logging based on debug flag
    setup_logging(args.debug)

    print()
    print("=" * 70)
    print("  CONTRACT FILTER VALIDATION")
    print(f"  Date: {date.today()}")
    if args.debug:
        print("  Mode: DEBUG")
    print("=" * 70)

    # Load config and create filters
    config = ScreeningConfig()
    provider = UnifiedDataProvider()
    underlying_filter = UnderlyingFilter(config, provider)
    contract_filter = ContractFilter(config, provider)

    results: dict[str, list[dict]] = {"US": [], "HK": []}

    # Single symbol mode
    if args.symbol:
        symbol = args.symbol.upper()
        # Detect market type
        if symbol.endswith(".HK"):
            market_type = MarketType.HK
            market_key = "HK"
        else:
            market_type = MarketType.US
            market_key = "US"

        result = validate_contracts(
            symbol, market_type, config, provider,
            underlying_filter, contract_filter, args.max_display, args.debug
        )
        results[market_key].append(result)
    else:
        # Validate US market
        if args.market in ["us", "both"]:
            us_symbols = get_symbols_for_market("us")[:3]  # Limit to 3 for speed
            print_header(f"US MARKET - {len(us_symbols)} symbols")

            for symbol in us_symbols:
                try:
                    result = validate_contracts(
                        symbol, MarketType.US, config, provider,
                        underlying_filter, contract_filter, args.max_display, args.debug
                    )
                    results["US"].append(result)
                except Exception as e:
                    print(f"\n[ERROR] Validation failed for {symbol}: {e}")
                    import traceback
                    traceback.print_exc()

        # Validate HK market
        if args.market in ["hk", "both"]:
            hk_symbols = get_symbols_for_market("hk")[:2]  # Limit to 2 for speed
            print_header(f"HK MARKET - {len(hk_symbols)} symbols")

            for symbol in hk_symbols:
                try:
                    result = validate_contracts(
                        symbol, MarketType.HK, config, provider,
                        underlying_filter, contract_filter, args.max_display, args.debug
                    )
                    results["HK"].append(result)
                except Exception as e:
                    print(f"\n[ERROR] Validation failed for {symbol}: {e}")
                    import traceback
                    traceback.print_exc()

    # Final summary
    print_header("FINAL SUMMARY")

    total_opportunities = 0
    for market, market_results in results.items():
        if not market_results:
            continue

        symbols_with_opps = sum(1 for r in market_results if r["passed"])
        total_opps = sum(len(r.get("opportunities", [])) for r in market_results)
        total_opportunities += total_opps

        print(f"\n  {market} Market:")
        print(f"    Symbols Evaluated:  {len(market_results)}")
        print(f"    Symbols with Opps:  {symbols_with_opps}")
        print(f"    Total Opportunities: {total_opps}")

        if symbols_with_opps > 0:
            print(f"    Symbols: {', '.join(r['symbol'] for r in market_results if r['passed'])}")

    print()
    print("=" * 70)
    print(f"  Validation Complete - {total_opportunities} total opportunities found")
    print("=" * 70)

    return 0 if total_opportunities > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
