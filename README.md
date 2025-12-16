# Option Quant Trade System

期权量化策略交易系统 - 基于 QuantConnect LEAN 引擎的期权交易系统

## 项目结构

```
option_quant_trade_system/
├── src/
│   ├── data/                    # 数据层
│   │   ├── models/              # 数据模型
│   │   ├── providers/           # 数据提供者
│   │   └── formatters/          # 数据格式化
│   └── engine/                  # 计算引擎层
│       ├── bs/                  # B-S 模型基础计算
│       ├── strategy/            # 期权策略实现
│       ├── greeks/              # 希腊值计算
│       ├── volatility/          # 波动率计算
│       ├── returns/             # 收益风险指标
│       ├── sentiment/           # 市场情绪
│       ├── fundamental/         # 基本面分析
│       ├── technical/           # 技术面分析
│       └── portfolio/           # 组合风险指标
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
| **期权Bid/Ask** | ⚠️ 非交易时段为0* | ✅ | ✅ |
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

**\*期权数据注意事项：**
- **Bid/Ask**: 在非交易时段（美东时间 9:30-16:00 之外）通常为 0
- **Open Interest**: 临近到期的期权可能显示为 0
- **Implied Volatility**: 当 Bid/Ask 为 0 时无法计算，显示为接近 0 的值
- **Greeks**: 不提供（始终为 None）
- **建议**: 在美股交易时段内测试以获得完整期权数据

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

## 计算引擎层 (Calculation Engine)

计算引擎层提供期权量化指标的计算功能，采用三层架构设计：

### 期权策略计算

```python
from src.engine import (
    # 策略类
    ShortPutStrategy,
    CoveredCallStrategy,
    ShortStrangleStrategy,
    # 便捷接口
    calc_short_put_metrics,
    calc_option_sharpe_ratio,
    StrategyType,
)

# 方式 1: 使用策略类
strategy = ShortPutStrategy(
    spot_price=580,      # 现价
    strike_price=550,    # 行权价
    premium=6.5,         # 权利金
    volatility=0.20,     # 隐含波动率
    time_to_expiry=30/365,  # 到期时间 (年)
    risk_free_rate=0.03,
)

# 计算各项指标
expected_return = strategy.calc_expected_return()  # 期望收益
return_std = strategy.calc_return_std()            # 收益标准差
sharpe = strategy.calc_sharpe_ratio(margin_ratio=0.2)  # 夏普比率
kelly = strategy.calc_kelly_fraction()             # Kelly仓位
win_prob = strategy.calc_win_probability()         # 胜率

# 或一次性获取所有指标
metrics = strategy.calc_metrics()
print(f"期望收益: ${metrics.expected_return:.2f}")
print(f"夏普比率: {metrics.sharpe_ratio:.2f}")
print(f"胜率: {metrics.win_probability:.1%}")

# 方式 2: 使用便捷接口
metrics = calc_short_put_metrics(
    spot_price=580,
    strike_price=550,
    premium=6.5,
    volatility=0.20,
    time_to_expiry=30/365,
)

# 方式 3: 策略无关接口
sr = calc_option_sharpe_ratio(
    strategy_type=StrategyType.SHORT_PUT,
    spot_price=580,
    strike_price=550,
    premium=6.5,
    volatility=0.20,
    time_to_expiry=30/365,
    margin_ratio=0.2,
)
```

### B-S 模型基础计算

```python
from src.engine import (
    calc_d1, calc_d2, calc_n,
    calc_bs_call_price, calc_bs_put_price,
    calc_put_exercise_prob, calc_call_exercise_prob,
)

# B-S 参数
S, K, r, sigma, T = 100, 95, 0.03, 0.20, 30/365

# 计算 d1, d2
d1 = calc_d1(S, K, r, sigma, T)
d2 = calc_d2(d1, sigma, T)

# 计算理论价格
call_price = calc_bs_call_price(S, K, r, sigma, T)
put_price = calc_bs_put_price(S, K, r, sigma, T)

# 计算行权概率
put_prob = calc_put_exercise_prob(S, K, r, sigma, T)  # N(-d2)
call_prob = calc_call_exercise_prob(S, K, r, sigma, T)  # N(d2)
```

### 支持的策略

| 策略 | 类名 | 描述 |
|-----|------|------|
| Short Put | `ShortPutStrategy` | 卖出看跌期权 |
| Covered Call | `CoveredCallStrategy` | 持股卖购 |
| Short Strangle | `ShortStrangleStrategy` | 卖出宽跨式 |

### 核心公式

- **期望收益**: `E[π] = C - N(-d2) × [K - e^(rT) × S × N(-d1) / N(-d2)]`
- **夏普比率**: `SR = (E[π] - Rf) / Std[π]`，其中 `Rf = margin × K × (e^(rT) - 1)`
- **Kelly公式**: `f* = E[π] / Var[π]`

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
