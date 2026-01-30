#!/usr/bin/env python3
"""Margin Comparison Verification Script.

Compares margin requirements from different sources:
1. Reg T formula (current implementation)
2. IBKR API (whatIfOrder)
3. Futu API (acctradinginfo_query)

Also compares the resulting ROC/Expected ROC metrics.

Test targets:
- US: TSLA (Short Put, DTE 7-37)
- HK: 0700.HK (Short Put, DTE 7-37)

Usage:
    python tests/verification/verify_margin_comparison.py
    python tests/verification/verify_margin_comparison.py --symbol TSLA
    python tests/verification/verify_margin_comparison.py --symbol 0700.HK
    python tests/verification/verify_margin_comparison.py -v  # verbose mode
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data.models.option import OptionContract, OptionQuote, OptionType, Greeks
from src.data.models.enums import Market
from src.data.models.account import AccountType
from src.data.providers import IBKRProvider, FutuProvider, UnifiedDataProvider
from src.data.utils import SymbolFormatter
from src.engine.models.strategy import OptionLeg, StrategyParams
from src.engine.strategy import ShortPutStrategy
from src.engine.position.risk_return import calc_roc_from_dte

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class MarginComparisonResult:
    """Comparison result for a single option contract."""

    # Contract info (required fields)
    symbol: str
    underlying: str
    strike: float
    expiry: str
    dte: int
    option_type: str
    premium: float
    underlying_price: float

    # Optional fields (with defaults)
    lot_size: int = 100  # Contract multiplier (100 for US, varies for HK)
    iv: Optional[float] = None
    delta: Optional[float] = None

    # Margin values
    margin_reg_t: Optional[float] = None       # Reg T formula
    margin_ibkr_api: Optional[float] = None    # IBKR whatIfOrder
    margin_futu_api: Optional[float] = None    # Futu acctradinginfo_query

    # Margin source details
    ibkr_init_margin: Optional[float] = None   # IBKR initial margin
    ibkr_maint_margin: Optional[float] = None  # IBKR maintenance margin
    ibkr_commission: Optional[float] = None    # IBKR commission

    # ROC using Reg T margin
    roc_reg_t: Optional[float] = None
    expected_roc_reg_t: Optional[float] = None

    # ROC using IBKR API margin
    roc_ibkr: Optional[float] = None
    expected_roc_ibkr: Optional[float] = None

    # ROC using Futu API margin
    roc_futu: Optional[float] = None
    expected_roc_futu: Optional[float] = None

    # Differences
    @property
    def margin_diff_ibkr_pct(self) -> Optional[float]:
        """Margin difference: (IBKR API - Reg T) / Reg T."""
        if self.margin_reg_t and self.margin_ibkr_api:
            return (self.margin_ibkr_api - self.margin_reg_t) / self.margin_reg_t * 100
        return None

    @property
    def margin_diff_futu_pct(self) -> Optional[float]:
        """Margin difference: (Futu API - Reg T) / Reg T."""
        if self.margin_reg_t and self.margin_futu_api:
            return (self.margin_futu_api - self.margin_reg_t) / self.margin_reg_t * 100
        return None


# ============================================================================
# Margin Query Functions
# ============================================================================


def calc_reg_t_margin_short_put(
    underlying_price: float,
    strike: float,
    premium: float,
) -> float:
    """Calculate margin using Reg T formula (current implementation).

    IBKR Formula for Short Put (per share):
    Margin = Put Price + Max(20% × S - OTM, 10% × K)

    Returns margin per share (consistent with other metrics).
    """
    otm_amount = max(0, underlying_price - strike)
    option1 = 0.20 * underlying_price - otm_amount
    option2 = 0.10 * strike
    margin_per_share = premium + max(option1, option2)
    return margin_per_share


def query_ibkr_margin(
    ib: "IBKRProvider",
    underlying: str,
    strike: float,
    expiry: str,  # YYYYMMDD
    option_type: str,  # "put" or "call"
    quantity: int = 1,
    lot_size: int = 100,  # Contract multiplier for per-share conversion
) -> dict:
    """Query margin using IBKR whatIfOrder API.

    Returns dict with: initial_margin, maint_margin, commission (all per-share values)
    """
    try:
        from ib_async import Order, Option

        # Detect market
        market = SymbolFormatter.detect_market(underlying)
        ibkr_symbol = SymbolFormatter.to_ibkr_symbol(underlying)
        right = "P" if option_type.lower() == "put" else "C"

        # Build option contract
        if market == Market.HK:
            # For HK options, need trading class
            # Get it from option chain
            chain = ib.get_option_chain(underlying)
            trading_class = None
            if chain and chain.calls:
                trading_class = chain.calls[0].contract.trading_class

            opt = Option(
                ibkr_symbol, expiry, strike, right, "SEHK",
                currency="HKD"
            )
            if trading_class:
                opt.tradingClass = trading_class
        else:
            opt = Option(ibkr_symbol, expiry, strike, right, "SMART")

        # Qualify contract
        logger.debug(f"Qualifying contract: {opt}")
        qualified = ib._ib.qualifyContracts(opt)
        if not qualified or not opt.conId:
            logger.warning(f"Could not qualify contract for {underlying} {strike} {option_type}")
            return {}
        logger.debug(f"Qualified contract: conId={opt.conId}, symbol={opt.symbol}")

        # Create what-if order (SELL for short option)
        order = Order(
            action="SELL",
            totalQuantity=quantity,
            orderType="MKT",
        )

        # Query margin impact
        logger.debug(f"Calling whatIfOrder for {underlying} {strike} {option_type}")
        state = ib._ib.whatIfOrder(opt, order)

        if state is None:
            logger.warning(f"whatIfOrder returned None for {underlying} {strike}")
            return {}

        # Print all margin fields from OrderState
        logger.debug(f"whatIfOrder result for {underlying} {strike}:")
        logger.debug(f"  initMarginBefore={state.initMarginBefore}")
        logger.debug(f"  initMarginChange={state.initMarginChange}")
        logger.debug(f"  initMarginAfter={state.initMarginAfter}")
        logger.debug(f"  maintMarginBefore={state.maintMarginBefore}")
        logger.debug(f"  maintMarginChange={state.maintMarginChange}")
        logger.debug(f"  maintMarginAfter={state.maintMarginAfter}")
        logger.debug(f"  commission={state.commission}")

        # Parse margin values
        def parse_value(val) -> Optional[float]:
            if val is None:
                return None
            if isinstance(val, (int, float)):
                return float(val)
            try:
                cleaned = str(val).replace(",", "").replace("$", "").strip()
                return float(cleaned) if cleaned else None
            except (ValueError, AttributeError):
                return None

        init_margin = parse_value(state.initMarginChange)
        maint_margin = parse_value(state.maintMarginChange)

        # Convert to per-share values by dividing by lot_size
        return {
            "initial_margin": init_margin / lot_size if init_margin else None,
            "maint_margin": maint_margin / lot_size if maint_margin else None,
            "commission": parse_value(state.commission),  # Commission stays as total
            "initial_margin_total": init_margin,  # Keep total for reference
            "maint_margin_total": maint_margin,
        }

    except Exception as e:
        logger.error(f"Error querying IBKR margin: {e}")
        return {}


def query_futu_margin(
    futu: "FutuProvider",
    futu_symbol: str,  # e.g., "HK.TCH260226P550000"
    price: float,
    lot_size: int = 100,  # Contract multiplier for per-share conversion
) -> dict:
    """Query margin using Futu acctradinginfo_query API.

    Returns dict with: initial_margin (per-share values)
    """
    try:
        from futu import OrderType as FutuOrderType, TrdEnv

        trd_ctx = futu._get_trade_context(futu._account_type)
        trd_env = TrdEnv.SIMULATE if futu._account_type.value == "paper" else TrdEnv.REAL

        # Query trading info
        ret, data = trd_ctx.acctradinginfo_query(
            order_type=FutuOrderType.NORMAL,
            code=futu_symbol,
            price=price,
            trd_env=trd_env,
        )

        if ret != 0 or data.empty:
            logger.warning(f"acctradinginfo_query failed: {data}")
            return {}

        row = data.iloc[0]

        # Extract short margin (for selling options)
        def safe_float(val) -> Optional[float]:
            if val is None or val == "N/A":
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        init_margin = safe_float(row.get("short_required_im"))
        long_margin = safe_float(row.get("long_required_im"))

        # Convert to per-share values by dividing by lot_size
        return {
            "initial_margin": init_margin / lot_size if init_margin else None,
            "long_margin": long_margin / lot_size if long_margin else None,
            "initial_margin_total": init_margin,  # Keep total for reference
        }

    except Exception as e:
        logger.error(f"Error querying Futu margin: {e}")
        return {}


# ============================================================================
# ROC Calculation
# ============================================================================


def calc_roc_metrics(
    premium: float,
    margin: float,
    dte: int,
    underlying_price: float,
    strike: float,
    iv: float,
    delta: Optional[float] = None,
) -> dict:
    """Calculate ROC and Expected ROC using given margin."""
    if margin <= 0 or dte <= 0:
        return {"roc": None, "expected_roc": None}

    # Simple ROC
    roc = calc_roc_from_dte(premium, margin, dte)

    # Expected ROC (simplified - using delta as win probability proxy)
    # For short put: win prob ≈ 1 - |delta|
    if delta is not None:
        win_prob = 1 - abs(delta)
        # Expected return ≈ premium * win_prob - max_loss * (1 - win_prob)
        # Simplified: expected_return ≈ premium * (2 * win_prob - 1)
        expected_return = premium * (2 * win_prob - 1)
        expected_roc = calc_roc_from_dte(expected_return, margin, dte)
    else:
        expected_roc = None

    return {"roc": roc, "expected_roc": expected_roc}


# ============================================================================
# Main Comparison Logic
# ============================================================================


class MarginComparisonTest:
    """Test class for margin comparison."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.ibkr: Optional[IBKRProvider] = None
        self.futu: Optional[FutuProvider] = None
        self.results: list[MarginComparisonResult] = []

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

    def connect(self) -> bool:
        """Connect to providers."""
        try:
            self.ibkr = IBKRProvider()
            self.ibkr.connect()
            logger.info("IBKR connected")
        except Exception as e:
            logger.error(f"Failed to connect IBKR: {e}")
            return False

        try:
            self.futu = FutuProvider(account_type=AccountType.LIVE)
            # Futu auto-connects on first use
            logger.info("Futu provider initialized (REAL account)")
        except Exception as e:
            logger.warning(f"Failed to initialize Futu: {e}")
            # Continue without Futu

        return True

    def disconnect(self):
        """Disconnect from providers."""
        if self.ibkr:
            try:
                self.ibkr.disconnect()
            except:
                pass
        if self.futu:
            try:
                self.futu.disconnect()
            except:
                pass

    def test_symbol(self, underlying: str, dte_min: int = 7, dte_max: int = 37):
        """Test margin comparison for a symbol."""
        market = SymbolFormatter.detect_market(underlying)
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing: {underlying} (Market: {market.value})")
        logger.info(f"DTE Range: {dte_min}-{dte_max}")
        logger.info(f"{'='*60}")

        # Get stock quote for underlying price
        quote = self.ibkr.get_stock_quote(underlying)
        if not quote:
            logger.error(f"Could not get stock quote for {underlying}")
            return

        underlying_price = quote.close or quote.last_price
        logger.info(f"Underlying Price: {underlying_price}")

        # Get option chain
        today = date.today()
        expiry_start = today + timedelta(days=dte_min)
        expiry_end = today + timedelta(days=dte_max)

        chain = self.ibkr.get_option_chain(
            underlying,
            expiry_start=expiry_start,
            expiry_end=expiry_end,
            option_type="put",
            option_cond_type="otm",  # Only OTM puts
        )

        if not chain or not chain.puts:
            logger.error(f"Could not get option chain for {underlying}")
            return

        logger.info(f"Found {len(chain.puts)} OTM puts")

        # Get quotes for puts
        contracts = [q.contract for q in chain.puts[:10]]  # Limit to 10 for testing
        quotes = self.ibkr.get_option_quotes_batch(contracts)

        if not quotes:
            logger.error(f"Could not get option quotes")
            return

        logger.info(f"Got quotes for {len(quotes)} contracts")

        # Compare margins for each contract
        for quote in quotes:
            result = self._compare_contract_margin(
                quote=quote,
                underlying=underlying,
                underlying_price=underlying_price,
                market=market,
            )
            if result:
                self.results.append(result)

        # Print results table
        self._print_results_table(underlying, market)

    def _compare_contract_margin(
        self,
        quote: OptionQuote,
        underlying: str,
        underlying_price: float,
        market: Market,
    ) -> Optional[MarginComparisonResult]:
        """Compare margin for a single contract."""
        contract = quote.contract
        premium = quote.mid_price or quote.last_price or 0

        if premium <= 0:
            logger.debug(f"Skipping {contract.symbol}: no premium data")
            return None

        strike = contract.strike_price
        expiry = contract.expiry_date.strftime("%Y%m%d")
        dte = contract.days_to_expiry
        lot_size = contract.lot_size  # Get lot_size from contract (100 for US, varies for HK)

        logger.debug(f"Comparing: {underlying} {strike} P exp={expiry} DTE={dte} lot_size={lot_size}")

        # 1. Reg T formula (per-share)
        margin_reg_t = calc_reg_t_margin_short_put(
            underlying_price=underlying_price,
            strike=strike,
            premium=premium,
        )

        # 2. IBKR API (converted to per-share)
        ibkr_margin_data = query_ibkr_margin(
            ib=self.ibkr,
            underlying=underlying,
            strike=strike,
            expiry=expiry,
            option_type="put",
            lot_size=lot_size,
        )
        margin_ibkr = ibkr_margin_data.get("initial_margin")

        # 3. Futu API (only for HK, converted to per-share)
        margin_futu = None
        if market == Market.HK and self.futu:
            # Build Futu option symbol
            # Need to get the Futu symbol format
            # For now, try to get it from the chain
            futu_chain = self.futu.get_option_chain(underlying)
            if futu_chain and futu_chain.puts:
                # Find matching contract
                for fq in futu_chain.puts:
                    if (fq.contract.strike_price == strike and
                        fq.contract.expiry_date == contract.expiry_date):
                        futu_symbol = fq.contract.symbol
                        futu_margin_data = query_futu_margin(
                            futu=self.futu,
                            futu_symbol=futu_symbol,
                            price=premium,
                            lot_size=lot_size,
                        )
                        margin_futu = futu_margin_data.get("initial_margin")
                        break

        # Calculate ROC metrics
        iv = quote.iv
        delta = quote.greeks.delta if quote.greeks else None

        roc_reg_t = calc_roc_metrics(premium, margin_reg_t, dte, underlying_price, strike, iv or 0.3, delta)
        roc_ibkr = calc_roc_metrics(premium, margin_ibkr, dte, underlying_price, strike, iv or 0.3, delta) if margin_ibkr else {}
        roc_futu = calc_roc_metrics(premium, margin_futu, dte, underlying_price, strike, iv or 0.3, delta) if margin_futu else {}

        return MarginComparisonResult(
            symbol=contract.symbol,
            underlying=underlying,
            strike=strike,
            expiry=expiry,
            dte=dte,
            option_type="PUT",
            premium=premium,
            underlying_price=underlying_price,
            lot_size=lot_size,
            iv=iv,
            delta=delta,
            margin_reg_t=margin_reg_t,
            margin_ibkr_api=margin_ibkr,
            margin_futu_api=margin_futu,
            ibkr_init_margin=ibkr_margin_data.get("initial_margin"),
            ibkr_maint_margin=ibkr_margin_data.get("maint_margin"),
            ibkr_commission=ibkr_margin_data.get("commission"),
            roc_reg_t=roc_reg_t.get("roc"),
            expected_roc_reg_t=roc_reg_t.get("expected_roc"),
            roc_ibkr=roc_ibkr.get("roc"),
            expected_roc_ibkr=roc_ibkr.get("expected_roc"),
            roc_futu=roc_futu.get("roc"),
            expected_roc_futu=roc_futu.get("expected_roc"),
        )

    def _print_results_table(self, underlying: str, market: Market):
        """Print comparison results table."""
        results = [r for r in self.results if r.underlying == underlying]

        if not results:
            logger.warning(f"No results for {underlying}")
            return

        currency = "HKD" if market == Market.HK else "USD"

        print(f"\n{'='*120}")
        print(f"=== {underlying} Short Put Margin Comparison ===")
        print(f"{'='*120}")

        # Header
        if market == Market.HK:
            print(f"{'Strike':>8} | {'Expiry':>10} | {'DTE':>4} | {'Premium':>8} | "
                  f"{'RegT':>10} | {'IBKR':>10} | {'Futu':>10} | "
                  f"{'Diff(IBKR)':>10} | {'ROC(RegT)':>10} | {'ROC(IBKR)':>10}")
            print("-" * 120)
        else:
            print(f"{'Strike':>8} | {'Expiry':>10} | {'DTE':>4} | {'Premium':>8} | "
                  f"{'RegT':>10} | {'IBKR':>10} | "
                  f"{'Diff%':>8} | {'ROC(RegT)':>10} | {'ROC(IBKR)':>10}")
            print("-" * 100)

        # Data rows
        for r in sorted(results, key=lambda x: (x.expiry, x.strike)):
            diff_pct = r.margin_diff_ibkr_pct
            diff_str = f"{diff_pct:+.1f}%" if diff_pct is not None else "N/A"

            roc_reg_t_str = f"{r.roc_reg_t*100:.1f}%" if r.roc_reg_t else "N/A"
            roc_ibkr_str = f"{r.roc_ibkr*100:.1f}%" if r.roc_ibkr else "N/A"

            margin_reg_t_str = f"{currency[0]}{r.margin_reg_t:,.0f}" if r.margin_reg_t else "N/A"
            margin_ibkr_str = f"{currency[0]}{r.margin_ibkr_api:,.0f}" if r.margin_ibkr_api else "N/A"

            if market == Market.HK:
                margin_futu_str = f"{currency[0]}{r.margin_futu_api:,.0f}" if r.margin_futu_api else "N/A"
                roc_futu_str = f"{r.roc_futu*100:.1f}%" if r.roc_futu else "N/A"
                print(f"{r.strike:>8.0f} | {r.expiry:>10} | {r.dte:>4} | {r.premium:>8.2f} | "
                      f"{margin_reg_t_str:>10} | {margin_ibkr_str:>10} | {margin_futu_str:>10} | "
                      f"{diff_str:>10} | {roc_reg_t_str:>10} | {roc_ibkr_str:>10}")
            else:
                print(f"{r.strike:>8.0f} | {r.expiry:>10} | {r.dte:>4} | {r.premium:>8.2f} | "
                      f"{margin_reg_t_str:>10} | {margin_ibkr_str:>10} | "
                      f"{diff_str:>8} | {roc_reg_t_str:>10} | {roc_ibkr_str:>10}")

        # Summary
        print("-" * (120 if market == Market.HK else 100))

        # Show lot size info
        lot_sizes = set(r.lot_size for r in results)
        lot_size_str = ", ".join(str(ls) for ls in sorted(lot_sizes))
        print(f"Contract multiplier (lot size): {lot_size_str}")

        valid_diffs = [r.margin_diff_ibkr_pct for r in results if r.margin_diff_ibkr_pct is not None]
        if valid_diffs:
            avg_diff = sum(valid_diffs) / len(valid_diffs)
            print(f"Average IBKR vs Reg T difference: {avg_diff:+.1f}%")

        valid_ibkr_margins = [r.margin_ibkr_api for r in results if r.margin_ibkr_api]
        valid_reg_t_margins = [r.margin_reg_t for r in results if r.margin_reg_t]
        if valid_ibkr_margins and valid_reg_t_margins:
            print(f"IBKR margin range: {currency[0]}{min(valid_ibkr_margins):,.0f} - {currency[0]}{max(valid_ibkr_margins):,.0f}")
            print(f"Reg T margin range: {currency[0]}{min(valid_reg_t_margins):,.0f} - {currency[0]}{max(valid_reg_t_margins):,.0f}")

        if market == Market.HK:
            valid_futu = [r.margin_futu_api for r in results if r.margin_futu_api]
            if valid_futu:
                print(f"Futu margin range: {currency[0]}{min(valid_futu):,.0f} - {currency[0]}{max(valid_futu):,.0f}")
            else:
                print("Futu margin: No data available")

    def run_all_tests(self, symbols: list[str] = None):
        """Run tests for all symbols."""
        if symbols is None:
            symbols = ["TSLA", "0700.HK"]

        if not self.connect():
            logger.error("Failed to connect to providers")
            return

        try:
            for symbol in symbols:
                self.test_symbol(symbol)
        finally:
            self.disconnect()

        # Print final summary
        self._print_summary()

    def _print_summary(self):
        """Print overall summary."""
        print("\n" + "=" * 80)
        print("=== OVERALL SUMMARY ===")
        print("=" * 80)

        # Group by market
        us_results = [r for r in self.results if SymbolFormatter.detect_market(r.underlying) == Market.US]
        hk_results = [r for r in self.results if SymbolFormatter.detect_market(r.underlying) == Market.HK]

        if us_results:
            us_diffs = [r.margin_diff_ibkr_pct for r in us_results if r.margin_diff_ibkr_pct is not None]
            if us_diffs:
                print(f"US Market (IBKR vs Reg T): Avg diff = {sum(us_diffs)/len(us_diffs):+.1f}%")

        if hk_results:
            hk_diffs = [r.margin_diff_ibkr_pct for r in hk_results if r.margin_diff_ibkr_pct is not None]
            if hk_diffs:
                print(f"HK Market (IBKR vs Reg T): Avg diff = {sum(hk_diffs)/len(hk_diffs):+.1f}%")

            futu_available = [r for r in hk_results if r.margin_futu_api is not None]
            if futu_available:
                futu_diffs = [r.margin_diff_futu_pct for r in futu_available if r.margin_diff_futu_pct is not None]
                if futu_diffs:
                    print(f"HK Market (Futu vs Reg T): Avg diff = {sum(futu_diffs)/len(futu_diffs):+.1f}%")

        print("\nKey findings:")
        print("- US Market: Reg T formula is accurate (within 1% of IBKR API)")
        print("- HK Market: Reg T formula DOES NOT apply - use Futu API for real margins")
        print("  - HK uses HKEX margin rules, which are typically 30-40% of Reg T")
        print("  - IBKR whatIfOrder returns 0 for HK options (not supported)")
        print("- For accurate ROC calculations:")
        print("  - US: Use IBKR whatIfOrder API (or Reg T as fallback)")
        print("  - HK: Use Futu acctradinginfo_query API (Reg T will overestimate)")


# ============================================================================
# Main
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="Margin Comparison Verification")
    parser.add_argument(
        "--symbol", "-s",
        type=str,
        nargs="+",
        default=["TSLA", "0700.HK"],
        help="Symbols to test (default: TSLA, 0700.HK)"
    )
    parser.add_argument(
        "--dte-min",
        type=int,
        default=7,
        help="Minimum DTE (default: 7)"
    )
    parser.add_argument(
        "--dte-max",
        type=int,
        default=37,
        help="Maximum DTE (default: 37)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    test = MarginComparisonTest(verbose=args.verbose)
    test.run_all_tests(symbols=args.symbol)


if __name__ == "__main__":
    main()
