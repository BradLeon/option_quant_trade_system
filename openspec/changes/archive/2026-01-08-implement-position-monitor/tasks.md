## 1. 数据转换层 (Data Bridge)

- [x] 1.1 创建 `src/business/monitoring/data_bridge.py`
  - 定义 `MonitoringDataBridge` 类
  - 实现 `convert_positions()` 方法
  - 实现批量波动率数据预获取 `_prefetch_volatility()`

- [x] 1.2 扩展 `PositionData` 模型
  - 添加策略指标字段 (sas, roc, expected_roc, sharpe, kelly, strategy_type)
  - 添加股票分析字段 (trend_signal, rsi_zone, iv_rank, iv_hv_ratio, volatility_score, fundamental_score)

- [x] 1.3 实现期权持仓转换
  - 集成 `create_strategies_from_position()` 获取策略实例
  - 调用 `strategy.calc_metrics()` 获取 `StrategyMetrics`
  - 填充 PREI/TGR/SAS/ROC/Kelly 到 `PositionData`

- [x] 1.4 实现股票持仓转换 (使用统一出口算子)
  - 调用 `evaluate_volatility(StockVolatility)` → `VolatilityScore`
  - 调用 `calc_technical_score(TechnicalData)` → `TechnicalScore`
  - 调用 `evaluate_fundamentals(Fundamental)` → `FundamentalScore`
  - 从返回的 Score 模型中提取字段填充到 `PositionData`

- [ ] 1.5 编写 `data_bridge` 单元测试

## 2. 调整建议生成

- [x] 2.1 创建 `src/business/monitoring/suggestions.py`
  - 定义 `ActionType` 枚举 (HOLD, MONITOR, CLOSE, REDUCE, ROLL, HEDGE, ADJUST, SET_STOP, REVIEW, DIVERSIFY, TAKE_PROFIT)
  - 定义 `UrgencyLevel` 枚举 (IMMEDIATE, SOON, MONITOR)
  - 定义 `PositionSuggestion` 数据类
  - 定义 `SuggestionGenerator` 类

- [x] 2.2 实现 ALERT_ACTION_MAP 配置 (Position-Level)
  - DTE ≤ 3 → ROLL/CLOSE, IMMEDIATE
  - DTE 4-7 → ROLL, SOON
  - PREI > 75 → REDUCE/HEDGE, IMMEDIATE
  - PREI 40-75 → MONITOR, MONITOR
  - SAS < 30 → CLOSE, SOON
  - |Delta| > 0.8 → CLOSE, IMMEDIATE
  - |Delta| > 0.5 → ADJUST, SOON
  - 止损触发 → CLOSE, IMMEDIATE

- [x] 2.3 实现 ALERT_ACTION_MAP 配置 (Portfolio/Capital-Level)
  - Portfolio Delta$ > 10% NAV → HEDGE, SOON
  - TGR < 0.3 → ADJUST, SOON
  - 集中度 HHI > 0.5 → DIVERSIFY, SOON
  - 保证金使用率 > 80% → REDUCE, IMMEDIATE
  - 保证金使用率 50-80% → REVIEW, SOON

- [x] 2.4 实现市场环境调整
  - 获取市场情绪 (`get_us_sentiment()` / `get_hk_sentiment()`)
  - 高波动环境下提高风险建议优先级

- [ ] 2.5 编写 `suggestions` 单元测试

## 3. 监控流程增强

- [x] 3.1 增强 `MonitoringPipeline`
  - 添加 `data_bridge` 参数
  - 添加 `suggestion_generator` 参数
  - 在 `run()` 方法末尾生成调整建议

- [x] 3.2 增强 `PositionMonitor` (Position-Level Metrics)
  - 添加 DTE 监控 (`_check_dte()`) - 阈值: ≤3 RED, 4-7 YELLOW
  - 添加 PREI 监控 (`_check_prei()`) - 阈值: >75 RED, 40-75 YELLOW
  - 添加 SAS 监控 (`_check_sas()`) - 阈值: <30 RED, 30-50 YELLOW
  - 添加 Delta 监控 (`_check_delta()`) - 阈值: |Δ|>0.8 RED, |Δ|>0.5 YELLOW
  - 添加 Kelly 使用率监控 (`_check_kelly_usage()`)

- [x] 3.3 增强 `PortfolioMonitor` (Portfolio-Level Metrics)
  - 集成 `calc_delta_dollars()` - 阈值: Delta$ > 10% NAV YELLOW
  - 集成 `calc_portfolio_tgr()` - 阈值: TGR < 0.3 YELLOW, TGR < 0.1 RED
  - 集成 `calc_concentration_risk()` - 阈值: HHI > 0.5 YELLOW, HHI > 0.7 RED
  - 集成组合 Greeks 汇总 (gamma, theta, vega)

- [x] 3.4 增强 `MonitorResult`
  - 添加 `suggestions: list[PositionSuggestion]` 字段
  - 添加 `market_sentiment: MarketSentiment | None` 字段

## 4. CLI 命令增强

- [x] 4.1 增强 `monitor` 命令参数
  - 添加 `--account-type` (paper/real)
  - 添加 `--ibkr-only` / `--futu-only`
  - 添加 `--output` (table/json)
  - 添加 `-v` / `--verbose`

- [x] 4.2 实现账户连接和数据获取
  - 使用 `AccountAggregator` 获取持仓
  - 处理连接失败情况

- [x] 4.3 实现报告输出格式化
  - 账户概览表格
  - 持仓列表表格
  - 组合 Greeks 汇总
  - 预警列表（颜色编码）
  - 调整建议列表

- [x] 4.4 实现详细输出模式
  - 每个持仓的完整指标
  - 策略分类详情
  - 数据获取日志

## 5. 测试与验证

- [ ] 5.1 编写集成测试
  - 端到端测试：账户获取 → 转换 → 监控 → 建议
  - Mock 数据提供者测试

- [ ] 5.2 使用真实 Paper 账户验证
  - 连接 IBKR Paper 账户
  - 验证完整监控流程
  - 验证输出格式正确性

- [ ] 5.3 更新 `verify_position_strategies.py`
  - 添加监控流程集成测试选项

## 验证检查清单

- [x] `data_bridge` 正确转换所有持仓类型
- [x] 期权持仓包含完整策略指标
- [x] 股票持仓包含技术面和波动率分析
- [x] 调整建议基于预警正确生成
- [x] CLI 命令可正常连接账户并输出报告
- [ ] 单元测试覆盖核心逻辑
- [ ] 集成测试验证完整流程
