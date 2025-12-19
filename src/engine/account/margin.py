"""Margin management calculations.

Account-level module for margin-related metrics.
"""


def calc_margin_utilization(
    margin_used: float,
    total_margin: float,
) -> float | None:
    """Calculate margin utilization percentage.

    Physical meaning:
    - Measures how much of available margin is currently being used
    - 50% utilization means half of margin capacity is deployed
    - High utilization (>80%) indicates limited capacity for new positions

    Args:
        margin_used: Current margin used.
        total_margin: Total available margin.

    Returns:
        Utilization as decimal (e.g., 0.50 for 50%).
        Returns None if total_margin is zero.

    Example:
        >>> calc_margin_utilization(50000, 100000)
        0.5
    """
    if total_margin is None or total_margin == 0:
        return None

    if margin_used is None:
        return None

    return margin_used / total_margin
