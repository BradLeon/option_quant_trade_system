"""Strategy-agnostic option expected return interface.

Provides convenient functions that internally create strategy objects
and calculate metrics based on B-S model.
"""

from enum import Enum
from typing import Literal

from src.engine.strategy import (
    CoveredCallStrategy,
    ShortPutStrategy,
    ShortStrangleStrategy,
    StrategyMetrics,
)


class StrategyType(Enum):
    """Supported strategy types."""

    SHORT_PUT = "short_put"
    COVERED_CALL = "covered_call"
    SHORT_STRANGLE = "short_strangle"


def calc_short_put_metrics(
    spot_price: float,
    strike_price: float,
    premium: float,
    volatility: float,
    time_to_expiry: float,
    risk_free_rate: float = 0.03,
    margin_ratio: float = 1.0,
) -> StrategyMetrics:
    """Calculate all metrics for a short put strategy.

    Args:
        spot_price: Current stock price (S).
        strike_price: Put strike price (K).
        premium: Premium received per share (C).
        volatility: Implied volatility (σ).
        time_to_expiry: Time to expiration in years (T).
        risk_free_rate: Annual risk-free rate (r).
        margin_ratio: Margin requirement ratio for Sharpe calculation.

    Returns:
        StrategyMetrics with all calculated values.
    """
    strategy = ShortPutStrategy(
        spot_price=spot_price,
        strike_price=strike_price,
        premium=premium,
        volatility=volatility,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
    )
    return strategy.calc_metrics(margin_ratio)


def calc_covered_call_metrics(
    spot_price: float,
    strike_price: float,
    premium: float,
    volatility: float,
    time_to_expiry: float,
    risk_free_rate: float = 0.03,
    margin_ratio: float = 1.0,
    stock_cost_basis: float | None = None,
) -> StrategyMetrics:
    """Calculate all metrics for a covered call strategy.

    Args:
        spot_price: Current stock price (S).
        strike_price: Call strike price (K).
        premium: Premium received per share (C).
        volatility: Implied volatility (σ).
        time_to_expiry: Time to expiration in years (T).
        risk_free_rate: Annual risk-free rate (r).
        margin_ratio: Margin requirement ratio for Sharpe calculation.
        stock_cost_basis: Original cost of stock (defaults to spot_price).

    Returns:
        StrategyMetrics with all calculated values.
    """
    strategy = CoveredCallStrategy(
        spot_price=spot_price,
        strike_price=strike_price,
        premium=premium,
        volatility=volatility,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
        stock_cost_basis=stock_cost_basis,
    )
    return strategy.calc_metrics(margin_ratio)


def calc_short_strangle_metrics(
    spot_price: float,
    put_strike: float,
    call_strike: float,
    put_premium: float,
    call_premium: float,
    volatility: float,
    time_to_expiry: float,
    risk_free_rate: float = 0.03,
    margin_ratio: float = 1.0,
    put_volatility: float | None = None,
    call_volatility: float | None = None,
) -> StrategyMetrics:
    """Calculate all metrics for a short strangle strategy.

    Args:
        spot_price: Current stock price (S).
        put_strike: Put strike price (K_p), should be < spot.
        call_strike: Call strike price (K_c), should be > spot.
        put_premium: Premium received for put.
        call_premium: Premium received for call.
        volatility: Default implied volatility (σ).
        time_to_expiry: Time to expiration in years (T).
        risk_free_rate: Annual risk-free rate (r).
        margin_ratio: Margin requirement ratio for Sharpe calculation.
        put_volatility: IV for put leg (optional).
        call_volatility: IV for call leg (optional).

    Returns:
        StrategyMetrics with all calculated values.
    """
    strategy = ShortStrangleStrategy(
        spot_price=spot_price,
        put_strike=put_strike,
        call_strike=call_strike,
        put_premium=put_premium,
        call_premium=call_premium,
        volatility=volatility,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
        put_volatility=put_volatility,
        call_volatility=call_volatility,
    )
    return strategy.calc_metrics(margin_ratio)


def calc_option_expected_return(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    **kwargs,
) -> float:
    """Calculate expected return for any supported strategy.

    Args:
        strategy_type: Type of strategy.
        **kwargs: Strategy-specific parameters.

    Returns:
        Expected return in dollar amount per share.

    Raises:
        ValueError: If strategy type is not supported.
    """
    strategy = _create_strategy(strategy_type, **kwargs)
    return strategy.calc_expected_return()


def calc_option_return_std(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    **kwargs,
) -> float:
    """Calculate return standard deviation for any supported strategy.

    Args:
        strategy_type: Type of strategy.
        **kwargs: Strategy-specific parameters.

    Returns:
        Standard deviation of return.
    """
    strategy = _create_strategy(strategy_type, **kwargs)
    return strategy.calc_return_std()


def calc_option_sharpe_ratio(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    margin_ratio: float = 1.0,
    **kwargs,
) -> float | None:
    """Calculate Sharpe ratio for any supported strategy.

    SR = (E[π] - Rf) / Std[π]
    Rf = margin_ratio × capital_at_risk × (e^(rT) - 1)

    Args:
        strategy_type: Type of strategy.
        margin_ratio: Margin requirement ratio.
        **kwargs: Strategy-specific parameters.

    Returns:
        Sharpe ratio, or None if not calculable.
    """
    strategy = _create_strategy(strategy_type, **kwargs)
    return strategy.calc_sharpe_ratio(margin_ratio)


def calc_option_sharpe_ratio_annualized(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    margin_ratio: float = 1.0,
    **kwargs,
) -> float | None:
    """Calculate annualized Sharpe ratio for any supported strategy.

    SR_annual = SR / sqrt(T)

    Args:
        strategy_type: Type of strategy.
        margin_ratio: Margin requirement ratio.
        **kwargs: Strategy-specific parameters.

    Returns:
        Annualized Sharpe ratio, or None if not calculable.
    """
    strategy = _create_strategy(strategy_type, **kwargs)
    return strategy.calc_sharpe_ratio_annualized(margin_ratio)


def calc_option_kelly_fraction(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    **kwargs,
) -> float:
    """Calculate Kelly fraction for any supported strategy.

    f* = E[π] / Var[π]

    Args:
        strategy_type: Type of strategy.
        **kwargs: Strategy-specific parameters.

    Returns:
        Kelly fraction (0 if negative expectation).
    """
    strategy = _create_strategy(strategy_type, **kwargs)
    return strategy.calc_kelly_fraction()


def calc_option_win_probability(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    **kwargs,
) -> float:
    """Calculate win probability for any supported strategy.

    Args:
        strategy_type: Type of strategy.
        **kwargs: Strategy-specific parameters.

    Returns:
        Win probability (0-1).
    """
    strategy = _create_strategy(strategy_type, **kwargs)
    return strategy.calc_win_probability()


def _create_strategy(
    strategy_type: StrategyType | Literal["short_put", "covered_call", "short_strangle"],
    **kwargs,
):
    """Create a strategy object based on type.

    Args:
        strategy_type: Type of strategy.
        **kwargs: Strategy-specific parameters.

    Returns:
        Strategy instance.

    Raises:
        ValueError: If strategy type is not supported.
    """
    # Normalize strategy type
    if isinstance(strategy_type, str):
        strategy_type = StrategyType(strategy_type)

    if strategy_type == StrategyType.SHORT_PUT:
        return ShortPutStrategy(
            spot_price=kwargs["spot_price"],
            strike_price=kwargs["strike_price"],
            premium=kwargs["premium"],
            volatility=kwargs["volatility"],
            time_to_expiry=kwargs["time_to_expiry"],
            risk_free_rate=kwargs.get("risk_free_rate", 0.03),
        )

    elif strategy_type == StrategyType.COVERED_CALL:
        return CoveredCallStrategy(
            spot_price=kwargs["spot_price"],
            strike_price=kwargs["strike_price"],
            premium=kwargs["premium"],
            volatility=kwargs["volatility"],
            time_to_expiry=kwargs["time_to_expiry"],
            risk_free_rate=kwargs.get("risk_free_rate", 0.03),
            stock_cost_basis=kwargs.get("stock_cost_basis"),
        )

    elif strategy_type == StrategyType.SHORT_STRANGLE:
        return ShortStrangleStrategy(
            spot_price=kwargs["spot_price"],
            put_strike=kwargs["put_strike"],
            call_strike=kwargs["call_strike"],
            put_premium=kwargs["put_premium"],
            call_premium=kwargs["call_premium"],
            volatility=kwargs["volatility"],
            time_to_expiry=kwargs["time_to_expiry"],
            risk_free_rate=kwargs.get("risk_free_rate", 0.03),
            put_volatility=kwargs.get("put_volatility"),
            call_volatility=kwargs.get("call_volatility"),
        )

    else:
        raise ValueError(f"Unsupported strategy type: {strategy_type}")
