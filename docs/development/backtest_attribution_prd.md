# 回测系统归因与迭代 PRD

> **版本**: v1.1
> **创建日期**: 2026-02-10
> **最后更新**: 2026-02-10
> **状态**: P0/P1/P3 已实现，P2 待实现

---

## 一、背景与目标

### 1.1 问题陈述

当前回测系统能够输出策略的整体绩效指标（收益率、夏普比率、最大回撤等），但存在以下问题：

1. **缺乏归因能力**：看到最大回撤日，但无法理解亏损的根本原因（Delta 风险？Vega 风险？时间衰减不足？）
2. **缺乏诊断能力**：无法判断策略的入场/出场规则是否合理，风控是否过度或不足
3. **缺乏环境感知**：不知道策略在不同市场环境（高波动/低波动、趋势/震荡）下的表现差异
4. **数据展示不完整**：缺少每日持仓快照、组合 Greeks 暴露、市场环境参考等基础信息

### 1.2 目标

构建**专业期权 Desk 级别**的归因与诊断系统，支持：

- **理解 PnL 来源**：每日/每笔交易的 Greeks 分解归因
- **诊断策略问题**：入场时机、出场规则、风控有效性验证
- **优化策略参数**：基于归因数据驱动的参数调优
- **适应市场环境**：识别策略适用的市场 Regime

### 1.3 成功指标

| 指标 | 目标 |
|------|------|
| 归因覆盖率 | Greeks 归因可解释 > 90% 的 PnL 变动 |
| 诊断覆盖率 | 覆盖 100% 的平仓规则有效性分析 |
| 用户反馈 | 能在 5 分钟内定位最大回撤日的亏损原因 |

---

## 二、功能需求

### 2.1 补齐展示基础内容

#### 2.1.1 可视化图表增强 ✅ 已实现

| 图表 | 实现 | 说明 |
|------|------|------|
| **Symbol K 线图** | `dashboard.py: create_symbol_kline()` | Candlestick + Volume 子图 + 交易标记叠加 (开仓=绿色上三角, 平仓=红色下三角) |
| **VIX 日 K 线图** | `dashboard.py: create_vix_kline()` | Candlestick，MacroData OHLC None 时 fallback 到 value |
| **SPY 日 K 线图** | `dashboard.py: create_spy_kline()` | Candlestick + Volume，与 Symbol K 线结构一致 |
| **重大事件日历** | `dashboard.py: create_events_calendar()` | y 轴 FOMC/CPI/NFP/GDP/PPI 五行，菱形标记按 impact 着色 (HIGH=红, MEDIUM=橙, LOW=灰) |

**数据管道**: `pipeline.py` 中新增 `MarketContext` dataclass 和 `_fetch_market_context()` 方法，回测完成后从 DuckDBProvider 获取 K 线和 VIX 数据，从 `EconomicCalendarProvider` 获取事件日历。FOMC 始终从静态 YAML (`config/screening/fomc_calendar.yaml`) 补充。

**图表交互**: Plotly 原生支持 Zoom/Pan/Hover。Symbol K 线图叠加了交易标记，定位在当日收盘价。

#### 2.1.2 Daily Position Snapshot（每日持仓快照表）

记录每个交易日结束时，所有持仓的完整状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | date | 日期 |
| `underlying` | str | 标的代码 (GOOG, SPY) |
| `strike` | float | 行权价 |
| `expiry` | date | 到期日 |
| `option_type` | str | CALL / PUT |
| `qty` | int | 持仓数量 (负数=卖方) |
| `underlying_price` | float | 标的收盘价 |
| `option_mid_price` | float | 期权中间价 (Bid+Ask)/2 |
| `iv` | float | 隐含波动率 |
| `hv_20` | float | 20 日历史波动率 |
| `iv_hv_ratio` | float | IV/HV 比值 |
| `iv_rank` | float | IV Rank (0-100%) |
| `iv_percentile` | float | IV Percentile (0-100%) |
| `delta` | float | Delta |
| `gamma` | float | Gamma |
| `theta` | float | Theta (日衰减) |
| `vega` | float | Vega |
| `rho` | float | Rho |
| `mark_to_market` | float | 市值 = mid_price × qty × 100 |
| `unrealized_pnl` | float | 未实现盈亏 |
| `daily_pnl` | float | 当日盈亏变动 |
| `moneyness_pct` | float | OTM% = (strike - underlying) / underlying |
| `dte` | int | 剩余到期天数 |

**存储格式**: Parquet (按日期分区)

#### 2.1.3 Portfolio Snapshot（每日组合快照表）

记录每个交易日结束时，整个组合的聚合指标。

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | date | 日期 |
| `nlv` | float | 净清算价值 |
| `cash` | float | 现金余额 |
| `margin_used` | float | 已用保证金 |
| `position_count` | int | 持仓数量 |
| **Greeks 暴露** | | |
| `portfolio_delta` | float | 组合 Delta (原始) |
| `beta_weighted_delta` | float | Beta 加权 Delta (SPY 等效) |
| `portfolio_gamma` | float | 组合 Gamma |
| `portfolio_theta` | float | 组合 Theta (日收益) |
| `portfolio_vega` | float | 组合 Vega |
| **Greeks 占比** | | |
| `beta_weighted_delta_pct` | float | Delta / NLV × 100 |
| `gamma_pct` | float | Gamma 风险占比 |
| `theta_pct` | float | Theta 收益占比 |
| `vega_pct` | float | Vega 风险占比 |
| **加权指标** | | |
| `vega_weighted_iv` | float | Vega 加权平均 IV |
| `vega_weighted_iv_hv` | float | Vega 加权平均 IV/HV |

**Beta Weighted Delta 计算公式**:
```
beta_weighted_delta = Σ(position_delta × underlying_beta_to_SPY × underlying_price / SPY_price)
```

---

### 2.2 Greeks-Based PnL Attribution（Greeks 归因分解）

#### 2.2.1 核心原理

期权 PnL 通过 Taylor 展开分解为各因子贡献：

```
Daily PnL ≈ Delta × ΔS + ½ × Gamma × (ΔS)² + Theta × Δt + Vega × Δσ + Residual
```

| 因子 | 公式 | 业务含义 |
|------|------|----------|
| **Delta PnL** | Δ × ΔS × 100 × qty | 标的价格变动贡献（方向性风险） |
| **Gamma PnL** | ½ × Γ × (ΔS)² × 100 × qty | 凸性贡献（卖方通常为负—Gamma Bleed） |
| **Theta PnL** | Θ × Δt × 100 × qty | 时间衰减收入（卖方策略主要利润来源） |
| **Vega PnL** | ν × Δσ × 100 × qty | IV 变动贡献 |
| **Residual** | Actual - Σ(上述) | 高阶项 + 模型误差 + Bid-Ask |

#### 2.2.2 归因粒度

| 粒度 | 说明 | 用途 |
|------|------|------|
| **Daily** | 每日组合级别归因 | 回答"今天亏损的原因是什么" |
| **Per-Trade** | 单笔交易从开仓到平仓的归因 | 回答"这笔交易亏损的原因是什么" |
| **Per-Position-Daily** | 单个持仓的每日归因 | 定位具体哪个持仓造成了当日亏损 |

#### 2.2.3 输出格式

**Daily Attribution Table**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | date | 日期 |
| `total_pnl` | float | 总 PnL |
| `delta_pnl` | float | Delta 贡献 |
| `gamma_pnl` | float | Gamma 贡献 |
| `theta_pnl` | float | Theta 贡献 |
| `vega_pnl` | float | Vega 贡献 |
| `residual` | float | 残差 |
| `delta_pnl_pct` | float | Delta 占比 |
| `gamma_pnl_pct` | float | Gamma 占比 |
| `theta_pnl_pct` | float | Theta 占比 |
| `vega_pnl_pct` | float | Vega 占比 |
| `underlying_move` | float | 标的变动 (ΔS) |
| `underlying_move_pct` | float | 标的变动% |
| `iv_change` | float | IV 变动 (Δσ) |
| `positions_count` | int | 持仓数量 |

**Trade Attribution Table**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `trade_id` | str | 交易 ID |
| `symbol` | str | 标的 |
| `entry_date` | date | 开仓日期 |
| `exit_date` | date | 平仓日期 |
| `holding_days` | int | 持仓天数 |
| `total_pnl` | float | 总 PnL |
| `delta_pnl` | float | Delta 累计贡献 |
| `gamma_pnl` | float | Gamma 累计贡献 |
| `theta_pnl` | float | Theta 累计贡献 |
| `vega_pnl` | float | Vega 累计贡献 |
| `residual` | float | 残差 |
| `entry_iv` | float | 开仓时 IV |
| `exit_iv` | float | 平仓时 IV |
| `entry_underlying` | float | 开仓时标的价格 |
| `exit_underlying` | float | 平仓时标的价格 |

---

### 2.3 多维度切片归因

#### 2.3.1 按标的归因

**问题**: GOOG 和 SPY 各贡献了多少 PnL？

| 字段 | 说明 |
|------|------|
| `underlying` | 标的代码 |
| `total_pnl` | 该标的总 PnL |
| `pnl_contribution_pct` | 占组合 PnL 百分比 |
| `trade_count` | 交易笔数 |
| `win_rate` | 胜率 |
| `avg_pnl_per_trade` | 平均每笔 PnL |
| `max_win` | 最大盈利 |
| `max_loss` | 最大亏损 |

#### 2.3.2 按期权类型归因

**问题**: Call 卖方 vs Put 卖方各贡献多少？

| 字段 | 说明 |
|------|------|
| `option_type` | CALL / PUT |
| `side` | BUY / SELL |
| `total_pnl` | 该类型总 PnL |
| `pnl_contribution_pct` | 占组合 PnL 百分比 |
| `trade_count` | 交易笔数 |
| `win_rate` | 胜率 |
| `avg_premium` | 平均权利金 |
| `assignment_rate` | 被指派率 |

#### 2.3.3 按开仓时机归因

**问题**: 在高 IV 环境开仓 vs 低 IV 环境开仓，表现差异多大？

**IV 环境分组**:
- **低 IV**: IV Rank < 30%
- **中 IV**: IV Rank 30% - 70%
- **高 IV**: IV Rank > 70%

| 字段 | 说明 |
|------|------|
| `iv_regime` | LOW / MEDIUM / HIGH |
| `trade_count` | 交易笔数 |
| `total_pnl` | 该环境下总 PnL |
| `win_rate` | 胜率 |
| `avg_pnl_per_trade` | 平均每笔 PnL |
| `avg_entry_iv` | 平均开仓 IV |
| `avg_realized_vol` | 平均实现波动率 |
| `vrp_captured` | 捕获的波动率风险溢价 |

**预期发现**: 卖方策略在高 IV 环境开仓应有更高的胜率和期望收益。

#### 2.3.4 按平仓原因归因

**问题**: 哪种平仓规则触发后的平均 PnL 最差？哪种是假警报？

**平仓原因分类** (来自 `monitoring_config.py`):

| 平仓原因 | 说明 |
|----------|------|
| `EXPIRED_WORTHLESS` | 到期作废 (最佳) |
| `EXPIRED_ITM` | 到期实值 (被指派) |
| `PROFIT_TARGET` | 达到止盈目标 |
| `STOP_LOSS_DELTA` | Delta 止损 |
| `STOP_LOSS_PRICE` | 价格止损 |
| `STOP_LOSS_PNL` | PnL 百分比止损 |
| `TIME_EXIT` | 时间止损 (临近到期) |
| `ROLL_FORWARD` | 移仓 |
| `MANUAL` | 手动平仓 |

**归因指标**:

| 字段 | 说明 |
|------|------|
| `exit_reason` | 平仓原因 |
| `trade_count` | 触发次数 |
| `total_pnl` | 该原因下总 PnL |
| `avg_pnl_per_trade` | 平均每笔 PnL |
| `win_rate` | 盈利比例 |
| `avg_holding_days` | 平均持仓天数 |
| `avg_pnl_if_held_to_expiry` | 如果持有到期的平均 PnL (What-if) |
| `false_alarm_rate` | 假警报率 (止损后反转比例) |

---

### 2.4 策略诊断

#### 2.4.1 Entry Quality Analysis（入场质量分析）

**核心问题**: 卖出的 Premium 是否足够补偿承担的风险？

**指标 1: Realized Vol vs Implied Vol**

| 字段 | 说明 |
|------|------|
| `trade_id` | 交易 ID |
| `entry_iv` | 开仓时隐含波动率 |
| `realized_vol` | 持仓期间实现波动率 |
| `iv_rv_spread` | IV - RV (应为正值) |
| `vrp_captured` | 捕获的 VRP = (IV - RV) × Vega |

**预期**:
- 健康的卖方策略应有 **IV > RV** (正的 VRP)
- 如果系统性 **IV < RV**，说明入场时机有问题

**指标 2: Entry Timing Score**

| 字段 | 说明 |
|------|------|
| `entry_iv_rank` | 开仓时 IV Rank |
| `entry_iv_percentile` | 开仓时 IV Percentile |
| `avg_entry_iv_rank` | 平均开仓 IV Rank |
| `high_iv_entry_pct` | 高 IV (>50%) 开仓占比 |

**预期**: 高 IV 开仓占比应 > 60%

#### 2.4.2 Exit Quality Analysis（出场质量分析）

**核心问题**: 风控规则是在保护你还是在"砍掉好仓位"？

**分析 1: What-If Analysis（反事实分析）**

对于每笔被风控强制平仓的交易，模拟"如果持有到期会怎样"：

| 字段 | 说明 |
|------|------|
| `trade_id` | 交易 ID |
| `exit_reason` | 平仓原因 |
| `actual_pnl` | 实际 PnL |
| `pnl_if_held_to_expiry` | 持有到期的 PnL |
| `exit_benefit` | 平仓收益 = actual - if_held |
| `was_good_exit` | 是否正确决策 (exit_benefit > 0) |

**汇总指标**:

| 指标 | 说明 |
|------|------|
| `good_exit_rate` | 正确平仓比例 |
| `avg_exit_benefit` | 平均平仓收益 |
| `total_saved_by_exit` | 风控总共挽救的损失 |
| `total_lost_by_exit` | 风控总共损失的利润 |
| `net_exit_value` | 风控净价值 = saved - lost |

**分析 2: 止损后反转率**

| 字段 | 说明 |
|------|------|
| `exit_reason` | 平仓原因 (仅止损类) |
| `reversal_rate_1d` | 1 天内反转率 |
| `reversal_rate_3d` | 3 天内反转率 |
| `reversal_rate_5d` | 5 天内反转率 |
| `avg_reversal_magnitude` | 平均反转幅度 |

**反转定义**: 止损平仓后，如果持有到期会盈利，则为"反转"

**预期**:
- 反转率 < 30% 表示止损阈值合理
- 反转率 > 50% 表示止损阈值过于敏感

#### 2.4.3 Regime Analysis（市场环境分析）

**核心问题**: 策略在不同市场环境下的表现差异

**Regime 分类维度**:

| 维度 | 分类 | 说明 |
|------|------|------|
| **VIX 水平** | LOW (<15), NORMAL (15-20), ELEVATED (20-25), HIGH (>25) | 市场恐慌程度 |
| **VIX 趋势** | RISING, FALLING, STABLE | 波动率变化方向 |
| **SPY 趋势** | BULLISH (>1%), BEARISH (<-1%), NEUTRAL | 市场方向 |
| **重大事件** | FOMC, EARNINGS, CPI, JOBS, NONE | 事件日 |

**每日 Regime 标签**:

| 字段 | 说明 |
|------|------|
| `date` | 日期 |
| `vix_level` | VIX 水平分类 |
| `vix_trend` | VIX 趋势 |
| `spy_trend` | SPY 趋势 |
| `event_type` | 重大事件类型 |
| `regime_label` | 综合标签 (e.g., "HIGH_VOL_BEARISH_FOMC") |

**按 Regime 归因**:

| 字段 | 说明 |
|------|------|
| `regime_label` | 环境标签 |
| `trading_days` | 交易天数 |
| `total_pnl` | 该环境下总 PnL |
| `avg_daily_pnl` | 平均日 PnL |
| `win_rate` | 盈利天数占比 |
| `max_daily_loss` | 最大单日亏损 |
| `sharpe_ratio` | 该环境下夏普比率 |

**预期发现**:
- 卖方策略在 **LOW VOL + NEUTRAL** 环境表现最好
- 卖方策略在 **HIGH VOL + BEARISH** 环境表现最差
- FOMC 日通常波动大，需要特殊处理

---

## 三、技术设计

### 3.1 模块结构

> **注**: 实际实现与原始设计有所调整。归因模块独立为 `attribution/` 包，采用 Observer 模式 (`AttributionCollector`) 采集数据；K 线图和事件日历直接集成在 `dashboard.py` 中而非独立文件。

```
src/backtest/
├── attribution/                     # 归因模块 (独立包)
│   ├── __init__.py
│   ├── models.py                    # 数据模型 (PositionSnapshot, PortfolioSnapshot, DailyAttribution, etc.)
│   ├── collector.py                 # 数据采集器 (Observer 模式，挂载到 BacktestExecutor)
│   ├── pnl_attribution.py          # Greeks 归因引擎
│   ├── slice_attribution.py        # 多维度切片归因
│   ├── strategy_diagnosis.py       # 策略诊断
│   └── regime_analyzer.py          # 市场环境分析
│
├── engine/
│   ├── backtest_executor.py         # 更新: 支持 attribution_collector 参数
│   └── ...
│
├── visualization/
│   ├── dashboard.py                 # 更新: 集成 K 线、VIX、SPY、事件日历、交易标记
│   └── attribution_charts.py        # 归因可视化 (瀑布图、累计面积图、Greeks 2×2 子图、切片对比)
│
├── pipeline.py                      # 更新: MarketContext + _fetch_market_context()
└── ...
```

### 3.2 数据流

> **实现说明**: 采用 Observer 模式——`AttributionCollector` 作为可选参数注入 `BacktestExecutor`，在回测执行期间采集每日持仓/组合快照。归因计算在回测完成后进行 (Post-hoc)。市场上下文 (K 线、VIX、事件日历) 由 Pipeline 在生成报告前独立获取。

```
BacktestExecutor (attribution_collector=AttributionCollector())
    │
    │  [回测期间: Observer 采集]
    ├── AttributionCollector
    │       ├── position_snapshots (每日持仓快照)
    │       └── portfolio_snapshots (每日组合快照)
    │
    │  [回测完成后: Post-hoc 归因]
    └── BacktestResult + Snapshots
            │
            ├── PnLAttributionEngine
            │       ├── Daily Attribution (每日归因)
            │       └── Trade Attribution (每笔交易归因)
            │
            ├── SliceAttributionEngine
            │       ├── By Underlying (按标的)
            │       ├── By Option Type (按期权类型)
            │       ├── By IV Regime (按 IV 环境)
            │       └── By Exit Reason (按平仓原因)
            │
            ├── StrategyDiagnosis [P2, 待实现]
            │       ├── Entry Quality
            │       ├── Exit Quality (What-If)
            │       └── Reversal Analysis
            │
            └── RegimeAnalyzer [P2, 待实现]
                    └── Regime Attribution

Pipeline._fetch_market_context()
    │
    └── MarketContext
            ├── symbol_klines (各标的日 K 线)
            ├── spy_klines (SPY 日 K 线)
            ├── vix_data (VIX 日数据)
            ├── economic_events (经济事件日历)
            └── trade_records (交易记录, 用于图表叠加)
```

### 3.3 关键类设计

> **实现说明**: 实际实现不依赖 `DuckDBProvider` 进行归因计算。所有归因数据通过 `AttributionCollector` 在回测期间采集的 Snapshot 获取，归因引擎直接操作内存数据。

#### AttributionCollector (Observer)

```python
class AttributionCollector:
    """挂载到 BacktestExecutor，采集持仓/组合快照"""
    position_snapshots: list[PositionSnapshot]   # 每日每持仓快照
    portfolio_snapshots: list[PortfolioSnapshot]  # 每日组合快照

    def on_daily_snapshot(self, date, positions, portfolio_state): ...
```

#### PnLAttributionEngine

```python
class PnLAttributionEngine:
    def __init__(self, position_snapshots, portfolio_snapshots, trade_records):
        ...

    def compute_all_daily(self) -> list[DailyAttribution]:
        """计算所有日期的归因"""

    def compute_trade_attributions(self) -> list[TradeAttribution]:
        """计算每笔交易的归因"""

    def attribution_summary(self) -> dict:
        """归因汇总摘要"""
```

#### SliceAttributionEngine

```python
class SliceAttributionEngine:
    def __init__(self, trade_attributions, position_snapshots):
        ...

    def by_underlying(self) -> dict[str, SliceStats]:
        """按标的切片"""

    def by_option_type(self) -> dict[str, SliceStats]:
        """按期权类型切片"""

    def by_exit_reason(self) -> dict[str, SliceStats]:
        """按平仓原因切片"""

    def by_iv_regime(self) -> dict[str, SliceStats]:
        """按 IV 环境切片"""
```

#### MarketContext (Pipeline 数据管道)

```python
@dataclass
class MarketContext:
    symbol_klines: dict[str, list]   # symbol → KlineBar list
    spy_klines: list                  # KlineBar list
    vix_data: list                    # MacroData list
    economic_events: list             # EconomicEvent list
    trade_records: list               # TradeRecord list (for chart overlay)
```

#### StrategyDiagnosis [P2, 待实现]

```python
class StrategyDiagnosis:
    def analyze_entry_quality(self) -> EntryQualityReport: ...
    def analyze_exit_quality(self) -> ExitQualityReport: ...
    def analyze_reversal_rate(self) -> ReversalReport: ...
```

#### RegimeAnalyzer [P2, 待实现]

```python
class RegimeAnalyzer:
    def label_regimes(self) -> pd.DataFrame: ...
    def attribute_by_regime(self) -> dict[str, RegimeStats]: ...
    def get_worst_regimes(self, n: int = 3) -> list[RegimeStats]: ...
```

---

## 四、实现优先级

### P0 - 核心归因 (Must Have) ✅ 已完成

| 功能 | 说明 | 状态 |
|------|------|------|
| Daily Position Snapshot | 每日持仓快照记录 (`attribution/collector.py`) | ✅ |
| Portfolio Snapshot | 组合 Greeks 暴露 (`attribution/models.py`) | ✅ |
| Greeks PnL Attribution | Daily + Per-Trade 归因 (`attribution/pnl_attribution.py`) | ✅ |
| Attribution Charts | 瀑布图、累计面积图、每日柱状图、Greeks 2×2 子图 | ✅ |

### P1 - 多维度切片 (Should Have) ✅ 已完成

| 功能 | 说明 | 状态 |
|------|------|------|
| 按标的/期权类型归因 | `slice_attribution.py: by_underlying(), by_option_type()` | ✅ |
| 按开仓 IV 归因 | `slice_attribution.py: by_iv_regime()` | ✅ |
| 按平仓原因归因 | `slice_attribution.py: by_exit_reason()` | ✅ |

### P2 - 策略诊断 (Nice to Have) ⏳ 待实现

| 功能 | 说明 | 状态 |
|------|------|------|
| Entry Quality Analysis | IV vs RV 分析 | ⏳ |
| Exit What-If Analysis | 反事实分析 | ⏳ |
| Reversal Rate Analysis | 止损反转率 | ⏳ |
| Regime Analysis | 市场环境分析 | ⏳ |

### P3 - 可视化增强 ✅ 已完成

| 功能 | 说明 | 状态 |
|------|------|------|
| Symbol K 线图 | Candlestick + Volume + 交易标记叠加 (`dashboard.py`) | ✅ |
| VIX K 线图 | 日 K 线 (`dashboard.py`) | ✅ |
| SPY K 线图 | Candlestick + Volume (`dashboard.py`) | ✅ |
| 事件日历 | FOMC/CPI/NFP/GDP/PPI 菱形标记 (`dashboard.py`) | ✅ |
| Position Timeline 修复 | position_id 配对 + 同日最小宽度 + ISO 日期 | ✅ |
| Greeks Exposure 修复 | 改为 2×2 子图避免量级遮盖 | ✅ |
| MarketContext 数据管道 | Pipeline 获取 K 线/VIX/事件数据传入 Dashboard | ✅ |

---

## 五、验收标准

### 5.1 功能验收

| 功能 | 验收标准 |
|------|----------|
| Greeks 归因 | Σ(归因) 与 Actual PnL 残差 < 10% |
| What-If 分析 | 覆盖 100% 的止损交易 |
| Regime 分析 | 覆盖 100% 的交易日 |
| 可视化 | 所有图表可交互、可导出 |

### 5.2 性能要求

| 指标 | 要求 |
|------|------|
| 归因计算 | 2 个月数据 < 30s |
| 报告生成 | < 60s |
| 内存占用 | < 2GB |

### 5.3 测试要求

| 测试类型 | 覆盖范围 |
|----------|----------|
| 单元测试 | 归因公式正确性 |
| 集成测试 | 完整流程 (GOOG, SPY, 2025-12 ~ 2026-02) |
| 回归测试 | 现有功能不受影响 |

---

## 六、附录

### 6.1 参考资料

- [Option Greeks Explained](https://www.optionseducation.org/advancedconcepts/greeks)
- [Volatility Risk Premium](https://www.investopedia.com/terms/v/volatility-risk-premium.asp)
- [Taylor Series for Option Pricing](https://en.wikipedia.org/wiki/Greeks_(finance))

### 6.2 术语表

| 术语 | 定义 |
|------|------|
| **VRP** | Volatility Risk Premium = IV - RV |
| **IV Rank** | 当前 IV 在过去 52 周的百分位 |
| **Beta Weighted Delta** | 以 SPY 为基准标准化的 Delta |
| **Gamma Bleed** | 卖方因 Gamma 导致的亏损 |
| **Regime** | 市场环境分类 (波动率 + 方向 + 事件) |

### 6.3 现有代码依赖

| 模块 | 路径 | 说明 |
|------|------|------|
| BacktestResult | `src/backtest/engine/backtest_executor.py` | 回测结果 |
| DailySnapshot | `src/backtest/engine/backtest_executor.py` | 每日快照 |
| TradeRecord | `src/backtest/engine/trade_simulator.py` | 交易记录 |
| DuckDBProvider | `src/backtest/data/duckdb_provider.py` | 数据提供者 |
| BacktestDashboard | `src/backtest/visualization/dashboard.py` | 可视化 |
