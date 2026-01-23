"""
Futu Trading Provider - 富途证券交易提供者

⚠️  CRITICAL: 仅支持 Paper Trading (模拟账户)

实现约束:
1. 只使用 TrdEnv.SIMULATE (模拟环境)
2. 每次操作前验证账户类型
3. 交易密码使用 MD5 加密
"""

import hashlib
import logging
import os
from datetime import datetime
from threading import Lock
from typing import Any

from dotenv import load_dotenv

from src.business.trading.models.order import (
    AssetClass,
    OrderRequest,
    OrderSide,
    OrderType,
)
from src.business.trading.models.trading import (
    AccountTypeError,
    CancelResult,
    OrderQueryResult,
    TradingAccountType,
    TradingProviderError,
    TradingResult,
)
from src.business.trading.provider.base import TradingProvider

logger = logging.getLogger(__name__)

# Try to import futu
try:
    from futu import (
        OpenSecTradeContext,
        RET_OK,
        TrdEnv,
        TrdMarket,
        TrdSide,
        OrderType as FutuOrderType,
        OrderStatus as FutuOrderStatus,
    )

    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    logger.warning("futu-api not installed. Futu trading provider will be unavailable.")


class FutuTradingProvider(TradingProvider):
    """富途交易提供者

    ⚠️  CRITICAL: 仅支持 Paper Trading

    环境约束:
    - 只使用 TrdEnv.SIMULATE (模拟环境)
    - TrdEnv.REAL 禁止使用

    Usage:
        with FutuTradingProvider() as provider:
            result = provider.submit_order(order)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        account_type: TradingAccountType = TradingAccountType.PAPER,
    ) -> None:
        """初始化富途交易提供者

        Args:
            host: OpenD 主机地址
            port: OpenD 端口
            account_type: 账户类型 (必须是 PAPER)

        Raises:
            AccountTypeError: 账户类型不是 PAPER
        """
        super().__init__(account_type)

        load_dotenv()

        self._host = host or os.getenv("FUTU_HOST", "127.0.0.1")
        self._port = port or int(os.getenv("FUTU_PORT", "11111"))
        self._trade_password = os.getenv("FUTU_TRADE_PASSWORD", "")

        self._trd_ctx: Any = None
        self._connected = False
        self._lock = Lock()

        # 计算交易密码的 MD5
        self._password_md5 = ""
        if self._trade_password:
            self._password_md5 = hashlib.md5(
                self._trade_password.encode()
            ).hexdigest()

        logger.info(
            f"FutuTradingProvider initialized: "
            f"host={self._host}, port={self._port} (PAPER ONLY - SIMULATE)"
        )

    @property
    def name(self) -> str:
        """提供者名称"""
        return "futu"

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected and self._trd_ctx is not None

    def connect(self) -> None:
        """建立连接

        Raises:
            TradingProviderError: 连接失败
        """
        if not FUTU_AVAILABLE:
            raise TradingProviderError("futu-api is not installed")

        with self._lock:
            if self._connected:
                return

            try:
                # 创建交易上下文 - 强制使用 SIMULATE 环境
                self._trd_ctx = OpenSecTradeContext(
                    host=self._host,
                    port=self._port,
                    filter_trdmarket=TrdMarket.US,  # 默认美股，可以后续调整
                )

                # 解锁交易 (使用 SIMULATE 环境)
                if self._password_md5:
                    ret, data = self._trd_ctx.unlock_trade(
                        password_md5=self._password_md5,
                        is_unlock=True,
                    )
                    if ret != RET_OK:
                        raise TradingProviderError(f"Failed to unlock trade: {data}")

                self._connected = True
                logger.info(
                    f"Connected to Futu OpenD: {self._host}:{self._port} (SIMULATE)"
                )

            except Exception as e:
                self._connected = False
                if self._trd_ctx:
                    self._trd_ctx.close()
                    self._trd_ctx = None
                raise TradingProviderError(f"Failed to connect: {e}")

    def disconnect(self) -> None:
        """断开连接"""
        with self._lock:
            if self._trd_ctx:
                try:
                    self._trd_ctx.close()
                except Exception as e:
                    logger.warning(f"Error disconnecting: {e}")
                finally:
                    self._trd_ctx = None
                    self._connected = False
                    logger.info("Disconnected from Futu")

    def submit_order(self, order: OrderRequest) -> TradingResult:
        """提交订单

        Args:
            order: 订单请求

        Returns:
            TradingResult: 交易结果
        """
        # 验证 Paper 账户
        self._validate_paper_account()

        if order.account_type != "paper":
            return TradingResult.failure_result(
                internal_order_id=order.order_id,
                error_code="ACCOUNT_TYPE_ERROR",
                error_message=f"Order account_type must be 'paper', got '{order.account_type}'",
            )

        if not self.is_connected:
            return TradingResult.failure_result(
                internal_order_id=order.order_id,
                error_code="NOT_CONNECTED",
                error_message="Not connected to Futu",
            )

        try:
            # 转换参数
            code = self._convert_symbol(order)
            price = order.limit_price or 0
            qty = abs(order.quantity)

            # 买卖方向
            trd_side = TrdSide.BUY if order.side == OrderSide.BUY else TrdSide.SELL

            # 订单类型
            if order.order_type == OrderType.MARKET:
                order_type = FutuOrderType.MARKET
            else:
                order_type = FutuOrderType.NORMAL  # 限价单

            # 提交订单 (使用 SIMULATE 环境)
            ret, data = self._trd_ctx.place_order(
                price=price,
                qty=qty,
                code=code,
                trd_side=trd_side,
                order_type=order_type,
                trd_env=TrdEnv.SIMULATE,  # ⚠️ 强制使用模拟环境
            )

            if ret != RET_OK:
                return TradingResult.failure_result(
                    internal_order_id=order.order_id,
                    error_code="PLACE_ORDER_FAILED",
                    error_message=str(data),
                )

            # 获取订单 ID
            broker_order_id = str(data["order_id"].iloc[0])

            logger.info(
                f"Order submitted: {order.order_id} -> broker_id={broker_order_id}, "
                f"symbol={code}, qty={qty}, side={trd_side}"
            )

            return TradingResult.success_result(
                internal_order_id=order.order_id,
                broker_order_id=broker_order_id,
            )

        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            return TradingResult.failure_result(
                internal_order_id=order.order_id,
                error_code="SUBMIT_ERROR",
                error_message=str(e),
            )

    def _convert_symbol(self, order: OrderRequest) -> str:
        """转换符号格式

        Futu 格式:
        - 美股: US.AAPL
        - 港股: HK.00700
        - 期权: 需要特殊处理
        """
        symbol = order.symbol

        # 如果是期权，需要构建期权代码
        if order.asset_class == AssetClass.OPTION:
            # Futu 期权代码格式较复杂，这里简化处理
            # 实际需要根据 Futu API 文档构建
            underlying = order.underlying or symbol
            expiry = order.expiry or ""
            strike = order.strike or 0
            opt_type = "C" if order.option_type == "call" else "P"

            # 格式: US.AAPL240119C150000 (示例)
            if expiry and "-" in expiry:
                expiry = expiry.replace("-", "")[2:]  # YYYYMMDD -> YYMMDD

            strike_str = f"{int(strike * 1000):06d}"
            code = f"US.{underlying}{expiry}{opt_type}{strike_str}"
            return code

        # 股票处理
        if not symbol.startswith(("US.", "HK.")):
            # 默认美股
            return f"US.{symbol}"

        return symbol

    def query_order(self, broker_order_id: str) -> OrderQueryResult:
        """查询订单状态"""
        if not self.is_connected:
            return OrderQueryResult.not_found(broker_order_id)

        try:
            ret, data = self._trd_ctx.order_list_query(
                order_id=broker_order_id,
                trd_env=TrdEnv.SIMULATE,
            )

            if ret != RET_OK or data.empty:
                return OrderQueryResult.not_found(broker_order_id)

            row = data.iloc[0]
            return OrderQueryResult(
                found=True,
                broker_order_id=broker_order_id,
                status=row.get("order_status", ""),
                filled_quantity=int(row.get("dealt_qty", 0)),
                remaining_quantity=int(row.get("qty", 0) - row.get("dealt_qty", 0)),
                average_price=row.get("dealt_avg_price"),
                last_updated=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Query order failed: {e}")
            return OrderQueryResult.not_found(broker_order_id)

    def cancel_order(self, broker_order_id: str) -> CancelResult:
        """取消订单"""
        self._validate_paper_account()

        if not self.is_connected:
            return CancelResult.failure_cancel(
                broker_order_id, "Not connected to Futu"
            )

        try:
            ret, data = self._trd_ctx.modify_order(
                modify_order_op=2,  # 2 = Cancel
                order_id=broker_order_id,
                qty=0,
                price=0,
                trd_env=TrdEnv.SIMULATE,
            )

            if ret != RET_OK:
                return CancelResult.failure_cancel(broker_order_id, str(data))

            logger.info(f"Order cancelled: broker_id={broker_order_id}")
            return CancelResult.success_cancel(broker_order_id)

        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return CancelResult.failure_cancel(broker_order_id, str(e))

    def get_open_orders(self) -> list[OrderQueryResult]:
        """获取所有未完成订单"""
        if not self.is_connected:
            return []

        try:
            ret, data = self._trd_ctx.order_list_query(
                trd_env=TrdEnv.SIMULATE,
            )

            if ret != RET_OK or data.empty:
                return []

            results = []
            for _, row in data.iterrows():
                status = row.get("order_status", "")
                # 只返回未完成的订单
                if status not in (
                    FutuOrderStatus.FILLED_ALL,
                    FutuOrderStatus.CANCELLED_ALL,
                    FutuOrderStatus.FAILED,
                ):
                    results.append(
                        OrderQueryResult(
                            found=True,
                            broker_order_id=str(row.get("order_id", "")),
                            status=status,
                            filled_quantity=int(row.get("dealt_qty", 0)),
                            remaining_quantity=int(
                                row.get("qty", 0) - row.get("dealt_qty", 0)
                            ),
                            average_price=row.get("dealt_avg_price"),
                            last_updated=datetime.now(),
                        )
                    )

            return results

        except Exception as e:
            logger.error(f"Get open orders failed: {e}")
            return []
