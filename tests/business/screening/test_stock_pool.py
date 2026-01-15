"""Tests for Stock Pool Manager.

Tests for:
- src/business/screening/stock_pool.py
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.business.screening.models import MarketType
from src.business.screening.stock_pool import (
    StockPoolError,
    StockPoolManager,
)


@pytest.fixture
def sample_config():
    """Sample stock pool configuration."""
    return {
        "us_pools": {
            "us_default": {
                "description": "US default pool",
                "symbols": ["SPY", "QQQ", "AAPL", "MSFT"],
            },
            "us_tech": {
                "description": "US tech stocks",
                "symbols": ["AAPL", "MSFT", "GOOGL", "NVDA"],
            },
            "us_empty": {
                "description": "Empty pool for testing",
                "symbols": [],
            },
        },
        "hk_pools": {
            "hk_default": {
                "description": "HK default pool",
                "symbols": ["2800.HK", "0700.HK", "9988.HK"],
            },
        },
        "defaults": {
            "us": "us_default",
            "hk": "hk_default",
        },
    }


@pytest.fixture
def config_file(sample_config):
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        delete=False,
    ) as f:
        yaml.dump(sample_config, f)
        return Path(f.name)


@pytest.fixture
def manager(config_file):
    """Create a StockPoolManager with sample config."""
    return StockPoolManager(config_path=config_file)


class TestStockPoolManagerInit:
    """Tests for StockPoolManager initialization."""

    def test_default_config_path(self):
        """Test default config path is set."""
        manager = StockPoolManager()
        assert "stock_pools.yaml" in str(manager.config_path)

    def test_custom_config_path(self, config_file):
        """Test custom config path."""
        manager = StockPoolManager(config_path=config_file)
        assert manager.config_path == config_file

    def test_missing_config_file(self):
        """Test error on missing config file."""
        manager = StockPoolManager(config_path="/nonexistent/path.yaml")
        with pytest.raises(StockPoolError, match="配置文件不存在"):
            _ = manager.config


class TestLoadPool:
    """Tests for load_pool method."""

    def test_load_us_pool(self, manager):
        """Test loading US pool."""
        symbols = manager.load_pool("us_default")
        assert symbols == ["SPY", "QQQ", "AAPL", "MSFT"]

    def test_load_hk_pool(self, manager):
        """Test loading HK pool."""
        symbols = manager.load_pool("hk_default")
        assert symbols == ["2800.HK", "0700.HK", "9988.HK"]

    def test_load_tech_pool(self, manager):
        """Test loading tech pool."""
        symbols = manager.load_pool("us_tech")
        assert "NVDA" in symbols
        assert "GOOGL" in symbols

    def test_load_nonexistent_pool(self, manager):
        """Test error on nonexistent pool."""
        with pytest.raises(StockPoolError, match="股票池不存在"):
            manager.load_pool("nonexistent")

    def test_load_empty_pool(self, manager):
        """Test loading empty pool returns empty list."""
        symbols = manager.load_pool("us_empty")
        assert symbols == []


class TestListPools:
    """Tests for list_pools method."""

    def test_list_all_pools(self, manager):
        """Test listing all pools."""
        pools = manager.list_pools()
        assert "us_default" in pools
        assert "us_tech" in pools
        assert "hk_default" in pools

    def test_pools_are_sorted(self, manager):
        """Test pools are returned sorted."""
        pools = manager.list_pools()
        assert pools == sorted(pools)


class TestListPoolsByMarket:
    """Tests for list_pools_by_market method."""

    def test_list_us_pools(self, manager):
        """Test listing US pools."""
        pools = manager.list_pools_by_market(MarketType.US)
        assert "us_default" in pools
        assert "us_tech" in pools
        assert "hk_default" not in pools

    def test_list_hk_pools(self, manager):
        """Test listing HK pools."""
        pools = manager.list_pools_by_market(MarketType.HK)
        assert "hk_default" in pools
        assert "us_default" not in pools


class TestGetDefaultPool:
    """Tests for get_default_pool method."""

    def test_get_us_default(self, manager):
        """Test getting US default pool."""
        symbols = manager.get_default_pool(MarketType.US)
        assert symbols == ["SPY", "QQQ", "AAPL", "MSFT"]

    def test_get_hk_default(self, manager):
        """Test getting HK default pool."""
        symbols = manager.get_default_pool(MarketType.HK)
        assert symbols == ["2800.HK", "0700.HK", "9988.HK"]


class TestGetDefaultPoolName:
    """Tests for get_default_pool_name method."""

    def test_us_default_name(self, manager):
        """Test getting US default pool name."""
        name = manager.get_default_pool_name(MarketType.US)
        assert name == "us_default"

    def test_hk_default_name(self, manager):
        """Test getting HK default pool name."""
        name = manager.get_default_pool_name(MarketType.HK)
        assert name == "hk_default"


class TestGetPoolInfo:
    """Tests for get_pool_info method."""

    def test_get_us_pool_info(self, manager):
        """Test getting US pool info."""
        info = manager.get_pool_info("us_default")
        assert info["name"] == "us_default"
        assert info["description"] == "US default pool"
        assert info["count"] == 4
        assert info["market"] == "us"

    def test_get_hk_pool_info(self, manager):
        """Test getting HK pool info."""
        info = manager.get_pool_info("hk_default")
        assert info["market"] == "hk"

    def test_get_nonexistent_pool_info(self, manager):
        """Test error on nonexistent pool."""
        with pytest.raises(StockPoolError, match="股票池不存在"):
            manager.get_pool_info("nonexistent")


class TestValidatePool:
    """Tests for validate_pool method."""

    def test_validate_existing_pool(self, manager):
        """Test validating existing pool."""
        assert manager.validate_pool("us_default") is True

    def test_validate_nonexistent_pool(self, manager):
        """Test validating nonexistent pool."""
        assert manager.validate_pool("nonexistent") is False

    def test_validate_empty_pool(self, manager):
        """Test validating empty pool."""
        assert manager.validate_pool("us_empty") is False


class TestReload:
    """Tests for reload method."""

    def test_reload_clears_cache(self, manager):
        """Test reload clears internal cache."""
        # Access config to populate cache
        _ = manager.config
        assert manager._config is not None

        # Reload should clear and repopulate
        manager.reload()
        assert manager._config is not None


class TestRealConfig:
    """Tests using the real stock_pools.yaml config file."""

    @pytest.fixture
    def real_manager(self):
        """Create manager with real config file."""
        return StockPoolManager()

    def test_load_real_us_default(self, real_manager):
        """Test loading real US default pool."""
        try:
            symbols = real_manager.load_pool("us_default")
            assert "SPY" in symbols
            assert "QQQ" in symbols
            assert len(symbols) >= 5
        except StockPoolError:
            pytest.skip("Real config file not available")

    def test_load_real_hk_default(self, real_manager):
        """Test loading real HK default pool."""
        try:
            symbols = real_manager.load_pool("hk_default")
            assert "2800.HK" in symbols
            assert len(symbols) >= 3
        except StockPoolError:
            pytest.skip("Real config file not available")

    def test_real_pools_exist(self, real_manager):
        """Test real pools are defined."""
        try:
            pools = real_manager.list_pools()
            assert len(pools) > 0
            assert any("us" in p for p in pools)
            assert any("hk" in p for p in pools)
        except StockPoolError:
            pytest.skip("Real config file not available")


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_empty_config(self):
        """Test error on empty config file."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
        ) as f:
            f.write("")  # Empty file
            config_path = Path(f.name)

        manager = StockPoolManager(config_path=config_path)
        with pytest.raises(StockPoolError, match="配置文件为空"):
            _ = manager.config

    def test_invalid_yaml(self):
        """Test error on invalid YAML."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
        ) as f:
            f.write("invalid: yaml: content: [")  # Invalid YAML
            config_path = Path(f.name)

        manager = StockPoolManager(config_path=config_path)
        with pytest.raises(StockPoolError, match="配置文件格式错误"):
            _ = manager.config
