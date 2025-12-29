#!/usr/bin/env python3
"""Debug script to compare DataBridge vs Direct conversion.

Compares the data flow between:
1. Dashboard path: AccountPosition → DataBridge → PositionData → calc_portfolio_metrics
2. Verification path: AccountPosition → account_position_to_engine_position → Position → calc_*
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from src.data.models.account import AccountType, AssetType
from src.data.models.option import Greeks
from src.data.providers.ibkr_provider import IBKRProvider
from src.data.providers.account_aggregator import AccountAggregator
from src.business.monitoring.data_bridge import MonitoringDataBridge
from src.engine.models.position import Position
from src.engine.portfolio.metrics import calc_portfolio_metrics
from src.engine.portfolio.greeks_agg import (
    calc_portfolio_delta,
    calc_beta_weighted_delta,
    calc_portfolio_gamma,
    calc_portfolio_theta,
    calc_portfolio_vega,
)
from src.engine.portfolio.risk_metrics import calc_portfolio_tgr, calc_concentration_risk


def account_position_to_engine_position(ap):
    """Direct conversion (same as verification script)."""
    greeks = Greeks(
        delta=ap.delta,
        gamma=ap.gamma,
        theta=ap.theta,
        vega=ap.vega,
    )

    dte = None
    if ap.expiry:
        try:
            expiry_date = datetime.strptime(ap.expiry, "%Y%m%d")
            dte = (expiry_date - datetime.now()).days
            if dte < 0:
                dte = 0
        except ValueError:
            pass

    multiplier = ap.contract_multiplier
    if isinstance(multiplier, str):
        multiplier = int(multiplier) if multiplier else 1
    elif multiplier is None:
        multiplier = 1

    return Position(
        symbol=ap.symbol,
        quantity=ap.quantity,
        greeks=greeks,
        market_value=ap.market_value,
        underlying_price=ap.underlying_price,
        contract_multiplier=multiplier,
        margin=ap.margin,
        dte=dte,
        currency=ap.currency,
    )


def main():
    print("=" * 80)
    print("  DataBridge vs Direct Conversion Debug")
    print("=" * 80)

    # Connect to IBKR
    ibkr = IBKRProvider(account_type=AccountType.PAPER)
    ibkr.__enter__()

    try:
        # Get portfolio
        aggregator = AccountAggregator(ibkr_provider=ibkr, futu_provider=None)
        portfolio = aggregator.get_consolidated_portfolio(AccountType.PAPER)

        print(f"\n总持仓数: {len(portfolio.positions)}")

        # === Path 1: Direct conversion (verification script way) ===
        print("\n" + "=" * 80)
        print("  Path 1: Direct Conversion (验证脚本方式)")
        print("=" * 80)

        direct_positions = [account_position_to_engine_position(p) for p in portfolio.positions]

        print("\n[Direct] Position Details:")
        print(f"{'Symbol':<25} {'Type':<6} {'Qty':>8} {'Delta':>10} {'Mult':>6} {'UndPrice':>12} {'Beta':>8}")
        print("-" * 85)
        for i, (ap, pos) in enumerate(zip(portfolio.positions, direct_positions)):
            asset_type = "OPT" if ap.asset_type == AssetType.OPTION else "STK"
            delta = f"{pos.delta:.4f}" if pos.delta is not None else "None"
            und_price = f"{pos.underlying_price:.2f}" if pos.underlying_price else "None"
            beta = f"{pos.beta:.2f}" if pos.beta is not None else "None"
            print(f"{pos.symbol:<25} {asset_type:<6} {pos.quantity:>8.0f} {delta:>10} {pos.contract_multiplier:>6} {und_price:>12} {beta:>8}")

        # Calculate metrics
        direct_delta = calc_portfolio_delta(direct_positions)
        direct_bwd = calc_beta_weighted_delta(direct_positions)
        direct_gamma = calc_portfolio_gamma(direct_positions)
        direct_theta = calc_portfolio_theta(direct_positions)
        direct_vega = calc_portfolio_vega(direct_positions)
        direct_tgr = calc_portfolio_tgr(direct_positions)
        direct_hhi = calc_concentration_risk(direct_positions)

        print(f"\n[Direct] Aggregated Metrics:")
        print(f"  Portfolio Delta:      {direct_delta:.4f}")
        print(f"  Beta-Weighted Delta:  {direct_bwd}")
        print(f"  Portfolio Gamma:      {direct_gamma:.4f}")
        print(f"  Portfolio Theta:      {direct_theta:.4f}")
        print(f"  Portfolio Vega:       {direct_vega:.4f}")
        print(f"  TGR:                  {direct_tgr}")
        print(f"  HHI:                  {direct_hhi}")

        # === Path 2: DataBridge conversion (dashboard way) ===
        print("\n" + "=" * 80)
        print("  Path 2: DataBridge Conversion (Dashboard 方式)")
        print("=" * 80)

        bridge = MonitoringDataBridge(data_provider=None)  # No provider to avoid extra API calls
        bridge_positions = bridge.convert_positions(portfolio)

        print("\n[Bridge] Position Details:")
        print(f"{'Symbol':<25} {'Type':<6} {'Qty':>8} {'Delta':>10} {'Mult':>6} {'UndPrice':>12} {'Beta':>8}")
        print("-" * 85)
        for pos in bridge_positions:
            asset_type = "OPT" if pos.is_option else "STK"
            delta = f"{pos.delta:.4f}" if pos.delta is not None else "None"
            und_price = f"{pos.underlying_price:.2f}" if pos.underlying_price else "None"
            beta = f"{pos.beta:.2f}" if pos.beta is not None else "None"
            print(f"{pos.symbol:<25} {asset_type:<6} {pos.quantity:>8.0f} {delta:>10} {pos.contract_multiplier:>6} {und_price:>12} {beta:>8}")

        # Calculate metrics using calc_portfolio_metrics (same as pipeline)
        bridge_metrics = calc_portfolio_metrics(bridge_positions)  # type: ignore

        print(f"\n[Bridge] Aggregated Metrics (via calc_portfolio_metrics):")
        print(f"  Portfolio Delta:      {bridge_metrics.total_delta}")
        print(f"  Beta-Weighted Delta:  {bridge_metrics.beta_weighted_delta}")
        print(f"  Portfolio Gamma:      {bridge_metrics.total_gamma}")
        print(f"  Portfolio Theta:      {bridge_metrics.total_theta}")
        print(f"  Portfolio Vega:       {bridge_metrics.total_vega}")
        print(f"  TGR:                  {bridge_metrics.portfolio_tgr}")
        print(f"  HHI:                  {bridge_metrics.concentration_hhi}")

        # === Comparison ===
        print("\n" + "=" * 80)
        print("  Comparison (Bridge / Direct)")
        print("=" * 80)

        def ratio(a, b):
            if b is None or b == 0:
                return "N/A"
            if a is None:
                return "N/A"
            return f"{a/b:.2f}x"

        print(f"\n{'Metric':<25} {'Direct':>15} {'Bridge':>15} {'Ratio':>10}")
        print("-" * 70)
        print(f"{'Portfolio Delta':<25} {direct_delta:>15.2f} {bridge_metrics.total_delta:>15.2f} {ratio(bridge_metrics.total_delta, direct_delta):>10}")
        print(f"{'Beta-Weighted Delta':<25} {str(direct_bwd):>15} {str(bridge_metrics.beta_weighted_delta):>15} {ratio(bridge_metrics.beta_weighted_delta, direct_bwd):>10}")
        print(f"{'Portfolio Gamma':<25} {direct_gamma:>15.2f} {bridge_metrics.total_gamma:>15.2f} {ratio(bridge_metrics.total_gamma, direct_gamma):>10}")
        print(f"{'Portfolio Theta':<25} {direct_theta:>15.2f} {bridge_metrics.total_theta:>15.2f} {ratio(bridge_metrics.total_theta, direct_theta):>10}")
        print(f"{'Portfolio Vega':<25} {direct_vega:>15.2f} {bridge_metrics.total_vega:>15.2f} {ratio(bridge_metrics.total_vega, direct_vega):>10}")
        print(f"{'TGR':<25} {str(direct_tgr):>15} {str(bridge_metrics.portfolio_tgr):>15} {ratio(bridge_metrics.portfolio_tgr, direct_tgr):>10}")
        print(f"{'HHI':<25} {str(direct_hhi):>15} {str(bridge_metrics.concentration_hhi):>15} {ratio(bridge_metrics.concentration_hhi, direct_hhi):>10}")

    finally:
        ibkr.__exit__(None, None, None)


if __name__ == "__main__":
    main()
