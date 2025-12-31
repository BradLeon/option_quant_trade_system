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
from src.data.providers.ibkr_provider import IBKRProvider
from src.data.providers.unified_provider import UnifiedDataProvider
from src.engine.position.fundamental.metrics import evaluate_fundamentals
from src.engine.position.technical.metrics import calc_technical_score, calc_technical_signal
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
        ibkr_provider: IBKRProvider | None = None,
        cache_ttl_seconds: int = 300,
    ):
        """初始化数据转换器

        Args:
            data_provider: 统一数据提供者，用于获取补充数据
            ibkr_provider: IBKR 提供者，用于获取 HV 数据计算 SAS
            cache_ttl_seconds: 缓存有效期（秒），默认 5 分钟
        """
        self._provider = data_provider
        self._ibkr_provider = ibkr_provider
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

        # Step 3: 转换每个持仓（期权可能拆分为多个策略实例）
        result = []
        for pos in portfolio.positions:
            try:
                position_data_list = self._convert_position(pos, portfolio.positions)
                if position_data_list:
                    result.extend(position_data_list)
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

        logger.debug(f"_prefetch_data: Fetching data for symbols: {symbols}")

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
                        logger.debug(f"_prefetch_data: Got fundamental for {symbol}, beta={fund.beta}")
                    else:
                        logger.debug(f"_prefetch_data: No fundamental returned for {symbol}")
                except Exception as e:
                    logger.warning(f"Failed to get fundamental for {symbol}: {e}")

    def _convert_position(
        self,
        pos: AccountPosition,
        all_positions: list[AccountPosition],
    ) -> list[PositionData]:
        """转换单个持仓

        Args:
            pos: 账户持仓
            all_positions: 所有持仓（用于策略分类）

        Returns:
            转换后的 PositionData 列表（期权可能拆分为多个策略实例）
        """
        if pos.asset_type == AssetType.OPTION:
            return self._convert_option_position(pos, all_positions)
        elif pos.asset_type == AssetType.STOCK:
            stock_data = self._convert_stock_position(pos)
            return [stock_data] if stock_data else []
        else:
            logger.debug(f"Skipping non-stock/option position: {pos.symbol}")
            return []

    def _convert_option_position(
        self,
        pos: AccountPosition,
        all_positions: list[AccountPosition],
    ) -> list[PositionData]:
        """转换期权持仓

        为每个策略实例创建单独的 PositionData。
        例如 short call 可能拆分为 covered_call + naked_call。

        Args:
            pos: 期权持仓
            all_positions: 所有持仓

        Returns:
            转换后的 PositionData 列表
        """
        # 基础字段
        dte = calc_dte_from_expiry(pos.expiry) if pos.expiry else None
        underlying_symbol = pos.underlying or pos.symbol

        # 计算 moneyness (旧公式，保留兼容)
        moneyness = None
        if pos.underlying_price and pos.strike:
            moneyness = (pos.underlying_price - pos.strike) / pos.strike

        # 计算 otm_pct (新统一公式)
        # Put: OTM% = (S-K)/S (正值表示 OTM)
        # Call: OTM% = (K-S)/S (正值表示 OTM)
        otm_pct = None
        if pos.underlying_price and pos.strike and pos.underlying_price > 0:
            if pos.option_type == "put":
                otm_pct = (pos.underlying_price - pos.strike) / pos.underlying_price
            elif pos.option_type == "call":
                otm_pct = (pos.strike - pos.underlying_price) / pos.underlying_price

        # 计算 PnL%
        unrealized_pnl_pct = 0.0
        if pos.avg_cost and pos.avg_cost != 0:
            unrealized_pnl_pct = pos.unrealized_pnl / (
                abs(pos.quantity) * pos.contract_multiplier * pos.avg_cost
            )

        # 计算 current_price (每股权利金)
        current_price = 0.0
        if pos.quantity != 0:
            current_price = pos.market_value / (abs(pos.quantity) * pos.contract_multiplier)

        # 创建策略实例（可能有多个，如 covered_call + naked_call）
        try:
            strategies = create_strategies_from_position(
                position=pos,
                all_positions=all_positions,
                ibkr_provider=self._ibkr_provider,  # 传入 ibkr_provider 获取 HV 数据
            )
        except Exception as e:
            logger.warning(f"Failed to create strategies for {pos.symbol}: {e}")
            strategies = []

        # 如果没有策略实例，返回基础 PositionData
        if not strategies:
            position_data = self._create_base_position_data(
                pos, dte, moneyness, otm_pct, unrealized_pnl_pct, current_price
            )
            self._enrich_volatility(position_data, underlying_symbol)
            self._enrich_technical(position_data, underlying_symbol)
            self._enrich_technical_signal(position_data, underlying_symbol)
            self._enrich_fundamental(position_data, underlying_symbol)
            return [position_data]

        # 为每个策略实例创建 PositionData
        result = []
        for strategy_instance in strategies:
            strategy = strategy_instance.strategy
            ratio = strategy_instance.quantity_ratio
            desc = strategy_instance.description

            # 提取策略类型
            strategy_type = desc.split("(")[0].strip()

            # 创建 PositionData，数量按 ratio 计算
            position_data = PositionData(
                position_id=f"{pos.symbol}_{pos.strike}_{pos.expiry}_{strategy_type}",
                symbol=pos.symbol,
                asset_type="option",
                quantity=ratio * pos.quantity,  # 按比例计算数量
                entry_price=pos.avg_cost,
                current_price=current_price,
                market_value=pos.market_value * ratio,  # 按比例计算市值
                unrealized_pnl=pos.unrealized_pnl * ratio,
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
                otm_pct=otm_pct,  # 新增: 统一 OTM% 公式
                # Greeks (从 strategy.leg 获取，更准确)
                delta=strategy.leg.delta if strategy.leg else pos.delta,
                gamma=strategy.leg.gamma if strategy.leg else pos.gamma,
                theta=strategy.leg.theta if strategy.leg else pos.theta,
                vega=strategy.leg.vega if strategy.leg else pos.vega,
                iv=pos.iv,
                underlying_price=pos.underlying_price,
                # 策略信息
                strategy_type=strategy_type,
                # HV from strategy params
                hv=strategy.params.hv,
            )

            # 填充波动率数据
            self._enrich_volatility(position_data, underlying_symbol)

            # 填充技术面数据
            self._enrich_technical(position_data, underlying_symbol)

            # 填充技术信号数据
            self._enrich_technical_signal(position_data, underlying_symbol)

            # 填充基本面数据
            self._enrich_fundamental(position_data, underlying_symbol)

            # 填充策略指标
            try:
                metrics = strategy.calc_metrics()
                position_data.prei = metrics.prei
                position_data.tgr = metrics.tgr
                position_data.sas = metrics.sas
                position_data.roc = metrics.roc
                position_data.expected_roc = metrics.expected_roc
                position_data.sharpe = metrics.sharpe_ratio
                position_data.kelly = metrics.kelly_fraction
                position_data.win_probability = metrics.win_probability
                position_data.expected_return = metrics.expected_return
                position_data.max_profit = metrics.max_profit
                position_data.max_loss = metrics.max_loss
                position_data.breakeven = metrics.breakeven
                position_data.return_std = metrics.return_std

                # 资金相关指标
                try:
                    margin_per_contract = strategy.calc_margin_requirement()
                    position_data.margin = margin_per_contract * ratio
                    position_data.capital_at_risk = strategy._calc_capital_at_risk()

                    # 计算 gamma_risk_pct: |Gamma| / Margin
                    # 只有当 margin > 0 时才计算
                    if position_data.margin and position_data.margin > 0 and position_data.gamma:
                        position_data.gamma_risk_pct = abs(position_data.gamma) / position_data.margin
                except Exception as margin_error:
                    logger.debug(f"Could not calculate margin for {pos.symbol}: {margin_error}")

            except Exception as e:
                logger.warning(f"Failed to calc metrics for {pos.symbol} {strategy_type}: {e}")

            result.append(position_data)

        return result

    def _create_base_position_data(
        self,
        pos: AccountPosition,
        dte: int | None,
        moneyness: float | None,
        otm_pct: float | None,
        unrealized_pnl_pct: float,
        current_price: float,
    ) -> PositionData:
        """创建基础 PositionData（无策略信息）"""
        return PositionData(
            position_id=f"{pos.symbol}_{pos.strike}_{pos.expiry}",
            symbol=pos.symbol,
            asset_type="option",
            quantity=pos.quantity,
            entry_price=pos.avg_cost,
            current_price=current_price,
            market_value=pos.market_value,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            currency=pos.currency,
            broker=pos.broker,
            timestamp=pos.last_updated or datetime.now(),
            underlying=pos.underlying,
            option_type=pos.option_type,
            strike=pos.strike,
            expiry=pos.expiry,
            dte=dte,
            contract_multiplier=pos.contract_multiplier,
            moneyness=moneyness,
            otm_pct=otm_pct,  # 新增: 统一 OTM% 公式
            delta=pos.delta,
            gamma=pos.gamma,
            theta=pos.theta,
            vega=pos.vega,
            iv=pos.iv,
            underlying_price=pos.underlying_price,
        )

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

        # 计算 current_price (每股价格)
        current_price = 0.0
        if pos.quantity != 0:
            current_price = abs(pos.market_value / pos.quantity)

        position_data = PositionData(
            position_id=f"{pos.symbol}_stock",
            symbol=pos.symbol,
            asset_type="stock",
            quantity=pos.quantity,
            entry_price=pos.avg_cost,
            current_price=current_price,
            market_value=pos.market_value,
            unrealized_pnl=pos.unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            currency=pos.currency,
            broker=pos.broker,
            timestamp=pos.last_updated or datetime.now(),
            # 使用 AccountPosition 的值，与验证脚本保持一致
            delta=pos.delta,
            gamma=pos.gamma,
            theta=pos.theta,
            vega=pos.vega,
            # 直接使用 IBKR 已计算好的 underlying_price，不要重新计算
            underlying_price=pos.underlying_price,
            # 使用 AccountPosition 的 contract_multiplier（股票默认为1）
            contract_multiplier=pos.contract_multiplier,
        )

        # 填充波动率数据
        self._enrich_volatility(position_data, pos.symbol)

        # 填充技术面数据
        self._enrich_technical(position_data, pos.symbol)

        # 填充技术信号数据
        self._enrich_technical_signal(position_data, pos.symbol)

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
            logger.debug(f"_enrich_fundamental: No fundamental data cached for {symbol}")
            return

        # 调用统一出口算子
        fund_score = evaluate_fundamentals(fund)

        # 从 Fundamental 提取字段
        pos.pe_ratio = fund.pe_ratio
        pos.beta = fund.beta  # 用于 beta_weighted_delta 计算
        logger.debug(f"_enrich_fundamental: {symbol} beta={fund.beta}")
        # 从 FundamentalScore 提取字段
        pos.fundamental_score = fund_score.score
        pos.analyst_rating = fund_score.rating.value if fund_score.rating else None

    def _enrich_technical_signal(self, pos: PositionData, symbol: str) -> None:
        """调用 calc_technical_signal() 填充技术信号字段

        Args:
            pos: 待填充的 PositionData
            symbol: 标的 symbol
        """
        tech_data = self._technical_cache.get(symbol)
        if not tech_data:
            return

        # 调用统一出口算子
        tech_signal = calc_technical_signal(tech_data)

        # 从 TechnicalSignal 提取字段
        pos.market_regime = tech_signal.market_regime
        pos.tech_trend_strength = tech_signal.trend_strength
        pos.sell_put_signal = tech_signal.sell_put_signal
        pos.sell_call_signal = tech_signal.sell_call_signal
        pos.is_dangerous_period = tech_signal.is_dangerous_period

    def clear_cache(self) -> None:
        """清除所有缓存"""
        self._volatility_cache.clear()
        self._technical_cache.clear()
        self._fundamental_cache.clear()
