"""Generalized market trend analysis.

Account-level module for market trend analysis supporting multiple symbols.
Extends the base trend functions to support SPY, QQQ (US) and 2800.HK, 3032.HK (HK).
"""

from src.engine.models.enums import TrendSignal
from src.engine.models.sentiment import MarketTrend

from src.engine.account.sentiment.trend import (
    calc_sma,
    calc_trend_strength,
)


# Market-specific default parameters
# HK markets may have different volatility characteristics
MARKET_PARAMS: dict[str, dict] = {
    # US markets - standard parameters
    "SPY": {"short_window": 20, "long_window": 50, "threshold": 0.005},
    "QQQ": {"short_window": 20, "long_window": 50, "threshold": 0.005},
    # HK markets - Futu index symbols (preferred)
    "800000.HK": {"short_window": 20, "long_window": 50, "threshold": 0.007},  # HSI
    # HK markets - Yahoo index symbols
    "^HSI": {"short_window": 20, "long_window": 50, "threshold": 0.007},
    "HSTECH.HK": {"short_window": 20, "long_window": 50, "threshold": 0.008},
    # HK markets - ETF symbols (fallback)
    "2800.HK": {"short_window": 20, "long_window": 50, "threshold": 0.007},
    "3032.HK": {"short_window": 20, "long_window": 50, "threshold": 0.008},
}

# Default parameters for unknown symbols
DEFAULT_PARAMS = {"short_window": 20, "long_window": 50, "threshold": 0.005}


def calc_market_trend(
    symbol: str,
    prices: list[float],
    short_window: int | None = None,
    long_window: int | None = None,
    threshold: float | None = None,
) -> TrendSignal:
    """Calculate market trend for any symbol.

    Uses market-specific defaults if parameters not provided.
    Generalizes calc_spy_trend to support multiple markets.

    Args:
        symbol: Symbol being analyzed (e.g., "SPY", "QQQ", "2800.HK").
        prices: List of closing prices (oldest to newest).
        short_window: Short-term MA period (optional, uses market default).
        long_window: Long-term MA period (optional, uses market default).
        threshold: Trend threshold (optional, uses market default).

    Returns:
        TrendSignal: BULLISH if short > long, BEARISH if short < long, NEUTRAL otherwise.

    Example:
        >>> prices = list(range(100, 160))  # Uptrend
        >>> calc_market_trend("SPY", prices)
        <TrendSignal.BULLISH: 'bullish'>
        >>> calc_market_trend("2800.HK", prices)
        <TrendSignal.BULLISH: 'bullish'>
    """
    # Get market-specific defaults
    params = MARKET_PARAMS.get(symbol, DEFAULT_PARAMS)
    short_window = short_window if short_window is not None else params["short_window"]
    long_window = long_window if long_window is not None else params["long_window"]
    threshold = threshold if threshold is not None else params["threshold"]

    if prices is None or len(prices) < long_window:
        return TrendSignal.NEUTRAL

    short_ma = calc_sma(prices, short_window)
    long_ma = calc_sma(prices, long_window)

    if short_ma is None or long_ma is None:
        return TrendSignal.NEUTRAL

    # Calculate percentage difference
    diff_pct = (short_ma - long_ma) / long_ma

    if diff_pct > threshold:
        return TrendSignal.BULLISH
    elif diff_pct < -threshold:
        return TrendSignal.BEARISH
    else:
        return TrendSignal.NEUTRAL


def analyze_market_trend(
    symbol: str,
    prices: list[float],
    current_price: float | None = None,
    short_window: int | None = None,
    long_window: int | None = None,
) -> MarketTrend:
    """Complete market trend analysis for any symbol.

    Provides comprehensive trend analysis including signal, strength,
    moving averages, and 200-day MA position.

    Args:
        symbol: Symbol being analyzed (e.g., "SPY", "QQQ", "2800.HK").
        prices: Historical closing prices (oldest to newest).
        current_price: Current price for 200MA comparison.
        short_window: Short-term MA period (optional).
        long_window: Long-term MA period (optional).

    Returns:
        MarketTrend result with complete analysis.

    Example:
        >>> prices = [100 + i * 0.1 for i in range(250)]
        >>> result = analyze_market_trend("SPY", prices, current_price=125.0)
        >>> result.signal
        <TrendSignal.BULLISH: 'bullish'>
        >>> result.above_200ma
        True
    """
    params = MARKET_PARAMS.get(symbol, DEFAULT_PARAMS)
    short_window = short_window if short_window is not None else params["short_window"]
    long_window = long_window if long_window is not None else params["long_window"]

    # Calculate trend signal
    signal = calc_market_trend(symbol, prices, short_window, long_window)

    # Calculate trend strength
    strength = calc_trend_strength(prices, short_window) if prices else None
    strength = strength if strength is not None else 0.0

    # Calculate moving averages
    short_ma = None
    long_ma = None
    if prices:
        if len(prices) >= short_window:
            short_ma = calc_sma(prices, short_window)
        if len(prices) >= long_window:
            long_ma = calc_sma(prices, long_window)

    # Check 200-day MA position
    above_200ma = None
    if current_price is not None and prices and len(prices) >= 200:
        ma_200 = calc_sma(prices, 200)
        if ma_200 is not None:
            above_200ma = current_price > ma_200

    return MarketTrend(
        symbol=symbol,
        signal=signal,
        strength=strength,
        short_ma=short_ma,
        long_ma=long_ma,
        above_200ma=above_200ma,
    )


def get_trend_description(trend: MarketTrend) -> str:
    """Get a human-readable description of market trend.

    Args:
        trend: MarketTrend analysis result.

    Returns:
        String description of the trend.
    """
    signal_desc = {
        TrendSignal.BULLISH: "uptrend",
        TrendSignal.BEARISH: "downtrend",
        TrendSignal.NEUTRAL: "sideways",
    }

    strength_desc = ""
    if abs(trend.strength) > 0.7:
        strength_desc = "strong "
    elif abs(trend.strength) > 0.4:
        strength_desc = "moderate "
    elif abs(trend.strength) > 0.1:
        strength_desc = "weak "
    else:
        strength_desc = "very weak "

    base = signal_desc.get(trend.signal, "unknown")
    ma_status = ""
    if trend.above_200ma is not None:
        ma_status = ", above 200MA" if trend.above_200ma else ", below 200MA"

    return f"{trend.symbol}: {strength_desc}{base}{ma_status}"
