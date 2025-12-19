## Context

计算引擎层是系统四层架构中的第二层，位于数据层之上、业务层之下。负责将原始市场数据加工为可用于策略决策的量化指标。

**约束条件：**
- 算子实现必须是纯计算逻辑，不关心数据来源
- 算子输出格式标准化，便于后续业务层使用
- 支持单值计算和批量计算

## Goals / Non-Goals

**Goals:**
- 实现完整的量化指标算子库
- 保证每个算子计算的正确性
- 代码结构清晰，易于扩展新算子
- 算子之间解耦，可独立使用

**Non-Goals:**
- 本阶段不关心算子的数据来源（由调用方负责）
- 本阶段不关心算子如何被策略使用
- 不实现算子的缓存和持久化

## Decisions

### 1. 目录结构

```
src/engine/
├── __init__.py
├── base.py              # 基础类型和接口定义
├── bs/                  # Black-Scholes 基础计算层
│   ├── __init__.py
│   ├── core.py          # d1, d2, d3, N(d), B-S定价
│   └── probability.py   # 行权概率、ITM概率
├── strategy/            # 期权策略实现层
│   ├── __init__.py
│   ├── base.py          # OptionStrategy基类、OptionLeg、StrategyMetrics
│   ├── short_put.py     # Short Put策略
│   ├── covered_call.py  # Covered Call策略
│   └── strangle.py      # Short Strangle策略
├── greeks/              # 希腊值相关
│   ├── __init__.py
│   └── calculator.py    # Greeks计算/获取
├── volatility/          # 波动率相关
│   ├── __init__.py
│   ├── historical.py    # HV计算
│   ├── implied.py       # IV相关
│   └── iv_rank.py       # IV Rank计算
├── returns/             # 收益风险指标
│   ├── __init__.py
│   ├── basic.py         # 基础收益计算
│   ├── risk.py          # 风险指标(夏普、最大回撤)
│   ├── kelly.py         # Kelly公式
│   └── option_expected.py  # 期权策略无关接口
├── sentiment/           # 市场情绪
│   ├── __init__.py
│   ├── vix.py           # VIX指标
│   ├── trend.py         # 趋势判断
│   └── pcr.py           # Put/Call Ratio
├── fundamental/         # 基本面
│   ├── __init__.py
│   └── metrics.py       # PE、增长率等
├── technical/           # 技术面
│   ├── __init__.py
│   ├── rsi.py           # RSI计算
│   └── support.py       # 支撑位计算
└── portfolio/           # 组合指标
    ├── __init__.py
    ├── greeks_agg.py    # 组合Greeks汇总
    ├── risk_metrics.py  # TGR, ROC等
    └── composite.py     # SAS, PREI等复合指标
```

### 2. 算子函数签名设计原则

```python
# 单值算子
def calculate_xxx(input_data: InputType) -> float:
    """计算单个指标值"""
    pass

# 批量算子
def calculate_xxx_batch(items: list[InputType]) -> list[float]:
    """批量计算，提高效率"""
    pass

# 返回多值的算子使用dataclass
@dataclass
class XxxResult:
    value: float
    signal: str  # e.g., "bullish", "bearish", "neutral"
    details: dict[str, Any] | None = None

def calculate_xxx(input_data: InputType) -> XxxResult:
    pass
```

### 3. 各模块算子清单

| 模块 | 算子 | 输入 | 输出 |
|------|------|------|------|
| **B-S Core** | calc_d1 | S, K, r, σ, T | float |
| | calc_d2 | d1, σ, T | float |
| | calc_d3 | d2, σ, T | float |
| | calc_n | d | float (0-1) |
| | calc_bs_call_price | S, K, r, σ, T | float |
| | calc_bs_put_price | S, K, r, σ, T | float |
| **B-S Probability** | calc_put_exercise_prob | S, K, r, σ, T | float (0-1) |
| | calc_call_exercise_prob | S, K, r, σ, T | float (0-1) |
| | calc_put_itm_prob | S, K, r, σ, T | float (0-1) |
| | calc_call_itm_prob | S, K, r, σ, T | float (0-1) |
| **Strategy** | ShortPutStrategy | S, K, C, σ, T, r | StrategyMetrics |
| | CoveredCallStrategy | S, K, C, σ, T, r | StrategyMetrics |
| | ShortStrangleStrategy | S, K_p, K_c, C_p, C_c, σ, T, r | StrategyMetrics |
| **Greeks** | get_greeks | OptionQuote | Greeks |
| **Volatility** | calc_hv | prices[], window | float |
| | get_iv | OptionQuote | float |
| | calc_iv_hv_ratio | iv, hv | float |
| | calc_iv_rank | current_iv, hist_ivs[] | float (0-100) |
| **Returns** | calc_annualized_return | returns[], periods | float |
| | calc_win_rate | trades[] | float (0-1) |
| | calc_expected_return | win_rate, avg_win, avg_loss | float |
| | calc_expected_std | returns[] | float |
| | calc_sharpe_ratio | returns[], risk_free_rate | float |
| | calc_kelly | win_rate, win_loss_ratio | float |
| | calc_max_drawdown | equity_curve[] | float |
| | calc_option_sharpe_ratio | strategy_type, params | float |
| | calc_option_kelly_fraction | strategy_type, params | float |
| **Sentiment** | get_vix | (from data layer) | float |
| | calc_spy_trend | prices[], window | TrendSignal |
| | calc_pcr | put_vol, call_vol | float |
| **Fundamental** | get_pe | Fundamental | float |
| | get_revenue_growth | Fundamental | float |
| | get_profit_margin | Fundamental | float |
| | get_analyst_rating | Fundamental | RatingSignal |
| **Technical** | calc_rsi | prices[], period | float (0-100) |
| | calc_support_distance | price, support | float (%) |
| **Portfolio** | calc_beta_weighted_delta | positions[], betas[] | float |
| | calc_portfolio_theta | positions[] | float |
| | calc_portfolio_vega | positions[] | float |
| | calc_portfolio_gamma | positions[] | float |
| | calc_tgr | theta, gamma | float |
| | calc_roc | profit, capital | float |
| | calc_sas | allocations[] | float |
| | calc_prei | exposures[] | float |

### 4. 数据类型定义

```python
# base.py
from dataclasses import dataclass
from enum import Enum

class TrendSignal(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class RatingSignal(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"

@dataclass
class Position:
    """持仓信息，用于组合计算"""
    symbol: str
    quantity: float
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    beta: float | None = None
    market_value: float | None = None
```

### 5. 期权策略架构设计

采用三层架构分离关注点：

```
┌─────────────────────────────────────────────────────────────┐
│  策略无关接口层 (option_expected.py)                          │
│  calc_option_sharpe_ratio(strategy_type, **params)          │
│  calc_short_put_metrics(S, K, C, σ, T, r) → StrategyMetrics │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  策略实现层 (strategy/)                                       │
│  ShortPutStrategy, CoveredCallStrategy, ShortStrangleStrategy│
│  - calc_expected_return() → E[π]                             │
│  - calc_return_variance() → Var[π]                           │
│  - calc_sharpe_ratio() → SR                                  │
│  - calc_kelly_fraction() → f*                                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  B-S 基础计算层 (bs/)                                         │
│  calc_d1, calc_d2, calc_d3, calc_n                           │
│  calc_bs_call_price, calc_bs_put_price                       │
│  calc_put_exercise_prob, calc_call_exercise_prob             │
└─────────────────────────────────────────────────────────────┘
```

**核心公式：**

```python
# 期望收益 (Short Put)
# E[π] = C - N(-d2) × [K - e^(rT) × S × N(-d1) / N(-d2)]

# 期望收益方差
# Var[π] = E[π²] - (E[π])²

# 夏普比率 (期权)
# SR = (E[π] - Rf) / Std[π]
# 其中 Rf = margin_ratio × K × (e^(rT) - 1)  # 无风险收益金额，非利率

# 年化夏普比率
# SR_annual = SR / √T

# Kelly公式 (期权)
# f* = E[π] / Var[π]
```

**策略类设计：**

```python
@dataclass
class OptionLeg:
    option_type: OptionType  # CALL / PUT
    side: PositionSide       # LONG / SHORT
    strike: float
    premium: float
    volatility: float | None = None  # 可指定单腿IV

@dataclass
class StrategyMetrics:
    expected_return: float      # E[π]
    return_std: float           # Std[π]
    return_variance: float      # Var[π]
    max_profit: float
    max_loss: float
    breakeven: float | list[float]
    win_probability: float
    sharpe_ratio: float | None
    kelly_fraction: float | None

class OptionStrategy(ABC):
    @abstractmethod
    def calc_expected_return(self) -> float: ...
    @abstractmethod
    def calc_return_variance(self) -> float: ...
    def calc_sharpe_ratio(self, margin_ratio: float = 1.0) -> float | None: ...
    def calc_kelly_fraction(self) -> float: ...
    def calc_metrics(self) -> StrategyMetrics: ...
```

## Risks / Trade-offs

**Risk 1: 计算精度**
- 浮点数精度问题
- Mitigation: 使用 decimal 或在关键计算中控制精度

**Risk 2: 边界条件**
- 除零错误、空数据处理
- Mitigation: 每个算子都要处理边界条件，返回 None 或抛出明确异常

**Risk 3: 性能**
- 批量计算时的效率问题
- Mitigation: 使用 numpy 向量化计算，避免 Python 循环

## Migration Plan

N/A - 新模块，无需迁移

## Open Questions

1. ~~是否需要算子结果缓存？~~ → 本阶段不实现，后续按需添加
2. ~~算子是否需要支持异步？~~ → 本阶段使用同步实现，算子为纯计算
