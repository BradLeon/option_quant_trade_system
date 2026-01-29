"""
Trading Provider Base - 交易提供者抽象基类

定义统一的券商交易接口。

⚠️  CRITICAL: 本接口仅支持 Paper Trading (模拟账户)。
    TradingAccountType 枚举仅定义 PAPER，不存在 REAL。
    每个实现类必须在构造函数和每次操作前验证账户类型。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from src.business.trading.models.order import OrderRequest
from src.business.trading.models.trading import (
    AccountTypeError,
    CancelResult,
    OrderQueryResult,
    TradingAccountType,
    TradingProviderError,
    TradingResult,
)

logger = logging.getLogger(__name__)


class TradingProvider(ABC):
    """交易提供者抽象基类

    ⚠️  CRITICAL: 本接口仅支持 Paper Trading (模拟账户)。

    所有实现类必须:
    1. 在构造函数中验证 account_type == PAPER
    2. 在每次操作前调用 _validate_paper_account()
    3. 使用券商的模拟交易端口/环境

    Usage:
        provider = IBKRTradingProvider()  # Defaults to PAPER
        result = provider.submit_order(order)
    """

    def __init__(
        self,
        account_type: TradingAccountType = TradingAccountType.PAPER,
    ) -> None:
        """初始化交易提供者

        Args:
            account_type: 账户类型，必须是 PAPER

        Raises:
            AccountTypeError: 如果 account_type 不是 PAPER
        """
        # 构造函数验证
        if account_type != TradingAccountType.PAPER:
            raise AccountTypeError(
                "REAL trading is NOT supported. "
                "This system only supports PAPER trading accounts. "
                "DO NOT attempt to trade with real money."
            )
        self._account_type = account_type
        logger.info(f"{self.__class__.__name__} initialized with PAPER account")

    @property
    @abstractmethod
    def name(self) -> str:
        """提供者名称 (e.g., "ibkr", "futu")"""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        ...

    @property
    def account_type(self) -> TradingAccountType:
        """账户类型 (总是 PAPER)"""
        return self._account_type

    def _validate_paper_account(self) -> None:
        """验证账户类型是否为 PAPER

        每次交易操作前必须调用此方法。

        Raises:
            AccountTypeError: 如果账户类型不是 PAPER
        """
        if self._account_type != TradingAccountType.PAPER:
            raise AccountTypeError(
                "Trading only allowed on PAPER accounts. "
                f"Current account type: {self._account_type}"
            )

    @abstractmethod
    def connect(self) -> None:
        """建立连接

        Raises:
            TradingProviderError: 连接失败
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> TradingResult:
        """提交订单

        Args:
            order: 订单请求

        Returns:
            TradingResult: 交易结果

        Raises:
            AccountTypeError: 如果不是 PAPER 账户
            TradingProviderError: 其他交易错误
        """
        ...

    @abstractmethod
    def query_order(self, broker_order_id: str) -> OrderQueryResult:
        """查询订单状态

        Args:
            broker_order_id: 券商订单 ID

        Returns:
            OrderQueryResult: 查询结果
        """
        ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> CancelResult:
        """取消订单

        Args:
            broker_order_id: 券商订单 ID

        Returns:
            CancelResult: 取消结果

        Raises:
            AccountTypeError: 如果不是 PAPER 账户
        """
        ...

    @abstractmethod
    def get_open_orders(self) -> list[OrderQueryResult]:
        """获取所有未完成订单

        Returns:
            未完成订单列表
        """
        ...

    def __enter__(self) -> "TradingProvider":
        """进入上下文管理器"""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """退出上下文管理器"""
        self.disconnect()
