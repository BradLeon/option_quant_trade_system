"""SPY Pure LEAPS + Cash Interest Strategy (Vol Target)

纯 LEAPS 版本: 所有暴露通过深度 ITM LEAPS Call 的 delta 控制，不持正股。
闲置现金按 ^TNX 无风险利率计息（模拟货币基金/国债收益）。

信号系统完全复用 SpyMomentumLevVolTarget:
- 7 分动量评分 (5 SMA + 2 momentum)
- 仓位映射: {0:0, 1:0, 2:0.5, 3:1.0, 4:1.5, 5:2.0, 6:2.5, 7:3.0}
- Vol Target: vol_scalar = min(2.0, 15/VIX)
- 最终目标 = raw × vol_scalar, 上限 3.0

与 SpyMomentumLevVolTarget 的关键差异:
- target_pct 直接映射到 LEAPS delta 暴露 (target=1.0 → LEAPS 暴露 = 100% NLV)
- 资金约束: cash-based (实际现金支付期权金), 非 NLV-based
- 每日按 ^TNX 利率对正现金计息
- 无 stock proxy / stock_positions / _pending_stock_topup_pct
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
from src.business.strategy.versions._momentum_vol_mixin import (
    DEFAULT_POSITION_MAP,
    MomentumVolTargetMixin,
)

logger = logging.getLogger(__name__)


@dataclass
class LeapsOnlyVolTargetConfig:
    """Pure LEAPS + Cash Interest + Vol Target 策略配置"""

    # SMA 信号参数
    sma_periods: tuple = (20, 50, 200)
    momentum_lookback_short: int = 20
    momentum_lookback_long: int = 60
    position_map: dict = field(default_factory=lambda: dict(DEFAULT_POSITION_MAP))

    # Volatility targeting
    vol_target: float = 15.0
    vol_scalar_max: float = 2.0
    max_exposure: float = 3.0

    # 决策频率 & 再平衡
    decision_frequency: int = 1
    rebalance_threshold: float = 0.25
    min_rebalance_interval: int = 5

    # LEAPS 合约参数
    target_moneyness: float = 0.85
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400
    roll_dte_threshold: int = 60
    max_capital_pct: float = 0.95

    # 现金利息
    cash_yield_enabled: bool = True
    default_risk_free_rate: float = 0.04  # ^TNX 缺失时的 fallback

    @classmethod
    def from_yaml(cls, path: Path) -> "LeapsOnlyVolTargetConfig":
        with open(path) as f:
            raw = yaml.safe_load(f)
        section = raw.get("leaps_only_vol_target_config", {})
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in section.items() if k in known_fields}
        if "position_map" in filtered and isinstance(filtered["position_map"], dict):
            filtered["position_map"] = {int(k): float(v) for k, v in filtered["position_map"].items()}
        return cls(**filtered)

    @classmethod
    def default_yaml_path(cls) -> Path:
        return Path(__file__).resolve().parents[4] / "config" / "screening" / "spy_leaps_only_vol_target.yaml"


class SpyLeapsOnlyVolTarget(BaseTradeStrategy, MomentumVolTargetMixin):
    """Pure LEAPS + Cash Interest + Vol Target 策略

    7 分动量评分 + vol_scalar=min(2.0, 15/VIX)。
    所有暴露通过深度 ITM LEAPS Call delta 控制，闲置现金按 ^TNX 计息。

    完全 override 三个生命周期方法:
    - evaluate_positions: 信号计算 + 仓位调整 (减仓/清仓/roll，纯 LEAPS)
    - find_opportunities: 开仓/再平衡时选取 LEAPS Call
    - generate_entry_signals: 按目标百分比计算 LEAPS 合约数量 (现金约束)
    """

    _signal_log_prefix = "LeapsOnly"

    def __init__(self):
        super().__init__()
        self._config: Optional[LeapsOnlyVolTargetConfig] = None

        # 信号缓存
        self._signal_computed_for_date: Optional[date] = None
        self._current_target_pct: float = 0.0
        self._last_signal_detail: dict = {}

        # 跨方法协调标志 (无 stock 相关)
        self._pending_rebalance: bool = False
        self._pending_exit_to_cash: bool = False
        self._pending_leaps_topup_contracts: int = 0

        # 交易日计数 & 冷却期
        self._trading_day_count: int = 0
        self._last_eval_date: Optional[date] = None
        self._last_nlv: float = 0.0
        self._last_rebalance_day: int = -9999

        # 现金利息累积
        self._cumulative_interest: float = 0.0
        self._tnx_cache: dict[date, float] = {}

    @property
    def name(self) -> str:
        return "spy_leaps_only_vol_target"

    @property
    def position_side(self) -> str:
        return "LONG"

    # ==========================================
    # 配置加载
    # ==========================================
    def _ensure_config_loaded(self) -> LeapsOnlyVolTargetConfig:
        if self._config is None:
            path = LeapsOnlyVolTargetConfig.default_yaml_path()
            if path.exists():
                self._config = LeapsOnlyVolTargetConfig.from_yaml(path)
            else:
                self._config = LeapsOnlyVolTargetConfig()
        return self._config

    # ==========================================
    # 现金利息 (LeapsOnly 特有)
    # ==========================================
    def _compute_daily_interest(self, cash: float, current_date: date, data_provider: Any) -> float:
        """返回当日应计利息金额。仅正现金生息。

        由 BacktestExecutor duck-typing 调用。
        """
        cfg = self._ensure_config_loaded()
        if not cfg.cash_yield_enabled or cash <= 0:
            return 0.0
        rate = self._get_risk_free_rate(current_date, data_provider)
        interest = cash * (rate / 365.0)
        self._cumulative_interest += interest
        return interest

    def _get_risk_free_rate(self, current_date: date, data_provider: Any) -> float:
        """获取当日无风险利率 (^TNX)"""
        if current_date in self._tnx_cache:
            return self._tnx_cache[current_date]
        try:
            tnx_data = data_provider.get_macro_data("^TNX", current_date - timedelta(days=7), current_date)
            if tnx_data:
                val = tnx_data[-1].close / 1000.0
                self._tnx_cache[current_date] = val
                return val
        except Exception:
            pass
        rate = self._ensure_config_loaded().default_risk_free_rate
        self._tnx_cache[current_date] = rate
        return rate

    # ==========================================
    # 仓位辅助
    # ==========================================
    def _get_leaps_positions(self, positions: List[PositionData]) -> List[PositionData]:
        return [p for p in positions if self._is_leaps(p)]

    def _compute_current_exposure(self, leaps_positions: List[PositionData], context: MarketContext) -> float:
        """计算当前总暴露百分比 (纯 LEAPS delta)"""
        if self._last_nlv <= 0:
            return 0.0
        total = 0.0
        for pos in leaps_positions:
            delta = pos.delta or 0
            qty = pos.quantity or 0
            multiplier = pos.contract_multiplier or 100
            spot = self._resolve_spot(pos, context)
            total += delta * qty * multiplier * spot
        return total / self._last_nlv

    # ==========================================
    # 阶段 1: evaluate_positions — 拆分为子方法
    # ==========================================
    def evaluate_positions(
        self, positions: List[PositionData], context: MarketContext, data_provider: Any = None
    ) -> List[TradeSignal]:
        """监控 & 平仓: 信号计算 → 减仓/清仓/roll (纯 LEAPS，无 stock)"""
        self._begin_eval_day(positions, context)
        leaps = self._get_leaps_positions(positions)
        if not leaps:
            return []

        target_pct = self._compute_signal(context, data_provider)
        current_pct = self._compute_current_exposure(leaps, context)
        self._last_signal_detail["current_pct"] = current_pct

        # a) target == 0 → 全部清仓
        if target_pct == 0.0:
            return self._signal_exit_all(leaps)

        # b) LEAPS DTE roll check
        roll_signals = self._signal_roll_expiring(leaps)
        if roll_signals:
            self._plan_roll_topup(leaps, roll_signals, target_pct, context)
            return roll_signals

        # c) 再平衡判断
        return self._signal_rebalance(leaps, target_pct, current_pct, context)

    def _begin_eval_day(self, positions: List[PositionData], context: MarketContext) -> None:
        """重置跨方法标志，递增交易日计数。"""
        self._last_positions = list(positions)
        self._trading_day_count += 1
        self._last_eval_date = context.current_date
        self._pending_rebalance = False
        self._pending_exit_to_cash = False
        self._pending_leaps_topup_contracts = 0

    def _signal_exit_all(self, leaps: List[PositionData]) -> List[TradeSignal]:
        """target=0: 生成全部 LEAPS 平仓信号。"""
        from src.backtest.engine.trade_simulator import TradeAction

        self._pending_exit_to_cash = True
        sd = self._last_signal_detail
        score = sd.get("momentum_score", 0)
        vix = sd.get("vix", 0)

        signals = []
        for pos in leaps:
            signals.append(
                TradeSignal(
                    action=TradeAction.CLOSE,
                    symbol=pos.symbol,
                    quantity=-(pos.quantity or 0),
                    reason=f"LeapsOnly exit: target=0 (score={score}) vix={vix:.1f}",
                    alert_type="voltgt_exit",
                    position_id=pos.position_id,
                    priority="high",
                )
            )
        logger.info(f"LEAPS_ONLY EXIT: target_pct=0 score={score}, closing all LEAPS")
        return signals

    def _signal_roll_expiring(self, leaps: List[PositionData]) -> List[TradeSignal]:
        """DTE roll check + DTE<=5 safety net。"""
        from src.backtest.engine.trade_simulator import TradeAction

        cfg = self._ensure_config_loaded()
        signals: List[TradeSignal] = []

        for pos in leaps:
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

        # DTE <= 5 safety net
        for pos in leaps:
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
        return signals

    def _plan_roll_topup(
        self,
        leaps: List[PositionData],
        roll_signals: List[TradeSignal],
        target_pct: float,
        context: MarketContext,
    ) -> None:
        """Roll 后计算需要补入的合约数。"""
        closing_ids = {s.position_id for s in roll_signals}
        surviving = [p for p in leaps if p.position_id not in closing_ids]
        surviving_qty = sum(p.quantity or 0 for p in surviving)

        if target_pct > 0 and self._last_nlv > 0 and leaps:
            target_contracts = self._compute_leaps_target_contracts(
                target_pct, leaps[0], context, default_delta=0.8
            )
            self._pending_leaps_topup_contracts = max(0, target_contracts - surviving_qty)
            logger.info(
                f"ROLL: target_contracts={target_contracts} surviving={surviving_qty} "
                f"topup={self._pending_leaps_topup_contracts}"
            )

    def _signal_rebalance(
        self,
        leaps: List[PositionData],
        target_pct: float,
        current_pct: float,
        context: MarketContext,
    ) -> List[TradeSignal]:
        """再平衡: 加仓/减仓 LEAPS。"""
        from src.backtest.engine.trade_simulator import TradeAction

        cfg = self._ensure_config_loaded()
        signals: List[TradeSignal] = []

        delta_pct = target_pct - current_pct
        if abs(delta_pct) <= cfg.rebalance_threshold or not self._rebalance_cooldown_ok():
            return signals

        sd = self._last_signal_detail
        rb_score = sd.get("momentum_score", "?")
        rb_vix = sd.get("vix", 0)

        if leaps:
            rep = leaps[0]
            rep_delta = rep.delta or 0
            rep_multiplier = rep.contract_multiplier or 100
            rep_spot = self._resolve_spot(rep, context)
            total_current = sum(p.quantity or 0 for p in leaps)

            if rep_delta > 0 and rep_spot > 0 and self._last_nlv > 0:
                target_contracts = math.floor(
                    target_pct * self._last_nlv / (rep_delta * rep_multiplier * rep_spot)
                )
                diff = target_contracts - total_current

                if diff <= -1:
                    sell_qty = min(abs(diff), total_current)
                    pos = max(leaps, key=lambda p: p.quantity or 0)
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
                    self._pending_leaps_topup_contracts = diff
                    self._pending_rebalance = True
        elif target_pct > 0:
            self._pending_rebalance = True

        if signals or self._pending_rebalance:
            self._last_rebalance_day = self._trading_day_count
            logger.info(
                f"REBALANCE: target={target_pct:.2f} current={current_pct:.2f} Δ={delta_pct:+.2f} "
                f"leaps_topup={self._pending_leaps_topup_contracts}"
            )

        return signals

    # ==========================================
    # 阶段 2: find_opportunities — 拆分为子方法
    # ==========================================
    def find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        """寻找 LEAPS Call 开仓机会 (无 stock proxy)"""
        self._sync_if_no_eval(context)
        target_pct = self._compute_signal(context, data_provider)
        leaps_pct = self._resolve_leaps_target(target_pct)
        if leaps_pct <= 0:
            return []
        return self._search_leaps_opportunities(symbols, data_provider, context, leaps_pct)

    def _sync_if_no_eval(self, context: MarketContext) -> None:
        """补偿: 无持仓时 evaluate_positions 未被调用。"""
        if self._last_eval_date != context.current_date:
            self._trading_day_count += 1
            self._last_positions = []
            self._pending_rebalance = False
            self._pending_exit_to_cash = False
            self._pending_leaps_topup_contracts = 0

    def _resolve_leaps_target(self, target_pct: float) -> float:
        """判断是否需要开仓，返回 LEAPS 目标百分比 (0 = 不开仓)。"""
        need_entry = False
        if self._pending_rebalance:
            need_entry = True
        elif self._pending_exit_to_cash:
            need_entry = False
        elif target_pct > 0:
            leaps_pos = self._get_leaps_positions(self._last_positions)
            if not leaps_pos and self._is_decision_day():
                need_entry = True

        if not need_entry or target_pct <= 0:
            self._pending_leaps_topup_contracts = 0
            return 0.0

        existing_leaps = self._get_leaps_positions(self._last_positions)
        if existing_leaps and self._pending_leaps_topup_contracts <= 0:
            return 0.0
        return target_pct

    def _search_leaps_opportunities(
        self,
        symbols: List[str],
        data_provider: Any,
        context: MarketContext,
        leaps_pct: float,
    ) -> List[ContractOpportunity]:
        """遍历 symbols 查链、选合约、构造 ContractOpportunity。"""
        cfg = self._ensure_config_loaded()
        opportunities: List[ContractOpportunity] = []

        for symbol in symbols:
            spot = context.underlying_prices.get(symbol)
            if not spot or spot <= 0:
                continue

            target_strike = spot * cfg.target_moneyness
            chain = data_provider.get_option_chain(
                underlying=symbol,
                expiry_min_days=cfg.min_dte,
                expiry_max_days=cfg.max_dte,
            )
            if not chain or not chain.calls:
                logger.info(f"No LEAPS calls found for {symbol}")
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
    # 阶段 3: generate_entry_signals — 拆分为子方法
    # ==========================================
    def generate_entry_signals(
        self,
        candidates: List[ContractOpportunity],
        account: Any,
        context: MarketContext,
    ) -> List[TradeSignal]:
        """按目标百分比计算 LEAPS Call 合约数量 (现金约束)"""
        self._last_nlv = account.nlv
        if account.nlv <= 0 or not candidates:
            return []
        return [
            sig for opp in candidates
            if (sig := self._build_leaps_open_signal(opp, account, context)) is not None
        ]

    def _build_leaps_open_signal(
        self,
        opp: ContractOpportunity,
        account: Any,
        context: MarketContext,
    ) -> Optional[TradeSignal]:
        """单个候选 → 计算合约数 (含现金约束) → 构造 TradeSignal 或 None。"""
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import Greeks, OptionContract, OptionQuote, OptionType

        cfg = self._ensure_config_loaded()
        nlv = account.nlv
        cash = account.cash

        spot = opp.underlying_price or context.underlying_prices.get(opp.symbol, 0)
        if not spot or spot <= 0:
            return None

        is_leaps = opp.metadata.get("is_leaps", False) if opp.metadata else False
        target_pct = opp.metadata.get("target_pct", 0.0) if opp.metadata else 0.0
        if not is_leaps or target_pct <= 0:
            return None

        delta = opp.delta
        mid = opp.mid_price
        lot_size = opp.lot_size or 100

        if not delta or delta <= 0 or not mid or mid <= 0:
            logger.warning(f"Skipping LEAPS {opp.symbol}: missing delta/mid")
            return None

        # 优先使用增量 target_contracts
        if opp.metadata and "target_contracts" in opp.metadata:
            contracts = int(opp.metadata["target_contracts"])
        else:
            contracts = math.floor(target_pct * nlv / (delta * lot_size * spot))

        # 资金约束: 基于实际现金 (非 NLV)
        if mid * lot_size > 0 and cash > 0:
            max_contracts = math.floor((cfg.max_capital_pct * cash) / (mid * lot_size))
            contracts = min(contracts, max_contracts)

        if contracts <= 0:
            return None

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
        logger.info(
            f"LEAPS ENTRY: {opp.symbol} {contracts}x @ {mid:.2f} "
            f"leverage={actual_leverage:.2f}x premium=${total_premium:,.0f} (cash-constrained)"
        )

        return TradeSignal(
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
