## Why

实现数据层的核心功能，提供股票行情、期权行情、股票基本面和宏观数据的获取能力。数据优先从富途 OpenAPI 获取，备选从 Yahoo Finance 获取，并将数据格式化为 QuantConnect 兼容的类型，支持后续策略开发和回测。

**补充需求（2024-12-12）：**
由于富途账户仅有香港市场权限，缺少美股/美股期权权限，需新增 IBKR TWS API 数据源，用于获取美国市场的股票和期权行情数据。

## What Changes

### 新增实现

**数据源适配器**
- 富途 OpenAPI 适配器（港股数据源）
  - 股票实时/历史行情
  - 期权链和期权行情
  - 需要本地 OpenD 网关
- **IBKR TWS API 适配器（美股主数据源）** ← 新增
  - 股票实时/历史行情
  - 期权链和期权行情（含 Greeks）
  - 需要本地 TWS 或 IB Gateway
  - 使用 ib_async 库（ib_insync 的现代替代）
- Yahoo Finance 适配器（备用数据源）
  - 股票行情和历史数据
  - 基本面数据
  - 无需本地网关，直接 HTTP 调用

**数据类型**
- 股票行情数据（实时报价、K线）
- 期权行情数据（期权链、Greeks）
- 股票基本面数据（财务指标、估值）
- 宏观经济数据（利率、指数）

**数据缓存与持久化**
- 使用 Supabase 作为数据库
- 实现数据缓存层，减少 API 调用
- 支持历史数据查询和离线分析

**QuantConnect 兼容格式**
- 自定义 BaseData 子类
- 实现 GetSource 和 Reader 方法
- 支持 CSV 格式数据导出
- 兼容 LEAN 回测引擎

## Impact

- Affected specs: `data-layer`（扩展已有规格）
- New code:
  - `src/data/providers/` - 数据源适配器
  - `src/data/models/` - 数据模型定义
  - `src/data/formatters/` - QuantConnect 格式转换
  - `src/data/cache/` - 数据缓存层
- Dependencies:
  - `futu-api` - 富途 API SDK
  - `yfinance` - Yahoo Finance API
  - `ib_async` - IBKR TWS API 客户端 ← 新增
  - `pandas` - 数据处理
  - `supabase` - 数据库客户端
