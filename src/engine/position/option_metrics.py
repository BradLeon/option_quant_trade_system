"""Strategy Attractiveness Score (SAS) calculation.

Position-level module for evaluating option selling opportunities.

Note: For strategy metrics calculations (expected return, Sharpe ratio, etc.),
use Strategy classes directly:
    >>> from src.engine.strategy import ShortPutStrategy
    >>> strategy = ShortPutStrategy(spot_price=100, strike_price=95, ...)
    >>> metrics = strategy.calc_metrics()
"""


def calc_sas(
    iv: float,
    hv: float,
    sharpe_ratio: float,
    win_probability: float,
    weights: tuple[float, float, float] = (0.35, 0.35, 0.30),
) -> float | None:
    """Calculate Strategy Attractiveness Score (SAS) for a single option strategy.

    SAS measures the attractiveness of selling options based on:
    - IV/HV ratio: Volatility premium available to capture
    - Sharpe ratio: Risk-adjusted expected return
    - Win probability: Probability of profit (option expires worthless)

    Formula:
        SAS = w1 × IV_HV_Score + w2 × Sharpe_Score + w3 × Win_Score

        Where:
        - IV_HV_Score = min(2.0, IV/HV) / 2.0 × 100
        - Sharpe_Score = min(3.0, max(0, SR)) / 3.0 × 100
        - Win_Score = P(win) × 100

    For model-based interface, use Strategy.calc_sas() method:
        >>> strategy = ShortPutStrategy(spot_price=100, strike_price=95, ..., hv=0.20)
        >>> sas = strategy.calc_sas()

    Args:
        iv: Implied volatility (e.g., 0.30 for 30%).
        hv: Historical volatility (e.g., 0.20 for 20%).
        sharpe_ratio: Strategy Sharpe ratio (risk-adjusted return).
        win_probability: Win probability (0-1), e.g., probability option expires OTM.
        weights: Tuple of (w1, w2, w3) weights for IV/HV, Sharpe, and win prob.
            Default: (0.35, 0.35, 0.30).

    Returns:
        SAS score (0-100). Higher = more attractive strategy.
        Returns None if inputs are invalid.

    Example:
        >>> calc_sas(iv=0.30, hv=0.20, sharpe_ratio=2.0, win_probability=0.85)
        75.08  # Approximately
    """
    # Validate inputs
    if iv is None or hv is None or hv <= 0:
        return None
    if sharpe_ratio is None or win_probability is None:
        return None
    if not (0 <= win_probability <= 1):
        return None

    w1, w2, w3 = weights

    # IV/HV Score: Higher IV relative to HV means more premium to capture
    # Cap at 2.0 (IV being 2x HV is already very attractive)
    iv_hv_ratio = iv / hv
    iv_hv_score = min(2.0, iv_hv_ratio) / 2.0 * 100

    # Sharpe Score: Risk-adjusted return
    # Cap at 3.0 (Sharpe > 3 is exceptional)
    sharpe_clamped = min(3.0, max(0, sharpe_ratio))
    sharpe_score = sharpe_clamped / 3.0 * 100

    # Win Score: Direct probability mapping
    win_score = win_probability * 100

    # Weighted combination
    sas = w1 * iv_hv_score + w2 * sharpe_score + w3 * win_score

    return sas
