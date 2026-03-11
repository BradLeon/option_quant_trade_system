"""LEAPS Call B-S Pricing Diagnostic

Purpose: Identify the root cause of excessive time-value decay in synthetic
LEAPS call pricing. Decomposes daily price changes via Greeks attribution
and quantifies the impact of dividend discount, IV estimation, and theta cost.

Sections:
  1. Day-by-day B-S pricing decomposition for a typical holding
  2. Greeks-based P&L attribution (delta/gamma/theta/vega/residual)
  3. Dividend discount impact quantification
  4. Parameter sensitivity sweep (div_yield, term_coeff, skew_coeff)
  5. 3x leverage theta cost vs SPY delta income

Data: stock_daily.parquet + macro_daily.parquet from /Volumes/ORICO/option_quant/
"""

import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.bs.core import calc_bs_price
from src.engine.bs.greeks import calc_bs_greeks
from src.engine.models.bs_params import BSParams

# ============================================================
# Config
# ============================================================
STOCK_PARQUET = Path("/Volumes/ORICO/option_quant/stock_daily.parquet")
MACRO_PARQUET = Path("/Volumes/ORICO/option_quant/macro_daily.parquet")
SYMBOL = "SPY"

# Typical LEAPS position parameters
STRIKE = 380.0  # Deep ITM when SPY ~450
ENTRY_DATE = date(2021, 1, 4)  # SPY ~$375
HOLD_DAYS = 252  # ~1 year holding period
NUM_CONTRACTS = 74  # ~3x leverage on $1M
LOT_SIZE = 100

# Synthetic chain parameters (from SyntheticLeapsProvider)
DEFAULT_DIV_YIELD = 0.013
DEFAULT_TERM_COEFF = 0.15
DEFAULT_TERM_HALFLIFE = 180
DEFAULT_SKEW_COEFF = 0.15


# ============================================================
# Data Loading
# ============================================================
def load_market_data() -> dict:
    """Load SPY, VIX, TNX daily data into aligned dicts keyed by date."""
    # Stock
    stock_table = pq.read_table(
        STOCK_PARQUET,
        filters=[("symbol", "=", SYMBOL)],
        columns=["date", "close"],
    )
    stock = {
        d: c
        for d, c in zip(
            stock_table.column("date").to_pylist(),
            stock_table.column("close").to_pylist(),
        )
    }

    # VIX
    vix_table = pq.read_table(
        MACRO_PARQUET,
        filters=[("indicator", "=", "^VIX")],
        columns=["date", "close"],
    )
    vix = {
        d: c
        for d, c in zip(
            vix_table.column("date").to_pylist(),
            vix_table.column("close").to_pylist(),
        )
    }

    # TNX (10Y Treasury yield)
    tnx_table = pq.read_table(
        MACRO_PARQUET,
        filters=[("indicator", "=", "^TNX")],
        columns=["date", "close"],
    )
    tnx = {
        d: c
        for d, c in zip(
            tnx_table.column("date").to_pylist(),
            tnx_table.column("close").to_pylist(),
        )
    }

    return {"stock": stock, "vix": vix, "tnx": tnx}


def get_trading_days(stock_data: dict, start: date, num_days: int) -> list[date]:
    """Get N trading days starting from start_date."""
    all_dates = sorted(d for d in stock_data.keys() if d >= start)
    return all_dates[:num_days]


# ============================================================
# IV Estimation (copied from SyntheticLeapsProvider)
# ============================================================
def estimate_iv(
    vix: float,
    dte: int,
    moneyness: float,
    term_coeff: float = DEFAULT_TERM_COEFF,
    term_halflife: float = DEFAULT_TERM_HALFLIFE,
    skew_coeff: float = DEFAULT_SKEW_COEFF,
) -> float:
    """Estimate IV from VIX with term structure and moneyness skew.

    Args:
        vix: VIX value as decimal (e.g., 0.20)
        dte: Days to expiration
        moneyness: strike / spot
        term_coeff: Term structure decay coefficient
        term_halflife: Term structure exponential half-life in days
        skew_coeff: Moneyness skew coefficient
    """
    term_factor = 1.0 - term_coeff * (1 - math.exp(-dte / term_halflife))
    base_iv = vix * term_factor
    skew = skew_coeff * (1.0 - moneyness)
    return base_iv * (1.0 + skew)


def compute_bs_price_and_greeks(
    spot: float,
    strike: float,
    dte: int,
    vix_decimal: float,
    rfr: float,
    div_yield: float = DEFAULT_DIV_YIELD,
    term_coeff: float = DEFAULT_TERM_COEFF,
    skew_coeff: float = DEFAULT_SKEW_COEFF,
) -> dict | None:
    """Compute B-S call price and Greeks for given parameters."""
    if dte <= 0:
        return None

    T = dte / 365.0
    spot_adj = spot * math.exp(-div_yield * T)
    moneyness = strike / spot
    iv = estimate_iv(vix_decimal, dte, moneyness, term_coeff=term_coeff, skew_coeff=skew_coeff)

    params = BSParams(
        spot_price=spot_adj,
        strike_price=strike,
        risk_free_rate=rfr,
        volatility=iv,
        time_to_expiry=T,
        is_call=True,
    )

    price = calc_bs_price(params)
    if price is None:
        return None

    greeks = calc_bs_greeks(params)
    intrinsic = max(0, spot_adj - strike)

    return {
        "price": price,
        "intrinsic": intrinsic,
        "time_value": price - intrinsic,
        "spot": spot,
        "spot_adj": spot_adj,
        "iv": iv,
        "moneyness": moneyness,
        "T": T,
        "dte": dte,
        "delta": greeks.get("delta"),
        "gamma": greeks.get("gamma"),
        "theta": greeks.get("theta"),  # daily theta (/365)
        "vega": greeks.get("vega"),  # per 1% IV (/100)
        "rfr": rfr,
        "div_yield": div_yield,
    }


# ============================================================
# Section 1 & 2: Day-by-day Pricing + Greeks Attribution
# ============================================================
@dataclass
class DailyAttribution:
    dt: date
    dte: int
    spot: float
    spot_adj: float
    bs_price: float
    intrinsic: float
    time_value: float
    iv: float
    delta: float
    theta: float
    vega: float
    gamma: float
    # Attribution components (from previous day)
    delta_effect: float = 0.0
    gamma_effect: float = 0.0
    theta_effect: float = 0.0
    vega_effect: float = 0.0
    div_discount_effect: float = 0.0  # spot_adj change from div yield
    residual: float = 0.0
    price_change: float = 0.0


def run_daily_decomposition(
    data: dict,
    strike: float = STRIKE,
    entry_date: date = ENTRY_DATE,
    hold_days: int = HOLD_DAYS,
    div_yield: float = DEFAULT_DIV_YIELD,
    term_coeff: float = DEFAULT_TERM_COEFF,
    skew_coeff: float = DEFAULT_SKEW_COEFF,
) -> list[DailyAttribution]:
    """Run day-by-day B-S pricing and decompose changes via Greeks."""
    stock = data["stock"]
    vix_data = data["vix"]
    tnx_data = data["tnx"]

    trading_days = get_trading_days(stock, entry_date, hold_days)
    if not trading_days:
        print(f"ERROR: No trading days found from {entry_date}")
        return []

    # Compute initial DTE (assume 1 year LEAPS from entry)
    expiry = entry_date + timedelta(days=365)
    # Adjust to 3rd Friday of expiry month
    first_day = date(expiry.year, expiry.month, 1)
    first_friday_offset = (4 - first_day.weekday()) % 7
    third_friday = first_day + timedelta(days=first_friday_offset + 14)
    expiry = third_friday

    records: list[DailyAttribution] = []
    prev: dict | None = None

    for dt in trading_days:
        spot = stock.get(dt)
        vix_val = vix_data.get(dt)
        tnx_val = tnx_data.get(dt)
        if spot is None or vix_val is None:
            continue

        rfr = (tnx_val / 100.0) if tnx_val else 0.04
        vix_decimal = vix_val / 100.0
        dte = (expiry - dt).days
        if dte <= 0:
            break

        result = compute_bs_price_and_greeks(
            spot, strike, dte, vix_decimal, rfr,
            div_yield=div_yield, term_coeff=term_coeff, skew_coeff=skew_coeff,
        )
        if result is None:
            continue

        rec = DailyAttribution(
            dt=dt, dte=dte,
            spot=result["spot"], spot_adj=result["spot_adj"],
            bs_price=result["price"],
            intrinsic=result["intrinsic"],
            time_value=result["time_value"],
            iv=result["iv"],
            delta=result["delta"],
            theta=result["theta"],
            vega=result["vega"],
            gamma=result["gamma"],
        )

        # Attribution vs previous day
        if prev is not None:
            rec.price_change = result["price"] - prev["price"]

            d_spot_adj = result["spot_adj"] - prev["spot_adj"]
            d_iv = result["iv"] - prev["iv"]
            calendar_days = (dt - prev["dt"]).days

            # Use previous day's Greeks to explain today's change
            rec.delta_effect = prev["delta"] * d_spot_adj
            rec.gamma_effect = 0.5 * prev["gamma"] * d_spot_adj ** 2
            rec.theta_effect = prev["theta"] * calendar_days  # theta is daily (/365)
            rec.vega_effect = prev["vega"] * (d_iv * 100)  # vega is per 1% IV

            # Dividend discount effect on spot_adj
            # spot_adj = spot * exp(-q*T), so d(spot_adj) has two parts:
            # 1. From spot change: exp(-q*T_today) * d_spot
            # 2. From T change: spot * q * exp(-q*T) * dt/365 (dividend "release")
            T_today = result["T"]
            T_prev = prev["T"]
            # Counterfactual: what would spot_adj be if div_yield=0?
            spot_adj_no_div = result["spot"]  # no discount
            spot_adj_no_div_prev = prev["spot"]
            # The dividend discount steals from spot_adj
            div_drag_today = result["spot"] - result["spot_adj"]  # amount discounted today
            div_drag_prev = prev["spot"] - prev["spot_adj"]  # amount discounted prev
            rec.div_discount_effect = -(div_drag_today - div_drag_prev)  # net change in discount

            explained = rec.delta_effect + rec.gamma_effect + rec.theta_effect + rec.vega_effect
            rec.residual = rec.price_change - explained

        prev = {**result, "dt": dt}
        records.append(rec)

    return records


# ============================================================
# Section 3: Dividend Discount Impact
# ============================================================
def quantify_dividend_impact(data: dict) -> None:
    """Compare B-S prices with div_yield=0 vs div_yield=0.013."""
    print("\n" + "=" * 85)
    print("SECTION 3: Dividend Discount Impact")
    print("=" * 85)

    stock = data["stock"]
    vix_data = data["vix"]
    tnx_data = data["tnx"]

    # Pick a few representative dates and DTEs
    test_cases = [
        (ENTRY_DATE, 365, "Entry (DTE=365)"),
        (ENTRY_DATE + timedelta(days=126), 239, "Midpoint (DTE≈239)"),
        (ENTRY_DATE + timedelta(days=252), 113, "Near roll (DTE≈113)"),
    ]

    print(f"\n  Strike={STRIKE}  |  div_yield scenarios: 0%, 1.3%, 2.0%")
    print(f"  {'Scenario':<25} {'Spot':>8} {'DTE':>5} {'q=0%':>10} {'q=1.3%':>10} {'q=2.0%':>10} {'Diff(0-1.3)':>12} {'Diff(0-2.0)':>12}")
    print("  " + "-" * 95)

    for target_dt, approx_dte, label in test_cases:
        # Find nearest trading day
        dt = min(
            (d for d in stock if d >= target_dt),
            default=None,
        )
        if dt is None:
            continue

        spot = stock[dt]
        vix_decimal = vix_data.get(dt, 20) / 100.0
        rfr = tnx_data.get(dt, 4.0) / 100.0
        dte = approx_dte

        prices = {}
        for q in [0.0, 0.013, 0.02]:
            r = compute_bs_price_and_greeks(spot, STRIKE, dte, vix_decimal, rfr, div_yield=q)
            prices[q] = r["price"] if r else 0

        diff_013 = prices[0.0] - prices[0.013]
        diff_020 = prices[0.0] - prices[0.02]
        per_contract_013 = diff_013 * LOT_SIZE
        per_contract_020 = diff_020 * LOT_SIZE

        print(
            f"  {label:<25} {spot:>8.2f} {dte:>5} "
            f"${prices[0.0]:>9.2f} ${prices[0.013]:>9.2f} ${prices[0.02]:>9.2f} "
            f"${diff_013:>7.2f}(×100=${per_contract_013:>7.0f}) "
            f"${diff_020:>7.2f}(×100=${per_contract_020:>7.0f})"
        )

    # Total impact over holding period
    print(f"\n  Over {NUM_CONTRACTS} contracts × 100 shares:")
    # Entry: high T → large discount; Exit: low T → small discount
    # The asymmetry means you pay more (buy discounted) and sell less (discount released)
    # But actually: you BUY with high discount (cheaper), SELL with low discount (also cheaper)
    # Net: the discount shrinks as T decreases, so spot_adj rises even if spot unchanged → GOOD for longs
    # But: delta < 1 because spot_adj < spot, so you miss some spot upside → BAD for longs
    dt_entry = min((d for d in stock if d >= ENTRY_DATE), default=None)
    dt_exit_approx = ENTRY_DATE + timedelta(days=HOLD_DAYS)
    dt_exit = min((d for d in stock if d >= dt_exit_approx), default=None)

    if dt_entry and dt_exit:
        spot_entry = stock[dt_entry]
        spot_exit = stock[dt_exit]
        vix_entry = vix_data[dt_entry] / 100.0
        rfr_entry = tnx_data.get(dt_entry, 4.0) / 100.0

        # Price at entry with and without dividend
        r_div = compute_bs_price_and_greeks(spot_entry, STRIKE, 365, vix_entry, rfr_entry, div_yield=0.013)
        r_nodiv = compute_bs_price_and_greeks(spot_entry, STRIKE, 365, vix_entry, rfr_entry, div_yield=0.0)

        # Price at exit
        dte_exit = 365 - HOLD_DAYS
        if dte_exit < 10:
            dte_exit = 113  # approximate
        vix_exit = vix_data.get(dt_exit, 20) / 100.0
        rfr_exit = tnx_data.get(dt_exit, 4.0) / 100.0

        r_div_exit = compute_bs_price_and_greeks(spot_exit, STRIKE, dte_exit, vix_exit, rfr_exit, div_yield=0.013)
        r_nodiv_exit = compute_bs_price_and_greeks(spot_exit, STRIKE, dte_exit, vix_exit, rfr_exit, div_yield=0.0)

        if r_div and r_nodiv and r_div_exit and r_nodiv_exit:
            pnl_div = (r_div_exit["price"] - r_div["price"]) * NUM_CONTRACTS * LOT_SIZE
            pnl_nodiv = (r_nodiv_exit["price"] - r_nodiv["price"]) * NUM_CONTRACTS * LOT_SIZE
            div_impact = pnl_div - pnl_nodiv
            print(f"  P&L with div_yield=1.3%:  ${pnl_div:>12,.0f}")
            print(f"  P&L with div_yield=0%:    ${pnl_nodiv:>12,.0f}")
            print(f"  Dividend discount impact: ${div_impact:>12,.0f}")


# ============================================================
# Section 4: Parameter Sensitivity
# ============================================================
def run_sensitivity(data: dict) -> None:
    """Sweep key parameters and measure P&L impact."""
    print("\n" + "=" * 85)
    print("SECTION 4: Parameter Sensitivity Analysis")
    print("=" * 85)

    stock = data["stock"]
    trading_days = get_trading_days(stock, ENTRY_DATE, HOLD_DAYS)
    if len(trading_days) < 2:
        print("ERROR: Not enough trading days")
        return

    dt_entry = trading_days[0]
    dt_exit = trading_days[-1]
    spot_entry = stock[dt_entry]
    spot_exit = stock[dt_exit]

    vix_data = data["vix"]
    tnx_data = data["tnx"]
    vix_entry = vix_data[dt_entry] / 100.0
    vix_exit = vix_data[dt_exit] / 100.0
    rfr_entry = tnx_data.get(dt_entry, 4.0) / 100.0
    rfr_exit = tnx_data.get(dt_exit, 4.0) / 100.0

    dte_entry = 365
    dte_exit = max(365 - HOLD_DAYS, 10)

    def calc_pnl(div_yield, term_coeff, skew_coeff):
        r_entry = compute_bs_price_and_greeks(
            spot_entry, STRIKE, dte_entry, vix_entry, rfr_entry,
            div_yield=div_yield, term_coeff=term_coeff, skew_coeff=skew_coeff,
        )
        r_exit = compute_bs_price_and_greeks(
            spot_exit, STRIKE, dte_exit, vix_exit, rfr_exit,
            div_yield=div_yield, term_coeff=term_coeff, skew_coeff=skew_coeff,
        )
        if r_entry and r_exit:
            return (r_exit["price"] - r_entry["price"]) * NUM_CONTRACTS * LOT_SIZE
        return 0.0

    baseline_pnl = calc_pnl(DEFAULT_DIV_YIELD, DEFAULT_TERM_COEFF, DEFAULT_SKEW_COEFF)

    # Sweep div_yield
    print(f"\n  Baseline P&L: ${baseline_pnl:>12,.0f}")
    print(f"  (Entry: {dt_entry} SPY=${spot_entry:.2f} → Exit: {dt_exit} SPY=${spot_exit:.2f})")

    print(f"\n  --- div_yield sweep ---")
    print(f"  {'div_yield':>12} {'P&L':>14} {'vs baseline':>14}")
    for q in [0.0, 0.005, 0.010, 0.013, 0.015, 0.020, 0.025]:
        pnl = calc_pnl(q, DEFAULT_TERM_COEFF, DEFAULT_SKEW_COEFF)
        diff = pnl - baseline_pnl
        marker = " ← current" if q == DEFAULT_DIV_YIELD else ""
        print(f"  {q*100:>10.1f}% ${pnl:>13,.0f} ${diff:>13,.0f}{marker}")

    print(f"\n  --- term_coeff sweep (controls long-dated IV discount) ---")
    print(f"  {'term_coeff':>12} {'P&L':>14} {'vs baseline':>14}")
    for tc in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
        pnl = calc_pnl(DEFAULT_DIV_YIELD, tc, DEFAULT_SKEW_COEFF)
        diff = pnl - baseline_pnl
        marker = " ← current" if tc == DEFAULT_TERM_COEFF else ""
        print(f"  {tc:>12.2f} ${pnl:>13,.0f} ${diff:>13,.0f}{marker}")

    print(f"\n  --- skew_coeff sweep (ITM vs OTM IV tilt) ---")
    print(f"  {'skew_coeff':>12} {'P&L':>14} {'vs baseline':>14}")
    for sc in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
        pnl = calc_pnl(DEFAULT_DIV_YIELD, DEFAULT_TERM_COEFF, sc)
        diff = pnl - baseline_pnl
        marker = " ← current" if sc == DEFAULT_SKEW_COEFF else ""
        print(f"  {sc:>12.2f} ${pnl:>13,.0f} ${diff:>13,.0f}{marker}")


# ============================================================
# Section 5: 3x Leverage Theta Cost Analysis
# ============================================================
def analyze_theta_cost(records: list[DailyAttribution]) -> None:
    """Quantify daily theta cost at 3x leverage vs expected delta income."""
    print("\n" + "=" * 85)
    print("SECTION 5: 3x Leverage Theta Cost vs Delta Income")
    print("=" * 85)

    if not records:
        print("  No records to analyze")
        return

    # Portfolio-level daily P&L components
    total_delta_pnl = 0.0
    total_gamma_pnl = 0.0
    total_theta_pnl = 0.0
    total_vega_pnl = 0.0
    total_residual = 0.0
    total_price_change = 0.0

    scale = NUM_CONTRACTS * LOT_SIZE  # position scale

    daily_theta_costs = []
    daily_delta_income = []

    for rec in records[1:]:  # skip first day (no attribution)
        total_delta_pnl += rec.delta_effect * scale
        total_gamma_pnl += rec.gamma_effect * scale
        total_theta_pnl += rec.theta_effect * scale
        total_vega_pnl += rec.vega_effect * scale
        total_residual += rec.residual * scale
        total_price_change += rec.price_change * scale

        daily_theta_costs.append(rec.theta_effect * scale)
        daily_delta_income.append(rec.delta_effect * scale)

    holding_days = len(records) - 1

    print(f"\n  Position: {NUM_CONTRACTS} contracts × {LOT_SIZE} shares = {scale:,} share-equivalents")
    print(f"  Holding period: {holding_days} trading days ({records[0].dt} → {records[-1].dt})")
    print(f"  Entry spot: ${records[0].spot:.2f}  |  Exit spot: ${records[-1].spot:.2f}")
    print(f"  Entry IV: {records[0].iv*100:.1f}%  |  Exit IV: {records[-1].iv*100:.1f}%")

    print(f"\n  P&L Attribution ({holding_days} days):")
    print(f"  {'Component':<25} {'Total $':>14} {'Daily avg $':>14} {'% of total':>12}")
    print("  " + "-" * 70)

    components = [
        ("Delta (stock moves)", total_delta_pnl),
        ("Gamma (convexity)", total_gamma_pnl),
        ("Theta (time decay)", total_theta_pnl),
        ("Vega (IV changes)", total_vega_pnl),
        ("Residual (model gap)", total_residual),
    ]
    for name, val in components:
        daily_avg = val / holding_days if holding_days > 0 else 0
        pct = val / abs(total_price_change) * 100 if total_price_change != 0 else 0
        print(f"  {name:<25} ${val:>13,.0f} ${daily_avg:>13,.0f} {pct:>+11.1f}%")
    print("  " + "-" * 70)
    daily_avg = total_price_change / holding_days if holding_days > 0 else 0
    print(f"  {'TOTAL':.<25} ${total_price_change:>13,.0f} ${daily_avg:>13,.0f}")

    # Average daily theta per contract
    avg_theta_per_share = np.mean([r.theta for r in records])
    avg_daily_theta_portfolio = avg_theta_per_share * scale
    annualized_theta = avg_daily_theta_portfolio * 252

    print(f"\n  Theta analysis:")
    print(f"    Avg theta/share/day:      ${avg_theta_per_share:.4f}")
    print(f"    Avg portfolio theta/day:  ${avg_daily_theta_portfolio:>10,.0f}")
    print(f"    Annualized theta cost:    ${annualized_theta:>10,.0f}")

    # SPY expected return (12%/yr benchmark)
    entry_spot = records[0].spot
    expected_spy_return = 0.12
    # Delta-weighted exposure
    avg_delta = np.mean([r.delta for r in records])
    delta_exposure = avg_delta * scale * entry_spot
    expected_delta_income = delta_exposure * expected_spy_return

    print(f"\n  Expected delta income (SPY 12%/yr assumption):")
    print(f"    Avg delta:                 {avg_delta:.3f}")
    print(f"    Delta exposure:           ${delta_exposure:>10,.0f}")
    print(f"    Expected annual income:   ${expected_delta_income:>10,.0f}")
    print(f"    Theta cost / delta income: {abs(annualized_theta/expected_delta_income)*100:.1f}%")

    # Theta:daily price ratio
    avg_price = np.mean([r.bs_price for r in records])
    theta_pct_of_price = abs(avg_theta_per_share) / avg_price * 100
    print(f"\n  Daily theta as % of option price: {theta_pct_of_price:.3f}%")
    print(f"  Expected daily theta for deep ITM LEAPS: ~0.005-0.010%")
    if theta_pct_of_price > 0.05:
        print(f"  ⚠ ANOMALY: theta is {theta_pct_of_price/0.01:.0f}x higher than expected!")


# ============================================================
# Output Section 1 & 2
# ============================================================
def print_daily_decomposition(records: list[DailyAttribution]) -> None:
    """Print detailed daily decomposition (sampled)."""
    print("\n" + "=" * 85)
    print("SECTION 1 & 2: Day-by-Day B-S Pricing & Greeks Attribution")
    print("=" * 85)
    print(f"  Strike: {STRIKE}  |  Entry: {records[0].dt}  |  Expiry: DTE={records[0].dte}")

    # Print header
    print(f"\n  {'Date':>12} {'DTE':>5} {'Spot':>8} {'SpotAdj':>8} {'BSPrice':>8} "
          f"{'Intrin':>8} {'TimeVal':>8} {'IV':>6} {'Delta':>6} {'Theta':>7} "
          f"{'ΔPrice':>8} {'δ-eff':>8} {'γ-eff':>8} {'θ-eff':>8} {'ν-eff':>8} {'Resid':>8}")
    print("  " + "-" * 145)

    # Sample: first 10 days, then every 20 days, last 5 days
    indices = list(range(min(10, len(records))))
    indices += list(range(10, len(records) - 5, 20))
    indices += list(range(max(len(records) - 5, 10), len(records)))
    indices = sorted(set(i for i in indices if 0 <= i < len(records)))

    prev_idx = -1
    for idx in indices:
        r = records[idx]
        if prev_idx >= 0 and idx - prev_idx > 1:
            print(f"  {'...':>12}")
        print(
            f"  {str(r.dt):>12} {r.dte:>5} {r.spot:>8.2f} {r.spot_adj:>8.2f} "
            f"{r.bs_price:>8.2f} {r.intrinsic:>8.2f} {r.time_value:>8.2f} "
            f"{r.iv*100:>5.1f}% {r.delta:>6.3f} {r.theta:>7.4f} "
            f"{r.price_change:>+8.3f} {r.delta_effect:>+8.3f} {r.gamma_effect:>+8.3f} "
            f"{r.theta_effect:>+8.3f} {r.vega_effect:>+8.3f} {r.residual:>+8.3f}"
        )
        prev_idx = idx

    # Summary stats
    if len(records) > 1:
        total_change = records[-1].bs_price - records[0].bs_price
        total_delta = sum(r.delta_effect for r in records[1:])
        total_gamma = sum(r.gamma_effect for r in records[1:])
        total_theta = sum(r.theta_effect for r in records[1:])
        total_vega = sum(r.vega_effect for r in records[1:])
        total_resid = sum(r.residual for r in records[1:])

        print(f"\n  Per-share summary over {len(records)-1} days:")
        print(f"    Total price change:  ${total_change:>+10.2f}")
        print(f"    Delta attribution:   ${total_delta:>+10.2f}")
        print(f"    Gamma attribution:   ${total_gamma:>+10.2f}")
        print(f"    Theta attribution:   ${total_theta:>+10.2f}")
        print(f"    Vega attribution:    ${total_vega:>+10.2f}")
        print(f"    Residual:            ${total_resid:>+10.2f}")
        explained = total_delta + total_gamma + total_theta + total_vega
        print(f"    Explained total:     ${explained:>+10.2f}")
        print(f"    Actual total:        ${total_change:>+10.2f}")
        if abs(total_resid) > abs(total_change) * 0.1:
            print(f"    ⚠ Large residual ({abs(total_resid/total_change)*100:.0f}% of total) — model discontinuity!")


# ============================================================
# Additional: Find actual holding periods from backtest data
# ============================================================
def find_representative_periods(data: dict) -> list[dict]:
    """Find good test periods where SPY was in uptrend (above SMA200)."""
    stock = data["stock"]
    sorted_dates = sorted(stock.keys())
    prices = [stock[d] for d in sorted_dates]

    # Find periods where SMA is available and price > SMA
    from src.engine.position.technical.moving_average import calc_sma_series

    sma_series = calc_sma_series(prices, 200)

    periods = []
    # A few interesting periods
    test_configs = [
        (date(2017, 1, 3), 252, "2017 steady uptrend"),
        (date(2019, 1, 2), 252, "2019 recovery"),
        (date(2021, 1, 4), 252, "2021 post-COVID rally"),
        (date(2023, 6, 1), 252, "2023-24 AI rally"),
    ]

    for start, days, label in test_configs:
        td = get_trading_days(stock, start, days)
        if len(td) >= days:
            entry_price = stock[td[0]]
            exit_price = stock[td[-1]]
            spy_return = (exit_price / entry_price - 1) * 100
            periods.append({
                "start": start, "days": days, "label": label,
                "entry_price": entry_price, "exit_price": exit_price,
                "spy_return": spy_return,
            })

    return periods


def run_multi_period_comparison(data: dict) -> None:
    """Run pricing diagnostic across multiple representative periods."""
    print("\n" + "=" * 85)
    print("BONUS: Multi-Period LEAPS Pricing Comparison")
    print("=" * 85)

    periods = find_representative_periods(data)

    print(f"\n  {'Period':<25} {'SPY Ret':>9} {'LEAPS P&L/share':>16} {'Theta drag':>12} {'Residual':>12} {'Theta%':>8}")
    print("  " + "-" * 90)

    for p in periods:
        records = run_daily_decomposition(
            data, strike=STRIKE, entry_date=p["start"], hold_days=p["days"],
        )
        if len(records) < 2:
            continue

        total_change = records[-1].bs_price - records[0].bs_price
        total_theta = sum(r.theta_effect for r in records[1:])
        total_resid = sum(r.residual for r in records[1:])
        theta_pct = abs(total_theta / records[0].bs_price) * 100 if records[0].bs_price else 0

        print(
            f"  {p['label']:<25} {p['spy_return']:>+8.1f}% "
            f"${total_change:>+14.2f} ${total_theta:>+11.2f} "
            f"${total_resid:>+11.2f} {theta_pct:>7.1f}%"
        )


# ============================================================
# Main
# ============================================================
def main():
    print("Loading market data...")
    data = load_market_data()
    print(f"  SPY: {len(data['stock'])} days")
    print(f"  VIX: {len(data['vix'])} days")
    print(f"  TNX: {len(data['tnx'])} days")

    # Main decomposition
    print(f"\n  Running decomposition: STRIKE={STRIKE}, ENTRY={ENTRY_DATE}, HOLD={HOLD_DAYS} days")
    records = run_daily_decomposition(data)
    print(f"  Generated {len(records)} daily records")

    # Section 1 & 2: Daily decomposition
    print_daily_decomposition(records)

    # Section 3: Dividend impact
    quantify_dividend_impact(data)

    # Section 4: Parameter sensitivity
    run_sensitivity(data)

    # Section 5: Theta cost analysis
    analyze_theta_cost(records)

    # Bonus: Multi-period comparison
    run_multi_period_comparison(data)


if __name__ == "__main__":
    main()
