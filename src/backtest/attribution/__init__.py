"""
回测归因与迭代模块

提供 Greeks-based PnL 归因分解、多维切片归因、策略诊断和市场环境分析。

核心组件:
- AttributionCollector: 挂入 BacktestExecutor 每日采集持仓/组合快照
- PnLAttributionEngine: Greeks PnL 归因分解（Daily / Per-Trade）
- SliceAttributionEngine: 多维度切片归因（标的/期权类型/IV/平仓原因）
- StrategyDiagnosis: 策略诊断（入场质量/出场质量/止损反转率）
- RegimeAnalyzer: 市场环境分析（VIX/SPY/事件）

Usage:
    from src.backtest.attribution import AttributionCollector, PnLAttributionEngine

    # 创建 collector 并注入 BacktestExecutor
    collector = AttributionCollector()
    executor = BacktestExecutor(config, attribution_collector=collector)
    result = executor.run()

    # 事后归因
    engine = PnLAttributionEngine(
        position_snapshots=collector.position_snapshots,
        portfolio_snapshots=collector.portfolio_snapshots,
        trade_records=result.trade_records,
    )
    daily_attr = engine.compute_all_daily()
"""

from src.backtest.attribution.collector import AttributionCollector
from src.backtest.attribution.models import (
    DailyAttribution,
    DayRegime,
    PortfolioSnapshot,
    PositionDailyAttribution,
    PositionSnapshot,
    SliceStats,
    TradeAttribution,
)
from src.backtest.attribution.pnl_attribution import PnLAttributionEngine
from src.backtest.attribution.regime_analyzer import RegimeAnalyzer
from src.backtest.attribution.slice_attribution import SliceAttributionEngine
from src.backtest.attribution.strategy_diagnosis import StrategyDiagnosis

__all__ = [
    "AttributionCollector",
    "PnLAttributionEngine",
    "SliceAttributionEngine",
    "StrategyDiagnosis",
    "RegimeAnalyzer",
    "PositionSnapshot",
    "PortfolioSnapshot",
    "DailyAttribution",
    "PositionDailyAttribution",
    "TradeAttribution",
    "SliceStats",
    "DayRegime",
]
