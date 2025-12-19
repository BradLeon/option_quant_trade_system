"""Result models for analysis outputs."""

from dataclasses import dataclass
from typing import Any

from src.engine.models.enums import RatingSignal, TrendSignal


@dataclass
class FundamentalScore:
    """Fundamental analysis score result.

    Attributes:
        score: Overall score (0-100).
        rating: Overall rating signal.
        pe_score: P/E ratio score component.
        growth_score: Revenue growth score component.
        margin_score: Profit margin score component.
        analyst_score: Analyst rating score component.
        details: Additional details or breakdown.
    """

    score: float
    rating: RatingSignal
    pe_score: float | None = None
    growth_score: float | None = None
    margin_score: float | None = None
    analyst_score: float | None = None
    details: dict[str, Any] | None = None


@dataclass
class VolatilityScore:
    """Volatility analysis score result.

    Evaluates volatility conditions for option trading strategies.
    Higher scores indicate more favorable conditions for option selling.

    Attributes:
        score: Overall score (0-100).
        rating: Overall rating signal for option selling favorability.
        iv_rank: IV Rank (0-100).
        iv_hv_ratio: IV/HV ratio.
        iv_percentile: IV Percentile as decimal (0-1).
        pcr: Put/Call Ratio (excluded from scoring, for reference only).
        details: Additional details including interpretations.
    """

    score: float
    rating: RatingSignal
    iv_rank: float | None = None
    iv_hv_ratio: float | None = None
    iv_percentile: float | None = None
    pcr: float | None = None
    details: dict[str, Any] | None = None


@dataclass
class TrendResult:
    """Trend analysis result.

    Attributes:
        signal: The trend signal (bullish/bearish/neutral).
        strength: Trend strength (-1 to 1, where -1 is strong bearish, 1 is strong bullish).
        short_ma: Short-term moving average value.
        long_ma: Long-term moving average value.
    """

    signal: TrendSignal
    strength: float
    short_ma: float | None = None
    long_ma: float | None = None


@dataclass
class SupportResistance:
    """Support and resistance levels.

    Attributes:
        support: Support price level.
        resistance: Resistance price level.
        support_strength: Strength of support (number of touches or confidence).
        resistance_strength: Strength of resistance.
    """

    support: float
    resistance: float
    support_strength: float | None = None
    resistance_strength: float | None = None


@dataclass
class TechnicalScore:
    """Technical indicators aggregation with physical meaning.

    Aggregates and lightly processes technical indicators for option
    selling strategies. All fields have direct physical interpretation.

    Attributes:
        # Price context
        current_price: Current stock price.

        # Trend indicators (MA)
        sma20: 20-period Simple Moving Average.
        sma50: 50-period Simple Moving Average.
        sma200: 200-period Simple Moving Average.
        ema20: 20-period Exponential Moving Average.
        ma_alignment: MA alignment description (strong_bullish/bullish/neutral/bearish/strong_bearish).
        trend_signal: Trend direction from MA crossover.

        # Trend strength (ADX)
        adx: Average Directional Index (0-100, trend strength).
        plus_di: +DI (positive directional indicator).
        minus_di: -DI (negative directional indicator).

        # Momentum (RSI)
        rsi: Relative Strength Index (0-100).
        rsi_zone: RSI interpretation (overbought/neutral/oversold).

        # Bollinger Bands
        bb_upper: Upper Bollinger Band.
        bb_middle: Middle Bollinger Band (SMA20).
        bb_lower: Lower Bollinger Band.
        bb_percent_b: %B indicator (-inf to +inf, 0=lower, 1=upper).
        bb_bandwidth: Bandwidth (volatility measure).

        # Support/Resistance
        support: Nearest support level.
        resistance: Nearest resistance level.
        support_distance_pct: Distance to support as percentage.
        resistance_distance_pct: Distance to resistance as percentage.
    """

    # Price context
    current_price: float | None = None

    # Trend indicators (MA)
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    ema20: float | None = None
    ma_alignment: str | None = None
    trend_signal: TrendSignal = TrendSignal.NEUTRAL

    # Trend strength (ADX)
    adx: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None

    # Momentum (RSI)
    rsi: float | None = None
    rsi_zone: str | None = None

    # Bollinger Bands
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_percent_b: float | None = None
    bb_bandwidth: float | None = None

    # Support/Resistance
    support: float | None = None
    resistance: float | None = None
    support_distance_pct: float | None = None
    resistance_distance_pct: float | None = None

    # Volatility (ATR)
    atr: float | None = None  # Average True Range for strike buffer calculation


@dataclass
class TechnicalSignal:
    """Technical decision signals for option selling strategies.

    Converts technical indicators into actionable trading signals.
    Designed for Short Put, Covered Call, and Strangle strategies.

    Core logic:
    - ADX determines WHICH strategy to use
    - RSI + BB determine WHEN to open (contrarian entry)
    - Support/Resistance determine WHERE to set strike
    - MA alignment determines HOW aggressive (moneyness)

    Attributes:
        # 1. Market regime (ADX-based)
        market_regime: Current market state (ranging/trending_up/trending_down).
        trend_strength: Trend strength category (weak/moderate/strong).

        # 2. Strategy filter (ADX-based)
        allow_short_put: Whether Short Put is appropriate now.
        allow_short_call: Whether Short Call is appropriate now.
        allow_strangle: Whether Strangle is appropriate now.
        strategy_note: Explanation for strategy recommendation.

        # 3. Entry signals (RSI + BB, contrarian)
        sell_put_signal: Signal strength for selling Put (none/weak/moderate/strong).
        sell_call_signal: Signal strength for selling Call (none/weak/moderate/strong).
        entry_note: Explanation for entry signal.

        # 4. Key price levels (for strike selection)
        support_levels: List of (name, price) tuples for support.
        resistance_levels: List of (name, price) tuples for resistance.
        recommended_put_strike_zone: Price zone for Put strike (below support).
        recommended_call_strike_zone: Price zone for Call strike (above resistance).

        # 5. Moneyness bias (MA alignment)
        moneyness_bias: How aggressive to be (aggressive/neutral/conservative).
        moneyness_note: Explanation for moneyness recommendation.

        # 6. Stop loss reference
        stop_loss_level: Key support level for stop loss.
        stop_loss_note: Explanation for stop loss.

        # 7. Close signals
        close_put_signal: Signal strength for closing Put (none/weak/moderate/strong).
        close_call_signal: Signal strength for closing Call (none/weak/moderate/strong).
        close_note: Explanation for close signal.

        # 8. Danger period
        is_dangerous_period: Whether current period is dangerous for option selling.
        danger_warnings: List of danger warnings.
    """

    # 1. Market regime
    market_regime: str = "unknown"  # ranging, trending_up, trending_down
    trend_strength: str = "unknown"  # very_weak, weak, emerging, moderate, strong

    # 2. Strategy filter
    allow_short_put: bool = True
    allow_short_call: bool = True
    allow_strangle: bool = True
    strategy_note: str = ""

    # 3. Entry signals (contrarian)
    sell_put_signal: str = "none"  # none, weak, moderate, strong
    sell_call_signal: str = "none"  # none, weak, moderate, strong
    entry_note: str = ""

    # 4. Key price levels
    support_levels: list[tuple[str, float]] | None = None
    resistance_levels: list[tuple[str, float]] | None = None
    recommended_put_strike_zone: float | None = None  # Strike should be below this
    recommended_call_strike_zone: float | None = None  # Strike should be above this

    # 5. Moneyness bias
    moneyness_bias: str = "neutral"  # aggressive, neutral, conservative
    moneyness_note: str = ""

    # 6. Stop loss reference
    stop_loss_level: float | None = None
    stop_loss_note: str = ""

    # 7. Close signals
    close_put_signal: str = "none"  # none, weak, moderate, strong
    close_call_signal: str = "none"  # none, weak, moderate, strong
    close_note: str = ""

    # 8. Danger period
    is_dangerous_period: bool = False
    danger_warnings: list[str] | None = None
