## Why

实现持仓监控系统，将账户真实持仓通过三层检测系统进行全面分析，结合市场环境给出持仓调整建议。

当前状态：
- `src/business/monitoring/` 已有框架代码（models.py, pipeline.py, monitors/）
- 但缺少与 engine 层、data 层的完整集成
- 缺少从真实账户获取持仓并驱动监控的完整数据流

本次开发目标：
1. 实现从真实账户获取持仓 → 数据转换 → 三层监控 → 输出建议的完整流程
2. 遵循项目 data model 驱动的设计原则
3. 最小化 API 请求，避免限速

## What Changes

### 新增能力

**数据转换层 (Data Bridge)**
- `AccountPosition` → `PositionData` (监控模型)
- 批量获取 Greeks/波动率数据，避免重复 API 调用
- 集成 `UnifiedDataProvider` 作为数据源

**持仓级监控增强 (Position Level)**
- 期权持仓：集成 `StrategyMetrics` 计算（SAS/PREI/TGR/Kelly）
- 股票持仓：集成 Fundamental/Technical/Volatility 分析
- 基于分析结果生成持仓调整建议

**组合级监控增强 (Portfolio Level)**
- 集成 `portfolio.greeks_agg` 计算组合 Greeks
- 集成 `portfolio.risk_metrics` 计算 TGR、集中度风险

**账户级监控增强 (Account Level)**
- 集成 `account.margin` 计算保证金使用率
- 添加市场环境（sentiment）感知

**CLI 命令增强**
- `python -m src.business.cli monitor` 从真实账户读取并监控

### 数据流设计

```
AccountAggregator.get_consolidated_portfolio()
    → ConsolidatedPortfolio (positions: list[AccountPosition])
        → [Data Bridge] convert_to_position_data()
            → list[PositionData] (监控输入)

        → [Option Positions]
            → create_strategies_from_position()
            → StrategyMetrics (SAS/PREI/TGR/Kelly)

        → [Stock Positions] (调用统一出口算子)
            → evaluate_volatility(StockVolatility) → VolatilityScore
            → calc_technical_score(TechnicalData) → TechnicalScore
            → evaluate_fundamentals(Fundamental) → FundamentalScore

        → [Portfolio Level]
            → calc_portfolio_delta/gamma/theta/vega()
            → calc_portfolio_tgr()
            → calc_concentration_risk()

        → [Account Level]
            → calc_margin_utilization()
            → get_us/hk_sentiment() → Market Sentiment

        → MonitoringPipeline.run()
            → MonitorResult (alerts, suggestions)
```

## Impact

- Affected specs:
  - 实现 `add-business-layer-phase1/specs/position-monitor-system/spec.md` 中的需求

- Affected code:
  - 新建: `src/business/monitoring/data_bridge.py` - 数据转换
  - 新建: `src/business/monitoring/suggestions.py` - 调整建议生成
  - 修改: `src/business/monitoring/pipeline.py` - 增强监控流程
  - 修改: `src/business/monitoring/monitors/position_monitor.py` - 集成 engine 层
  - 修改: `src/business/cli/commands/monitor.py` - CLI 命令增强

- Dependencies:
  - `src/data/providers/account_aggregator.py` - 账户数据聚合
  - `src/engine/strategy/factory.py` - 策略创建和指标计算
  - `src/engine/portfolio/` - 组合级计算
  - `src/engine/account/sentiment/` - 市场情绪分析
