"""Technical analysis module.

Position-level technical indicators for individual securities.

Main Interface (recommended):
    Input:  TechnicalData (from src.data.models.technical)
    Output: TechnicalScore (from src.engine.models.result)

    Example:
        from src.data.models import TechnicalData
        from src.engine.position.technical import evaluate_technical

        data = TechnicalData.from_klines(bars)
        score = evaluate_technical(data)
        print(f"Technical Score: {score.score}, Rating: {score.rating}")

Low-level functions are also available for individual indicator calculations.
"""

# Threshold configuration (for backtesting/optimization)
from src.engine.position.technical.thresholds import (
    DEFAULT_THRESHOLDS,
    TechnicalThresholds,
)

# Unified interface (Input: TechnicalData -> Output: TechnicalScore/TechnicalSignal)
from src.engine.position.technical.metrics import (
    # New main functions
    calc_technical_score,
    calc_technical_signal,
    # Getter functions
    get_adx,
    get_bollinger_bands,
    get_ema,
    get_ma_alignment_str,
    get_rsi,
    get_sma,
    get_trend_signal,
    # Strategy helpers
    is_trend_favorable_for_covered_call,
    is_trend_favorable_for_short_put,
    is_trend_favorable_for_strangle,
    # Deprecated (backward compatibility)
    evaluate_technical,
    is_technically_favorable,
)

# ADX (low-level)
from src.engine.position.technical.adx import (
    ADXResult,
    calc_adx,
    calc_tr_series,
    calc_true_range,
    get_adx_trend_direction,
    interpret_adx,
    is_adx_favorable_for_directional,
    is_adx_favorable_for_strangle,
    is_ranging,
    is_trending,
)

# Bollinger Bands (low-level)
from src.engine.position.technical.bollinger_bands import (
    BollingerBands,
    calc_bandwidth,
    calc_bollinger_bands,
    calc_bollinger_series,
    calc_percent_b,
    get_bb_zone,
    get_volatility_signal,
    interpret_bb_position,
    is_favorable_for_covered_call,
    is_favorable_for_selling,
    is_favorable_for_short_put,
    is_squeeze,
)

# Moving Average (low-level)
from src.engine.position.technical.moving_average import (
    MovingAverageResult,
    calc_ema,
    calc_ema_series,
    calc_ma_distance,
    calc_sma,
    calc_sma_series,
    get_ma_alignment,
    get_ma_trend,
    interpret_ma_crossover,
    is_above_ma,
    is_ma_favorable_for_short_put,
)

# RSI (low-level)
from src.engine.position.technical.rsi import (
    calc_rsi,
    calc_rsi_series,
    get_rsi_zone,
    interpret_rsi,
    is_rsi_favorable_for_selling,
)

# Support/Resistance (low-level)
from src.engine.position.technical.support import (
    calc_resistance_distance,
    calc_resistance_level,
    calc_support_distance,
    calc_support_level,
    find_pivot_points,
    find_support_resistance,
    is_near_resistance,
    is_near_support,
)

__all__ = [
    # === Threshold Configuration ===
    "TechnicalThresholds",
    "DEFAULT_THRESHOLDS",
    # === Unified Interface (recommended) ===
    "calc_technical_score",
    "calc_technical_signal",
    # Getters (TechnicalData -> value)
    "get_sma",
    "get_ema",
    "get_rsi",
    "get_adx",
    "get_bollinger_bands",
    "get_trend_signal",
    "get_ma_alignment_str",
    # Strategy helpers
    "is_trend_favorable_for_short_put",
    "is_trend_favorable_for_covered_call",
    "is_trend_favorable_for_strangle",
    # Deprecated (backward compatibility)
    "evaluate_technical",
    "is_technically_favorable",
    # === Low-level functions ===
    # Moving Average
    "MovingAverageResult",
    "calc_sma",
    "calc_ema",
    "calc_sma_series",
    "calc_ema_series",
    "interpret_ma_crossover",
    "get_ma_trend",
    "is_above_ma",
    "calc_ma_distance",
    "get_ma_alignment",
    "is_ma_favorable_for_short_put",
    # ADX
    "ADXResult",
    "calc_true_range",
    "calc_tr_series",
    "calc_adx",
    "interpret_adx",
    "get_adx_trend_direction",
    "is_trending",
    "is_ranging",
    "is_adx_favorable_for_strangle",
    "is_adx_favorable_for_directional",
    # Bollinger Bands
    "BollingerBands",
    "calc_bollinger_bands",
    "calc_bollinger_series",
    "calc_percent_b",
    "calc_bandwidth",
    "is_squeeze",
    "interpret_bb_position",
    "get_bb_zone",
    "is_favorable_for_selling",
    "is_favorable_for_short_put",
    "is_favorable_for_covered_call",
    "get_volatility_signal",
    # RSI
    "calc_rsi",
    "calc_rsi_series",
    "interpret_rsi",
    "get_rsi_zone",
    "is_rsi_favorable_for_selling",
    # Support/Resistance
    "calc_support_level",
    "calc_resistance_level",
    "calc_support_distance",
    "calc_resistance_distance",
    "find_support_resistance",
    "find_pivot_points",
    "is_near_support",
    "is_near_resistance",
]
