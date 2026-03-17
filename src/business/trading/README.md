# Trading — V2 交易执行层

实盘交易的核心模块，将 V2 策略信号转换为 IBKR 订单并执行。

## 数据流

```
Signal (策略输出)
  → RiskGuard chain (信号级风控过滤)
  → SignalOrderBuilder (Signal → OrderRequest, 一步转换)
  → OrderValidator (订单安全校验)
  → OrderManager → TradingProvider (IBKR 提交)
  → OrderRecord (执行结果)
```

## 模块结构

```
src/business/trading/
├── live_executor.py          # LiveStrategyExecutor — 实盘编排器
├── live_snapshot_builder.py  # IBKR → MarketSnapshot + PortfolioState
├── signal_order_builder.py   # Signal → OrderRequest 直接转换
├── pipeline.py               # TradingPipeline (IBKR 连接 + 下单)
├── daily_limits.py           # DailyTradeTracker 核心逻辑
├── order/
│   ├── order_validator.py    # 订单安全校验 (保证金/现金/持仓数)
│   ├── manager.py            # OrderManager (订单提交/状态跟踪)
│   └── store.py              # OrderStore (JSON 持久化)
├── risk/
│   └── daily_limits_guard.py # DailyLimitsGuard (信号级截断)
├── provider/
│   ├── base.py               # TradingProvider 协议
│   └── ibkr_trading.py       # IBKR 实现
├── models/
│   └── order.py              # OrderRequest, OrderRecord, OrderSide
└── config/
    ├── risk_config.py        # 风控配置
    └── order_config.py       # 订单配置
```

## 核心组件

### LiveStrategyExecutor — 两阶段执行

```python
class LiveStrategyExecutor:
    def run_once(self) -> LiveExecutionResult:
        plan = self.plan()        # Phase A: 数据 + 决策
        return self.execute(plan)  # Phase B: 下单

    def plan(self) -> ExecutionPlan:
        # 1. IBKRProvider 连接, 构建 MarketSnapshot + PortfolioState
        # 2. strategy.generate_signals(market, portfolio, dp)
        # 3. RiskGuard chain 过滤
        # 4. SignalOrderBuilder 转换
        # 5. 断开数据连接
        return ExecutionPlan(orders, roll_pairs, portfolio, signals)

    def execute(self, plan: ExecutionPlan) -> LiveExecutionResult:
        # 1. TradingProvider 连接
        # 2. OrderValidator 校验
        # 3. OrderManager 提交 (ROLL → submit_roll_orders)
        # 4. 断开交易连接
        return LiveExecutionResult(...)
```

两阶段设计原因：IBKR TWS 单 clientId 只允许一个连接，数据通道和交易通道必须分时复用。

### SignalOrderBuilder — 信号到订单

```python
class SignalOrderBuilder:
    def build(self, signals: list[Signal], portfolio: PortfolioState) -> list[OrderRequest]:
        # ENTRY  → 1 OrderRequest
        # EXIT   → 1 OrderRequest (从 portfolio 解析 position)
        # ROLL   → 2 OrderRequests (close + open)
```

一步完成 Signal → OrderRequest 转换，取代旧版的 Signal → TradingDecision → OrderRequest 两步转换。

### OrderValidator — 订单安全校验

接受 `PortfolioState`（取代旧版 `AccountState`），校验：
- 保证金使用率 < 阈值
- 现金比率 > 最低要求
- 持仓数量 < 上限
- 单笔订单金额合理性

### DailyLimitsGuard — 每日交易限额

实现 `RiskGuard` 协议，在信号级（而非订单级）执行截断：
- 每标的每日最大交易次数
- 每日最大总交易金额（占 NLV 比例）
- 按 SignalType 分类统计配额
- EXIT 信号始终放行（不阻断止损）

## ROLL 处理

Signal 的 `roll_to: Instrument` 字段描述展期目标。处理流程：

1. SignalOrderBuilder 将 ROLL Signal 拆为 close + open 两个 OrderRequest
2. OrderManager 的 `submit_roll_orders()` 确保原子化提交
3. `alert_type=AlertType.ROLL_DTE` 用于 PnL 归因

## 配置

风控参数支持策略级 YAML 配置和 CLI 覆盖：

```yaml
# config/trading/risk.yaml
max_margin_utilization: 0.60
max_positions: 10
min_cash_ratio: 0.10
daily_limits:
  max_trades_per_symbol: 2
  max_daily_value_pct: 0.15
```

```bash
uv run optrade strategy run -s momentum_mixed_v2 -S QQQ --max-margin 0.50 --max-positions 5
```
