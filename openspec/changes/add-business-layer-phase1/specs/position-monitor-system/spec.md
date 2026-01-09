## ADDED Requirements

### Requirement: Portfolio Level Monitor

系统 SHALL 实现组合级监控器，监控整体持仓组合的风险敞口。

#### Scenario: Beta 加权 Delta 监控
- **WHEN** 系统监控组合方向性风险
- **THEN** 系统 MUST 计算 Beta 加权 Delta 总和（以 SPY 为基准）
- **AND** 如果 |Beta-Weighted Delta| < 100，状态为"正常"（绿色）
- **AND** 如果 |Beta-Weighted Delta| 在 100-300 之间，状态为"关注"（黄色）
- **AND** 如果 |Beta-Weighted Delta| > 300，状态为"风险"（红色），触发预警

#### Scenario: 组合 Theta 监控
- **WHEN** 系统监控组合时间价值收益
- **THEN** 系统 MUST 计算组合总 Theta
- **AND** 输出每日预期时间价值收益（美元）
- **AND** 如果总 Theta 为负（净买方头寸），标记为"警告"

#### Scenario: 组合 Vega 监控
- **WHEN** 系统监控组合波动率风险
- **THEN** 系统 MUST 计算组合总 Vega
- **AND** 输出 IV 变动 1% 时的损益影响
- **AND** 对于净卖方策略（总 Vega 为负），检查 IV 是否处于高位（利于 IV 回落获利）

#### Scenario: 组合 Gamma 监控
- **WHEN** 系统监控组合凸性风险
- **THEN** 系统 MUST 计算组合总 Gamma
- **AND** 如果 Gamma < -50，状态为"风险"，标记"凸性风险过高"
- **AND** 如果 Gamma 在 -50 到 -30 之间，状态为"关注"

#### Scenario: 组合 TGR（Theta/Gamma 比率）监控
- **WHEN** 系统评估组合风险收益比
- **THEN** 系统 MUST 计算 Portfolio TGR = Theta / |Gamma * 100|
- **AND** 如果 TGR > 0.15，状态为"健康"
- **AND** 如果 TGR 在 0.05-0.15 之间，状态为"关注"
- **AND** 如果 TGR < 0.05，状态为"风险"，标记"收益风险比失衡"

#### Scenario: 持仓相关性监控
- **WHEN** 系统评估持仓集中度风险
- **THEN** 系统 MUST 计算持仓之间的相关性
- **AND** 如果相关性加权 Delta > 1.5 倍简单 Delta 之和，标记"集中度过高"
- **AND** 建议增加负相关标的或减少同向头寸

### Requirement: Position Level Monitor

系统 SHALL 实现持仓级监控器，监控每个期权头寸的风险状态。

#### Scenario: Moneyness 监控
- **WHEN** 系统监控期权价内外程度
- **THEN** 系统 MUST 计算 Moneyness = (S - K) / K
- **AND** 对于 Short Put：
  - 如果 Moneyness > 5%，状态为"安全"
  - 如果 Moneyness 在 0%-5% 之间，状态为"关注"
  - 如果 Moneyness < 0%（ITM），状态为"风险"，触发行权预警

#### Scenario: Delta 变化监控
- **WHEN** 系统监控期权 Delta
- **THEN** 系统 MUST 跟踪 Delta 数值
- **AND** 对于 Short Put，如果 |Delta| > 0.5，触发"行权概率过高"预警
- **AND** 如果 |Delta| 较上次检查变化超过 0.1，标记"Delta 快速变化"

#### Scenario: Gamma 风险监控
- **WHEN** 系统监控个股期权 Gamma
- **THEN** 系统 MUST 跟踪 Gamma 数值
- **AND** 如果 |Gamma| > 0.05，状态为"高风险"
- **AND** 如果 |Gamma| > 0.03 且 DTE < 14，状态为"风险"，标记"临期 Gamma 风险"

#### Scenario: IV/HV 比值监控
- **WHEN** 系统评估期权波动率择时
- **THEN** 系统 MUST 计算当前 IV/HV 比值
- **AND** 如果 IV/HV > 1.5，对卖方标记"波动率溢价高"（利好）
- **AND** 如果 IV/HV < 0.8，对卖方标记"IV 偏低"（考虑平仓）

#### Scenario: PREI（风险暴露指数）监控
- **WHEN** 系统评估持仓综合风险
- **THEN** 系统 MUST 计算 PREI = w1×|Gamma| + w2×|Vega| + w3×(1/DTE)^0.5
- **AND** 如果 PREI > 75，状态为"高风险"，触发预警
- **AND** 如果 PREI 在 40-75 之间，状态为"关注"
- **AND** 如果 PREI < 40，状态为"安全"

#### Scenario: TGR（Theta/Gamma 比率）监控
- **WHEN** 系统评估单个持仓收益风险比
- **THEN** 系统 MUST 计算 TGR = Theta / |Gamma * 100|
- **AND** 标记 TGR 状态（高效 / 一般 / 低效）

#### Scenario: DTE 到期提醒
- **WHEN** 系统监控期权到期日
- **THEN** 系统 MUST 跟踪剩余到期天数
- **AND** 如果 DTE <= 7，触发"即将到期"预警
- **AND** 如果 DTE <= 3，触发"紧急"预警，建议立即处理

#### Scenario: 盈亏监控
- **WHEN** 系统监控持仓盈亏
- **THEN** 系统 MUST 计算以下盈亏指标：
  - 当前市值
  - 浮动盈亏（金额和百分比）
  - 与开仓权利金的对比
- **AND** 如果盈利达到 50% 权利金，触发"止盈信号"
- **AND** 如果亏损达到 200% 权利金，触发"止损信号"

### Requirement: Capital Level Monitor

系统 SHALL 实现资金级监控器，评估策略和资金使用效率。

#### Scenario: 夏普比率监控
- **WHEN** 系统评估策略性价比
- **THEN** 系统 MUST 计算组合夏普比率
- **AND** 如果夏普比率 >= 1.5，状态为"优秀"
- **AND** 如果夏普比率在 1.0-1.5 之间，状态为"关注"
- **AND** 如果夏普比率 < 1.0，状态为"风险"，标记"策略低效"

#### Scenario: Kelly 使用率监控
- **WHEN** 系统评估仓位使用效率
- **THEN** 系统 MUST 计算当前仓位占 Kelly 最优仓位的比例
- **AND** 如果使用率 > 100%，状态为"风险"，标记"过度杠杆"
- **AND** 如果使用率在 50%-100% 之间，状态为"合理"
- **AND** 如果使用率 < 50%，标记"可加仓机会"

#### Scenario: 保证金使用率监控
- **WHEN** 系统监控资金使用情况
- **THEN** 系统 MUST 计算保证金使用率 = 已用保证金 / 可用资金
- **AND** 如果使用率 > 80%，触发"保证金紧张"预警
- **AND** 如果使用率 > 90%，触发"紧急"预警

#### Scenario: 最大回撤监控
- **WHEN** 系统监控账户最大回撤
- **THEN** 系统 MUST 跟踪账户净值高点和当前回撤
- **AND** 如果回撤超过配置阈值（默认 10%），触发预警

### Requirement: Alert Generation

系统 SHALL 实现预警生成器，将监控结果转化为可操作的预警信号。

#### Scenario: 预警分级
- **WHEN** 监控指标触发阈值
- **THEN** 系统 MUST 生成分级预警：
  - **红色（紧急）**: 需要立即处理（如止损、临期处理）
  - **黄色（关注）**: 需要密切关注（如 Delta 升高、PREI 升高）
  - **绿色（机会）**: 发现机会（如可加仓、波动率套利）

#### Scenario: 预警内容结构
- **WHEN** 系统生成预警
- **THEN** 预警 MUST 包含以下信息：
  - alert_type: 预警类型（risk/opportunity/info）
  - alert_level: 预警级别（red/yellow/green）
  - symbol: 相关标的
  - indicator: 触发预警的指标
  - current_value: 当前指标值
  - threshold: 阈值
  - suggested_action: 建议操作
  - timestamp: 触发时间

#### Scenario: 预警去重
- **WHEN** 同一指标多次触发预警
- **THEN** 系统 MUST 实现去重机制：
  - 同一持仓同一指标在配置时间内（默认 30 分钟）不重复告警
  - 如果指标恶化（级别升高），立即发送新预警

### Requirement: Dynamic Threshold Adjustment

系统 SHALL 支持基于市场状态动态调整监控阈值。

#### Scenario: 高波动率环境调整
- **WHEN** VIX > 28（高波动率环境）
- **THEN** 系统 MUST 自动调整阈值：
  - 收紧 Gamma 阈值（|Gamma| > 0.03 即为高风险）
  - 收紧 Delta 阈值（更早干预接近平价的持仓）
  - 降低 Kelly 系数（使用 1/4 Kelly）

#### Scenario: 趋势环境调整
- **WHEN** ADX > 25（趋势明显）
- **THEN** 系统 MUST 调整阈值：
  - 收紧逆势仓位的风险阈值
  - 放宽顺势仓位的风险阈值
  - 提高 Delta 监控敏感度

#### Scenario: 震荡环境调整
- **WHEN** ADX < 20（震荡行情）
- **THEN** 系统 MUST 调整阈值：
  - 放宽 Gamma 阈值（震荡行情 Gamma 风险较低）
  - 提高 Theta 效率要求
  - 关注边界风险（支撑/阻力位）

### Requirement: Monitor CLI

系统 SHALL 提供命令行接口，支持手动触发监控。

#### Scenario: 运行监控命令
- **WHEN** 用户执行监控命令
- **THEN** 系统 MUST 支持以下命令格式：
  ```bash
  python -m src.business.cli monitor \
    --positions positions.json \
    --config config/monitoring/default.yaml \
    --output table
  ```
- **AND** 输出监控结果到控制台

#### Scenario: 持仓文件格式
- **WHEN** 用户提供持仓文件
- **THEN** 系统 MUST 支持以下 JSON 格式：
  ```json
  {
    "positions": [
      {
        "symbol": "AAPL",
        "option_type": "put",
        "strike": 180,
        "expiry": "2024-02-16",
        "quantity": -2,
        "entry_price": 3.50,
        "entry_date": "2024-01-15"
      }
    ],
    "account": {
      "available_capital": 100000,
      "margin_used": 15000
    }
  }
  ```

#### Scenario: 监控报告输出
- **WHEN** 监控完成
- **THEN** 系统 MUST 输出包含以下内容的报告：
  - 组合级指标摘要（表格）
  - 持仓级指标详情（表格）
  - 预警列表（按级别排序）
  - 市场状态概览
