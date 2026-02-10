"""
Slice Attribution Engine - 多维度切片归因

沿多个维度对交易归因结果进行切片分析：
- 按标的 (underlying)
- 按期权类型 (CALL/PUT × BUY/SELL)
- 按开仓 IV 环境 (LOW / MEDIUM / HIGH)
- 按平仓原因 (profit_target / stop_loss / expired 等)

Usage:
    engine = SliceAttributionEngine(trade_attributions, position_snapshots)
    by_symbol = engine.by_underlying()
    by_iv = engine.by_entry_iv_regime()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from src.backtest.attribution.models import (
    PositionSnapshot,
    SliceStats,
    TradeAttribution,
)

logger = logging.getLogger(__name__)


class SliceAttributionEngine:
    """多维度切片归因引擎"""

    def __init__(
        self,
        trade_attributions: list[TradeAttribution],
        position_snapshots: list[PositionSnapshot],
    ) -> None:
        self._trade_attrs = trade_attributions
        self._position_snapshots = position_snapshots

        # 构建 entry snap 索引: position_id -> first PositionSnapshot
        self._entry_snaps: dict[str, PositionSnapshot] = {}
        snap_by_pos: dict[str, list[PositionSnapshot]] = defaultdict(list)
        for snap in position_snapshots:
            snap_by_pos[snap.position_id].append(snap)
        for pos_id, snaps in snap_by_pos.items():
            snaps.sort(key=lambda s: s.date)
            self._entry_snaps[pos_id] = snaps[0]

    def by_underlying(self) -> dict[str, SliceStats]:
        """按标的切片归因"""
        return self._slice_by(lambda ta: ta.underlying)

    def by_option_type(self) -> dict[str, SliceStats]:
        """按期权类型切片归因

        分组为: SHORT_PUT, SHORT_CALL, LONG_PUT, LONG_CALL
        """

        def classify(ta: TradeAttribution) -> str:
            side = "SHORT" if ta.quantity < 0 else "LONG"
            opt_type = ta.option_type.upper() if ta.option_type else "UNKNOWN"
            if opt_type in ("PUT", "CALL"):
                return f"{side}_{opt_type}"
            return f"{side}_{opt_type}"

        return self._slice_by(classify)

    def by_entry_iv_regime(self) -> dict[str, SliceStats]:
        """按开仓 IV 环境切片归因

        IV Rank 分组:
        - LOW: iv_rank < 30
        - MEDIUM: 30 <= iv_rank <= 70
        - HIGH: iv_rank > 70
        - UNKNOWN: iv_rank 不可用
        """

        def classify(ta: TradeAttribution) -> str:
            iv_rank = ta.entry_iv_rank
            if iv_rank is None:
                # 回退: 从 entry snap 获取
                entry_snap = self._entry_snaps.get(ta.trade_id)
                if entry_snap:
                    iv_rank = entry_snap.iv_rank

            if iv_rank is None:
                return "UNKNOWN"
            if iv_rank < 30:
                return "LOW"
            if iv_rank <= 70:
                return "MEDIUM"
            return "HIGH"

        return self._slice_by(classify)

    def by_exit_reason(self) -> dict[str, SliceStats]:
        """按平仓原因切片归因"""

        def classify(ta: TradeAttribution) -> str:
            # 优先使用结构化类型
            if ta.exit_reason_type:
                return ta.exit_reason_type.upper()
            # fallback: 旧版字符串匹配（兼容无 exit_reason_type 的历史数据）
            return self._classify_exit_reason_legacy(ta)

        return self._slice_by(classify)

    @staticmethod
    def _classify_exit_reason_legacy(ta: TradeAttribution) -> str:
        """旧版字符串匹配分类（兼容无 exit_reason_type 的历史数据）"""
        reason = ta.exit_reason or "unknown"
        reason_lower = reason.lower()
        if "expired_worthless" in reason_lower or "expired worthless" in reason_lower:
            return "EXPIRED_WORTHLESS"
        if "assigned" in reason_lower or "expired_itm" in reason_lower:
            return "EXPIRED_ITM"
        if "profit" in reason_lower or "止盈" in reason:
            return "PROFIT_TARGET"
        if "触发止损" in reason or "平仓止损" in reason or "无条件平仓" in reason:
            return "STOP_LOSS"
        if "stop" in reason_lower or "loss" in reason_lower:
            return "STOP_LOSS"
        if "otm" in reason_lower or "OTM" in reason:
            return "STOP_LOSS_OTM"
        if "delta" in reason_lower or "DELTA" in reason:
            return "STOP_LOSS_DELTA"
        if "dte" in reason_lower or "time" in reason_lower:
            return "TIME_EXIT"
        if "roll" in reason_lower:
            return "ROLL_FORWARD"
        if "close" in reason_lower or "平仓" in reason:
            return "CLOSE"
        return reason[:30].upper() if len(reason) > 30 else reason.upper()

    def _slice_by(
        self,
        key_fn: Callable[[TradeAttribution], str],
    ) -> dict[str, SliceStats]:
        """通用切片方法

        Args:
            key_fn: 分组函数，输入 TradeAttribution，返回分组键

        Returns:
            分组键 -> SliceStats 字典
        """
        groups: dict[str, list[TradeAttribution]] = defaultdict(list)
        for ta in self._trade_attrs:
            key = key_fn(ta)
            groups[key].append(ta)

        total_pnl_all = sum(ta.total_pnl for ta in self._trade_attrs)

        results: dict[str, SliceStats] = {}
        for label, trades in sorted(groups.items()):
            total_pnl = sum(t.total_pnl for t in trades)
            winning = sum(1 for t in trades if t.total_pnl > 0)
            count = len(trades)

            results[label] = SliceStats(
                label=label,
                trade_count=count,
                total_pnl=total_pnl,
                avg_pnl=total_pnl / count if count > 0 else 0.0,
                win_rate=winning / count if count > 0 else 0.0,
                pnl_contribution_pct=(
                    total_pnl / total_pnl_all if total_pnl_all != 0 else 0.0
                ),
                delta_pnl=sum(t.delta_pnl for t in trades),
                gamma_pnl=sum(t.gamma_pnl for t in trades),
                theta_pnl=sum(t.theta_pnl for t in trades),
                vega_pnl=sum(t.vega_pnl for t in trades),
                avg_holding_days=(
                    sum(t.holding_days for t in trades) / count if count > 0 else 0.0
                ),
                max_win=max((t.total_pnl for t in trades), default=0.0),
                max_loss=min((t.total_pnl for t in trades), default=0.0),
            )

        return results
