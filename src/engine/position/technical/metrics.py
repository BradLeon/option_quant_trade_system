"""Technical metrics extraction and analysis.

Position-level module for technical analysis of individual securities.
Uses TechnicalData data model from data layer.

Two main functions:
1. calc_technical_score(): Aggregates raw indicator values (TechnicalData -> TechnicalScore)
2. calc_technical_signal(): Generates decision signals (TechnicalData -> TechnicalSignal)

Design based on option selling strategy framework:
- ADX -> Strategy selection (which strategy to use)
- RSI + BB -> Entry timing (stabilization, not contrarian extremes)
- ATR -> Strike buffer (dynamic based on volatility)
- Support/Resistance -> Strike selection (where to set strike)
- MA alignment -> Moneyness (how aggressive)
"""

from src.data.models.technical import TechnicalData
from src.engine.models.enums import TrendSignal
from src.engine.models.result import TechnicalScore, TechnicalSignal

from src.engine.position.technical.adx import (
    ADXResult,
    calc_adx,
)
from src.engine.position.technical.bollinger_bands import (
    BollingerBands,
    calc_bollinger_bands,
    calc_percent_b,
)
from src.engine.position.technical.moving_average import (
    calc_ema,
    calc_sma,
    get_ma_alignment,
    get_ma_trend,
)
from src.engine.position.technical.rsi import (
    calc_rsi,
    get_rsi_zone,
)
from src.engine.position.technical.support import (
    find_support_resistance,
)
from src.engine.position.technical.thresholds import (
    TechnicalThresholds,
    DEFAULT_THRESHOLDS,
)


# =============================================================================
# ATR Calculation
# =============================================================================

def calc_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float | None:
    """Calculate Average True Range (ATR).

    ATR measures volatility by decomposing the entire range of a security
    for a given period.

    Args:
        highs: List of high prices.
        lows: List of low prices.
        closes: List of close prices.
        period: ATR period (default 14).

    Returns:
        ATR value or None if insufficient data.
    """
    if len(closes) < period + 1:
        return None

    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


# =============================================================================
# Getter functions (TechnicalData -> single value)
# =============================================================================

def get_sma(data: TechnicalData, period: int = 20) -> float | None:
    """Get Simple Moving Average from technical data."""
    if data is None or len(data.closes) < period:
        return None
    return calc_sma(data.closes, period)


def get_ema(data: TechnicalData, period: int = 20) -> float | None:
    """Get Exponential Moving Average from technical data."""
    if data is None or len(data.closes) < period:
        return None
    return calc_ema(data.closes, period)


def get_rsi(data: TechnicalData, period: int = 14) -> float | None:
    """Get RSI from technical data."""
    if data is None or len(data.closes) < period + 1:
        return None
    return calc_rsi(data.closes, period)


def get_adx(data: TechnicalData, period: int = 14) -> ADXResult | None:
    """Get ADX with +DI/-DI from technical data."""
    if data is None or not data.has_ohlc:
        return None
    if len(data.closes) < 2 * period:
        return None
    return calc_adx(data.highs, data.lows, data.closes, period)


def get_bollinger_bands(
    data: TechnicalData,
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerBands | None:
    """Get Bollinger Bands from technical data."""
    if data is None or len(data.closes) < period:
        return None
    return calc_bollinger_bands(data.closes, period, num_std)


def get_trend_signal(data: TechnicalData) -> TrendSignal:
    """Get trend signal from MA analysis."""
    if data is None or len(data.closes) < 50:
        return TrendSignal.NEUTRAL
    return get_ma_trend(data.closes, short_period=20, long_period=50)


def get_ma_alignment_str(data: TechnicalData) -> str:
    """Get MA alignment description."""
    if data is None or len(data.closes) < 200:
        return "unknown"
    return get_ma_alignment(data.closes, periods=[20, 50, 200])


def get_atr(data: TechnicalData, period: int = 14) -> float | None:
    """Get ATR from technical data."""
    if data is None or not data.has_ohlc:
        return None
    return calc_atr(data.highs, data.lows, data.closes, period)


# =============================================================================
# calc_technical_score: Aggregate raw indicator values
# =============================================================================

def calc_technical_score(data: TechnicalData) -> TechnicalScore:
    """Calculate technical score by aggregating indicator values.

    This function aggregates raw technical indicator values into a single
    TechnicalScore object. All fields have direct physical interpretation.

    Args:
        data: TechnicalData object with OHLCV data.

    Returns:
        TechnicalScore with aggregated indicator values.
    """
    if data is None or len(data.closes) < 20:
        return TechnicalScore()

    # Current price
    current_price = data.current_price

    # Moving Averages
    sma20 = get_sma(data, 20)
    sma50 = get_sma(data, 50) if len(data.closes) >= 50 else None
    sma200 = get_sma(data, 200) if len(data.closes) >= 200 else None
    ema20 = get_ema(data, 20)

    # MA alignment and trend
    ma_alignment = get_ma_alignment_str(data)
    trend_signal = get_trend_signal(data)

    # ADX
    adx_result = get_adx(data)
    adx = adx_result.adx if adx_result else None
    plus_di = adx_result.plus_di if adx_result else None
    minus_di = adx_result.minus_di if adx_result else None

    # RSI
    rsi = get_rsi(data)
    rsi_zone = get_rsi_zone(rsi) if rsi is not None else None

    # Bollinger Bands
    bb = get_bollinger_bands(data)
    bb_upper = bb.upper if bb else None
    bb_middle = bb.middle if bb else None
    bb_lower = bb.lower if bb else None
    bb_percent_b = calc_percent_b(current_price, bb) if bb and current_price else None
    bb_bandwidth = bb.bandwidth if bb else None

    # ATR
    atr = get_atr(data)

    # Support/Resistance
    support = None
    resistance = None
    support_distance_pct = None
    resistance_distance_pct = None

    if len(data.closes) >= 20:
        sr = find_support_resistance(data.closes, window=20)
        support = sr.support
        resistance = sr.resistance
        if current_price and support:
            support_distance_pct = (current_price - support) / support * 100
        if current_price and resistance:
            resistance_distance_pct = (resistance - current_price) / current_price * 100

    return TechnicalScore(
        current_price=current_price,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        ema20=ema20,
        ma_alignment=ma_alignment,
        trend_signal=trend_signal,
        adx=adx,
        plus_di=plus_di,
        minus_di=minus_di,
        rsi=rsi,
        rsi_zone=rsi_zone,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        bb_percent_b=bb_percent_b,
        bb_bandwidth=bb_bandwidth,
        support=support,
        resistance=resistance,
        support_distance_pct=support_distance_pct,
        resistance_distance_pct=resistance_distance_pct,
        atr=atr,
    )


# =============================================================================
# calc_technical_signal: Generate decision signals
# =============================================================================

def calc_technical_signal(
    data: TechnicalData,
    thresholds: TechnicalThresholds = DEFAULT_THRESHOLDS,
) -> TechnicalSignal:
    """Calculate technical decision signals for option selling strategies.

    Converts technical indicators into actionable trading signals based on:
    - ADX -> Strategy selection (which strategy)
    - RSI + BB -> Entry timing (stabilization logic, not contrarian extremes)
    - ATR -> Strike buffer (dynamic based on volatility)
    - Support/Resistance -> Strike selection (where)
    - MA alignment -> Moneyness (how aggressive)

    Key improvements over contrarian approach:
    - Entry on stabilization, not during extreme moves (avoid catching falling knives)
    - Strong trend filter (no contrarian trades when ADX > extreme threshold)
    - BB Squeeze detection (danger signal for option sellers)
    - Close signals for risk management

    Args:
        data: TechnicalData object with OHLCV data.
        thresholds: TechnicalThresholds configuration object.

    Returns:
        TechnicalSignal with decision signals.
    """
    if data is None or len(data.closes) < 20:
        return TechnicalSignal()

    # First get the score for raw values
    score = calc_technical_score(data)
    current_price = score.current_price

    # Extract key indicators
    adx = score.adx
    plus_di = score.plus_di
    minus_di = score.minus_di
    rsi = score.rsi
    bb_percent_b = score.bb_percent_b
    bb_bandwidth = score.bb_bandwidth
    atr = score.atr

    # =========================================================================
    # 1. Market Regime (ADX-based with configurable thresholds)
    # =========================================================================
    if adx is None:
        market_regime = "unknown"
        trend_strength = "unknown"
    elif adx < thresholds.adx_very_weak:
        market_regime = "ranging"
        trend_strength = "very_weak"
    elif adx < thresholds.adx_weak:
        market_regime = "ranging"
        trend_strength = "weak"
    elif adx < thresholds.adx_emerging:
        if plus_di and minus_di:
            market_regime = "trending_up" if plus_di > minus_di else "trending_down"
        else:
            market_regime = "ranging"
        trend_strength = "emerging"
    elif adx < thresholds.adx_strong:
        if plus_di and minus_di:
            market_regime = "trending_up" if plus_di > minus_di else "trending_down"
        else:
            market_regime = "unknown"
        trend_strength = "moderate"
    else:  # adx >= adx_strong
        if plus_di and minus_di:
            market_regime = "trending_up" if plus_di > minus_di else "trending_down"
        else:
            market_regime = "unknown"
        trend_strength = "strong"

    # =========================================================================
    # 2. Strategy Filter (ADX + BB Squeeze)
    # =========================================================================
    allow_short_put = True
    allow_short_call = True
    allow_strangle = True
    strategy_notes = []

    # Check BB Squeeze (danger signal)
    is_squeezing = bb_bandwidth is not None and bb_bandwidth < thresholds.bb_squeeze
    if is_squeezing:
        allow_strangle = False
        strategy_notes.append("BB Squeeze: 变盘在即且权利金低，禁用Strangle")

    # ADX-based filtering
    if adx is not None:
        if adx < thresholds.adx_weak:
            strategy_notes.append(f"ADX<{thresholds.adx_weak:.0f}: 震荡市场，适合Strangle")
        elif adx >= thresholds.adx_strong:
            if market_regime == "trending_up":
                allow_short_call = False
                allow_strangle = False
                strategy_notes.append(f"ADX>{thresholds.adx_strong:.0f}+上涨: 禁用Short Call和Strangle")
            elif market_regime == "trending_down":
                allow_short_put = False
                allow_strangle = False
                strategy_notes.append(f"ADX>{thresholds.adx_strong:.0f}+下跌: 禁用Short Put和Strangle")
        else:
            strategy_notes.append(f"ADX={adx:.0f}: 中等趋势，各策略均可")

    strategy_note = "; ".join(strategy_notes)

    # =========================================================================
    # 3. Entry Signals (Stabilization logic, not contrarian extremes)
    # =========================================================================
    sell_put_signal = "none"
    sell_call_signal = "none"
    entry_notes = []

    # Strong trend filter - no contrarian trades in extreme trends
    strong_downtrend = (
        adx is not None
        and adx > thresholds.adx_extreme
        and minus_di is not None
        and plus_di is not None
        and minus_di > plus_di
    )
    strong_uptrend = (
        adx is not None
        and adx > thresholds.adx_extreme
        and plus_di is not None
        and minus_di is not None
        and plus_di > minus_di
    )

    if rsi is not None and bb_percent_b is not None:
        # Sell Put signals (stabilization after oversold, not during oversold)
        if strong_downtrend and rsi < thresholds.rsi_stabilizing_low:
            # Block signal in extreme downtrend
            sell_put_signal = "none"
            entry_notes.append(f"ADX>{thresholds.adx_extreme:.0f}强空头+RSI超卖: 谨防钝化，暂停卖Put")
        elif (
            thresholds.rsi_stabilizing_low <= rsi <= thresholds.rsi_stabilizing_high
            and thresholds.bb_stabilizing_low <= bb_percent_b <= thresholds.bb_stabilizing_high
        ):
            sell_put_signal = "strong"
            entry_notes.append(f"RSI={rsi:.0f}和BB={bb_percent_b:.2f}企稳区: 适合卖Put")
        elif (
            thresholds.rsi_stabilizing_low <= rsi <= thresholds.rsi_stabilizing_high
            or thresholds.bb_stabilizing_low <= bb_percent_b <= thresholds.bb_stabilizing_high
        ):
            sell_put_signal = "moderate"
            entry_notes.append(f"RSI={rsi:.0f}, BB={bb_percent_b:.2f}: 中等卖Put信号")
        elif rsi < 50 and bb_percent_b < 0.4:
            sell_put_signal = "weak"
            entry_notes.append(f"RSI={rsi:.0f}, BB={bb_percent_b:.2f}: 偏弱卖Put信号")

        # Sell Call signals (exhaustion, not extreme overbought)
        if strong_uptrend and rsi > thresholds.rsi_exhaustion_high:
            # Block signal in extreme uptrend
            sell_call_signal = "none"
            entry_notes.append(f"ADX>{thresholds.adx_extreme:.0f}强多头+RSI超买: 谨防继续上涨，暂停卖Call")
        elif (
            thresholds.rsi_exhaustion_low <= rsi <= thresholds.rsi_exhaustion_high
            and thresholds.bb_exhaustion_low <= bb_percent_b <= thresholds.bb_exhaustion_high
        ):
            sell_call_signal = "strong"
            entry_notes.append(f"RSI={rsi:.0f}和BB={bb_percent_b:.2f}动能衰竭区: 适合卖Call")
        elif (
            thresholds.rsi_exhaustion_low <= rsi <= thresholds.rsi_exhaustion_high
            or thresholds.bb_exhaustion_low <= bb_percent_b <= thresholds.bb_exhaustion_high
        ):
            sell_call_signal = "moderate"
            entry_notes.append(f"RSI={rsi:.0f}, BB={bb_percent_b:.2f}: 中等卖Call信号")
        elif rsi > 50 and bb_percent_b > 0.6:
            sell_call_signal = "weak"
            entry_notes.append(f"RSI={rsi:.0f}, BB={bb_percent_b:.2f}: 偏弱卖Call信号")

    entry_note = "; ".join(entry_notes) if entry_notes else "无明显开仓信号"

    # =========================================================================
    # 4. Close Signals
    # =========================================================================
    close_put_signal = "none"
    close_call_signal = "none"
    close_notes = []

    # Close Put on trend reversal to bearish
    if market_regime == "trending_down" and adx is not None and adx > thresholds.close_adx_threshold:
        close_put_signal = "strong"
        close_notes.append(f"趋势转空+ADX>{thresholds.close_adx_threshold:.0f}: 建议平仓Short Put")

    # Close Call on trend reversal to bullish
    if market_regime == "trending_up" and adx is not None and adx > thresholds.close_adx_threshold:
        close_call_signal = "strong"
        close_notes.append(f"趋势转多+ADX>{thresholds.close_adx_threshold:.0f}: 建议平仓Short Call")

    # RSI extreme close signals
    if rsi is not None:
        if rsi < thresholds.rsi_close_low:
            if close_put_signal == "none":
                close_put_signal = "moderate"
            close_notes.append(f"RSI={rsi:.0f}<{thresholds.rsi_close_low:.0f}极度超卖: 考虑平仓Short Put")
        if rsi > thresholds.rsi_close_high:
            if close_call_signal == "none":
                close_call_signal = "moderate"
            close_notes.append(f"RSI={rsi:.0f}>{thresholds.rsi_close_high:.0f}极度超买: 考虑平仓Short Call")

    close_note = "; ".join(close_notes) if close_notes else ""

    # =========================================================================
    # 5. Key Price Levels (for Strike Selection)
    # =========================================================================
    support_levels = []
    resistance_levels = []

    # Add MA levels as support/resistance
    if score.sma200 and current_price:
        if current_price > score.sma200:
            support_levels.append(("MA200", score.sma200))
        else:
            resistance_levels.append(("MA200", score.sma200))

    if score.sma50 and current_price:
        if current_price > score.sma50:
            support_levels.append(("MA50", score.sma50))
        else:
            resistance_levels.append(("MA50", score.sma50))

    if score.sma20 and current_price:
        if current_price > score.sma20:
            support_levels.append(("MA20", score.sma20))
        else:
            resistance_levels.append(("MA20", score.sma20))

    # Add recent support/resistance
    if score.support:
        support_levels.append(("近期低点", score.support))
    if score.resistance:
        resistance_levels.append(("近期高点", score.resistance))

    # Add BB bands
    if score.bb_lower:
        support_levels.append(("BB下轨", score.bb_lower))
    if score.bb_upper:
        resistance_levels.append(("BB上轨", score.bb_upper))

    # Sort by price (support descending, resistance ascending)
    support_levels.sort(key=lambda x: x[1], reverse=True)
    resistance_levels.sort(key=lambda x: x[1])

    # Recommended strike zones (ATR-based buffer)
    recommended_put_strike_zone = None
    recommended_call_strike_zone = None

    if support_levels:
        strongest_support = support_levels[0][1]
        if atr is not None:
            # Dynamic buffer: support - k * ATR
            recommended_put_strike_zone = strongest_support - atr * thresholds.atr_buffer_multiplier
        else:
            # Fallback to 5%
            recommended_put_strike_zone = strongest_support * 0.95

    if resistance_levels:
        strongest_resistance = resistance_levels[0][1]
        if atr is not None:
            # Dynamic buffer: resistance + k * ATR
            recommended_call_strike_zone = strongest_resistance + atr * thresholds.atr_buffer_multiplier
        else:
            # Fallback to 5%
            recommended_call_strike_zone = strongest_resistance * 1.05

    # =========================================================================
    # 6. Moneyness Bias (MA Alignment)
    # =========================================================================
    ma_alignment = score.ma_alignment

    if ma_alignment in ("strong_bullish", "bullish"):
        moneyness_bias = "aggressive"
        moneyness_note = "上升趋势: 可激进卖Put, 保守卖Call"
    elif ma_alignment in ("strong_bearish", "bearish"):
        moneyness_bias = "conservative"
        moneyness_note = "下降趋势: 保守卖Put, 可激进卖Call"
    else:
        moneyness_bias = "neutral"
        moneyness_note = "中性/震荡: 平衡激进度"

    # =========================================================================
    # 7. Stop Loss Reference
    # =========================================================================
    stop_loss_level = None
    stop_loss_note = ""

    if support_levels:
        stop_loss_level = support_levels[0][1]
        stop_loss_note = f"关键支撑位 {support_levels[0][0]}={stop_loss_level:.2f}, 若有效跌破则止损"

    # =========================================================================
    # 8. Danger Period Detection
    # =========================================================================
    danger_warnings = []

    if is_squeezing:
        danger_warnings.append("布林带极度收窄(Squeeze)，即将突破")
    if adx is not None and adx > 30:
        danger_warnings.append(f"ADX={adx:.0f}，趋势较强")
    if score.support_distance_pct is not None and score.support_distance_pct < thresholds.support_danger_pct:
        danger_warnings.append(f"价格距支撑仅{score.support_distance_pct:.1f}%")
    if score.resistance_distance_pct is not None and score.resistance_distance_pct < thresholds.resistance_danger_pct:
        danger_warnings.append(f"价格距阻力仅{score.resistance_distance_pct:.1f}%")
    if rsi is not None and (rsi > thresholds.rsi_extreme_high or rsi < thresholds.rsi_extreme_low):
        danger_warnings.append(f"RSI={rsi:.0f}处于极端位置")

    is_dangerous_period = len(danger_warnings) >= thresholds.danger_warning_threshold

    return TechnicalSignal(
        market_regime=market_regime,
        trend_strength=trend_strength,
        allow_short_put=allow_short_put,
        allow_short_call=allow_short_call,
        allow_strangle=allow_strangle,
        strategy_note=strategy_note,
        sell_put_signal=sell_put_signal,
        sell_call_signal=sell_call_signal,
        entry_note=entry_note,
        support_levels=support_levels if support_levels else None,
        resistance_levels=resistance_levels if resistance_levels else None,
        recommended_put_strike_zone=recommended_put_strike_zone,
        recommended_call_strike_zone=recommended_call_strike_zone,
        moneyness_bias=moneyness_bias,
        moneyness_note=moneyness_note,
        stop_loss_level=stop_loss_level,
        stop_loss_note=stop_loss_note,
        close_put_signal=close_put_signal,
        close_call_signal=close_call_signal,
        close_note=close_note,
        is_dangerous_period=is_dangerous_period,
        danger_warnings=danger_warnings if danger_warnings else None,
    )


# =============================================================================
# Strategy-specific helpers
# =============================================================================

def is_trend_favorable_for_short_put(data: TechnicalData) -> bool:
    """Check if trend is favorable for Short Put strategy.

    Short Put works best in bullish or neutral markets with ADX not too high.
    """
    signal = calc_technical_signal(data)
    return signal.allow_short_put and signal.market_regime != "trending_down"


def is_trend_favorable_for_covered_call(data: TechnicalData) -> bool:
    """Check if trend is favorable for Covered Call strategy.

    Covered Call works best in neutral to slightly bullish markets.
    """
    signal = calc_technical_signal(data)
    return signal.allow_short_call and signal.market_regime != "trending_up"


def is_trend_favorable_for_strangle(data: TechnicalData) -> bool:
    """Check if trend is favorable for Short Strangle strategy.

    Short Strangle works best in ranging (low ADX) markets.
    """
    signal = calc_technical_signal(data)
    return signal.allow_strangle and signal.market_regime == "ranging"


# =============================================================================
# Backward compatibility (deprecated)
# =============================================================================

def evaluate_technical(data: TechnicalData) -> TechnicalScore:
    """[DEPRECATED] Use calc_technical_score() instead.

    This function is kept for backward compatibility.
    """
    return calc_technical_score(data)


def is_technically_favorable(data: TechnicalData, min_score: float = 60.0) -> bool:
    """[DEPRECATED] Use calc_technical_signal() instead.

    This function is kept for backward compatibility.
    Returns True if there's any entry signal.
    """
    signal = calc_technical_signal(data)
    return (
        signal.sell_put_signal in ("moderate", "strong")
        or signal.sell_call_signal in ("moderate", "strong")
    )
