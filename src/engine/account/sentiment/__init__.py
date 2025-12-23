"""Market sentiment analysis for account-level decisions.

Account-level module for macro market sentiment indicators:
- VIX analysis
- VIX term structure (VIX vs VIX3M)
- Market trend signals
- Put/Call Ratio
"""

from src.engine.account.sentiment.pcr import (
    calc_pcr,
    calc_pcr_percentile,
    get_pcr_zone,
    interpret_pcr,
    is_pcr_favorable_for_puts,
)
from src.engine.account.sentiment.term_structure import (
    TermStructureResult,
    calc_term_structure,
    get_term_structure_regime,
    get_term_structure_state,
    interpret_term_structure,
    is_term_structure_favorable,
)
from src.engine.account.sentiment.trend import (
    calc_ema,
    calc_sma,
    calc_spy_trend,
    calc_trend_detailed,
    calc_trend_strength,
    is_above_moving_average,
)
from src.engine.account.sentiment.vix import (
    calc_vix_percentile,
    get_vix_regime,
    get_vix_zone,
    interpret_vix,
    is_vix_favorable_for_selling,
)

__all__ = [
    # VIX
    "interpret_vix",
    "get_vix_zone",
    "is_vix_favorable_for_selling",
    "calc_vix_percentile",
    "get_vix_regime",
    # Term Structure
    "TermStructureResult",
    "calc_term_structure",
    "get_term_structure_state",
    "is_term_structure_favorable",
    "get_term_structure_regime",
    "interpret_term_structure",
    # Trend
    "calc_sma",
    "calc_ema",
    "calc_spy_trend",
    "calc_trend_strength",
    "calc_trend_detailed",
    "is_above_moving_average",
    # PCR
    "calc_pcr",
    "interpret_pcr",
    "get_pcr_zone",
    "is_pcr_favorable_for_puts",
    "calc_pcr_percentile",
]
