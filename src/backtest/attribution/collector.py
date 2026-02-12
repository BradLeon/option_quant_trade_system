"""
Attribution Collector - 归因数据采集器

挂入 BacktestExecutor 每日循环，采集持仓快照和组合快照。
复用 monitoring 阶段已计算的 PositionData（避免重复获取 Greeks）。

Usage:
    collector = AttributionCollector()
    executor = BacktestExecutor(config, attribution_collector=collector)
    result = executor.run()

    # 采集结果
    pos_snapshots = collector.position_snapshots
    port_snapshots = collector.portfolio_snapshots
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from src.backtest.attribution.models import PortfolioSnapshot, PositionSnapshot
from src.backtest.data.greeks_calculator import GreeksCalculator
from src.data.models.option import Greeks
from src.engine.models.position import Position
from src.engine.portfolio.metrics import calc_portfolio_metrics

if TYPE_CHECKING:
    from src.business.monitoring.models import PositionData
    from src.data.providers.base import DataProvider

logger = logging.getLogger(__name__)


class AttributionCollector:
    """归因数据采集器

    在 BacktestExecutor 每日循环中被调用，将 PositionData 转为
    PositionSnapshot 和 PortfolioSnapshot 并存储在内存中。
    """

    def __init__(self) -> None:
        self.position_snapshots: list[PositionSnapshot] = []
        self.portfolio_snapshots: list[PortfolioSnapshot] = []
        self._prev_nlv: float | None = None
        self._greeks_calc = GreeksCalculator()

    def capture_daily(
        self,
        current_date: date,
        position_data_list: list[PositionData],
        nlv: float,
        cash: float,
        margin_used: float,
        data_provider: DataProvider | None = None,
        as_of_date: date | None = None,
    ) -> None:
        """采集当日快照

        Args:
            current_date: 当前交易日
            position_data_list: 当日持仓数据（来自 monitoring 或 position_manager）
            nlv: 净清算价值
            cash: 现金
            margin_used: 已用保证金
            data_provider: 数据提供者（用于补充 HV/IV Rank 等）
            as_of_date: 日期（用于数据查询）
        """
        # 1. 采集持仓快照
        daily_position_snapshots: list[PositionSnapshot] = []
        for pd in position_data_list:
            snap = self._position_data_to_snapshot(pd, current_date, data_provider)
            if snap is not None:
                daily_position_snapshots.append(snap)
                self.position_snapshots.append(snap)

        # 2. 采集组合快照
        daily_pnl = nlv - self._prev_nlv if self._prev_nlv is not None else 0.0
        portfolio_snap = self._build_portfolio_snapshot(
            current_date=current_date,
            position_data_list=position_data_list,
            nlv=nlv,
            cash=cash,
            margin_used=margin_used,
            daily_pnl=daily_pnl,
            data_provider=data_provider,
            as_of_date=as_of_date,
        )
        self.portfolio_snapshots.append(portfolio_snap)

        self._prev_nlv = nlv

        logger.debug(
            f"Attribution captured: {current_date}, "
            f"positions={len(daily_position_snapshots)}, "
            f"NLV=${nlv:,.0f}"
        )

    def _recover_iv_and_greeks(
        self,
        pd: PositionData,
        current_date: date,
        expiration_date: date,
    ) -> tuple[float | None, float | None, float | None, float | None, float | None]:
        """用 BS 模型从期权 mid price 反算 IV 和 Greeks

        当 PositionData.iv 为 None 时调用。利用已有的 GreeksCalculator
        从期权价格反算 IV，并计算 delta/gamma/theta/vega。

        Args:
            pd: 持仓数据
            current_date: 当前日期
            expiration_date: 到期日期

        Returns:
            (iv, delta, gamma, theta, vega) — position-level Greeks
            任何字段可能为 None（计算失败时）
        """
        option_price = pd.current_price
        spot = pd.underlying_price
        strike = pd.strike

        if not option_price or option_price <= 0 or not spot or spot <= 0 or not strike or strike <= 0:
            return None, None, None, None, None

        dte = (expiration_date - current_date).days
        if dte <= 0:
            return None, None, None, None, None

        tte = dte / 365.0
        is_call = (pd.option_type or "").lower() == "call"

        result = self._greeks_calc.calculate(
            option_price=option_price,
            spot=spot,
            strike=strike,
            tte=tte,
            rate=0.045,
            is_call=is_call,
        )

        if not result.is_valid:
            logger.debug(
                f"IV recovery failed for {pd.symbol}: {result.error_msg}"
            )
            return None, None, None, None, None

        # 转换 per-share Greeks → position-level Greeks
        # 与 PositionData 约定一致:
        #   delta, theta: 乘 qty
        #   gamma, vega: 乘 abs(qty)
        qty = int(pd.quantity)
        abs_qty = abs(qty)

        iv = result.iv
        delta = result.delta * qty
        gamma = result.gamma * abs_qty
        theta = result.theta * qty
        vega = result.vega * abs_qty

        logger.debug(
            f"IV recovered for {pd.symbol}: IV={iv:.2%}, "
            f"delta={delta:.4f}, gamma={gamma:.6f}, "
            f"theta={theta:.4f}, vega={vega:.4f}"
        )

        return iv, delta, gamma, theta, vega

    def _position_data_to_snapshot(
        self,
        pd: PositionData,
        current_date: date,
        data_provider: DataProvider | None = None,
    ) -> PositionSnapshot | None:
        """将 PositionData 转为 PositionSnapshot

        PositionData 的 Greeks 为 position-level（已乘 quantity），
        直接保留该约定，与 PositionData 一致。

        当 pd.iv 为 None 时，用 BS 模型从期权 mid price 反算 IV 和 Greeks。
        """
        if not pd.is_option:
            return None

        # 补充 HV/IV 相关指标（PositionData 中可能已有，缺失时从 data_provider 查询）
        hv = pd.hv
        iv_rank = pd.iv_rank
        iv_percentile = pd.iv_percentile
        iv_hv_ratio = pd.iv_hv_ratio

        if data_provider is not None and (hv is None or iv_rank is None):
            try:
                vol = data_provider.get_stock_volatility(pd.underlying or pd.symbol)
                if vol is not None:
                    if hv is None:
                        hv = vol.hv
                    if iv_rank is None and vol.iv_rank is not None:
                        iv_rank = vol.iv_rank
                    if iv_percentile is None and vol.iv_percentile is not None:
                        iv_percentile = vol.iv_percentile
                    if pd.iv is not None and hv is not None and hv > 0 and iv_hv_ratio is None:
                        from src.engine.position.volatility.implied import (
                            calc_iv_hv_ratio,
                        )
                        iv_hv_ratio = calc_iv_hv_ratio(pd.iv, hv)
            except Exception as e:
                logger.debug(f"Failed to get volatility for {pd.underlying}: {e}")

        # 解析 expiration
        expiration_date = current_date
        if pd.expiry:
            try:
                from datetime import datetime
                expiration_date = datetime.strptime(pd.expiry, "%Y%m%d").date()
            except (ValueError, TypeError):
                pass

        # 使用原始值
        iv = pd.iv
        delta = pd.delta
        gamma = pd.gamma
        theta = pd.theta
        vega = pd.vega

        # IV 恢复: 当 IV 缺失时，用 BS 模型从期权价格反算
        if iv is None:
            rec_iv, rec_delta, rec_gamma, rec_theta, rec_vega = (
                self._recover_iv_and_greeks(pd, current_date, expiration_date)
            )
            if rec_iv is not None:
                iv = rec_iv
                # 同时填充缺失的 Greeks
                if delta is None:
                    delta = rec_delta
                if gamma is None:
                    gamma = rec_gamma
                if theta is None:
                    theta = rec_theta
                if vega is None:
                    vega = rec_vega

        return PositionSnapshot(
            date=current_date,
            position_id=pd.position_id,
            underlying=pd.underlying or pd.symbol,
            symbol=pd.symbol,
            option_type=pd.option_type or "unknown",
            strike=pd.strike or 0.0,
            expiration=expiration_date,
            quantity=int(pd.quantity),
            lot_size=pd.contract_multiplier,
            underlying_price=pd.underlying_price or 0.0,
            option_mid_price=pd.current_price,
            iv=iv,
            hv=hv,
            iv_hv_ratio=iv_hv_ratio,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            market_value=pd.market_value,
            unrealized_pnl=pd.unrealized_pnl,
            moneyness_pct=pd.otm_pct or 0.0,
            dte=pd.dte or 0,
            entry_price=pd.entry_price,
            entry_date=None,  # 不在 PositionData 中，由后续从 SimulatedPosition 补充
        )

    def _build_portfolio_snapshot(
        self,
        current_date: date,
        position_data_list: list[PositionData],
        nlv: float,
        cash: float,
        margin_used: float,
        daily_pnl: float,
        data_provider: DataProvider | None = None,
        as_of_date: date | None = None,
    ) -> PortfolioSnapshot:
        """构建组合快照

        将 PositionData 转为 Position 对象，调用 calc_portfolio_metrics() 计算
        所有组合级别指标。
        """
        position_count = len(position_data_list)

        if not position_data_list:
            return PortfolioSnapshot(
                date=current_date,
                nlv=nlv,
                cash=cash,
                margin_used=margin_used,
                position_count=0,
                daily_pnl=daily_pnl,
            )

        # 转换 PositionData → Position (per-share Greeks)
        positions, iv_hv_ratios = self._convert_to_positions(position_data_list)

        # 调用已有的 calc_portfolio_metrics
        metrics = calc_portfolio_metrics(
            positions=positions,
            nlv=nlv,
            position_iv_hv_ratios=iv_hv_ratios if iv_hv_ratios else None,
            data_provider=data_provider,
            as_of_date=as_of_date,
        )

        return PortfolioSnapshot(
            date=current_date,
            nlv=nlv,
            cash=cash,
            margin_used=margin_used,
            position_count=position_count,
            daily_pnl=daily_pnl,
            portfolio_delta=metrics.total_delta or 0.0,
            beta_weighted_delta=metrics.beta_weighted_delta,
            portfolio_gamma=metrics.total_gamma or 0.0,
            portfolio_theta=metrics.total_theta or 0.0,
            portfolio_vega=metrics.total_vega or 0.0,
            beta_weighted_delta_pct=metrics.beta_weighted_delta_pct,
            gamma_pct=metrics.gamma_pct,
            theta_pct=metrics.theta_pct,
            vega_pct=metrics.vega_pct,
            vega_weighted_iv_hv=metrics.vega_weighted_iv_hv,
            portfolio_tgr=metrics.portfolio_tgr,
            concentration_hhi=metrics.concentration_hhi,
        )

    @staticmethod
    def _convert_to_positions(
        position_data_list: list[PositionData],
    ) -> tuple[list[Position], dict[str, float]]:
        """将 PositionData 列表转为 Position 列表

        PositionData 的 Greeks 为 position-level（已乘 qty），
        需要还原为 per-share Greeks 供 greeks_agg.py 使用。

        greeks_agg.py 中：portfolio_delta = Σ(pos.delta × pos.quantity × pos.contract_multiplier)
        PositionData 中：pd.delta = raw_delta × qty

        因此：raw_delta = pd.delta / qty
        Position 传入 quantity=qty, delta=raw_delta
        greeks_agg: raw_delta × qty × multiplier = pd.delta × multiplier ✓

        Returns:
            (positions, iv_hv_ratios) 元组
        """
        positions: list[Position] = []
        iv_hv_ratios: dict[str, float] = {}

        for pd in position_data_list:
            if not pd.is_option:
                continue

            qty = pd.quantity
            if qty == 0:
                continue

            abs_qty = abs(qty)

            # 还原 per-share Greeks
            raw_delta = pd.delta / qty if pd.delta is not None else None
            raw_gamma = pd.gamma / abs_qty if pd.gamma is not None else None
            raw_theta = pd.theta / qty if pd.theta is not None else None
            raw_vega = pd.vega / abs_qty if pd.vega is not None else None

            pos = Position(
                symbol=pd.underlying or pd.symbol,
                quantity=qty,
                greeks=Greeks(
                    delta=raw_delta,
                    gamma=raw_gamma,
                    theta=raw_theta,
                    vega=raw_vega,
                ),
                beta=pd.beta,
                market_value=pd.market_value,
                underlying_price=pd.underlying_price,
                contract_multiplier=pd.contract_multiplier,
                margin=pd.margin,
                dte=pd.dte,
                iv=pd.iv,
            )
            positions.append(pos)

            if pd.iv_hv_ratio is not None:
                iv_hv_ratios[pd.underlying or pd.symbol] = pd.iv_hv_ratio

        return positions, iv_hv_ratios

    def reset(self) -> None:
        """重置采集数据"""
        self.position_snapshots.clear()
        self.portfolio_snapshots.clear()
        self._prev_nlv = None
