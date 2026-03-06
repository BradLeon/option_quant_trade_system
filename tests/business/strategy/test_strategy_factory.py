import pytest

from src.business.strategy.base import BaseOptionStrategy
from src.business.strategy.factory import StrategyFactory
from src.business.strategy.versions.short_options_with_expire_itm_stock_trade import ShortOptionsWithExpireItmStockTrade
from src.business.strategy.versions.short_options_without_expire_itm_stock_trade import ShortOptionsWithoutExpireItmStockTrade

def test_strategy_factory_registry():
    """Test that the strategy factory registers strategies correctly."""
    available = StrategyFactory.get_available_strategies()
    assert "short_options_with_expire_itm_stock_trade" in available
    assert "short_options_without_expire_itm_stock_trade" in available

def test_strategy_factory_create_with_expire():
    """Test creating ShortOptionsWithExpireItmStockTrade via factory."""
    strategy = StrategyFactory.create("short_options_with_expire_itm_stock_trade")
    assert isinstance(strategy, ShortOptionsWithExpireItmStockTrade)
    assert isinstance(strategy, BaseOptionStrategy)
    assert strategy.name == "short_options_with_expire_itm_stock_trade"

def test_strategy_factory_create_without_expire():
    """Test creating ShortOptionsWithoutExpireItmStockTrade via factory."""
    strategy = StrategyFactory.create("short_options_without_expire_itm_stock_trade")
    assert isinstance(strategy, ShortOptionsWithoutExpireItmStockTrade)
    assert isinstance(strategy, BaseOptionStrategy)
    assert strategy.name == "short_options_without_expire_itm_stock_trade"

def test_strategy_factory_invalid():
    """Test that creating an unknown strategy raises ValueError."""
    with pytest.raises(ValueError, match="Unknown strategy"):
        StrategyFactory.create("unknown_strategy")
