"""Position-level risk and return calculations.

Single-trade metrics for individual positions.
Includes Position Risk Exposure Index (PREI) for tail risk assessment.

All functions are designed to accept Position objects directly.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.models.position import Position


# ============================================================================
# Normalization Helper (shared with portfolio/composite.py)
# ============================================================================


def _normalize_to_01(value: float, k: float = 1.0) -> float:
    """Normalize a non-negative value to 0-1 range using sigmoid-like function.

    Formula: normalized = value / (value + k)

    Properties:
    - value=0 -> 0
    - value=k -> 0.5
    - value->inf -> 1

    Args:
        value: Non-negative value to normalize.
        k: Scaling constant. When value=k, output is 0.5.

    Returns:
        Normalized value in range [0, 1).
    """
    if value <= 0:
        return 0.0
    return value / (value + k)


# ============================================================================
# Position Risk Exposure Index (PREI)
# ============================================================================


def calc_prei(
    position: Position,
    weights: tuple[float, float, float] = (0.40, 0.30, 0.30),
) -> float | None:
    """Calculate Position Risk Exposure Index (PREI) for a single position.

    PREI measures tail risk exposure based on:
    - Gamma risk: Convexity risk from large underlying moves
    - Vega risk: Volatility spike risk
    - DTE risk: Near-expiry gamma amplification

    Algorithm is aligned with calc_portfolio_prei, using sigmoid normalization.

    Formula:
        PREI = (w1 × Gamma_Risk + w2 × Vega_Risk + w3 × DTE_Risk) × 100

        Where each component is normalized to 0-1:
        - Gamma_Risk = |gamma| / (|gamma| + k), k=1.0
        - Vega_Risk = |vega| / (|vega| + k), k=100.0
        - DTE_Risk = sqrt(1 / max(1, DTE))

    Args:
        position: Position object with gamma, vega, underlying_price, dte.
        weights: Tuple of (w1, w2, w3) weights for gamma, vega, and DTE risk.
            Default: (0.40, 0.30, 0.30).

    Returns:
        PREI score (0-100). Higher = more risk exposure.
        Returns None if position lacks required data.

    Example:
        >>> from src.engine.models.position import Position
        >>> pos = Position(
        ...     symbol="AAPL",
        ...     quantity=1,
        ...     gamma=0.05,
        ...     vega=20.0,
        ...     underlying_price=500.0,
        ...     dte=3,
        ... )
        >>> calc_prei(pos)
        45.2  # Moderate-high risk
    """
    gamma = position.gamma
    vega = position.vega
    dte = position.dte

    # Validate required fields
    if gamma is None or vega is None:
        return None
    if dte is None:
        return None

    w1, w2, w3 = weights

    # Gamma Risk: sigmoid normalization, k=10.0 means gamma=10 -> risk=0.5
    gamma_risk = _normalize_to_01(abs(gamma), k=1.0)

    # Vega Risk: sigmoid normalization, k=1.0 means vega=1 -> risk=0.5
    vega_risk = _normalize_to_01(abs(vega), k=1.0)

    # DTE Risk: sqrt(1/DTE), already in 0-1 range for DTE >= 1
    dte_clamped = max(1, dte)
    dte_risk = math.sqrt(1.0 / dte_clamped)

    # Weighted combination, scale to 0-100
    prei = (w1 * gamma_risk + w2 * vega_risk + w3 * dte_risk) * 100

    return prei


# ============================================================================
# Theta/Gamma Ratio (TGR)
# ============================================================================


def calc_tgr(position: Position) -> float | None:
    """Calculate Theta/Gamma Ratio (TGR) for a single position.

    TGR measures the ratio of daily time decay income to gamma risk.
    Higher TGR indicates more favorable risk/reward for theta strategies.

    Physical meaning:
    - Theta is daily income from time decay (negative value = you earn)
    - Gamma is the rate of delta change (convexity risk)
    - High TGR = more theta income per unit of gamma risk
    - Typical target: TGR > 2-3 for income strategies

    Args:
        position: Position object with theta and gamma.

    Returns:
        TGR value. Higher is better for theta strategies.
        Returns None if gamma is zero or data is missing.

    Example:
        >>> from src.engine.models.position import Position
        >>> pos = Position(symbol="AAPL", quantity=1, theta=-0.05, gamma=0.01)
        >>> calc_tgr(pos)
        5.0
    """
    theta = position.theta
    gamma = position.gamma

    if gamma is None or gamma == 0:
        return None
    if theta is None:
        return None

    return abs(theta) / abs(gamma)


# ============================================================================
# Return on Capital (ROC)
# ============================================================================


def calc_roc_from_dte(
    profit: float,
    capital: float,
    dte: int,
) -> float | None:
    """Calculate annualized ROC based on Days to Expiration.

    Convenience function for option trades where DTE is known upfront.

    Args:
        profit: Expected or realized profit.
        capital: Capital at risk (e.g., margin requirement).
        dte: Days to expiration when trade was opened.

    Returns:
        Annualized ROC as decimal.
        Returns None if inputs are invalid.

    Example:
        >>> calc_roc_from_dte(65, 5500, dte=30)  # $65 profit on $5500 margin, 30 DTE
        0.144  # 14.4% annualized
    """
    if capital is None or capital == 0:
        return None

    if profit is None:
        return None

    if dte is None or dte <= 0:
        return None

    simple_roc = profit / capital
    # Annualize: ROC × (365 / days_held)
    return simple_roc * (365 / dte)


# ============================================================================
# Risk/Reward Ratio
# ============================================================================


def calc_risk_reward_ratio(
    max_profit: float,
    max_loss: float,
) -> float | None:
    """Calculate risk/reward ratio for a single trade.

    Note: max_profit and max_loss are strategy-level calculations,
    not direct Position attributes. Use Strategy.calc_max_profit()
    and Strategy.calc_max_loss() to obtain these values.

    Args:
        max_profit: Maximum potential profit.
        max_loss: Maximum potential loss (as positive number).

    Returns:
        Risk/reward ratio. < 1 means reward exceeds risk.
        Returns None if max_profit is zero.

    Example:
        >>> calc_risk_reward_ratio(max_profit=650, max_loss=5500)
        8.46  # Risk is 8.46x the reward
    """
    if max_profit is None or max_profit == 0:
        return None

    if max_loss is None:
        return None

    return abs(max_loss) / max_profit
