# Strategy — 策略框架

回测与实盘共用的策略框架：协议、实现、信号计算器、风控链、注册表。

## 核心设计

**一份策略代码，两种执行路径**：策略只需实现 `generate_signals()`，框架负责将信号路由到回测引擎或实盘交易通道。

```
策略代码
├── 回测: DuckDBProvider → generate_signals() → SignalConverter → TradeSimulator
└── 实盘: IBKRProvider → generate_signals() → SignalOrderBuilder → IBKR Paper
```

## 模块结构

```
src/strategy/
├── models.py           # 核心数据模型: Instrument, Signal, MarketSnapshot, PortfolioState, AlertType
├── protocol.py         # StrategyProtocol (最小契约) + Strategy (模板基类)
├── risk.py             # RiskGuard 协议
├── execution_log.py    # 结构化执行日志
├── cash_sweep.py       # CashSweepMixin (闲置现金 → 货币基金)
├── leaps_selector.py   # LeapsContractSelector (Delta 驱动选约)
├── registry.py         # StrategyRegistry — 策略名 → 工厂函数
├── signals/            # 可复用信号计算器
│   ├── sma.py          #   SmaComputer (均线择时)
│   └── momentum.py     #   MomentumVolTargetComputer (动量+波动率目标)
├── risk_guards/        # 风控中间件实现
│   └── account_risk.py #   AccountRiskGuard (保证金/现金/持仓数限制)
└── versions/           # 策略实现
    ├── sma_stock.py    #   SMA 择时 + 股票
    ├── sma_leaps.py    #   SMA 择时 + LEAPS
    ├── momentum_mixed.py     # 动量 + Stock/LEAPS 混合
    ├── momentum_mixed_v2.py  # 动量 V2 + CashSweep
    ├── short_options.py      # 卖方策略 (桥接旧 Pipeline)
    ├── spread.py             # Bull Put Spread
    └── leaps_variants.py     # LEAPS A/B 测试变体
```

## 核心模型 (models.py)

### Instrument — 金融工具标识

```python
@dataclass(frozen=True)
class Instrument:
    type: InstrumentType        # STOCK / OPTION / COMBO
    underlying: str             # "QQQ", "SPY"
    right: Optional[OptionRight]  # CALL / PUT
    strike: Optional[float]
    expiry: Optional[date]
    lot_size: int = 100
```

frozen=True 使其可作为 dict key / set member。消除了旧版 "stock proxy" hack — 股票是一等公民。

### Signal — 策略唯一输出

```python
@dataclass
class Signal:
    type: SignalType             # ENTRY / EXIT / ROLL / REBALANCE
    instrument: Instrument
    target_quantity: int         # 正=买, 负=卖
    reason: str
    position_id: Optional[str]  # EXIT/ROLL 必填
    roll_to: Optional[Instrument]  # ROLL 目标合约
    priority: int               # EXIT > ROLL > REBALANCE > ENTRY
    alert_type: Optional[AlertType]  # 22 种结构化退出原因
    quote_price: Optional[float]
    greeks: Optional[dict]
    metadata: dict
```

### AlertType — 退出原因枚举

22 种结构化类型，每个映射到 `CloseReasonType` 用于 PnL 归因。策略通过设置 `signal.alert_type = AlertType.PROFIT_TARGET` 标记退出原因，取代原来的 `metadata={"alert_type": "profit_target"}` 字符串方式。

### MarketSnapshot — 只读市场视图

```python
@dataclass
class MarketSnapshot:
    date: date
    prices: dict[str, float]     # symbol → close
    vix: Optional[float]
    risk_free_rate: Optional[float]
```

### PortfolioState — 只读组合快照

```python
@dataclass
class PortfolioState:
    date: date
    nlv: float                    # Net Liquidation Value
    cash: float
    margin_used: float
    positions: list[PositionView]

    @property
    def margin_utilization(self) -> float: ...
    @property
    def cash_ratio(self) -> float: ...
```

## 策略协议 (protocol.py)

### StrategyProtocol — 最小契约

```python
class StrategyProtocol(Protocol):
    def generate_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]: ...
```

### Strategy — 模板基类

```python
class Strategy:
    def generate_signals(self, market, portfolio, dp) -> list[Signal]:
        self.on_day_start(market, portfolio, dp)      # 初始化
        exits = self.compute_exit_signals(...)         # 退出信号
        entries = self.compute_entry_signals(...)      # 入场信号
        return exits + entries

    # 子类实现:
    def on_day_start(self, market, portfolio, dp): ...
    def compute_exit_signals(self, market, portfolio, dp) -> list[Signal]: ...
    def compute_entry_signals(self, market, portfolio, dp) -> list[Signal]: ...
```

## RiskGuard — 风控中间件 (risk.py)

```python
class RiskGuard(Protocol):
    def check(
        self, signals: list[Signal], portfolio: PortfolioState, market: MarketSnapshot
    ) -> list[Signal]: ...
```

多个 Guard 组成链式过滤，每层可过滤、截断或修改信号数量。EXIT 信号始终通过（不截断止损）。

## ExecutionLog — 结构化日志 (execution_log.py)

记录策略执行每一步的 trace，供 CLI 输出和飞书通知渲染：

```python
log = ExecutionLog(strategy_name="momentum_mixed_v2", symbols=["QQQ"])
log.step("exit_scan", "扫描 3 个持仓, 发现 1 个止盈信号")
log.step("entry_scan", "VIX=18.5, 动量=0.85, 生成 2 个入场信号")
log.step("risk_guard", "AccountRiskGuard: 3→2 (保证金限制截断 1 个)")
```

## CashSweepMixin — 闲置现金管理 (cash_sweep.py)

策略 mixin，自动将闲置现金买入货币基金 ETF (如 SGOV)，赎回时释放资金用于交易。DailyLimits 截断逻辑内置。
