## 1. 项目初始化

- [x] 1.1 创建项目目录结构（src/data/providers, src/data/models, src/data/formatters, src/data/cache）
- [x] 1.2 创建 pyproject.toml，配置项目依赖
- [x] 1.3 安装依赖包（futu-api, yfinance, pandas, supabase）
- [x] 1.4 创建配置文件模板（config/settings.yaml, .env.example）

## 2. 数据库设置（Supabase）

- [x] 2.1 创建 Supabase 项目和数据库
- [x] 2.2 执行数据库 schema 创建脚本
- [x] 2.3 配置 Supabase 连接（环境变量）
- [x] 2.4 实现 Supabase 客户端封装
- [x] 2.5 编写数据库连接测试

## 3. 数据模型定义

- [x] 3.1 定义股票行情数据模型（StockQuote）
- [x] 3.2 定义 K 线数据模型（KlineBar）
- [x] 3.3 定义期权行情数据模型（OptionQuote）
- [x] 3.4 定义期权链数据模型（OptionChain）
- [x] 3.5 定义股票基本面数据模型（Fundamental）
- [x] 3.6 定义宏观数据模型（MacroData）
- [x] 3.7 编写数据模型单元测试

## 4. 数据缓存层

- [x] 4.1 实现 DataCache 基类
- [x] 4.2 实现 get_or_fetch 缓存逻辑
- [x] 4.3 实现各数据类型的缓存存取方法
- [x] 4.4 实现缓存过期和刷新机制
- [x] 4.5 编写缓存层单元测试

## 5. 数据源抽象层

- [x] 5.1 定义 DataProvider 抽象基类
- [x] 5.2 定义各数据类型的获取接口
- [x] 5.3 实现数据源降级逻辑（Futu → Yahoo）
- [x] 5.4 编写抽象层单元测试

## 6. 富途 API 适配器

- [x] 6.1 实现 FutuProvider 类和连接管理
- [x] 6.2 实现股票实时行情获取（get_stock_quote）
- [x] 6.3 实现历史 K 线获取（get_history_kline）
- [x] 6.4 实现期权链获取（get_option_chain）
- [x] 6.5 实现期权行情获取（get_option_quote）
- [x] 6.6 实现连接健康检查和重连机制
- [x] 6.7 实现请求限流（遵守 API 频率限制）
- [x] 6.8 编写富途适配器单元测试（需要 mock）

## 7. Yahoo Finance 适配器

- [x] 7.1 实现 YahooProvider 类
- [x] 7.2 实现股票行情获取
- [x] 7.3 实现历史 K 线获取
- [x] 7.4 实现股票基本面数据获取
- [x] 7.5 实现宏观数据获取（指数、利率）
- [x] 7.6 编写 Yahoo 适配器单元测试

## 8. QuantConnect 格式转换

- [x] 8.1 实现 StockQuoteData（继承 PythonData）
- [x] 8.2 实现 OptionQuoteData（继承 PythonData）
- [x] 8.3 实现 FundamentalData（继承 PythonData）
- [x] 8.4 实现数据导出为 CSV 格式
- [x] 8.5 实现 GetSource 和 Reader 方法
- [x] 8.6 编写格式转换单元测试
- [x] 8.7 验证与 LEAN 引擎兼容性

## 9. 集成与验证

- [x] 9.1 端到端集成测试（获取数据 → 缓存 → 转换格式）
- [x] 9.2 验证富途实时行情获取
- [x] 9.3 验证期权链数据获取
- [x] 9.4 验证 Yahoo Finance 降级逻辑
- [x] 9.5 验证 Supabase 数据持久化
- [x] 9.6 编写使用示例和文档

## 10. IBKR TWS API 适配器（补充需求）

- [x] 10.1 添加 ib_async 依赖到 pyproject.toml
- [x] 10.2 更新 .env.example 和 settings.yaml 添加 IBKR 配置
- [x] 10.3 实现 IBKRProvider 类和连接管理
- [x] 10.4 实现股票实时行情获取（get_stock_quote）
- [x] 10.5 实现历史 K 线获取（get_history_kline）
- [x] 10.6 实现期权链获取（get_option_chain）
- [x] 10.7 实现期权行情获取（含 Greeks: modelGreeks, bidGreeks, askGreeks）
- [x] 10.8 实现连接健康检查和重连机制
- [x] 10.9 编写 IBKR 适配器单元测试（需要 mock）

## 11. 更新 UnifiedProvider 支持 IBKR

- [x] 11.1 更新 UnifiedDataProvider 集成 IBKRProvider
- [x] 11.2 实现市场路由逻辑（美股 → IBKR，港股 → Futu）
- [x] 11.3 更新降级策略（IBKR → Yahoo）
- [x] 11.4 更新配置支持选择主数据源

## 12. IBKR 集成验证

- [x] 12.1 验证 IBKR 股票行情获取（需要 TWS/Gateway 运行）
- [x] 12.2 验证 IBKR 期权链和 Greeks 获取
- [x] 12.3 验证 IBKR → Yahoo 降级逻辑
- [x] 12.4 更新使用示例文档
