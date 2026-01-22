"""Unified symbol formatting utility.

Provides consistent symbol format conversion across all data providers.
Eliminates duplicate logic and ensures predictable behavior.

Symbol Formats:
    - Standard: "0700.HK" (HK stocks), "AAPL" (US stocks)
    - IBKR: ("700", "SEHK", "HKD") for HK, ("AAPL", "SMART", "USD") for US
    - Futu: "HK.00700" (HK), "US.AAPL" (US)
    - Matching: "700" (HK normalized), "AAPL" (US as-is)
"""

from dataclasses import dataclass

from src.data.models.enums import Market


@dataclass
class IBKRContract:
    """IBKR contract parameters."""

    symbol: str
    exchange: str
    currency: str
    market: Market


class SymbolFormatter:
    """Unified symbol formatting utility.

    All methods are static and stateless for easy usage.

    Examples:
        >>> # Standardize symbols
        >>> SymbolFormatter.to_standard("HK.00700")  # "0700.HK"
        >>> SymbolFormatter.to_standard("700")       # "0700.HK"
        >>> SymbolFormatter.to_standard("AAPL")      # "AAPL"

        >>> # Convert to IBKR contract
        >>> SymbolFormatter.to_ibkr_contract("0700.HK")
        IBKRContract(symbol="700", exchange="SEHK", currency="HKD", market=Market.HK)

        >>> # Normalize for matching
        >>> SymbolFormatter.normalize_for_matching("0700.HK")  # "700"
        >>> SymbolFormatter.normalize_for_matching("HK.00700") # "700"
    """

    # Exchange and currency mappings
    HK_EXCHANGE = "SEHK"
    HK_CURRENCY = "HKD"
    US_EXCHANGE = "SMART"
    US_CURRENCY = "USD"

    @staticmethod
    def detect_market(symbol: str) -> Market:
        """Detect market type from symbol.

        Args:
            symbol: Symbol in any format.

        Returns:
            Market.HK, Market.US, or Market.UNKNOWN.

        Examples:
            >>> SymbolFormatter.detect_market("0700.HK")  # Market.HK
            >>> SymbolFormatter.detect_market("HK.00700") # Market.HK
            >>> SymbolFormatter.detect_market("700")      # Market.HK
            >>> SymbolFormatter.detect_market("AAPL")     # Market.US
        """
        symbol = symbol.upper()

        # Explicit HK indicators
        if symbol.endswith(".HK") or symbol.startswith("HK."):
            return Market.HK

        # Pure digits = HK stock (e.g., "700", "9988")
        if symbol.isdigit():
            return Market.HK

        # Alphabetic = US stock (e.g., "AAPL", "GOOG")
        if symbol.isalpha():
            return Market.US

        # US prefix
        if symbol.startswith("US."):
            return Market.US

        return Market.UNKNOWN

    @staticmethod
    def to_standard(symbol: str) -> str:
        """Convert any symbol format to standard format.

        Standard format:
            - HK stocks: "0700.HK" (4 digits + .HK)
            - US stocks: "AAPL" (uppercase letters)

        Args:
            symbol: Symbol in any format.

        Returns:
            Standardized symbol.

        Examples:
            >>> SymbolFormatter.to_standard("HK.00700")  # "0700.HK"
            >>> SymbolFormatter.to_standard("700")       # "0700.HK"
            >>> SymbolFormatter.to_standard("0700.HK")   # "0700.HK"
            >>> SymbolFormatter.to_standard("aapl")      # "AAPL"
            >>> SymbolFormatter.to_standard("US.AAPL")   # "AAPL"
        """
        symbol = symbol.upper().strip()
        market = SymbolFormatter.detect_market(symbol)

        if market == Market.HK:
            # Remove prefixes/suffixes
            if symbol.startswith("HK."):
                symbol = symbol[3:]
            if symbol.endswith(".HK"):
                symbol = symbol[:-3]

            # Remove leading zeros and re-add with padding
            code = symbol.lstrip("0") or "0"
            return f"{int(code):04d}.HK"

        elif market == Market.US:
            # Remove US prefix if present
            if symbol.startswith("US."):
                symbol = symbol[3:]
            return symbol.upper()

        else:
            # Unknown format, return uppercase
            return symbol

    @staticmethod
    def to_ibkr_contract(symbol: str) -> IBKRContract:
        """Convert symbol to IBKR contract parameters.

        Args:
            symbol: Symbol in any format.

        Returns:
            IBKRContract with (symbol, exchange, currency, market).

        Examples:
            >>> SymbolFormatter.to_ibkr_contract("0700.HK")
            IBKRContract(symbol="700", exchange="SEHK", currency="HKD", market=Market.HK)

            >>> SymbolFormatter.to_ibkr_contract("AAPL")
            IBKRContract(symbol="AAPL", exchange="SMART", currency="USD", market=Market.US)
        """
        market = SymbolFormatter.detect_market(symbol)
        standard = SymbolFormatter.to_standard(symbol)

        if market == Market.HK:
            # Extract numeric code without .HK suffix
            code = standard[:-3]  # Remove .HK
            # Remove leading zeros for IBKR
            ibkr_symbol = code.lstrip("0") or "0"
            return IBKRContract(
                symbol=ibkr_symbol,
                exchange=SymbolFormatter.HK_EXCHANGE,
                currency=SymbolFormatter.HK_CURRENCY,
                market=Market.HK,
            )

        elif market == Market.US:
            return IBKRContract(
                symbol=standard,
                exchange=SymbolFormatter.US_EXCHANGE,
                currency=SymbolFormatter.US_CURRENCY,
                market=Market.US,
            )

        else:
            # Unknown market, assume US
            return IBKRContract(
                symbol=standard,
                exchange=SymbolFormatter.US_EXCHANGE,
                currency=SymbolFormatter.US_CURRENCY,
                market=Market.UNKNOWN,
            )

    @staticmethod
    def to_ibkr_symbol(symbol: str) -> str:
        """Convert symbol to IBKR symbol format only.

        Args:
            symbol: Symbol in any format.

        Returns:
            IBKR symbol string.

        Examples:
            >>> SymbolFormatter.to_ibkr_symbol("0700.HK")  # "700"
            >>> SymbolFormatter.to_ibkr_symbol("AAPL")     # "AAPL"
        """
        return SymbolFormatter.to_ibkr_contract(symbol).symbol

    @staticmethod
    def normalize_for_matching(symbol: str) -> str:
        """Normalize symbol for cross-broker matching.

        Removes all prefixes, suffixes, and leading zeros for consistent matching.

        Args:
            symbol: Symbol in any format.

        Returns:
            Normalized symbol for matching.

        Examples:
            >>> SymbolFormatter.normalize_for_matching("0700.HK")  # "700"
            >>> SymbolFormatter.normalize_for_matching("HK.00700") # "700"
            >>> SymbolFormatter.normalize_for_matching("700")      # "700"
            >>> SymbolFormatter.normalize_for_matching("AAPL")     # "AAPL"
        """
        market = SymbolFormatter.detect_market(symbol)

        if market == Market.HK:
            # Remove all prefixes/suffixes and leading zeros
            symbol = symbol.upper()
            if symbol.startswith("HK."):
                symbol = symbol[3:]
            if symbol.endswith(".HK"):
                symbol = symbol[:-3]
            # Remove leading zeros
            return symbol.lstrip("0") or "0"

        else:
            # US stocks: just uppercase, remove US. prefix
            symbol = symbol.upper()
            if symbol.startswith("US."):
                symbol = symbol[3:]
            return symbol

    @staticmethod
    def to_futu(symbol: str) -> str:
        """Convert any symbol format to Futu format.

        Futu format:
            - HK stocks: "HK.09988" (HK. prefix + 5 digits)
            - US stocks: "US.AAPL" (US. prefix + symbol)

        Args:
            symbol: Symbol in any format.

        Returns:
            Futu format symbol.

        Examples:
            >>> SymbolFormatter.to_futu("9988.HK")   # "HK.09988"
            >>> SymbolFormatter.to_futu("0700.HK")   # "HK.00700"
            >>> SymbolFormatter.to_futu("AAPL")      # "US.AAPL"
        """
        standard = SymbolFormatter.to_standard(symbol)
        market = SymbolFormatter.detect_market(symbol)

        if market == Market.HK:
            code = standard[:-3]  # Remove .HK
            return f"HK.{code.zfill(5)}"  # Pad to 5 digits
        elif market == Market.US:
            return f"US.{standard}"
        return standard

    @staticmethod
    def parse_futu_option_trading_class(symbol: str) -> str | None:
        """Extract trading class from Futu option symbol.

        Futu option format: HK.<trading_class><YYMMDD><C/P><strike*1000>
        Example: HK.ALB260129P80000 -> ALB

        Args:
            symbol: Futu option symbol.

        Returns:
            Trading class (e.g., "ALB") or None if not a valid option symbol.
        """
        import re

        code = symbol.upper()
        if code.startswith("HK."):
            code = code[3:]

        # Pattern: <letters><YYMMDD><C/P><digits>
        pattern = r"^([A-Z]+)\d{6}[CP]\d+$"
        match = re.match(pattern, code)
        return match.group(1) if match else None

    @staticmethod
    def from_ibkr_contract(symbol: str, exchange: str | None = None) -> str:
        """Convert IBKR contract info back to standard format.

        Args:
            symbol: IBKR symbol (e.g., "700", "AAPL").
            exchange: Exchange name (e.g., "SEHK", "SMART").

        Returns:
            Standard format symbol.

        Examples:
            >>> SymbolFormatter.from_ibkr_contract("700", "SEHK")  # "0700.HK"
            >>> SymbolFormatter.from_ibkr_contract("9988", "SMART") # "9988.HK"
            >>> SymbolFormatter.from_ibkr_contract("AAPL", "SMART") # "AAPL"
        """
        # Detect HK stock by exchange or pure digits (HK codes are 1-5 digits)
        # Note: IBKR may use SMART routing for HK stocks, so check symbol pattern
        is_hk = exchange == SymbolFormatter.HK_EXCHANGE or (
            symbol.isdigit() and len(symbol) <= 5
        )

        if is_hk:
            # Pad with zeros and add .HK suffix
            code = symbol.lstrip("0") or "0"
            return f"{int(code):04d}.HK"
        else:
            return symbol.upper()
