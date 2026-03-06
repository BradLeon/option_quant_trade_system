from src.business.strategy.base import BaseTradeStrategy
from src.business.strategy.versions.short_options_with_expire_itm_stock_trade import ShortOptionsWithExpireItmStockTrade
from src.business.strategy.versions.short_options_without_expire_itm_stock_trade import ShortOptionsWithoutExpireItmStockTrade

class StrategyFactory:
    """策略工厂
    
    统一根据名称实例化不同的期权策略。
    """
    
    _registry = {
        "short_options_with_expire_itm_stock_trade": ShortOptionsWithExpireItmStockTrade,
        "short_options_without_expire_itm_stock_trade": ShortOptionsWithoutExpireItmStockTrade,
    }
    
    @classmethod
    def create(cls, name: str, **kwargs) -> BaseTradeStrategy:
        strategy_class = cls._registry.get(name.lower())
        if not strategy_class:
            available_strategies = list(cls._registry.keys())
            raise ValueError(f"Unknown strategy: '{name}'. Available strategies: {available_strategies}")
            
        return strategy_class(**kwargs)
        
    @classmethod
    def get_available_strategies(cls) -> list[str]:
        return list(cls._registry.keys())
