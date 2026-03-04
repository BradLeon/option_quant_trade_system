import logging
from src.business.strategy.base import BaseOptionStrategy

logger = logging.getLogger(__name__)

class ShortOptionsWithExpireItmStockTrade(BaseOptionStrategy):
    """Short Options with ITM assignment

    通过 BaseOptionStrategy 提供的标准交易管道执行，
    默认持有至到期或触发行权信号。
    """

    @property
    def name(self) -> str:
        return "short_options_with_expire_itm_stock_trade"

    def get_monitoring_overrides(self) -> dict | None:
        """接股版：禁用 OTM% 平仓 + 禁用 P&L 止损"""
        return {
            "otm_pct": {"enabled": False},  # 允许 ITM 持有至行权
            "pnl": {"enabled": False},       # 行权接盘兜底，禁用 P&L 止损
        }
