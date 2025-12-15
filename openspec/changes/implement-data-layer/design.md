## Context

数据层是整个期权量化交易系统的基础，负责从外部数据源获取各类市场数据，并转换为系统内部统一格式。本次实现需要支持多数据源（富途为主、Yahoo Finance 为备），并兼容 QuantConnect LEAN 框架的数据格式要求。

**补充背景（2024-12-12）：**
发现富途账户仅有香港市场权限，无美股/美股期权权限。为支持美股期权交易，需新增 IBKR TWS API 作为美股主数据源。用户已有 IBKR 账户，可直接使用。

**关键约束：**
- 富途 OpenAPI 需要本地运行 OpenD 网关（仅港股）
- IBKR TWS API 需要本地运行 TWS 或 IB Gateway（美股）
- Yahoo Finance 有请求频率限制（免费 API）
- QuantConnect 自定义数据需要继承 BaseData 类
- 使用 Supabase 作为数据持久化存储

## Goals / Non-Goals

### Goals
- 实现富途 OpenAPI 数据获取（港股）
- 实现 IBKR TWS API 数据获取（美股、美股期权）← 新增
- 实现 Yahoo Finance 备用数据获取
- 将数据转换为 QuantConnect 兼容格式
- 提供统一的数据获取接口，屏蔽底层数据源差异
- 支持股票基本面和宏观数据获取
- 实现数据缓存和持久化（Supabase）

### Non-Goals
- 不实现实时推送订阅（本次仅实现拉取）
- 不实现异步数据获取（当前 API 吞吐量有限）
- 不实现复杂的数据清洗逻辑

## Decisions

### D1: 数据源抽象架构

**决定：** 使用 Provider 抽象层 + 具体适配器模式

```
DataProvider (抽象基类)
├── FutuProvider (富途实现 - 港股)
├── IBKRProvider (IBKR实现 - 美股) ← 新增
└── YahooProvider (Yahoo Finance 实现 - 备用)
```

**原因：**
- 便于切换和扩展数据源
- 统一上层调用接口
- 支持故障切换（IBKR 不可用时降级到 Yahoo）
- 按市场区分主数据源：港股用富途，美股用 IBKR

### D2: QuantConnect 数据格式

**决定：** 创建自定义 BaseData 子类，每种数据类型一个类

```python
class StockQuoteData(PythonData):
    """股票行情数据"""
    def GetSource(self, config, date, isLive):
        # 返回数据源 URL 或本地路径

    def Reader(self, config, line, date, isLive):
        # 解析数据行，返回 StockQuoteData 实例
```

**原因：**
- 遵循 QuantConnect 官方推荐模式
- 支持历史回测和实时交易
- 数据可被 LEAN 引擎直接消费

### D3: 数据模型设计

**决定：** 使用 dataclass 定义内部数据模型，与 QuantConnect 类型分离

```python
@dataclass
class StockQuote:
    """内部股票行情模型"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    # ...
```

**原因：**
- 内部模型与外部格式解耦
- 便于测试和调试
- 支持多种输出格式（QuantConnect、CSV、JSON）

### D4: 错误处理策略

**决定：** 主数据源失败时自动降级到备用数据源

```python
def get_stock_quote(symbol):
    try:
        return futu_provider.get_quote(symbol)
    except FutuConnectionError:
        logger.warning("Futu unavailable, falling back to Yahoo")
        return yahoo_provider.get_quote(symbol)
```

**原因：**
- 提高系统可用性
- 富途需要本地网关，可能不总是可用
- Yahoo Finance 作为可靠备份

### D5: 富途 API 使用模式

**决定：** 使用上下文管理器管理连接生命周期

```python
class FutuProvider:
    def __enter__(self):
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        return self

    def __exit__(self, *args):
        self.quote_ctx.close()
```

**原因：**
- 确保连接正确关闭
- 避免资源泄漏
- 符合 Python 惯用法

### D6: 数据持久化策略

**决定：** 使用 Supabase 作为数据库，实现数据缓存

```python
class DataCache:
    """数据缓存层"""
    def __init__(self, supabase_client):
        self.client = supabase_client

    def get_or_fetch(self, symbol, date, fetcher):
        # 先查缓存
        cached = self.client.table('stock_quotes').select('*').eq('symbol', symbol).eq('date', date).execute()
        if cached.data:
            return cached.data[0]
        # 缓存未命中，从 API 获取
        data = fetcher()
        self.client.table('stock_quotes').insert(data).execute()
        return data
```

**原因：**
- 减少 API 调用次数，避免触发限流
- 历史数据只需获取一次
- Supabase 提供免费层，PostgreSQL 兼容

### D7: 同步实现模式

**决定：** 使用同步方式实现数据获取

**原因：**
- 当前使用免费 API，吞吐量有限
- 同步代码更简单易调试
- 后续如需异步可重构

### D8: IBKR TWS API 集成策略（新增）

**决定：** 使用 ib_async 库实现 IBKRProvider

```python
class IBKRProvider(DataProvider):
    """IBKR TWS API 数据提供者"""

    def __init__(self, host='127.0.0.1', port=7497, client_id=1):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id

    def connect(self):
        self.ib.connect(self.host, self.port, clientId=self.client_id)

    def get_option_chain(self, underlying):
        # 使用 reqSecDefOptParams 获取期权链参数
        stock = Stock(underlying, 'SMART', 'USD')
        self.ib.qualifyContracts(stock)
        chains = self.ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        # ... 构建期权合约并获取行情
```

**原因：**
- ib_async 是 ib_insync 的现代替代，原作者已去世，社区维护版本
- 提供同步和异步两种调用方式
- 支持完整的期权链和 Greeks 数据
- 用户已有 IBKR 账户，无额外数据费用（仅需基础市场数据订阅）

**连接端口：**
| 应用 | Live | Paper |
|------|------|-------|
| TWS | 7496 | 7497 |
| IB Gateway | 4001 | 4002 |

**API 特点：**
- 需要本地运行 TWS 或 IB Gateway
- 支持 modelGreeks、bidGreeks、askGreeks、lastGreeks
- reqSecDefOptParams 获取期权链参数（到期日、行权价）
- reqTickers 获取实时行情和 Greeks

### D9: 市场路由策略（新增）

**决定：** 根据股票代码自动选择数据源

```python
def _get_provider_for_symbol(self, symbol: str) -> DataProvider:
    """根据股票代码选择合适的数据提供者"""
    if symbol.startswith('HK.') or self._is_hk_stock(symbol):
        return self._futu  # 港股用富途
    else:
        return self._ibkr  # 美股用 IBKR
```

**原因：**
- 简化上层调用，无需关心数据源
- 充分利用各数据源的权限优势
- 自动降级到 Yahoo Finance 作为备用

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 富途 API 限流 | 批量请求失败 | 实现请求节流，遵守 API 限制 |
| Yahoo Finance 数据延迟 | 期权数据可能不够实时 | 仅作为备用，期权数据优先用 IBKR |
| QuantConnect 版本兼容 | BaseData 接口可能变化 | 锁定依赖版本，添加版本检查 |
| OpenD 连接不稳定 | 数据获取中断 | 实现重连机制和健康检查 |
| Supabase 连接问题 | 缓存不可用 | 降级为直接 API 调用 |
| TWS/Gateway 未启动 | IBKR 数据获取失败 | 自动降级到 Yahoo Finance |
| IBKR 市场数据订阅缺失 | 某些数据无法获取 | 提示用户订阅基础市场数据包 |

## Data Type Mapping

### 富途 → 内部模型

| 富途字段 | 内部字段 | 说明 |
|----------|----------|------|
| last_price | close | 最新价 |
| open_price | open | 开盘价 |
| high_price | high | 最高价 |
| low_price | low | 最低价 |
| volume | volume | 成交量 |
| turnover | turnover | 成交额 |
| implied_volatility | iv | 隐含波动率 |
| delta/gamma/theta/vega | greeks.* | Greeks |

### Yahoo Finance → 内部模型

| Yahoo 字段 | 内部字段 | 说明 |
|------------|----------|------|
| Close | close | 收盘价 |
| Open | open | 开盘价 |
| High | high | 最高价 |
| Low | low | 最低价 |
| Volume | volume | 成交量 |
| marketCap | market_cap | 市值 |
| trailingPE | pe_ratio | 市盈率 |

### IBKR TWS → 内部模型（新增）

| IBKR 字段 | 内部字段 | 说明 |
|-----------|----------|------|
| ticker.last | close | 最新价 |
| ticker.open | open | 开盘价 |
| ticker.high | high | 最高价 |
| ticker.low | low | 最低价 |
| ticker.volume | volume | 成交量 |
| ticker.bid | bid | 买一价 |
| ticker.ask | ask | 卖一价 |
| ticker.modelGreeks.impliedVol | iv | 隐含波动率 |
| ticker.modelGreeks.delta | greeks.delta | Delta |
| ticker.modelGreeks.gamma | greeks.gamma | Gamma |
| ticker.modelGreeks.theta | greeks.theta | Theta |
| ticker.modelGreeks.vega | greeks.vega | Vega |
| BarData.open | open | K线开盘价 |
| BarData.high | high | K线最高价 |
| BarData.low | low | K线最低价 |
| BarData.close | close | K线收盘价 |
| BarData.volume | volume | K线成交量 |

## Database Schema (Supabase)

```sql
-- 股票行情表
CREATE TABLE stock_quotes (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(18,4),
    high DECIMAL(18,4),
    low DECIMAL(18,4),
    close DECIMAL(18,4),
    volume BIGINT,
    turnover DECIMAL(18,2),
    source VARCHAR(20),  -- 'futu' or 'yahoo'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);

-- K线数据表
CREATE TABLE kline_bars (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    ktype VARCHAR(10) NOT NULL,  -- 'day', '1min', '5min', etc.
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(18,4),
    high DECIMAL(18,4),
    low DECIMAL(18,4),
    close DECIMAL(18,4),
    volume BIGINT,
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, ktype, timestamp)
);

-- 期权行情表
CREATE TABLE option_quotes (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    underlying VARCHAR(20) NOT NULL,
    option_type VARCHAR(4) NOT NULL,  -- 'call' or 'put'
    strike_price DECIMAL(18,4) NOT NULL,
    expiry_date DATE NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    last_price DECIMAL(18,4),
    bid DECIMAL(18,4),
    ask DECIMAL(18,4),
    volume BIGINT,
    open_interest BIGINT,
    iv DECIMAL(8,4),
    delta DECIMAL(8,4),
    gamma DECIMAL(8,4),
    theta DECIMAL(8,4),
    vega DECIMAL(8,4),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timestamp)
);

-- 基本面数据表
CREATE TABLE fundamentals (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    market_cap DECIMAL(20,2),
    pe_ratio DECIMAL(10,2),
    pb_ratio DECIMAL(10,2),
    dividend_yield DECIMAL(8,4),
    eps DECIMAL(10,4),
    revenue DECIMAL(20,2),
    profit DECIMAL(20,2),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, date)
);

-- 宏观数据表
CREATE TABLE macro_data (
    id BIGSERIAL PRIMARY KEY,
    indicator VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    value DECIMAL(18,6),
    source VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(indicator, date)
);
```

## Resolved Questions

1. **宏观数据来源**：先用 Yahoo Finance，后续根据算子层所需和数据来源订阅成本扩展

2. **数据缓存策略**：本次实现数据缓存和持久化，使用 Supabase 作为数据库

3. **异步获取**：使用同步实现，当前免费 API 吞吐量有限
