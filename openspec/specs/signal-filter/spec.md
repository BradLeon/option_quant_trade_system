# signal-filter Specification

## Purpose
TBD - created by archiving change add-signal-filter-system. Update Purpose after archive.
## Requirements
### Requirement: Stock Pool Management

系统 SHALL 提供配置驱动的股票池管理，支持预定义和自定义的标的候选集。

#### Scenario: 加载预定义股票池
- **WHEN** 用户指定股票池名称 `us_default`
- **THEN** 系统从配置文件加载对应的股票列表
- **AND** 返回 `["SPY", "QQQ", "AAPL", ...]`

#### Scenario: 列出可用股票池
- **WHEN** 用户查询可用股票池
- **THEN** 系统返回所有配置的股票池名称
- **AND** 包含 `us_default`, `us_large_cap`, `hk_default`, `hk_large_cap` 等

#### Scenario: 获取默认股票池
- **WHEN** 用户未指定股票池且市场类型为 US
- **THEN** 系统返回 `us_default` 池中的股票列表

#### Scenario: CLI --pool 选项
- **WHEN** 用户执行 `screen --pool us_large_cap`
- **THEN** 系统使用指定股票池进行筛选
- **AND** 忽略默认股票列表

### Requirement: Three-Layer Signal Filter Pipeline

系统 SHALL 实现三层信号过滤管道，用于期权卖方策略（Covered Call / Cash-Secured Put / Wheel）的开仓筛选。

#### Scenario: 完整筛选流程
- **WHEN** 用户启动筛选流程
- **THEN** 系统依次执行：Layer 1 市场过滤 → Layer 2 标的过滤 → Layer 3 合约过滤
- **AND** 任一层的 P0/P1 条件不满足时，后续层不执行

#### Scenario: 市场过滤阻断
- **WHEN** Layer 1 市场过滤返回 `is_favorable=False`
- **THEN** 系统记录不利原因
- **AND** 返回空的候选合约列表
- **AND** 建议用户等待市场环境改善

### Requirement: Market Filter with Macro Event Blackout

系统 SHALL 在市场过滤层检查宏观事件日历，在重大事件发布前暂停开仓。

#### Scenario: FOMC 前暂停开仓
- **WHEN** 距下一次 FOMC 利率决议少于 3 天
- **THEN** `MarketStatus.is_favorable` 返回 `False`
- **AND** `unfavorable_reasons` 包含 "FOMC 会议临近，暂停开仓"

#### Scenario: CPI 发布前暂停开仓
- **WHEN** 距下一次 CPI 数据发布少于 3 天
- **THEN** `MarketStatus.is_favorable` 返回 `False`
- **AND** `unfavorable_reasons` 包含 "CPI 数据发布临近，暂停开仓"

#### Scenario: 非农数据前暂停开仓
- **WHEN** 距下一次非农就业数据发布少于 3 天
- **THEN** `MarketStatus.is_favorable` 返回 `False`
- **AND** `unfavorable_reasons` 包含 "非农数据发布临近，暂停开仓"

#### Scenario: 宏观事件后恢复
- **WHEN** 宏观事件已过去
- **THEN** 宏观事件检查通过
- **AND** 市场过滤继续评估其他条件

### Requirement: Underlying Filter with Earnings Calendar

系统 SHALL 在标的过滤层检查财报日历，回避财报公布前后的二元风险。

#### Scenario: 财报日过近时排除
- **WHEN** 标的距下一财报日少于 7 天
- **THEN** `UnderlyingScore.passed` 返回 `False`
- **AND** `disqualify_reasons` 包含 "距财报发布不足 7 天"

#### Scenario: 合约在财报前到期时通过
- **WHEN** 标的距下一财报日少于 7 天
- **AND** 候选合约的到期日早于财报日
- **THEN** 该标的可进入合约过滤层
- **AND** 仅筛选在财报前到期的合约

#### Scenario: 无财报日期时通过
- **WHEN** 标的的 `earnings_date` 为 `None`
- **THEN** 财报检查通过
- **AND** 记录 "无财报日期信息" 的提示

### Requirement: Underlying Filter with Ex-Dividend Check

系统 SHALL 在标的过滤层检查除息日，对 Covered Call 策略评估提前行权风险。

#### Scenario: 除息日检查 (Covered Call)
- **WHEN** 策略类型为 Covered Call
- **AND** 标的距下一除息日少于 7 天
- **THEN** `UnderlyingScore.passed` 返回 `False`
- **AND** `disqualify_reasons` 包含 "距除息日不足 7 天，ITM Call 可能被提前行权"

#### Scenario: 除息日检查 (Cash-Secured Put)
- **WHEN** 策略类型为 Cash-Secured Put
- **THEN** 除息日检查跳过（不影响 Put 策略）

### Requirement: Contract Liquidity Metrics

系统 SHALL 计算合约流动性指标，用于过滤低流动性合约。

#### Scenario: 计算 Bid-Ask Spread
- **WHEN** 用户请求合约的流动性评估
- **THEN** 系统计算 `bid_ask_spread = (ask - bid) / mid * 100`
- **AND** 返回百分比形式

#### Scenario: Spread 过大时排除
- **WHEN** 合约的 Bid-Ask Spread > 10%
- **THEN** `ContractOpportunity.passed` 返回 `False`
- **AND** `disqualify_reasons` 包含 "Bid-Ask Spread 过大"

#### Scenario: 期权链成交量检查
- **WHEN** 评估标的期权链流动性
- **THEN** 系统计算期权链总成交量（当日或昨日）
- **AND** 成交量 < 5000 时记录警告

### Requirement: Strike Selection Metrics

系统 SHALL 计算行权价选择相关指标，支持智能 Strike 推荐。

#### Scenario: 计算 OTM 百分比
- **WHEN** 用户请求 Put 合约的 OTM 百分比
- **THEN** 系统计算 `otm_percent = (spot - strike) / spot * 100`
- **AND** 返回百分比形式

#### Scenario: 计算支撑位距离
- **WHEN** 用户请求支撑位距离
- **THEN** 系统计算 `support_distance = (price - support) / price * 100`
- **AND** 返回百分比形式

#### Scenario: Strike 位置验证
- **WHEN** 用户选择 Put Strike
- **THEN** 系统检查 Strike < 最近支撑位
- **AND** 不满足时记录警告

### Requirement: Risk-Return Validation

系统 SHALL 计算收益风险指标，排除期望收益为负的合约。

#### Scenario: 期望收益检查
- **WHEN** 合约的 `expected_roc < 0`
- **THEN** `ContractOpportunity.passed` 返回 `False`
- **AND** `disqualify_reasons` 包含 "期望收益为负"

#### Scenario: TGR 检查
- **WHEN** 合约的 `tgr < 0.10`
- **THEN** `ContractOpportunity.passed` 返回 `False`
- **AND** `disqualify_reasons` 包含 "Theta/Gamma 风险比过低"

#### Scenario: Sharpe 比率检查
- **WHEN** 合约的 `sharpe_ratio < 1.0`
- **THEN** 记录警告（不强制排除）
- **AND** 降低合约评分

### Requirement: Signal Filter Configuration

系统 SHALL 提供可配置的过滤器参数，支持不同风险偏好。

#### Scenario: 配置宏观事件黑名单
- **WHEN** 用户配置 `blackout_events = ["FOMC", "CPI"]`
- **THEN** 仅这些事件类型触发开仓暂停
- **AND** 其他事件类型不影响过滤

#### Scenario: 配置财报回避天数
- **WHEN** 用户配置 `min_days_to_earnings = 10`
- **THEN** 距财报少于 10 天的标的被过滤

#### Scenario: 配置流动性阈值
- **WHEN** 用户配置 `max_bid_ask_spread = 0.15`
- **THEN** Spread > 15% 的合约被过滤

