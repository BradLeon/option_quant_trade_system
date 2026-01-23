"""
IBKR Trading Provider - Interactive Brokers 交易提供者

⚠️  CRITICAL: 仅支持 Paper Trading (模拟账户)

实现约束:
1. 只连接 4002 端口 (Paper Trading Gateway)
2. 验证账户 ID 以 "DU" 开头 (Paper 账户前缀)
3. 每次操作前验证账户类型
"""

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

# Try to import ib_async
try:
    from ib_async import IB, Contract, LimitOrder, MarketOrder, Option, Stock, Trade

    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    logger.warning("ib_async not installed. IBKR trading provider will be unavailable.")


class IBKRTradingProvider(TradingProvider):
    """IBKR 交易提供者

    ⚠️  CRITICAL: 仅支持 Paper Trading

    端口约束:
    - Paper Trading: 4002 (唯一允许的端口)
    - Live Trading: 4001 (禁止连接)

    账户约束:
    - 账户 ID 必须以 "DU" 开头 (Paper 账户前缀)

    Usage:
        with IBKRTradingProvider() as provider:
            result = provider.submit_order(order)
    """

    # 端口定义
    PAPER_PORT = 4002  # Paper Trading Gateway
    LIVE_PORT = 4001  # Live Trading Gateway (禁止使用)

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        timeout: int = 30,
        account_type: TradingAccountType = TradingAccountType.PAPER,
    ) -> None:
        """初始化 IBKR 交易提供者

        Args:
            host: TWS/Gateway 主机地址
            port: 端口号 (只允许 4002)
            client_id: 客户端 ID
            timeout: 超时时间
            account_type: 账户类型 (必须是 PAPER)

        Raises:
            AccountTypeError: 账户类型不是 PAPER
            ValueError: 端口不是 4002
        """
        # 调用父类构造函数验证账户类型
        super().__init__(account_type)

        load_dotenv()

        self._host = host or os.getenv("IBKR_HOST", "127.0.0.1")

        # 端口验证: 只允许 Paper Trading 端口
        if port is not None and port != self.PAPER_PORT:
            raise AccountTypeError(
                f"Only Paper Trading port ({self.PAPER_PORT}) is allowed. "
                f"Port {port} is NOT permitted. "
                "This system does NOT support live trading."
            )
        self._port = port or self.PAPER_PORT

        # 生成唯一的 client ID
        default_client_id = 200 + (os.getpid() % 800)  # 200-999 范围
        self._client_id = client_id or default_client_id
        self._timeout = timeout

        self._ib: Any = None
        self._connected = False
        self._lock = Lock()
        self._account_id: str | None = None

        logger.info(
            f"IBKRTradingProvider initialized: "
            f"host={self._host}, port={self._port} (PAPER ONLY)"
        )

    @property
    def name(self) -> str:
        """提供者名称"""
        return "ibkr"

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        if not self._connected or self._ib is None:
            return False
        try:
            accounts = self._ib.managedAccounts()
            return accounts is not None and len(accounts) > 0
        except Exception:
            return False

    def connect(self) -> None:
        """建立连接

        连接后验证:
        1. 端口必须是 4002
        2. 账户 ID 必须以 "DU" 开头

        Raises:
            TradingProviderError: 连接失败
            AccountTypeError: 账户验证失败
        """
        if not IBKR_AVAILABLE:
            raise TradingProviderError("ib_async is not installed")

        with self._lock:
            if self._connected:
                return

            # 再次验证端口
            if self._port != self.PAPER_PORT:
                raise AccountTypeError(
                    f"Cannot connect to port {self._port}. "
                    f"Only Paper Trading port ({self.PAPER_PORT}) is allowed."
                )

            try:
                self._ib = IB()
                self._ib.connect(
                    self._host,
                    self._port,
                    clientId=self._client_id,
                    timeout=self._timeout,
                )

                # 获取账户 ID 并验证是否为 Paper 账户
                accounts = self._ib.managedAccounts()
                if not accounts:
                    raise TradingProviderError("No accounts found")

                self._account_id = accounts[0]

                # Paper 账户验证: 账户 ID 应以 "DU" 开头
                if not self._account_id.startswith("DU"):
                    self._ib.disconnect()
                    raise AccountTypeError(
                        f"Account {self._account_id} is NOT a Paper account. "
                        f"Paper account IDs start with 'DU'. "
                        "This system does NOT support live trading."
                    )

                self._connected = True
                logger.info(
                    f"Connected to IBKR Paper Trading: "
                    f"{self._host}:{self._port}, account={self._account_id}"
                )

            except AccountTypeError:
                raise
            except Exception as e:
                self._connected = False
                raise TradingProviderError(f"Failed to connect: {e}")

    def disconnect(self) -> None:
        """断开连接"""
        with self._lock:
            if self._ib:
                try:
                    self._ib.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting: {e}")
                finally:
                    self._ib = None
                    self._connected = False
                    logger.info("Disconnected from IBKR")

    def submit_order(self, order: OrderRequest) -> TradingResult:
        """提交订单

        Args:
            order: 订单请求

        Returns:
            TradingResult: 交易结果
        """
        # 验证 Paper 账户
        self._validate_paper_account()

        # 验证订单账户类型
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
                error_message="Not connected to IBKR",
            )

        try:
            # 构建合约
            contract = self._build_contract(order)

            # 构建订单
            ib_order = self._build_order(order)

            # 提交订单
            trade: Trade = self._ib.placeOrder(contract, ib_order)

            # 等待订单确认
            self._ib.sleep(1)

            # 获取订单 ID
            broker_order_id = str(trade.order.orderId)

            logger.info(
                f"Order submitted: {order.order_id} -> broker_id={broker_order_id}, "
                f"symbol={order.symbol}, qty={order.quantity}, "
                f"side={order.side.value}, price={order.limit_price}"
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

    def _build_contract(self, order: OrderRequest) -> Any:
        """构建 IBKR 合约对象"""
        if order.asset_class == AssetClass.OPTION:
            # 期权合约
            # 转换 expiry 格式: YYYY-MM-DD -> YYYYMMDD
            expiry = order.expiry
            if expiry and "-" in expiry:
                expiry = expiry.replace("-", "")

            # 转换 right: put/call -> P/C
            right = "P" if order.option_type == "put" else "C"

            #TODO, 如果交易的是港股期权，  multiplier不一定是100吧？ 要根据实际的合约来。
            contract = Option(
                symbol=order.underlying or order.symbol,
                lastTradeDateOrContractMonth=expiry,
                strike=order.strike,
                right=right,
                exchange="SMART",
                multiplier="100",
            )

            # 设置 trading class (如果有)
            if order.trading_class:
                contract.tradingClass = order.trading_class

        else:
            # 股票合约
            contract = Stock(
                symbol=order.symbol,
                exchange="SMART",
                currency="USD",
            )

        return contract

    def _build_order(self, order: OrderRequest) -> Any:
        """构建 IBKR 订单对象"""
        action = "BUY" if order.side == OrderSide.BUY else "SELL"
        quantity = abs(order.quantity)

        if order.order_type == OrderType.MARKET:
            ib_order = MarketOrder(action=action, totalQuantity=quantity)
        else:
            # 默认使用限价单
            ib_order = LimitOrder(
                action=action,
                totalQuantity=quantity,
                lmtPrice=order.limit_price,
            )

        # 设置有效期
        ib_order.tif = order.time_in_force

        return ib_order

    def query_order(self, broker_order_id: str) -> OrderQueryResult:
        """查询订单状态"""
        if not self.is_connected:
            return OrderQueryResult.not_found(broker_order_id)

        try:
            # 获取所有活跃订单
            trades = self._ib.trades()

            for trade in trades:
                if str(trade.order.orderId) == broker_order_id:
                    return OrderQueryResult(
                        found=True,
                        broker_order_id=broker_order_id,
                        status=trade.orderStatus.status,
                        filled_quantity=int(trade.orderStatus.filled),
                        remaining_quantity=int(trade.orderStatus.remaining),
                        average_price=trade.orderStatus.avgFillPrice or None,
                        last_updated=datetime.now(),
                    )

            return OrderQueryResult.not_found(broker_order_id)

        except Exception as e:
            logger.error(f"Query order failed: {e}")
            return OrderQueryResult.not_found(broker_order_id)

    def cancel_order(self, broker_order_id: str) -> CancelResult:
        """取消订单"""
        self._validate_paper_account()

        if not self.is_connected:
            return CancelResult.failure_cancel(
                broker_order_id, "Not connected to IBKR"
            )

        try:
            # 查找订单
            trades = self._ib.trades()
            target_trade = None

            for trade in trades:
                if str(trade.order.orderId) == broker_order_id:
                    target_trade = trade
                    break

            if target_trade is None:
                return CancelResult.failure_cancel(
                    broker_order_id, "Order not found"
                )

            # 取消订单
            self._ib.cancelOrder(target_trade.order)
            self._ib.sleep(1)

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
            trades = self._ib.trades()
            results = []

            for trade in trades:
                status = trade.orderStatus.status
                # 只返回未完成的订单
                if status not in ("Filled", "Cancelled", "Inactive"):
                    results.append(
                        OrderQueryResult(
                            found=True,
                            broker_order_id=str(trade.order.orderId),
                            status=status,
                            filled_quantity=int(trade.orderStatus.filled),
                            remaining_quantity=int(trade.orderStatus.remaining),
                            average_price=trade.orderStatus.avgFillPrice or None,
                            last_updated=datetime.now(),
                        )
                    )

            return results

        except Exception as e:
            logger.error(f"Get open orders failed: {e}")
            return []
