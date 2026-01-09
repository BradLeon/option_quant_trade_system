# Option Quant Trade System

期权量化策略交易系统 - 基于 QuantConnect LEAN 引擎的期权交易系统

## 项目结构

```
option_quant_trade_system/
├── src/
│   ├── data/                    # 数据层
│   │   ├── models/              # 数据模型 (Option, Stock, Greeks, Technical)
│   │   │   ├── account.py       # AccountPosition, AccountSummary, ConsolidatedPortfolio
│   │   │   └── technical.py     # TechnicalData (K线→技术指标输入)
│   │   ├── providers/           # 数据提供者 (Yahoo, Futu, IBKR)
│   │   │   ├── account_aggregator.py  # 多券商账户聚合
│   │   │   └── unified_provider.py    # 统一数据路由 (含Greeks路由)
│   │   ├── currency/            # 汇率转换 (Yahoo Finance FX)
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
| **账户持仓** | ❌ | ✅ | ✅ |
| **现金余额** | ❌ | ✅ | ✅ |
| **期权Greeks路由** | N/A | fallback | 首选 |
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

**Greeks 数据获取增强：**
- ✅ **自动备用方案**：当 IBKR API 无法提供实时 Greeks 时（非交易时段、低流动性合约），自动使用 Black-Scholes 模型计算
- ✅ **完整数据保障**：确保即使在非交易时段也能获取完整的 Greeks 数据（delta, gamma, theta, vega, IV）
- ✅ **智能数据源**：
  1. 优先使用 IBKR API 实时 Greeks（交易时段）
  2. 如果失败，自动查询标的股票价格
  3. 使用标的股票波动率（IV/HV）
  4. 通过 Black-Scholes 公式计算 Greeks
- ✅ **支持港股期权**：`fetch_greeks_for_hk_option()` 方法同样支持备用方案
- ⚠️ **计算 Greeks 精度**：备用方案使用 Black-Scholes 模型，可能与实际市场 Greeks 略有差异，但足以支持策略分析

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

## 账户持仓模块 (Account & Position)

多券商账户聚合模块，支持从 IBKR 和 Futu 获取持仓，统一汇率转换，并使用智能路由获取期权 Greeks。

### 数据模型

```python
from src.data.models import (
    AccountType,      # REAL / PAPER
    AssetType,        # STOCK / OPTION / CASH
    AccountPosition,  # 单个持仓 (含 Greeks)
    AccountCash,      # 现金余额
    AccountSummary,   # 单券商账户概要
    ConsolidatedPortfolio,  # 合并后的投资组合
)
```

**AccountPosition 字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | str | 标的代码 (AAPL, 0700.HK) |
| asset_type | AssetType | 资产类型 |
| market | Market | 市场 (US/HK) |
| quantity | float | 持仓数量 |
| avg_cost | float | 平均成本 |
| market_value | float | 市值 |
| unrealized_pnl | float | 未实现盈亏 |
| currency | str | 货币 (USD/HKD) |
| strike | float | 期权行权价 |
| expiry | str | 期权到期日 |
| option_type | str | call/put |
| delta/gamma/theta/vega | float | 期权 Greeks |
| iv | float | 隐含波动率 |
| broker | str | 券商 (ibkr/futu) |

### 使用示例

```python
from src.data.providers import (
    IBKRProvider, FutuProvider, UnifiedDataProvider
)
from src.data.providers.account_aggregator import AccountAggregator
from src.data.models import AccountType

# 连接多个券商
with IBKRProvider(account_type=AccountType.REAL) as ibkr, \
     FutuProvider() as futu:

    # 创建 UnifiedProvider 用于期权 Greeks 路由
    # 路由规则: HK期权 → IBKR > Futu, US期权 → IBKR > Futu > Yahoo
    unified = UnifiedDataProvider(
        ibkr_provider=ibkr,
        futu_provider=futu,
    )

    # 创建账户聚合器
    aggregator = AccountAggregator(
        ibkr_provider=ibkr,
        futu_provider=futu,
        unified_provider=unified,  # 启用智能Greeks路由
    )

    # 获取合并后的投资组合
    portfolio = aggregator.get_consolidated_portfolio(
        account_type=AccountType.REAL,
        base_currency="USD",
    )

    print(f"总资产: ${portfolio.total_value_usd:,.2f}")
    print(f"未实现盈亏: ${portfolio.total_unrealized_pnl_usd:,.2f}")

    # 查看持仓
    for pos in portfolio.positions:
        print(f"[{pos.broker}] {pos.symbol}: {pos.quantity} @ {pos.market_value:,.2f} {pos.currency}")
        if pos.asset_type == AssetType.OPTION:
            print(f"  Delta: {pos.delta}, IV: {pos.iv}")

    # 按券商查看
    for broker, summary in portfolio.by_broker.items():
        print(f"{broker}: 总资产={summary.total_assets:,.2f}")
```

### 期权 Greeks 路由

系统使用智能路由获取期权 Greeks，解决不同券商的数据能力差异：

**路由规则**：
| 市场 | 数据类型 | Provider优先级 | 原因 |
|------|---------|---------------|------|
| HK | option_quote | IBKR > Futu | IBKR提供完整IV/Greeks，Futu需额外订阅 |
| US | option_quote | IBKR > Futu > Yahoo | IBKR数据最全，Yahoo无Greeks |

**实现原理**：
1. `AccountAggregator` 调用各券商 `get_positions(fetch_greeks=False)` 获取持仓
2. 收集完毕后调用 `UnifiedProvider.fetch_option_greeks_for_positions()` 统一获取 Greeks
3. 根据持仓的 market 属性，选择合适的 provider
4. 失败时自动 fallback 到下一个 provider

### 汇率转换

```python
from src.data.currency import CurrencyConverter

converter = CurrencyConverter()

# 自动从 Yahoo Finance 获取实时汇率
hkd_to_usd = converter.convert(10000, "HKD", "USD")
print(f"10,000 HKD = ${hkd_to_usd:,.2f} USD")

# 获取所有汇率
rates = converter.get_all_rates()  # {"HKD": 0.128, "CNY": 0.138, ...}
```

### 数据流与 Greeks 货币转换

系统从券商获取持仓数据后，经过货币转换，最终用于策略计算：

```
AccountPosition (券商原始数据, HKD/USD)
       ↓
_convert_position_currency() (account_aggregator.py)
       ↓
ConsolidatedPortfolio.positions (统一为 USD)
       ↓
  ┌────┴────┐
  ↓         ↓
Position    factory.py → OptionLeg + StrategyParams
(greeks_agg)              ↓
                      OptionStrategy (strategy metrics)
```

**Greeks 货币转换规则**：

根据 Greeks 的数学定义，不同的 Greeks 需要不同的转换方式：

| Greek | 数学定义 | 单位 | 转换方式 | 说明 |
|-------|---------|------|---------|------|
| Delta | ∂C/∂S | 无量纲 | **不转换** | 货币/货币 自动抵消 |
| Gamma | ∂²C/∂S² | 1/货币 | **÷ rate** | 二阶导，需除以汇率 |
| Theta | ∂C/∂t | 货币/天 | **× rate** | HKD→USD 需乘以汇率 |
| Vega | ∂C/∂σ | 货币/% | **× rate** | HKD→USD 需乘以汇率 |
| Rho | ∂C/∂r | 货币/% | **× rate** | HKD→USD 需乘以汇率 |

**为什么 Delta 不需要转换？**

```python
# Delta = (期权价格变化) / (股价变化) = 货币/货币 = 无量纲
# HKD: Δ = 0.5 HKD / 1 HKD = 0.5
# USD: Δ = (0.5/rate) / (1/rate) = 0.5 (不变!)
```

**为什么 Gamma 要除以汇率？**

```python
# Gamma 是二阶导：Γ = ∂Δ/∂S
# Δ 无量纲，S 有货币单位
# Γ_USD = ∂Δ/∂S_USD = ∂Δ/∂(S_HKD × rate) = Γ_HKD / rate
```

**Gamma Dollars 计算验证**：

系统将 Gamma 转换为 Gamma Dollars 格式以便跨货币聚合：

```python
# Gamma Dollars = Γ × S² × 0.01
#
# 方法1: 先算 HKD，再转 USD
# Gamma$_HKD = Γ_HKD × S_HKD² × 0.01
# Gamma$_USD = Gamma$_HKD × rate
#
# 方法2: 用转换后的参数计算
# Gamma$_USD = Γ_HKD × (S_HKD × rate)² × 0.01 / rate
#            = Γ_HKD × S_HKD² × rate² × 0.01 / rate
#            = Γ_HKD × S_HKD² × rate × 0.01  ✓ (两种方法结果一致)
```

**示例 (700.HK Short Put)**：

```python
# 原始数据 (HKD)
S_HKD = 602.0
Γ_HKD = 0.0067
θ_HKD = -0.0819  # 每天
ν_HKD = 0.3664   # per 1% IV

# 汇率
rate = 0.1286  # HKD → USD

# 转换后 (USD)
S_USD = 602 × 0.1286 = 77.44
Γ_USD = 0.0067 / 0.1286 = 0.052  # 变大！
θ_USD = -0.0819 × 0.1286 = -0.0105
ν_USD = 0.3664 × 0.1286 = 0.0471

# Gamma Dollars (USD)
Gamma$_USD = 0.0067 × 602² × 0.01 × 0.1286 = 3.12
# 或等价于
Gamma$_USD = 0.052 × 77.44² × 0.01 / 0.1286 = 3.12  ✓
```

### 核心公式

- **期望收益**: `E[π] = C - N(-d2) × [K - e^(rT) × S × N(-d1) / N(-d2)]`
- **夏普比率**: `SR = (E[π] - Rf) / Std[π]`，其中 `Rf = margin × K × (e^(rT) - 1)`
- **Kelly公式**: `f* = E[π] / Var[π]`

### ROC 与 Expected ROC

系统提供两个关键的年化收益指标，用于评估期权策略的收益潜力：

| 指标 | 公式 | 说明 |
|------|------|------|
| **ROC** | `(premium / capital) × (365/dte)` | 确定性权利金收入的年化收益率 |
| **Expected ROC** | `(expected_return / capital) × (365/dte)` | 概率加权期望收益的年化收益率 |

**Capital 的选择（按策略类型）**：

| 策略 | Capital | 说明 |
|------|---------|------|
| Short Put | margin_requirement | IBKR保证金公式 |
| Short Call | margin_requirement | IBKR保证金公式 |
| Covered Call | stock_cost_basis | 正股持仓成本（资金锁定） |
| Short Strangle | margin_requirement | 两腿中较高的保证金 |

**为什么 Covered Call 使用 stock_cost_basis？**

对于 Covered Call，真正锁定的资金是购买正股的成本，而不是期权保证金（几乎为零）。如果使用 margin_requirement，会导致 ROC 虚高：

```python
# 错误示例
ROC = 0.72 / 0.72 × (365/21) = 1738%  # ← 使用 margin = premium

# 正确计算
ROC = 0.72 / 315.47 × (365/21) = 3.97%  # ← 使用 stock_cost_basis
```

**ROC vs Expected ROC 的意义**：

ROC 告诉你「确定能收到多少钱」，Expected ROC 告诉你「这笔交易的期望价值」。

```
示例: ATM Short Put (3 DTE)
├─ ROC = 237.8% (权利金年化，看起来很诱人)
└─ Expected ROC = -78.5% (实际期望为负，这是亏钱的交易!)

原因分析:
├─ 58% 概率: 赚 $0.30 (保留权利金)
└─ 42% 概率: 亏 $0.66 (被行权损失)
加权期望 = 0.58×0.30 + 0.42×(-0.66) = -$0.10
```

**Expected ROC 与其他指标的一致性**：
- Expected ROC < 0 → Sharpe Ratio < 0 → Kelly Fraction = 0
- 三个指标一致表明这是一个负期望交易，不应该做

**Covered Call 的 Expected Return 计算**：

Covered Call 的期望收益包含股票和期权两部分：

```python
# E[Return] = E[Stock Gain] + Premium - E[Call Payoff]
#           = (S × e^(rT) - S) + C - (S × e^(rT) × N(d1) - K × N(d2))
```

因此对于 Covered Call：
- ROC 仅反映期权权利金收入
- Expected ROC 反映整体策略收益（含股票增值期望）
- 通常 Expected ROC > ROC（因为包含了股票上涨预期）

## 业务层 CLI (Business Layer CLI)

业务层命令行工具，提供开仓筛选、持仓监控、实时仪表盘等功能。

### 安装与运行

```bash
# 运行 CLI
python -m src.business.cli.main --help

# 或使用别名 (需配置)
optrade --help
```

### 命令列表

| 命令 | 说明 |
|------|------|
| `dashboard` | 实时监控仪表盘 |
| `monitor` | 运行持仓监控（三层预警） |
| `screen` | 运行开仓筛选 |
| `notify` | 测试通知发送 |

### Dashboard 仪表盘

实时监控仪表盘，显示完整的组合健康度、资金管理、风险热力图和持仓明细。

```bash
# 使用示例数据（无需连接券商）
python -m src.business.cli.main dashboard

# 从 Paper 账户获取真实数据
python -m src.business.cli.main dashboard --account-type paper

# 自动刷新（每30秒）
python -m src.business.cli.main dashboard -a paper --refresh 30

# 仅使用 IBKR 账户
python -m src.business.cli.main dashboard -a paper --ibkr-only
```

**仪表盘布局**：

```
══════════════════════════════════════════════════════════════════════════════
  实时监控仪表盘  |  2025-12-29 15:48:22  |  状态: 🟢
══════════════════════════════════════════════════════════════════════════════

┌─── Portfolio健康度 ────────────────┐    ┌─── 资金管理 ─────────────────────┐
│ Delta:  +163 [████████░░] 🟢       │    │ Sharpe Ratio:   1.80  🟢         │
│ Theta:   +64 [██████░░░░] 🟢       │    │ Kelly Optimal:  8.5%             │
│ Vega:   -410 [████░░░░░░] 🟡       │    │ Current Usage:  7.2%  🟢         │
│ Gamma:   -65 [███░░░░░░░] 🟡       │    │ Margin Usage:  25.0%  🟢         │
│ TGR:    0.98 [████████░░] 🟢       │    │ Drawdown:       2.1%  🟢         │
│ HHI:    0.12 [██░░░░░░░░] 🟢       │    └──────────────────────────────────┘
└────────────────────────────────────┘

┌─── 风险热力图 ─────────────────────┐    ┌─── 今日待办 ─────────────────────┐
│        AAPL  TSLA   SPY  NVDA      │    │ 🚨 [NVDA] 处理高Gamma风险        │
│ PREI    45    55    60   88🔴      │    │ ⚡ [SPY] 评估加仓机会            │
│ SAS     70    75   85🟢   40       │    │ 👁️ [portfolio] 监控相关性风险    │
└────────────────────────────────────┘    └──────────────────────────────────┘

┌─── 期权持仓明细 ────────────────────────────────────────────────────────────┐
│ 标的 │类型│行权价│DTE│Delta│Gamma│Theta│Vega│ TGR │ ROC │PREI│SAS│状态    │
├──────┼────┼──────┼───┼─────┼─────┼─────┼────┼─────┼─────┼────┼───┼────    │
│ AAPL │Put │  170 │ 25│  +30│   -2│  +12│ -80│ 0.60│  28%│  45│ 70│        │
│ NVDA │Call│  450 │  7│  -55│  -12│   +9│ -50│ 0.08│  42%│  88│ 40│🔴      │
└──────────────────────────────────────────────────────────────────────────────┘

┌─── 股票持仓明细 ────────────────────────────────────────────────────────────┐
│ 标的 │数量│ 成本 │ 现价 │盈亏% │Delta│RSI│趋势│ 支撑 │ 阻力 │基本面│状态  │
├──────┼────┼──────┼──────┼──────┼─────┼───┼────┼──────┼──────┼──────┼────  │
│ AAPL │ 100│175.0 │185.0 │+5.7% │  100│ 55│bull│170.0 │195.0 │ 78.5 │🟢    │
│ MSFT │  50│380.0 │340.0 │-10.5%│   50│ 42│neut│320.0 │360.0 │ 82.0 │🔴    │
└──────────────────────────────────────────────────────────────────────────────┘
──────────────────────────────────────────────────────────────────────────────
  总持仓: 7 | 风险持仓: 1 | 机会持仓: 0 | 预警: 🔴2 🟡9 🟢4
══════════════════════════════════════════════════════════════════════════════
```

**面板说明**：

| 面板 | 内容 | 指标 |
|------|------|------|
| Portfolio健康度 | 组合级Greeks汇总 | Delta, Theta, Vega, Gamma, TGR, HHI |
| 资金管理 | 资金层风险指标 | Sharpe, Kelly, Margin, Drawdown |
| 风险热力图 | 按标的展示风险 | PREI (风险指数), SAS (策略评分) |
| 今日待办 | 建议列表 | 🚨立即 ⚡尽快 👁️监控 |
| 期权持仓明细 | 期权持仓详情 | Greeks, TGR, ROC, PREI, SAS |
| 股票持仓明细 | 股票持仓详情 | 技术面, 基本面 |

**预警图标**：
- 🔴 红色：需要立即处理（高风险/超阈值）
- 🟡 黄色：需要关注（接近阈值）
- 🟢 绿色：正常/机会

### Monitor 持仓监控

三层持仓监控，生成风险预警和调整建议。

```bash
# 从 Paper 账户监控
python -m src.business.cli.main monitor --account-type paper

# 仅显示红色预警
python -m src.business.cli.main monitor -a paper --level red

# 推送预警到飞书
python -m src.business.cli.main monitor -a paper --push

# JSON 格式输出
python -m src.business.cli.main monitor -a paper --output json

# 从文件加载数据
python -m src.business.cli.main monitor -p positions.json -C capital.json
```

**监控层级**：

| 层级 | 监控内容 | 关键指标 |
|------|---------|---------|
| Portfolio级 | 组合整体风险 | Beta加权Delta, 组合TGR, 集中度HHI |
| Position级 | 单个持仓风险 | DTE, PREI, SAS, TGR |
| Capital级 | 资金层面风险 | Margin使用率, Kelly使用率, Drawdown |

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
