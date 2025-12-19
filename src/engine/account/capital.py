"""Capital management calculations.

Account-level module for return on capital metrics.
"""


def calc_roc(
    profit: float,
    capital: float,
    days_held: int | None = None,
) -> float | None:
    """Calculate Return on Capital (ROC).

    Physical meaning:
    - Measures profit relative to capital deployed
    - Annualized ROC allows comparison across different holding periods
    - Essential for evaluating capital efficiency

    Args:
        profit: Realized or unrealized profit.
        capital: Capital employed/at risk.
        days_held: Number of days position was held (optional, for annualization).

    Returns:
        ROC as decimal (e.g., 0.15 for 15% return).
        If days_held is provided, returns annualized ROC.
        Returns None if capital is zero.

    Example:
        >>> calc_roc(150, 1000)  # Simple ROC
        0.15
        >>> calc_roc(150, 1000, days_held=30)  # Annualized: 15% in 30 days
        1.825  # ~182.5% annualized
    """
    if capital is None or capital == 0:
        return None

    if profit is None:
        return None

    simple_roc = profit / capital

    # Annualize if days_held is provided
    if days_held is not None and days_held > 0:
        # Annualized ROC = simple_roc * (365 / days_held)
        return simple_roc * (365 / days_held)

    return simple_roc
