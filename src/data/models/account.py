"""Account and position data models.

Provides unified data structures for broker account positions,
cash balances, and consolidated portfolio views.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from src.data.models.enums import Market


class AccountType(Enum):
    """Account type enumeration."""

    REAL = "real"
    PAPER = "paper"


class AssetType(Enum):
    """Asset type enumeration."""

    STOCK = "stock"
    OPTION = "option"
    CASH = "cash"


@dataclass
class AccountPosition:
    """Single position in an account.

    Attributes:
        symbol: Symbol code (e.g., "AAPL", "0700.HK").
        asset_type: Type of asset (stock, option, cash).
        market: Market where the asset is traded.
        quantity: Position quantity.
        avg_cost: Average cost in local currency.
        market_value: Market value in local currency.
        unrealized_pnl: Unrealized P&L in local currency.
        currency: Original currency (USD/HKD/CNY).
        strike: Option strike price.
        expiry: Option expiry date (YYYY-MM-DD).
        option_type: "call" or "put".
        contract_multiplier: Option contract multiplier.
        delta: Option delta.
        gamma: Option gamma.
        theta: Option theta.
        vega: Option vega.
        iv: Implied volatility.
        broker: Broker name ("futu" / "ibkr").
        last_updated: Last update timestamp.
    """

    symbol: str
    asset_type: AssetType
    market: Market
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    currency: str
    # Option-specific fields
    underlying: str | None = None  # Underlying stock code (e.g., "9988" for IBKR)
    strike: float | None = None
    expiry: str | None = None
    option_type: str | None = None
    contract_multiplier: int = 1
    # Greeks (options)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    iv: float | None = None
    # Underlying price (for delta_dollars calculation)
    underlying_price: float | None = None
    # Margin requirement for this position
    margin: float | None = None
    # Metadata
    broker: str = ""
    last_updated: datetime | None = None


@dataclass
class AccountCash:
    """Cash balance in a specific currency.

    Attributes:
        currency: Currency code (USD/HKD/CNY).
        balance: Total balance.
        available: Available balance for trading.
        broker: Broker name.
    """

    currency: str
    balance: float
    available: float
    broker: str


@dataclass
class AccountSummary:
    """Account summary from a single broker.

    Attributes:
        broker: Broker name.
        account_type: Real or paper account.
        account_id: Broker account ID.
        total_assets: Total assets in local currency.
        cash: Total cash.
        market_value: Total market value of positions.
        unrealized_pnl: Total unrealized P&L.
        margin_used: Used margin.
        margin_available: Available margin.
        buying_power: Buying power.
        cash_by_currency: Cash breakdown by currency.
        timestamp: Data timestamp.
    """

    broker: str
    account_type: AccountType
    account_id: str
    total_assets: float
    cash: float
    market_value: float
    unrealized_pnl: float
    # Margin fields (option-related)
    margin_used: float | None = None
    margin_available: float | None = None
    buying_power: float | None = None
    # Cash by currency
    cash_by_currency: dict[str, float] | None = None
    # Timestamp
    timestamp: datetime | None = None


@dataclass
class ConsolidatedPortfolio:
    """Consolidated portfolio from multiple brokers.

    All values are converted to USD for unified view.

    Attributes:
        positions: List of all positions.
        cash_balances: List of cash balances by currency.
        total_value_usd: Total portfolio value in USD.
        total_unrealized_pnl_usd: Total unrealized P&L in USD.
        by_broker: Summary by broker.
        exchange_rates: Exchange rate snapshot (e.g., {"HKD": 0.128}).
        timestamp: Data timestamp.
    """

    positions: list[AccountPosition]
    cash_balances: list[AccountCash]
    total_value_usd: float
    total_unrealized_pnl_usd: float
    by_broker: dict[str, AccountSummary]
    exchange_rates: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
