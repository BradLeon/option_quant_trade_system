"""Long LEAPS Call + SMA Timing Strategy

深度 ITM LEAPS Call + SMA200 均线择时策略:
- SMA 上方: 持有深度 ITM LEAPS Call，提供 ~3x delta 暴露
- SMA 下方: 全部清仓，持有现金
- 自动 Roll: DTE <= 阈值时平仓旧合约，买入新合约
- 自动 Rebalance: 实际杠杆偏离目标时调仓
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

# 合约选择权重
_W_DTE = 1.0
_W_STRIKE = 2.0


@dataclass
class LeapsCallConfig:
    """LEAPS Call 策略专用配置"""

    # SMA 信号参数
    sma_period: int = 200
    decision_frequency: int = 5

    # LEAPS 合约参数
    target_moneyness: float = 0.85  # Strike = Spot * 0.85 (15% ITM)
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400

    # 杠杆与仓位
    target_leverage: float = 3.0
    leverage_drift_threshold: float = 0.5
    max_capital_pct: float = 0.95

    # Roll 参数
    roll_dte_threshold: int = 60

    @classmethod
    def from_yaml(cls, path: Path) -> "LeapsCallConfig":
        """从 YAML 的 leaps_config 节点加载"""
        with open(path) as f:
            raw = yaml.safe_load(f)
        section = raw.get("leaps_config", {})
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in section.items() if k in known_fields}
        return cls(**filtered)

    @classmethod
    def default_yaml_path(cls) -> Path:
        """默认 YAML 路径"""
        return Path(__file__).resolve().parents[4] / "config" / "screening" / "long_leaps_call_sma_timing.yaml"


class LongLeapsCallSmaTiming(BaseTradeStrategy):
    """LEAPS Call + SMA 择时策略

    完全 override 三个生命周期方法:
    - evaluate_positions: SMA 信号翻空清仓 + DTE 滚仓 + 杠杆漂移调仓
    - find_opportunities: SMA 信号做多时选取最优 LEAPS 合约
    - generate_entry_signals: 按目标杠杆计算合约数量
    """

    def __init__(self):
        super().__init__()
        self._leaps_config: Optional[LeapsCallConfig] = None

        # SMA 信号状态
        self._signal_invested: bool = False
        self._signal_computed_for_date: Optional[date] = None

        # 跨方法协调标志
        self._pending_roll: bool = False
        self._pending_rebalance: bool = False
        self._pending_exit_to_cash: bool = False

        # 交易日计数器
        self._trading_day_count: int = 0

        # 跟踪 evaluate_positions 是否在当天被调用
        self._last_eval_date: Optional[date] = None

        # NLV 缓存
        self._last_nlv: float = 0.0

    @property
    def name(self) -> str:
        return "long_leaps_call_sma_timing"

    @property
    def position_side(self) -> str:
        return "LONG"

    # ==========================================
    # 配置加载
    # ==========================================
    def _ensure_config_loaded(self) -> LeapsCallConfig:
        """懒加载 YAML 配置"""
        if self._leaps_config is None:
            path = LeapsCallConfig.default_yaml_path()
            if path.exists():
                self._leaps_config = LeapsCallConfig.from_yaml(path)
            else:
                logger.warning(f"LEAPS config not found at {path}, using defaults")
                self._leaps_config = LeapsCallConfig()
        return self._leaps_config

    # ==========================================
    # SMA 信号计算
    # ==========================================
    def _compute_sma_signal(self, context: MarketContext, data_provider: Any) -> bool:
        """计算 SMA 信号，按 date 缓存

        无 look-ahead: 用前一个交易日收盘价 vs SMA200

        Returns:
            True = 看多 (invested), False = 看空 (cash)
        """
        if self._signal_computed_for_date == context.current_date:
            return self._signal_invested

        cfg = self._ensure_config_loaded()

        # 获取任一 symbol 的历史数据 (LEAPS 策略通常只做一个标的，如 SPY)
        symbols = list(context.underlying_prices.keys())
        if not symbols:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        symbol = symbols[0]

        from src.data.models.stock import KlineType

        # 需要足够多的历史数据来计算 SMA
        lookback_start = context.current_date - timedelta(days=cfg.sma_period * 2)
        klines = data_provider.get_history_kline(
            symbol=symbol,
            ktype=KlineType.DAY,
            start_date=lookback_start,
            end_date=context.current_date,
        )

        if not klines or len(klines) < cfg.sma_period:
            logger.info(
                f"SMA: insufficient data ({len(klines) if klines else 0} bars < {cfg.sma_period}), defaulting to CASH"
            )
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        # 提取收盘价序列 (oldest → newest)
        prices = [k.close for k in klines]

        from src.engine.position.technical.moving_average import calc_sma

        sma_value = calc_sma(prices, cfg.sma_period)

        if sma_value is None:
            self._signal_invested = False
            self._signal_computed_for_date = context.current_date
            return False

        # 用前一交易日 (即 klines[-1]) 的收盘价与 SMA 比较
        # klines 数据截至 as_of_date，最后一条是最近的交易日
        last_close = prices[-1]
        self._signal_invested = last_close > sma_value

        logger.debug(
            f"SMA signal: {symbol} close={last_close:.2f} vs SMA{cfg.sma_period}={sma_value:.2f} → {'INVESTED' if self._signal_invested else 'CASH'}"
        )

        self._signal_computed_for_date = context.current_date
        return self._signal_invested

    # ==========================================
    # 辅助方法
    # ==========================================
    def _is_decision_day(self) -> bool:
        """是否为决策日 (每 N 个交易日评估一次)"""
        cfg = self._ensure_config_loaded()
        return self._trading_day_count % cfg.decision_frequency == 0

    def _compute_actual_leverage(
        self, positions: List[PositionData], context: MarketContext
    ) -> float:
        """从 PositionData 计算实际杠杆

        leverage = sum(per_share_delta * qty * multiplier * spot) / NLV

        注意: 回测中 PositionData.delta 是 per-share delta (来自 option chain Greeks),
        需要乘以 quantity 和 contract_multiplier 得到 position-level exposure.
        """
        if self._last_nlv <= 0:
            return 0.0

        total_delta_exposure = 0.0
        for pos in positions:
            if pos.delta is None:
                continue

            qty = pos.quantity or 0
            multiplier = pos.contract_multiplier or 100

            spot = pos.underlying_price
            if spot is None:
                symbol = pos.symbol.split("_")[0] if "_" in pos.symbol else pos.symbol
                spot = context.underlying_prices.get(symbol, 0)

            total_delta_exposure += pos.delta * qty * multiplier * spot

        return total_delta_exposure / self._last_nlv

    def _get_leaps_positions(self, positions: List[PositionData]) -> List[PositionData]:
        """从持仓中筛选 LEAPS call 持仓"""
        return [
            p for p in positions
            if p.option_type and p.option_type.lower() == "call" and (p.quantity or 0) > 0
        ]

    def _select_best_contract(
        self,
        calls: list,
        target_strike: float,
        target_dte: int,
        current_date: date,
    ) -> Optional[Any]:
        """从 OptionChain.calls 中选取最匹配的合约

        打分: score = -w_dte * |dte - target_dte| / target_dte - w_strike * |strike - target_strike| / target_strike
        """
        cfg = self._ensure_config_loaded()
        best_score = -float("inf")
        best = None

        for call in calls:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days

            # 基本过滤
            if dte < cfg.min_dte or dte > cfg.max_dte:
                continue

            # mid price 必须 > 0
            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if mid is None or mid <= 0:
                continue

            # delta 必须 > 0 (deep ITM call)
            delta = call.greeks.delta if call.greeks else None
            if delta is None or delta <= 0:
                continue

            # 打分
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
        """评估持仓: SMA 翻空清仓 / DTE 滚仓 / 杠杆漂移调仓"""
        from src.backtest.engine.trade_simulator import TradeAction

        self._last_positions = list(positions)
        self._trading_day_count += 1
        self._last_eval_date = context.current_date

        # 重置跨方法协调标志
        self._pending_roll = False
        self._pending_rebalance = False
        self._pending_exit_to_cash = False

        cfg = self._ensure_config_loaded()
        signals: List[TradeSignal] = []

        leaps_positions = self._get_leaps_positions(positions)

        if not leaps_positions:
            # 无持仓，不需要评估
            return signals

        # 1. 计算 SMA 信号
        invested = self._compute_sma_signal(context, data_provider)


        # 2. SMA 翻空 → 清仓所有 LEAPS
        if not invested:
            self._pending_exit_to_cash = True
            for pos in leaps_positions:
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason="SMA exit: price below SMA, moving to cash",
                        alert_type="sma_exit",
                        position_id=pos.position_id,
                        priority="high",
                    )
                )
            logger.info(f"SMA EXIT: closing {len(leaps_positions)} LEAPS positions")
            return signals

        # 3. DTE ≤ roll_dte → 滚仓
        # TODO，滚仓怎么没有OPEN只有CLOSE？ 而且滚仓有专门的TradeAction.ROLL.
        for pos in leaps_positions:
            if pos.dte is not None and pos.dte <= cfg.roll_dte_threshold:
                self._pending_roll = True
                signals.append(
                    TradeSignal(
                        action=TradeAction.CLOSE,
                        symbol=pos.symbol,
                        quantity=-(pos.quantity or 0),
                        reason=f"Roll trigger: DTE={pos.dte} <= {cfg.roll_dte_threshold}",
                        alert_type="roll_dte",
                        position_id=pos.position_id,
                        priority="normal",
                    )
                )
                logger.info(f"ROLL: closing {pos.symbol} DTE={pos.dte}")

        # 4. DTE ≤ 5 安全网: 强制平仓 (防止被 executor 到期处理)
        for pos in leaps_positions:
            if pos.dte is not None and pos.dte <= 5:
                already_closing = any(s.position_id == pos.position_id for s in signals)
                if not already_closing:
                    self._pending_roll = True
                    signals.append(
                        TradeSignal(
                            action=TradeAction.CLOSE,
                            symbol=pos.symbol,
                            quantity=-(pos.quantity or 0),
                            reason=f"Safety net: DTE={pos.dte} <= 5, force close",
                            alert_type="roll_dte",
                            position_id=pos.position_id,
                            priority="high",
                        )
                    )

        # 5. 杠杆漂移检查 — 暂时关闭
        # 频繁 rebalance 交易成本高，且 LEAPS 深度 ITM delta 变化小，暂不启用
        # if not self._pending_roll and self._is_decision_day():
        #     actual_lev = self._compute_actual_leverage(leaps_positions, context)
        #     if abs(actual_lev - cfg.target_leverage) > cfg.leverage_drift_threshold:
        #         self._pending_rebalance = True
        #         for pos in leaps_positions:
        #             signals.append(
        #                 TradeSignal(
        #                     action=TradeAction.CLOSE,
        #                     symbol=pos.symbol,
        #                     quantity=-(pos.quantity or 0),
        #                     reason=f"Rebalance: leverage={actual_lev:.2f} vs target={cfg.target_leverage:.1f}",
        #                     alert_type="leverage_rebalance",
        #                     position_id=pos.position_id,
        #                     priority="normal",
        #                 )
        #             )
        #         logger.info(
        #             f"REBALANCE: actual leverage {actual_lev:.2f} drifted from target {cfg.target_leverage:.1f}"
        #         )

        return signals

    # ==========================================
    # 阶段 2: find_opportunities — 完全 override
    # ==========================================
    def find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        """寻找 LEAPS Call 开仓机会"""
        cfg = self._ensure_config_loaded()

        # 当无持仓时，executor 跳过 evaluate_positions 调用，
        # 导致 _trading_day_count 不递增、_last_positions 残留旧数据。
        # 在此补偿：如果今天 evaluate_positions 没有被调用，手动推进状态。
        if self._last_eval_date != context.current_date:
            self._trading_day_count += 1
            self._last_positions = []
            self._pending_roll = False
            self._pending_rebalance = False
            self._pending_exit_to_cash = False

        # 1. 计算 SMA 信号 (可能已缓存)
        invested = self._compute_sma_signal(context, data_provider)

        # 2. 判断是否需要新建仓
        need_entry = False
        if self._pending_roll or self._pending_rebalance:
            need_entry = True
        elif invested and not self._get_leaps_positions(self._last_positions) and self._is_decision_day():
            # 信号看多 + 无持仓 + decision day
            need_entry = True

        if not need_entry:
            return []

        # 3. 对每个 symbol 选取最优 LEAPS Call
        opportunities: List[ContractOpportunity] = []

        for symbol in symbols:
            spot = context.underlying_prices.get(symbol)
            if not spot or spot <= 0:
                continue

            target_strike = spot * cfg.target_moneyness

            # 获取 option chain
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

            opp = ContractOpportunity(
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
                annual_roc=0.0,  # not applicable for buyer strategy
                metadata={"source_strategy_type": "long_call", "leaps_sma_timing": True},
            )
            opportunities.append(opp)
            logger.info(
                f"LEAPS opportunity: {symbol} strike={contract.strike_price:.0f} "
                f"DTE={dte} delta={greeks.delta if greeks else '?':.2f} mid={mid:.2f}"
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
        """按目标杠杆计算 LEAPS Call 合约数量"""
        from src.backtest.engine.trade_simulator import TradeAction
        from src.data.models.option import OptionContract, OptionQuote, OptionType, Greeks

        if not candidates:
            return []

        cfg = self._ensure_config_loaded()
        nlv = account.nlv
        cash = account.cash
        self._last_nlv = nlv

        if nlv <= 0 or cash <= 0:
            return []

        signals: List[TradeSignal] = []

        for opp in candidates:
            spot = opp.underlying_price or context.underlying_prices.get(opp.symbol, 0)
            delta = opp.delta
            mid = opp.mid_price
            lot_size = opp.lot_size or 100

            if not spot or not delta or delta <= 0 or not mid or mid <= 0:
                logger.warning(f"Skipping {opp.symbol}: missing spot/delta/mid")
                continue

            # 合约数量 = target_leverage * NLV / (delta * lot_size * spot)
            contracts = math.floor(
                cfg.target_leverage * nlv / (delta * lot_size * spot)
            )

            # 资金约束: premium * contracts * lot_size <= available_capital
            # Roll/Rebalance 场景: 旧仓位尚未平仓，cash 偏低，用 NLV 作为可用资金
            # 普通开仓场景: 用 cash 作为可用资金
            if self._pending_roll or self._pending_rebalance:
                available_capital = cfg.max_capital_pct * nlv
            else:
                available_capital = cfg.max_capital_pct * cash
            if mid * lot_size > 0:
                max_contracts = math.floor(available_capital / (mid * lot_size))
                contracts = min(contracts, max_contracts)

            if contracts <= 0:
                logger.info(f"Sizing: {opp.symbol} contracts=0, skipping")
                continue

            # 构建 OptionQuote
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
            total_premium = contracts * mid * lot_size

            signals.append(
                TradeSignal(
                    action=TradeAction.OPEN,
                    symbol=opp.symbol,
                    quantity=contracts,  # positive = BUY
                    reason=(
                        f"LEAPS entry: {contracts}x strike={opp.strike:.0f} DTE={opp.dte} "
                        f"delta={delta:.2f} leverage={actual_leverage:.2f}x premium=${total_premium:,.0f}"
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
