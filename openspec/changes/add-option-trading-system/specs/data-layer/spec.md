## ADDED Requirements

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

### Requirement: Stock Quote Fetching

系统 SHALL 能够获取指定股票的实时行情数据。

#### Scenario: 获取单只股票实时行情
- **WHEN** 用户请求股票 "AAPL" 的实时行情
- **THEN** 系统返回最新价格、涨跌幅、成交量等数据
- **AND** 数据延迟不超过 3 秒

#### Scenario: 批量获取多只股票行情
- **WHEN** 用户请求多只股票的实时行情（最多 50 只）
- **THEN** 系统并行获取所有股票数据
- **AND** 在 5 秒内返回完整结果

### Requirement: Option Chain Data Fetching

系统 SHALL 能够获取指定标的的完整期权链数据。

#### Scenario: 获取股票的期权链
- **WHEN** 用户请求 "AAPL" 的期权链
- **THEN** 系统返回所有可用到期日和行权价的期权合约
- **AND** 每个合约包含：行权价、到期日、看涨/看跌、最新价、买卖价、成交量、持仓量

#### Scenario: 按到期日筛选期权
- **WHEN** 用户请求未来 30 天内到期的期权
- **THEN** 系统仅返回符合条件的期权合约

### Requirement: Historical Data Fetching

系统 SHALL 能够获取历史 K 线数据用于回测和分析。

#### Scenario: 获取日 K 线数据
- **WHEN** 用户请求 "AAPL" 过去 1 年的日 K 线
- **THEN** 系统返回包含开高低收、成交量的完整数据
- **AND** 数据按日期升序排列

#### Scenario: 获取期权历史数据
- **WHEN** 用户请求特定期权合约的历史价格
- **THEN** 系统返回该合约存续期内的价格变化

### Requirement: Data Persistence

系统 SHALL 将获取的数据持久化存储，支持离线查询和历史分析。

#### Scenario: 自动缓存行情数据
- **WHEN** 系统获取到新的行情数据
- **THEN** 数据自动存储到本地数据库（SQLite）
- **AND** 支持按标的、日期查询历史数据

#### Scenario: 数据去重
- **WHEN** 同一时间戳的数据被重复获取
- **THEN** 系统仅保留一份，避免重复存储

### Requirement: Data Normalization

系统 SHALL 对原始数据进行清洗和标准化，确保下游模块使用一致的数据格式。

#### Scenario: 统一数据格式
- **WHEN** 从富途 API 获取原始数据
- **THEN** 系统将其转换为内部标准格式
- **AND** 字段命名遵循 snake_case 规范

#### Scenario: 处理缺失数据
- **WHEN** 某些字段数据缺失（如期权无成交）
- **THEN** 系统使用默认值或标记为 None
- **AND** 记录数据质量日志
