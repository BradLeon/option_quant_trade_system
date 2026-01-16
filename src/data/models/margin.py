"""Margin requirement data models."""

from dataclasses import dataclass
from enum import Enum


class MarginSource(Enum):
    """Source of margin data."""

    IBKR_API = "ibkr_api"  # IBKR whatIfOrder API
    FUTU_API = "futu_api"  # Futu acctradinginfo_query API
    REG_T_FORMULA = "reg_t_formula"  # Reg T formula calculation


@dataclass
class MarginRequirement:
    """Margin requirement for an option position.

    All margin values are PER-SHARE to be consistent with other metrics
    (premium, ROC, etc.). Multiply by lot_size for total contract margin.

    Attributes:
        initial_margin: Initial margin required to open position (per-share).
                       Used for ROC calculation.
        maintenance_margin: Maintenance margin to keep position (per-share).
                           Used for risk monitoring (margin call distance).
        source: Data source (API or formula).
        is_estimated: True if calculated via formula, False if from API.
        currency: Currency code (USD, HKD, etc.).
        commission: Commission for the trade (total, not per-share).
    """

    initial_margin: float
    maintenance_margin: float | None = None
    source: MarginSource = MarginSource.REG_T_FORMULA
    is_estimated: bool = True
    currency: str = "USD"
    commission: float | None = None

    def __post_init__(self):
        """Validate margin values."""
        if self.initial_margin < 0:
            raise ValueError(f"Initial margin cannot be negative: {self.initial_margin}")
        if self.maintenance_margin is not None and self.maintenance_margin < 0:
            raise ValueError(f"Maintenance margin cannot be negative: {self.maintenance_margin}")

    @property
    def is_from_api(self) -> bool:
        """Check if margin is from real API (not formula)."""
        return self.source in (MarginSource.IBKR_API, MarginSource.FUTU_API)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "initial_margin": self.initial_margin,
            "maintenance_margin": self.maintenance_margin,
            "source": self.source.value,
            "is_estimated": self.is_estimated,
            "currency": self.currency,
            "commission": self.commission,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MarginRequirement":
        """Create from dictionary."""
        source_str = data.get("source", "reg_t_formula")
        source = MarginSource(source_str) if isinstance(source_str, str) else source_str

        return cls(
            initial_margin=data["initial_margin"],
            maintenance_margin=data.get("maintenance_margin"),
            source=source,
            is_estimated=data.get("is_estimated", True),
            currency=data.get("currency", "USD"),
            commission=data.get("commission"),
        )


def calc_reg_t_margin_short_put(
    underlying_price: float,
    strike: float,
    premium: float,
) -> float:
    """Calculate Reg T margin for short put (per-share).

    IBKR Formula:
    Margin = Put Price + Max(20% × Underlying - OTM Amount, 10% × Strike)

    Where OTM Amount = Max(0, Underlying - Strike) for puts.

    Args:
        underlying_price: Current underlying stock price.
        strike: Put strike price.
        premium: Put premium (per-share).

    Returns:
        Margin per share.

    Note:
        This formula is accurate for US market (verified within 1% of IBKR API).
        DO NOT use for HK market - HK uses HKEX margin rules (~70% lower).
    """
    otm_amount = max(0, underlying_price - strike)
    option1 = 0.20 * underlying_price - otm_amount
    option2 = 0.10 * strike
    return premium + max(option1, option2)


def calc_reg_t_margin_short_call(
    underlying_price: float,
    strike: float,
    premium: float,
) -> float:
    """Calculate Reg T margin for short call (per-share).

    IBKR Formula:
    Margin = Call Price + Max(20% × Underlying - OTM Amount, 10% × Underlying)

    Where OTM Amount = Max(0, Strike - Underlying) for calls.

    Args:
        underlying_price: Current underlying stock price.
        strike: Call strike price.
        premium: Call premium (per-share).

    Returns:
        Margin per share.

    Note:
        This formula is accurate for US market.
        DO NOT use for HK market - HK uses HKEX margin rules.
    """
    otm_amount = max(0, strike - underlying_price)
    option1 = 0.20 * underlying_price - otm_amount
    option2 = 0.10 * underlying_price  # Note: 10% of underlying for calls
    return premium + max(option1, option2)
