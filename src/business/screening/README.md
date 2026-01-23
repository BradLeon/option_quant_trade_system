# 期权开仓信号捕捉系统

本文档介绍期权开仓筛选系统的三层过滤器架构、指标优先级体系、CLI 使用方法和配置管理。

## 目录

- [概述](#概述)
- [快速开始](#快速开始)
- [指标优先级体系](#指标优先级体系)
- [三层过滤器详解](#三层过滤器详解)
- [配置管理](#配置管理)
- [CLI 命令参考](#cli-命令参考)
- [数据流水线](#数据流水线)
- [股票池管理](#股票池管理)
- [常见问题](#常见问题)

---

## 概述

筛选系统采用 **三层漏斗架构**，逐层过滤不合格的开仓机会：

| 层级 | 名称 | 核心问题 | 过滤对象 |
|------|------|----------|----------|
| **Layer 1** | 市场过滤 | 现在是卖期权的好时机吗？ | 市场环境 |
| **Layer 2** | 标的过滤 | 这个标的适合卖期权吗？ | 股票池中的每个标的 |
| **Layer 3** | 合约过滤 | 选择哪个 Strike 和到期日？ | 每个标的的期权合约 |

### 支持的策略

| 策略 | 描述 | 适用场景 |
|------|------|----------|
| **Short Put (CSP)** | 卖出看跌期权，收取权利金 | 看涨或震荡市场 |
| **Covered Call (CC)** | 持有正股 + 卖出看涨期权 | 温和看涨或中性市场 |

### 支持的市场

| 市场 | 标识 | 波动率指标 | 数据来源 |
|------|------|-----------|----------|
| **美股** | us | VIX / VIX3M | IBKR → Futu → Yahoo |
| **港股** | hk | VHSI / 2800.HK IV | IBKR → Futu |

---

## 快速开始

### 基本使用

```bash
# 默认筛选：所有市场 + 所有策略 + 所有股票池
python src/business/cli/main.py screen

# 详细模式（显示更多日志）
python src/business/cli/main.py screen -v

# 调试模式（跳过市场检查）
python src/business/cli/main.py screen --skip-market-check
```

### 指定筛选范围

```bash
# 只筛选美股
python src/business/cli/main.py screen --market us

# 只筛选 Short Put 策略
python src/business/cli/main.py screen --strategy short_put

# 只筛选港股 Covered Call
python src/business/cli/main.py screen -m hk -s covered_call

# 指定股票池
python src/business/cli/main.py screen --pool us_large_cap

# 指定单个标的
python src/business/cli/main.py screen -S AAPL -S MSFT
```

### 输出格式

```bash
# 文本输出（默认）
python src/business/cli/main.py screen

# JSON 输出
python src/business/cli/main.py screen -o json

# 推送到企业微信
python src/business/cli/main.py screen --push
```

---

## 指标优先级体系

系统采用 **P0-P3 优先级分类**，确保筛选结果质量：

| 优先级 | 含义 | 处理方式 | 示例 |
|--------|------|----------|------|
| **P0** | 致命条件 | 不满足 = 立即排除，无例外 | 期望收益为负 |
| **P1** | 核心条件 | 不满足 = 强烈建议不开仓 | VIX 极端、流动性不足、IV Rank 偏低 |
| **P2** | 重要条件 | 不满足 = 警告，需其他条件补偿 | RSI 超买超卖、Annual ROC 不足 |
| **P3** | 参考条件 | 不满足 = 可接受，记录风险 | Sharpe Ratio、Premium Rate、Volume 较低 |

### 指标汇总表

#### Layer 1: 市场环境指标

| 指标 | 优先级 | 条件 | 说明 |
|------|--------|------|------|
| 宏观事件 | P1 | FOMC/CPI/NFP 前3天 | 事件前暂停新开仓 |
| VIX 水平 | P1 | 15~28 (Short Put) / 12~25 (CC) | <15 保费太低，>30 风险大 |
| VIX 期限结构 | P1 | VIX/VIX3M < 1.0 | >1.0 反向结构=近期黑天鹅预期 |
| VIX Percentile | P2 | 20%~80% | 50%-80% 最佳 |
| SPY/盈富 趋势 | P2 | 符合策略方向 | Short Put 要求看涨/震荡 |
| Put/Call Ratio | P2 | 0.8~1.2 | 极端值预示市场转折 |

#### Layer 2: 标的指标

| 指标 | 优先级 | 条件 | 说明 |
|------|--------|------|------|
| 财报日期 | P1 | > 7天或合约在财报前到期 | 避免财报博弈 |
| **IV Rank** | **P1** | > 30% | **阻塞条件**，卖方必须卖"贵"的东西 |
| IV/HV Ratio | P1 | 0.8~2.0 | 隐含波动率相对历史波动率 |
| RSI | P2 | 30~70 | 避免超买超卖区域 |
| ADX | P2 | < 45 | 避免强趋势行情 |
| 除息日 (CC) | P2 | > 7天 | 仅 Covered Call 检查 |

#### Layer 3: 合约指标

| 指标 | 优先级 | 条件 | 说明 |
|------|--------|------|------|
| Annual Expected ROC | P0 | > 10% | 年化期望收益率必须为正，致命条件 |
| TGR | P1 | > 0.5 | Theta/Gamma 比率（标准化） |
| DTE | P1 | 7~45 天 | 港股到期日稀疏，范围宽松 |
| \|Delta\| | P1 | 0.05~0.35 | 最优 0.20~0.30 |
| OTM% | P2 | 7%~30% | 虚值百分比 |
| Bid-Ask Spread | P1 | < 10% | 流动性指标 |
| Open Interest | P1 | > 100 | 持仓量 |
| Annual ROC | P2 | > 15% | 年化收益率 |
| **Sharpe Ratio** | **P3** | > 0.5 | 参考条件，卖方收益非正态分布 |
| **Premium Rate** | **P3** | > 1% | 参考条件，已被 Annual ROC 包含 |
| Win Probability | P3 | > 65% | 理论胜率 |
| Volume | P3 | > 10 | 当日成交量 |
| **Theta/Margin** | **排序** | - | **资金效率排序指标**，用于对通过筛选的合约排序 |

---

## 三层过滤器详解

### Layer 1: 市场过滤器 (MarketFilter)

**文件**: `src/business/screening/filters/market_filter.py`

**职责**: 评估整体市场环境是否适合期权卖方策略。

**美股检查项**:
- VIX 水平和期限结构
- VIX Percentile 分布
- SPY 趋势方向
- Put/Call Ratio
- 宏观事件日历 (FOMC/CPI/NFP)

**港股检查项**:
- VHSI 或 2800.HK ATM IV
- IV Percentile
- 盈富基金趋势
- 美股宏观事件（FOMC 对全球有影响）

### Layer 2: 标的过滤器 (UnderlyingFilter)

**文件**: `src/business/screening/filters/underlying_filter.py`

**职责**: 评估单个标的是否适合开仓。

**检查项**:
1. **波动率**: IV Rank、IV/HV Ratio
2. **技术面**: RSI、ADX、均线排列
3. **事件日历**: 财报日期、除息日期
4. **基本面** (可选): PE Percentile、分析师评级

### Layer 3: 合约过滤器 (ContractFilter)

**文件**: `src/business/screening/filters/contract_filter.py`

**职责**: 筛选最优的期权合约。

**检查项**:
1. **DTE**: 14~60 天（最优 25~45）
2. **Delta**: |Delta| 0.10~0.40（最优 0.20~0.30）
3. **流动性**: Bid-Ask Spread、Open Interest、Volume
4. **收益指标**: Expected ROC、Premium Rate、Annual ROC
5. **风险指标**: TGR、Sharpe Ratio、Kelly Fraction

---

## 配置管理

### 配置文件层次

```
config/screening/
├── stock_pools.yaml       # 股票池定义
├── short_put.yaml         # Short Put 策略配置
└── covered_call.yaml      # Covered Call 策略配置

src/business/config/
└── screening_config.py    # 默认值和数据类定义
```

### 配置优先级

**YAML 文件 > screening_config.py 默认值**

- `screening_config.py`: 定义所有配置项的默认值，适用于两种策略
- `short_put.yaml` / `covered_call.yaml`: 策略特定覆盖，仅包含与默认值不同的配置

### 何时修改哪个文件？

| 场景 | 修改文件 |
|------|----------|
| 调整两种策略共用的默认值 | `screening_config.py` |
| 调整 Short Put 特有参数 | `short_put.yaml` |
| 调整 Covered Call 特有参数 | `covered_call.yaml` |
| 添加/修改股票池 | `stock_pools.yaml` |
| 添加新配置项 | `screening_config.py` + 对应 YAML |

### 策略配置示例

**Short Put** (`config/screening/short_put.yaml`):

```yaml
market_filter:
  us_market:
    vix_range: [15, 28]           # VIX 适宜区间
    trend_required: "bullish_or_neutral"
  hk_market:
    iv_range: [18, 32]
    trend_required: "bullish_or_neutral"

underlying_filter:
  min_iv_rank: 50                 # 较高 IV Rank
  technical:
    min_rsi: 30                   # 避免接飞刀
    rsi_stabilizing_range: [30, 45]  # 企稳区间

# contract_filter 使用 screening_config.py 默认值
```

**Covered Call** (`config/screening/covered_call.yaml`):

```yaml
market_filter:
  us_market:
    vix_range: [12, 25]           # 较低 VIX 区间
    trend_required: "neutral_or_bearish"
  hk_market:
    iv_range: [15, 28]
    trend_required: "neutral_or_bearish"

underlying_filter:
  min_iv_rank: 40                 # 较低 IV Rank 要求
  technical:
    rsi_exhaustion_range: [55, 70]   # 动能衰竭区间

# contract_filter 使用 screening_config.py 默认值
```

### 默认合约配置 (screening_config.py)

```python
@dataclass
class ContractFilterConfig:
    # DTE 范围（港股期权到期日稀疏，使用宽范围）
    dte_range: tuple[int, int] = (7, 45)
    optimal_dte_range: tuple[int, int] = (25, 45)

    # |Delta| 范围（绝对值，覆盖两种策略）
    delta_range: tuple[float, float] = (0.05, 0.35)
    optimal_delta_range: tuple[float, float] = (0.20, 0.30)

    # OTM% 范围
    otm_range: tuple[float, float] = (0.07, 0.30)

@dataclass
class LiquidityConfig:
    max_bid_ask_spread: float = 0.10  # 10%
    min_open_interest: int = 100
    min_volume: int = 10

@dataclass
class MetricsConfig:
    min_sharpe_ratio: float = 0.5     # P3: 参考条件
    min_tgr: float = 0.5              # P1: 核心条件
    min_expected_roc: float = 0.10    # P0: 致命条件 (10%)
    min_annual_roc: float = 0.15      # P2: 重要条件 (15%)
    min_win_probability: float = 0.65 # P3: 参考条件 (65%)
    min_premium_rate: float = 0.01    # P3: 参考条件 (1%)
```

---

## CLI 命令参考

### 完整参数列表

```bash
python src/business/cli/main.py screen --help
```

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `--market` | `-m` | all | 市场：us, hk, all |
| `--strategy` | `-s` | all | 策略：short_put, covered_call, all |
| `--pool` | `-p` | (默认池) | 股票池名称 |
| `--symbols` | `-S` | (无) | 指定标的（可多次使用） |
| `--output` | `-o` | text | 输出格式：text, json |
| `--push` | | False | 推送结果到企业微信 |
| `--skip-market-check` | | False | 跳过市场环境检查（调试用） |
| `--verbose` | `-v` | False | 详细模式 |
| `--list-pools` | | False | 列出所有可用股票池 |

### 使用示例

```bash
# 场景 1: 日常扫描（默认配置）
python src/business/cli/main.py screen

# 场景 2: 只看美股 Short Put 机会
python src/business/cli/main.py screen -m us -s short_put

# 场景 3: 调试单个标的
python src/business/cli/main.py screen -S AAPL --skip-market-check -v

# 场景 4: JSON 输出用于程序处理
python src/business/cli/main.py screen -o json > opportunities.json

# 场景 5: 扫描后推送通知
python src/business/cli/main.py screen --push
```

---

## 数据流水线

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Data Layer                                 │
│                                                                     │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐       │
│   │  Yahoo   │  │   IBKR   │  │   Futu   │  │ FRED + FOMC  │       │
│   │ Finance  │  │   TWS    │  │  OpenD   │  │ (宏观事件)    │       │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘       │
│        │             │             │               │                │
│        └─────────────┴─────────────┴───────────────┘                │
│                              │                                      │
│                              ▼                                      │
│                    ┌─────────────────────┐                          │
│                    │ UnifiedDataProvider │                          │
│                    │  (智能路由 + 缓存)   │                          │
│                    └─────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Business Layer                               │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │                    ScreeningPipeline                         │  │
│   │                                                              │  │
│   │   Stock Pool  ──▶  MarketFilter  ──▶  UnderlyingFilter      │  │
│   │   (配置驱动)        (Layer 1)          (Layer 2)             │  │
│   │                                              │               │  │
│   │                                              ▼               │  │
│   │                                      ContractFilter         │  │
│   │                                         (Layer 3)            │  │
│   │                                              │               │  │
│   │                                              ▼               │  │
│   │                                     ScreeningResult          │  │
│   │                                   (ContractOpportunity[])    │  │
│   └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 数据路由策略

| 数据类型 | US 市场 | HK 市场 |
|----------|---------|---------|
| 股票行情 | IBKR → Futu → Yahoo | IBKR → Futu |
| 期权链 | IBKR → Futu → Yahoo | IBKR → Futu |
| Greeks | IBKR → Futu | IBKR → Futu |
| 波动率 | IBKR → Futu → Yahoo | IBKR → Futu |
| 宏观数据 | Yahoo (VIX) | Yahoo (VHSI) |
| 经济日历 | FRED + 静态FOMC | FRED + 静态FOMC |

---

## 股票池管理

### 配置文件

**文件**: `config/screening/stock_pools.yaml`

```yaml
us_pools:
  us_default:
    description: "美股默认池 - 高流动性期权标的"
    symbols: [SPY, QQQ, AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA]

  us_large_cap:
    description: "美股大盘股池"
    symbols: [...]

hk_pools:
  hk_default:
    description: "港股默认池"
    symbols: [2800.HK, 3033.HK, 0700.HK, 9988.HK, 9618.HK]

defaults:
  us: us_default
  hk: hk_default
```

### 查看可用股票池

```bash
python src/business/cli/main.py screen --list-pools
```

### Python API

```python
from src.business.screening import StockPoolManager, MarketType

manager = StockPoolManager()

# 加载指定股票池
symbols = manager.load_pool("us_large_cap")

# 列出所有可用池
pools = manager.list_pools()

# 获取默认池
symbols = manager.get_default_pool(MarketType.US)
```

---

## 常见问题

### Q: 为什么港股期权没有找到合约？

A: 港股期权只有月度到期日（每月最后一个交易日），不像美股有周度期权。确保 DTE 范围足够宽（默认 14~60 天）以覆盖下一个月度到期日。

### Q: 如何跳过市场环境检查进行调试？

A: 使用 `--skip-market-check` 参数：
```bash
python src/business/cli/main.py screen --skip-market-check -v
```

### Q: 为什么某些合约被过滤掉了？

A: 使用详细模式查看过滤原因：
```bash
python src/business/cli/main.py screen -v
```
日志会显示每个合约的评估结果和具体失败原因。

### Q: 如何添加自定义股票池？

A: 编辑 `config/screening/stock_pools.yaml`，添加新的池定义：
```yaml
us_pools:
  my_custom_pool:
    description: "我的自定义股票池"
    symbols: [AAPL, MSFT, GOOGL]
```

### Q: 如何调整筛选阈值？

A:
- 调整两种策略共用的阈值：修改 `src/business/config/screening_config.py`
- 调整特定策略的阈值：修改对应的 YAML 文件

---

## 更新日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 2.1 | 2026-01 | 更新文档：同步指标阈值，完善配置说明 |
| 2.0 | 2025-01 | 统一合约配置，简化 CLI 默认行为 |
| 1.2 | 2025-01 | 添加事件日历集成，港股 DTE 范围优化 |
| 1.1 | 2025-01 | 添加股票池管理 (StockPoolManager) |
| 1.0 | 2025-01 | 初始版本：三层过滤器框架 |
