"""Account-level calculations for risk and capital management.

This module provides calculations at the account/fund level:
- Margin utilization
- Position sizing (Kelly criterion)
- Capital management (ROC)
- Market sentiment (VIX, Trend, PCR)
"""

from src.engine.account.capital import calc_roc
from src.engine.account.margin import calc_margin_utilization
from src.engine.account.position_sizing import (
    calc_fractional_kelly,
    calc_half_kelly,
    calc_kelly,
    calc_kelly_from_trades,
    interpret_kelly,
)
from src.engine.account.sentiment import (
    calc_ema,
    calc_pcr,
    calc_pcr_percentile,
    calc_sma,
    calc_spy_trend,
    calc_trend_detailed,
    calc_trend_strength,
    calc_vix_percentile,
    get_pcr_zone,
    get_vix_regime,
    get_vix_zone,
    interpret_pcr,
    interpret_vix,
    is_above_moving_average,
    is_pcr_favorable_for_puts,
    is_vix_favorable_for_selling,
)

__all__ = [
    # Margin
    "calc_margin_utilization",
    # Position sizing
    "calc_kelly",
    "calc_kelly_from_trades",
    "calc_half_kelly",
    "calc_fractional_kelly",
    "interpret_kelly",
    # Capital
    "calc_roc",
    # Sentiment - VIX
    "interpret_vix",
    "get_vix_zone",
    "is_vix_favorable_for_selling",
    "calc_vix_percentile",
    "get_vix_regime",
    # Sentiment - Trend
    "calc_sma",
    "calc_ema",
    "calc_spy_trend",
    "calc_trend_strength",
    "calc_trend_detailed",
    "is_above_moving_average",
    # Sentiment - PCR
    "calc_pcr",
    "interpret_pcr",
    "get_pcr_zone",
    "is_pcr_favorable_for_puts",
    "calc_pcr_percentile",
]
