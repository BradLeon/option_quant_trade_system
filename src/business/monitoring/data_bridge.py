"""Monitoring Data Bridge - 数据转换层

将 AccountPosition 转换为 PositionData，调用 Engine 层算子填充分析结果。

设计原则（遵循 Decision #0）：
- 每类分析只调用一个统一出口函数
- 从返回的 Output Model 中提取字段填充到 PositionData
- 批量预获取数据避免重复 API 调用
"""

import logging
from datetime import datetime

from src.business.monitoring.models import PositionData
from src.data.models.account import AccountPosition, AssetType, ConsolidatedPortfolio
from src.data.models.fundamental import Fundamental
from src.data.models.stock import StockVolatility
from src.data.models.technical import TechnicalData
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.position.fundamental.metrics import evaluate_fundamentals
from src.engine.position.technical.metrics import calc_technical_score
from src.engine.position.volatility.metrics import evaluate_volatility
from src.engine.strategy.factory import (
    calc_dte_from_expiry,
    create_strategies_from_position,
)

logger = logging.getLogger(__name__)


class MonitoringDataBridge:
    """数据转换桥接器

    将 AccountPosition 转换为 PositionData，调用 Engine 层算子填充分析结果。

    Usage:
        >>> bridge = MonitoringDataBridge(provider)
        >>> positions = bridge.convert_positions(portfolio)
    """

    def __init__(
        self,
        data_provider: UnifiedDataProvider | None = None,
        cache_ttl_seconds: int = 300,
    ):
        """初始化数据转换器

        Args:
            data_provider: 统一数据提供者，用于获取补充数据
            cache_ttl_seconds: 缓存有效期（秒），默认 5 分钟
        """
        self._provider = data_provider
        self._cache_ttl = cache_ttl_seconds

        # 数据缓存（按 symbol 存储）
        self._volatility_cache: dict[str, StockVolatility] = {}
        self._technical_cache: dict[str, TechnicalData] = {}
        self._fundamental_cache: dict[str, Fundamental] = {}

    def convert_positions(
        self,
        portfolio: ConsolidatedPortfolio,
    ) -> list[PositionData]:
        """主入口：将 ConsolidatedPortfolio 转换为 list[PositionData]

        Args:
            portfolio: 合并后的账户持仓

        Returns:
            转换后的 PositionData 列表
        """
        if not portfolio.positions:
            return []

        # Step 1: 收集所有标的 symbols
        symbols = self._collect_symbols(portfolio.positions)

        # Step 2: 批量预获取补充数据
        self._prefetch_data(symbols)

        # Step 3: 转换每个持仓
        result = []
        for pos in portfolio.positions:
            try:
                position_data = self._convert_position(pos, portfolio.positions)
                if position_data:
                    result.append(position_data)
            except Exception as e:
                logger.warning(f"Failed to convert position {pos.symbol}: {e}")

        return result

    def _collect_symbols(self, positions: list[AccountPosition]) -> set[str]:
        """收集所有需要获取数据的标的 symbols

        Args:
            positions: 账户持仓列表

        Returns:
            唯一的 symbol 集合
        """
        symbols = set()
        for pos in positions:
            if pos.asset_type == AssetType.OPTION:
                # 期权使用 underlying
                symbol = pos.underlying or pos.symbol
            else:
                # 股票使用自身 symbol
                symbol = pos.symbol
            symbols.add(symbol)
        return symbols

    def _prefetch_data(self, symbols: set[str]) -> None:
        """批量预获取补充数据

        Args:
            symbols: 需要获取数据的 symbols
        """
        if not self._provider:
            logger.debug("No data provider configured, skipping prefetch")
            return

        for symbol in symbols:
            # Volatility data
            if symbol not in self._volatility_cache:
                try:
                    vol = self._provider.get_stock_volatility(symbol)
                    if vol:
                        self._volatility_cache[symbol] = vol
                except Exception as e:
                    logger.warning(f"Failed to get volatility for {symbol}: {e}")

            # Technical data (from K-lines)
            if symbol not in self._technical_cache:
                try:
                    klines = self._provider.get_history_kline(symbol)
                    if klines:
                        tech_data = TechnicalData.from_klines(klines)
                        self._technical_cache[symbol] = tech_data
                except Exception as e:
                    logger.warning(f"Failed to get technical data for {symbol}: {e}")

            # Fundamental data
            if symbol not in self._fundamental_cache:
                try:
                    fund = self._provider.get_fundamental(symbol)
                    if fund:
                        self._fundamental_cache[symbol] = fund
                except Exception as e:
                    logger.warning(f"Failed to get fundamental for {symbol}: {e}")

    def _convert_position(
        self,
        pos: AccountPosition,
        all_positions: list[AccountPosition],
    ) -> PositionData | None:
        """转换单个持仓

        Args:
            pos: 账户持仓
            all_positions: 所有持仓（用于策略分类）

        Returns:
            转换后的 PositionData 或 None
        """
        if pos.asset_type == AssetType.OPTION:
            return self._convert_option_position(pos, all_positions)
        elif pos.asset_type == AssetType.STOCK:
            return self._convert_stock_position(pos)
        else:
            logger.debug(f"Skipping non-stock/option position: {pos.symbol}")
            return None

    def _convert_option_position(
        self,
        pos: AccountPosition,
        all_positions: list[AccountPosition],
    ) -> PositionData:
        """转换期权持仓

        Args:
            pos: 期权持仓
            all_positions: 所有持仓

        Returns:
            转换后的 PositionData
        """
        # 基础字段
        dte = calc_dte_from_expiry(pos.expiry) if pos.expiry else None

        # 计算 moneyness
        moneyness = None
        if pos.underlying_price and pos.strike:
            moneyness = (pos.underlying_price - pos.strike) / pos.strike

        # 计算 PnL%
        unrealized_pnl_pct = 0.0
        if pos.avg_cost and pos.avg_cost != 0:
            unrealized_pnl_pct = pos.unrealized_pnl / (
                abs(pos.quantity) * pos.contract_multiplier * pos.avg_cost
            )

        position_data = PositionData(
            position_id=f"{pos.symbol}_{pos.strike}_{pos.expiry}",
            symbol=pos.symbol,
            asset_type="option",
            quantity=pos.quantity,
            entry_price=pos.avg_cost,
            current_price=pos.market_value / (abs(pos.quantity) * pos.contract_multiplier)
            if pos.quantity != 0
            else 0,
            market_value=pos.market_value,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            currency=pos.currency,
            broker=pos.broker,
            timestamp=pos.last_updated or datetime.now(),
            # 期权专用字段
            underlying=pos.underlying,
            option_type=pos.option_type,
            strike=pos.strike,
            expiry=pos.expiry,
            dte=dte,
            contract_multiplier=pos.contract_multiplier,
            moneyness=moneyness,
            # Greeks
            delta=pos.delta,
            gamma=pos.gamma,
            theta=pos.theta,
            vega=pos.vega,
            iv=pos.iv,
            underlying_price=pos.underlying_price,
        )

        # 获取 underlying symbol 用于查询缓存
        underlying_symbol = pos.underlying or pos.symbol

        # 填充波动率数据
        self._enrich_volatility(position_data, underlying_symbol)

        # 填充技术面数据
        self._enrich_technical(position_data, underlying_symbol)

        # 填充策略指标
        self._enrich_strategy_metrics(position_data, pos, all_positions)

        return position_data

    def _convert_stock_position(self, pos: AccountPosition) -> PositionData:
        """转换股票持仓

        Args:
            pos: 股票持仓

        Returns:
            转换后的 PositionData
        """
        # 计算 PnL%
        unrealized_pnl_pct = 0.0
        if pos.avg_cost and pos.avg_cost != 0:
            unrealized_pnl_pct = pos.unrealized_pnl / (pos.quantity * pos.avg_cost)

        position_data = PositionData(
            position_id=f"{pos.symbol}_stock",
            symbol=pos.symbol,
            asset_type="stock",
            quantity=pos.quantity,
            entry_price=pos.avg_cost,
            current_price=pos.market_value / pos.quantity if pos.quantity != 0 else 0,
            market_value=pos.market_value,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            currency=pos.currency,
            broker=pos.broker,
            timestamp=pos.last_updated or datetime.now(),
            # 股票的 delta 等于持仓数量
            delta=pos.quantity,
            underlying_price=pos.market_value / pos.quantity if pos.quantity != 0 else 0,
        )

        # 填充波动率数据
        self._enrich_volatility(position_data, pos.symbol)

        # 填充技术面数据
        self._enrich_technical(position_data, pos.symbol)

        # 填充基本面数据
        self._enrich_fundamental(position_data, pos.symbol)

        return position_data

    def _enrich_volatility(self, pos: PositionData, symbol: str) -> None:
        """调用 evaluate_volatility() 填充波动率字段

        Args:
            pos: 待填充的 PositionData
            symbol: 标的 symbol
        """
        vol = self._volatility_cache.get(symbol)
        if not vol:
            return

        # 调用统一出口算子
        vol_score = evaluate_volatility(vol)

        # 从 VolatilityScore 提取字段
        pos.hv = vol.hv
        pos.iv_rank = vol_score.iv_rank
        pos.iv_percentile = vol_score.iv_percentile
        pos.iv_hv_ratio = vol_score.iv_hv_ratio
        pos.volatility_score = vol_score.score
        pos.volatility_rating = vol_score.rating.value if vol_score.rating else None

    def _enrich_technical(self, pos: PositionData, symbol: str) -> None:
        """调用 calc_technical_score() 填充技术面字段

        Args:
            pos: 待填充的 PositionData
            symbol: 标的 symbol
        """
        tech_data = self._technical_cache.get(symbol)
        if not tech_data:
            return

        # 调用统一出口算子
        tech_score = calc_technical_score(tech_data)

        # 从 TechnicalScore 提取字段
        pos.trend_signal = (
            tech_score.trend_signal.value if tech_score.trend_signal else None
        )
        pos.ma_alignment = tech_score.ma_alignment
        pos.rsi = tech_score.rsi
        pos.rsi_zone = tech_score.rsi_zone
        pos.adx = tech_score.adx
        pos.support = tech_score.support
        pos.resistance = tech_score.resistance

    def _enrich_fundamental(self, pos: PositionData, symbol: str) -> None:
        """调用 evaluate_fundamentals() 填充基本面字段

        Args:
            pos: 待填充的 PositionData
            symbol: 标的 symbol
        """
        fund = self._fundamental_cache.get(symbol)
        if not fund:
            return

        # 调用统一出口算子
        fund_score = evaluate_fundamentals(fund)

        # 从 FundamentalScore 提取字段
        pos.pe_ratio = fund.pe_ratio
        pos.fundamental_score = fund_score.score
        pos.analyst_rating = fund_score.rating.value if fund_score.rating else None

    def _enrich_strategy_metrics(
        self,
        pos: PositionData,
        account_pos: AccountPosition,
        all_positions: list[AccountPosition],
    ) -> None:
        """调用 strategy.calc_metrics() 填充策略指标

        Args:
            pos: 待填充的 PositionData
            account_pos: 原始账户持仓
            all_positions: 所有持仓
        """
        # 只处理期权
        if account_pos.asset_type != AssetType.OPTION:
            return

        try:
            # 创建策略实例
            strategies = create_strategies_from_position(
                position=account_pos,
                all_positions=all_positions,
                ibkr_provider=None,  # 不需要 provider，数据已在 account_pos 中
            )

            if not strategies:
                return

            # 取第一个策略（主策略）
            strategy_instance = strategies[0]
            strategy = strategy_instance.strategy

            # 获取策略类型
            pos.strategy_type = strategy.__class__.__name__.lower().replace(
                "strategy", ""
            )

            # 调用 calc_metrics() 获取指标
            metrics = strategy.calc_metrics()

            # 从 StrategyMetrics 提取字段
            pos.prei = metrics.prei
            pos.tgr = metrics.tgr
            pos.sas = metrics.sas
            pos.roc = metrics.roc
            pos.expected_roc = metrics.expected_roc
            pos.sharpe = metrics.sharpe_ratio
            pos.kelly = metrics.kelly_fraction
            pos.win_probability = metrics.win_probability

        except Exception as e:
            logger.warning(
                f"Failed to calculate strategy metrics for {pos.symbol}: {e}"
            )

    def clear_cache(self) -> None:
        """清除所有缓存"""
        self._volatility_cache.clear()
        self._technical_cache.clear()
        self._fundamental_cache.clear()
