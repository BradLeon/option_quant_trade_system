# 自动交易模块 (V2)

## 概述

V2 交易模块以 **Signal** 为核心，实现策略信号到订单的直接转换。取代 V1 四层架构（Pipeline → DecisionEngine → OrderGenerator → TradingProvider），简化为 **Signal → RiskGuard → SignalOrderBuilder → OrderValidator → TradingProvider**。

**输入**: `list[Signal]`（策略输出）+ `PortfolioState`（组合快照）
**输出**: `list[OrderRecord]`（订单执行记录）
**关键约束**: **仅支持 Paper Trading（模拟账户）**，硬性权限控制

### V1 → V2 对比

| V1 | V2 | 变化 |
|---|---|---|
| Signal → LiveSignalConverter → TradingDecision → OrderGenerator → OrderRequest | Signal → SignalOrderBuilder → OrderRequest | 3 次转换 → 1 次 |
| TradingDecision（30 字段中间体） | 消除 | Signal 承载意图，OrderRequest 承载指令 |
| AccountState | PortfolioState（+ 计算属性） | 统一共享模型 |
| DecisionEngine (Layer 1-2 风控) | RiskGuard chain（信号级） | 与回测共用 |
| DailyLimits（订单级阻断） | DailyLimitsGuard（信号级截断） | 截断而非拒绝 |
| RiskChecker（需要 AccountState） | OrderValidator（接受 PortfolioState） | 消除 AccountState 依赖 |

## 架构

### 目录结构

```
src/business/trading/
├── signal_order_builder.py        # Signal → OrderRequest 直接转换
├── live_executor.py               # LiveStrategyExecutor (plan/execute 两阶段)
├── live_snapshot_builder.py       # IBKR → MarketSnapshot + PortfolioState
├── pipeline.py                    # TradingPipeline V2 (execute_orders)
├── daily_limits.py                # DailyTradeTracker 核心逻辑
├── risk/
│   ├── __init__.py
│   └── daily_limits_guard.py      # DailyLimitsGuard (RiskGuard 协议)
├── config/
│   ├── order_config.py            # 订单管理配置
│   └── risk_config.py             # 风控限额配置（支持按策略覆盖）
├── order/
│   ├── manager.py                 # OrderManager 订单生命周期
│   ├── order_validator.py         # OrderValidator 订单级风控
│   └── store.py                   # OrderStore (JSON 持久化)
├── models/
│   ├── decision.py                # (遗留) TradingDecision, AccountState — 通知/回测仍引用
│   ├── order.py                   # OrderRequest, OrderRecord, OrderFill
│   └── trading.py                 # TradingResult, TradingAccountType
└── provider/
    ├── base.py                    # TradingProvider 抽象基类
    └── ibkr_trading.py            # IBKRTradingProvider (Paper Only)

src/strategy/                      # 共享模型层（回测 + 实盘）
├── models.py                      # Signal, Instrument, PortfolioState, MarketSnapshot
├── protocol.py                    # StrategyProtocol
└── risk.py                        # RiskGuard 协议

src/business/cli/commands/
└── strategy.py                    # `optrade strategy run` 唯一策略命令
```

### 数据流

```
IBKRProvider ──→ LiveSnapshotBuilder ──→ MarketSnapshot + PortfolioState
                                              │
                 strategy.generate_signals(market, portfolio, dp)
                                              │
                                         list[Signal]
                                              │
                 RiskGuard chain: AccountRiskGuard → DailyLimitsGuard → ...
                                              │
                                         list[Signal] (filtered/truncated)
                                              │
                 SignalOrderBuilder.build(signals, portfolio)
                                              │
                                         list[OrderRequest]
                                              │
                 OrderValidator.check(order, portfolio)
                                              │
                 OrderManager.submit(order) → TradingProvider
                                              │
                                         OrderRecord
```

### 组件架构图

```
┌─────────────────── LiveStrategyExecutor ───────────────────┐
│                                                             │
│  ┌──────────────┐    ┌─────────────────┐                   │
│  │ Snapshot      │───→│ Strategy        │                   │
│  │ Builder       │    │ .generate_signals│                  │
│  └──────────────┘    └────────┬────────┘                   │
│                               │ list[Signal]                │
│                     ┌─────────▼──────────┐                 │
│                     │  RiskGuard Chain    │                 │
│                     │  ├ AccountRiskGuard │                 │
│                     │  └ DailyLimitsGuard │                 │
│                     └─────────┬──────────┘                 │
│                               │ list[Signal]                │
│                     ┌─────────▼──────────┐                 │
│                     │ SignalOrderBuilder  │                 │
│                     │ Signal → OrderRequest│                │
│                     └─────────┬──────────┘                 │
│                               │ list[OrderRequest]          │
│                     ┌─────────▼──────────┐                 │
│                     │ TradingPipeline     │                 │
│                     │  ├ OrderValidator   │                 │
│                     │  ├ OrderManager     │                 │
│                     │  └ OrderStore       │                 │
│                     └─────────┬──────────┘                 │
│                     ┌─────────▼──────────┐                 │
│                     │ TradingProvider     │                 │
│                     │ (IBKR Paper Only)   │                 │
│                     └────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

## 核心概念

### Signal — 策略唯一输出

```python
@dataclass
class Signal:
    type: SignalType          # ENTRY | EXIT | ROLL | REBALANCE
    instrument: Instrument    # 目标合约（frozen dataclass, 可做 dict key）
    target_quantity: int      # 正=BUY, 负=SELL
    reason: str
    position_id: str | None   # EXIT/ROLL/REBALANCE 必填
    roll_to: Instrument | None  # ROLL 必填 — 目标新合约
    priority: int             # EXIT > ROLL > REBALANCE > ENTRY
    quote_price: float | None # 报价参考
    metadata: dict            # 策略自定义数据
    greeks: dict | None       # 可选 Greeks 快照
```

### LiveStrategyExecutor — plan/execute 两阶段

IBKR TWS 单 clientId 只允许一个连接。`LiveStrategyExecutor` 拆分为两个阶段：

| 阶段 | 方法 | 连接 | 工作内容 |
|------|------|------|---------|
| **Phase A** | `plan()` | 数据通道 | 数据采集 → 信号生成 → 风控过滤 → 订单构建 |
| **Phase B** | `execute(plan)` | 交易通道 | 订单验证 → 提交 → 状态追踪 |

```python
executor = LiveStrategyExecutor(strategy, risk_guards, config)

# Phase A: 数据 + 信号 + 订单构建
result, plan = executor.plan()
# result: LiveExecutionResult (统计摘要)
# plan: ExecutionPlan (orders, roll_pairs, portfolio, signals)

# Phase B: 提交订单
if not dry_run:
    records = executor.execute(plan)

# 便捷方法
result = executor.run_once(dry_run=True)  # 等价于 plan() + execute()
```

### SignalOrderBuilder — 信号到订单

取代 LiveSignalConverter + OrderGenerator 两步转换：

| SignalType | 生成订单数 | 处理逻辑 |
|-----------|----------|---------|
| ENTRY | 1 | instrument → order, quantity 符号决定 BUY/SELL |
| EXIT | 1 | 从 portfolio 查找 position，BUY to close |
| ROLL | 2 | close (MARKET) + open (LIMIT), 共享 decision_id |
| REBALANCE | 1 | 调整现有仓位 |

**Signal → OrderRequest 字段映射：**

| Signal 字段 | OrderRequest 字段 |
|---|---|
| `instrument.symbol` | `symbol` |
| `instrument.underlying` | `underlying` |
| `instrument.right.value` | `option_type` |
| `instrument.strike/expiry` | `strike/expiry` |
| `target_quantity` 符号 | `side` (BUY/SELL) |
| `quote_price` | `limit_price` |
| `type` | `decision_type` (ENTRY→"open", EXIT→"close", ROLL→"roll", REBALANCE→"adjust") |
| `instrument.lot_size` | `contract_multiplier` |

### RiskGuard Chain — 信号级风控

RiskGuard 协议（`src/strategy/risk.py`）在信号级别过滤/截断，与回测共用：

```python
class RiskGuard(Protocol):
    def check(self, signals, portfolio, market) -> list[Signal]: ...
```

| Guard | 职责 | 动作 |
|-------|------|------|
| `AccountRiskGuard` | 账户级门控（margin/position count） | 过滤所有 ENTRY |
| `DailyLimitsGuard` | 日内频率/规模限额 | 截断数量或过滤 |

**DailyLimitsGuard 截断语义**：不是拒绝整个信号，而是减少 `target_quantity`。例如：单标的日内限额剩余 1 张合约，信号请求 3 张 → 截断为 1 张。

### OrderValidator — 订单级安全校验

原 RiskChecker，现接受 `PortfolioState` 而非 `AccountState`：

| 检查项 | 条件 | 说明 |
|--------|------|------|
| **account_type** (CRITICAL) | == "paper" | 永远不允许实盘 |
| **price_deviation** | \|limit - mid\| / mid < 5% | 价格偏离保护 |
| **margin_projection** | projected < 80% | 交易后保证金预估 |
| **order_value** | value / NLV < 10% | 单笔占比限制 |

`PortfolioState` 新增计算属性（取代 AccountState 的冗余字段）：
- `margin_utilization` = `margin_used / nlv`
- `cash_ratio` = `cash / nlv`

### Paper-Only 安全约束

系统通过**多层硬性校验**确保永远不会触发实盘交易：

1. `TradingAccountType` 枚举**仅定义 PAPER**（不存在 REAL 选项）
2. `TradingProvider.__init__()` 校验 account_type == PAPER
3. `SignalOrderBuilder` 硬编码 `account_type="paper"`
4. `OrderValidator._check_account_type()` **CRITICAL** 检查
5. 每次 `submit_order()` 前调用 `_validate_paper_account()`
6. IBKR 只连接 7497/4002 端口（Paper）；**禁止** 7496/4001（Live）
7. 账户 ID 前缀校验（Paper 账户以 "DU" 开头）

### ROLL 订单处理

Signal 的 `roll_to: Instrument` 字段描述目标合约。`SignalOrderBuilder` 生成两笔订单：

1. **Close Order**: BUY to close 当前合约（MARKET Order 确保成交）
2. **Open Order**: SELL to open 新合约（LIMIT Order 控制价格）

两笔订单共享 `decision_id`。`OrderManager.submit_roll_orders()` 保证顺序执行——close 失败则 open 自动取消。

### DailyLimits 日内限额

`DailyTradeTracker`（核心逻辑）+ `DailyLimitsGuard`（RiskGuard 包装）：

| 限制类型 | 默认值 | 说明 |
|---------|--------|------|
| `max_open_quantity_per_underlying` | 5 | 单标的每日开仓合约数 |
| `max_close_quantity_per_underlying` | 5 | 单标的每日平仓合约数 |
| `max_roll_quantity_per_underlying` | 5 | 单标的每日展期合约数 |
| `max_value_pct_per_underlying` | 5% | 单标的交易价值占比 |
| `max_total_value_pct` | 25% | 全组合每日交易价值占比 |

V2 变化：DailyLimits 从 TradingPipeline 内部（订单级阻断）移至 RiskGuard 链（信号级截断）。

## 风控配置

### 按策略覆盖

`RiskConfig` 支持按策略名覆盖基础限额：

```yaml
# config/trading/short_put_with_assignment.yaml
risk:
  max_margin_utilization: 0.50    # 比基础值 0.70 更保守
  max_positions: 10               # 比基础值 20 更少
  min_margin_reserve_pct: 0.30

# config/trading/spy_leaps_only_vol_target.yaml
risk:
  max_margin_utilization: 0.70
  max_positions: 20
  min_margin_reserve_pct: 0.10    # LEAPS 买方策略，保证金要求低
```

### 订单级风控配置

```yaml
# config/trading/risk.yaml (基础)
risk_limits:
  max_price_deviation_pct: 0.05
  max_order_value_pct: 0.10
  max_projected_margin_utilization: 0.80
  margin_rate_stock_option: 0.20  # 期权保证金估算比例
```

## CLI 命令

```bash
# V2 策略执行（唯一策略命令）
optrade strategy run -s leaps_v2_cash_sweep -S QQQ              # Dry-run
optrade strategy run -s leaps_v2_cash_sweep -S QQQ --execute    # 实际下单
optrade strategy run -s short_put_with_assignment -S SPY --push  # 执行 + 飞书通知

# 仪表盘
optrade dashboard -a paper -r 30

# 通知测试
optrade notify test
```

| 参数 | 说明 |
|------|------|
| `-s` / `--strategy` | 策略名（对应 BacktestStrategyRegistry 中注册的名称） |
| `-S` / `--symbol` | 标的符号（可多个） |
| `--execute` | 执行交易（默认 dry-run） |
| `--push` | 推送飞书通知 |
| `-v` / `--verbose` | 详细输出 |

## Python API

```python
from src.business.trading.signal_order_builder import SignalOrderBuilder
from src.business.trading.pipeline import TradingPipeline
from src.business.trading.live_executor import LiveStrategyExecutor

# 方式 1: 使用 LiveStrategyExecutor（推荐）
executor = LiveStrategyExecutor(
    strategy=strategy,
    risk_guards=[account_guard, daily_limits_guard],
    config=config,
)
result, plan = executor.plan()      # Phase A: 数据 + 信号 + 订单
records = executor.execute(plan)    # Phase B: 提交

# 方式 2: 手动组装
builder = SignalOrderBuilder()
orders = builder.build(signals, portfolio)  # Signal → OrderRequest

pipeline = TradingPipeline()
records = pipeline.execute_orders(orders, portfolio, dry_run=False)
```

## TradingProvider 接口

```python
class TradingProvider(ABC):
    """抽象交易接口 — 仅支持 Paper Trading"""

    def connect() -> None: ...
    def disconnect() -> None: ...
    def submit_order(order: OrderRequest) -> TradingResult: ...
    def query_order(broker_order_id: str) -> OrderQueryResult: ...
    def cancel_order(broker_order_id: str) -> CancelResult: ...
    def get_open_orders() -> list[OrderQueryResult]: ...
```

IBKR 实现要点：
- 优先使用 `con_id` 构建合约（最精确）
- 回退到 symbol/strike/expiry/option_type
- `qualifyContracts()` 验证合约有效性
- 提交后等待 5s 确认状态

## 开发指南

### 添加新 RiskGuard

1. 实现 `RiskGuard` 协议（`src/strategy/risk.py`）
2. `check(signals, portfolio, market) → list[Signal]`
3. 在 CLI `strategy.py` 中加入 risk_guards 列表

```python
class MyGuard:
    def check(self, signals, portfolio, market):
        return [s for s in signals if self._allowed(s, portfolio)]
```

### 添加新 TradingProvider

1. 继承 `TradingProvider` 抽象基类
2. **必须**在构造函数中调用 `super().__init__(account_type=TradingAccountType.PAPER)`
3. **必须**在每个交易操作前调用 `_validate_paper_account()`

## 遗留依赖

以下 V1 模块暂未删除，仍有下游引用：

| 模块 | 引用方 | 计划 |
|------|--------|------|
| `models/decision.py` (AccountState, TradingDecision) | 通知模块、回测 account_simulator | 回测 V2 完成后删除 |
| `src/business/screening/` | 回测 backtest_executor、dashboard | 回测 V2 完全迁移后删除 |
| `src/business/monitoring/` | 回测 backtest_executor、dashboard、attribution | 同上 |
| `src/business/strategy/` | 回测 signal_converter | 同上 |

## Changelog

| 日期 | 变更 |
|------|------|
| 2026-03 | **V2 重构**: SignalOrderBuilder 取代 LiveSignalConverter+OrderGenerator; DailyLimitsGuard 信号级截断; OrderValidator 取代 RiskChecker; LiveStrategyExecutor plan/execute 拆分; 删除 V1 CLI 命令 (screen/monitor/trade); 删除 decision/ 目录 |
| 2026-02 | ROLL 订单拆分为 close+open 原子对；DailyTradeTracker 日内限额；IBKRTradingProvider 端口/账户双重校验 |
| 2026-01 | 初始版本：四层架构、DecisionEngine、OrderManager、Paper-Only 约束 |
