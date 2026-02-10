"""Portfolio Greeks aggregation."""

import logging
from datetime import date
from typing import TYPE_CHECKING

from src.engine.models.position import Position

if TYPE_CHECKING:
    from src.data.providers.base import DataProvider

logger = logging.getLogger(__name__)


def _get_spy_price(
    base_currency: str = "USD",
    data_provider: "DataProvider | None" = None,
) -> float | None:
    """Get current SPY price for beta-weighted delta calculation.

    In backtest mode (data_provider provided), reads from DuckDB.
    In live mode, uses yfinance to fetch the latest SPY price.
    If base_currency is not USD, converts the price.

    Args:
        base_currency: Target currency for the price.
        data_provider: Optional data provider for backtest mode.

    Returns:
        Current SPY price in base_currency or None if unavailable.
    """
    # Backtest mode: read from data_provider
    if data_provider is not None:
        try:
            quote = data_provider.get_stock_quote("SPY")
            if quote and quote.close and quote.close > 0:
                price = quote.close
                # Convert to base_currency if not USD
                if base_currency != "USD":
                    from src.data.currency import CurrencyConverter
                    converter = CurrencyConverter()
                    price = converter.convert(price, "USD", base_currency)
                logger.debug(f"Fetched SPY price from data_provider: {price:.2f} {base_currency}")
                return price
        except Exception as e:
            logger.debug(f"Failed to get SPY price from data_provider: {e}")
        return None

    # Live mode: use yfinance
    try:
        import yfinance as yf

        spy = yf.Ticker("SPY")
        price = spy.fast_info.get("lastPrice")
        if not price or price <= 0:
            return None

        # Convert to base_currency if not USD
        if base_currency != "USD":
            from src.data.currency import CurrencyConverter
            converter = CurrencyConverter()
            price = converter.convert(price, "USD", base_currency)

        logger.debug(f"Fetched SPY price: {price:.2f} {base_currency}")
        return price
    except Exception as e:
        logger.warning(f"Failed to fetch SPY price: {e}")
        return None


def _get_stock_beta(
    symbol: str,
    data_provider: "DataProvider | None" = None,
    as_of_date: date | None = None,
) -> float | None:
    """Get stock beta.

    In backtest mode (data_provider provided), reads from stock_beta_daily.parquet
    or stock_beta.parquet. In live mode, uses yfinance.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "9988.HK").
        data_provider: Optional data provider for backtest mode.
        as_of_date: Query date for rolling beta lookup (backtest mode).

    Returns:
        Stock beta or None if unavailable.
    """
    # Backtest mode: read from data_provider
    if data_provider is not None:
        try:
            # Use get_stock_beta if available (DuckDBProvider)
            if hasattr(data_provider, "get_stock_beta"):
                beta = data_provider.get_stock_beta(symbol.upper(), as_of_date)
                if beta is not None:
                    logger.debug(f"Fetched beta for {symbol} from data_provider: {beta:.2f} (as_of={as_of_date})")
                    return beta
        except Exception as e:
            logger.debug(f"Failed to get beta for {symbol} from data_provider: {e}")
        return None

    # Live mode: use yfinance
    try:
        import yfinance as yf

        # Normalize symbol for yfinance
        yf_symbol = symbol.upper()
        # Convert HK format: "9988" -> "9988.HK", "700" -> "0700.HK"
        if yf_symbol.isdigit():
            yf_symbol = yf_symbol.zfill(4) + ".HK"

        ticker = yf.Ticker(yf_symbol)
        beta = ticker.info.get("beta")
        if beta is not None:
            logger.debug(f"Fetched beta for {symbol}: {beta:.2f}")
            return float(beta)
        return None
    except Exception as e:
        logger.debug(f"Failed to fetch beta for {symbol}: {e}")
        return None


def calc_portfolio_delta(positions: list[Position]) -> float:
    """Calculate total portfolio delta.

    Formula: Σ(delta × quantity × contract_multiplier)

    For options, delta represents sensitivity per share. Multiplying by
    contract_multiplier converts to per-contract sensitivity.

    Note on currency: Delta is dimensionless (∂C/∂S = currency/currency),
    so it does NOT require currency conversion. The same delta value applies
    regardless of whether prices are in USD, HKD, or any other currency.

    Args:
        positions: List of Position objects with delta values.

    Returns:
        Sum of all position deltas (in share-equivalent terms).

    Example:
        # AAPL call: delta=0.5, 2 contracts, multiplier=100
        # Position delta = 0.5 × 2 × 100 = 100 shares equivalent
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.delta is not None:
            total += pos.delta * pos.quantity * pos.contract_multiplier
    return total


def calc_portfolio_gamma(positions: list[Position]) -> float:
    """Calculate total portfolio gamma.

    Formula: Σ(gamma × quantity × contract_multiplier)

    Note: After currency conversion in account_aggregator, gamma is stored
    in "gamma_dollars per share" format (Γ × S² × 0.01). This function
    aggregates across positions by multiplying by quantity and multiplier.
    The result is total gamma_dollars exposure for the portfolio.

    Args:
        positions: List of Position objects with gamma values.

    Returns:
        Sum of all position gammas in gamma_dollars (base currency).
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.gamma is not None:
            total += pos.gamma * pos.quantity * pos.contract_multiplier
    return total


def calc_portfolio_theta(positions: list[Position]) -> float:
    """Calculate total portfolio theta.

    Formula: Σ(theta × quantity × contract_multiplier)

    Represents daily time decay of the portfolio in dollar terms.

    Args:
        positions: List of Position objects with theta values.

    Returns:
        Sum of all position thetas (typically negative for long options).
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.theta is not None:
            total += pos.theta * pos.quantity * pos.contract_multiplier
    return total


def calc_portfolio_vega(positions: list[Position]) -> float:
    """Calculate total portfolio vega.

    Formula: Σ(vega × quantity × contract_multiplier)

    Represents sensitivity to changes in implied volatility.

    Args:
        positions: List of Position objects with vega values.

    Returns:
        Sum of all position vegas.
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.vega is not None:
            total += pos.vega * pos.quantity * pos.contract_multiplier
    return total


def calc_beta_weighted_delta(
    positions: list[Position],
    data_provider: "DataProvider | None" = None,
    as_of_date: date | None = None,
) -> float | None:
    """Calculate beta-weighted delta normalized to SPY.

    This converts all position deltas to SPY-equivalent shares,
    allowing comparison of directional exposure across different underlyings.

    Formula: BWD = Σ(delta × underlying_price × multiplier × quantity × beta / spy_price)

    Physical meaning:
    - Converts dollar delta exposure to SPY-equivalent shares
    - A BWD of 100 means the portfolio behaves like being long 100 shares of SPY
    - Useful for hedging: to neutralize, short BWD shares of SPY

    Args:
        positions: List of Position objects with delta, beta, and underlying_price.
        data_provider: Optional data provider for backtest mode (reads from DuckDB).
        as_of_date: Query date for rolling beta lookup (backtest mode).

    Returns:
        Beta-weighted delta in SPY-equivalent shares, or None if SPY price unavailable.

    Example:
        # NVDA Call: delta=0.5, NVDA=$500, beta=1.8, 2 contracts, SPY=$450
        # BWD = 0.5 × 500 × 100 × 2 × 1.8 / 450 = 200 SPY shares
        # This NVDA position moves like 200 shares of SPY
    """
    if not positions:
        return None

    # Get currency from positions and fetch SPY price
    base_currency = "USD"
    if hasattr(positions[0], "currency"):
        base_currency = positions[0].currency

    spy_price = _get_spy_price(base_currency, data_provider=data_provider)
    if spy_price is None or spy_price <= 0:
        logger.debug("calc_beta_weighted_delta: SPY price unavailable")
        return None

    logger.debug(f"calc_beta_weighted_delta: SPY price={spy_price:.2f}")

    total_bwd = 0.0
    for pos in positions:
        if pos.delta is None or pos.underlying_price is None:
            logger.debug(f"  {pos.symbol}: SKIP - delta={pos.delta}, und_price={pos.underlying_price}")
            continue

        # Get beta - use provided value or fetch from data source
        beta = pos.beta
        beta_source = "provided"
        if beta is None:
            # Use underlying symbol for beta lookup (not option symbol)
            underlying = getattr(pos, "underlying", None) or pos.symbol
            beta = _get_stock_beta(underlying, data_provider=data_provider, as_of_date=as_of_date)
            beta_source = "data_provider" if data_provider else "yfinance"
        if beta is None:
            logger.debug(f"  {pos.symbol}: SKIP - no beta available")
            continue

        # Beta-weighted delta = delta × underlying_price × multiplier × quantity × beta / spy_price
        delta_dollars = pos.delta * pos.underlying_price * pos.contract_multiplier * pos.quantity
        bwd = delta_dollars * beta / spy_price
        total_bwd += bwd
        logger.debug(
            f"  {pos.symbol}: delta={pos.delta:.4f} und={pos.underlying_price:.2f} mult={pos.contract_multiplier} "
            f"qty={pos.quantity:.0f} beta={beta:.2f}({beta_source}) -> delta$={delta_dollars:.2f} bwd={bwd:.2f}"
        )

    logger.debug(f"calc_beta_weighted_delta: total_bwd={total_bwd:.2f}")
    return total_bwd


def calc_delta_dollars(positions: list[Position]) -> float:
    """Calculate delta exposure in dollar terms.

    Formula: Delta$ = Σ(delta × underlying_price × multiplier × quantity)

    Physical meaning:
    - How much the portfolio value changes when the underlying moves $1
    - Delta$ of $10,000 means a $1 move in underlying changes portfolio by $10,000

    Args:
        positions: List of Position objects with delta and underlying_price.

    Returns:
        Total dollar delta exposure.

    Example:
        # AAPL Call: delta=0.5, AAPL=$150, 3 contracts
        # Delta$ = 0.5 × 150 × 100 × 3 = $22,500
        # If AAPL moves $1, position value changes by $150 (0.5 × 100 × 3)
    """
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.delta is not None and pos.underlying_price is not None:
            # Delta dollars = delta × underlying_price × multiplier × quantity
            total += pos.delta * pos.underlying_price * pos.contract_multiplier * pos.quantity
    return total


def calc_gamma_dollars(positions: list[Position]) -> float:
    """DEPRECATED: Use calc_portfolio_gamma() instead.

    This function calculates gamma exposure from RAW gamma values.
    After currency conversion in account_aggregator, gamma is already stored
    in gamma_dollars format (Γ × S² × 0.01), so use calc_portfolio_gamma().

    Formula: Gamma$ = Σ(gamma × underlying_price² × multiplier × quantity / 100)

    Args:
        positions: List of Position objects with RAW gamma and underlying_price.

    Returns:
        Total dollar gamma exposure.

    .. deprecated::
        Use :func:`calc_portfolio_gamma` instead. After currency conversion,
        gamma is already in gamma_dollars format.
    """
    import warnings
    warnings.warn(
        "calc_gamma_dollars is deprecated. Use calc_portfolio_gamma() instead. "
        "After currency conversion, gamma is already in gamma_dollars format.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not positions:
        return 0.0

    total = 0.0
    for pos in positions:
        if pos.gamma is not None and pos.underlying_price is not None:
            # Gamma dollars = gamma × underlying_price² × multiplier × quantity / 100
            total += (
                pos.gamma
                * pos.underlying_price ** 2
                * pos.contract_multiplier
                * pos.quantity
                / 100
            )
    return total


def summarize_portfolio_greeks(
    positions: list[Position],
    data_provider: "DataProvider | None" = None,
    as_of_date: date | None = None,
) -> dict[str, float | None]:
    """Get summary of all portfolio Greeks.

    Args:
        positions: List of Position objects.
        data_provider: Optional data provider for backtest mode (reads from DuckDB).
        as_of_date: Query date for rolling beta lookup (backtest mode).

    Returns:
        Dictionary with all aggregated Greek values.
    """
    # Note: After currency conversion in account_aggregator, gamma is stored
    # in gamma_dollars format (Γ × S² × 0.01), so total_gamma = gamma_dollars.
    total_gamma = calc_portfolio_gamma(positions)
    summary: dict[str, float | None] = {
        "total_delta": calc_portfolio_delta(positions),
        "total_gamma": total_gamma,
        "total_theta": calc_portfolio_theta(positions),
        "total_vega": calc_portfolio_vega(positions),
        "delta_dollars": calc_delta_dollars(positions),
        "gamma_dollars": total_gamma,  # Same as total_gamma after currency conversion
        "beta_weighted_delta": calc_beta_weighted_delta(
            positions, data_provider=data_provider, as_of_date=as_of_date
        ),
    }

    return summary
