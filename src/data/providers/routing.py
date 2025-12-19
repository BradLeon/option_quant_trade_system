"""Routing configuration for data providers.

This module provides configuration management for intelligent data routing,
allowing the system to select the best provider based on data type and market.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.data.models.enums import DataType, Market

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Provider capability configuration."""

    name: str
    markets: list[str] = field(default_factory=list)
    data_types: list[str] = field(default_factory=list)
    features: dict[str, bool] = field(default_factory=dict)
    priority: int = 0

    @property
    def supports_realtime(self) -> bool:
        """Check if provider supports real-time data."""
        return self.features.get("realtime", False)

    @property
    def supports_option_greeks(self) -> bool:
        """Check if provider supports option Greeks."""
        return self.features.get("option_greeks", False)


@dataclass
class RoutingRule:
    """A single routing rule."""

    providers: list[str] = field(default_factory=list)
    market: str | None = None
    data_type: str | list[str] | None = None

    def matches(self, data_type: DataType, market: Market | None) -> bool:
        """Check if this rule matches the given data type and market.

        Args:
            data_type: The data type being requested.
            market: The market (can be None for market-agnostic data).

        Returns:
            True if this rule matches, False otherwise.
        """
        # Check data_type match
        if self.data_type is not None:
            if isinstance(self.data_type, list):
                if data_type.value not in self.data_type:
                    return False
            elif data_type.value != self.data_type:
                return False

        # Check market match
        if self.market is not None:
            if market is None:
                return False
            if market.value != self.market:
                return False

        return True


class RoutingConfig:
    """Routing configuration manager.

    Loads routing rules from YAML config file or uses default configuration.
    """

    def __init__(self, config_path: str | Path | None = None):
        """Initialize routing configuration.

        Args:
            config_path: Path to YAML config file. If None, uses default config.
        """
        self.config_path = Path(config_path) if config_path else None
        self.providers: dict[str, ProviderConfig] = {}
        self.rules: list[RoutingRule] = []
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file or use defaults."""
        if self.config_path and self.config_path.exists():
            logger.info(f"Loading routing config from {self.config_path}")
            self._load_from_file()
        else:
            logger.info("Using default routing configuration")
            self._load_defaults()

    def _load_from_file(self) -> None:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # Load provider configs
            for name, pconfig in config.get("providers", {}).items():
                self.providers[name] = ProviderConfig(
                    name=name,
                    markets=pconfig.get("markets", []),
                    data_types=pconfig.get("data_types", []),
                    features=pconfig.get("features", {}),
                    priority=pconfig.get("priority", 0),
                )

            # Load routing rules
            for rule_config in config.get("routing_rules", []):
                self.rules.append(
                    RoutingRule(
                        providers=rule_config.get("providers", []),
                        market=rule_config.get("market"),
                        data_type=rule_config.get("data_type"),
                    )
                )

        except Exception as e:
            logger.error(f"Failed to load routing config: {e}, using defaults")
            self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default routing configuration."""
        # Default provider capabilities
        self.providers = {
            "ibkr": ProviderConfig(
                name="ibkr",
                markets=["us"],
                data_types=[
                    "stock_quote",
                    "stock_quotes",
                    "history_kline",
                    "option_chain",
                    "option_quote",
                    "option_quotes",
                    # fundamental: excluded - requires paid subscription, limited fields
                    "macro_data",
                ],
                features={"realtime": True, "option_greeks": True},
                priority=100,
            ),
            "futu": ProviderConfig(
                name="futu",
                markets=["us", "hk"],
                data_types=[
                    "stock_quote",
                    "stock_quotes",
                    "history_kline",
                    "option_chain",
                    "option_quote",
                    "option_quotes",
                    # fundamental: excluded - get_market_snapshot API timeout issues
                    "macro_data",
                ],
                features={"realtime": True, "option_greeks": True},
                priority=90,
            ),
            "yahoo": ProviderConfig(
                name="yahoo",
                markets=["us", "hk", "cn"],
                data_types=[
                    "stock_quote",
                    "stock_quotes",
                    "history_kline",
                    "option_chain",
                    "fundamental",
                    "macro_data",
                ],
                features={"realtime": False, "option_greeks": False},
                priority=10,
            ),
        }

        # Default routing rules (order matters - first match wins)
        self.rules = [
            # Fundamental data → Yahoo only (most complete, free)
            # IBKR requires paid subscription, Futu has API issues
            RoutingRule(
                data_type="fundamental",
                providers=["yahoo"],
            ),
            # Macro data → Yahoo preferred (most comprehensive)
            RoutingRule(
                data_type="macro_data",
                providers=["yahoo"],
            ),
            # US K-line/technical data → IBKR > Yahoo (Futu doesn't support US stocks)
            # Verified: IBKR has best technical indicator accuracy for US stocks
            RoutingRule(
                market="us",
                data_type="history_kline",
                providers=["ibkr", "yahoo"],
            ),
            # HK K-line/technical data → IBKR > Futu > Yahoo
            # Verified: IBKR best, Futu second, Yahoo fallback
            RoutingRule(
                market="hk",
                data_type="history_kline",
                providers=["ibkr", "futu", "yahoo"],
            ),
            # HK options → Futu only (Yahoo doesn't support HK options)
            RoutingRule(
                market="hk",
                data_type=["option_chain", "option_quote", "option_quotes"],
                providers=["futu"],
            ),
            # HK stocks (quote) → Futu preferred
            RoutingRule(
                market="hk",
                data_type=["stock_quote", "stock_quotes"],
                providers=["futu", "yahoo"],
            ),
            # US options → IBKR preferred (best Greeks), Futu fallback, Yahoo last resort
            RoutingRule(
                market="us",
                data_type=["option_chain", "option_quote", "option_quotes"],
                providers=["ibkr", "futu", "yahoo"],
            ),
            # US stocks (quote) → IBKR preferred (real-time)
            RoutingRule(
                market="us",
                data_type=["stock_quote", "stock_quotes"],
                providers=["ibkr", "futu", "yahoo"],
            ),
            # Default fallback → Yahoo (always available)
            RoutingRule(
                providers=["yahoo"],
            ),
        ]

    def select_providers(
        self,
        data_type: DataType,
        market: Market | None = None,
    ) -> list[str]:
        """Select providers based on data type and market.

        Args:
            data_type: The type of data being requested.
            market: The market (optional, for market-specific routing).

        Returns:
            List of provider names in priority order.
        """
        for rule in self.rules:
            if rule.matches(data_type, market):
                logger.debug(
                    f"Matched rule for {data_type.value}/{market}: {rule.providers}"
                )
                return rule.providers

        # Fallback to Yahoo if no rule matches
        logger.debug(f"No rule matched for {data_type.value}/{market}, using yahoo")
        return ["yahoo"]

    def get_provider_config(self, name: str) -> ProviderConfig | None:
        """Get configuration for a specific provider."""
        return self.providers.get(name)

    def to_dict(self) -> dict[str, Any]:
        """Export configuration as dictionary (for debugging/logging)."""
        return {
            "providers": {
                name: {
                    "markets": p.markets,
                    "data_types": p.data_types,
                    "features": p.features,
                    "priority": p.priority,
                }
                for name, p in self.providers.items()
            },
            "routing_rules": [
                {
                    "market": r.market,
                    "data_type": r.data_type,
                    "providers": r.providers,
                }
                for r in self.rules
            ],
        }
