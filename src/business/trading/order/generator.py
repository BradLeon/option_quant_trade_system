"""
Order Generator - 订单生成器

从 TradingDecision 生成 OrderRequest。

支持的决策类型:
- OPEN: 生成单个开仓订单
- CLOSE: 生成单个平仓订单
- ROLL: 生成两个订单 (平仓 + 开仓)
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
from src.data.utils.symbol_formatter import SymbolFormatter

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
            con_id=decision.con_id,  # IBKR contract ID
            side=side,
            order_type=order_type,
            quantity=abs(decision.quantity),
            limit_price=decision.limit_price,
            time_in_force=self._config.default_time_in_force,
            contract_multiplier=decision.contract_multiplier,
            currency=decision.currency,
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

        Decision.quantity 约定:
        - 正数: 买入 (BUY to open / BUY to close)
        - 负数: 卖出 (SELL to open / SELL to close)

        OrderRequest.quantity 始终为正数，方向由 side 决定。

        规则 (对所有 decision_type 统一适用):
        - quantity < 0 -> SELL
        - quantity > 0 -> BUY

        示例:
        - OPEN 卖 Put: decision.quantity = -1 -> SELL
        - CLOSE 买回 Put (原空头 -2): decision.quantity = 2 -> BUY
        - CLOSE 卖出股票 (原多头 +100): decision.quantity = -100 -> SELL
        """
        # 统一规则: quantity 的符号决定方向
        return OrderSide.SELL if decision.quantity < 0 else OrderSide.BUY

    def _determine_order_type(self, decision: TradingDecision) -> OrderType:
        """确定订单类型

        当前支持: MARKET, LIMIT
        预留类型: STOP, STOP_LIMIT (未实现)

        规则:
        - price_type == "market" -> MARKET
        - limit_price 存在 -> LIMIT
        - 默认 -> MARKET (更安全，避免限价单挂单不成交)
        """
        if decision.price_type == "market":
            return OrderType.MARKET
        if decision.limit_price is not None:
            return OrderType.LIMIT
        return OrderType.MARKET  # 无限价时默认市价单

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

    def generate_roll(self, decision: TradingDecision) -> list[OrderRequest]:
        """从 ROLL 决策生成两个订单

        展期操作 = 平仓当前合约 + 开仓新合约

        Args:
            decision: ROLL 类型的交易决策
                - symbol/expiry/strike: 当前合约信息
                - roll_to_expiry: 新到期日
                - roll_to_strike: 新行权价 (None 表示保持不变)
                - quantity: 平仓数量 (正数表示买入平仓)

        Returns:
            [close_order, open_order] - 平仓订单在前，开仓订单在后

        Raises:
            ValueError: 决策类型不是 ROLL 或缺少展期参数
        """
        if decision.decision_type != DecisionType.ROLL:
            raise ValueError(f"Expected ROLL decision, got {decision.decision_type}")

        if not decision.roll_to_expiry:
            raise ValueError("ROLL decision missing roll_to_expiry")

        # ========================================
        # 1. 平仓订单 (BUY to close 当前合约)
        # ========================================
        close_order_id = self._generate_order_id()

        # 平仓数量 = decision.quantity (正数，表示 BUY to close)
        close_quantity = abs(decision.quantity)

        close_order = OrderRequest(
            order_id=close_order_id,
            decision_id=decision.decision_id,
            symbol=decision.symbol,
            asset_class=AssetClass.OPTION,
            underlying=decision.underlying,
            option_type=decision.option_type,
            strike=decision.strike,
            expiry=decision.expiry,
            trading_class=decision.trading_class,
            con_id=decision.con_id,  # IBKR contract ID
            side=OrderSide.BUY,  # BUY to close
            order_type=OrderType.MARKET,  # 平仓用市价单确保成交
            quantity=close_quantity,
            limit_price=None,
            time_in_force=self._config.default_time_in_force,
            contract_multiplier=decision.contract_multiplier,
            currency=decision.currency,
            broker=decision.broker,
            account_type="paper",
            status=OrderStatus.PENDING_VALIDATION,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            context={
                "decision_type": "roll_close",
                "source": decision.source.value,
                "priority": decision.priority.value,
                "reason": f"ROLL: 平仓 {decision.expiry} 合约",
                "roll_pair": "close",
            },
        )

        # ========================================
        # 2. 开仓订单 (SELL to open 新合约)
        # ========================================
        open_order_id = self._generate_order_id()

        # 新合约参数
        new_strike = decision.roll_to_strike or decision.strike  # 默认保持行权价不变
        new_expiry = decision.roll_to_expiry

        # 构建新合约 symbol
        new_symbol = self._build_roll_symbol(
            underlying=decision.underlying,
            expiry=new_expiry,
            strike=new_strike,
            option_type=decision.option_type,
        )

        open_order = OrderRequest(
            order_id=open_order_id,
            decision_id=decision.decision_id,
            symbol=new_symbol,
            asset_class=AssetClass.OPTION,
            underlying=decision.underlying,
            option_type=decision.option_type,
            strike=new_strike,
            expiry=new_expiry,
            trading_class=decision.trading_class,
            side=OrderSide.SELL,  # SELL to open
            order_type=OrderType.LIMIT if decision.roll_credit else OrderType.MARKET,
            quantity=close_quantity,  # 保持数量一致
            limit_price=decision.roll_credit,  # 用 roll_credit 作为限价
            time_in_force=self._config.default_time_in_force,
            contract_multiplier=decision.contract_multiplier,
            currency=decision.currency,
            broker=decision.broker,
            account_type="paper",
            status=OrderStatus.PENDING_VALIDATION,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            context={
                "decision_type": "roll_open",
                "source": decision.source.value,
                "priority": decision.priority.value,
                "reason": f"ROLL: 开仓 {new_expiry} 合约",
                "roll_pair": "open",
                "roll_credit": decision.roll_credit,
            },
        )

        logger.info(
            f"Roll orders generated from decision {decision.decision_id}: "
            f"close={close_order_id} ({decision.expiry}), "
            f"open={open_order_id} ({new_expiry})"
        )

        return [close_order, open_order]

    def _build_roll_symbol(
        self,
        underlying: str,
        expiry: str,
        strike: float,
        option_type: str,
    ) -> str:
        """构建展期新合约的 symbol

        格式: UNDERLYING YYMMDDCP00STRIKE (OCC 格式)
        示例: MSFT 250228P00380000
        """
        # 转换日期格式: YYYY-MM-DD -> YYMMDD
        expiry_short = expiry.replace("-", "")[2:]  # 2025-02-28 -> 250228

        # 期权类型: put -> P, call -> C
        opt_char = "P" if option_type == "put" else "C"

        # 行权价: 填充到 8 位 (整数部分 5 位 + 小数部分 3 位)
        strike_str = f"{int(strike * 1000):08d}"

        # 获取纯 underlying (去除 .HK 等后缀)
        pure_underlying = underlying.split(".")[0] if "." in underlying else underlying

        return f"{pure_underlying} {expiry_short}{opt_char}{strike_str}"
