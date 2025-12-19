"""Technical indicator thresholds configuration.

Configurable thresholds for technical signal generation.
Designed for option selling strategies (Short Put, Covered Call, Strangle).
"""

from dataclasses import dataclass


@dataclass
class TechnicalThresholds:
    """Technical indicator thresholds configuration.

    All thresholds are configurable for backtesting and optimization.

    Attributes:
        # ADX thresholds for market regime classification
        adx_very_weak: ADX below this = very weak trend (ideal for strangle)
        adx_weak: ADX below this = weak trend / ranging
        adx_emerging: ADX below this = emerging trend
        adx_strong: ADX above this = strong trend (high risk for sellers)
        adx_extreme: ADX above this = extreme trend (no contrarian trades)

        # RSI thresholds for entry signals
        rsi_stabilizing_low: Lower bound of put stabilization zone
        rsi_stabilizing_high: Upper bound of put stabilization zone
        rsi_exhaustion_low: Lower bound of call exhaustion zone
        rsi_exhaustion_high: Upper bound of call exhaustion zone
        rsi_extreme_low: Extreme oversold (danger/close signal)
        rsi_extreme_high: Extreme overbought (danger/close signal)

        # Bollinger Bands thresholds
        bb_squeeze: Bandwidth below this = squeeze (danger signal)
        bb_stabilizing_low: Lower bound of put stabilization zone
        bb_stabilizing_high: Upper bound of put stabilization zone
        bb_exhaustion_low: Lower bound of call exhaustion zone
        bb_exhaustion_high: Upper bound of call exhaustion zone

        # ATR strike buffer
        atr_buffer_multiplier: Strike = Support - k * ATR

        # Danger period detection
        danger_warning_threshold: Number of warnings to trigger danger period
        support_danger_pct: Distance to support below this % = danger
        resistance_danger_pct: Distance to resistance below this % = danger

        # Close signal thresholds
        close_adx_threshold: ADX above this triggers close signal on trend reversal
    """

    # ADX thresholds
    adx_very_weak: float = 15.0
    adx_weak: float = 20.0
    adx_emerging: float = 25.0
    adx_strong: float = 35.0
    adx_extreme: float = 45.0

    # RSI thresholds
    rsi_stabilizing_low: float = 30.0
    rsi_stabilizing_high: float = 45.0
    rsi_exhaustion_low: float = 55.0
    rsi_exhaustion_high: float = 70.0
    rsi_extreme_low: float = 20.0
    rsi_extreme_high: float = 80.0
    rsi_close_low: float = 25.0  # RSI below this = close put signal
    rsi_close_high: float = 75.0  # RSI above this = close call signal

    # Bollinger Bands thresholds
    bb_squeeze: float = 0.08
    bb_stabilizing_low: float = 0.1
    bb_stabilizing_high: float = 0.3
    bb_exhaustion_low: float = 0.7
    bb_exhaustion_high: float = 0.9

    # ATR strike buffer
    atr_buffer_multiplier: float = 1.5
    atr_period: int = 14

    # Danger period detection
    danger_warning_threshold: int = 2
    support_danger_pct: float = 2.0
    resistance_danger_pct: float = 2.0

    # Close signal thresholds
    close_adx_threshold: float = 25.0


# Default configuration
DEFAULT_THRESHOLDS = TechnicalThresholds()
