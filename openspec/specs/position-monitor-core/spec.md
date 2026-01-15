# position-monitor-core Specification

## Purpose
TBD - created by archiving change implement-position-monitor. Update Purpose after archive.
## Requirements
### Requirement: Data Bridge for Position Conversion

系统 SHALL 实现数据转换桥接器，将账户持仓转换为监控输入数据。

#### Scenario: AccountPosition 批量转换
- **GIVEN** 系统获取到 `ConsolidatedPortfolio` 包含多个 `AccountPosition`
- **WHEN** 调用 `MonitoringDataBridge.convert_positions(portfolio)`
- **THEN** 系统 MUST 返回 `list[PositionData]`
- **AND** 每个 `PositionData` 包含完整的监控所需字段
- **AND** 期权持仓包含 PREI/TGR/SAS 等策略指标
- **AND** 股票持仓包含技术面分析结果

#### Scenario: 波动率数据批量获取
- **GIVEN** 持仓中包含多个不同标的
- **WHEN** 系统转换持仓数据
- **THEN** 系统 MUST 批量获取所有标的的波动率数据
- **AND** 使用缓存避免重复 API 调用
- **AND** 获取失败时记录警告但不中断流程

#### Scenario: 策略指标计算
- **GIVEN** 一个期权 `AccountPosition`
- **WHEN** 系统转换为 `PositionData`
- **THEN** 系统 MUST 调用 `create_strategies_from_position()` 创建策略
- **AND** 调用 `strategy.calc_metrics()` 获取 `StrategyMetrics`
- **AND** 将 PREI/TGR/SAS/ROC/Sharpe/Kelly 填充到 `PositionData`

### Requirement: Option Position Enhanced Monitoring

系统 SHALL 增强期权持仓监控，集成策略指标评估。

#### Scenario: 策略吸引力评估 (SAS)
- **WHEN** 系统评估期权持仓的策略吸引力
- **THEN** 系统 MUST 获取 `StrategyMetrics.sas`
- **AND** 如果 SAS < 30，状态为"不推荐"，建议考虑平仓
- **AND** 如果 SAS 在 30-50 之间，状态为"一般"
- **AND** 如果 SAS >= 50，状态为"推荐"

#### Scenario: 预期收益评估 (Expected ROC)
- **WHEN** 系统评估期权持仓的收益潜力
- **THEN** 系统 MUST 获取 `StrategyMetrics.expected_roc`
- **AND** 显示年化预期收益率
- **AND** 与当前 ROC 对比，评估持仓效率

#### Scenario: Kelly 仓位评估
- **WHEN** 系统评估期权持仓的仓位合理性
- **THEN** 系统 MUST 获取 `StrategyMetrics.kelly_fraction`
- **AND** 计算当前仓位占 Kelly 建议仓位的比例
- **AND** 如果超过 100%，标记"过度杠杆"

### Requirement: Stock Position Analysis

系统 SHALL 对股票持仓进行多维度分析。

#### Scenario: 技术面分析
- **GIVEN** 一个股票 `AccountPosition`
- **WHEN** 系统分析该持仓
- **THEN** 系统 MUST 获取历史 K 线数据
- **AND** 调用 `calc_technical_score()` 计算技术评分
- **AND** 输出趋势信号（bullish/bearish/neutral）
- **AND** 输出 RSI zone、MA alignment

#### Scenario: 波动率分析
- **GIVEN** 一个股票持仓
- **WHEN** 系统分析该持仓
- **THEN** 系统 MUST 获取 `StockVolatility`
- **AND** 输出 IV Rank/IV Percentile
- **AND** 输出 HV/IV 比值
- **AND** 对于期权卖方策略，评估波动率环境是否有利

### Requirement: Position Adjustment Suggestions

系统 SHALL 基于监控结果生成持仓调整建议。

#### Scenario: 红色预警处理
- **GIVEN** 监控结果包含红色预警
- **WHEN** 系统生成调整建议
- **THEN** 系统 MUST 为每个红色预警生成"立即处理"建议
- **AND** 建议包含具体行动（平仓/展期/对冲）
- **AND** 建议包含原因说明

#### Scenario: 黄色预警处理
- **GIVEN** 监控结果包含黄色预警
- **WHEN** 系统生成调整建议
- **THEN** 系统 MUST 为每个黄色预警生成"密切关注"建议
- **AND** 建议包含触发条件和观察要点

#### Scenario: 市场环境调整
- **GIVEN** 系统获取到市场情绪数据
- **WHEN** 生成调整建议
- **THEN** 系统 MAY 根据市场情绪调整建议优先级
- **AND** 高波动率环境下提高风险建议优先级
- **AND** 趋势明确时调整方向性建议

### Requirement: CLI Monitor Command Enhancement

系统 SHALL 增强 CLI monitor 命令，支持真实账户监控。

#### Scenario: 从真实账户监控
- **WHEN** 用户执行 `python -m src.business.cli monitor --account-type paper`
- **THEN** 系统 MUST 连接到 IBKR/Futu
- **AND** 获取真实账户持仓
- **AND** 执行完整监控流程
- **AND** 输出格式化的监控报告

#### Scenario: 监控报告输出
- **WHEN** 监控完成
- **THEN** 系统 MUST 输出包含以下内容：
  - 账户概览（总资产、保证金使用率）
  - 持仓列表（股票 + 期权）
  - 组合 Greeks 汇总
  - 预警列表（按级别排序）
  - 调整建议（按紧急程度排序）

#### Scenario: 详细输出模式
- **WHEN** 用户添加 `-v` 或 `--verbose` 参数
- **THEN** 系统 MUST 输出详细信息：
  - 每个持仓的完整指标
  - 策略分类和指标详情
  - 数据获取日志

### Requirement: PositionData Model Extension

系统 SHALL 扩展 `PositionData` 模型，添加策略指标字段以支持增强监控。

#### Scenario: 策略指标字段
- **WHEN** 系统创建期权 `PositionData`
- **THEN** 模型 MUST 包含以下字段：
  - `sas: float | None` - 策略吸引力分数
  - `roc: float | None` - 当前资本收益率
  - `expected_roc: float | None` - 预期资本收益率
  - `sharpe: float | None` - 夏普比率
  - `kelly: float | None` - Kelly 建议仓位
  - `strategy_type: str | None` - 策略类型

#### Scenario: 股票分析字段
- **WHEN** 系统创建股票 `PositionData`
- **THEN** 模型 MUST 包含以下字段：
  - `trend_signal: str | None` - 趋势信号
  - `rsi_zone: str | None` - RSI 区域
  - `iv_rank: float | None` - IV 排名
  - `iv_hv_ratio: float | None` - IV/HV 比值
  - `volatility_score: float | None` - 波动率评分
  - `fundamental_score: float | None` - 基本面评分

