from src.business.strategy.base import BaseTradeStrategy
from src.business.strategy.versions.short_options_with_expire_itm_stock_trade import ShortOptionsWithExpireItmStockTrade
from src.business.strategy.versions.short_options_without_expire_itm_stock_trade import ShortOptionsWithoutExpireItmStockTrade
from src.business.strategy.versions.long_leaps_call_sma_timing import LongLeapsCallSmaTiming
from src.business.strategy.versions.spy_buy_and_hold_sma_timing import SpyBuyAndHoldSmaTiming
from src.business.strategy.versions.spy_sma200_freq5_timing import SpySma200Freq5Timing
from src.business.strategy.versions.spy_momentum_lev_vol_target import SpyMomentumLevVolTarget
from src.business.strategy.versions.spy_leaps_only_vol_target import SpyLeapsOnlyVolTarget

class StrategyFactory:
    """策略工厂

    统一根据名称实例化不同的期权策略。
    """

    _registry = {
        "short_options_with_expire_itm_stock_trade": ShortOptionsWithExpireItmStockTrade,
        "short_options_without_expire_itm_stock_trade": ShortOptionsWithoutExpireItmStockTrade,
        "long_leaps_call_sma_timing": LongLeapsCallSmaTiming,
        "spy_buy_and_hold_sma_timing": SpyBuyAndHoldSmaTiming,
        "spy_sma200_freq5_timing": SpySma200Freq5Timing,
        "spy_momentum_lev_vol_target": SpyMomentumLevVolTarget,
        "spy_leaps_only_vol_target": SpyLeapsOnlyVolTarget,
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
