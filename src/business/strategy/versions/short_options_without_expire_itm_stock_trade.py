import logging
from typing import List

from src.business.strategy.base import BaseTradeStrategy
from src.business.strategy.models import MarketContext, TradeSignal

logger = logging.getLogger(__name__)


class ShortOptionsWithoutExpireItmStockTrade(BaseTradeStrategy):
    """Short Options without ITM assignment

    特点：
    - 开仓：完全继承 BaseTradeStrategy 的配置驱动逻辑，不再硬编码跳过大盘风控。
    - 平仓：
        继承 BaseTradeStrategy 的配置驱动逻辑。
        额外增加：对于即将在当天到期 (DTE=0) 且为 ITM 的期权，
        直接市价平仓以避免股票行权交收。
        通过 filter_close_signals() hook 实现。
    """

    @property
    def name(self) -> str:
        return "short_options_without_expire_itm_stock_trade"

    def get_monitoring_overrides(self) -> dict | None:
        """不接股版：关闭 OTM% 和 P&L 平仓"""
        return {
            "otm_pct": {"enabled": False, "red_below": 0.02},  # 关闭 OTM 强制平仓
            "pnl": {"enabled": False, "red_below": -1.0},       # 关闭 亏损止损
            # win_probability 不再 override，使用 YAML 配置的 enabled: true
            "technical_close": {"enabled": False},               # 不接股版也关闭技术面平仓（保持与关闭screening一致）
        }

    # ==========================
    # 平仓信号后处理 Hook
    # ==========================
    def filter_close_signals(self, signals: List[TradeSignal], context: MarketContext) -> List[TradeSignal]:
        """追加 DTE=0 ITM 强制平仓逻辑（防御行权）

        在基类 monitoring pipeline 生成信号后，检查是否有即将到期的 ITM 期权未被覆盖，
        为其追加强制平仓信号。
        """
        from src.backtest.engine.trade_simulator import TradeAction

        # 获取已经被标记为平仓的仓位 ID (避免重复发信号)
        existing_close_ids = {s.position_id for s in signals if s.action == TradeAction.CLOSE}

        for pos in self._last_positions:
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
                            alert_type="dte_warning",
                            position_id=pos.position_id,
                            priority="high"
                        )
                    )

        return signals

    # ==========================
    # 阶段 2：开仓条件与标的筛选
    # ==========================
    # 完全继承 BaseTradeStrategy.find_opportunities 的默认逻辑。
    # 因为配置已经对齐，不再需要在此处 hardcode skip_market_check=True

    # 完全继承 BaseTradeStrategy.generate_entry_signals 的默认逻辑。
    # 因为 V6 同样是分配 25% 仓位买入 AnnROC 最高的合约。
