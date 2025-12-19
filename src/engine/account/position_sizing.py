"""Position sizing calculations using Kelly criterion.

Account-level module for optimal bet sizing.
"""


def calc_kelly(win_rate: float, win_loss_ratio: float) -> float | None:
    """Calculate Kelly criterion optimal bet fraction.

    Formula: Kelly% = W - (1-W)/R
    where W = win rate, R = win/loss ratio

    Physical meaning:
    - Optimal fraction of bankroll to risk on each trade
    - Maximizes long-term geometric growth rate
    - Should typically be scaled down (half-Kelly) for safety

    Args:
        win_rate: Probability of winning (0-1).
        win_loss_ratio: Ratio of average win to average loss (e.g., 2.0 means avg win is 2x avg loss).

    Returns:
        Kelly fraction (0-1) representing optimal bet size as fraction of bankroll.
        Returns None if inputs are invalid.
        Returns 0 if Kelly is negative (don't bet).

    Example:
        >>> calc_kelly(0.6, 1.5)  # 60% win rate, 1.5:1 win/loss ratio
        0.3333...  # Bet 33% of bankroll
    """
    if win_rate is None or win_loss_ratio is None:
        return None

    if win_rate < 0 or win_rate > 1:
        return None

    if win_loss_ratio <= 0:
        return None

    kelly = win_rate - (1 - win_rate) / win_loss_ratio

    # Don't bet if Kelly is negative
    return max(0.0, kelly)


def calc_half_kelly(win_rate: float, win_loss_ratio: float) -> float | None:
    """Calculate half-Kelly for more conservative position sizing.

    Half-Kelly is commonly used to reduce volatility while capturing
    most of the growth benefits.

    Args:
        win_rate: Probability of winning (0-1).
        win_loss_ratio: Ratio of average win to average loss.

    Returns:
        Half of the Kelly fraction.
    """
    kelly = calc_kelly(win_rate, win_loss_ratio)
    if kelly is None:
        return None
    return kelly / 2


def calc_fractional_kelly(
    win_rate: float,
    win_loss_ratio: float,
    fraction: float = 0.5,
) -> float | None:
    """Calculate fractional Kelly for custom risk tolerance.

    Args:
        win_rate: Probability of winning (0-1).
        win_loss_ratio: Ratio of average win to average loss.
        fraction: Fraction of Kelly to use (e.g., 0.25 for quarter Kelly).

    Returns:
        Fractional Kelly value.
    """
    if fraction <= 0 or fraction > 1:
        return None

    kelly = calc_kelly(win_rate, win_loss_ratio)
    if kelly is None:
        return None
    return kelly * fraction


def interpret_kelly(kelly: float) -> str:
    """Interpret Kelly fraction value.

    Args:
        kelly: Kelly fraction (0-1).

    Returns:
        Interpretation string.
    """
    if kelly <= 0:
        return "no_edge"  # No positive edge, don't bet
    elif kelly < 0.05:
        return "marginal"  # Marginal edge
    elif kelly < 0.15:
        return "small"  # Small but tradeable edge
    elif kelly < 0.25:
        return "moderate"  # Moderate edge
    elif kelly < 0.40:
        return "strong"  # Strong edge
    else:
        return "very_strong"  # Very strong edge (be cautious, may be overfitting)


def calc_kelly_from_trades(trades: list[float]) -> float | None:
    """Calculate Kelly criterion from a list of trade P&L.

    Derives win rate and win/loss ratio from historical trades,
    then calculates the Kelly fraction.

    Args:
        trades: List of trade profits/losses (positive = win, negative = loss).

    Returns:
        Kelly fraction (0-1), or None if insufficient data.

    Example:
        >>> trades = [100, -50, 150, -60, 200, -40]
        >>> kelly = calc_kelly_from_trades(trades)
        >>> kelly > 0  # Should have positive edge
        True
    """
    if trades is None or len(trades) == 0:
        return None

    wins = [t for t in trades if t > 0]
    losses = [abs(t) for t in trades if t < 0]

    if len(wins) == 0 or len(losses) == 0:
        return None

    win_rate = len(wins) / len(trades)
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)

    if avg_loss == 0:
        return None

    win_loss_ratio = avg_win / avg_loss

    return calc_kelly(win_rate, win_loss_ratio)
