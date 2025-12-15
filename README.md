# Option Quant Trade System

期权量化策略交易系统 - 基于 QuantConnect LEAN 引擎的期权交易系统

## 项目结构

```
option_quant_trade_system/
├── src/
│   └── data/                    # 数据层
│       ├── models/              # 数据模型
│       ├── providers/           # 数据提供者
│       └── formatters/          # 数据格式化
├── examples/                    # 示例代码
├── tests/                       # 测试代码
└── openspec/                    # 规格文档
```

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行示例

```bash
# Yahoo Finance 数据测试
python examples/data_layer_demo.py --yahoo

# Futu OpenD 数据测试 (需要运行 OpenD)
python examples/data_layer_demo.py --futu

# IBKR TWS 数据测试 (需要运行 TWS)
python examples/data_layer_demo.py --ibkr
```

## 数据提供者 (Data Providers)

系统支持三个数据源，各有不同的能力边界：

### 功能对比矩阵

| 功能 | Yahoo Finance | Futu OpenAPI | IBKR TWS |
|-----|---------------|--------------|----------|
| **股票行情** | ✅ 美股/港股 | ✅ 美股/港股 | ✅ 美股 |
| **历史K线** | ✅ | ✅ | ✅ |
| **期权链** | ✅ 美股 | ✅ 美股/港股 | ✅ 美股 |
| **期权Greeks** | ❌ | ✅ | ✅ |
| **期权Bid/Ask** | ⚠️ 非交易时段为0 | ✅ | ✅ |
| **基本面数据** | ✅ | ❌ | ❌ |
| **宏观数据** | ✅ (VIX/TNX等) | ⚠️ 仅K线 | ⚠️ 仅K线 |
| **Put/Call Ratio** | ✅ (计算) | ❌ | ❌ |
| **分析师评级** | ✅ | ❌ | ❌ |
| **实时数据** | ❌ 延迟 | ✅ | ✅ |
| **需要网关** | ❌ | ✅ OpenD | ✅ TWS/Gateway |

### Yahoo Finance Provider

**最佳用途：** 基本面数据、宏观经济指标、历史数据回测

```python
from src.data.providers.yahoo_provider import YahooProvider

provider = YahooProvider()

# 股票行情
quote = provider.get_stock_quote("AAPL")
quote_hk = provider.get_stock_quote("0700.HK")

# 基本面数据 (含营收增长率、分析师评级)
fundamental = provider.get_fundamental("AAPL")
print(f"Revenue Growth: {fundamental.revenue_growth}")
print(f"Recommendation: {fundamental.recommendation}")
print(f"Target Price: ${fundamental.target_price}")

# 宏观数据
vix_data = provider.get_macro_data("^VIX", start_date, end_date)

# Put/Call Ratio
pcr = provider.get_put_call_ratio("SPY")
```

**支持的基本面字段：**
- 估值：market_cap, pe_ratio, pb_ratio, ps_ratio, eps
- 增长：revenue_growth, earnings_growth
- 分析师：recommendation, recommendation_mean, analyst_count, target_price
- 其他：dividend_yield, roe, roa, beta 等

### Futu OpenAPI Provider

**最佳用途：** 港股实时行情、期权链完整数据（含Greeks）

```python
from src.data.providers.futu_provider import FutuProvider

# 需要运行 OpenD 网关
with FutuProvider() as provider:
    # 股票行情
    quote = provider.get_stock_quote("HK.00700")

    # 期权链
    chain = provider.get_option_chain("HK.00700")

    # 期权行情 (含Greeks, IV, Bid/Ask)
    quotes = provider.get_option_quotes_batch(contracts)
```

**注意事项：**
- 需要安装并运行 Futu OpenD 网关
- 期权链请求时间跨度不能超过30天
- 美股需要额外市场数据订阅
- 使用 `get_market_snapshot` API 获取期权完整数据

### IBKR TWS Provider

**最佳用途：** 美股实时交易、期权Greeks

```python
from src.data.providers.ibkr_provider import IBKRProvider

# 需要运行 TWS 或 IB Gateway
with IBKRProvider() as provider:
    # 股票行情
    quote = provider.get_stock_quote("AAPL")

    # 期权链
    chain = provider.get_option_chain("AAPL")

    # 期权行情 (含Greeks)
    quotes = provider.get_option_quotes_batch(contracts)
```

**注意事项：**
- 需要安装并运行 TWS 或 IB Gateway
- API端口：Paper Trading=7497, Live=7496
- 实时行情需要市场数据订阅
- 历史数据无需订阅

### 推荐使用场景

| 场景 | 推荐Provider | 原因 |
|-----|-------------|------|
| 策略回测 | Yahoo | 免费历史数据 |
| 基本面分析 | Yahoo | 唯一提供完整基本面 |
| 港股期权交易 | Futu | 支持港股期权Greeks |
| 美股期权交易 | IBKR/Futu | 实时数据+Greeks |
| 市场情绪分析 | Yahoo | VIX + Put/Call Ratio |
| 宏观分析 | Yahoo | 完整宏观指标 |

## 环境配置

创建 `.env` 文件：

```env
# Futu OpenAPI
FUTU_HOST=127.0.0.1
FUTU_PORT=11111

# IBKR TWS API
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# Supabase (可选，用于数据缓存)
SUPABASE_URL=your-project-url
SUPABASE_KEY=your-anon-key
```

## License

MIT
