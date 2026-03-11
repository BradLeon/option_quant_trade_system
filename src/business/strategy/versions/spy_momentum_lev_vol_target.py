"""SPY Momentum + Leverage + Vol Target Strategy

7 分动量评分 + Vol Target 风控 + Stock/LEAPS Call 复合仓位：
- 5 分 SMA 基础分: close>SMA20, close>SMA50, close>SMA200, SMA20>SMA50, SMA50>SMA200
- 2 分动量分: close>close[-20], close>close[-60]
- 仓位映射: {0:0, 1:0, 2:0.5, 3:1.0, 4:1.5, 5:2.0, 6:2.5, 7:3.0}
- 风控: vol_scalar = min(2.0, 15/VIX), target = base * vol_scalar, capped at [0, 3.0]
- 仓位分解: stock_pct = min(1.0, target), leaps_pct = max(0, target - 1.0)
- 减仓优先级: 先平 LEAPS，不够再减正股

移植自诊断脚本: output/diagnostics/ma_signal_search.py #15 "Moment+Lev (VolTgt)"
杠杆部分 (target_pct > 1.0) 用深度 ITM LEAPS CALL 替代保证金杠杆。
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

import yaml

from src.business.monitoring.models import PositionData
from src.business.screening.models import ContractOpportunity
from src.business.strategy.base import BaseTradeStrategy
from src.business.strategy.models import MarketContext, TradeSignal

logger = logging.getLogger(__name__)

# 合约选择权重（复用 LEAPS 策略 pattern）
_W_DTE = 1.0
_W_STRIKE = 2.0

# 默认仓位映射
_DEFAULT_POSITION_MAP = {
    0: 0.0,
    1: 0.0,
    2: 0.5,
    3: 1.0,
    4: 1.5,
    5: 2.0,
    6: 2.5,
    7: 3.0,
}


@dataclass
class MomentumLevVolTargetConfig:
    """Momentum + Leverage + Vol Target 策略配置"""

    # SMA 信号参数
    sma_periods: tuple = (20, 50, 200)
    momentum_lookback_short: int = 20
    momentum_lookback_long: int = 60
    position_map: dict = field(default_factory=lambda: dict(_DEFAULT_POSITION_MAP))

    # Volatility targeting (唯一风控层)
    vol_target: float = 15.0
    vol_scalar_max: float = 2.0
    max_exposure: float = 3.0

    # 决策频率 & 再平衡
    decision_frequency: int = 1
    rebalance_threshold: float = 0.25  # |Δpct| > 25% 才触发再平衡
    min_rebalance_interval: int = 5  # 两次再平衡间至少 5 个交易日冷却

    # LEAPS 合约参数
    target_moneyness: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    roll_dte_threshold: int = 60
    max_capital_pct: float = 0.95

    @classmethod
    def from_yaml(cls, path: Path) -> "MomentumLevVolTargetConfig":
        with open(path) as f:
            raw = yaml.safe_load(f)
        section = raw.get("momentum_lev_vol_target_config", {})
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in section.items() if k in known_fields}
        # 转换 position_map keys 为 int
        if "position_map" in filtered and isinstance(filtered["position_map"], dict):
            filtered["position_map"] = {int(k): float(v) for k, v in filtered["position_map"].items()}
        return cls(**filtered)

    @classmethod
    def default_yaml_path(cls) -> Path:
        return Path(__file__).resolve().parents[4] / "config" / "screening" / "spy_momentum_lev_vol_target.yaml"


class SpyMomentumLevVolTarget(BaseTradeStrategy):
    """Momentum + Leverage + Vol Target 复合仓位策略

    7 分动量评分 + vol_scalar=min(2.0, 15/VIX) 波动率目标。
    target ≤ 1.0 部分用 stock proxy，> 1.0 部分用深度 ITM LEAPS Call。

    完全 override 三个生命周期方法:
    - evaluate_positions: 信号计算 + 仓位调整（减仓/清仓/roll）
    - find_opportunities: 开仓/再平衡时选取 stock proxy 和 LEAPS Call
    - generate_entry_signals: 按目标百分比计算 stock shares 和 LEAPS 合约数量
    """

    def __init__(self):
        super().__init__()
        self._config: Optional[MomentumLevVolTargetConfig] = None

        # 信号缓存
        self._signal_computed_for_date: Optional[date] = None
        self._current_target_pct: float = 0.0
        self._last_signal_detail: dict = {}  # 信号元数据（供可视化/调试）

        # 跨方法协调标志
        self._pending_rebalance: bool = False
        self._pending_exit_to_cash: bool = False
        self._pending_stock_topup_pct: float = 0.0  # 增量加仓百分比
        self._pending_leaps_topup_contracts: int = 0  # 增量加仓合约数

        # 交易日计数 & 冷却期
        self._trading_day_count: int = 0
        self._last_eval_date: Optional[date] = None
        self._last_nlv: float = 0.0
        self._last_rebalance_day: int = -9999  # 上次再平衡的交易日序号

    @property
    def name(self) -> str:
        return "spy_momentum_lev_vol_target"

    @property
    def position_side(self) -> str:
        return "LONG"

    # ==========================================
    # 配置加载
    # ==========================================
    def _ensure_config_loaded(self) -> MomentumLevVolTargetConfig:
        if self._config is None:
            path = MomentumLevVolTargetConfig.default_yaml_path()
            if path.exists():
                self._config = MomentumLevVolTargetConfig.from_yaml(path)
            else:
                self._config = MomentumLevVolTargetConfig()
        return self._config

    # ==========================================
    # 信号计算
    # ==========================================
    def _compute_signal(self, context: MarketContext, data_provider: Any) -> float:
        """计算风控后的目标仓位百分比，按日期缓存。

        Returns:
            target_pct: 风控后的目标暴露 (0.0 ~ 3.0)
        """
        if self._signal_computed_for_date == context.current_date:
            return self._current_target_pct

        cfg = self._ensure_config_loaded()

        symbols = list(context.underlying_prices.keys())
        if not symbols:
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        symbol = symbols[0]

        from src.data.models.stock import KlineType
        from src.engine.position.technical.moving_average import calc_sma_series

        # 获取价格数据（需要足够长以覆盖 SMA200 + momentum 回溯）
        max_sma = max(cfg.sma_periods)
        lookback_days = max(max_sma, cfg.momentum_lookback_long) * 2 + 50
        lookback_start = context.current_date - timedelta(days=lookback_days)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=context.current_date,
        )

        if not klines or len(klines) < max_sma:
            logger.info(f"MomentumLev: insufficient price data ({len(klines) if klines else 0} < {max_sma})")
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        prices = [k.close for k in klines]

        # 计算 SMA 系列
        sma_values = {}
        for period in cfg.sma_periods:
            series = calc_sma_series(prices, period)
            sma_values[period] = series[-1] if series and series[-1] is not None else None

        sma20 = sma_values.get(20)
        sma50 = sma_values.get(50)
        sma200 = sma_values.get(200)

        if sma20 is None or sma50 is None or sma200 is None:
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        close = prices[-1]

        # === 7 分动量评分 ===
        score = 0
        # 5 分 SMA 基础
        if close > sma20:
            score += 1
        if close > sma50:
            score += 1
        if close > sma200:
            score += 1
        if sma20 > sma50:
            score += 1
        if sma50 > sma200:
            score += 1
        # 2 分动量
        if len(prices) > cfg.momentum_lookback_short and close > prices[-1 - cfg.momentum_lookback_short]:
            score += 1
        if len(prices) > cfg.momentum_lookback_long and close > prices[-1 - cfg.momentum_lookback_long]:
            score += 1

        # 仓位映射
        target_pct = cfg.position_map.get(score, 0.0)
        if target_pct == 0.0:
            self._last_signal_detail = {
                "momentum_score": score, "sma20": sma20, "sma50": sma50,
                "sma200": sma200, "close": close, "vix": 0.0,
                "vol_scalar": 0.0, "raw_target": 0.0, "target_pct": 0.0,
            }
            self._current_target_pct = 0.0
            self._signal_computed_for_date = context.current_date
            return 0.0

        # === Vol Target 风控 ===
        vix = self._get_vix(context, data_provider)
        vol_scalar = min(cfg.vol_scalar_max, cfg.vol_target / vix) if vix > 0 else 1.0
        target_pct = target_pct * vol_scalar
        target_pct = max(0.0, min(cfg.max_exposure, target_pct))

        logger.debug(
            f"VolTgt signal: {symbol} score={score} raw_map={cfg.position_map.get(score, 0)} "
            f"vix={vix:.1f} vol_scalar={vol_scalar:.2f} → target_pct={target_pct:.2f}"
        )

        self._last_signal_detail = {
            "momentum_score": score,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "close": close,
            "vix": vix,
            "vol_scalar": vol_scalar,
            "raw_target": cfg.position_map.get(score, 0.0),
            "target_pct": target_pct,
        }

        self._current_target_pct = target_pct
        self._signal_computed_for_date = context.current_date
        return target_pct

    def _get_vix(self, context: MarketContext, data_provider: Any) -> float:
        """获取当日 VIX 值，缺失时默认 20.0"""
        try:
            lookback = context.current_date - timedelta(days=10)
            vix_data = data_provider.get_macro_data("^VIX", lookback, context.current_date)
            if vix_data and len(vix_data) > 0:
                return vix_data[-1].close
        except Exception:
            pass
        return 20.0

    # ==========================================
    # 仓位识别
    # ==========================================
    @staticmethod
    def _is_stock_proxy(pos: PositionData) -> bool:
        # Fix 1 之后 stock proxy 走股票路径: asset_type="stock"
        if getattr(pos, 'asset_type', None) == "stock":
            return True
        # legacy 兼容: 旧路径产生的 strike < 1.0 期权
        if pos.strike is not None and pos.strike < 1.0:
            return True
        return False

    @staticmethod
    def _is_leaps(pos: PositionData) -> bool:
        return (
            pos.option_type is not None
            and pos.option_type.lower() == "call"
            and pos.strike is not None
            and pos.strike >= 1.0
            and (pos.quantity or 0) > 0
        )

    def _classify_positions(self, positions: List[PositionData]) -> tuple:
        """分类持仓为 stock_positions 和 leaps_positions"""
        stock_positions = [p for p in positions if self._is_stock_proxy(p)]
        leaps_positions = [p for p in positions if self._is_leaps(p)]
        return stock_positions, leaps_positions

    def _compute_current_exposure(
        self, stock_positions: List[PositionData], leaps_positions: List[PositionData], context: MarketContext
    ) -> float:
        """计算当前总暴露百分比 (stock_pct + leaps_delta_pct)"""
        if self._last_nlv <= 0:
            return 0.0

        total_exposure = 0.0

        # Stock proxy: delta=1, lot_size=1
        for pos in stock_positions:
            qty = pos.quantity or 0
            spot = pos.underlying_price
            if spot is None:
                symbol = pos.symbol.split("_")[0] if "_" in pos.symbol else pos.symbol
                spot = context.underlying_prices.get(symbol, 0)
            total_exposure += qty * spot

        # LEAPS: delta * qty * multiplier * spot
        for pos in leaps_positions:
            delta = pos.delta or 0
            qty = pos.quantity or 0
            multiplier = pos.contract_multiplier or 100
            spot = pos.underlying_price
            if spot is None:
                symbol = pos.symbol.split("_")[0] if "_" in pos.symbol else pos.symbol
                spot = context.underlying_prices.get(symbol, 0)
            total_exposure += delta * qty * multiplier * spot

        return total_exposure / self._last_nlv

    # ==========================================
    # LEAPS 合约选择（复用 LongLeapsCallSmaTiming pattern）
    # ==========================================
    def _select_best_contract(
        self,
        calls: list,
        target_strike: float,
        target_dte: int,
        current_date: date,
    ) -> Optional[Any]:
        """从 OptionChain.calls 中选取最匹配的 LEAPS Call 合约"""
        cfg = self._ensure_config_loaded()
        best_score = -float("inf")
        best = None

        for call in calls:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days

            if dte < cfg.min_dte or dte > cfg.max_dte:
                continue

            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if mid is None or mid <= 0:
                continue

            delta = call.greeks.delta if call.greeks else None
            if delta is None or delta <= 0:
                continue

            dte_dev = abs(dte - target_dte) / target_dte if target_dte > 0 else 0
            strike_dev = abs(contract.strike_price - target_strike) / target_strike if target_strike > 0 else 0
            score = -_W_DTE * dte_dev - _W_STRIKE * strike_dev

            if score > best_score:
                best_score = score
                best = call

        return best

    # ==========================================
    # 阶段 1: evaluate_positions — 完全 override
    # ==========================================
    def evaluate_positions(
        self, positions: List[PositionData], context: MarketContext, data_provider: Any = None
    ) -> List[TradeSignal]:
        """监控 & 平仓: 信号计算 → 减仓(先 LEAPS 后 stock) / 清仓 / roll"""
        from src.backtest.engine.trade_simulator import TradeAction

        self._last_positions = list(positions)
        self._trading_day_count += 1
        self._last_eval_date = context.current_date

        # 重置跨方法标志
        self._pending_rebalance = False
        self._pending_exit_to_cash = False
        self._pending_leaps_topup_contracts = 0

        cfg = self._ensure_config_loaded()
        signals: List[TradeSignal] = []

        stock_positions, leaps_positions = self._classify_positions(positions)

        if not stock_positions and not leaps_positions:
            return signals

        # NLV 由 generate_entry_signals 更新，这里用上次值做近似
        target_pct = self._compute_signal(context, data_provider)

        # 计算当前暴露
        current_pct = self._compute_current_exposure(stock_positions, leaps_positions, context)

        # 记录 current_pct 到信号元数据
        self._last_signal_detail["current_pct"] = current_pct

        # === 决策逻辑 ===

        # a) target == 0 → 全部清仓
        if target_pct == 0.0:
            self._pending_exit_to_cash = True
            sd = self._last_signal_detail
            score = sd.get("momentum_score", 0)
            vix = sd.get("vix", 0)
            # LEAPS 先平
            for pos in leaps_positions:
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason=f"VolTgt exit: target=0 (score={score}) vix={vix:.1f} | close LEAPS",
                        alert_type="voltgt_exit",
                        position_id=pos.position_id,
                        priority="high",
                    )
                )
            for pos in stock_positions:
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason=f"VolTgt exit: target=0 (score={score}) vix={vix:.1f} | close stock",
                        alert_type="voltgt_exit",
                        position_id=pos.position_id,
                        priority="high",
                    )
                )
            logger.info(f"VOLTGT EXIT: target_pct=0 score={score}, closing all positions")
            return signals

        # b) LEAPS DTE roll check
        for pos in leaps_positions:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_rebalance = True
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason=f"LEAPS roll: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                        alert_type="roll_dte",
                        position_id=pos.position_id,
                        priority="normal",
                    )
                )
                logger.info(f"LEAPS ROLL: closing {pos.symbol} DTE={pos.dte}")

        # DTE ≤ 5 safety net
        for pos in leaps_positions:
            if pos.dte is not None and pos.dte <= 5:
                already_closing = any(s.position_id == pos.position_id for s in signals)
                if not already_closing:
                    self._pending_rebalance = True
                    signals.append(
                        TradeSignal(
                            action=TradeAction.CLOSE,
                            symbol=pos.symbol,
                            quantity=-(pos.quantity or 0),
                            reason=f"Safety net: LEAPS DTE={pos.dte} <= 5",
                            alert_type="roll_dte",
                            position_id=pos.position_id,
                            priority="high",
                        )
                    )

        # 如果已经有 roll 信号，计算需要补入的合约数（替代被 roll 的仓位）
        if signals:
            closing_ids = {s.position_id for s in signals}
            surviving_leaps = [p for p in leaps_positions if p.position_id not in closing_ids]
            surviving_qty = sum(p.quantity or 0 for p in surviving_leaps)

            target_leaps_pct = max(0.0, target_pct - 1.0)
            if target_leaps_pct > 0 and self._last_nlv > 0 and leaps_positions:
                rep = leaps_positions[0]
                rep_delta = rep.delta or 0.8
                rep_multiplier = rep.contract_multiplier or 100
                rep_spot = rep.underlying_price
                if rep_spot is None:
                    sym = rep.symbol.split("_")[0] if "_" in rep.symbol else rep.symbol
                    rep_spot = context.underlying_prices.get(sym, 0)

                if rep_delta > 0 and rep_spot > 0:
                    target_contracts = math.floor(
                        target_leaps_pct * self._last_nlv / (rep_delta * rep_multiplier * rep_spot)
                    )
                    self._pending_leaps_topup_contracts = max(0, target_contracts - surviving_qty)
                    logger.info(
                        f"ROLL: target_contracts={target_contracts} surviving={surviving_qty} "
                        f"topup={self._pending_leaps_topup_contracts}"
                    )

            return signals

        # c) 再平衡判断: |target - current| > threshold + 冷却期
        delta_pct = target_pct - current_pct
        if abs(delta_pct) > cfg.rebalance_threshold and self._rebalance_cooldown_ok():
            # 分解: stock 部分 vs LEAPS 部分
            target_stock_pct = min(1.0, target_pct)
            target_leaps_pct = max(0.0, target_pct - 1.0)

            # 计算当前 stock/leaps 各自的暴露
            stock_exposure = 0.0
            for pos in stock_positions:
                qty = pos.quantity or 0
                spot = pos.underlying_price
                if spot is None:
                    symbol = pos.symbol.split("_")[0] if "_" in pos.symbol else pos.symbol
                    spot = context.underlying_prices.get(symbol, 0)
                stock_exposure += qty * spot
            current_stock_pct = stock_exposure / self._last_nlv if self._last_nlv > 0 else 0.0

            sd = self._last_signal_detail
            rb_score = sd.get("momentum_score", "?")
            rb_vix = sd.get("vix", 0)

            # LEAPS 部分: 增量调仓（以合约为最小交易单位）
            if leaps_positions:
                rep = leaps_positions[0]
                rep_delta = rep.delta or 0
                rep_multiplier = rep.contract_multiplier or 100
                rep_spot = rep.underlying_price
                if rep_spot is None:
                    sym = rep.symbol.split("_")[0] if "_" in rep.symbol else rep.symbol
                    rep_spot = context.underlying_prices.get(sym, 0)

                total_current = sum(p.quantity or 0 for p in leaps_positions)
                if rep_delta > 0 and rep_spot > 0 and self._last_nlv > 0:
                    target_contracts = math.floor(
                        target_leaps_pct * self._last_nlv / (rep_delta * rep_multiplier * rep_spot)
                    )
                    diff = target_contracts - total_current

                    if diff <= -1:
                        # 减仓: 从最大仓位卖出差额（部分平仓）
                        sell_qty = min(abs(diff), total_current)
                        pos = max(leaps_positions, key=lambda p: p.quantity or 0)
                        sell_qty = min(sell_qty, pos.quantity or 0)
                        if sell_qty > 0:
                            signals.append(TradeSignal(
                                action=TradeAction.CLOSE,
                                symbol=pos.symbol,
                                quantity=-sell_qty,
                                reason=(
                                    f"LEAPS reduce: {total_current}→{target_contracts} ({diff:+d}) "
                                    f"target={target_pct:.2f} current={current_pct:.2f} "
                                    f"| score={rb_score} vix={rb_vix:.1f}"
                                ),
                                alert_type="rebalance",
                                position_id=pos.position_id,
                                priority="normal",
                            ))
                            self._last_rebalance_day = self._trading_day_count
                    elif diff >= 1:
                        # 加仓: 标记需要新增合约数
                        self._pending_leaps_topup_contracts = diff
                        self._pending_rebalance = True
                    # |diff| < 1: 不足一手，不交易（天然死区）
            elif target_leaps_pct > 0:
                # 无 LEAPS 仓位但目标 > 0 → 需要新开
                self._pending_rebalance = True

            # Stock 部分: 增量调仓（merge 后最多 1 个股票仓位）
            stock_delta_pct = target_stock_pct - current_stock_pct
            if abs(stock_delta_pct) > cfg.rebalance_threshold:
                if stock_delta_pct < 0 and stock_positions:
                    # 减仓: 只卖差额股数（部分平仓），不需要重开
                    pos = stock_positions[0]
                    spot = pos.underlying_price
                    if spot is None:
                        symbol = pos.symbol.split("_")[0] if "_" in pos.symbol else pos.symbol
                        spot = context.underlying_prices.get(symbol, 0)
                    if self._last_nlv > 0 and spot > 0:
                        shares_to_sell = math.ceil(abs(stock_delta_pct) * self._last_nlv / spot)
                        shares_to_sell = min(shares_to_sell, abs(pos.quantity or 0))
                        if shares_to_sell > 0:
                            signals.append(
                                TradeSignal(
                                    action=TradeAction.CLOSE,
                                    symbol=pos.symbol,
                                    quantity=-shares_to_sell,
                                    reason=(
                                        f"Rebalance: target={target_pct:.2f} current={current_pct:.2f} "
                                        f"Δ={delta_pct:+.2f} | score={rb_score} vix={rb_vix:.1f} "
                                        f"| sell {shares_to_sell} shares"
                                    ),
                                    alert_type="rebalance",
                                    position_id=pos.position_id,
                                    priority="normal",
                                )
                            )
                    # 不设 _pending_rebalance，减仓不需要重开
                elif stock_delta_pct > 0:
                    # 加仓: 不平现有持仓，直接标记需要 top-up
                    self._pending_stock_topup_pct = stock_delta_pct
                    self._pending_rebalance = True

            if signals or self._pending_stock_topup_pct > 0 or self._pending_rebalance:
                self._last_rebalance_day = self._trading_day_count
                logger.info(
                    f"REBALANCE: target={target_pct:.2f} current={current_pct:.2f} Δ={delta_pct:+.2f} "
                    f"stock_topup={self._pending_stock_topup_pct:.2f} leaps_topup={self._pending_leaps_topup_contracts}"
                )

        return signals

    # ==========================================
    # 阶段 2: find_opportunities — 完全 override
    # ==========================================
    def find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        """寻找 Stock Proxy 和 LEAPS Call 开仓机会"""
        cfg = self._ensure_config_loaded()

        # 补偿: 无持仓时 evaluate_positions 未被调用
        if self._last_eval_date != context.current_date:
            self._trading_day_count += 1
            self._last_positions = []
            self._pending_rebalance = False
            self._pending_exit_to_cash = False
            self._pending_stock_topup_pct = 0.0
            self._pending_leaps_topup_contracts = 0

        target_pct = self._compute_signal(context, data_provider)

        # 判断是否需要开仓
        need_entry = False
        if self._pending_rebalance:
            need_entry = True
        elif self._pending_exit_to_cash:
            need_entry = False
        elif target_pct > 0:
            # 无持仓 + 信号看多 + decision day
            stock_pos, leaps_pos = self._classify_positions(self._last_positions)
            if not stock_pos and not leaps_pos and self._is_decision_day():
                need_entry = True

        if not need_entry or target_pct <= 0:
            self._pending_stock_topup_pct = 0.0
            self._pending_leaps_topup_contracts = 0
            return []

        # 仓位分解: 优先使用增量 top-up，否则用全额
        if self._pending_stock_topup_pct > 0:
            stock_pct = self._pending_stock_topup_pct
            self._pending_stock_topup_pct = 0.0
        elif self._pending_rebalance:
            stock_pos, _ = self._classify_positions(self._last_positions)
            stock_pct = 0.0 if stock_pos else min(1.0, target_pct)
        else:
            stock_pct = min(1.0, target_pct)
        # LEAPS 目标: 仅当无存量 LEAPS 或有增量合约需求时才分配新的 LEAPS
        _, existing_leaps = self._classify_positions(self._last_positions)
        if existing_leaps and self._pending_leaps_topup_contracts <= 0:
            leaps_pct = 0.0  # 存量 LEAPS 充足，无需新开
        else:
            leaps_pct = max(0.0, target_pct - 1.0)

        opportunities: List[ContractOpportunity] = []

        for symbol in symbols:
            spot = context.underlying_prices.get(symbol)
            if not spot or spot <= 0:
                continue

            # a) Stock proxy
            if stock_pct > 0:
                stock_opp = ContractOpportunity(
                    symbol=symbol,
                    expiry=(context.current_date + timedelta(days=9999)).strftime("%Y-%m-%d"),
                    strike=0.01,
                    option_type="call",
                    lot_size=1,
                    bid=spot,
                    ask=spot,
                    mid_price=spot,
                    open_interest=999999,
                    volume=999999,
                    delta=1.0,
                    gamma=0.0,
                    theta=0.0,
                    vega=0.0,
                    iv=0.0,
                    dte=9999,
                    underlying_price=spot,
                    moneyness=0.0,
                    annual_roc=0.0,
                    metadata={
                        "source_strategy_type": "long_call",
                        "is_stock_proxy": True,
                        "target_pct": stock_pct,
                    },
                )
                opportunities.append(stock_opp)

            # b) LEAPS Call (仅当 target > 1.0)
            if leaps_pct > 0:
                target_strike = spot * cfg.target_moneyness

                chain = data_provider.get_option_chain(
                    underlying=symbol,
                    expiry_min_days=cfg.min_dte,
                    expiry_max_days=cfg.max_dte,
                )
                if not chain or not chain.calls:
                    logger.info(f"No LEAPS calls found for {symbol}, skipping leverage component")
                    continue

                best = self._select_best_contract(
                    chain.calls, target_strike, cfg.target_dte, context.current_date
                )
                if not best:
                    logger.info(f"No matching LEAPS contract for {symbol}")
                    continue

                contract = best.contract
                greeks = best.greeks
                dte = (contract.expiry_date - context.current_date).days
                mid = best.last_price
                if best.bid is not None and best.ask is not None and best.ask > 0:
                    mid = (best.bid + best.ask) / 2

                leaps_opp = ContractOpportunity(
                    symbol=symbol,
                    expiry=contract.expiry_date.strftime("%Y-%m-%d"),
                    strike=contract.strike_price,
                    option_type="call",
                    lot_size=contract.lot_size,
                    bid=best.bid,
                    ask=best.ask,
                    mid_price=mid,
                    open_interest=best.open_interest,
                    volume=best.volume,
                    delta=greeks.delta if greeks else None,
                    gamma=greeks.gamma if greeks else None,
                    theta=greeks.theta if greeks else None,
                    vega=greeks.vega if greeks else None,
                    iv=best.iv,
                    dte=dte,
                    underlying_price=spot,
                    moneyness=(spot - contract.strike_price) / contract.strike_price if contract.strike_price > 0 else None,
                    annual_roc=0.0,
                    metadata={
                        "source_strategy_type": "long_call",
                        "is_leaps": True,
                        "target_pct": leaps_pct,
                        **({"target_contracts": self._pending_leaps_topup_contracts} if self._pending_leaps_topup_contracts > 0 else {}),
                    },
                )
                opportunities.append(leaps_opp)
                self._pending_leaps_topup_contracts = 0
                logger.info(
                    f"LEAPS opportunity: {symbol} strike={contract.strike_price:.0f} "
                    f"DTE={dte} delta={greeks.delta if greeks else '?'} mid={mid:.2f} target_pct={leaps_pct:.2f}"
                )

        return opportunities

    # ==========================================
    # 阶段 3: generate_entry_signals — 完全 override
    # ==========================================
    def generate_entry_signals(
        self,
        candidates: List[ContractOpportunity],
        account: Any,
        context: MarketContext,
    ) -> List[TradeSignal]:
        """按目标百分比计算 stock shares 和 LEAPS Call 合约数量"""
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import Greeks, OptionContract, OptionQuote, OptionType

        if not candidates:
            return []

        cfg = self._ensure_config_loaded()
        nlv = account.nlv
        cash = account.cash
        self._last_nlv = nlv

        if nlv <= 0:
            return []

        # 保证金账户: 始终基于 NLV 计算 (cash 可为负)
        available_capital = cfg.max_capital_pct * nlv

        signals: List[TradeSignal] = []

        for opp in candidates:
            spot = opp.underlying_price or context.underlying_prices.get(opp.symbol, 0)
            if not spot or spot <= 0:
                continue

            is_stock_proxy = opp.metadata.get("is_stock_proxy", False) if opp.metadata else False
            is_leaps = opp.metadata.get("is_leaps", False) if opp.metadata else False
            target_pct = opp.metadata.get("target_pct", 0.0) if opp.metadata else 0.0

            if target_pct <= 0:
                continue

            if is_stock_proxy:
                # Stock proxy: shares = target_pct * NLV / spot
                target_value = target_pct * nlv
                shares = math.floor(target_value / spot)

                if shares <= 0:
                    continue

                # Stock 不消耗 available_capital (保证金账户: stock 贡献 NLV)
                # AccountSimulator 允许负 cash

                expiration = context.current_date + timedelta(days=9999)
                option_contract = OptionContract(
                    symbol=f"{opp.symbol}_{expiration.strftime('%y%m%d')}_C_0",
                    underlying=opp.symbol,
                    option_type=OptionType.CALL,
                    strike_price=opp.strike,
                    expiry_date=expiration,
                    lot_size=1,
                )
                greeks = Greeks(delta=1.0, gamma=0.0, theta=0.0, vega=0.0)
                quote = OptionQuote(
                    contract=option_contract,
                    timestamp=datetime.combine(context.current_date, datetime.min.time()),
                    bid=spot,
                    ask=spot,
                    last_price=spot,
                    iv=0.0,
                    volume=99999,
                    open_interest=99999,
                    greeks=greeks,
                )

                sd = self._last_signal_detail
                signals.append(
                    TradeSignal(
                        action=TradeAction.OPEN,
                        symbol=option_contract.symbol,
                        quantity=shares,
                        reason=(
                            f"Stock proxy: {shares} shares @ {spot:.2f} "
                            f"target_pct={target_pct:.2f} | score={sd.get('momentum_score', '?')} "
                            f"vix={sd.get('vix', 0):.1f} vol_scalar={sd.get('vol_scalar', 0):.2f}"
                        ),
                        priority="normal",
                        quote=quote,
                    )
                )

            elif is_leaps:
                delta = opp.delta
                mid = opp.mid_price
                lot_size = opp.lot_size or 100

                if not delta or delta <= 0 or not mid or mid <= 0:
                    logger.warning(f"Skipping LEAPS {opp.symbol}: missing delta/mid")
                    continue

                # 优先使用增量 target_contracts，否则从百分比计算
                if opp.metadata and "target_contracts" in opp.metadata:
                    contracts = int(opp.metadata["target_contracts"])
                else:
                    contracts = math.floor(target_pct * nlv / (delta * lot_size * spot))

                # 资金约束: LEAPS 独立预算 (不与 stock 共享，作为安全上限)
                if mid * lot_size > 0:
                    leaps_budget = cfg.max_capital_pct * nlv
                    max_contracts = math.floor(leaps_budget / (mid * lot_size))
                    contracts = min(contracts, max_contracts)

                if contracts <= 0:
                    continue

                total_premium = contracts * mid * lot_size

                try:
                    expiration = datetime.strptime(opp.expiry, "%Y-%m-%d").date()
                except Exception:
                    expiration = context.current_date + timedelta(days=opp.dte)

                option_contract = OptionContract(
                    symbol=opp.symbol,
                    underlying=opp.symbol,
                    option_type=OptionType.CALL,
                    strike_price=opp.strike,
                    expiry_date=expiration,
                    lot_size=lot_size,
                )
                greeks = Greeks(
                    delta=opp.delta,
                    gamma=opp.gamma,
                    theta=opp.theta,
                    vega=opp.vega,
                )
                quote = OptionQuote(
                    contract=option_contract,
                    timestamp=datetime.combine(context.current_date, datetime.min.time()),
                    bid=opp.bid or mid,
                    ask=opp.ask or mid,
                    last_price=mid,
                    iv=opp.iv,
                    volume=opp.volume or 0,
                    open_interest=opp.open_interest or 0,
                    greeks=greeks,
                )

                actual_leverage = (contracts * delta * lot_size * spot) / nlv

                sd = self._last_signal_detail
                signals.append(
                    TradeSignal(
                        action=TradeAction.OPEN,
                        symbol=opp.symbol,
                        quantity=contracts,
                        reason=(
                            f"LEAPS entry: {contracts}x K={opp.strike:.0f} DTE={opp.dte} "
                            f"delta={delta:.2f} | score={sd.get('momentum_score', '?')} "
                            f"vix={sd.get('vix', 0):.1f} target_pct={sd.get('target_pct', 0):.2f}"
                        ),
                        priority="normal",
                        quote=quote,
                    )
                )
                logger.info(
                    f"LEAPS ENTRY: {opp.symbol} {contracts}x @ {mid:.2f} "
                    f"leverage={actual_leverage:.2f}x premium=${total_premium:,.0f}"
                )

        return signals

    # ==========================================
    # 辅助
    # ==========================================
    def _is_decision_day(self) -> bool:
        cfg = self._ensure_config_loaded()
        return self._trading_day_count % cfg.decision_frequency == 0

    def _rebalance_cooldown_ok(self) -> bool:
        """检查是否已过冷却期"""
        cfg = self._ensure_config_loaded()
        return (self._trading_day_count - self._last_rebalance_day) >= cfg.min_rebalance_interval
