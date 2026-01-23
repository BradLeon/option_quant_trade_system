"""Strategy factory for creating option strategies from positions.

This module provides a reusable factory pattern for creating strategy instances,
including automatic handling of partial coverage scenarios.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime

from src.data.models.account import AccountPosition, AssetType
from src.data.models.option import Greeks, OptionType
from src.data.models.stock import StockVolatility
from src.data.providers.ibkr_provider import IBKRProvider
from src.data.providers.futu_provider import FutuProvider
from src.engine.models.enums import PositionSide, StrategyType
from src.engine.models.strategy import OptionLeg, StrategyParams
from src.engine.strategy.base import OptionStrategy
from src.engine.strategy.covered_call import CoveredCallStrategy
from src.engine.strategy.short_call import ShortCallStrategy
from src.engine.strategy.short_put import ShortPutStrategy
from src.engine.strategy.strangle import ShortStrangleStrategy

logger = logging.getLogger(__name__)


@dataclass
class StrategyInstance:
    """Represents a strategy instance with its quantity ratio.

    Attributes:
        strategy: The option strategy object
        quantity_ratio: Portion of original position (0.0-1.0)
        description: Human-readable description (e.g., "covered (150/200)")
    """

    strategy: OptionStrategy
    quantity_ratio: float  # 0.0 - 1.0
    description: str


# ============================================================================
# Helper Functions
# ============================================================================


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol for matching across brokers.

    Examples:
        "HK.09988" -> "9988"
        "9988.HK" -> "9988"
        "AAPL" -> "AAPL"
    """
    # Remove HK prefix/suffix
    symbol = symbol.replace("HK.", "").replace(".HK", "")
    # Remove leading zeros for HK stocks
    if symbol.isdigit():
        symbol = str(int(symbol))
    return symbol


def calc_dte_from_expiry(expiry_str: str) -> int | None:
    """Calculate days to expiry from YYYYMMDD format.

    Args:
        expiry_str: Expiry date in YYYYMMDD format (e.g., "20250117").

    Returns:
        Days to expiry (non-negative), or None if parsing fails.
    """
    if not expiry_str:
        return None
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
        dte = (expiry_date - datetime.now()).days
        return max(0, dte)  # Cannot be negative
    except ValueError:
        return None


def build_option_leg(ap: AccountPosition) -> OptionLeg:
    """Build OptionLeg data model from AccountPosition.

    Args:
        ap: AccountPosition with option data.

    Returns:
        OptionLeg with option_type, side, strike, premium, greeks.
    """
    # Determine side: quantity < 0 = SHORT (sold), > 0 = LONG (bought)
    side = PositionSide.SHORT if ap.quantity < 0 else PositionSide.LONG

    # Calculate premium per share
    # market_value is total value, need to divide by (quantity * multiplier)
    premium = abs(ap.market_value / (ap.quantity * ap.contract_multiplier))

    # Build Greeks
    greeks = Greeks(
        delta=ap.delta,
        gamma=ap.gamma,
        theta=ap.theta,
        vega=ap.vega
    )

    return OptionLeg(
        option_type=OptionType.CALL if ap.option_type == "call" else OptionType.PUT,
        side=side,
        strike=ap.strike,
        premium=premium,
        greeks=greeks,
    )


def build_strategy_params(
    ap: AccountPosition, hv: float | None = None
) -> StrategyParams:
    """Build StrategyParams data model from AccountPosition.

    Args:
        ap: AccountPosition with option data.
        hv: Historical volatility (from StockVolatility), optional.

    Returns:
        StrategyParams with spot_price, volatility, time_to_expiry, hv, dte.
    """
    dte_days = calc_dte_from_expiry(ap.expiry)
    time_to_expiry = dte_days / 365.0 if dte_days else 0.01  # Minimum 0.01 years

    return StrategyParams(
        spot_price=ap.underlying_price,
        volatility=ap.iv,
        time_to_expiry=time_to_expiry,
        risk_free_rate=0.03,
        hv=hv,
        dte=dte_days,
    )


def get_volatility_data(
    symbol: str, provider: IBKRProvider | None
) -> StockVolatility | None:
    """Get stock volatility data (IV + HV) from provider.

    Args:
        symbol: Stock symbol (normalized).
        provider: IBKR provider instance (has get_stock_volatility method).

    Returns:
        StockVolatility model with iv, hv, iv_rank, iv_percentile, pcr.
        Returns None if provider unavailable or data fetch fails.
    """
    if provider is None:
        return None

    try:
        volatility = provider.get_stock_volatility(symbol)
        return volatility
    except Exception as e:
        logger.warning(f"Failed to get volatility for {symbol}: {e}")
        return None


# ============================================================================
# Strategy Classification
# ============================================================================


def classify_option_strategy(
    position: AccountPosition, all_positions: list[AccountPosition]
) -> StrategyType:
    """Classify option strategy type based on position characteristics.

    Args:
        position: Option position to classify.
        all_positions: All positions in the portfolio (for checking stock holdings).

    Returns:
        StrategyType enum: SHORT_PUT, COVERED_CALL, PARTIAL_COVERED_CALL,
        NAKED_CALL, SHORT_STRANGLE, UNKNOWN, or NOT_OPTION.
    """
    if position.asset_type != AssetType.OPTION:
        return StrategyType.NOT_OPTION

    # Short Put: PUT + quantity < 0 (sold)
    if position.option_type == "put" and position.quantity < 0:
        return StrategyType.SHORT_PUT

    # Covered Call / Partial / Naked Call: CALL + quantity < 0 (sold)
    if position.option_type == "call" and position.quantity < 0:
        # Check if we have the underlying stock
        underlying_symbol = position.underlying or position.symbol
        # Normalize symbol for matching (e.g., "9988" from "HK.09988")
        underlying_symbol = normalize_symbol(underlying_symbol)

        # Find stock position
        stock_position = None
        for p in all_positions:
            if (
                p.asset_type == AssetType.STOCK
                and normalize_symbol(p.symbol) == underlying_symbol
                and p.quantity > 0
            ):
                stock_position = p
                break

        if stock_position:
            # Calculate how many shares the calls represent
            call_shares = abs(position.quantity) * position.contract_multiplier
            stock_shares = stock_position.quantity

            if stock_shares >= call_shares:
                return StrategyType.COVERED_CALL  # Fully covered
            elif stock_shares > 0:
                return StrategyType.PARTIAL_COVERED_CALL  # Partially covered
            else:
                return StrategyType.NAKED_CALL  # No coverage
        else:
            return StrategyType.NAKED_CALL  # No stock position

    # Short Strangle: Check if there's both PUT and CALL short positions
    # (This is simplified - real detection would check strikes/expiries)
    if position.option_type in ["put", "call"] and position.quantity < 0:
        # For now, we handle strangles in verify script
        # TODO: Implement strangle detection
        pass

    return StrategyType.UNKNOWN


# ============================================================================
# Main Factory Function
# ============================================================================


def create_strategies_from_position(
    position: AccountPosition,
    all_positions: list[AccountPosition],
    ibkr_provider: IBKRProvider | None = None,
    futu_provider: FutuProvider | None = None,
    risk_free_rate: float = 0.03,
) -> list[StrategyInstance]:
    """Create strategy instances from a position, handling partial coverage.

    This is the main factory function. It detects the strategy type and creates
    appropriate strategy objects. For partial coverage scenarios, it automatically
    splits into multiple strategies (covered + naked portions).

    Args:
        position: The option position to analyze
        all_positions: All positions in the account (to find stock holdings)
        ibkr_provider: IBKR provider for fetching volatility data (optional)
        futu_provider: Futu provider for HK stock data fallback (optional)
        risk_free_rate: Risk-free rate for calculations (default: 0.03)

    Returns:
        List of StrategyInstance objects. Most positions return 1 strategy,
        but partial coverage returns 2 (covered + naked portions).

    Example:
        >>> position = GOOG -2 CALL (200 shares)
        >>> stock = GOOG 150 shares
        >>> strategies = create_strategies_from_position(position, [position, stock])
        >>> len(strategies)
        2
        >>> strategies[0].description
        'covered_call (150/200 shares, 75%)'
        >>> strategies[1].description
        'naked_call (50/200 shares, 25%)'
    """
    # Step 1: Classify strategy type
    strategy_type = classify_option_strategy(position, all_positions)

    if strategy_type in [StrategyType.NOT_OPTION, StrategyType.UNKNOWN]:
        logger.warning(f"{position.symbol}: Strategy type '{strategy_type}' not supported")
        return []

    # Step 2: Validate and prepare data
    if not _validate_position_data(position, ibkr_provider, futu_provider):
        return []

    # Step 3: Get volatility data
    volatility_data = _fetch_volatility_data(position, ibkr_provider)
    hv = volatility_data.hv if volatility_data else None

    # Step 4: Build common components
    try:
        leg = build_option_leg(position)
        params = build_strategy_params(position, hv=hv)
    except Exception as e:
        logger.warning(f"{position.symbol}: Failed to build leg/params: {e}")
        return []

    # Step 5: Create strategy instance(s)
    if strategy_type in [StrategyType.COVERED_CALL, StrategyType.PARTIAL_COVERED_CALL]:
        return _create_covered_call_strategies(
            position, all_positions, strategy_type, leg, params
        )
    elif strategy_type == StrategyType.NAKED_CALL:
        return _create_naked_call_strategy(position, leg, params)
    elif strategy_type == StrategyType.SHORT_PUT:
        return _create_short_put_strategy(position, leg, params)
    else:
        logger.warning(f"{position.symbol}: Strategy type '{strategy_type}' not implemented")
        return []


# ============================================================================
# Private Helper Functions
# ============================================================================


def _validate_position_data(
    position: AccountPosition,
    ibkr_provider: IBKRProvider | None,
    futu_provider: FutuProvider | None = None,
) -> bool:
    """Validate and fetch missing position data."""
    # Validate required fields
    if not position.strike or not position.iv:
        logger.warning(
            f"{position.symbol}: Missing required data "
            f"(strike={position.strike}, iv={position.iv})"
        )
        return False

    # If underlying_price is missing, try to fetch it
    if not position.underlying_price:
        underlying_symbol = position.underlying or position.symbol

        # Convert HK stocks to .HK format if needed
        is_hk_stock = False
        if underlying_symbol.startswith("HK."):
            code = underlying_symbol[3:].lstrip("0") or "0"
            underlying_symbol = f"{int(code):04d}.HK"
            is_hk_stock = True
        elif underlying_symbol.isdigit():
            underlying_symbol = f"{int(underlying_symbol):04d}.HK"
            is_hk_stock = True

        # HKD to USD conversion rate (for HK stocks when position is already in USD)
        # Position has been converted to USD by AccountAggregator, so fetched HKD prices
        # need to be converted to match
        hkd_to_usd = 0.128  # ~7.8 HKD/USD

        # Try IBKR first
        try:
            if ibkr_provider:
                stock_quote = ibkr_provider.get_stock_quote(underlying_symbol)
                # Check for valid close price (not None, not nan)
                if stock_quote and stock_quote.close is not None:
                    try:
                        if not math.isnan(stock_quote.close):
                            fetched_price = stock_quote.close
                            # Convert HKD to USD if position currency is USD
                            if is_hk_stock and position.currency == "USD":
                                fetched_price = fetched_price * hkd_to_usd
                                logger.info(
                                    f"Converted HK stock price to USD: {stock_quote.close:.2f} HKD -> {fetched_price:.2f} USD"
                                )
                            position.underlying_price = fetched_price
                            logger.info(
                                f"Fetched missing underlying_price for {position.symbol}: "
                                f"{position.underlying_price}"
                            )
                        else:
                            logger.warning(
                                f"Stock quote for {underlying_symbol} returned nan close price"
                            )
                    except (TypeError, ValueError):
                        # close is not a number
                        pass
        except Exception as e:
            logger.warning(
                f"Could not fetch underlying price for {position.symbol} via IBKR: {e}"
            )

        # Fallback: Try Futu for HK stocks if IBKR failed
        if not position.underlying_price and is_hk_stock and futu_provider:
            try:
                # Convert to Futu symbol format: "0700.HK" → "HK.00700"
                code = underlying_symbol.replace(".HK", "")
                futu_symbol = f"HK.{int(code):05d}"
                logger.info(f"Trying Futu fallback for {position.symbol}: {futu_symbol}")
                stock_quote = futu_provider.get_stock_quote(futu_symbol)
                if stock_quote and stock_quote.close is not None:
                    try:
                        if not math.isnan(stock_quote.close):
                            fetched_price = stock_quote.close
                            # Convert HKD to USD if position currency is USD
                            if position.currency == "USD":
                                fetched_price = fetched_price * hkd_to_usd
                                logger.info(
                                    f"Converted HK stock price to USD: {stock_quote.close:.2f} HKD -> {fetched_price:.2f} USD"
                                )
                            position.underlying_price = fetched_price
                            logger.info(
                                f"Fetched underlying_price from Futu for {position.symbol}: "
                                f"{position.underlying_price}"
                            )
                    except (TypeError, ValueError):
                        pass
            except Exception as e:
                logger.warning(
                    f"Could not fetch underlying price for {position.symbol} via Futu: {e}"
                )

        if not position.underlying_price:
            logger.warning(
                f"{position.symbol}: Missing underlying_price and could not fetch it"
            )
            return False

    return True


def _fetch_volatility_data(
    position: AccountPosition, ibkr_provider: IBKRProvider | None
) -> StockVolatility | None:
    """Fetch volatility data for the underlying."""
    underlying_symbol = position.underlying or position.symbol

    # Convert HK stocks to .HK format if needed
    if underlying_symbol.startswith("HK."):
        code = underlying_symbol[3:].lstrip("0") or "0"
        underlying_symbol = f"{int(code):04d}.HK"
    elif underlying_symbol.isdigit():
        underlying_symbol = f"{int(underlying_symbol):04d}.HK"

    return get_volatility_data(underlying_symbol, ibkr_provider)


def _create_covered_call_strategies(
    position: AccountPosition,
    all_positions: list[AccountPosition],
    strategy_type: StrategyType,
    leg: OptionLeg,
    params: StrategyParams,
) -> list[StrategyInstance]:
    """Create covered call strategy instance(s), splitting if partial coverage."""
    # Find stock position
    underlying_symbol = normalize_symbol(position.underlying or position.symbol)
    stock_position = next(
        (
            p
            for p in all_positions
            if p.asset_type == AssetType.STOCK
            and normalize_symbol(p.symbol) == underlying_symbol
        ),
        None,
    )

    if stock_position is None:
        logger.warning(
            f"{position.symbol}: Covered call without stock position (should not happen)"
        )
        return []

    # Calculate coverage
    call_shares = abs(position.quantity) * position.contract_multiplier
    stock_shares = stock_position.quantity
    coverage_ratio = min(1.0, stock_shares / call_shares)

    stock_cost_basis = stock_position.avg_cost

    # If fully covered, return single strategy
    if coverage_ratio >= 1.0:
        strategy = CoveredCallStrategy(
            spot_price=params.spot_price,
            strike_price=leg.strike,
            premium=leg.premium,
            stock_cost_basis=stock_cost_basis,
            volatility=params.volatility,
            time_to_expiry=params.time_to_expiry,
            risk_free_rate=params.risk_free_rate,
            hv=params.hv,
            dte=params.dte,
            delta=leg.delta,
            gamma=leg.gamma,
            theta=leg.theta,
            vega=leg.vega,
        )
        return [
            StrategyInstance(
                strategy=strategy,
                quantity_ratio=1.0,
                description=f"covered_call ({stock_shares:.0f}/{call_shares:.0f} shares, 100%)",
            )
        ]

    # Partial coverage: split into covered + naked
    logger.info(
        f"{position.symbol}: Partial coverage detected - "
        f"Stock: {stock_shares}, Call: {call_shares}. "
        f"Splitting into {coverage_ratio:.1%} covered + {(1-coverage_ratio):.1%} naked"
    )

    # Create covered portion
    covered_strategy = CoveredCallStrategy(
        spot_price=params.spot_price,
        strike_price=leg.strike,
        premium=leg.premium,
        stock_cost_basis=stock_cost_basis,
        volatility=params.volatility,
        time_to_expiry=params.time_to_expiry,
        risk_free_rate=params.risk_free_rate,
        hv=params.hv,
        dte=params.dte,
        delta=leg.delta,
        gamma=leg.gamma,
        theta=leg.theta,
        vega=leg.vega,
    )

    # Create naked portion
    naked_strategy = ShortCallStrategy(
        spot_price=params.spot_price,
        strike_price=leg.strike,
        premium=leg.premium,
        volatility=params.volatility,
        time_to_expiry=params.time_to_expiry,
        risk_free_rate=params.risk_free_rate,
        hv=params.hv,
        dte=params.dte,
        delta=leg.delta,
        gamma=leg.gamma,
        theta=leg.theta,
        vega=leg.vega,
    )

    return [
        StrategyInstance(
            strategy=covered_strategy,
            quantity_ratio=coverage_ratio,
            description=f"covered_call ({stock_shares:.0f}/{call_shares:.0f} shares, {coverage_ratio:.0%})",
        ),
        StrategyInstance(
            strategy=naked_strategy,
            quantity_ratio=1.0 - coverage_ratio,
            description=f"naked_call ({call_shares - stock_shares:.0f}/{call_shares:.0f} shares, {(1-coverage_ratio):.0%})",
        ),
    ]


def _create_naked_call_strategy(
    position: AccountPosition, leg: OptionLeg, params: StrategyParams
) -> list[StrategyInstance]:
    """Create naked call strategy instance."""
    strategy = ShortCallStrategy(
        spot_price=params.spot_price,
        strike_price=leg.strike,
        premium=leg.premium,
        volatility=params.volatility,
        time_to_expiry=params.time_to_expiry,
        risk_free_rate=params.risk_free_rate,
        hv=params.hv,
        dte=params.dte,
        delta=leg.delta,
        gamma=leg.gamma,
        theta=leg.theta,
        vega=leg.vega,
    )

    return [
        StrategyInstance(
            strategy=strategy,
            quantity_ratio=1.0,
            description="naked_call (100%)",
        )
    ]


def _create_short_put_strategy(
    position: AccountPosition, leg: OptionLeg, params: StrategyParams
) -> list[StrategyInstance]:
    """Create short put strategy instance."""
    strategy = ShortPutStrategy(
        spot_price=params.spot_price,
        strike_price=leg.strike,
        premium=leg.premium,
        volatility=params.volatility,
        time_to_expiry=params.time_to_expiry,
        risk_free_rate=params.risk_free_rate,
        hv=params.hv,
        dte=params.dte,
        delta=leg.delta,
        gamma=leg.gamma,
        theta=leg.theta,
        vega=leg.vega,
    )

    return [
        StrategyInstance(
            strategy=strategy,
            quantity_ratio=1.0,
            description="short_put (100%)",
        )
    ]
