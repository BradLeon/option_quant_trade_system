## Context

本项目采用 data model 驱动的架构，计算流程为 `ModelA → Engine Function → ModelB`。

已有模块：
- **数据层**: `AccountPosition` (账户持仓), `StockVolatility` (波动率数据), `TechnicalData`, `Fundamental`
- **引擎层**: `StrategyMetrics` (策略指标), `TechnicalScore` (技术分析), `FundamentalScore` (基本面分析), `VolatilityScore`
- **业务层**: `PositionData` (监控输入), `MonitorResult` (监控输出)

**关键 Engine 层算子（必须复用，禁止重复实现）**:

| 算子函数 | 输入模型 | 输出 | 位置 |
|---------|---------|------|------|
| `get_iv_hv_ratio()` | `StockVolatility` | `float` | `engine/position/volatility/metrics.py` |
| `get_iv_rank()` | `StockVolatility` | `float` | `engine/position/volatility/metrics.py` |
| `evaluate_volatility()` | `StockVolatility` | `VolatilityScore` | `engine/position/volatility/metrics.py` |
| `calc_technical_score()` | `TechnicalData` | `TechnicalScore` | `engine/position/technical/metrics.py` |
| `calc_technical_signal()` | `TechnicalData` | `TechnicalSignal` | `engine/position/technical/metrics.py` |
| `evaluate_fundamentals()` | `Fundamental` | `FundamentalScore` | `engine/position/fundamental/metrics.py` |
| `calc_portfolio_tgr()` | `list[Position]` | `float` | `engine/portfolio/risk_metrics.py` |
| `calc_concentration_risk()` | `list[Position]` | `float` | `engine/portfolio/risk_metrics.py` |
| `strategy.calc_metrics()` | `OptionStrategy` | `StrategyMetrics` | `engine/strategy/base.py` |

参考实现：
- `tests/verification/verify_position_strategies.py` - 期权策略指标计算
- `tests/verification/verify_portfolio_calculations.py` - 组合级计算
- `tests/verification/verify_technical_data.py` - 技术指标验证
- `tests/verification/verify_fundamental_data.py` - 基本面数据验证

## Goals / Non-Goals

### Goals
- 实现从真实账户持仓到监控建议的完整数据流
- 最小化 API 请求，批量获取数据
- CLI 输出清晰的监控报告和调整建议
- 遵循项目分层架构原则

### Non-Goals
- 暂不实现飞书推送（Phase 2）
- 暂不实现自动化定时监控（cron 调度）
- 暂不实现策略回测

## Decisions

### 0. Engine 层算子复用原则（核心设计约束）

**问题**: `PositionData` 中的某些计算（如 `iv_hv_ratio`）与 engine 层已有算子重复。

**决策**: **禁止在 PositionData 中重复实现 engine 层已有的计算逻辑**。

**实现方式**:
1. `PositionData` 仅作为**数据容器**，存储从 engine 层算子获取的结果值
2. `MonitoringDataBridge` 负责调用 engine 层算子，将结果填充到 `PositionData`
3. 计算流程遵循 `DataModel → Engine Function → Result` 模式

```python
# ❌ 错误做法：在 PositionData 中实现计算
@dataclass
class PositionData:
    iv: float
    hv: float

    @property
    def iv_hv_ratio(self) -> float | None:
        if self.iv and self.hv and self.hv > 0:
            return self.iv / self.hv  # 重复实现！
        return None

# ❌ 错误做法：调用多个单独算子
def _enrich_volatility_data(self, pos: PositionData, vol: StockVolatility):
    pos.iv_hv_ratio = get_iv_hv_ratio(vol)  # 调用多个算子
    pos.iv_rank = get_iv_rank(vol)          # 这些都包含在 VolatilityScore 中

# ✅ 正确做法：调用统一出口，一次获取所有指标
class MonitoringDataBridge:
    def _enrich_volatility_data(self, pos: PositionData, vol: StockVolatility):
        # 调用统一出口算子
        vol_score: VolatilityScore = evaluate_volatility(vol)

        # 从 Output Model 提取所有字段
        pos.iv_hv_ratio = vol_score.iv_hv_ratio
        pos.iv_rank = vol_score.iv_rank
        pos.iv_percentile = vol_score.iv_percentile
        pos.volatility_score = vol_score.score
        pos.volatility_rating = vol_score.rating.value
```

**理由**:
- 避免重复代码和逻辑不一致
- engine 层算子已经过充分测试
- 保持分层架构的清晰职责

### 1. DataBridge 设计 (Engine 层算子调用)

**问题**: Monitor 模块需要从 Engine 层获取各类分析结果，需要清晰的数据转换层。

**决策**: 创建 `data_bridge.py` 模块，负责：
1. 将 `AccountPosition` 转换为 `PositionData`
2. 调用 Engine 层算子填充分析结果
3. 批量获取数据避免 API 限速

#### 1.1 Engine 层算子调用映射（统一出口原则）

**设计原则**: 每类分析只调用一个统一出口函数，返回包含所有指标的 Output Model。

| 分析类型 | Engine 算子 (统一出口) | 输入 Model | 输出 Model | 输出 Model 包含的字段 |
|---------|----------------------|-----------|-----------|---------------------|
| **波动率分析** | `evaluate_volatility()` | `StockVolatility` | `VolatilityScore` | `score`, `rating`, `iv_rank`, `iv_hv_ratio`, `iv_percentile`, `pcr` |
| **技术分析** | `calc_technical_score()` | `TechnicalData` | `TechnicalScore` | `trend_signal`, `ma_alignment`, `rsi`, `rsi_zone`, `adx`, `support`, `resistance`, `atr` |
| **基本面分析** | `evaluate_fundamentals()` | `Fundamental` | `FundamentalScore` | `score`, `rating`, `pe_score`, `growth_score`, `margin_score`, `analyst_score` |
| **策略指标** | `strategy.calc_metrics()` | `OptionStrategy` | `StrategyMetrics` | `prei`, `tgr`, `sas`, `roc`, `expected_roc`, `sharpe_ratio`, `kelly_fraction`, `win_probability` |
| **组合风险** | `calc_portfolio_metrics()` | `list[Position]` | `PortfolioRiskMetrics` | `tgr`, `concentration_hhi`, `beta_weighted_delta`, `total_delta/gamma/theta/vega` |

**注**: 如果 Output Model 字段不完整，应修改 engine 层的 Model 和算子，而非在 monitor 层调用多个算子。

#### 1.2 Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MonitoringDataBridge                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  INPUT: ConsolidatedPortfolio (from AccountAggregator)                      │
│         ├── positions: list[AccountPosition]                                │
│         └── account_summaries                                               │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 1: 收集所有标的 symbols (underlying for options, self for stocks)│   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 2: 批量获取补充数据 (UnifiedDataProvider)                       │   │
│  │   ├── get_stock_volatility(symbol) → StockVolatility                │   │
│  │   ├── get_technical_data(symbol)   → TechnicalData                  │   │
│  │   └── get_fundamental(symbol)      → Fundamental                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Step 3: 调用 Engine 层算子，填充分析结果                             │   │
│  │                                                                     │   │
│  │   [期权持仓]                                                         │   │
│  │   AccountPosition ──┬──► create_strategies_from_position()          │   │
│  │                     │         └──► OptionStrategy                    │   │
│  │                     │                  └──► calc_metrics()           │   │
│  │                     │                         └──► StrategyMetrics   │   │
│  │                     │                               (prei,tgr,sas...)│   │
│  │                     │                                                │   │
│  │                     ├──► StockVolatility                             │   │
│  │                     │         └──► get_iv_hv_ratio/evaluate_volatility│  │
│  │                     │                                                │   │
│  │                     └──► TechnicalData                               │   │
│  │                               └──► calc_technical_score/signal       │   │
│  │                                                                     │   │
│  │   [股票持仓]                                                         │   │
│  │   AccountPosition ──┬──► StockVolatility → evaluate_volatility()    │   │
│  │                     ├──► TechnicalData   → calc_technical_score()   │   │
│  │                     └──► Fundamental     → evaluate_fundamentals()  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                          │                                                  │
│                          ▼                                                  │
│  OUTPUT: list[PositionData] (已填充所有分析结果)                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 1.3 核心函数定义

| 函数 | 作用 |
|------|------|
| `convert_positions()` | 主入口：ConsolidatedPortfolio → list[PositionData] |
| `_prefetch_data()` | 批量预获取 Volatility/Technical/Fundamental 数据 |
| `_convert_option_position()` | 转换期权持仓，调用策略算子 |
| `_convert_stock_position()` | 转换股票持仓，调用分析算子 |
| `_enrich_volatility()` | 调用波动率算子填充字段 |
| `_enrich_technical()` | 调用技术分析算子填充字段 |
| `_enrich_fundamental()` | 调用基本面算子填充字段 |
| `_enrich_strategy_metrics()` | 调用策略算子填充 PREI/TGR/SAS 等 |

#### 1.4 缓存策略

- 同一 underlying 的多个期权共享 Volatility/Technical/Fundamental 数据
- 缓存有效期：5 分钟（适合日内监控）
- 批量获取减少 API 调用次数

### 2. 期权持仓监控增强

**问题**: 当前 `PositionMonitor` 仅检查基础指标，缺少策略级评分。

**决策**: 集成 `create_strategies_from_position()` 获取 `StrategyMetrics`。

```python
# 增强 PositionData 转换
def _convert_option_position(
    self,
    pos: AccountPosition,
    all_positions: list[AccountPosition],
) -> PositionData:
    # 1. 创建策略实例
    strategies = create_strategies_from_position(
        position=pos,
        all_positions=all_positions,
        ibkr_provider=self._ibkr,
    )

    # 2. 获取策略指标
    if strategies:
        metrics = strategies[0].strategy.calc_metrics()
        prei = metrics.prei
        tgr = metrics.tgr
        sas = metrics.sas
        roc = metrics.roc
        sharpe = metrics.sharpe_ratio
        kelly = metrics.kelly_fraction

    # 3. 构建 PositionData
    return PositionData(
        position_id=f"{pos.symbol}_{pos.strike}_{pos.expiry}",
        symbol=pos.symbol,
        prei=prei,
        tgr=tgr,
        # ... 其他字段
    )
```

### 3. PositionData 统一模型设计

**问题**: 需要同时支持期权和股票持仓，且共享标的分析数据。

**决策**: 扩展 `PositionData` 为**纯数据容器**，通过 `asset_type` 区分类型。**所有计算由 DataBridge 调用 engine 层算子完成，结果存储到对应字段**。

```python
@dataclass
class PositionData:
    """持仓数据（统一支持期权和股票）

    设计原则：
    - 纯数据容器，不包含计算逻辑（遵循 Decision #0）
    - 期权专用字段（strike, expiry等）股票持仓为 None
    - 标的分析字段（技术面、波动率）期权和股票都可以有
    - 期权的标的分析基于 underlying，股票基于自身
    - 所有派生值由 DataBridge 调用 engine 层算子计算后填充
    """

    # === 基础信息 ===
    position_id: str
    symbol: str                           # 持仓代码
    asset_type: str                       # "option" / "stock"
    quantity: float
    entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    currency: str
    broker: str
    timestamp: datetime

    # === 期权专用字段（股票为 None）===
    underlying: str | None = None         # 底层标的
    option_type: str | None = None        # "put" / "call"
    strike: float | None = None
    expiry: str | None = None             # YYYYMMDD
    dte: int | None = None
    contract_multiplier: int = 1
    moneyness: float | None = None        # 由 DataBridge 计算: (S-K)/K

    # === Greeks（期权必须，股票 delta=quantity）===
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    iv: float | None = None

    # === 标的价格（期权为 underlying 价格，股票为自身价格）===
    underlying_price: float | None = None

    # === 波动率数据（由 DataBridge 调用 engine 层算子填充）===
    hv: float | None = None               # 来自 get_hv(StockVolatility)
    iv_rank: float | None = None          # 来自 get_iv_rank(StockVolatility)
    iv_percentile: float | None = None    # 来自 get_iv_percentile(StockVolatility)
    iv_hv_ratio: float | None = None      # 来自 get_iv_hv_ratio(StockVolatility)
    volatility_score: float | None = None # 来自 evaluate_volatility().score
    volatility_rating: str | None = None  # 来自 evaluate_volatility().rating

    # === 技术面分析（由 DataBridge 调用 calc_technical_score/signal 填充）===
    trend_signal: str | None = None       # 来自 TechnicalScore.trend_signal
    ma_alignment: str | None = None       # 来自 TechnicalScore.ma_alignment
    rsi: float | None = None              # 来自 TechnicalScore.rsi
    rsi_zone: str | None = None           # 来自 TechnicalScore.rsi_zone
    adx: float | None = None              # 来自 TechnicalScore.adx
    support: float | None = None          # 来自 TechnicalScore.support
    resistance: float | None = None       # 来自 TechnicalScore.resistance

    # === 基本面分析（由 DataBridge 调用 evaluate_fundamentals 填充）===
    pe_ratio: float | None = None         # 来自 Fundamental.pe_ratio
    fundamental_score: float | None = None  # 来自 FundamentalScore.score
    analyst_rating: str | None = None     # 来自 FundamentalScore.rating

    # === 策略指标（由 DataBridge 调用 strategy.calc_metrics() 填充）===
    strategy_type: str | None = None      # "short_put" / "covered_call" 等
    prei: float | None = None             # 来自 StrategyMetrics.prei
    tgr: float | None = None              # 来自 StrategyMetrics.tgr
    sas: float | None = None              # 来自 StrategyMetrics.sas
    roc: float | None = None              # 来自 StrategyMetrics.roc
    expected_roc: float | None = None     # 来自 StrategyMetrics.expected_roc
    sharpe: float | None = None           # 来自 StrategyMetrics.sharpe_ratio
    kelly: float | None = None            # 来自 StrategyMetrics.kelly_fraction
    win_probability: float | None = None  # 来自 StrategyMetrics.win_probability

    # === 便捷属性（仅做类型判断，无计算逻辑）===
    @property
    def is_option(self) -> bool:
        return self.asset_type == "option"

    @property
    def is_stock(self) -> bool:
        return self.asset_type == "stock"
```

**数据共享逻辑**:
- 期权持仓的技术面/基本面/波动率数据基于 `underlying`
- 股票持仓的这些数据基于自身 `symbol`
- 同一 underlying 的多个期权可以共享这些数据（通过缓存）

### 4. SuggestionGenerator 设计

**问题**: 监控系统仅生成 Alert（发现问题），缺少 Suggestion（解决方案）。

**决策**: 新建 `suggestions.py` 模块，将 Alert 转换为可执行的调整建议。

#### 4.1 数据模型定义

| Dataclass | 作用 |
|-----------|------|
| `ActionType` (Enum) | 建议动作类型 |
| `UrgencyLevel` (Enum) | 紧急程度: IMMEDIATE, SOON, MONITOR |
| `PositionSuggestion` | 持仓调整建议，包含 action, urgency, reason, details, trigger_alerts |

**ActionType 枚举值**:

| ActionType | 含义 | 适用场景 |
|-----------|------|---------|
| `HOLD` | 继续持有 | 指标正常，无需操作 |
| `MONITOR` | 密切关注 | 黄色预警，观察变化 |
| `CLOSE` | 平仓 | 止损、止盈、高风险 |
| `REDUCE` | 减仓 | 风险敞口过大 |
| `ROLL` | 展期 | 临近到期、ITM |
| `HEDGE` | 对冲 | 方向性风险过大 |
| `ADJUST` | 调整策略 | TGR/效率不佳 |
| `SET_STOP` | 设置止损 | 中等风险，需防守 |
| `REVIEW` | 复盘评估 | 策略吸引力下降 |
| `DIVERSIFY` | 分散化 | 集中度过高 |
| `TAKE_PROFIT` | 止盈 | 达到收益目标 |

#### 4.2 核心函数定义

| 函数 | 作用 |
|------|------|
| `generate()` | 主入口：MonitorResult + PositionData → list[PositionSuggestion] |
| `_group_alerts_by_position()` | 将 alerts 按 position_id 分组 |
| `_get_highest_priority_alert()` | 从多个 alert 中选取最高优先级 |
| `_generate_for_position()` | 为单个持仓生成建议 |
| `_adjust_for_market()` | 根据市场情绪调整建议优先级 |
| `_sort_by_priority()` | 按 IMMEDIATE > SOON > MONITOR 排序 |

#### 4.3 Workflow

```
MonitorResult.alerts
        │
        ▼
┌─────────────────────────────┐
│ _group_alerts_by_position() │  按 position_id 分组
└─────────────────────────────┘
        │
        ▼ {position_id: [alerts]}
┌─────────────────────────────┐
│ _get_highest_priority_alert │  每组取最高优先级 alert
└─────────────────────────────┘
        │
        ▼ primary_alert
┌─────────────────────────────┐
│ ALERT_ACTION_MAP 查表       │  (AlertType, AlertLevel) → (ActionType, UrgencyLevel)
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ _generate_for_position()    │  生成 PositionSuggestion
└─────────────────────────────┘
        │
        ▼ list[PositionSuggestion]
┌─────────────────────────────┐
│ _adjust_for_market()        │  市场环境调整（VIX>25 提高优先级）
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ _sort_by_priority()         │  按紧急程度排序输出
└─────────────────────────────┘
```

#### 4.4 三层指标体系与阈值规则

监控指标按层级组织，每个指标有明确的阈值范围和对应动作。

##### 4.4.1 Portfolio-Level 指标

| 指标 | 计算方式 | 阈值范围 | AlertLevel | Action | Urgency |
|-----|---------|---------|------------|--------|---------|
| **Portfolio Delta** | Σ(Position Delta × Beta) | > 300 | RED | HEDGE | IMMEDIATE |
| (Beta加权方向敞口) | | 100-300 | YELLOW | MONITOR | MONITOR |
| | | < 100 | GREEN | HOLD | - |
| **Portfolio Theta** | Σ(Position Theta) | < 0 (买方净头寸) | YELLOW | REVIEW | SOON |
| (每日时间收益) | | > 日均目标×2 | YELLOW | MONITOR | MONITOR |
| **Portfolio Vega** | Σ(Position Vega) | 负值 + 低IV环境 | YELLOW | REDUCE | SOON |
| (波动率敞口) | | 正值 + 事件前 | YELLOW | CLOSE | SOON |
| **Portfolio Gamma** | Σ(Position Gamma) | < -50 | RED | REDUCE | IMMEDIATE |
| (加速风险) | | -50 ~ -30 | YELLOW | SET_STOP | SOON |
| | | > -30 | GREEN | HOLD | - |
| **Portfolio TGR** | Theta$ / \|Gamma$\| | < 0.05 | RED | ADJUST | IMMEDIATE |
| (Theta/Gamma效率) | | 0.05-0.15 | YELLOW | MONITOR | MONITOR |
| | | > 0.15 | GREEN | HOLD | - |
| **集中度 (HHI)** | Σ(weight²) | > 0.5 | YELLOW | DIVERSIFY | SOON |
| | | > 0.8 | RED | DIVERSIFY | IMMEDIATE |

##### 4.4.2 Position-Level 指标

| 指标类别 | 指标 | 阈值范围 | AlertLevel | Action | Urgency | 策略依据 |
|---------|-----|---------|------------|--------|---------|---------|
| **行权风险** | Moneyness (S-K)/K | ITM > 5% | RED | ROLL/CLOSE | IMMEDIATE | 准备被行权 |
| | | ATM ±5% | YELLOW | MONITOR | SOON | 高Gamma区 |
| | | OTM < -5% | GREEN | HOLD | - | 安全 |
| | Delta \|Δ\| | > 0.8 | RED | CLOSE | IMMEDIATE | 深度实值 |
| | | 0.3-0.7 | YELLOW | MONITOR | MONITOR | 活跃区 |
| | | < 0.2 | GREEN | HOLD | - | 深度虚值 |
| **加速风险** | Gamma \|Γ\| | > 0.05 | RED | REDUCE | IMMEDIATE | 高Gamma风险 |
| | | 0.02-0.05 | YELLOW | MONITOR | MONITOR | 中等 |
| | | < 0.02 | GREEN | HOLD | - | 稳定 |
| **时间风险** | DTE | ≤ 3 天 | RED | ROLL/CLOSE | IMMEDIATE | Gamma爆炸区 |
| | | 4-7 天 | YELLOW | ROLL | SOON | 准备展期 |
| | | > 21 天 | GREEN | HOLD | - | 安全 |
| **波动率** | IV/HV | > 1.5 | GREEN | HOLD | - | 卖出机会好 |
| | | 0.8-1.2 | - | HOLD | - | 正常 |
| | | < 0.8 | YELLOW | REVIEW | MONITOR | 吸引力下降 |
| **综合评分** | SAS | < 30 | RED | CLOSE | SOON | 策略失效 |
| (策略吸引力) | | 30-50 | YELLOW | REVIEW | MONITOR | 边缘 |
| | | > 50 | GREEN | HOLD | - | 可持有 |
| **风险暴露** | PREI | > 75 | RED | REDUCE/HEDGE | IMMEDIATE | 红色警报 |
| | | 40-75 | YELLOW | MONITOR | MONITOR | 黄色关注 |
| | | < 40 | GREEN | HOLD | - | 安全 |
| **效率指标** | TGR (Position) | < 0.1 | YELLOW | ADJUST | SOON | 需调整 |
| | | 0.1-0.2 | GREEN | HOLD | - | 良好 |
| | | > 0.2 | GREEN | HOLD | - | 优秀 |
| **收益效率** | ROC (年化) | < 15% | YELLOW | REVIEW | MONITOR | 低效 |
| | | 15-30% | GREEN | HOLD | - | 正常 |
| | | > 30% | GREEN | HOLD | - | 高效 |
| **盈亏管理** | PnL% | ≤ -100% | RED | CLOSE | IMMEDIATE | 止损 |
| | | ≥ 50% | GREEN | TAKE_PROFIT | SOON | 止盈 |

##### 4.4.3 Capital-Level 指标

| 指标 | 目标值 | 阈值范围 | AlertLevel | Action | Urgency |
|-----|-------|---------|------------|--------|---------|
| **Sharpe Ratio** | > 1.5 | < 1.0 | YELLOW | REVIEW_STRATEGY | SOON |
| | | < 0.5 | RED | REVIEW_STRATEGY | IMMEDIATE |
| **Kelly 使用率** | 0.25×Kelly | > 100% | RED | REDUCE | IMMEDIATE |
| | | 50-100% | YELLOW | MONITOR | MONITOR |
| **最大回撤** | < 15% | > 15% | RED | STOP_TRADING | IMMEDIATE |
| | | 10-15% | YELLOW | REDUCE | SOON |
| **保证金使用率** | < 50% | > 80% | RED | REDUCE | IMMEDIATE |
| | | 50-80% | YELLOW | MONITOR | MONITOR |

#### 4.5 ALERT_ACTION_MAP 配置

基于上述指标体系，`ALERT_ACTION_MAP` 的配置逻辑：

```python
# 映射结构: (AlertType, AlertLevel) → (ActionType, UrgencyLevel)
ALERT_ACTION_MAP = {
    # === RED Alerts → IMMEDIATE ===
    (AlertType.STOP_LOSS, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.DTE_WARNING, AlertLevel.RED): (ActionType.ROLL, UrgencyLevel.IMMEDIATE),
    (AlertType.MONEYNESS, AlertLevel.RED): (ActionType.ROLL, UrgencyLevel.IMMEDIATE),
    (AlertType.DELTA_CHANGE, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.GAMMA_EXPOSURE, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.PREI_HIGH, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.TGR_LOW, AlertLevel.RED): (ActionType.ADJUST, UrgencyLevel.IMMEDIATE),
    (AlertType.MARGIN_WARNING, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.DRAWDOWN, AlertLevel.RED): (ActionType.CLOSE, UrgencyLevel.IMMEDIATE),
    (AlertType.KELLY_USAGE, AlertLevel.RED): (ActionType.REDUCE, UrgencyLevel.IMMEDIATE),
    (AlertType.CONCENTRATION, AlertLevel.RED): (ActionType.DIVERSIFY, UrgencyLevel.IMMEDIATE),

    # === YELLOW Alerts → SOON or MONITOR ===
    (AlertType.DTE_WARNING, AlertLevel.YELLOW): (ActionType.ROLL, UrgencyLevel.SOON),
    (AlertType.MONEYNESS, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.DELTA_CHANGE, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.GAMMA_EXPOSURE, AlertLevel.YELLOW): (ActionType.SET_STOP, UrgencyLevel.SOON),
    (AlertType.GAMMA_NEAR_EXPIRY, AlertLevel.YELLOW): (ActionType.ROLL, UrgencyLevel.SOON),
    (AlertType.PREI_HIGH, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.IV_HV_CHANGE, AlertLevel.YELLOW): (ActionType.REVIEW, UrgencyLevel.MONITOR),
    (AlertType.TGR_LOW, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.VEGA_EXPOSURE, AlertLevel.YELLOW): (ActionType.REDUCE, UrgencyLevel.SOON),
    (AlertType.SHARPE_LOW, AlertLevel.YELLOW): (ActionType.REVIEW, UrgencyLevel.SOON),
    (AlertType.MARGIN_WARNING, AlertLevel.YELLOW): (ActionType.MONITOR, UrgencyLevel.MONITOR),
    (AlertType.CONCENTRATION, AlertLevel.YELLOW): (ActionType.DIVERSIFY, UrgencyLevel.SOON),

    # === GREEN Alerts → Opportunities ===
    (AlertType.PROFIT_TARGET, AlertLevel.GREEN): (ActionType.TAKE_PROFIT, UrgencyLevel.SOON),
    (AlertType.IV_HV_CHANGE, AlertLevel.GREEN): (ActionType.HOLD, UrgencyLevel.MONITOR),  # 高IV环境有利
}
```

**优先级规则**:
1. **AlertLevel 优先**: RED > YELLOW > GREEN
2. **同级别内按危险程度**: 止损 > 行权风险 > Gamma风险 > Delta风险 > 其他
3. **同持仓多个 Alert**: 取最高优先级生成 Suggestion

#### 4.6 市场环境调整逻辑

| 市场条件 | 调整规则 |
|---------|---------|
| VIX > 25 | 所有 REDUCE/HEDGE/CLOSE 建议: MONITOR → SOON |
| VIX > 35 | 所有风险建议: SOON → IMMEDIATE |
| Trend = Bearish | Short Put 相关: 优先级提升一级 |
| Trend = Bullish | Short Call 相关: 优先级提升一级 |
| 高Gamma环境 (临近到期) | 所有建议附加 Gamma 风险警告 |

### 5. CLI 命令设计

**决策**: 增强 `monitor` 命令，支持真实账户数据。

```bash
# 从真实账户监控
python -m src.business.cli monitor --account-type paper

# 指定券商
python -m src.business.cli monitor --account-type paper --ibkr-only

# 详细输出
python -m src.business.cli monitor --account-type paper -v

# 输出 JSON 格式
python -m src.business.cli monitor --account-type paper --output json
```

### 6. 数据获取优化

**问题**: 避免重复 API 调用导致限速。

**决策**:
1. 使用缓存存储已获取的数据
2. 批量获取波动率数据
3. 复用 `AccountAggregator` 已获取的 Greeks

```python
class MonitoringDataBridge:
    def __init__(self):
        # 缓存
        self._volatility_cache: dict[str, StockVolatility] = {}
        self._technical_cache: dict[str, TechnicalScore] = {}
        self._fundamental_cache: dict[str, FundamentalScore] = {}

    def _prefetch_volatility(self, symbols: set[str]) -> None:
        """批量预获取波动率数据"""
        for symbol in symbols:
            if symbol not in self._volatility_cache:
                try:
                    vol = self._provider.get_stock_volatility(symbol)
                    if vol:
                        self._volatility_cache[symbol] = vol
                except Exception as e:
                    logger.warning(f"Failed to get volatility for {symbol}: {e}")
```

### 7. 端到端 Workflow 总览

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Monitor System Workflow                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐                                                                │
│  │   CLI       │  python -m src.business.cli monitor --account-type paper       │
│  └──────┬──────┘                                                                │
│         │                                                                       │
│         ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        AccountAggregator                                │   │
│  │  get_consolidated_portfolio() → ConsolidatedPortfolio                   │   │
│  │    ├── IBKR positions (Greeks included)                                 │   │
│  │    └── Futu positions (Greeks included)                                 │   │
│  └──────────────────────────────┬──────────────────────────────────────────┘   │
│                                 │                                               │
│                                 ▼ ConsolidatedPortfolio                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      MonitoringDataBridge                               │   │
│  │                                                                         │   │
│  │  1. 收集 symbols → 批量获取补充数据                                     │   │
│  │  2. 调用 Engine 层算子:                                                 │   │
│  │     - evaluate_volatility(StockVolatility) → VolatilityScore            │   │
│  │     - calc_technical_score(TechnicalData) → TechnicalScore              │   │
│  │     - evaluate_fundamentals(Fundamental) → FundamentalScore             │   │
│  │     - strategy.calc_metrics() → StrategyMetrics (期权)                  │   │
│  │  3. 填充分析结果到 PositionData                                         │   │
│  │                                                                         │   │
│  └──────────────────────────────┬──────────────────────────────────────────┘   │
│                                 │                                               │
│                                 ▼ list[PositionData]                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      MonitoringPipeline.run()                           │   │
│  │                                                                         │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │   │
│  │  │ PortfolioMonitor.evaluate()                                      │  │   │
│  │  │   - calc_portfolio_delta/gamma/theta/vega()                      │  │   │
│  │  │   - calc_portfolio_tgr()                                         │  │   │
│  │  │   - calc_concentration_risk()                                    │  │   │
│  │  │   → Portfolio-level Alerts                                       │  │   │
│  │  └──────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                         │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │   │
│  │  │ PositionMonitor.evaluate()                                       │  │   │
│  │  │   - check_moneyness(), check_delta(), check_dte()                │  │   │
│  │  │   - check_prei(), check_iv_hv(), check_pnl()                     │  │   │
│  │  │   - check_sas(), check_roc(), check_kelly()  (新增)              │  │   │
│  │  │   → Position-level Alerts                                        │  │   │
│  │  └──────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                         │   │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │   │
│  │  │ CapitalMonitor.evaluate()                                        │  │   │
│  │  │   - check_margin_usage()                                         │  │   │
│  │  │   - check_drawdown()                                             │  │   │
│  │  │   → Capital-level Alerts                                         │  │   │
│  │  └──────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                         │   │
│  └──────────────────────────────┬──────────────────────────────────────────┘   │
│                                 │                                               │
│                                 ▼ MonitorResult (alerts)                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      SuggestionGenerator.generate()                     │   │
│  │                                                                         │   │
│  │  1. 按 position_id 分组 alerts                                          │   │
│  │  2. ALERT_ACTION_MAP 查表: (AlertType, AlertLevel) → (Action, Urgency)  │   │
│  │  3. 市场环境调整 (VIX > 25 提高优先级)                                  │   │
│  │  4. 按优先级排序                                                        │   │
│  │                                                                         │   │
│  └──────────────────────────────┬──────────────────────────────────────────┘   │
│                                 │                                               │
│                                 ▼ list[PositionSuggestion]                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      CLI Output Formatter                               │   │
│  │                                                                         │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │   │
│  │  │ 账户概览: 总资产 $xxx | 保证金使用率 xx%                         │   │   │
│  │  ├─────────────────────────────────────────────────────────────────┤   │   │
│  │  │ 持仓列表: Symbol | Type | DTE | Delta | PnL% | PREI | SAS       │   │   │
│  │  ├─────────────────────────────────────────────────────────────────┤   │   │
│  │  │ 组合 Greeks: Delta$ | Gamma$ | Theta$ | Vega$ | TGR             │   │   │
│  │  ├─────────────────────────────────────────────────────────────────┤   │   │
│  │  │ 预警列表: 🔴 RED | 🟡 YELLOW | 🟢 GREEN                         │   │   │
│  │  ├─────────────────────────────────────────────────────────────────┤   │   │
│  │  │ 调整建议: IMMEDIATE → SOON → MONITOR                            │   │   │
│  │  └─────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Risks / Trade-offs

### Risk 1: API 限速
- **问题**: 批量获取数据可能触发 API 限速
- **缓解**:
  - 添加请求间隔
  - 缓存已获取的数据
  - 优先复用 AccountAggregator 已获取的数据

### Risk 2: 数据一致性
- **问题**: 不同时间点获取的数据可能不一致
- **缓解**:
  - 在 `MonitorResult` 中记录数据时间戳
  - 关键指标使用同一时间点的数据

### Risk 3: 复杂度增加
- **问题**: 集成多个 engine 模块增加复杂度
- **缓解**:
  - 清晰的数据流文档
  - 分层测试（单元测试 + 集成测试）

## Open Questions

1. **缓存有效期**: 波动率/技术面数据缓存多久？
   - 建议: 5 分钟有效期，适合日内监控

2. **股票分析深度**: 股票持仓是否需要完整的技术面分析？
   - 建议: 首期仅做基础分析（趋势、支撑阻力）

3. **市场情绪权重**: 市场情绪如何影响调整建议？
   - 建议: 作为辅助参考，不改变核心逻辑
