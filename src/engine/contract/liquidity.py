"""Liquidity metrics for option contracts.

Contract-level module for evaluating option liquidity.
"""

from typing import Any


def calc_bid_ask_spread(
    bid: float | None,
    ask: float | None,
) -> float | None:
    """Calculate bid-ask spread as a percentage.

    The spread is calculated as a percentage of the mid-price:
        spread = (ask - bid) / mid_price * 100

    A tighter spread indicates better liquidity.
    Rule of thumb:
        - < 5%: Very liquid
        - 5-10%: Acceptable
        - > 10%: Poor liquidity

    Args:
        bid: Bid price.
        ask: Ask price.

    Returns:
        Spread as a percentage (e.g., 5.0 for 5%).
        Returns None if inputs are invalid.

    Example:
        >>> calc_bid_ask_spread(1.90, 2.10)
        10.0  # 10% spread
    """
    if bid is None or ask is None:
        return None

    if bid <= 0 or ask <= 0:
        return None

    if ask < bid:
        return None

    mid_price = (bid + ask) / 2
    if mid_price == 0:
        return None

    spread_percent = (ask - bid) / mid_price * 100
    return spread_percent


def calc_bid_ask_spread_ratio(
    bid: float | None,
    ask: float | None,
) -> float | None:
    """Calculate bid-ask spread as a ratio (decimal).

    Returns the spread as a decimal for direct comparison with thresholds.
        ratio = (ask - bid) / mid_price

    Args:
        bid: Bid price.
        ask: Ask price.

    Returns:
        Spread as a decimal (e.g., 0.10 for 10%).
        Returns None if inputs are invalid.

    Example:
        >>> calc_bid_ask_spread_ratio(1.90, 2.10)
        0.10
    """
    spread_percent = calc_bid_ask_spread(bid, ask)
    if spread_percent is None:
        return None
    return spread_percent / 100


def calc_option_chain_volume(
    option_quotes: list[Any],
    include_zero_volume: bool = False,
) -> int:
    """Calculate total volume across an option chain.

    Sums up the volume of all option contracts in a chain.
    Higher total volume indicates a more liquid underlying.

    Args:
        option_quotes: List of OptionQuote objects with 'volume' attribute.
        include_zero_volume: Whether to include contracts with zero volume.

    Returns:
        Total volume across all contracts.

    Example:
        >>> quotes = [OptionQuote(volume=100), OptionQuote(volume=200)]
        >>> calc_option_chain_volume(quotes)
        300
    """
    total_volume = 0

    for quote in option_quotes:
        volume = getattr(quote, "volume", None)
        if volume is None:
            continue
        if volume == 0 and not include_zero_volume:
            continue
        total_volume += volume

    return total_volume


def calc_option_chain_open_interest(
    option_quotes: list[Any],
) -> int:
    """Calculate total open interest across an option chain.

    Sums up the open interest of all option contracts in a chain.
    Higher OI indicates more market participants and better liquidity.

    Args:
        option_quotes: List of OptionQuote objects with 'open_interest' attribute.

    Returns:
        Total open interest across all contracts.
    """
    total_oi = 0

    for quote in option_quotes:
        oi = getattr(quote, "open_interest", None)
        if oi is not None and oi > 0:
            total_oi += oi

    return total_oi


def is_liquid(
    bid: float | None,
    ask: float | None,
    open_interest: int | None = None,
    volume: int | None = None,
    max_spread_percent: float = 10.0,
    min_open_interest: int = 100,
    min_volume: int = 10,
) -> bool:
    """Check if an option contract meets liquidity requirements.

    Evaluates multiple liquidity factors:
    - Bid-ask spread
    - Open interest
    - Volume (optional)

    Args:
        bid: Bid price.
        ask: Ask price.
        open_interest: Current open interest.
        volume: Trading volume (optional).
        max_spread_percent: Maximum acceptable spread percentage.
        min_open_interest: Minimum required open interest.
        min_volume: Minimum required volume (if checking volume).

    Returns:
        True if contract meets all liquidity requirements.

    Example:
        >>> is_liquid(1.90, 2.10, open_interest=500, volume=50)
        True  # 10% spread, 500 OI, 50 volume all pass
    """
    # Check spread
    spread = calc_bid_ask_spread(bid, ask)
    if spread is None or spread > max_spread_percent:
        return False

    # Check open interest
    if open_interest is not None:
        if open_interest < min_open_interest:
            return False

    # Check volume (if provided)
    if volume is not None:
        if volume < min_volume:
            return False

    return True


def liquidity_score(
    bid: float | None,
    ask: float | None,
    open_interest: int | None = None,
    volume: int | None = None,
) -> float:
    """Calculate a composite liquidity score (0-100).

    Combines multiple liquidity factors into a single score.
    Higher score = better liquidity.

    Components:
    - Spread score (40%): Lower spread = higher score
    - OI score (40%): Higher OI = higher score (capped)
    - Volume score (20%): Higher volume = higher score (capped)

    Args:
        bid: Bid price.
        ask: Ask price.
        open_interest: Current open interest.
        volume: Trading volume.

    Returns:
        Liquidity score (0-100).

    Example:
        >>> liquidity_score(1.95, 2.05, open_interest=1000, volume=100)
        85.0  # Very liquid
    """
    score = 0.0

    # Spread score (40% weight)
    # 0% spread = 100, 10% spread = 0
    spread = calc_bid_ask_spread(bid, ask)
    if spread is not None:
        spread_score = max(0, 100 - spread * 10)
        score += spread_score * 0.40
    else:
        score += 0  # No spread data

    # OI score (40% weight)
    # 0 OI = 0, 1000+ OI = 100
    if open_interest is not None and open_interest > 0:
        oi_score = min(100, open_interest / 10)  # Cap at 1000 OI
        score += oi_score * 0.40
    else:
        score += 0

    # Volume score (20% weight)
    # 0 volume = 0, 100+ volume = 100
    if volume is not None and volume > 0:
        vol_score = min(100, volume)  # Cap at 100 volume
        score += vol_score * 0.20
    else:
        score += 0

    return score
