"""
PnL Attribution Engine - Greeks 归因分解

基于 Taylor 展开将期权组合 PnL 分解为 Delta、Gamma、Theta、Vega 贡献：

    Daily PnL ≈ Delta × ΔS + ½ × Gamma × (ΔS)² + Theta × Δt + Vega × Δσ + Residual

支持三种粒度：
- Daily: 每日组合级别归因
- Per-Position-Daily: 每持仓每日归因
- Per-Trade: 单笔交易从开仓到平仓的累计归因

Usage:
    engine = PnLAttributionEngine(
        position_snapshots=collector.position_snapshots,
        portfolio_snapshots=collector.portfolio_snapshots,
        trade_records=result.trade_records,
    )
    daily = engine.compute_all_daily()
    trades = engine.compute_trade_attributions()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from src.backtest.attribution.models import (
    DailyAttribution,
    PositionDailyAttribution,
    PositionSnapshot,
    TradeAttribution,
)

if TYPE_CHECKING:
    from src.backtest.attribution.models import PortfolioSnapshot
    from src.backtest.engine.trade_simulator import TradeRecord

logger = logging.getLogger(__name__)


class PnLAttributionEngine:
    """Greeks PnL 归因引擎

    使用前一日快照的 Greeks 和当日价格变动进行归因分解。

    关键约定:
    - PositionSnapshot.delta/gamma/theta/vega 为 position-level 值
      (已乘 quantity 或 abs(quantity))
    - 归因公式中需再乘 lot_size 转为美元金额
    - theta 为 daily theta，dt = 1 天
    - vega 为 per 1% IV change，dIV 以百分点为单位 (decimal * 100)
    """

    def __init__(
        self,
        position_snapshots: list[PositionSnapshot],
        portfolio_snapshots: list[PortfolioSnapshot],
        trade_records: list[TradeRecord],
    ) -> None:
        self._position_snapshots = position_snapshots
        self._portfolio_snapshots = portfolio_snapshots
        self._trade_records = trade_records

        # 建立索引
        self._snap_by_date: dict[date, list[PositionSnapshot]] = defaultdict(list)
        self._snap_by_pos: dict[str, list[PositionSnapshot]] = defaultdict(list)
        self._dates: list[date] = []

        # 平仓/到期记录索引 (position_id → TradeRecord)
        self._close_records: dict[str, TradeRecord] = {}
        for rec in self._trade_records:
            if rec.action in ("close", "expire") and rec.position_id:
                self._close_records[rec.position_id] = rec

        self._build_indexes()

    def _build_indexes(self) -> None:
        """构建按日期和持仓的索引"""
        for snap in self._position_snapshots:
            self._snap_by_date[snap.date].append(snap)
            self._snap_by_pos[snap.position_id].append(snap)

        # 按日期排序
        self._dates = sorted(self._snap_by_date.keys())
        for pos_id in self._snap_by_pos:
            self._snap_by_pos[pos_id].sort(key=lambda s: s.date)

    def compute_all_daily(self) -> list[DailyAttribution]:
        """计算所有交易日的组合级别归因

        对每个交易日，遍历当日所有持仓，使用前一日同一持仓的快照 Greeks
        计算归因分解，然后聚合为组合级别。

        Returns:
            按日期排序的 DailyAttribution 列表
        """
        daily_results: list[DailyAttribution] = []

        # 构建前一日快照索引: date -> {position_id -> PositionSnapshot}
        prev_date_snaps: dict[str, PositionSnapshot] = {}

        for current_date in self._dates:
            current_snaps = self._snap_by_date[current_date]

            pos_attrs: list[PositionDailyAttribution] = []

            for snap in current_snaps:
                prev_snap = prev_date_snaps.get(snap.position_id)
                if prev_snap is None:
                    # 开仓首日：用 entry_price 构造初始市值，计算 entry → 首日收盘 PnL
                    if snap.entry_price > 0:
                        initial_mv = snap.entry_price * snap.quantity * snap.lot_size
                        actual_pnl = snap.market_value - initial_mv
                        attr = PositionDailyAttribution(
                            position_id=snap.position_id,
                            underlying=snap.underlying,
                            actual_pnl=actual_pnl,
                            residual=actual_pnl,  # 无前日 Greeks，全入 residual
                        )
                        pos_attrs.append(attr)
                    continue

                attr = self._attribute_position_daily(prev_snap, snap)
                pos_attrs.append(attr)

            # 检测消失的持仓（到期日/平仓日 PnL）
            current_ids = {s.position_id for s in current_snaps}
            for pid, prev in prev_date_snaps.items():
                if pid not in current_ids:
                    close_rec = self._close_records.get(pid)
                    if close_rec and close_rec.trade_date == current_date:
                        closing_mv = close_rec.price * prev.quantity * prev.lot_size
                        actual_pnl = closing_mv - prev.market_value
                        attr = PositionDailyAttribution(
                            position_id=pid,
                            underlying=prev.underlying,
                            actual_pnl=actual_pnl,
                            residual=actual_pnl,
                        )
                        pos_attrs.append(attr)

            # 聚合为组合级别（跳过无归因数据的日期）
            if pos_attrs:
                daily = self._aggregate_daily(current_date, pos_attrs)
                daily_results.append(daily)

            # 更新前一日快照索引
            prev_date_snaps = {s.position_id: s for s in current_snaps}

        return daily_results

    def _attribute_position_daily(
        self,
        prev: PositionSnapshot,
        curr: PositionSnapshot,
    ) -> PositionDailyAttribution:
        """计算单持仓单日归因

        使用前日 Greeks + 当日价格变动:
            delta_pnl = prev.delta * lot_size * ΔS
            gamma_pnl = 0.5 * prev.gamma * lot_size * (ΔS)²
            theta_pnl = prev.theta * lot_size * 1  (dt=1天)
            vega_pnl  = prev.vega * lot_size * (ΔIV_decimal * 100)
        """
        lot_size = prev.lot_size

        # 价格变动
        dS = curr.underlying_price - prev.underlying_price
        dS_pct = dS / prev.underlying_price if prev.underlying_price != 0 else 0.0

        # IV 变动 (decimal)
        dIV = 0.0
        if curr.iv is not None and prev.iv is not None:
            dIV = curr.iv - prev.iv

        # 实际 PnL = 市值变动
        actual_pnl = curr.market_value - prev.market_value

        # Greeks 归因
        delta_pnl = 0.0
        if prev.delta is not None:
            delta_pnl = prev.delta * lot_size * dS

        gamma_pnl = 0.0
        if prev.gamma is not None:
            gamma_pnl = 0.5 * prev.gamma * lot_size * dS * dS

        theta_pnl = 0.0
        if prev.theta is not None:
            theta_pnl = prev.theta * lot_size  # dt = 1 day

        vega_pnl = 0.0
        if prev.vega is not None and dIV != 0.0:
            # vega 是 per 1% IV change, dIV 是 decimal
            # 需要转为百分点: dIV * 100
            vega_pnl = prev.vega * lot_size * (dIV * 100)

        residual = actual_pnl - (delta_pnl + gamma_pnl + theta_pnl + vega_pnl)

        return PositionDailyAttribution(
            position_id=curr.position_id,
            underlying=curr.underlying,
            delta_pnl=delta_pnl,
            gamma_pnl=gamma_pnl,
            theta_pnl=theta_pnl,
            vega_pnl=vega_pnl,
            residual=residual,
            actual_pnl=actual_pnl,
            underlying_move=dS,
            underlying_move_pct=dS_pct,
            iv_change=dIV,
        )

    @staticmethod
    def _aggregate_daily(
        current_date: date,
        pos_attrs: list[PositionDailyAttribution],
    ) -> DailyAttribution:
        """将持仓级别归因聚合为组合级别"""
        total_pnl = sum(a.actual_pnl for a in pos_attrs)
        delta_pnl = sum(a.delta_pnl for a in pos_attrs)
        gamma_pnl = sum(a.gamma_pnl for a in pos_attrs)
        theta_pnl = sum(a.theta_pnl for a in pos_attrs)
        vega_pnl = sum(a.vega_pnl for a in pos_attrs)
        residual = sum(a.residual for a in pos_attrs)

        abs_total = abs(total_pnl) if total_pnl != 0 else 1.0

        return DailyAttribution(
            date=current_date,
            total_pnl=total_pnl,
            delta_pnl=delta_pnl,
            gamma_pnl=gamma_pnl,
            theta_pnl=theta_pnl,
            vega_pnl=vega_pnl,
            residual=residual,
            delta_pnl_pct=delta_pnl / abs_total if total_pnl != 0 else 0.0,
            gamma_pnl_pct=gamma_pnl / abs_total if total_pnl != 0 else 0.0,
            theta_pnl_pct=theta_pnl / abs_total if total_pnl != 0 else 0.0,
            vega_pnl_pct=vega_pnl / abs_total if total_pnl != 0 else 0.0,
            positions_count=len(pos_attrs),
            position_attributions=pos_attrs,
        )

    def compute_trade_attributions(self) -> list[TradeAttribution]:
        """计算所有交易的累计归因

        对每个 position_id，收集其所有日级别归因并累加。
        交易的 entry/exit 信息从 trade_records 中获取。

        Returns:
            TradeAttribution 列表
        """
        # 首先计算所有 daily
        all_daily = self.compute_all_daily()

        # 构建 position_id -> list[PositionDailyAttribution] 索引
        pos_daily_attrs: dict[str, list[PositionDailyAttribution]] = defaultdict(list)
        for daily in all_daily:
            for pa in daily.position_attributions:
                pos_daily_attrs[pa.position_id].append(pa)

        # 从 trade_records 提取交易信息
        trade_info = self._extract_trade_info()

        results: list[TradeAttribution] = []
        for position_id, daily_attrs in pos_daily_attrs.items():
            info = trade_info.get(position_id, {})

            # 从 position_snapshots 获取 entry/exit IV 和 underlying price
            pos_snaps = self._snap_by_pos.get(position_id, [])
            entry_snap = pos_snaps[0] if pos_snaps else None
            exit_snap = pos_snaps[-1] if pos_snaps else None

            ta = TradeAttribution(
                trade_id=position_id,
                symbol=info.get("symbol", entry_snap.symbol if entry_snap else ""),
                underlying=info.get(
                    "underlying", entry_snap.underlying if entry_snap else ""
                ),
                option_type=info.get(
                    "option_type", entry_snap.option_type if entry_snap else ""
                ),
                strike=info.get("strike", entry_snap.strike if entry_snap else 0.0),
                entry_date=info.get(
                    "entry_date", entry_snap.date if entry_snap else date.min
                ),
                exit_date=info.get(
                    "exit_date", exit_snap.date if exit_snap else None
                ),
                exit_reason=info.get("exit_reason"),
                exit_reason_type=info.get("exit_reason_type"),
                holding_days=len(daily_attrs),
                total_pnl=sum(a.actual_pnl for a in daily_attrs),
                delta_pnl=sum(a.delta_pnl for a in daily_attrs),
                gamma_pnl=sum(a.gamma_pnl for a in daily_attrs),
                theta_pnl=sum(a.theta_pnl for a in daily_attrs),
                vega_pnl=sum(a.vega_pnl for a in daily_attrs),
                residual=sum(a.residual for a in daily_attrs),
                entry_iv=entry_snap.iv if entry_snap else None,
                exit_iv=exit_snap.iv if exit_snap else None,
                entry_underlying=(
                    entry_snap.underlying_price if entry_snap else 0.0
                ),
                exit_underlying=(
                    exit_snap.underlying_price if exit_snap else 0.0
                ),
                entry_iv_rank=entry_snap.iv_rank if entry_snap else None,
                quantity=entry_snap.quantity if entry_snap else 0,
            )
            results.append(ta)

        return results

    def _extract_trade_info(self) -> dict[str, dict]:
        """从 trade_records 提取每个 position_id 的交易元信息"""
        info: dict[str, dict] = {}

        for record in self._trade_records:
            pid = record.position_id
            if pid is None:
                continue

            if pid not in info:
                info[pid] = {}

            if record.action == "open":
                info[pid]["symbol"] = record.symbol
                info[pid]["underlying"] = record.underlying
                info[pid]["option_type"] = record.option_type.value if hasattr(record.option_type, "value") else str(record.option_type)
                info[pid]["strike"] = record.strike
                info[pid]["entry_date"] = record.trade_date
            elif record.action in ("close", "expire"):
                info[pid]["exit_date"] = record.trade_date
                info[pid]["exit_reason"] = record.reason
                if hasattr(record, "close_reason_type") and record.close_reason_type is not None:
                    info[pid]["exit_reason_type"] = record.close_reason_type.value

        return info

    def get_worst_days(self, n: int = 5) -> list[DailyAttribution]:
        """最差 N 天"""
        all_daily = self.compute_all_daily()
        return sorted(all_daily, key=lambda d: d.total_pnl)[:n]

    def get_best_days(self, n: int = 5) -> list[DailyAttribution]:
        """最佳 N 天"""
        all_daily = self.compute_all_daily()
        return sorted(all_daily, key=lambda d: d.total_pnl, reverse=True)[:n]

    def attribution_summary(self) -> dict:
        """整体归因摘要

        Returns:
            包含累计各因子 PnL、贡献百分比、residual 占比等的字典
        """
        all_daily = self.compute_all_daily()

        total_pnl = sum(d.total_pnl for d in all_daily)
        total_delta = sum(d.delta_pnl for d in all_daily)
        total_gamma = sum(d.gamma_pnl for d in all_daily)
        total_theta = sum(d.theta_pnl for d in all_daily)
        total_vega = sum(d.vega_pnl for d in all_daily)
        total_residual = sum(d.residual for d in all_daily)

        abs_total = abs(total_pnl) if total_pnl != 0 else 1.0

        return {
            "total_pnl": total_pnl,
            "delta_pnl": total_delta,
            "gamma_pnl": total_gamma,
            "theta_pnl": total_theta,
            "vega_pnl": total_vega,
            "residual": total_residual,
            "delta_pnl_pct": total_delta / abs_total if total_pnl != 0 else 0.0,
            "gamma_pnl_pct": total_gamma / abs_total if total_pnl != 0 else 0.0,
            "theta_pnl_pct": total_theta / abs_total if total_pnl != 0 else 0.0,
            "vega_pnl_pct": total_vega / abs_total if total_pnl != 0 else 0.0,
            "residual_pct": total_residual / abs_total if total_pnl != 0 else 0.0,
            "trading_days": len(all_daily),
            "attribution_coverage": 1.0 - abs(total_residual) / abs_total if total_pnl != 0 else 0.0,
        }
