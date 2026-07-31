"""Live Daily Snapshot — 实盘/Paper Trading 每日组合快照

记录每次策略执行时的组合状态，用于绩效追踪。
数据来源: LiveExecutionResult (plan() 阶段从 IBKR 获取的真实数据)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class LiveDailySnapshot:
    """每日组合快照 (实盘/Paper Trading)"""

    date: date
    strategy_name: str
    account_type: str  # "paper" | "live"
    symbols: list[str]

    # 账户状态 (from PortfolioState)
    nlv: float
    cash: float
    margin_used: float
    positions_value: float  # nlv - cash
    unrealized_pnl: float
    position_count: int

    # 当日活动 (from LiveExecutionResult)
    signals_generated: int = 0
    signals_after_risk: int = 0
    orders_executed: int = 0

    # 持仓明细 (PositionView 序列化)
    positions: list[dict] = field(default_factory=list)

    # Market context
    vix: float | None = None
    risk_free_rate: float | None = None

    # Timestamp
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "strategy_name": self.strategy_name,
            "account_type": self.account_type,
            "symbols": self.symbols,
            "nlv": self.nlv,
            "cash": self.cash,
            "margin_used": self.margin_used,
            "positions_value": self.positions_value,
            "unrealized_pnl": self.unrealized_pnl,
            "position_count": self.position_count,
            "signals_generated": self.signals_generated,
            "signals_after_risk": self.signals_after_risk,
            "orders_executed": self.orders_executed,
            "positions": self.positions,
            "vix": self.vix,
            "risk_free_rate": self.risk_free_rate,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveDailySnapshot:
        return cls(
            date=date.fromisoformat(data["date"]),
            strategy_name=data["strategy_name"],
            account_type=data["account_type"],
            symbols=data.get("symbols", []),
            nlv=data["nlv"],
            cash=data["cash"],
            margin_used=data["margin_used"],
            positions_value=data["positions_value"],
            unrealized_pnl=data["unrealized_pnl"],
            position_count=data["position_count"],
            signals_generated=data.get("signals_generated", 0),
            signals_after_risk=data.get("signals_after_risk", 0),
            orders_executed=data.get("orders_executed", 0),
            positions=data.get("positions", []),
            vix=data.get("vix"),
            risk_free_rate=data.get("risk_free_rate"),
            recorded_at=data.get("recorded_at", ""),
        )

    @classmethod
    def from_execution_result(
        cls,
        result: Any,  # LiveExecutionResult
        strategy_name: str,
        symbols: list[str],
        account_type: str,
    ) -> LiveDailySnapshot:
        """从 LiveExecutionResult 构建快照。

        Args:
            result: LiveExecutionResult (plan() 的输出)
            strategy_name: 策略名称
            symbols: 标的列表
            account_type: "paper" | "live"
        """
        portfolio = result.portfolio_state
        market = result.market_snapshot

        # 序列化持仓
        positions_dicts: list[dict] = []
        total_unrealized = 0.0
        if portfolio and portfolio.positions:
            for pv in portfolio.positions:
                pos_dict: dict[str, Any] = {
                    "position_id": pv.position_id,
                    "symbol": pv.instrument.symbol,
                    "underlying": pv.instrument.underlying,
                    "type": pv.instrument.type.value,
                    "quantity": pv.quantity,
                    "entry_price": pv.entry_price,
                    "current_price": pv.current_price,
                    "unrealized_pnl": pv.unrealized_pnl,
                }
                if pv.is_option:
                    pos_dict["strike"] = pv.instrument.strike
                    pos_dict["expiry"] = (
                        pv.instrument.expiry.isoformat()
                        if pv.instrument.expiry
                        else None
                    )
                    pos_dict["right"] = (
                        pv.instrument.right.value if pv.instrument.right else None
                    )
                    pos_dict["dte"] = pv.dte
                    pos_dict["iv"] = pv.iv
                if pv.delta is not None:
                    pos_dict["delta"] = pv.delta
                positions_dicts.append(pos_dict)
                total_unrealized += pv.unrealized_pnl

        nlv = portfolio.nlv if portfolio else 0.0
        cash = portfolio.cash if portfolio else 0.0
        margin_used = portfolio.margin_used if portfolio else 0.0
        position_count = portfolio.position_count if portfolio else 0

        return cls(
            date=market.date if market else date.today(),
            strategy_name=strategy_name,
            account_type=account_type,
            symbols=symbols,
            nlv=nlv,
            cash=cash,
            margin_used=margin_used,
            positions_value=nlv - cash,
            unrealized_pnl=total_unrealized,
            position_count=position_count,
            signals_generated=result.signals_generated,
            signals_after_risk=result.signals_after_risk,
            orders_executed=len(result.orders),
            positions=positions_dicts,
            vix=market.vix if market else None,
            risk_free_rate=market.risk_free_rate if market else None,
            recorded_at=datetime.now().isoformat(),
        )
