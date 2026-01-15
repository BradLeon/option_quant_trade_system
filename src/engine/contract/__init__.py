"""Contract-level utility functions for options screening.

Provides calculations for:
- Liquidity metrics (bid/ask spread, volume)
- Option metrics (OTM percent, theta/premium ratio)
"""

from src.engine.contract.liquidity import (
    calc_bid_ask_spread,
    calc_bid_ask_spread_ratio,
    calc_option_chain_open_interest,
    calc_option_chain_volume,
    is_liquid,
    liquidity_score,
)
from src.engine.contract.metrics import (
    calc_annual_return,
    calc_break_even,
    calc_expected_move,
    calc_max_loss,
    calc_moneyness,
    calc_otm_percent,
    calc_theta_gamma_ratio,
    calc_theta_premium_ratio,
)

__all__ = [
    # Liquidity
    "calc_bid_ask_spread",
    "calc_bid_ask_spread_ratio",
    "calc_option_chain_volume",
    "calc_option_chain_open_interest",
    "is_liquid",
    "liquidity_score",
    # Metrics
    "calc_otm_percent",
    "calc_moneyness",
    "calc_theta_premium_ratio",
    "calc_theta_gamma_ratio",
    "calc_annual_return",
    "calc_break_even",
    "calc_max_loss",
    "calc_expected_move",
]
