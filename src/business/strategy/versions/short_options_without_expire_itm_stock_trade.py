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
    - 开仓：由配置决定，不限制趋势和 VIX。
    - 平仓：
        由配置决定。对于即将在当天到期 (DTE=0) 且为 ITM 的期权，
        直接市价平仓以避免股票行权交收。
    """

    @property
    def name(self) -> str:
        return "short_options_without_expire_itm_stock_trade"

    # ==========================
    # 阶段 1：平仓监控与风控决策
    # ==========================
    def evaluate_positions(
        self, positions: List[PositionData], context: MarketContext
    ) -> List[TradeSignal]:
        """Override V9: 取消提前止盈，仅保留绝对止损"""
        signals = []
        from src.backtest.engine.trade_simulator import TradeAction
        from src.business.monitoring.pipeline import MonitoringPipeline
        from src.business.config.monitoring_config import MonitoringConfig

        # 使用注入的配置或从 YAML 加载
        config = self._monitoring_config or MonitoringConfig.load(strategy_name=self.name)

        # 运行监控管道
        pipeline = MonitoringPipeline(config)
        vix = context.vix_value

        result = pipeline.run(
            positions=positions,
            vix=vix,
            as_of_date=context.current_date,
        )

        for suggestion in result.suggestions:
            if suggestion.action.value in ["close", "roll"]:
                pos = next((p for p in positions if p.symbol == suggestion.symbol), None)
                if pos:
                    action_enum = TradeAction.CLOSE if suggestion.action.value == "close" else TradeAction.ROLL

                    roll_to_expiry = suggestion.metadata.get("suggested_expiry") if action_enum == TradeAction.ROLL else None
                    roll_to_strike = suggestion.metadata.get("suggested_strike") if action_enum == TradeAction.ROLL else None

                    signals.append(
                        TradeSignal(
                            action=action_enum,
                            symbol=suggestion.symbol,
                            quantity=-pos.quantity,
                            reason=suggestion.reason,
                            position_id=pos.position_id,  # 设置 position_id 用于交易执行
                            roll_to_expiry=roll_to_expiry,
                            roll_to_strike=roll_to_strike,
                            priority="high" if suggestion.urgency.value == "immediate" else "normal"
                        )
                    )

        # 针对即将到期 (DTE=0) 的 ITM 期权，触发市价平仓
        for pos in positions:
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
                            position_id=pos.position_id,  # 设置 position_id 用于交易执行
                            priority="high"
                        )
                    )

        return signals

    # ==========================
    # 阶段 2：开仓条件与标的筛选
    # ==========================
    def find_opportunities(
        self, symbols: List[str], data_provider: Any, context: MarketContext
    ) -> List[ContractOpportunity]:
        """Override V9: 取消大盘趋势和 VIX 验证的极简筛选"""
        from src.business.config.screening_config import ScreeningConfig
        from src.business.screening.pipeline import ScreeningPipeline
        from src.business.screening.models import MarketType
        from src.engine.models.enums import StrategyType

        # 使用注入的配置或从 YAML 加载
        config = self._screening_config or ScreeningConfig.load(strategy_name=self.name)

        pipeline = ScreeningPipeline(config, data_provider)
        try:
            # skip_market_check=True 跳过大盘级别的过滤
            result = pipeline.run(
                symbols=symbols,
                market_type=MarketType.US,
                strategy_type=StrategyType.SHORT_PUT,
                skip_market_check=True
            )
            if result and result.confirmed:
                return result.confirmed
        except Exception as e:
            logger.error(f"Strategy {self.name} screening failed: {e}")

        return []

    # ==========================
    # 阶段 3：建仓信号生成
    # ==========================
    # 完全继承 BaseOptionStrategy.generate_entry_signals 的默认逻辑。
    # 因为 V6 同样是分配 25% 仓位买入 AnnROC 最高的合约。
