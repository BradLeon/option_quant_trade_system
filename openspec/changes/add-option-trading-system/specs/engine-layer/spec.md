## ADDED Requirements

### Requirement: Greeks Calculation

系统 SHALL 能够计算期权的 Greeks 指标，包括 Delta、Gamma、Theta、Vega 和 Rho。

#### Scenario: 计算单个期权的 Greeks
- **WHEN** 用户请求计算某个期权合约的 Greeks
- **THEN** 系统基于 Black-Scholes 模型返回 Delta、Gamma、Theta、Vega、Rho
- **AND** 计算耗时不超过 100ms

#### Scenario: 批量计算期权链 Greeks
- **WHEN** 用户请求计算整个期权链的 Greeks
- **THEN** 系统并行计算所有合约的 Greeks
- **AND** 结果包含每个合约的完整 Greeks 数据

### Requirement: Implied Volatility Calculation

系统 SHALL 能够从期权市场价格反推隐含波动率。

#### Scenario: 计算隐含波动率
- **WHEN** 给定期权的市场价格、标的价格、行权价、到期时间、无风险利率
- **THEN** 系统使用数值方法（如牛顿迭代）计算隐含波动率
- **AND** 迭代次数不超过 100 次，精度达到 0.0001

#### Scenario: 处理无法收敛的情况
- **WHEN** 隐含波动率计算无法收敛（如深度实值/虚值期权）
- **THEN** 系统返回 None 并记录警告日志

### Requirement: Option Screening Engine

系统 SHALL 提供期权筛选引擎，根据多种条件筛选合适的期权合约。

#### Scenario: 按 Delta 范围筛选
- **WHEN** 用户设置筛选条件 Delta 在 -0.3 到 -0.2 之间
- **THEN** 系统返回所有符合条件的 Put 期权

#### Scenario: 按到期日范围筛选
- **WHEN** 用户设置筛选条件为 30-45 天后到期
- **THEN** 系统返回在此时间范围内到期的所有期权

#### Scenario: 按流动性筛选
- **WHEN** 用户设置最低成交量要求（如日成交 > 100）
- **THEN** 系统仅返回流动性达标的期权

#### Scenario: 组合多条件筛选
- **WHEN** 用户同时设置 Delta、到期日、流动性等多个条件
- **THEN** 系统返回同时满足所有条件的期权
- **AND** 结果按指定字段排序（如按 Theta 降序）

### Requirement: Risk Metrics Calculation

系统 SHALL 能够计算组合级别的风险指标。

#### Scenario: 计算组合 Delta
- **WHEN** 用户持有多个期权头寸
- **THEN** 系统计算组合的总 Delta 敞口
- **AND** 显示对标的资产价格变动 1% 时的预估盈亏

#### Scenario: 计算最大潜在亏损
- **WHEN** 用户持有 Short Put 头寸
- **THEN** 系统计算如果标的价格归零时的最大亏损
- **AND** 显示保证金占用情况

#### Scenario: 计算盈亏平衡点
- **WHEN** 用户持有期权头寸
- **THEN** 系统计算该头寸的盈亏平衡价格

### Requirement: Signal Generation Interface

系统 SHALL 定义统一的信号生成接口，供业务层策略调用。

#### Scenario: 生成开仓信号
- **WHEN** 策略判断符合开仓条件
- **THEN** 系统生成包含以下信息的开仓信号：
  - 信号类型（开仓）
  - 标的代码
  - 期权合约详情（行权价、到期日、类型）
  - 建议数量
  - 当前价格
  - 理由说明

#### Scenario: 生成平仓信号
- **WHEN** 策略判断符合平仓条件
- **THEN** 系统生成包含以下信息的平仓信号：
  - 信号类型（平仓）
  - 持仓标识
  - 当前盈亏
  - 平仓理由
