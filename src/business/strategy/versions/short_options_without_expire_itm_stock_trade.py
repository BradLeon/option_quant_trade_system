import logging
from typing import List, Any

from src.business.strategy.base import BaseOptionStrategy
from src.business.strategy.models import MarketContext, TradeSignal
from src.business.screening.models import ContractOpportunity
from src.business.monitoring.models import PositionData

logger = logging.getLogger(__name__)


class ShortOptionsWithoutExpireItmStockTrade(BaseOptionStrategy):
    """Short Options without ITM assignment

    特点：
    - 开仓：完全继承 BaseOptionStrategy 的配置驱动逻辑，不再硬编码跳过大盘风控。
    - 平仓：
        继承 BaseOptionStrategy 的配置驱动逻辑。
        额外增加：对于即将在当天到期 (DTE=0) 且为 ITM 的期权，
        直接市价平仓以避免股票行权交收。
    """

    @property
    def name(self) -> str:
        return "short_options_without_expire_itm_stock_trade"

    def get_monitoring_overrides(self) -> dict | None:
        """不接股版：启用 OTM% + 严格 P&L 止损"""
        return {
            "otm_pct": {"enabled": True, "red_below": 0.02},  # OTM < 2% 强制平仓
            "pnl": {"enabled": True, "red_below": -1.0},       # 亏损 > 100% 止损
        }

    # ==========================
    # 阶段 1：平仓监控与风控决策
    # ==========================
    def evaluate_positions(
        self, positions: List[PositionData], context: MarketContext, data_provider: Any = None
    ) -> List[TradeSignal]:
        """Override V9: 继承基类的监控逻辑，但追加 DTE=0 ITM 强制平仓逻辑"""
        
        # 1. 首先运行基类的标准评估逻辑 (包含早期止盈/止损以及缓存的 Pipeline)
        signals = super().evaluate_positions(positions, context, data_provider)
        
        from src.backtest.engine.trade_simulator import TradeAction

        # 2. 针对即将到期 (DTE=0) 的 ITM 期权，触发市价平仓 (防御行权)
        # 获取已经被基类标记为平仓的仓位 ID (避免重复发信号)
        existing_close_ids = {s.position_id for s in signals if s.action == TradeAction.CLOSE}

        for pos in positions:
            if pos.position_id in existing_close_ids:
                continue
                
            if pos.dte is not None and pos.dte <= 0:
                is_itm = False
                if pos.option_type == "put" and pos.underlying_price is not None and pos.strike is not None and pos.underlying_price < pos.strike:
                    is_itm = True
                elif pos.option_type == "call" and pos.underlying_price is not None and pos.strike is not None and pos.underlying_price > pos.strike:
                    is_itm = True

                if is_itm:
                    signals.append(
                        TradeSignal(
                            action=TradeAction.CLOSE,
                            symbol=pos.symbol,
                            quantity=-pos.quantity,
                            reason="close_itm_at_expiration",
                            position_id=pos.position_id,
                            priority="high"
                        )
                    )

        return signals

    # ==========================
    # 阶段 2：开仓条件与标的筛选
    # ==========================
    # 完全继承 BaseOptionStrategy.find_opportunities 的默认逻辑。
    # 因为配置已经对齐，不再需要在此处 hardcode skip_market_check=True 


    # 完全继承 BaseOptionStrategy.generate_entry_signals 的默认逻辑。
    # 因为 V6 同样是分配 25% 仓位买入 AnnROC 最高的合约。
