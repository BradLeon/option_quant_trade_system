"""Cached Black-Scholes Greeks calculations.

Provides LRU-cached versions of Greeks calculations to improve performance
when the same calculations are repeated multiple times (e.g., in backtesting).

Usage:
    from src.engine.bs.greeks_cache import CachedGreeksCalculator

    calculator = CachedGreeksCalculator(maxsize=10000)
    greeks = calculator.calc_greeks(params)

    # Check cache stats
    print(calculator.cache_info())

    # Clear cache if needed
    calculator.clear_cache()
"""

from functools import lru_cache
from typing import NamedTuple

from src.engine.models import BSParams
from src.engine.bs.greeks import (
    calc_bs_delta,
    calc_bs_gamma,
    calc_bs_theta,
    calc_bs_vega,
    calc_bs_rho,
)


class GreeksResult(NamedTuple):
    """Cached Greeks result as a named tuple for immutability."""

    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None

    def to_dict(self) -> dict[str, float | None]:
        """Convert to dictionary format."""
        return {
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
        }


def _params_to_key(params: BSParams) -> tuple:
    """Convert BSParams to a hashable cache key.

    Rounds values to reduce cache misses from floating point imprecision.
    """
    return (
        round(params.spot_price, 4),
        round(params.strike_price, 4),
        round(params.risk_free_rate, 6),
        round(params.volatility, 6),
        round(params.time_to_expiry, 6),
        params.is_call,
    )


class CachedGreeksCalculator:
    """LRU-cached Greeks calculator.

    Caches Greeks calculations to improve performance when the same
    parameters are queried multiple times, which is common in:
    - Backtesting with repeated evaluation of the same positions
    - Parameter sweep optimization
    - Portfolio Greeks aggregation

    Usage:
        calculator = CachedGreeksCalculator(maxsize=10000)
        greeks = calculator.calc_greeks(params)

        # Check cache efficiency
        info = calculator.cache_info()
        print(f"Hit rate: {info.hits / (info.hits + info.misses):.1%}")
    """

    def __init__(self, maxsize: int = 10000) -> None:
        """Initialize cached calculator.

        Args:
            maxsize: Maximum number of cached results (default: 10000)
        """
        self._maxsize = maxsize

        # Create the cached function
        @lru_cache(maxsize=maxsize)
        def _calc_greeks_cached(
            spot_price: float,
            strike_price: float,
            risk_free_rate: float,
            volatility: float,
            time_to_expiry: float,
            is_call: bool,
        ) -> GreeksResult:
            """Internal cached calculation."""
            params = BSParams(
                spot_price=spot_price,
                strike_price=strike_price,
                risk_free_rate=risk_free_rate,
                volatility=volatility,
                time_to_expiry=time_to_expiry,
                is_call=is_call,
            )
            return GreeksResult(
                delta=calc_bs_delta(params),
                gamma=calc_bs_gamma(params),
                theta=calc_bs_theta(params),
                vega=calc_bs_vega(params),
                rho=calc_bs_rho(params),
            )

        self._calc_greeks_cached = _calc_greeks_cached

    def calc_greeks(self, params: BSParams) -> GreeksResult:
        """Calculate all Greeks with caching.

        Args:
            params: Black-Scholes calculation parameters

        Returns:
            GreeksResult with all five Greeks
        """
        key = _params_to_key(params)
        return self._calc_greeks_cached(*key)

    def calc_greeks_dict(self, params: BSParams) -> dict[str, float | None]:
        """Calculate all Greeks with caching, return as dict.

        Args:
            params: Black-Scholes calculation parameters

        Returns:
            Dictionary with delta, gamma, theta, vega, rho
        """
        return self.calc_greeks(params).to_dict()

    def calc_delta(self, params: BSParams) -> float | None:
        """Calculate delta with caching."""
        return self.calc_greeks(params).delta

    def calc_gamma(self, params: BSParams) -> float | None:
        """Calculate gamma with caching."""
        return self.calc_greeks(params).gamma

    def calc_theta(self, params: BSParams) -> float | None:
        """Calculate theta with caching."""
        return self.calc_greeks(params).theta

    def calc_vega(self, params: BSParams) -> float | None:
        """Calculate vega with caching."""
        return self.calc_greeks(params).vega

    def calc_rho(self, params: BSParams) -> float | None:
        """Calculate rho with caching."""
        return self.calc_greeks(params).rho

    def cache_info(self):
        """Get cache statistics.

        Returns:
            CacheInfo with hits, misses, maxsize, currsize
        """
        return self._calc_greeks_cached.cache_info()

    def clear_cache(self) -> None:
        """Clear the cache."""
        self._calc_greeks_cached.cache_clear()


# Global singleton for convenience
_default_calculator: CachedGreeksCalculator | None = None


def get_cached_calculator(maxsize: int = 10000) -> CachedGreeksCalculator:
    """Get or create the default cached calculator.

    Args:
        maxsize: Maximum cache size (only used on first call)

    Returns:
        Global CachedGreeksCalculator instance
    """
    global _default_calculator
    if _default_calculator is None:
        _default_calculator = CachedGreeksCalculator(maxsize=maxsize)
    return _default_calculator


def calc_bs_greeks_cached(params: BSParams) -> dict[str, float | None]:
    """Calculate all Greeks using the default cached calculator.

    Convenience function that uses a global calculator instance.

    Args:
        params: Black-Scholes calculation parameters

    Returns:
        Dictionary with delta, gamma, theta, vega, rho
    """
    return get_cached_calculator().calc_greeks_dict(params)


def clear_greeks_cache() -> None:
    """Clear the default Greeks cache."""
    global _default_calculator
    if _default_calculator is not None:
        _default_calculator.clear_cache()


def get_greeks_cache_info():
    """Get cache info for the default calculator.

    Returns:
        CacheInfo or None if calculator not initialized
    """
    global _default_calculator
    if _default_calculator is not None:
        return _default_calculator.cache_info()
    return None
