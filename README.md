# Option Quant Trade System

期权量化策略交易系统 - 基于 QuantConnect LEAN 引擎的期权交易系统

## 项目结构

```
option_quant_trade_system/
├── src/
│   ├── data/                    # 数据层
│   │   ├── models/              # 数据模型 (Option, Stock, Greeks, Technical)
│   │   │   └── technical.py     # TechnicalData (K线→技术指标输入)
│   │   ├── providers/           # 数据提供者 (Yahoo, Futu, IBKR)
│   │   ├── formatters/          # 数据格式化 (QuantConnect)
│   │   └── cache/               # 数据缓存 (Supabase)
│   └── engine/                  # 计算引擎层
│       ├── models/              # 引擎数据模型
│       │   ├── bs_params.py     # BSParams - B-S计算参数封装
│       │   ├── position.py      # Position - 持仓模型(含Greeks)
│       │   ├── strategy.py      # OptionLeg, StrategyParams, StrategyMetrics
│       │   └── enums.py         # 枚举类型
│       ├── bs/                  # B-S 模型核心计算
│       │   ├── core.py          # calc_d1, calc_d2, calc_n, calc_bs_price
│       │   ├── greeks.py        # calc_bs_delta/gamma/theta/vega/rho
│       │   └── probability.py   # calc_exercise_prob, calc_itm_prob
│       ├── strategy/            # 期权策略实现
│       │   ├── base.py          # OptionStrategy 抽象基类
│       │   ├── short_put.py     # ShortPutStrategy
│       │   ├── covered_call.py  # CoveredCallStrategy
│       │   └── strangle.py      # ShortStrangleStrategy
│       ├── position/            # 持仓级计算
│       │   ├── greeks.py        # get_greeks, get_delta (从报价获取/计算)
│       │   ├── option_metrics.py # calc_sas (策略吸引力评分)
│       │   ├── risk_return.py   # calc_prei, calc_tgr, calc_roc
│       │   ├── volatility/      # HV/IV/IV Rank 计算
│       │   ├── technical/       # 技术指标 (MA/ADX/BB/RSI/ATR)
│       │   │   ├── metrics.py   # TechnicalScore, TechnicalSignal
│       │   │   ├── thresholds.py # TechnicalThresholds 可配置阈值
│       │   │   ├── moving_average.py # SMA/EMA (20/50/200)
│       │   │   ├── adx.py       # ADX/+DI/-DI (趋势强度)
│       │   │   ├── bollinger_bands.py # BB/%B/Bandwidth
│       │   │   ├── rsi.py       # RSI (相对强弱)
│       │   │   └── support.py   # 支撑/阻力位
│       │   └── fundamental/     # 基本面指标提取
│       ├── portfolio/           # 组合级计算
│       │   ├── greeks_agg.py    # 组合Greeks汇总(delta$, BWD, gamma$)
│       │   ├── composite.py     # 组合PREI, 组合SAS
│       │   ├── risk_metrics.py  # 组合TGR, VaR
│       │   └── returns.py       # 收益率, 夏普比率, Kelly
│       └── account/             # 账户级计算
│           ├── capital.py       # ROC计算
│           ├── margin.py        # 保证金计算
│           ├── position_sizing.py # 仓位管理
│           └── sentiment/       # 市场情绪(VIX, PCR, 趋势)
├── examples/                    # 示例代码
├── tests/                       # 测试代码
│   └── engine/                  # 引擎层测试
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

计算引擎层提供期权量化指标的计算功能，采用四层架构设计：
- **models**: 数据模型 (BSParams, Position, OptionLeg, StrategyMetrics)
- **bs**: Black-Scholes 核心计算
- **strategy**: 期权策略封装
- **position/portfolio/account**: 多级风险指标计算

### 数据模型设计

引擎层使用组合模式，通过模型对象封装参数：

```python
from src.engine.models import BSParams, Position
from src.data.models.option import Greeks

# BSParams - 封装 B-S 计算参数
params = BSParams(
    spot_price=100.0,
    strike_price=95.0,
    risk_free_rate=0.03,
    volatility=0.20,
    time_to_expiry=30/365,
    is_call=False,  # Put option
)

# Position - 持仓模型，使用 Greeks 组合
position = Position(
    symbol="AAPL",
    quantity=2,
    greeks=Greeks(delta=0.5, gamma=0.02, theta=-0.05, vega=0.30),
    beta=1.2,
    underlying_price=150.0,
    margin=5000.0,
    dte=30,
)
```

### 期权策略计算

```python
from src.engine.strategy import (
    ShortPutStrategy,
    CoveredCallStrategy,
    ShortStrangleStrategy,
)

# 使用策略类
strategy = ShortPutStrategy(
    spot_price=580,      # 现价
    strike_price=550,    # 行权价
    premium=6.5,         # 权利金
    volatility=0.20,     # 隐含波动率
    time_to_expiry=30/365,  # 到期时间 (年)
    risk_free_rate=0.03,
    # 可选：传入 Greeks 用于扩展指标计算
    hv=0.18,             # 历史波动率 (用于 SAS)
    dte=30,              # 到期天数 (用于 PREI, ROC)
    gamma=0.02,          # 用于 TGR, PREI
    theta=-0.05,         # 用于 TGR
    vega=0.30,           # 用于 PREI
)

# 计算各项指标
expected_return = strategy.calc_expected_return()  # 期望收益
return_std = strategy.calc_return_std()            # 收益标准差
sharpe = strategy.calc_sharpe_ratio(margin_ratio=0.2)  # 夏普比率
kelly = strategy.calc_kelly_fraction()             # Kelly仓位
win_prob = strategy.calc_win_probability()         # 胜率

# 扩展指标 (需要额外参数)
prei = strategy.calc_prei()   # 风险暴露指数 (0-100)
sas = strategy.calc_sas()     # 策略吸引力评分 (0-100)
tgr = strategy.calc_tgr()     # Theta/Gamma 比率
roc = strategy.calc_roc()     # 年化资本回报率

# 一次性获取所有指标
metrics = strategy.calc_metrics()
print(f"期望收益: ${metrics.expected_return:.2f}")
print(f"夏普比率: {metrics.sharpe_ratio:.2f}")
print(f"胜率: {metrics.win_probability:.1%}")
print(f"PREI: {metrics.prei:.1f}")  # 风险指数
print(f"SAS: {metrics.sas:.1f}")    # 吸引力评分
```

### B-S 模型基础计算

```python
from src.engine.models import BSParams
from src.engine.bs import (
    calc_d1, calc_d2, calc_n,
    calc_bs_price,
    calc_bs_delta, calc_bs_gamma, calc_bs_theta, calc_bs_vega,
    calc_put_exercise_prob, calc_call_exercise_prob,
)

# 使用 BSParams 封装参数
params = BSParams(
    spot_price=100,
    strike_price=95,
    risk_free_rate=0.03,
    volatility=0.20,
    time_to_expiry=30/365,
    is_call=True,
)

# 计算 d1, d2
d1 = calc_d1(params)
d2 = calc_d2(params, d1)

# 计算理论价格
call_price = calc_bs_price(params)
put_price = calc_bs_price(params.with_is_call(False))

# 计算 Greeks
delta = calc_bs_delta(params)
gamma = calc_bs_gamma(params)
theta = calc_bs_theta(params)
vega = calc_bs_vega(params)

# 计算行权概率
put_params = params.with_is_call(False)
put_prob = calc_put_exercise_prob(put_params)   # N(-d2)
call_prob = calc_call_exercise_prob(params)     # N(d2)
```

### 组合级计算

```python
from src.engine.models import Position
from src.data.models.option import Greeks
from src.engine.portfolio import (
    calc_portfolio_theta,
    calc_portfolio_vega,
    calc_portfolio_gamma,
    calc_delta_dollars,
    calc_beta_weighted_delta,
    calc_portfolio_tgr,
    calc_portfolio_prei,
)

# 构建持仓列表
positions = [
    Position(
        symbol="AAPL",
        quantity=2,
        greeks=Greeks(delta=0.5, gamma=0.02, theta=-5.0, vega=10.0),
        underlying_price=150.0,
        beta=1.2,
        dte=30,
    ),
    Position(
        symbol="MSFT",
        quantity=-1,
        greeks=Greeks(delta=0.4, gamma=0.01, theta=-3.0, vega=8.0),
        underlying_price=400.0,
        beta=1.1,
        dte=30,
    ),
]

# 组合 Greeks 汇总
portfolio_theta = calc_portfolio_theta(positions)
portfolio_vega = calc_portfolio_vega(positions)
portfolio_gamma = calc_portfolio_gamma(positions)
delta_dollars = calc_delta_dollars(positions)
bwd = calc_beta_weighted_delta(positions, spy_price=450.0)

# 组合风险指标
tgr = calc_portfolio_tgr(positions)      # Theta/Gamma 比率
prei = calc_portfolio_prei(positions)    # 组合风险暴露指数
```

### 支持的策略

| 策略 | 类名 | 描述 |
|-----|------|------|
| Short Put | `ShortPutStrategy` | 卖出看跌期权 |
| Covered Call | `CoveredCallStrategy` | 持股卖购 |
| Short Strangle | `ShortStrangleStrategy` | 卖出宽跨式 |

### 技术面指标模块

技术指标模块专为期权卖方策略设计，提供统一接口：

```python
from src.data.models.technical import TechnicalData
from src.engine.position.technical import (
    calc_technical_score,
    calc_technical_signal,
    TechnicalThresholds,
)

# 1. 从K线数据创建 TechnicalData
bars = provider.get_history_kline("TSLA", KlineType.DAY, start_date, end_date)
data = TechnicalData.from_klines(bars)

# 2. 计算技术指标 (TechnicalScore)
score = calc_technical_score(data)
print(f"SMA20: {score.sma20:.2f}")
print(f"RSI: {score.rsi:.2f} ({score.rsi_zone})")
print(f"ADX: {score.adx:.2f}")
print(f"BB %B: {score.bb_percent_b:.2f}")
print(f"ATR: {score.atr:.2f}")

# 3. 生成交易信号 (TechnicalSignal)
signal = calc_technical_signal(data)
print(f"市场状态: {signal.market_regime} (趋势强度: {signal.trend_strength})")
print(f"卖Put信号: {signal.sell_put_signal}")
print(f"卖Call信号: {signal.sell_call_signal}")
print(f"Put行权价建议: < {signal.recommended_put_strike_zone:.2f}")
print(f"危险时段: {signal.is_dangerous_period}")

# 4. 自定义阈值 (用于回测优化)
custom_thresholds = TechnicalThresholds(
    adx_strong=30.0,      # 更保守的强趋势阈值
    rsi_stabilizing_low=35.0,  # 调整企稳区间
    atr_buffer_multiplier=2.0,  # 更大的行权价buffer
)
signal = calc_technical_signal(data, thresholds=custom_thresholds)
```

**TechnicalScore 指标**：
| 指标 | 字段 | 说明 |
|------|------|------|
| 移动平均 | sma20/50/200, ema20 | 趋势判断 |
| MA排列 | ma_alignment | strong_bullish/bullish/neutral/bearish/strong_bearish |
| RSI | rsi, rsi_zone | 超买/超卖判断 |
| ADX | adx, plus_di, minus_di | 趋势强度 |
| 布林带 | bb_upper/middle/lower, bb_percent_b, bb_bandwidth | 波动率 |
| ATR | atr | 动态行权价buffer |
| 支撑阻力 | support, resistance | 关键价位 |

**TechnicalSignal 信号**：
| 信号 | 说明 |
|------|------|
| market_regime | ranging/trending_up/trending_down |
| allow_short_put/call/strangle | 策略是否适用 |
| sell_put_signal/sell_call_signal | none/weak/moderate/strong |
| recommended_put/call_strike_zone | ATR动态buffer计算 |
| close_put_signal/close_call_signal | 平仓信号 |
| is_dangerous_period | BB Squeeze / 强趋势 / 接近支撑阻力 |

**信号逻辑**（专家Review优化）：
- **企稳入场**：RSI 30-45 + %B 0.1-0.3 → 卖Put（避免"接飞刀"）
- **动能衰竭**：RSI 55-70 + %B 0.7-0.9 → 卖Call
- **强趋势屏蔽**：ADX > 45 时禁止逆势开仓
- **BB Squeeze**：bandwidth < 0.08 禁用Strangle
- **ATR行权价**：strike = support - 1.5×ATR

### 市场情绪模块

市场情绪模块提供宏观层面的市场状态分析，用于账户级风险管理决策：

```python
from src.data.providers import UnifiedDataProvider
from src.engine.account.sentiment.data_bridge import (
    get_us_sentiment,
    get_hk_sentiment,
)
from src.engine.account.sentiment import get_sentiment_summary

provider = UnifiedDataProvider()

# US 市场情绪分析
us_sentiment = get_us_sentiment(provider)
print(f"VIX: {us_sentiment.vix_value:.1f} ({us_sentiment.vix_zone.value})")
print(f"VIX信号: {us_sentiment.vix_signal.value}")  # bullish/bearish/neutral
print(f"期限结构: {us_sentiment.term_structure.structure.value if us_sentiment.term_structure else 'N/A'}")
print(f"SPY趋势: {us_sentiment.primary_trend.signal.value if us_sentiment.primary_trend else 'N/A'}")
print(f"综合评分: {us_sentiment.composite_score:.1f} ({us_sentiment.composite_signal.value})")
print(f"适合卖权: {us_sentiment.favorable_for_selling}")

# HK 市场情绪分析
hk_sentiment = get_hk_sentiment(provider)
print(get_sentiment_summary(hk_sentiment))
```

**MarketSentiment 字段**：
| 字段 | 说明 |
|------|------|
| vix_value | VIX/VHSI 当前值 |
| vix_zone | LOW/NORMAL/ELEVATED/HIGH/EXTREME |
| vix_signal | 逆向信号（高恐慌=bullish，低恐慌=bearish） |
| term_structure | VIX期限结构（contango/backwardation/flat） |
| primary_trend | 主指数趋势（SPY/HSI） |
| secondary_trend | 次指数趋势（QQQ/HSTECH） |
| pcr | Put/Call Ratio 分析 |
| composite_score | 综合评分（-100到+100） |
| composite_signal | 综合信号（>20=bullish, <-20=bearish） |
| favorable_for_selling | 是否适合卖权策略 |

**数据源配置**：
| 市场 | 数据项 | 数据源 |
|------|--------|--------|
| US | VIX/VIX3M | Yahoo (^VIX, ^VIX3M) |
| US | SPY/QQQ价格 | Yahoo/Futu/IBKR |
| US | PCR | Yahoo (计算) |
| HK | VHSI | Futu (800125.HK) 或 IBKR (2800.HK IV) |
| HK | HSI价格 | Futu (800000.HK) 或 Yahoo (^HSI) |
| HK | HSTECH价格 | Futu (3032.HK) |
| HK | PCR | IBKR (2800.HK Open Interest) |

**注意事项**：
- HK市场的`vhsi_3m_proxy`目前不可用（IBKR远期期权合约未上市），term_structure返回None
- 综合评分采用加权计算：VIX(25%) + 期限结构(15%) + 主趋势(25%) + 次趋势(15%) + PCR(20%)
- 缺失数据时权重自动重新分配

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
