## ADDED Requirements

### Requirement: Strategy Base Interface

系统 SHALL 定义策略基类接口，所有具体策略 MUST 实现此接口。

#### Scenario: 策略接口定义
- **WHEN** 开发新策略
- **THEN** 策略 MUST 实现以下方法：
  - `initialize()` - 策略初始化
  - `on_data(data)` - 数据更新回调
  - `check_entry_conditions()` - 检查开仓条件
  - `check_exit_conditions()` - 检查平仓条件
  - `generate_signals()` - 生成交易信号

### Requirement: Short Put Strategy

系统 SHALL 实现 Short Put（卖出看跌期权）策略。

#### Scenario: Short Put 开仓条件判断
- **WHEN** 系统评估 Short Put 开仓机会
- **THEN** 检查以下条件：
  - 标的处于上涨或震荡趋势
  - 期权 Delta 在目标范围内（如 -0.3 到 -0.2）
  - 到期日在目标范围内（如 30-45 天）
  - 隐含波动率处于合理水平
  - 流动性满足最低要求
- **AND** 所有条件满足时生成开仓信号

#### Scenario: Short Put 止盈平仓
- **WHEN** Short Put 头寸已获得目标收益（如 50% 权利金）
- **THEN** 系统生成平仓信号
- **AND** 记录平仓理由为"止盈"

#### Scenario: Short Put 止损平仓
- **WHEN** Short Put 头寸亏损达到阈值（如 200% 权利金）
- **THEN** 系统生成平仓信号
- **AND** 记录平仓理由为"止损"

#### Scenario: Short Put 到期前平仓
- **WHEN** Short Put 头寸距到期不足 7 天
- **THEN** 系统生成平仓信号（无论盈亏）
- **AND** 记录平仓理由为"到期前平仓"

### Requirement: Covered Call Strategy

系统 SHALL 实现 Covered Call（持股卖出看涨期权）策略。

#### Scenario: Covered Call 开仓条件判断
- **WHEN** 用户持有正股且系统评估 Covered Call 开仓机会
- **THEN** 检查以下条件：
  - 用户持有足够的正股（每手期权对应 100 股）
  - 期权 Delta 在目标范围内（如 0.2 到 0.3）
  - 到期日在目标范围内
  - 行权价高于当前价格一定比例
- **AND** 所有条件满足时生成开仓信号

#### Scenario: Covered Call 止盈平仓
- **WHEN** Covered Call 头寸已获得目标收益
- **THEN** 系统生成平仓信号

#### Scenario: Covered Call 正股可能被行权
- **WHEN** 正股价格接近或超过行权价且临近到期
- **THEN** 系统生成预警信号
- **AND** 提示用户考虑是否移仓或接受行权

### Requirement: Rotation Strategy

系统 SHALL 实现 Short Put 和 Covered Call 的轮动策略。

#### Scenario: 从 Short Put 轮动到 Covered Call
- **WHEN** Short Put 被行权（用户获得正股）
- **THEN** 系统自动评估 Covered Call 开仓机会
- **AND** 生成 Covered Call 开仓建议

#### Scenario: 从 Covered Call 轮动到 Short Put
- **WHEN** Covered Call 被行权（正股被卖出）
- **THEN** 系统自动评估 Short Put 开仓机会
- **AND** 生成 Short Put 开仓建议

#### Scenario: 市场状态驱动的轮动
- **WHEN** 市场趋势发生明显变化
- **THEN** 系统根据趋势推荐策略切换
- **AND** 提供切换理由

### Requirement: Position Management

系统 SHALL 提供持仓管理功能，跟踪所有期权头寸的状态。

#### Scenario: 记录新开仓
- **WHEN** 用户确认执行开仓信号
- **THEN** 系统记录持仓信息：
  - 合约详情
  - 开仓价格和数量
  - 开仓时间
  - 开仓理由
  - 止盈止损设置

#### Scenario: 更新持仓状态
- **WHEN** 市场数据更新
- **THEN** 系统更新所有持仓的：
  - 当前市值
  - 浮动盈亏
  - 当前 Greeks

#### Scenario: 记录平仓
- **WHEN** 用户确认执行平仓
- **THEN** 系统记录平仓信息并计算实现盈亏

### Requirement: Position Monitoring

系统 SHALL 实时监控持仓并在必要时发出预警。

#### Scenario: Greeks 预警
- **WHEN** 持仓 Delta 超出预设阈值
- **THEN** 系统发出风险预警

#### Scenario: 亏损预警
- **WHEN** 持仓亏损达到预设比例
- **THEN** 系统发出止损预警

#### Scenario: 到期日预警
- **WHEN** 持仓距到期不足 N 天（可配置）
- **THEN** 系统发出到期提醒

### Requirement: Backtesting Framework

系统 SHALL 提供策略回测功能，验证策略在历史数据上的表现。

#### Scenario: 运行策略回测
- **WHEN** 用户选择策略和回测时间范围
- **THEN** 系统在历史数据上模拟策略执行
- **AND** 生成回测报告，包含：
  - 总收益率
  - 年化收益率
  - 最大回撤
  - 夏普比率
  - 胜率
  - 盈亏比

#### Scenario: 回测参数优化
- **WHEN** 用户指定参数范围
- **THEN** 系统遍历参数组合进行回测
- **AND** 返回最优参数组合
