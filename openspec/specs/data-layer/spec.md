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

系统 SHALL 能够获取股票的基本面数据。

#### Scenario: 获取单只股票基本面
- **WHEN** 用户请求股票 "AAPL" 的基本面数据
- **THEN** 系统返回市值、市盈率、市净率、股息率、EPS、营收、利润等指标

#### Scenario: 批量获取基本面数据
- **WHEN** 用户请求多只股票的基本面数据
- **THEN** 系统批量获取并返回所有股票的财务指标

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

