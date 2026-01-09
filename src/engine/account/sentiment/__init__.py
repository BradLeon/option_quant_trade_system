"""Market sentiment analysis for account-level decisions.

Account-level module for macro market sentiment indicators:
- VIX analysis and term structure (VIX vs VIX3M)
- Market trend signals (SPY, QQQ, 2800.HK, 3032.HK)
- Put/Call Ratio
- Aggregated sentiment for US and HK markets
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

# VIX term structure
from src.engine.account.sentiment.vix_term import (
    analyze_term_structure,
    calc_vix_term_ratio,
    get_term_structure,
    interpret_term_structure,
    is_term_structure_favorable,
)

# Generalized market trend
from src.engine.account.sentiment.market_trend import (
    analyze_market_trend,
    calc_market_trend,
    get_trend_description,
)

# Aggregation
from src.engine.account.sentiment.aggregator import (
    analyze_hk_sentiment,
    analyze_us_sentiment,
    calc_composite_score,
    get_sentiment_summary,
    score_to_signal,
)

# Data bridge
from src.engine.account.sentiment.data_bridge import (
    fetch_hk_sentiment_data,
    fetch_us_sentiment_data,
    get_hk_sentiment,
    get_us_sentiment,
)

__all__ = [
    # VIX
    "interpret_vix",
    "get_vix_zone",
    "is_vix_favorable_for_selling",
    "calc_vix_percentile",
    "get_vix_regime",
    # Term Structure (term_structure.py)
    "TermStructureResult",
    "calc_term_structure",
    "get_term_structure_state",
    "get_term_structure_regime",
    # VIX Term Structure (vix_term.py)
    "calc_vix_term_ratio",
    "get_term_structure",
    "interpret_term_structure",
    "analyze_term_structure",
    "is_term_structure_favorable",
    # Trend
    "calc_sma",
    "calc_ema",
    "calc_spy_trend",
    "calc_trend_strength",
    "calc_trend_detailed",
    "is_above_moving_average",
    # Generalized Market Trend
    "calc_market_trend",
    "analyze_market_trend",
    "get_trend_description",
    # PCR
    "calc_pcr",
    "interpret_pcr",
    "get_pcr_zone",
    "is_pcr_favorable_for_puts",
    "calc_pcr_percentile",
    # Aggregation
    "analyze_us_sentiment",
    "analyze_hk_sentiment",
    "calc_composite_score",
    "score_to_signal",
    "get_sentiment_summary",
    # Data Bridge
    "fetch_us_sentiment_data",
    "fetch_hk_sentiment_data",
    "get_us_sentiment",
    "get_hk_sentiment",
]
