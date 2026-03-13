"""Cash Sweep Mixin — 闲置现金自动买入/卖出货币基金 ETF.

将策略中的闲置现金投入 SHV/BIL/SGOV 等短期国债 ETF，
在需要现金时（LEAPS entry/roll）自动卖出 ETF 释放资金。

回测和实盘共用同一套信号逻辑:
- 回测: Signal → TradeSimulator → 模拟 SHV 买卖
- 实盘: Signal → LiveSignalConverter → IBKR 委托单
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.strategy.models import MarketSnapshot, PortfolioState, PositionView, Signal

# 现金等价物 ETF 列表 — 用于 PositionView.is_cash_equivalent 判断
CASH_EQUIVALENT_SYMBOLS: frozenset[str] = frozenset({"SHV", "BIL", "SGOV", "SCHO"})


@dataclass
class CashSweepConfig:
    """Cash sweep configuration."""

    enabled: bool = False
    instrument_symbol: str = "SHV"  # iShares Short Treasury Bond ETF
    min_cash_buffer_pct: float = 0.05  # 保留 5% NLV 裸现金
    sweep_threshold: float = 10_000  # 闲置 > $10k 才买入
    min_trade_size: int = 10  # 最少交易 10 股


class CashSweepMixin:
    """Mixin: 任何策略继承后即可启用现金 ETF 自动管理.

    Usage:
        class MyStrategy(BacktestStrategy, CashSweepMixin):
            def __init__(self, config):
                super().__init__(config)
                self._cash_sweep_config = config.cash_sweep_config
    """

    _cash_sweep_config: CashSweepConfig

    def compute_cash_sweep_exits(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        cash_needed: float = 0,
    ) -> list[Signal]:
        """卖出现金 ETF 释放现金。

        触发条件: raw cash < min_buffer 或策略需要额外 cash_needed。
        """
        from src.strategy.models import Signal, SignalType

        cfg = self._cash_sweep_config
        if not cfg.enabled:
            return []

        etf_positions = self._get_cash_etf_positions(portfolio)
        if not etf_positions:
            return []

        min_buffer = portfolio.nlv * cfg.min_cash_buffer_pct
        available_cash = portfolio.cash - min_buffer  # 可用于策略的现金
        cash_deficit = max(0, cash_needed - available_cash)  # 还缺多少需要卖 ETF
        if cash_deficit <= 0:
            return []

        signals: list[Signal] = []
        remaining = cash_deficit
        for pos in etf_positions:
            if remaining <= 0:
                break
            etf_price = market.get_price_or_zero(pos.instrument.underlying)
            if etf_price <= 0:
                continue
            shares_to_sell = min(pos.quantity, math.ceil(remaining / etf_price))
            if shares_to_sell > 0:
                signals.append(Signal(
                    type=SignalType.EXIT,
                    instrument=pos.instrument,
                    target_quantity=-shares_to_sell,
                    reason=f"Cash sweep sell: {shares_to_sell}sh {pos.instrument.underlying} "
                           f"(need ${cash_deficit:,.0f})",
                    position_id=pos.position_id,
                    priority=1,  # 低优先级 exit（先处理策略本身的 exit）
                    metadata={"is_cash_equivalent": True},
                ))
                remaining -= shares_to_sell * etf_price

        return signals

    def compute_cash_sweep_entries(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        cash_reserved: float = 0,
    ) -> list[Signal]:
        """买入现金 ETF 投资闲置现金。

        Args:
            cash_reserved: 已预留给其他入场信号的现金（不参与 sweep）。

        触发条件: idle_cash = cash - NLV*buffer_pct - cash_reserved > sweep_threshold。
        """
        from src.strategy.models import (
            Instrument,
            InstrumentType,
            Signal,
            SignalType,
        )

        cfg = self._cash_sweep_config
        if not cfg.enabled:
            return []

        etf_price = market.get_price_or_zero(cfg.instrument_symbol)
        if etf_price <= 0:
            return []

        min_buffer = portfolio.nlv * cfg.min_cash_buffer_pct
        idle_cash = portfolio.cash - min_buffer - cash_reserved

        if idle_cash < cfg.sweep_threshold:
            return []

        shares = math.floor(idle_cash / etf_price)
        if shares < cfg.min_trade_size:
            return []

        instrument = Instrument(
            type=InstrumentType.STOCK,
            underlying=cfg.instrument_symbol,
            lot_size=1,
        )
        return [Signal(
            type=SignalType.ENTRY,
            instrument=instrument,
            target_quantity=shares,
            reason=f"Cash sweep buy: {shares}sh {cfg.instrument_symbol} "
                   f"@ ${etf_price:.2f} (idle=${idle_cash:,.0f})",
            quote_price=etf_price,
            priority=-1,  # 最低优先级 — 在所有策略 entry 之后
            metadata={"is_cash_equivalent": True},
        )]

    def _get_cash_etf_positions(self, portfolio: PortfolioState) -> list[PositionView]:
        """获取当前持有的现金 ETF 仓位。"""
        sym = self._cash_sweep_config.instrument_symbol
        return [
            p for p in portfolio.positions
            if p.instrument.is_stock and p.instrument.underlying == sym
        ]
