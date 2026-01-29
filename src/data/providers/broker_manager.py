"""
Broker Manager - 统一的 Broker Provider 管理器

提供简洁的 API 创建和管理 broker provider 实例。

Usage:
    manager = BrokerManager(account_type="paper")
    conn = manager.connect()

    if conn.ibkr:
        positions = conn.ibkr.get_positions()

    aggregator = conn.get_aggregator()
    portfolio = aggregator.get_consolidated_portfolio()
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from src.data.models.account import AccountType

if TYPE_CHECKING:
    from src.data.providers.account_aggregator import AccountAggregator
    from src.data.providers.futu_provider import FutuProvider
    from src.data.providers.ibkr_provider import IBKRProvider

AccountTypeStr = Literal["paper", "real"]


@dataclass
class BrokerConnection:
    """Broker 连接结果"""

    ibkr: "IBKRProvider | None" = None
    futu: "FutuProvider | None" = None
    ibkr_error: str | None = None
    futu_error: str | None = None

    @property
    def any_connected(self) -> bool:
        """是否有任何 broker 连接成功"""
        return self.ibkr is not None or self.futu is not None

    def get_aggregator(self) -> "AccountAggregator":
        """获取账户聚合器"""
        from src.data.providers.account_aggregator import AccountAggregator

        return AccountAggregator(
            ibkr_provider=self.ibkr,
            futu_provider=self.futu,
        )


class BrokerManager:
    """统一的 Broker Provider 管理器

    将 account_type 字符串统一映射到正确的 provider 配置:
    - "paper" -> IBKR port 4002, Futu SIMULATE
    - "real"  -> IBKR port 4001, Futu REAL

    Usage:
        manager = BrokerManager(account_type="paper")
        conn = manager.connect(ibkr=True, futu=True)

        if conn.ibkr:
            positions = conn.ibkr.get_positions()

        if not conn.any_connected:
            raise Exception("无法连接任何券商")

        aggregator = conn.get_aggregator()
    """

    def __init__(self, account_type: AccountTypeStr = "paper") -> None:
        """初始化 BrokerManager

        Args:
            account_type: "paper" 或 "real"
        """
        self._account_type = (
            AccountType.PAPER if account_type == "paper" else AccountType.REAL
        )
        self._account_type_str = account_type

    def connect(
        self,
        ibkr: bool = True,
        futu: bool = True,
    ) -> BrokerConnection:
        """连接 broker providers

        Args:
            ibkr: 是否连接 IBKR
            futu: 是否连接 Futu

        Returns:
            BrokerConnection 包含连接的 provider 和错误信息
        """
        result = BrokerConnection()

        if ibkr:
            result.ibkr, result.ibkr_error = self._connect_ibkr()

        if futu:
            result.futu, result.futu_error = self._connect_futu()

        return result

    def _connect_ibkr(self) -> tuple["IBKRProvider | None", str | None]:
        """连接 IBKR

        Returns:
            (provider, error_message) - 成功时 error 为 None
        """
        try:
            from src.data.providers.ibkr_provider import IBKRProvider

            provider = IBKRProvider(account_type=self._account_type)
            provider.connect()
            return provider, None
        except Exception as e:
            return None, str(e)

    def _connect_futu(self) -> tuple["FutuProvider | None", str | None]:
        """连接 Futu

        Returns:
            (provider, error_message) - 成功时 error 为 None
        """
        try:
            from src.data.providers.futu_provider import FutuProvider

            provider = FutuProvider(account_type=self._account_type)
            provider.connect()
            return provider, None
        except Exception as e:
            return None, str(e)

    @property
    def account_type(self) -> AccountType:
        """获取账户类型枚举"""
        return self._account_type

    @property
    def account_type_str(self) -> str:
        """获取账户类型字符串"""
        return self._account_type_str
