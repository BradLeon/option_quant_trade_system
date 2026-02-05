"""
Order Store - 订单存储

使用 JSON 文件持久化订单记录。

文件结构:
    data/trading/orders/
    ├── YYYY-MM-DD/
    │   ├── order_001.json
    │   └── order_002.json
    └── index.json  # 订单索引
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.models.order import OrderRecord, OrderStatus

logger = logging.getLogger(__name__)


class OrderStore:
    """订单存储

    使用 JSON 文件持久化订单，按日期组织目录结构。

    Usage:
        store = OrderStore()
        store.save(order_record)
        record = store.get("order_123")
    """

    def __init__(self, config: OrderConfig | None = None) -> None:
        """初始化订单存储

        Args:
            config: 订单配置
        """
        self._config = config or OrderConfig.load()
        self._base_path = Path(self._config.storage_path)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """确保存储目录存在"""
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _get_order_path(self, order_id: str, created_at: datetime) -> Path:
        """获取订单文件路径"""
        date_str = created_at.strftime("%Y-%m-%d")
        date_dir = self._base_path / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir / f"{order_id}.json"

    def save(self, record: OrderRecord) -> None:
        """保存订单记录

        Args:
            record: 订单记录
        """
        try:
            order_path = self._get_order_path(
                record.order.order_id, record.order.created_at
            )

            with open(order_path, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)

            # 更新索引
            self._update_index(record)

            logger.debug(f"Order saved: {record.order.order_id} -> {order_path}")

        except Exception as e:
            logger.error(f"Failed to save order {record.order.order_id}: {e}")
            raise

    def _update_index(self, record: OrderRecord) -> None:
        """更新订单索引"""
        index_path = self._base_path / "index.json"

        # 读取现有索引
        index: dict[str, Any] = {}
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f)
            except Exception:
                index = {}

        # 更新索引
        if "orders" not in index:
            index["orders"] = {}

        order_info = {
            "order_id": record.order.order_id,
            "decision_id": record.order.decision_id,
            "symbol": record.order.symbol,
            "status": record.order.status.value,
            "decision_type": record.order.decision_type,
            "created_at": record.order.created_at.isoformat(),
            "is_complete": record.is_complete,
        }

        index["orders"][record.order.order_id] = order_info
        index["updated_at"] = datetime.now().isoformat()

        # 写入索引
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def get(self, order_id: str) -> OrderRecord | None:
        """获取订单记录

        Args:
            order_id: 订单 ID

        Returns:
            订单记录，不存在则返回 None
        """
        # 从索引获取日期信息
        index_path = self._base_path / "index.json"
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f)

                order_info = index.get("orders", {}).get(order_id)
                if order_info:
                    created_at = datetime.fromisoformat(order_info["created_at"])
                    order_path = self._get_order_path(order_id, created_at)

                    if order_path.exists():
                        with open(order_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return OrderRecord.from_dict(data)

            except Exception as e:
                logger.error(f"Failed to get order {order_id}: {e}")

        # 如果索引中找不到，扫描目录
        return self._scan_for_order(order_id)

    def _scan_for_order(self, order_id: str) -> OrderRecord | None:
        """扫描目录查找订单"""
        for date_dir in self._base_path.iterdir():
            if date_dir.is_dir() and date_dir.name != "archive":
                order_path = date_dir / f"{order_id}.json"
                if order_path.exists():
                    try:
                        with open(order_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return OrderRecord.from_dict(data)
                    except Exception:
                        pass
        return None

    def get_by_status(self, status: OrderStatus) -> list[OrderRecord]:
        """按状态获取订单

        Args:
            status: 订单状态

        Returns:
            符合条件的订单列表
        """
        results = []
        index_path = self._base_path / "index.json"

        if not index_path.exists():
            return results

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)

            for order_id, info in index.get("orders", {}).items():
                if info.get("status") == status.value:
                    record = self.get(order_id)
                    if record:
                        results.append(record)

        except Exception as e:
            logger.error(f"Failed to get orders by status {status}: {e}")

        return results

    def get_open_orders(self) -> list[OrderRecord]:
        """获取所有未完成订单"""
        open_statuses = [
            OrderStatus.PENDING_VALIDATION,
            OrderStatus.APPROVED,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIAL_FILLED,
        ]

        results = []
        for status in open_statuses:
            results.extend(self.get_by_status(status))

        return results

    def get_recent(self, days: int = 7) -> list[OrderRecord]:
        """获取最近的订单

        Args:
            days: 天数

        Returns:
            最近 N 天的订单列表
        """
        results = []
        cutoff = datetime.now() - timedelta(days=days)

        for date_dir in sorted(self._base_path.iterdir(), reverse=True):
            if not date_dir.is_dir() or date_dir.name in ("archive",):
                continue

            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    break

                for order_file in date_dir.glob("*.json"):
                    try:
                        with open(order_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        record = OrderRecord.from_dict(data)
                        results.append(record)
                    except Exception as e:
                        logger.warning(f"Failed to load order {order_file}: {e}")

            except ValueError:
                continue

        # 按创建时间排序
        results.sort(key=lambda r: r.order.created_at, reverse=True)
        return results

    def get_by_decision(self, decision_id: str) -> list[OrderRecord]:
        """按决策 ID 获取订单

        Args:
            decision_id: 决策 ID

        Returns:
            关联的订单列表
        """
        results = []
        index_path = self._base_path / "index.json"

        if not index_path.exists():
            return results

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)

            for order_id, info in index.get("orders", {}).items():
                if info.get("decision_id") == decision_id:
                    record = self.get(order_id)
                    if record:
                        results.append(record)

        except Exception as e:
            logger.error(f"Failed to get orders by decision {decision_id}: {e}")

        return results

    def get_daily_orders_by_underlying(
        self,
        underlying: str,
        target_date: date | None = None,
        include_pending: bool = True,
    ) -> list[OrderRecord]:
        """获取指定 underlying 当日的订单列表

        Args:
            underlying: 标的代码 (e.g., "AAPL", "TQQQ")
            target_date: 目标日期，默认今天
            include_pending: 是否包含 pending 状态的订单

        Returns:
            符合条件的订单列表
        """
        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        results = []
        date_str = target_date.strftime("%Y-%m-%d")
        date_dir = self._base_path / date_str

        if not date_dir.exists():
            return results

        # 定义哪些状态算作 "pending"
        pending_statuses = {
            OrderStatus.PENDING_VALIDATION,
            OrderStatus.APPROVED,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIAL_FILLED,
        }

        # 定义哪些状态算作 "有效" (包含成交)
        valid_statuses = pending_statuses | {OrderStatus.FILLED}

        try:
            for order_file in date_dir.glob("*.json"):
                try:
                    with open(order_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    record = OrderRecord.from_dict(data)
                    order = record.order

                    # 检查 underlying 匹配
                    order_underlying = order.underlying or order.symbol
                    # 处理可能的格式差异 (US.AAPL vs AAPL)
                    if "." in order_underlying:
                        order_underlying = order_underlying.split(".")[-1]
                    if "." in underlying:
                        underlying_check = underlying.split(".")[-1]
                    else:
                        underlying_check = underlying

                    if order_underlying.upper() != underlying_check.upper():
                        continue

                    # 检查状态
                    if include_pending:
                        # 包含所有有效状态
                        if order.status not in valid_statuses:
                            continue
                    else:
                        # 只包含已成交
                        if order.status not in {
                            OrderStatus.FILLED,
                            OrderStatus.PARTIAL_FILLED,
                        }:
                            continue

                    results.append(record)

                except Exception as e:
                    logger.warning(f"Failed to load order {order_file}: {e}")

        except Exception as e:
            logger.error(
                f"Failed to get daily orders for {underlying} on {date_str}: {e}"
            )

        return results
