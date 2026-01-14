"""
Stock Pool Manager - 股票池管理器

管理配置驱动的股票池，提供预定义和自定义的标的候选集。

使用方式:
    manager = StockPoolManager()

    # 加载预定义股票池
    symbols = manager.load_pool("us_default")

    # 列出所有可用股票池
    pools = manager.list_pools()

    # 获取默认股票池
    symbols = manager.get_default_pool(MarketType.US)
"""

import logging
from pathlib import Path

import yaml

from src.business.screening.models import MarketType

logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "screening" / "stock_pools.yaml"


class StockPoolError(Exception):
    """股票池相关错误"""
    pass


class StockPoolManager:
    """股票池管理器

    从配置文件加载股票池，支持按名称查询和按市场类型获取默认池。

    配置文件结构:
    ```yaml
    us_pools:
      us_default:
        description: "..."
        symbols: [SPY, QQQ, ...]
    hk_pools:
      hk_default:
        description: "..."
        symbols: [2800.HK, ...]
    defaults:
      us: us_default
      hk: hk_default
    ```

    Attributes:
        config_path: 配置文件路径
        _config: 已加载的配置数据
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        """初始化股票池管理器

        Args:
            config_path: 配置文件路径，默认使用 config/screening/stock_pools.yaml
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict | None = None

    @property
    def config(self) -> dict:
        """懒加载配置"""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> dict:
        """加载配置文件

        Returns:
            配置字典

        Raises:
            StockPoolError: 配置文件不存在或格式错误
        """
        if not self.config_path.exists():
            raise StockPoolError(f"配置文件不存在: {self.config_path}")

        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if not config:
                raise StockPoolError(f"配置文件为空: {self.config_path}")

            return config
        except yaml.YAMLError as e:
            raise StockPoolError(f"配置文件格式错误: {e}") from e

    def load_pool(self, name: str) -> list[str]:
        """加载指定名称的股票池

        Args:
            name: 股票池名称，如 "us_default", "hk_large_cap"

        Returns:
            股票代码列表

        Raises:
            StockPoolError: 股票池不存在
        """
        # 尝试从 us_pools 或 hk_pools 中查找
        for pool_section in ["us_pools", "hk_pools"]:
            pools = self.config.get(pool_section, {})
            if name in pools:
                pool_data = pools[name]
                symbols = pool_data.get("symbols", [])
                if not symbols:
                    logger.warning(f"股票池 '{name}' 为空")
                return symbols

        raise StockPoolError(f"股票池不存在: {name}")

    def list_pools(self) -> list[str]:
        """列出所有可用的股票池名称

        Returns:
            股票池名称列表
        """
        pools: list[str] = []

        for pool_section in ["us_pools", "hk_pools"]:
            section_pools = self.config.get(pool_section, {})
            pools.extend(section_pools.keys())

        return sorted(pools)

    def get_pool_info(self, name: str) -> dict:
        """获取股票池详细信息

        Args:
            name: 股票池名称

        Returns:
            包含 description, symbols, count 的字典

        Raises:
            StockPoolError: 股票池不存在
        """
        for pool_section in ["us_pools", "hk_pools"]:
            pools = self.config.get(pool_section, {})
            if name in pools:
                pool_data = pools[name]
                return {
                    "name": name,
                    "description": pool_data.get("description", ""),
                    "symbols": pool_data.get("symbols", []),
                    "count": len(pool_data.get("symbols", [])),
                    "market": "us" if pool_section == "us_pools" else "hk",
                }

        raise StockPoolError(f"股票池不存在: {name}")

    def get_default_pool(self, market_type: MarketType) -> list[str]:
        """获取指定市场类型的默认股票池

        Args:
            market_type: 市场类型 (US/HK)

        Returns:
            默认股票池的股票代码列表
        """
        defaults = self.config.get("defaults", {})
        market_key = market_type.value.lower()  # "us" or "hk"

        default_pool_name = defaults.get(market_key)
        if not default_pool_name:
            logger.warning(f"未配置 {market_type.value} 市场的默认股票池")
            return []

        return self.load_pool(default_pool_name)

    def get_default_pool_name(self, market_type: MarketType) -> str | None:
        """获取指定市场类型的默认股票池名称

        Args:
            market_type: 市场类型 (US/HK)

        Returns:
            默认股票池名称，如 "us_default"
        """
        defaults = self.config.get("defaults", {})
        market_key = market_type.value.lower()
        return defaults.get(market_key)

    def list_pools_by_market(self, market_type: MarketType) -> list[str]:
        """列出指定市场的所有股票池

        Args:
            market_type: 市场类型 (US/HK)

        Returns:
            该市场的股票池名称列表
        """
        pool_section = f"{market_type.value.lower()}_pools"
        pools = self.config.get(pool_section, {})
        return sorted(pools.keys())

    def validate_pool(self, name: str) -> bool:
        """验证股票池是否存在且有效

        Args:
            name: 股票池名称

        Returns:
            True 如果股票池存在且包含股票
        """
        try:
            symbols = self.load_pool(name)
            return len(symbols) > 0
        except StockPoolError:
            return False

    def reload(self) -> None:
        """重新加载配置文件"""
        self._config = None
        _ = self.config  # 触发重新加载
