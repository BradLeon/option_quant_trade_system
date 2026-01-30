"""
Daily Trade Limits - 每日交易限额管理

追踪每个 underlying 在当日已提交的交易量/金额，
在新订单提交前检查是否超过限额。

Usage:
    tracker = DailyTradeTracker(order_store, config)
    allowed, reason = tracker.check_limits("AAPL", quantity=-2, value=5000.0, nlv=100000.0)
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from src.business.trading.order.store import OrderStore
from src.business.trading.models.order import OrderRecord, OrderStatus

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    """从环境变量获取 float"""
    val = os.getenv(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _env_int(key: str, default: int) -> int:
    """从环境变量获取 int"""
    val = os.getenv(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool) -> bool:
    """从环境变量获取 bool"""
    val = os.getenv(key)
    if val is not None:
        return val.lower() in ("true", "1", "yes")
    return default


@dataclass
class DailyLimitsConfig:
    """每日交易限额配置

    支持通过环境变量覆盖默认值 (前缀: DAILY_LIMITS_)

    示例:
        export DAILY_LIMITS_MAX_QUANTITY_PER_UNDERLYING=3
        export DAILY_LIMITS_MAX_VALUE_PCT_PER_UNDERLYING=5.0
    """

    # 是否启用每日限额
    enabled: bool = True

    # 每个 underlying 每天最多开仓数量（绝对值）
    max_quantity_per_underlying: int = 5

    # 每个 underlying 每天开仓市值不超过 NLV 的 X%
    max_value_pct_per_underlying: float = 5.0

    # 全账户每天总开仓市值不超过 NLV 的 X%
    max_total_value_pct: float = 25.0

    # 是否计入 pending 订单 (true) 还是只计已成交 (false)
    include_pending_orders: bool = True

    @classmethod
    def load(cls) -> "DailyLimitsConfig":
        """加载配置

        优先级: 环境变量 > 默认值
        """
        return cls(
            enabled=_env_bool("DAILY_LIMITS_ENABLED", True),
            max_quantity_per_underlying=_env_int(
                "DAILY_LIMITS_MAX_QUANTITY_PER_UNDERLYING", 5
            ),
            max_value_pct_per_underlying=_env_float(
                "DAILY_LIMITS_MAX_VALUE_PCT_PER_UNDERLYING", 5.0
            ),
            max_total_value_pct=_env_float("DAILY_LIMITS_MAX_TOTAL_VALUE_PCT", 25.0),
            include_pending_orders=_env_bool(
                "DAILY_LIMITS_INCLUDE_PENDING_ORDERS", True
            ),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyLimitsConfig":
        """从字典创建配置"""
        return cls(
            enabled=data.get("enabled", True),
            max_quantity_per_underlying=data.get("max_quantity_per_underlying", 5),
            max_value_pct_per_underlying=data.get("max_value_pct_per_underlying", 5.0),
            max_total_value_pct=data.get("max_total_value_pct", 25.0),
            include_pending_orders=data.get("include_pending_orders", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "max_quantity_per_underlying": self.max_quantity_per_underlying,
            "max_value_pct_per_underlying": self.max_value_pct_per_underlying,
            "max_total_value_pct": self.max_total_value_pct,
            "include_pending_orders": self.include_pending_orders,
        }


@dataclass
class DailyStats:
    """每日交易统计

    注意: quantity 和 value 都使用绝对值累加
    - buy 1 + sell 1 = 2 (不是 0)
    """

    underlying: str
    date: date
    total_quantity: int  # 绝对值累加
    total_value: float  # 绝对值累加
    order_count: int


class DailyTradeTracker:
    """每日交易限额追踪器

    追踪每个 underlying 当日已提交的交易量/金额，
    在新开仓前检查是否超过限额。

    Usage:
        tracker = DailyTradeTracker(order_store, config)

        # 检查是否允许新开仓
        allowed, reason = tracker.check_limits("AAPL", quantity=-2, value=5000.0, nlv=100000.0)

        # 过滤超限机会
        filtered = tracker.filter_opportunities(opportunities, account_state)
    """

    def __init__(
        self,
        order_store: OrderStore,
        config: DailyLimitsConfig | None = None,
    ) -> None:
        """初始化

        Args:
            order_store: 订单存储
            config: 每日限额配置
        """
        self._store = order_store
        self._config = config or DailyLimitsConfig.load()

        # 缓存当日统计，避免重复查询
        self._cache: dict[str, DailyStats] = {}
        self._cache_date: date | None = None

    def _invalidate_cache_if_needed(self) -> None:
        """如果日期变更则清除缓存"""
        today = date.today()
        if self._cache_date != today:
            self._cache.clear()
            self._cache_date = today

    def get_daily_stats(
        self,
        underlying: str,
        target_date: date | None = None,
    ) -> DailyStats:
        """获取指定 underlying 当日交易统计

        Args:
            underlying: 标的代码
            target_date: 目标日期，默认今天

        Returns:
            DailyStats 统计信息
        """
        target_date = target_date or date.today()
        self._invalidate_cache_if_needed()

        # 检查缓存
        cache_key = f"{underlying}:{target_date.isoformat()}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 查询订单
        orders = self._store.get_daily_orders_by_underlying(
            underlying=underlying,
            target_date=target_date,
            include_pending=self._config.include_pending_orders,
        )

        # 计算统计（使用绝对值！）
        total_quantity = 0
        total_value = 0.0

        for record in orders:
            order = record.order
            # 使用绝对值
            qty = abs(order.quantity)
            total_quantity += qty

            # 计算订单市值 = |quantity| * price * multiplier
            price = order.limit_price or 0.0
            multiplier = order.contract_multiplier or 100
            value = qty * price * multiplier
            total_value += value

        stats = DailyStats(
            underlying=underlying,
            date=target_date,
            total_quantity=total_quantity,
            total_value=total_value,
            order_count=len(orders),
        )

        # 缓存结果
        self._cache[cache_key] = stats

        logger.debug(
            f"Daily stats for {underlying}: qty={total_quantity}, "
            f"value=${total_value:.2f}, orders={len(orders)}"
        )

        return stats

    def get_total_daily_value(self, target_date: date | None = None) -> float:
        """获取当日所有 underlying 的总交易市值

        Args:
            target_date: 目标日期，默认今天

        Returns:
            总市值（绝对值累加）
        """
        target_date = target_date or date.today()

        # 获取当日所有订单
        orders = self._store.get_recent(days=1)

        total_value = 0.0
        for record in orders:
            order = record.order
            # 只计入目标日期的订单
            if order.created_at.date() != target_date:
                continue
            # 如果不计入 pending 订单，检查状态
            if not self._config.include_pending_orders:
                if order.status not in (
                    OrderStatus.FILLED,
                    OrderStatus.PARTIAL_FILLED,
                ):
                    continue

            qty = abs(order.quantity)
            price = order.limit_price or 0.0
            multiplier = order.contract_multiplier or 100
            total_value += qty * price * multiplier

        return total_value

    def check_limits(
        self,
        underlying: str,
        quantity: int,
        value: float,
        nlv: float,
    ) -> tuple[bool, str]:
        """检查是否允许新开仓

        Args:
            underlying: 标的代码
            quantity: 开仓数量（可正可负，内部用 abs()）
            value: 订单市值（可正可负，内部用 abs()）
            nlv: 账户净值

        Returns:
            (allowed, reason) - 是否允许，拒绝原因
        """
        if not self._config.enabled:
            return True, ""

        if nlv <= 0:
            logger.warning("NLV <= 0, skipping daily limits check")
            return True, ""

        today = date.today()
        daily_stats = self.get_daily_stats(underlying, today)

        # 使用绝对值
        abs_quantity = abs(quantity)
        abs_value = abs(value)

        # 检查数量限额
        new_total_qty = daily_stats.total_quantity + abs_quantity
        if new_total_qty > self._config.max_quantity_per_underlying:
            reason = (
                f"{underlying} 已达当日数量限额: "
                f"{daily_stats.total_quantity}/{self._config.max_quantity_per_underlying} 张, "
                f"新增 {abs_quantity} 张将超限"
            )
            logger.info(f"Daily limit exceeded: {reason}")
            return False, reason

        # 检查单标的市值占比限额
        existing_value_pct = (daily_stats.total_value / nlv) * 100
        new_value_pct = (abs_value / nlv) * 100
        total_value_pct = existing_value_pct + new_value_pct

        if total_value_pct > self._config.max_value_pct_per_underlying:
            reason = (
                f"{underlying} 已达当日市值限额: "
                f"{existing_value_pct:.2f}% + {new_value_pct:.2f}% = {total_value_pct:.2f}% "
                f"> {self._config.max_value_pct_per_underlying}% of NLV"
            )
            logger.info(f"Daily limit exceeded: {reason}")
            return False, reason

        # 检查全账户总市值限额
        total_daily_value = self.get_total_daily_value(today)
        total_daily_pct = ((total_daily_value + abs_value) / nlv) * 100

        if total_daily_pct > self._config.max_total_value_pct:
            reason = (
                f"全账户已达当日总市值限额: "
                f"{(total_daily_value / nlv) * 100:.2f}% + {new_value_pct:.2f}% = {total_daily_pct:.2f}% "
                f"> {self._config.max_total_value_pct}% of NLV"
            )
            logger.info(f"Daily limit exceeded: {reason}")
            return False, reason

        return True, ""

    def filter_opportunities(
        self,
        opportunities: list[Any],
        nlv: float,
    ) -> tuple[list[Any], list[tuple[Any, str]]]:
        """过滤超限的交易机会

        Args:
            opportunities: 交易机会列表，每个机会需要有 underlying, quantity, market_value 属性
            nlv: 账户净值

        Returns:
            (通过的机会列表, [(被过滤的机会, 原因)...])
        """
        if not self._config.enabled:
            return opportunities, []

        passed: list[Any] = []
        filtered: list[tuple[Any, str]] = []

        # 临时追踪本批次内的累加量（用于同一批次内的多个同 underlying 机会）
        batch_quantities: dict[str, int] = {}
        batch_values: dict[str, float] = {}

        for opp in opportunities:
            # 获取机会的属性
            underlying = getattr(opp, "underlying", None)
            if underlying is None:
                # 如果没有 underlying 属性，尝试从 symbol 解析
                symbol = getattr(opp, "symbol", "")
                # 简单假设 symbol 格式: US.AAPL... 或 AAPL...
                underlying = symbol.split(".")[0] if "." in symbol else symbol

            quantity = getattr(opp, "quantity", 1)
            # 市值可能来自不同属性
            market_value = getattr(
                opp,
                "market_value",
                getattr(opp, "notional_value", getattr(opp, "value", 0.0)),
            )

            # 计算包含本批次已通过机会后的累计值
            batch_qty = batch_quantities.get(underlying, 0)
            batch_val = batch_values.get(underlying, 0.0)

            # 临时增加本批次累加量，检查限额
            check_qty = quantity + batch_qty
            check_val = market_value + batch_val

            allowed, reason = self.check_limits(
                underlying=underlying,
                quantity=check_qty,
                value=check_val,
                nlv=nlv,
            )

            if allowed:
                passed.append(opp)
                # 更新本批次累加量
                batch_quantities[underlying] = batch_qty + abs(quantity)
                batch_values[underlying] = batch_val + abs(market_value)
            else:
                filtered.append((opp, reason))

        if filtered:
            logger.info(
                f"Daily limits filtered {len(filtered)} opportunities: "
                f"{[f[0].underlying if hasattr(f[0], 'underlying') else 'unknown' for f in filtered]}"
            )

        return passed, filtered

    def get_usage_summary(self, nlv: float) -> dict[str, dict[str, Any]]:
        """获取当日限额使用情况汇总

        Args:
            nlv: 账户净值

        Returns:
            {underlying: {qty_used, qty_limit, value_used, value_limit, value_pct}}
        """
        today = date.today()
        orders = self._store.get_recent(days=1)

        # 按 underlying 分组统计
        by_underlying: dict[str, dict[str, float]] = {}

        for record in orders:
            order = record.order
            if order.created_at.date() != today:
                continue

            underlying = order.underlying or order.symbol
            if underlying not in by_underlying:
                by_underlying[underlying] = {"qty": 0, "value": 0.0}

            by_underlying[underlying]["qty"] += abs(order.quantity)
            price = order.limit_price or 0.0
            multiplier = order.contract_multiplier or 100
            by_underlying[underlying]["value"] += (
                abs(order.quantity) * price * multiplier
            )

        # 构造汇总
        summary = {}
        for underlying, stats in by_underlying.items():
            value_pct = (stats["value"] / nlv * 100) if nlv > 0 else 0.0
            summary[underlying] = {
                "qty_used": int(stats["qty"]),
                "qty_limit": self._config.max_quantity_per_underlying,
                "value_used": stats["value"],
                "value_limit_pct": self._config.max_value_pct_per_underlying,
                "value_pct": value_pct,
            }

        return summary

    def invalidate_cache(self) -> None:
        """手动清除缓存（在订单提交后调用）"""
        self._cache.clear()
