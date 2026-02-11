"""
Strategy Diagnosis - 策略诊断

分析入场/出场质量和风控有效性:
- Entry Quality: IV vs Realized Vol, VRP 捕获
- Exit Quality: What-If 反事实分析 (持有到期 vs 实际平仓)
- Reversal Rate: 止损后反转率

Usage:
    diagnosis = StrategyDiagnosis(
        trade_attributions=trade_attrs,
        position_snapshots=collector.position_snapshots,
        trade_records=result.trade_records,
        data_provider=provider,
    )
    entry_report = diagnosis.analyze_entry_quality()
    exit_report = diagnosis.analyze_exit_quality()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from src.backtest.attribution.models import (
    EntryQualityReport,
    ExitQualityReport,
    PositionSnapshot,
    ReversalReport,
    TradeAttribution,
    TradeEntryQuality,
    TradeExitQuality,
)

if TYPE_CHECKING:
    from src.backtest.engine.trade_simulator import TradeRecord
    from src.data.providers.base import DataProvider

logger = logging.getLogger(__name__)

# 止损类平仓原因
STOP_LOSS_REASONS = frozenset({
    "STOP_LOSS", "STOP_LOSS_DELTA", "STOP_LOSS_PRICE", "STOP_LOSS_PNL",
    "stop_loss", "stop_loss_delta", "stop_loss_price", "stop_loss_pnl",
})


class StrategyDiagnosis:
    """策略诊断"""

    def __init__(
        self,
        trade_attributions: list[TradeAttribution],
        position_snapshots: list[PositionSnapshot],
        trade_records: list[TradeRecord],
        data_provider: DataProvider | None = None,
    ) -> None:
        self._trade_attrs = trade_attributions
        self._position_snapshots = position_snapshots
        self._trade_records = trade_records
        self._data_provider = data_provider

        # 索引: position_id -> sorted snapshots
        self._snap_by_pos: dict[str, list[PositionSnapshot]] = defaultdict(list)
        for snap in position_snapshots:
            self._snap_by_pos[snap.position_id].append(snap)
        for pos_id in self._snap_by_pos:
            self._snap_by_pos[pos_id].sort(key=lambda s: s.date)

        # 索引: position_id -> trade info from records
        self._trade_info = self._build_trade_info()

    def _build_trade_info(self) -> dict[str, dict]:
        """从 trade_records 提取交易元信息"""
        info: dict[str, dict] = {}
        for record in self._trade_records:
            pid = record.position_id
            if pid is None:
                continue
            if pid not in info:
                info[pid] = {}
            if record.action == "open":
                info[pid]["entry_date"] = record.trade_date
                info[pid]["entry_price"] = record.price
                info[pid]["quantity"] = record.quantity
                info[pid]["symbol"] = record.symbol
                info[pid]["underlying"] = record.underlying
                info[pid]["strike"] = record.strike
                info[pid]["expiration"] = record.expiration
                info[pid]["option_type"] = (
                    record.option_type.value
                    if hasattr(record.option_type, "value")
                    else str(record.option_type)
                )
            elif record.action in ("close", "expire"):
                info[pid]["exit_date"] = record.trade_date
                info[pid]["exit_reason"] = record.reason
                info[pid]["exit_price"] = record.price
                info[pid]["realized_pnl"] = record.pnl
        return info

    def analyze_entry_quality(self) -> EntryQualityReport:
        """入场质量分析

        对每笔交易：
        1. 获取开仓时 IV（从首日 PositionSnapshot）
        2. 计算持仓期间的实现波动率（从 data_provider 获取历史价格）
        3. 计算 VRP = entry_iv - realized_vol

        Returns:
            EntryQualityReport
        """
        trades: list[TradeEntryQuality] = []

        for ta in self._trade_attrs:
            entry_snap = self._get_entry_snap(ta.trade_id)
            info = self._trade_info.get(ta.trade_id, {})

            entry_iv = ta.entry_iv or (entry_snap.iv if entry_snap else None)
            entry_iv_rank = ta.entry_iv_rank or (
                entry_snap.iv_rank if entry_snap else None
            )
            entry_iv_pct = entry_snap.iv_percentile if entry_snap else None

            # 计算实现波动率
            realized_vol = self._compute_realized_vol(ta, info)

            # 计算 VRP
            iv_rv_spread = None
            vrp_captured = None
            if entry_iv is not None and realized_vol is not None:
                iv_rv_spread = entry_iv - realized_vol
                # VRP captured ≈ (IV - RV) × Vega × lot_size
                if entry_snap and entry_snap.vega is not None:
                    vrp_captured = iv_rv_spread * entry_snap.vega * entry_snap.lot_size

            trades.append(TradeEntryQuality(
                trade_id=ta.trade_id,
                underlying=ta.underlying,
                entry_iv=entry_iv,
                realized_vol=realized_vol,
                iv_rv_spread=iv_rv_spread,
                vrp_captured=vrp_captured,
                entry_iv_rank=entry_iv_rank,
                entry_iv_percentile=entry_iv_pct,
            ))

        # 汇总
        iv_ranks = [t.entry_iv_rank for t in trades if t.entry_iv_rank is not None]
        iv_rv_spreads = [t.iv_rv_spread for t in trades if t.iv_rv_spread is not None]

        return EntryQualityReport(
            trades=trades,
            avg_entry_iv_rank=(
                sum(iv_ranks) / len(iv_ranks) if iv_ranks else None
            ),
            high_iv_entry_pct=(
                sum(1 for r in iv_ranks if r > 50) / len(iv_ranks)
                if iv_ranks
                else 0.0
            ),
            avg_iv_rv_spread=(
                sum(iv_rv_spreads) / len(iv_rv_spreads) if iv_rv_spreads else None
            ),
            positive_vrp_pct=(
                sum(1 for s in iv_rv_spreads if s > 0) / len(iv_rv_spreads)
                if iv_rv_spreads
                else 0.0
            ),
        )

    def _compute_realized_vol(
        self,
        ta: TradeAttribution,
        info: dict,
    ) -> float | None:
        """计算持仓期间的实现波动率

        使用 calc_hv(prices, window) 从 engine 模块。
        """
        if self._data_provider is None:
            return None

        entry_date = ta.entry_date
        exit_date = ta.exit_date or ta.entry_date
        underlying = ta.underlying

        if not underlying or entry_date >= exit_date:
            return None

        try:
            from src.data.models.kline import KlineType

            bars = self._data_provider.get_history_kline(
                symbol=underlying,
                ktype=KlineType.DAILY,
                start_date=entry_date,
                end_date=exit_date,
            )
            if not bars or len(bars) < 3:
                return None

            prices = [bar.close for bar in bars if bar.close is not None and bar.close > 0]
            if len(prices) < 3:
                return None

            from src.engine.position.volatility.historical import calc_hv

            window = min(len(prices) - 1, 20)
            return calc_hv(prices, window=window)

        except Exception as e:
            logger.debug(f"Failed to compute realized vol for {underlying}: {e}")
            return None

    def analyze_exit_quality(self) -> ExitQualityReport:
        """出场质量分析 (What-If 反事实分析)

        对每笔被风控强制平仓的交易，模拟持有到期的 PnL：
        - 获取到期日的标的价格
        - 计算到期时的内在价值
        - 比较实际 PnL 与持有到期 PnL

        Returns:
            ExitQualityReport
        """
        trades: list[TradeExitQuality] = []

        for ta in self._trade_attrs:
            exit_reason = ta.exit_reason
            if not exit_reason:
                continue

            # 只分析非自然到期的交易
            reason_lower = exit_reason.lower()
            if "expired" in reason_lower:
                continue

            info = self._trade_info.get(ta.trade_id, {})
            actual_pnl = ta.total_pnl

            pnl_if_held = self._compute_pnl_if_held_to_expiry(ta, info)

            exit_benefit = None
            was_good_exit = None
            if pnl_if_held is not None:
                exit_benefit = actual_pnl - pnl_if_held
                was_good_exit = exit_benefit > 0

            trades.append(TradeExitQuality(
                trade_id=ta.trade_id,
                underlying=ta.underlying,
                exit_reason=exit_reason,
                actual_pnl=actual_pnl,
                pnl_if_held_to_expiry=pnl_if_held,
                exit_benefit=exit_benefit,
                was_good_exit=was_good_exit,
            ))

        # 汇总
        evaluated = [t for t in trades if t.exit_benefit is not None]
        good_exits = [t for t in evaluated if t.was_good_exit]
        bad_exits = [t for t in evaluated if not t.was_good_exit]

        good_count = len(good_exits)
        total_evaluated = len(evaluated)

        return ExitQualityReport(
            trades=trades,
            good_exit_rate=good_count / total_evaluated if total_evaluated > 0 else 0.0,
            avg_exit_benefit=(
                sum(t.exit_benefit for t in evaluated) / total_evaluated
                if total_evaluated > 0
                else 0.0
            ),
            total_saved_by_exit=sum(
                t.exit_benefit for t in good_exits if t.exit_benefit
            ),
            total_lost_by_exit=abs(sum(
                t.exit_benefit for t in bad_exits if t.exit_benefit
            )),
            net_exit_value=sum(
                t.exit_benefit for t in evaluated if t.exit_benefit is not None
            ),
        )

    def _compute_pnl_if_held_to_expiry(
        self,
        ta: TradeAttribution,
        info: dict,
    ) -> float | None:
        """计算持有到期的 PnL

        到期时 PnL = (intrinsic_value - entry_price) * qty * lot_size - commission
        """
        if self._data_provider is None:
            return None

        expiration = info.get("expiration")
        if not expiration:
            return None

        underlying = ta.underlying
        entry_price = info.get("entry_price", 0.0)
        quantity = info.get("quantity", ta.quantity)
        strike = ta.strike
        option_type = ta.option_type.lower() if ta.option_type else ""

        # 获取到期日的标的价格
        try:
            self._data_provider.set_as_of_date(expiration)
            quote = self._data_provider.get_stock_quote(underlying)
            if not quote or not quote.close or quote.close <= 0:
                return None

            final_price = quote.close

            # 计算到期内在价值
            if "put" in option_type:
                intrinsic = max(0.0, strike - final_price)
            elif "call" in option_type:
                intrinsic = max(0.0, final_price - strike)
            else:
                return None

            # 获取 entry snap 的 lot_size
            entry_snap = self._get_entry_snap(ta.trade_id)
            lot_size = entry_snap.lot_size if entry_snap else 100

            # PnL if held = (intrinsic - entry_price) * quantity * lot_size
            pnl_if_held = (intrinsic - entry_price) * quantity * lot_size

            return pnl_if_held

        except Exception as e:
            logger.debug(f"Failed to compute pnl_if_held for {ta.trade_id}: {e}")
            return None

    def analyze_reversal_rate(self) -> ReversalReport:
        """止损后反转率分析

        对每笔止损交易，检查持有到期是否反而盈利。

        Returns:
            ReversalReport
        """
        stop_loss_trades: list[TradeAttribution] = []
        for ta in self._trade_attrs:
            if not ta.exit_reason:
                continue
            reason = ta.exit_reason.lower()
            if any(sl in reason for sl in ("stop", "loss", "delta")):
                stop_loss_trades.append(ta)

        if not stop_loss_trades:
            return ReversalReport()

        reversal_count = 0
        reversal_magnitudes: list[float] = []
        by_reason: dict[str, list[float]] = defaultdict(list)

        for ta in stop_loss_trades:
            info = self._trade_info.get(ta.trade_id, {})
            pnl_if_held = self._compute_pnl_if_held_to_expiry(ta, info)

            if pnl_if_held is None:
                continue

            exit_reason = (ta.exit_reason or "STOP_LOSS").upper()
            is_reversal = pnl_if_held > 0  # 持有到期反而盈利

            if is_reversal:
                reversal_count += 1
                reversal_magnitudes.append(pnl_if_held - ta.total_pnl)

            by_reason[exit_reason].append(
                1.0 if is_reversal else 0.0
            )

        total_evaluated = len(stop_loss_trades)

        by_reason_stats: dict[str, dict[str, float]] = {}
        for reason, flags in by_reason.items():
            by_reason_stats[reason] = {
                "trade_count": len(flags),
                "reversal_rate": sum(flags) / len(flags) if flags else 0.0,
            }

        return ReversalReport(
            total_stop_loss_trades=total_evaluated,
            reversal_count=reversal_count,
            reversal_rate=(
                reversal_count / total_evaluated if total_evaluated > 0 else 0.0
            ),
            avg_reversal_magnitude=(
                sum(reversal_magnitudes) / len(reversal_magnitudes)
                if reversal_magnitudes
                else 0.0
            ),
            by_exit_reason=by_reason_stats,
        )

    def _get_entry_snap(self, position_id: str) -> PositionSnapshot | None:
        """获取持仓的首日快照"""
        snaps = self._snap_by_pos.get(position_id, [])
        return snaps[0] if snaps else None
