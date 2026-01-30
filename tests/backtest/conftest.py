"""
Pytest fixtures for backtest module tests.

Provides sample historical data for testing without requiring real ThetaData.
"""

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Generator

import pandas as pd
import pytest

from src.backtest.config.backtest_config import BacktestConfig
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.backtest.data.schema import get_parquet_path
from src.backtest.engine.account_simulator import AccountSimulator, SimulatedPosition
from src.backtest.engine.position_tracker import PositionTracker
from src.backtest.engine.trade_simulator import TradeSimulator
from src.engine.models.enums import StrategyType


# ============================================================================
# Sample Data Generation
# ============================================================================


def generate_stock_daily_data(
    symbol: str,
    start_date: date,
    end_date: date,
    base_price: float = 100.0,
    volatility: float = 0.02,
) -> pd.DataFrame:
    """Generate sample stock daily data.

    Args:
        symbol: Stock symbol
        start_date: Start date
        end_date: End date
        base_price: Starting price
        volatility: Daily volatility

    Returns:
        DataFrame with stock daily data
    """
    import numpy as np

    # Generate trading days (exclude weekends)
    dates = pd.date_range(start=start_date, end=end_date, freq="B")

    # Generate random returns
    np.random.seed(hash(symbol) % (2**32))
    returns = np.random.normal(0.0005, volatility, len(dates))

    # Generate prices
    prices = [base_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))

    # Generate OHLC
    data = []
    for i, d in enumerate(dates):
        price = prices[i]
        high = price * (1 + abs(np.random.normal(0, volatility / 2)))
        low = price * (1 - abs(np.random.normal(0, volatility / 2)))
        open_price = low + (high - low) * np.random.random()
        volume = int(np.random.uniform(1_000_000, 10_000_000))

        data.append({
            "date": d.date(),
            "symbol": symbol,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(price, 2),
            "volume": volume,
        })

    return pd.DataFrame(data)


def generate_option_daily_data(
    symbol: str,
    start_date: date,
    end_date: date,
    stock_data: pd.DataFrame,
    dte_range: tuple[int, int] = (30, 60),
    delta_range: tuple[float, float] = (0.15, 0.30),
) -> pd.DataFrame:
    """Generate sample option daily data.

    Column names match DuckDBProvider expectations:
    - 'right' instead of 'option_type' (P/C)
    - 'implied_vol' instead of 'iv'
    - 'count' for trade count

    Args:
        symbol: Underlying symbol
        start_date: Start date
        end_date: End date
        stock_data: Stock daily data for underlying prices
        dte_range: DTE range for options
        delta_range: Delta range for options

    Returns:
        DataFrame with option daily data
    """
    import numpy as np
    from scipy.stats import norm

    np.random.seed(hash(symbol + "opt") % (2**32))

    data = []
    stock_dict = {row["date"]: row["close"] for _, row in stock_data.iterrows()}

    for trade_date in pd.date_range(start=start_date, end=end_date, freq="B"):
        trade_date = trade_date.date()
        if trade_date not in stock_dict:
            continue

        underlying_price = stock_dict[trade_date]

        # Generate multiple expirations
        for dte in [30, 45, 60]:
            expiration = trade_date + timedelta(days=dte)
            # Round to Friday
            days_to_friday = (4 - expiration.weekday()) % 7
            expiration = expiration + timedelta(days=days_to_friday)

            # Generate strikes around current price
            for strike_pct in [0.90, 0.95, 0.97, 1.00, 1.03, 1.05, 1.10]:
                strike = round(underlying_price * strike_pct, 0)

                # Calculate option prices using simplified BS
                t = dte / 365
                iv = 0.25 + np.random.uniform(-0.05, 0.05)
                r = 0.05

                d1 = (np.log(underlying_price / strike) + (r + 0.5 * iv**2) * t) / (iv * np.sqrt(t))
                d2 = d1 - iv * np.sqrt(t)

                # Put option
                put_price = strike * np.exp(-r * t) * norm.cdf(-d2) - underlying_price * norm.cdf(-d1)
                put_delta = -norm.cdf(-d1)
                put_gamma = norm.pdf(d1) / (underlying_price * iv * np.sqrt(t))
                put_theta = -(underlying_price * norm.pdf(d1) * iv) / (2 * np.sqrt(t)) / 365
                put_vega = underlying_price * norm.pdf(d1) * np.sqrt(t) / 100

                # Call option
                call_price = underlying_price * norm.cdf(d1) - strike * np.exp(-r * t) * norm.cdf(d2)
                call_delta = norm.cdf(d1)
                call_gamma = put_gamma
                call_theta = put_theta
                call_vega = put_vega

                # Put record (use DuckDBProvider column names)
                data.append({
                    "date": trade_date,
                    "symbol": symbol,
                    "expiration": expiration,
                    "strike": strike,
                    "right": "P",  # DuckDBProvider expects 'right' not 'option_type'
                    "open": round(max(0.01, put_price * 0.98), 2),
                    "high": round(max(0.01, put_price * 1.05), 2),
                    "low": round(max(0.01, put_price * 0.95), 2),
                    "close": round(max(0.01, put_price), 2),
                    "volume": int(np.random.uniform(100, 5000)),
                    "count": int(np.random.uniform(10, 500)),
                    "bid": round(max(0.01, put_price * 0.97), 2),
                    "ask": round(max(0.01, put_price * 1.03), 2),
                    "open_interest": int(np.random.uniform(1000, 50000)),
                    "delta": round(put_delta, 4),
                    "gamma": round(put_gamma, 6),
                    "theta": round(put_theta, 4),
                    "vega": round(put_vega, 4),
                    "rho": 0.0,
                    "implied_vol": round(iv, 4),  # DuckDBProvider expects 'implied_vol'
                    "underlying_price": round(underlying_price, 2),
                })

                # Call record
                data.append({
                    "date": trade_date,
                    "symbol": symbol,
                    "expiration": expiration,
                    "strike": strike,
                    "right": "C",
                    "open": round(max(0.01, call_price * 0.98), 2),
                    "high": round(max(0.01, call_price * 1.05), 2),
                    "low": round(max(0.01, call_price * 0.95), 2),
                    "close": round(max(0.01, call_price), 2),
                    "volume": int(np.random.uniform(100, 5000)),
                    "count": int(np.random.uniform(10, 500)),
                    "bid": round(max(0.01, call_price * 0.97), 2),
                    "ask": round(max(0.01, call_price * 1.03), 2),
                    "open_interest": int(np.random.uniform(1000, 50000)),
                    "delta": round(call_delta, 4),
                    "gamma": round(call_gamma, 6),
                    "theta": round(call_theta, 4),
                    "vega": round(call_vega, 4),
                    "rho": 0.0,
                    "implied_vol": round(iv, 4),
                    "underlying_price": round(underlying_price, 2),
                })

    return pd.DataFrame(data)


def save_sample_data(
    data_dir: Path,
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> None:
    """Save sample data to Parquet files.

    Args:
        data_dir: Data directory
        symbols: List of symbols
        start_date: Start date
        end_date: End date
    """
    # Collect all stock data into a single DataFrame
    all_stock_dfs = []

    for symbol in symbols:
        # Generate stock data
        stock_df = generate_stock_daily_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            base_price=100.0 + hash(symbol) % 100,
        )
        all_stock_dfs.append(stock_df)

        # Generate option data
        option_df = generate_option_daily_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            stock_data=stock_df,
        )

        # Save option data by year
        # Get unique years in the data
        years = option_df["date"].apply(lambda d: d.year).unique()
        for year in years:
            year_df = option_df[option_df["date"].apply(lambda d: d.year) == year]
            option_path = get_parquet_path(data_dir, "option", symbol, year)
            option_path.parent.mkdir(parents=True, exist_ok=True)
            year_df.to_parquet(option_path, index=False)

    # Save all stock data to a single file
    combined_stock_df = pd.concat(all_stock_dfs, ignore_index=True)
    stock_path = get_parquet_path(data_dir, "stock")
    stock_path.parent.mkdir(parents=True, exist_ok=True)
    combined_stock_df.to_parquet(stock_path, index=False)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_symbols() -> list[str]:
    """Sample symbols for testing."""
    return ["AAPL", "MSFT", "GOOGL"]


@pytest.fixture
def sample_date_range() -> tuple[date, date]:
    """Sample date range for testing (3 months)."""
    end_date = date(2024, 3, 31)
    start_date = date(2024, 1, 1)
    return start_date, end_date


@pytest.fixture
def temp_data_dir(
    sample_symbols: list[str],
    sample_date_range: tuple[date, date],
) -> Generator[Path, None, None]:
    """Create temporary data directory with sample data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        start_date, end_date = sample_date_range

        # Generate and save sample data
        save_sample_data(data_dir, sample_symbols, start_date, end_date)

        yield data_dir


@pytest.fixture
def duckdb_provider(
    temp_data_dir: Path,
    sample_date_range: tuple[date, date],
) -> DuckDBProvider:
    """Create DuckDBProvider with sample data."""
    start_date, _ = sample_date_range
    return DuckDBProvider(
        data_dir=temp_data_dir,
        as_of_date=start_date,
    )


@pytest.fixture
def account_simulator() -> AccountSimulator:
    """Create AccountSimulator for testing."""
    return AccountSimulator(
        initial_capital=100_000.0,
        max_margin_utilization=0.70,
    )


@pytest.fixture
def position_tracker(duckdb_provider: DuckDBProvider) -> PositionTracker:
    """Create PositionTracker for testing."""
    return PositionTracker(
        data_provider=duckdb_provider,
        initial_capital=100_000.0,
        max_margin_utilization=0.70,
    )


@pytest.fixture
def trade_simulator() -> TradeSimulator:
    """Create TradeSimulator for testing."""
    return TradeSimulator(
        slippage_pct=0.001,
        commission_per_contract=0.65,
    )


@pytest.fixture
def sample_backtest_config(
    temp_data_dir: Path,
    sample_symbols: list[str],
    sample_date_range: tuple[date, date],
) -> BacktestConfig:
    """Create sample BacktestConfig for testing."""
    start_date, end_date = sample_date_range
    return BacktestConfig(
        name="TEST_SHORT_PUT",
        start_date=start_date,
        end_date=end_date,
        symbols=sample_symbols,
        strategy_type=StrategyType.SHORT_PUT,
        initial_capital=100_000.0,
        max_margin_utilization=0.70,
        max_position_pct=0.10,
        max_positions=10,
        slippage_pct=0.001,
        commission_per_contract=0.65,
        data_dir=temp_data_dir,
    )


@pytest.fixture
def sample_position() -> SimulatedPosition:
    """Create sample SimulatedPosition for testing."""
    return SimulatedPosition(
        position_id="P000001",
        symbol="AAPL 20240315 150P",
        underlying="AAPL",
        option_type="put",
        strike=150.0,
        expiration=date(2024, 3, 15),
        quantity=-1,  # Short 1 put
        entry_price=3.50,
        entry_date=date(2024, 2, 1),
        lot_size=100,
        underlying_price=155.0,
    )


@pytest.fixture
def sample_positions() -> list[SimulatedPosition]:
    """Create multiple sample positions for testing."""
    return [
        SimulatedPosition(
            position_id="P000001",
            symbol="AAPL 20240315 150P",
            underlying="AAPL",
            option_type="put",
            strike=150.0,
            expiration=date(2024, 3, 15),
            quantity=-1,
            entry_price=3.50,
            entry_date=date(2024, 2, 1),
            lot_size=100,
            underlying_price=155.0,
        ),
        SimulatedPosition(
            position_id="P000002",
            symbol="MSFT 20240322 400P",
            underlying="MSFT",
            option_type="put",
            strike=400.0,
            expiration=date(2024, 3, 22),
            quantity=-2,
            entry_price=5.00,
            entry_date=date(2024, 2, 5),
            lot_size=100,
            underlying_price=420.0,
        ),
        SimulatedPosition(
            position_id="P000003",
            symbol="GOOGL 20240329 140P",
            underlying="GOOGL",
            option_type="put",
            strike=140.0,
            expiration=date(2024, 3, 29),
            quantity=-1,
            entry_price=2.80,
            entry_date=date(2024, 2, 10),
            lot_size=100,
            underlying_price=145.0,
        ),
    ]
