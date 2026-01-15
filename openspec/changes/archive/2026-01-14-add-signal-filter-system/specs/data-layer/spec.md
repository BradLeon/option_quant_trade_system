## ADDED Requirements

### Requirement: Stock Calendar Data

系统 SHALL 能够获取股票的财经日历数据，包括财报发布日和除息日。

#### Scenario: 获取财报发布日期
- **WHEN** 用户请求股票 "AAPL" 的基本面数据
- **THEN** 系统返回 `Fundamental` 对象，包含 `earnings_date` 字段
- **AND** 日期为下一个财报发布日（如有）

#### Scenario: 获取除息日期
- **WHEN** 用户请求股票 "AAPL" 的基本面数据
- **THEN** 系统返回 `Fundamental` 对象，包含 `ex_dividend_date` 字段
- **AND** 日期为下一个除息日（如有）

#### Scenario: 无财报日期时返回 None
- **WHEN** 股票近期无财报安排
- **THEN** `earnings_date` 字段返回 `None`

### Requirement: Economic Event Calendar

系统 SHALL 能够获取宏观经济事件日历，支持筛选市场影响型事件。

#### Scenario: 获取未来宏观事件
- **WHEN** 用户请求未来 30 天的宏观经济事件
- **THEN** 系统返回 `EconomicEvent` 列表
- **AND** 每个事件包含类型、日期、名称、影响程度

#### Scenario: 按事件类型过滤
- **WHEN** 用户请求 FOMC 相关事件
- **THEN** 系统返回仅包含 FOMC 类型的事件列表

#### Scenario: 获取高影响事件
- **WHEN** 用户请求高影响（high impact）事件
- **THEN** 系统返回影响程度为 "high" 的事件
- **AND** 包括 FOMC 利率决议、CPI 数据、非农就业等

### Requirement: FRED + Static FOMC Economic Calendar Provider

系统 SHALL 支持从混合数据源获取宏观经济事件日历：
- **FRED API**: 获取 CPI、NFP、GDP、PPI 等经济数据发布日期
- **静态 YAML**: 获取 FOMC 会议日期（美联储每年提前公布）

#### Scenario: 调用 FRED 经济日历 API
- **WHEN** 系统请求 CPI/NFP/GDP 等经济数据发布日期
- **THEN** 调用 FRED `/fred/releases/dates` 端点
- **AND** 使用 `include_release_dates_with_no_data=true` 获取未来日期
- **AND** 返回标准化的 `EconomicEvent` 对象列表

#### Scenario: 获取 FOMC 会议日期
- **WHEN** 系统请求 FOMC 会议日期
- **THEN** 从静态配置文件 `config/screening/fomc_calendar.yaml` 读取
- **AND** 返回当前及未来年份的 FOMC 会议日期列表

#### Scenario: 按发布类型查询
- **WHEN** 用户指定 release_id 参数
- **THEN** 系统返回该发布类型的所有未来发布日期
- **AND** 支持的 release_id：
  - 10 = CPI (Consumer Price Index)
  - 50 = Employment Situation (NFP)
  - 53 = GDP
  - 46 = PPI

#### Scenario: API Key 未配置时降级
- **WHEN** FRED API Key 未配置
- **THEN** 系统仅使用静态 FOMC 日历
- **AND** 记录警告日志（不阻塞主流程）

#### Scenario: 事件类型映射
- **WHEN** 系统返回经济事件数据
- **THEN** 根据数据源映射到标准类型：
  - FRED release_id=10 → `EconomicEventType.CPI`
  - FRED release_id=50 → `EconomicEventType.NFP`
  - FRED release_id=53 → `EconomicEventType.GDP`
  - FRED release_id=46 → `EconomicEventType.PPI`
  - Static YAML → `EconomicEventType.FOMC`

#### Scenario: 合并多数据源日历
- **WHEN** 系统请求完整经济日历
- **THEN** 合并 FRED API 返回的发布日期与静态 FOMC 日期
- **AND** 按日期排序返回统一的 `EventCalendar` 对象

## MODIFIED Requirements

### Requirement: Stock Fundamental Data

系统 SHALL 能够获取股票的基本面数据，包括财务指标和财经日历。

#### Scenario: 获取单只股票基本面
- **WHEN** 用户请求股票 "AAPL" 的基本面数据
- **THEN** 系统返回市值、市盈率、市净率、股息率、EPS、营收、利润等指标
- **AND** 返回 `earnings_date`（下一财报日）
- **AND** 返回 `ex_dividend_date`（下一除息日）

#### Scenario: 批量获取基本面数据
- **WHEN** 用户请求多只股票的基本面数据
- **THEN** 系统批量获取并返回所有股票的财务指标和日历数据
