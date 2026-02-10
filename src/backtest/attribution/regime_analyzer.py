"""
Regime Analyzer - 市场环境分析

为每个交易日打 Regime 标签，并按 Regime 归因分析策略在不同市场环境下的表现。

Regime 维度:
- VIX Level: LOW (<15), NORMAL (15-20), ELEVATED (20-25), HIGH (>25)
- VIX Trend: RISING, FALLING, STABLE (vs 5日均线)
- SPY Trend: BULLISH (>1%), BEARISH (<-1%), NEUTRAL
- Events: FOMC, CPI, JOBS, NONE

Usage:
    analyzer = RegimeAnalyzer(
        daily_attributions=daily_attrs,
        data_provider=provider,
        start_date=date(2025, 12, 1),
        end_date=date(2026, 2, 7),
    )
    regimes = analyzer.label_all_days()
    stats = analyzer.attribute_by_regime()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.backtest.attribution.models import (
    DailyAttribution,
    DayRegime,
    RegimeStats,
)

if TYPE_CHECKING:
    from src.data.providers.base import DataProvider

logger = logging.getLogger(__name__)


class RegimeAnalyzer:
    """市场环境分析器"""

    def __init__(
        self,
        daily_attributions: list[DailyAttribution],
        data_provider: DataProvider,
        start_date: date,
        end_date: date,
    ) -> None:
        self._daily_attrs = daily_attributions
        self._data_provider = data_provider
        self._start_date = start_date
        self._end_date = end_date

        # 日归因索引
        self._attr_by_date: dict[date, DailyAttribution] = {
            da.date: da for da in daily_attributions
        }

        # 缓存
        self._regimes: list[DayRegime] | None = None

    def label_all_days(self) -> list[DayRegime]:
        """为每个交易日打 Regime 标签

        Returns:
            按日期排序的 DayRegime 列表
        """
        if self._regimes is not None:
            return self._regimes

        # 获取 VIX 数据
        vix_data = self._fetch_vix_data()
        # 获取 SPY 数据
        spy_data = self._fetch_spy_data()

        # 生成 Regime 标签
        regimes: list[DayRegime] = []
        trading_dates = sorted(self._attr_by_date.keys())

        for d in trading_dates:
            vix_close = vix_data.get(d, 0.0)
            vix_level = self._classify_vix_level(vix_close)
            vix_trend = self._classify_vix_trend(d, vix_data)
            spy_trend = self._classify_spy_trend(d, spy_data)
            event_type = self._classify_event(d)

            # 综合标签
            parts = []
            if vix_level in ("ELEVATED", "HIGH"):
                parts.append("HIGH_VOL")
            elif vix_level == "LOW":
                parts.append("LOW_VOL")
            else:
                parts.append("NORMAL_VOL")

            parts.append(spy_trend)

            if event_type != "NONE":
                parts.append(event_type)

            regime_label = "_".join(parts)

            regimes.append(DayRegime(
                date=d,
                vix_close=vix_close,
                vix_level=vix_level,
                vix_trend=vix_trend,
                spy_trend=spy_trend,
                event_type=event_type,
                regime_label=regime_label,
            ))

        self._regimes = regimes
        return regimes

    def attribute_by_regime(self) -> dict[str, RegimeStats]:
        """按 Regime 归因

        Returns:
            regime_label -> RegimeStats 字典
        """
        regimes = self.label_all_days()

        # 分组
        groups: dict[str, list[tuple[DayRegime, DailyAttribution | None]]] = defaultdict(list)
        for regime in regimes:
            attr = self._attr_by_date.get(regime.date)
            groups[regime.regime_label].append((regime, attr))

        results: dict[str, RegimeStats] = {}
        for label, items in sorted(groups.items()):
            daily_pnls: list[float] = []
            for _, attr in items:
                if attr is not None:
                    daily_pnls.append(attr.total_pnl)
                else:
                    daily_pnls.append(0.0)

            total_pnl = sum(daily_pnls)
            trading_days = len(daily_pnls)
            win_days = sum(1 for p in daily_pnls if p > 0)

            # 计算 Sharpe ratio (日级别)
            sharpe = None
            if trading_days >= 2:
                try:
                    from src.engine.portfolio.returns import calc_sharpe_ratio
                    sharpe = calc_sharpe_ratio(daily_pnls)
                except Exception:
                    pass

            results[label] = RegimeStats(
                regime_label=label,
                trading_days=trading_days,
                total_pnl=total_pnl,
                avg_daily_pnl=total_pnl / trading_days if trading_days > 0 else 0.0,
                win_rate=win_days / trading_days if trading_days > 0 else 0.0,
                max_daily_loss=min(daily_pnls) if daily_pnls else 0.0,
                sharpe_ratio=sharpe,
            )

        return results

    def get_worst_regimes(self, n: int = 3) -> list[RegimeStats]:
        """表现最差的 N 个 Regime"""
        stats = self.attribute_by_regime()
        return sorted(stats.values(), key=lambda s: s.avg_daily_pnl)[:n]

    # ========== 内部方法 ==========

    def _fetch_vix_data(self) -> dict[date, float]:
        """获取 VIX 日级别数据"""
        data: dict[date, float] = {}
        try:
            # 多取一些历史数据用于计算 SMA
            lookback_start = self._start_date - timedelta(days=15)
            macro = self._data_provider.get_macro_data(
                indicator="^VIX",
                start_date=lookback_start,
                end_date=self._end_date,
            )
            for item in macro:
                if hasattr(item, "date") and hasattr(item, "close"):
                    d = item.date if isinstance(item.date, date) else item.date
                    data[d] = item.close or 0.0
        except Exception as e:
            logger.warning(f"Failed to fetch VIX data: {e}")
        return data

    def _fetch_spy_data(self) -> dict[date, float]:
        """获取 SPY 收盘价"""
        data: dict[date, float] = {}
        try:
            lookback_start = self._start_date - timedelta(days=15)
            from src.data.models.kline import KlineType
            bars = self._data_provider.get_history_kline(
                symbol="SPY",
                ktype=KlineType.DAILY,
                start_date=lookback_start,
                end_date=self._end_date,
            )
            for bar in bars:
                if bar.close and bar.close > 0:
                    data[bar.date] = bar.close
        except Exception as e:
            logger.warning(f"Failed to fetch SPY data: {e}")
        return data

    @staticmethod
    def _classify_vix_level(vix: float) -> str:
        if vix < 15:
            return "LOW"
        if vix < 20:
            return "NORMAL"
        if vix < 25:
            return "ELEVATED"
        return "HIGH"

    @staticmethod
    def _classify_vix_trend(
        d: date,
        vix_data: dict[date, float],
    ) -> str:
        """VIX 趋势：与 5 日均线比较"""
        current = vix_data.get(d)
        if current is None:
            return "STABLE"

        # 获取过去 5 个交易日的 VIX
        recent: list[float] = []
        for offset in range(1, 8):  # 多取几天以应对非交易日
            check_date = d - timedelta(days=offset)
            val = vix_data.get(check_date)
            if val is not None:
                recent.append(val)
            if len(recent) >= 5:
                break

        if len(recent) < 3:
            return "STABLE"

        sma = sum(recent) / len(recent)
        pct_diff = (current - sma) / sma if sma > 0 else 0.0

        if pct_diff > 0.05:  # VIX 比均线高 5%
            return "RISING"
        if pct_diff < -0.05:
            return "FALLING"
        return "STABLE"

    @staticmethod
    def _classify_spy_trend(
        d: date,
        spy_data: dict[date, float],
    ) -> str:
        """SPY 趋势: 5 日累计涨跌幅"""
        current = spy_data.get(d)
        if current is None:
            return "NEUTRAL"

        # 找 5 个交易日前的价格
        prev_price = None
        for offset in range(4, 10):
            check_date = d - timedelta(days=offset)
            val = spy_data.get(check_date)
            if val is not None:
                prev_price = val
                break

        if prev_price is None or prev_price <= 0:
            return "NEUTRAL"

        pct_change = (current - prev_price) / prev_price
        if pct_change > 0.01:
            return "BULLISH"
        if pct_change < -0.01:
            return "BEARISH"
        return "NEUTRAL"

    def _classify_event(self, d: date) -> str:
        """检测重大事件日"""
        try:
            if hasattr(self._data_provider, "check_macro_blackout"):
                is_blackout, events = self._data_provider.check_macro_blackout(
                    target_date=d,
                    blackout_days=0,  # 只检查当天
                )
                if is_blackout and events:
                    # 返回第一个事件类型
                    event = events[0]
                    if hasattr(event, "event_type"):
                        return str(event.event_type).upper()
                    return "EVENT"
        except Exception as e:
            logger.debug(f"Failed to check events for {d}: {e}")
        return "NONE"
