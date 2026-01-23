"""
Order Generator - 订单生成器

从 TradingDecision 生成 OrderRequest。
"""

import logging
import uuid
from datetime import datetime

from src.business.trading.config.order_config import OrderConfig
from src.business.trading.models.decision import DecisionType, TradingDecision
from src.business.trading.models.order import (
    AssetClass,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)


class OrderGenerator:
    """订单生成器

    将 TradingDecision 转换为 OrderRequest。

    Usage:
        generator = OrderGenerator()
        order = generator.generate(decision)
    """

    def __init__(self, config: OrderConfig | None = None) -> None:
        """初始化订单生成器

        Args:
            config: 订单配置
        """
        self._config = config or OrderConfig.load()

    def generate(self, decision: TradingDecision) -> OrderRequest:
        """从决策生成订单

        Args:
            decision: 交易决策

        Returns:
            OrderRequest: 订单请求
        """
        # 生成订单 ID
        order_id = self._generate_order_id()

        # 确定资产类型
        asset_class = AssetClass.OPTION if decision.option_type else AssetClass.STOCK

        # 确定买卖方向
        side = self._determine_side(decision)

        # 确定订单类型
        order_type = self._determine_order_type(decision)

        # 构建上下文信息
        context = self._build_context(decision)

        order = OrderRequest(
            order_id=order_id,
            decision_id=decision.decision_id,
            symbol=decision.symbol,
            asset_class=asset_class,
            underlying=decision.underlying,
            option_type=decision.option_type,
            strike=decision.strike,
            expiry=decision.expiry,
            trading_class=decision.trading_class,
            side=side,
            order_type=order_type,
            quantity=abs(decision.quantity),
            limit_price=decision.limit_price,
            time_in_force=self._config.default_time_in_force,
            broker=decision.broker,
            account_type="paper",  # 强制 paper
            status=OrderStatus.PENDING_VALIDATION,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            context=context,
        )

        logger.info(
            f"Order generated: {order_id} from decision {decision.decision_id}, "
            f"symbol={decision.symbol}, side={side.value}, qty={order.quantity}"
        )

        return order

    def _generate_order_id(self) -> str:
        """生成订单 ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique = uuid.uuid4().hex[:8]
        return f"ORD-{timestamp}-{unique}"

    def _determine_side(self, decision: TradingDecision) -> OrderSide:
        """确定买卖方向

        规则:
        - OPEN + quantity < 0 (卖出期权) -> SELL
        - OPEN + quantity > 0 (买入期权) -> BUY
        - CLOSE + 原持仓为空头 -> BUY (平仓)
        - CLOSE + 原持仓为多头 -> SELL (平仓)
        """
        # TODO 这里需要好好确定下，开仓信号对于卖期权，quantity是否负数。

        if decision.decision_type == DecisionType.OPEN:
            return OrderSide.SELL if decision.quantity < 0 else OrderSide.BUY
        elif decision.decision_type == DecisionType.CLOSE:
            # 平仓时方向相反
            # 如果原决策 quantity < 0 (空头持仓)，平仓需要买入
            return OrderSide.BUY if decision.quantity < 0 else OrderSide.SELL
        else:
            # ADJUST, ROLL 等根据数量判断
            return OrderSide.SELL if decision.quantity < 0 else OrderSide.BUY

    def _determine_order_type(self, decision: TradingDecision) -> OrderType:
        """确定订单类型"""
        # TODO 我看OrderType定义有四种，这里为什么只返回两种？
        # TODO 如果OrderType.LIMIT代表现价单，应该检查decision中的报价吧？ 默认返回市价单更合适吧？（因为decision中不用设置报价）
        if decision.price_type == "market":
            return OrderType.MARKET
        return OrderType.LIMIT

    def _build_context(self, decision: TradingDecision) -> dict:
        """构建订单上下文"""
        return {
            "decision_type": decision.decision_type.value,
            "source": decision.source.value,
            "priority": decision.priority.value,
            "reason": decision.reason,
            "trigger_alerts": decision.trigger_alerts,
            "price_type": decision.price_type,
        }
