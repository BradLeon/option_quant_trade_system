<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# 项目架构概览

## 数据层 (src/data/)

数据层负责从外部数据源获取数据，定义统一的数据模型。

### 核心模型 (src/data/models/)
- `Greeks` - 期权希腊值 (delta, gamma, theta, vega, rho)
- `OptionContract` - 期权合约
- `OptionQuote` - 期权行情
- `StockQuote` - 股票行情
- `Fundamental` - 基本面数据

### 数据提供者 (src/data/providers/)
- `YahooProvider` - 免费数据，基本面/宏观数据
- `FutuProvider` - 港股/美股实时数据
- `IBKRProvider` - 美股交易数据

## 计算引擎层 (src/engine/)

计算引擎层提供期权量化指标计算，采用分层架构：

### 数据模型 (src/engine/models/)

```
BSParams       - B-S计算参数封装 (spot, strike, rate, vol, time, is_call)
Position       - 持仓模型 (symbol, quantity, greeks=Greeks(...), beta, dte, etc.)
OptionLeg      - 期权腿 (option_type, side, strike, premium, greeks=Greeks(...))
StrategyParams - 策略通用参数
StrategyMetrics - 策略计算结果
```

**设计原则：**
- 使用组合模式：Position 和 OptionLeg 内嵌 Greeks 对象
- 函数接受模型对象而非大量原始参数
- 工厂方法支持从市场数据构建：`BSParams.from_market_data()`, `Position.from_market_data()`

### B-S 核心计算 (src/engine/bs/)

所有函数接受 `BSParams` 对象：

```python
# core.py
calc_d1(params: BSParams) -> float
calc_d2(params: BSParams, d1: float) -> float
calc_bs_price(params: BSParams) -> float

# greeks.py
calc_bs_delta(params: BSParams) -> float
calc_bs_gamma(params: BSParams) -> float
calc_bs_theta(params: BSParams) -> float
calc_bs_vega(params: BSParams) -> float

# probability.py
calc_put_exercise_prob(params: BSParams) -> float
calc_call_exercise_prob(params: BSParams) -> float
```

### 策略层 (src/engine/strategy/)

策略类封装完整的期权策略计算：

```
OptionStrategy (抽象基类)
├── ShortPutStrategy     - 卖出看跌
├── CoveredCallStrategy  - 持股卖购
└── ShortStrangleStrategy - 卖出宽跨式

每个策略提供：
- calc_expected_return()   期望收益
- calc_return_variance()   收益方差
- calc_max_profit()        最大盈利
- calc_max_loss()          最大亏损
- calc_breakeven()         盈亏平衡点
- calc_win_probability()   胜率
- calc_sharpe_ratio()      夏普比率
- calc_kelly_fraction()    Kelly仓位
- calc_prei()              风险暴露指数 (需要gamma, vega, dte)
- calc_sas()               策略吸引力评分 (需要hv)
- calc_tgr()               Theta/Gamma比率 (需要theta, gamma)
- calc_roc()               年化资本回报率 (需要dte)
- calc_metrics()           一次性计算所有指标
```

### 持仓级计算 (src/engine/position/)

```
greeks.py           - 从报价获取/计算Greeks
option_metrics.py   - calc_sas() 策略吸引力评分
risk_return.py      - calc_prei(), calc_tgr(), calc_roc_from_dte()
volatility/         - HV/IV/IV Rank
technical/          - RSI, 支撑位
fundamental/        - 基本面指标提取
```

### 组合级计算 (src/engine/portfolio/)

```
greeks_agg.py       - 组合Greeks汇总
                      calc_portfolio_theta/vega/gamma()
                      calc_delta_dollars()
                      calc_beta_weighted_delta()
composite.py        - calc_portfolio_prei(), calc_portfolio_sas()
risk_metrics.py     - calc_portfolio_tgr(), calc_portfolio_var()
returns.py          - 收益率, 夏普比率, Kelly
```

### 账户级计算 (src/engine/account/)

```
capital.py          - calc_roc()
margin.py           - 保证金计算
position_sizing.py  - 仓位管理
sentiment/          - VIX解读, PCR, 趋势判断
```

## 测试 (tests/engine/)

```
test_bs.py          - B-S核心计算测试
test_greeks.py      - Greeks获取/计算测试
test_strategy.py    - 策略类测试
test_portfolio.py   - 组合计算测试
test_risk_return.py - 风险收益指标测试
test_models.py      - 模型测试
```

## 代码规范

1. **模型优先**：函数接受模型对象 (BSParams, Position) 而非大量参数
2. **组合模式**：Greeks 作为独立对象嵌入 Position/OptionLeg
3. **工厂方法**：提供 `from_market_data()` 从数据层模型构建引擎层模型
4. **类型安全**：使用 `TYPE_CHECKING` 避免循环导入
5. **测试覆盖**：每个模块有对应测试文件