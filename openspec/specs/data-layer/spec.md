# data-layer Specification

## Purpose
TBD - created by archiving change implement-data-layer. Update Purpose after archive.
## Requirements
### Requirement: Data Provider Abstraction

系统 SHALL 提供统一的数据源抽象层，支持多数据源切换和故障降级。

#### Scenario: 数据源降级
- **WHEN** 主数据源（富途）不可用
- **THEN** 系统自动切换到备用数据源（Yahoo Finance）
- **AND** 记录降级日志

#### Scenario: 数据源选择
- **WHEN** 用户请求数据
- **THEN** 系统根据配置选择优先数据源
- **AND** 返回统一格式的数据

### Requirement: Yahoo Finance Data Provider

系统 SHALL 支持从 Yahoo Finance 获取市场数据作为备用数据源。

#### Scenario: 获取股票行情
- **WHEN** 用户通过 Yahoo 提供者请求股票行情
- **THEN** 系统调用 yfinance API 获取数据
- **AND** 返回标准化的 StockQuote 对象

#### Scenario: 获取历史 K 线
- **WHEN** 用户请求历史 K 线数据
- **THEN** 系统返回指定时间范围内的 OHLCV 数据

#### Scenario: 获取基本面数据
- **WHEN** 用户请求股票基本面数据
- **THEN** 系统返回市值、PE、EPS 等财务指标

#### Scenario: 获取宏观数据
- **WHEN** 用户请求宏观经济指标（如 ^VIX, ^TNX）
- **THEN** 系统返回指数或利率数据

### Requirement: Data Caching with Supabase

系统 SHALL 使用 Supabase 实现数据缓存和持久化。

#### Scenario: 缓存命中
- **WHEN** 请求的数据已存在于 Supabase 缓存中
- **THEN** 系统直接返回缓存数据
- **AND** 不调用外部 API

#### Scenario: 缓存未命中
- **WHEN** 请求的数据不在缓存中
- **THEN** 系统从外部 API 获取数据
- **AND** 将数据存入 Supabase
- **AND** 返回数据给调用方

#### Scenario: 缓存更新
- **WHEN** 用户强制刷新数据
- **THEN** 系统从 API 获取最新数据
- **AND** 更新 Supabase 中的缓存记录

#### Scenario: Supabase 不可用时降级
- **WHEN** Supabase 连接失败
- **THEN** 系统直接从 API 获取数据
- **AND** 记录缓存不可用警告

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

### Requirement: Macro Economic Data

系统 SHALL 能够获取宏观经济数据。

#### Scenario: 获取 VIX 指数
- **WHEN** 用户请求 VIX 波动率指数
- **THEN** 系统返回 ^VIX 的最新值和历史数据

#### Scenario: 获取国债收益率
- **WHEN** 用户请求美国国债收益率（如 10 年期）
- **THEN** 系统返回 ^TNX 的最新值和历史数据

#### Scenario: 获取市场指数
- **WHEN** 用户请求市场指数（如 SPY, QQQ）
- **THEN** 系统返回指数的行情数据

### Requirement: QuantConnect Data Format

系统 SHALL 将数据转换为 QuantConnect LEAN 兼容的格式。

#### Scenario: 创建自定义数据类
- **WHEN** 系统需要向 LEAN 提供数据
- **THEN** 数据类继承自 PythonData
- **AND** 实现 GetSource 和 Reader 方法

#### Scenario: 股票数据格式化
- **WHEN** 将 StockQuote 转换为 QuantConnect 格式
- **THEN** 创建 StockQuoteData 实例
- **AND** 包含 Time, Symbol, Open, High, Low, Close, Volume 属性

#### Scenario: 期权数据格式化
- **WHEN** 将 OptionQuote 转换为 QuantConnect 格式
- **THEN** 创建 OptionQuoteData 实例
- **AND** 包含 Greeks（Delta, Gamma, Theta, Vega）和行权信息

#### Scenario: 导出 CSV 格式
- **WHEN** 用户请求导出数据为 CSV
- **THEN** 系统生成 LEAN 兼容的 CSV 文件
- **AND** 文件可被 LEAN 引擎直接读取

### Requirement: Rate Limiting

系统 SHALL 实现请求限流以遵守各 API 的频率限制。

#### Scenario: 富途 API 限流
- **WHEN** 发送请求到富途 API
- **THEN** 系统确保不超过限制（如期权链 10 次/30 秒）
- **AND** 超限时自动等待

#### Scenario: Yahoo Finance 限流
- **WHEN** 发送请求到 Yahoo Finance
- **THEN** 系统控制请求频率避免被封禁

### Requirement: Futu OpenAPI Connection Management

系统 SHALL 提供富途 OpenAPI 的连接管理能力，包括与 OpenD 网关的连接建立、心跳维护和自动重连。

#### Scenario: 成功连接到 OpenD
- **WHEN** 用户启动系统且 OpenD 网关正在运行
- **THEN** 系统成功建立 TCP 连接并完成认证
- **AND** 连接状态变为 "已连接"

#### Scenario: OpenD 连接断开后自动重连
- **WHEN** 与 OpenD 的连接意外断开
- **THEN** 系统在 5 秒内尝试重新连接
- **AND** 最多重试 3 次，每次间隔递增

#### Scenario: OpenD 未运行时的错误处理
- **WHEN** 用户启动系统但 OpenD 网关未运行
- **THEN** 系统显示明确的错误信息
- **AND** 提示用户启动 OpenD

#### Scenario: 使用上下文管理器管理连接
- **WHEN** 代码使用 with 语句创建 FutuProvider
- **THEN** 连接在进入时建立
- **AND** 连接在退出时自动关闭

### Requirement: Stock Volatility Data

系统 SHALL 提供股票级别的波动率指标数据，支持港美股市场。

#### Scenario: 获取股票波动率指标
- **WHEN** 用户请求股票的波动率数据
- **THEN** 系统返回 StockVolatility 对象，包含:
  - IV (30 天隐含波动率)
  - HV (30 天历史波动率)
  - PCR (看跌/看涨持仓比率，基于 Open Interest)
  - IV Rank (当前 IV 在 52 周范围内的百分位)
  - IV Percentile (历史 IV 低于当前值的天数占比)

#### Scenario: PCR 统一计算口径
- **WHEN** 计算 PCR 指标
- **THEN** 统一使用 Open Interest (未平仓合约数) 计算
- **AND** 确保港股和美股指标口径一致

#### Scenario: IV Rank/Percentile 计算
- **WHEN** 请求包含 IV Rank 的波动率数据
- **THEN** 系统获取 52 周历史 IV 数据
- **AND** 计算 IV Rank = (当前 IV - 最低 IV) / (最高 IV - 最低 IV) × 100
- **AND** 计算 IV Percentile = 低于当前 IV 的天数 / 总天数 × 100

### Requirement: Data Persistence with Supabase

系统 SHALL 将获取的数据持久化存储到 Supabase，支持离线查询和历史分析。

#### Scenario: 自动缓存行情数据
- **WHEN** 系统获取到新的行情数据
- **THEN** 数据自动存储到 Supabase 数据库
- **AND** 支持按标的、日期查询历史数据

#### Scenario: 数据去重
- **WHEN** 同一时间戳的数据被重复获取
- **THEN** 系统使用 UPSERT 操作，避免重复存储

#### Scenario: 查询历史数据
- **WHEN** 用户查询某股票的历史行情
- **THEN** 系统从 Supabase 返回指定时间范围的数据
- **AND** 按时间升序排列

### Requirement: Multi-Broker Account Aggregation

系统 SHALL 支持从多个券商获取账户持仓并聚合为统一视图。

#### Scenario: 获取单券商持仓
- **WHEN** 用户请求 IBKR 或 Futu 的账户持仓
- **THEN** 系统返回该券商的所有持仓列表
- **AND** 每个持仓包含标的、数量、成本、市值、盈亏
- **AND** 期权持仓包含行权价、到期日、期权类型

#### Scenario: 获取账户现金余额
- **WHEN** 用户请求账户现金余额
- **THEN** 系统返回按币种分类的现金余额
- **AND** 包含可用余额和总余额

#### Scenario: 多券商持仓聚合
- **WHEN** 用户请求合并后的投资组合
- **THEN** 系统从所有可用券商获取持仓
- **AND** 使用实时汇率转换为统一货币
- **AND** 计算总资产和总盈亏

#### Scenario: 汇率转换
- **WHEN** 合并不同币种的持仓
- **THEN** 系统从 Yahoo Finance 获取实时汇率
- **AND** 将所有持仓价值转换为目标货币

### Requirement: Option Greeks Routing

系统 SHALL 使用智能路由为期权持仓获取 Greeks 数据。

#### Scenario: HK 期权 Greeks 路由
- **WHEN** 用户请求港股期权的 Greeks
- **THEN** 系统优先使用 IBKR（提供完整 IV/Greeks）
- **AND** IBKR 失败时回退到 Futu

#### Scenario: US 期权 Greeks 路由
- **WHEN** 用户请求美股期权的 Greeks
- **THEN** 系统按优先级尝试 IBKR → Futu → Yahoo
- **AND** 返回第一个成功的结果

#### Scenario: 统一 Greeks 获取
- **WHEN** AccountAggregator 获取持仓
- **THEN** 先从各券商获取持仓（不含 Greeks）
- **AND** 再通过 UnifiedProvider 统一获取 Greeks
- **AND** 使用路由规则选择最佳数据源

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

