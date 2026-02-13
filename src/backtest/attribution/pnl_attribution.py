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
from src.backtest.data.greeks_calculator import GreeksCalculator

if TYPE_CHECKING:
    from src.backtest.attribution.models import PortfolioSnapshot
    from src.backtest.engine.trade_simulator import TradeRecord

logger = logging.getLogger(__name__)


class PnLAttributionEngine:
    """Greeks PnL 归因引擎

    使用前一日快照的 Greeks 和当日价格变动进行归因分解。

    关键约定:
    - PositionSnapshot 继承 PositionData 的 Greeks 符号约定:
      - delta, theta: 乘以 qty（带方向符号）
      - gamma, vega: 乘以 abs(qty)（永远为正，不含方向）
    - 归因计算时 gamma/vega 需额外乘 sign(qty) 恢复持仓方向
    - 归因公式中需再乘 lot_size 转为美元金额
    - theta 为 daily theta，dt = 实际日历天数（自动处理周末/假期）
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

        # 开仓记录索引 (position_id → TradeRecord)
        self._open_records: dict[str, TradeRecord] = {}
        for rec in self._trade_records:
            if rec.action == "open" and rec.position_id:
                self._open_records[rec.position_id] = rec

        self._greeks_calc = GreeksCalculator()

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

    def _synthesize_entry_snapshot(
        self,
        first_snap: PositionSnapshot,
    ) -> PositionSnapshot | None:
        """为开仓首日合成入场快照

        用 open TradeRecord 的 fill_price + underlying_price 调用 GreeksCalculator
        计算入场时 Greeks，构造合成 PositionSnapshot 作为 prev_snap。

        Args:
            first_snap: 该持仓首次出现的快照（次日采集）

        Returns:
            合成的入场快照，或 None（无法合成时）
        """
        open_rec = self._open_records.get(first_snap.position_id)
        if open_rec is None:
            return None

        # 需要入场时标的价格
        if open_rec.underlying_price is None or open_rec.underlying_price <= 0:
            return None

        entry_price = open_rec.price  # fill_price
        if entry_price <= 0:
            return None

        spot = open_rec.underlying_price
        strike = open_rec.strike
        expiration = open_rec.expiration
        trade_date = open_rec.trade_date

        dte = (expiration - trade_date).days
        if dte <= 0:
            return None

        tte = dte / 365.0
        is_call = open_rec.option_type.value.lower() == "call"

        result = self._greeks_calc.calculate(
            option_price=entry_price,
            spot=spot,
            strike=strike,
            tte=tte,
            rate=0.045,
            is_call=is_call,
        )

        if not result.is_valid:
            logger.debug(
                f"Entry snapshot synthesis failed for {first_snap.position_id}: "
                f"{result.error_msg}"
            )
            return None

        # 转换 per-share Greeks → position-level
        qty = first_snap.quantity
        abs_qty = abs(qty)

        # 入场市值 = entry_price * qty * lot_size
        entry_mv = entry_price * qty * first_snap.lot_size

        return PositionSnapshot(
            date=trade_date,
            position_id=first_snap.position_id,
            underlying=first_snap.underlying,
            symbol=first_snap.symbol,
            option_type=first_snap.option_type,
            strike=strike,
            expiration=expiration,
            quantity=qty,
            lot_size=first_snap.lot_size,
            underlying_price=spot,
            option_mid_price=entry_price,
            iv=result.iv,
            delta=result.delta * qty,
            gamma=result.gamma * abs_qty,
            theta=result.theta * qty,
            vega=result.vega * abs_qty,
            market_value=entry_mv,
            entry_price=first_snap.entry_price,
            entry_date=trade_date,
            dte=dte,
        )

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
                    # 开仓首日：尝试合成入场快照进行 Greeks 归因
                    if snap.entry_price > 0:
                        synthetic = self._synthesize_entry_snapshot(snap)
                        if synthetic is not None:
                            # 用合成入场快照 → 首日快照进行归因
                            attr = self._attribute_position_daily(synthetic, snap)
                            pos_attrs.append(attr)
                        else:
                            # 回退到现有逻辑：全部归入 residual
                            initial_mv = snap.entry_price * snap.quantity * snap.lot_size
                            actual_pnl = snap.market_value - initial_mv
                            attr = PositionDailyAttribution(
                                position_id=snap.position_id,
                                underlying=snap.underlying,
                                actual_pnl=actual_pnl,
                                residual=actual_pnl,
                            )
                            pos_attrs.append(attr)
                    continue

                attr = self._attribute_position_daily(prev_snap, snap)
                pos_attrs.append(attr)

            # 检测消失的持仓（到期日/平仓日 PnL）
            # 到期：step 2 移除持仓 → step 3.5 快照已无此持仓
            # 平仓：step 3.5 快照有此持仓 → step 5 移除 → 次日消失
            current_ids = {s.position_id for s in current_snaps}
            for pid, prev in prev_date_snaps.items():
                if pid not in current_ids:
                    close_rec = self._close_records.get(pid)
                    if close_rec and close_rec.trade_date >= prev.date:
                        closing_mv = close_rec.price * prev.quantity * prev.lot_size
                        actual_pnl = closing_mv - prev.market_value

                        # 使用前日 Greeks 归因（而非全部放入 residual）
                        attr = self._attribute_disappeared_position(
                            prev, actual_pnl, close_rec, current_date, current_snaps,
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
            gamma_pnl = 0.5 * prev.gamma * qty_sign * lot_size * (ΔS)²
            theta_pnl = prev.theta * lot_size * dt  (dt=实际日历天数)
            vega_pnl  = prev.vega * qty_sign * lot_size * (ΔIV_decimal * 100)

        注意 PositionData 的 Greeks 符号约定:
        - delta, theta: 乘以 qty（已带方向符号）
        - gamma, vega: 乘以 abs(qty)（永远为正，丢失了方向信息）
        因此 gamma 和 vega 需要额外乘 qty_sign 恢复方向:
        short position (qty<0) → gamma_pnl 为负（凸性成本）
        short position (qty<0) → vega_pnl 在 IV 上升时为负
        """
        lot_size = prev.lot_size

        # 持仓方向符号：gamma/vega 使用 abs(qty) 约定，需要恢复方向
        qty_sign = 1 if prev.quantity >= 0 else -1

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
        # delta/theta: PositionData 已乘 qty，自带方向符号，直接使用
        delta_pnl = 0.0
        if prev.delta is not None:
            delta_pnl = prev.delta * lot_size * dS

        # gamma: PositionData 乘 abs(qty)，永远为正，需乘 qty_sign 恢复方向
        # short gamma → gamma_pnl 永远为负（凸性成本）
        gamma_pnl = 0.0
        if prev.gamma is not None:
            gamma_pnl = 0.5 * prev.gamma * qty_sign * lot_size * dS * dS

        # theta: 使用实际日历天数（Fri→Mon = 3天，含周末/假期的 theta 衰减）
        dt = (curr.date - prev.date).days
        theta_pnl = 0.0
        if prev.theta is not None:
            theta_pnl = prev.theta * lot_size * dt

        # vega: PositionData 乘 abs(qty)，永远为正，需乘 qty_sign 恢复方向
        # short vega → IV 上升时 vega_pnl 为负
        vega_pnl = 0.0
        if prev.vega is not None and dIV != 0.0:
            # vega 是 per 1% IV change, dIV 是 decimal
            # 需要转为百分点: dIV * 100
            vega_pnl = prev.vega * qty_sign * lot_size * (dIV * 100)

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

    def _attribute_disappeared_position(
        self,
        prev: PositionSnapshot,
        actual_pnl: float,
        close_rec: TradeRecord,
        current_date: date,
        current_snaps: list[PositionSnapshot],
    ) -> PositionDailyAttribution:
        """归因消失持仓（到期/平仓）的最后一日 PnL

        使用前日 Greeks 进行归因分解，而非全部归入 residual。
        标的价格优先从 TradeRecord（到期记录含 underlying_price），
        其次从同日其他持仓的快照获取，最后回退到 prev 价格（dS=0）。
        """
        lot_size = prev.lot_size
        qty_sign = 1 if prev.quantity >= 0 else -1
        dt = (current_date - prev.date).days or 1

        # 获取标的价格：TradeRecord > 同日其他持仓 > 前日价格
        current_underlying_price = prev.underlying_price
        if close_rec.underlying_price is not None:
            current_underlying_price = close_rec.underlying_price
        else:
            for snap in current_snaps:
                if snap.underlying == prev.underlying and snap.underlying_price > 0:
                    current_underlying_price = snap.underlying_price
                    break

        dS = current_underlying_price - prev.underlying_price
        dS_pct = dS / prev.underlying_price if prev.underlying_price != 0 else 0.0

        # Greeks 归因
        delta_pnl = prev.delta * lot_size * dS if prev.delta else 0.0
        gamma_pnl = (
            0.5 * prev.gamma * qty_sign * lot_size * dS * dS
            if prev.gamma else 0.0
        )
        theta_pnl = prev.theta * lot_size * dt if prev.theta else 0.0
        vega_pnl = 0.0  # 无当日 IV 数据，无法计算 vega 归因

        residual = actual_pnl - (delta_pnl + gamma_pnl + theta_pnl + vega_pnl)

        return PositionDailyAttribution(
            position_id=prev.position_id,
            underlying=prev.underlying,
            delta_pnl=delta_pnl,
            gamma_pnl=gamma_pnl,
            theta_pnl=theta_pnl,
            vega_pnl=vega_pnl,
            residual=residual,
            actual_pnl=actual_pnl,
            underlying_move=dS,
            underlying_move_pct=dS_pct,
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
                entry_price=entry_snap.entry_price if entry_snap else 0.0,
                lot_size=entry_snap.lot_size if entry_snap else 100,
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
