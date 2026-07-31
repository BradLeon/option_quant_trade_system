# 路线 1：AI 驱动的因子选股系统

> 目标：从 "被动 beta 放大"（SPY LEAPS）升级为 "主动 smart beta 放大"（精选标的 LEAPS）。
> 预期：标的年化从 10% → 14-18%，叠加 LEAPS 杠杆后策略年化 35-45%。

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Factor Stock Selection Pipeline                   │
│                                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────────────┐  │
│  │ L1: 量化 │──▶│ L2: LLM  │──▶│ L3: 多因 │──▶│ L4: Portfolio  │  │
│  │ 因子筛选 │   │ 财报分析 │   │ 子评分   │   │ 接入 (路线3)   │  │
│  └──────────┘   └──────────┘   └──────────┘   └────────────────┘  │
│       │              │              │                               │
│  质量/动量/价值   10-K/10-Q      ML 组合          → LEAPS 回测     │
│  低波/盈利增长    电话会议纪要    信号权重          → SmartRisk      │
│  因子收益率       新闻情绪        综合排名          → 仓位分配       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. L1: 量化因子筛选（周 1-2）

### 2.1 核心因子定义

| 因子 | 计算方式 | 学术依据 | 预期 IC |
|------|---------|---------|---------|
| **Quality** | ROE > 15%, Debt/Equity < 1.0, FCF yield > 5% | Novy-Marx (2013) | 0.03-0.05 |
| **Momentum** | 12-1 月累计收益（跳过最近 1 月） | Jegadeesh & Titman (1993) | 0.04-0.07 |
| **Value** | Earnings Yield (EBIT/EV), 非 P/E | Greenblatt (2006) | 0.02-0.04 |
| **Low Volatility** | 过去 252 日日收益率标准差 | Ang et al. (2006) | 0.02-0.04 |
| **Earnings Growth** | EPS 连续 3 季同比增长 | 实证因子 | 0.02-0.03 |
| **Profitability** | Gross Profit / Total Assets | Novy-Marx (2013) | 0.03-0.05 |

> IC = Information Coefficient，即因子与未来收益的秩相关。IC > 0.03 即有经济意义。

### 2.2 因子计算数据源

| 数据 | 来源 | 频率 | 成本 |
|------|------|------|------|
| 财务数据 (ROE, Debt, FCF) | Yahoo Finance (`yfinance`) / SEC EDGAR | 季度 | 免费 |
| 价格数据 (动量, 波动率) | Yahoo Finance / 已有 DuckDB | 日频 | 免费 |
| 估值数据 (EV, EBIT) | Yahoo Finance `info` API | 季度 | 免费 |
| EPS 预期 / 实际 | Earnings Whispers / Alpha Vantage | 季度 | 免费/低成本 |

### 2.3 因子组合方式

**阶段 1：等权 Z-Score 排名**
```python
# 每月月底
for factor in [quality, momentum, value, low_vol, profitability]:
    z_score[factor] = (rank - mean) / std   # 截面标准化

composite_score = mean(z_scores)  # 等权组合
selected = top_N(composite_score, N=10)  # 选前10
```

**阶段 2：IC 加权（有足够回测数据后）**
```python
# 用过去 12 个月的滚动 IC 作为因子权重
factor_weight[f] = rolling_IC(f, window=12)
composite_score = weighted_mean(z_scores, factor_weights)
```

### 2.4 选股宇宙

```
初始宇宙: S&P 500 成分股 (流动性保证)
过滤条件:
  - 日均成交额 > $50M（LEAPS 流动性需求）
  - 有 LEAPS 期权链（DTE > 180 天）
  - 非金融/地产（杠杆行业的财务指标不可比）
最终宇宙: ~350 只
```

### 2.5 执行计划

| 步骤 | 任务 | 输出 |
|------|------|------|
| 1 | 构建因子计算模块 `src/factor/` | 各因子的月度截面计算 |
| 2 | 历史回测 2010-2025 各因子收益 | 因子 IC 序列、分层回测 |
| 3 | 等权组合 → 选股 → 对比 SPY | 选股组合 vs SPY 的超额收益 |
| 4 | 接入 LEAPS 回测框架 | 多标的 LEAPS SmartRisk 回测 |

---

## 3. L2: LLM 财报分析（周 3-6）

### 3.1 为什么 LLM 在财报分析中有 edge

学术验证：
- **Kim & Kim (2024)** "Financial Statement Analysis with Large Language Models"：GPT-4 在预测盈利方向上准确率 60.4%，超过人类分析师共识的 52.7%
- **Lopez-Lira & Tang (2023)** "Can ChatGPT Forecast Stock Price Movements?"：LLM 新闻情绪对次日收益有显著预测力
- **Li et al. (2023)** "Large Language Models and Financial Text"：LLM 在 10-K 文本变化检测上 F1 = 0.83

### 3.2 分析框架

```
┌────────────────────────────────────────────────────┐
│              LLM 财报分析 Pipeline                  │
│                                                    │
│  输入层                                             │
│  ├─ SEC EDGAR API → 10-K / 10-Q 全文               │
│  ├─ Earnings Call Transcript (Seeking Alpha/FMP)    │
│  └─ 公司新闻 (RSS / NewsAPI)                        │
│                                                    │
│  分析层 (Claude API / GPT-4)                        │
│  ├─ 结构化信息提取                                   │
│  │   ├─ revenue_growth_rate                         │
│  │   ├─ margin_trend (expanding/stable/compressing) │
│  │   ├─ guidance_vs_consensus                       │
│  │   ├─ capex_intensity_change                      │
│  │   └─ debt_maturity_risk                          │
│  │                                                  │
│  ├─ 文本变化检测 (对比前一季)                         │
│  │   ├─ risk_factors_added / removed                │
│  │   ├─ management_tone_shift                       │
│  │   └─ accounting_policy_changes                   │
│  │                                                  │
│  └─ 综合评分                                         │
│      ├─ fundamental_score: 1-10                     │
│      ├─ momentum_score: 1-10                        │
│      └─ risk_score: 1-10                            │
│                                                    │
│  输出层                                             │
│  └─ 每标的每季度一个 JSON 评分卡                      │
└────────────────────────────────────────────────────┘
```

### 3.3 Prompt 工程关键原则

1. **结构化输出**：要求 JSON 格式返回，便于程序化处理
2. **对比分析**：同时提供当季和上季文档，要求 LLM 识别差异
3. **量化打分**：每个维度 1-10 分 + 简短理由（避免模糊的文本描述）
4. **Chain of Thought**：先分析各维度，再给出综合评分
5. **基准锚定**：提供行业中位数作为参考（避免绝对评分漂移）

### 3.4 数据获取

| 数据 | API / 来源 | 成本 |
|------|-----------|------|
| 10-K / 10-Q 全文 | SEC EDGAR XBRL API (免费) | $0 |
| Earnings Call Transcript | Financial Modeling Prep API | $29/月 |
| 分析师预期 | Alpha Vantage / FMP | $29-49/月 |
| 公司新闻 | NewsAPI / Google News RSS | $0-29/月 |

### 3.5 LLM 成本估算

```
每篇 10-K: ~80,000 tokens (摘取关键章节后 ~20,000)
每篇 10-Q: ~30,000 tokens (摘取后 ~10,000)
Earnings Call: ~8,000 tokens

每标的每季度: ~40,000 input tokens + ~2,000 output tokens
350 标的 × 4 季 = 1,400 次调用/年

Claude Sonnet: $3/M input + $15/M output
年成本 ≈ 1400 × (40K × $3/M + 2K × $15/M) ≈ $210

→ 成本极低，完全可行
```

### 3.6 执行计划

| 步骤 | 任务 | 输出 |
|------|------|------|
| 1 | SEC EDGAR 数据拉取 pipeline | 10-K/10-Q 文本清洗 + 关键章节提取 |
| 2 | LLM 分析 prompt 模板 + 结构化输出 | 每标的季度评分卡 JSON |
| 3 | 历史回测：LLM 评分 → 次季收益 | 评分 IC、分层收益 |
| 4 | 与 L1 因子融合 | 综合评分 = 量化因子 + LLM 评分 |

---

## 4. L3: 多因子模型（周 5-8）

### 4.1 模型选择

| 方法 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **线性回归** | 可解释、稳定 | 忽略非线性 | 基线 |
| **XGBoost** | 捕捉非线性、特征交互 | 过拟合风险 | **推荐** |
| **LightGBM** | 更快、对类别特征友好 | 同上 | 推荐 |
| **神经网络** | 高容量 | 数据量不足、黑盒 | 不推荐 |

### 4.2 特征工程

```python
features = {
    # L1 量化因子
    "quality_zscore": float,
    "momentum_12_1": float,
    "earnings_yield": float,
    "volatility_252d": float,
    "profitability": float,

    # L2 LLM 评分
    "llm_fundamental_score": float,    # 1-10
    "llm_momentum_score": float,       # 1-10
    "llm_risk_score": float,           # 1-10
    "llm_tone_change": float,          # -1 to 1

    # 交互特征
    "momentum_x_quality": float,       # 动量 × 质量 交叉
    "sector_relative_value": float,    # 行业内相对估值

    # 宏观 context
    "regime": int,                     # 0=Normal, 1=Bull, 2=Bear, 3=Crisis
    "vix_level": float,
}

target = "forward_1m_return"  # 未来 1 个月收益（截面排名）
```

### 4.3 训练与验证

```
数据: 2010-2025, ~350 标的 × 180 月 = ~63,000 样本
训练: Expanding window walk-forward
  - 初始训练: 2010-2015
  - 预测: 2016 每月
  - 扩展训练: 2010-2016
  - 预测: 2017 每月
  - ...

验证指标:
  - IC (Information Coefficient): 目标 > 0.05
  - Long-Short 分层收益: Top 10% vs Bottom 10% 年化差 > 8%
  - Turnover: 月度换手 < 30% (避免过高交易成本)
```

### 4.4 最终选股输出

```
每月月底:
1. 计算所有标的的 composite_score
2. 排名 Top 10-15 只 → 候选池
3. 过滤: 必须有 LEAPS 期权链 + 足够流动性
4. 输出: [(symbol, score, sector, suggested_weight)]
5. 传递给 路线3 Portfolio 模块做最终配仓
```

---

## 5. 与现有 LEAPS 回测框架的集成

### 5.1 接口设计

```python
# src/factor/stock_selector.py
class StockSelector:
    """月度选股信号生成器"""

    def select(self, as_of_date: date, universe: list[str]) -> list[StockSignal]:
        """
        返回排名后的标的列表，每个标的包含:
        - symbol: str
        - composite_score: float (0-100)
        - factor_scores: dict[str, float]
        - sector: str
        """
        ...

# 在 BacktestExecutor 中集成
class BacktestExecutor:
    def _run_single_day(self, current_date):
        # 每月第一个交易日：更新选股
        if self._is_month_start(current_date):
            self.selected_stocks = self.stock_selector.select(
                current_date, self.universe
            )

        # 现有逻辑：对 selected_stocks 运行 LEAPS 策略
        for stock in self.selected_stocks:
            signals = self.strategy.generate_signals(
                market=self._get_market_snapshot(stock.symbol),
                portfolio=self._get_portfolio_state(),
                data_provider=self.data_provider,
            )
```

### 5.2 回测验证方案

| 测试 | 方法 | 预期 |
|------|------|------|
| 因子单独回测 | 各因子 Top/Bottom 分层收益 | Top-Bottom spread > 5%/年 |
| 因子 + LEAPS | 选股后跑 SmartRisk | 年化 > 35%, Sharpe > 2.0 |
| Out-of-sample | 2023-2025 不参与训练 | 收益衰减 < 30% |
| 交易成本敏感性 | 不同换手率下的净收益 | 月换手 < 25% 时仍盈利 |

---

## 6. 权威资料与参考文献

### 6.1 因子投资（必读）

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"Your Complete Guide to Factor-Based Investing"** | Berkin & Swedroe (2016) | 因子投资完整框架，5 大因子的学术证据与实践 | ★★☆ |
| **"Quantitative Equity Portfolio Management"** | Chincarini & Kim (2006) | 量化选股的教科书级参考，因子构建、回测方法 | ★★★ |
| **"Expected Returns"** | Antti Ilmanen (2011) | 各资产类别的预期收益来源，因子溢价的经济学解释 | ★★★ |
| **"The Cross-Section of Expected Stock Returns"** | Fama & French (1992) | 三因子模型原始论文 | ★★★ |
| **"Is Momentum Really Momentum?"** | Novy-Marx (2012) | 动量因子的真正来源是中间收益而非近期收益 | ★★★ |
| **"The Other Side of Value"** | Novy-Marx (2013) | Profitability 因子 (Gross Profit/Assets) 的发现 | ★★★ |
| **"Dissecting Anomalies with a Five-Factor Model"** | Fama & French (2015) | 五因子模型（市场、规模、价值、盈利、投资） | ★★★ |

### 6.2 LLM + 金融（必读）

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"Financial Statement Analysis with Large Language Models"** | Kim & Kim (2024) | GPT-4 财报分析准确率 60.4%，超过分析师共识 | ★★☆ |
| **"Can ChatGPT Forecast Stock Price Movements?"** | Lopez-Lira & Tang (2023) | LLM 新闻情绪 → 次日收益预测显著 | ★★☆ |
| **"BloombergGPT: A Large Language Model for Finance"** | Wu et al. (2023) | 金融专用 LLM 的训练与评估 | ★★★ |
| **"Large Language Models in Finance: A Survey"** | Li et al. (2023) | LLM 金融应用综述：情绪分析、信息提取、预测 | ★★☆ |
| **"FinGPT: Open-Source Financial LLMs"** | Yang et al. (2023) | 开源金融 LLM 框架，含情绪分析、报告生成 | ★★☆ |
| **Anthropic Claude API Docs** | Anthropic | 实际调用 Claude 做财报分析的 API 参考 | ★☆☆ |

### 6.3 多因子模型 & ML 选股

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"Advances in Financial Machine Learning"** | Marcos Lopez de Prado (2018) | ML 在金融中的正确用法：去噪、特征重要性、回测陷阱 | ★★★ |
| **"Machine Learning for Factor Investing"** | Coqueret & Guida (2020) | ML 选股的完整技术栈，从因子到组合 | ★★★ |
| **"Empirical Asset Pricing via Machine Learning"** | Gu, Kelly & Xiu (2020) | 用 ML 预测截面收益，树模型表现最佳 | ★★★ |
| **"Deep Learning for Stock Selection"** | Feng, He & Polson (2018) | 深度因子模型，但树模型通常更稳健 | ★★★ |
| **"The Characteristics that Provide Independent Information about Average U.S. Monthly Stock Returns"** | Green, Hand & Zhang (2017) | 系统评估 94 个因子，筛选出真正独立的因子 | ★★★ |

### 6.4 实战博客 & 开源项目

| 资源 | 类型 | 内容 |
|------|------|------|
| **Quantopian Lectures** (GitHub: quantopian/research_public) | 教程 | 因子分析、Alphalens、风险模型完整教程 |
| **Alphalens** (quantopian/alphalens) | 开源工具 | 因子 IC 计算、分层回测、换手率分析 |
| **OpenBB** (OpenBB-finance/OpenBBTerminal) | 开源平台 | 免费金融数据 + 分析工具 |
| **FinRL** (AI4Finance-Foundation/FinRL) | 开源框架 | 强化学习金融交易框架 |
| **Alpha Vantage API** | 数据 | 免费基本面数据 API |
| **SEC EDGAR Full-Text Search** | 数据 | 10-K/10-Q 全文免费获取 |
| **Ernest Chan's Blog** (epchan.blogspot.com) | 博客 | 量化策略实战，因子衰减、交易成本分析 |
| **Quantitative Trading** — Ernest Chan (2008) | 书 | 零售量化交易者的实战指南 |
