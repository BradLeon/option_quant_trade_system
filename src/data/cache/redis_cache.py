"""Redis-based local cache for technical and fundamental data.

This module provides a lightweight Redis cache specifically designed for
data that doesn't need real-time updates (klines, fundamentals).
"""

import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Try to import redis, but allow graceful degradation
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis not installed. Redis cache will be unavailable.")


class RedisCache:
    """Redis-based local cache for technical and fundamental data.

    Designed for caching data that updates daily:
    - History klines (for technical analysis)
    - Fundamental data

    Usage:
        cache = RedisCache()
        if cache.is_available:
            # Get cached klines
            klines = cache.get_klines("AAPL", "day")

            # Cache klines
            cache.set_klines("AAPL", "day", klines_data)
    """

    # Default TTL values in seconds
    DEFAULT_TTL = {
        "kline": 86400,  # 1 day for historical klines
        "fundamental": 86400,  # 1 day for fundamental data
    }

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ) -> None:
        """Initialize Redis cache.

        Args:
            host: Redis server host.
            port: Redis server port.
            db: Redis database number.
            password: Optional Redis password.
        """
        self._client: Any = None
        self._available = False

        if not REDIS_AVAILABLE:
            logger.warning("Redis not available - redis package not installed")
            return

        try:
            self._client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            # Test connection
            self._client.ping()
            self._available = True
            logger.info(f"Redis cache connected at {host}:{port}")
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}")
            self._client = None
            self._available = False

    @property
    def is_available(self) -> bool:
        """Check if Redis cache is available."""
        return self._available

    def _serialize(self, data: Any) -> str:
        """Serialize data to JSON string."""

        def default_serializer(obj: Any) -> Any:
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        return json.dumps(data, default=default_serializer)

    def _deserialize(self, data: str) -> Any:
        """Deserialize JSON string to data."""
        return json.loads(data)

    # ========== Kline Cache Methods ==========

    def get_klines(self, symbol: str, ktype: str) -> list[dict] | None:
        """Get cached kline data.

        Args:
            symbol: Stock symbol.
            ktype: Kline type (e.g., 'day', 'week').

        Returns:
            List of kline data dicts or None if not cached.
        """
        if not self._available:
            return None

        try:
            key = f"kline:{symbol}:{ktype}"
            data = self._client.get(key)
            if data:
                logger.debug(f"Redis cache hit: {key}")
                return self._deserialize(data)
            return None
        except Exception as e:
            logger.warning(f"Redis get_klines error: {e}")
            return None

    def set_klines(self, symbol: str, ktype: str, data: list[dict]) -> bool:
        """Cache kline data.

        Args:
            symbol: Stock symbol.
            ktype: Kline type (e.g., 'day', 'week').
            data: List of kline data dicts.

        Returns:
            True if cached successfully, False otherwise.
        """
        if not self._available:
            return False

        try:
            key = f"kline:{symbol}:{ktype}"
            ttl = self.DEFAULT_TTL["kline"]
            self._client.setex(key, ttl, self._serialize(data))
            logger.debug(f"Redis cache set: {key} (TTL={ttl}s)")
            return True
        except Exception as e:
            logger.warning(f"Redis set_klines error: {e}")
            return False

    # ========== Fundamental Cache Methods ==========

    def get_fundamental(self, symbol: str) -> dict | None:
        """Get cached fundamental data.

        Args:
            symbol: Stock symbol.

        Returns:
            Fundamental data dict or None if not cached.
        """
        if not self._available:
            return None

        try:
            key = f"fundamental:{symbol}"
            data = self._client.get(key)
            if data:
                logger.debug(f"Redis cache hit: {key}")
                return self._deserialize(data)
            return None
        except Exception as e:
            logger.warning(f"Redis get_fundamental error: {e}")
            return None

    def set_fundamental(self, symbol: str, data: dict) -> bool:
        """Cache fundamental data.

        Args:
            symbol: Stock symbol.
            data: Fundamental data dict.

        Returns:
            True if cached successfully, False otherwise.
        """
        if not self._available:
            return False

        try:
            key = f"fundamental:{symbol}"
            ttl = self.DEFAULT_TTL["fundamental"]
            self._client.setex(key, ttl, self._serialize(data))
            logger.debug(f"Redis cache set: {key} (TTL={ttl}s)")
            return True
        except Exception as e:
            logger.warning(f"Redis set_fundamental error: {e}")
            return False

    # ========== Utility Methods ==========

    def clear_all(self) -> bool:
        """Clear all cached data.

        Returns:
            True if cleared successfully, False otherwise.
        """
        if not self._available:
            return False

        try:
            self._client.flushdb()
            logger.info("Redis cache cleared")
            return True
        except Exception as e:
            logger.warning(f"Redis clear_all error: {e}")
            return False

    def clear_symbol(self, symbol: str) -> int:
        """Clear all cached data for a symbol.

        Args:
            symbol: Stock symbol.

        Returns:
            Number of keys deleted.
        """
        if not self._available:
            return 0

        try:
            # Find all keys for this symbol
            pattern = f"*:{symbol}:*"
            keys = list(self._client.scan_iter(pattern))
            # Also check keys without trailing part
            pattern2 = f"*:{symbol}"
            keys.extend(list(self._client.scan_iter(pattern2)))

            if keys:
                deleted = self._client.delete(*keys)
                logger.info(f"Redis cache cleared for {symbol}: {deleted} keys")
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"Redis clear_symbol error: {e}")
            return 0

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache statistics.
        """
        if not self._available:
            return {"available": False}

        try:
            info = self._client.info()
            return {
                "available": True,
                "used_memory": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "total_keys": self._client.dbsize(),
            }
        except Exception as e:
            logger.warning(f"Redis get_stats error: {e}")
            return {"available": False, "error": str(e)}
