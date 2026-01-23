# Automated Trading Module PRD

## Overview

构建自动化交易模块，作为 Screen（开仓筛选）和 Monitor（持仓监控）系统的下游，实现信号到订单的闭环。

**关键约束**: 仅支持 Paper Trading（模拟账户），硬性权限控制。

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Automated Trading Module                               │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐                    ┌──────────────────┐
│  Screen System   │                    │  Monitor System  │
│ (ScreeningResult)│                    │ (MonitorResult)  │
└────────┬─────────┘                    └────────┬─────────┘
         │ ContractOpportunity                   │ PositionSuggestion
         └───────────────┬───────────────────────┘
                         ▼
              ┌──────────────────────┐
              │   Decision Engine    │
              │  ┌────────────────┐  │
              │  │ SignalRouter   │  │
              │  │ AccountAnalyzer│  │
              │  │ PositionSizer  │  │
              │  │ ConflictResolver│ │
              │  └────────────────┘  │
              └──────────┬───────────┘
                         │ TradingDecision
                         ▼
              ┌──────────────────────┐
              │    Order Manager     │
              │  ┌────────────────┐  │
              │  │ OrderGenerator │  │
              │  │ RiskChecker    │  │
              │  │ OrderExecutor  │  │
              │  │ OrderStore     │  │
              │  └────────────────┘  │
              └──────────┬───────────┘
                         │ OrderRequest
                         ▼
              ┌──────────────────────┐
              │  Trading Interface   │
              │  ┌────────────────┐  │
              │  │ IBKR Trading   │  │
              │  │ Futu Trading   │  │
              │  └────────────────┘  │
              └──────────────────────┘
                         │
              ⚠️  PAPER TRADING ONLY
```

---

## 2. Core Modules

### 2.1 Decision Engine

**职责**: 信号接收 → 账户分析 → 仓位计算 → 冲突解决 → 决策输出

**核心组件**:
- `SignalRouter`: 路由 Screen/Monitor 信号
- `AccountStateAnalyzer`: 分析账户状态（现金、保证金、持仓）
- `PositionSizer`: Kelly 公式计算仓位大小
- `ConflictResolver`: 解决开仓/平仓信号冲突

**输入**:
- `ContractOpportunity` (from Screen.confirmed)
- `PositionSuggestion` (from Monitor.suggestions)
- `AccountState` (from AccountAggregator)

**输出**:
- `TradingDecision`: 包含决策类型、标的、数量、价格、优先级

### 2.2 Order Manager

**职责**: 订单生成 → 风控检验 → 下单执行 → 状态跟踪 → 持久化存储

**核心组件**:
- `OrderGenerator`: 从 Decision 生成 OrderRequest
- `RiskChecker`: 多层风控检验
- `OrderExecutor`: 调用 TradingProvider 执行
- `OrderStore`: 订单记录存储（JSON）

**输入**:
- `TradingDecision`

**输出**:
- `OrderRecord`: 包含完整订单生命周期和上下文

### 2.3 Trading Interface

**职责**: 提供统一的券商交易接口

**关键约束**:
- `TradingAccountType` 枚举**仅定义 PAPER**
- 构造函数校验 + 每次操作前校验
- IBKR 只连接 4002 端口（Paper）
- Futu 只使用 TrdEnv.SIMULATE

---

## 3. Data Models

### 3.1 Decision Models

```python
class DecisionType(Enum):
    OPEN = "open"      # 开仓
    CLOSE = "close"    # 平仓
    ROLL = "roll"      # 展期
    HEDGE = "hedge"    # 对冲
    ADJUST = "adjust"  # 调整
    HOLD = "hold"      # 持有

class DecisionSource(Enum):
    SCREEN_SIGNAL = "screen_signal"    # From Screen system
    MONITOR_ALERT = "monitor_alert"    # From Monitor system
    MANUAL = "manual"                  # Manual override

class DecisionPriority(Enum):
    CRITICAL = "critical"  # 止损/追保
    HIGH = "high"          # 分钟级
    NORMAL = "normal"      # 当日
    LOW = "low"            # 择时

@dataclass
class AccountState:
    broker: str
    account_type: str  # "paper" only
    total_equity: float
    cash_balance: float
    available_margin: float
    used_margin: float
    margin_utilization: float  # Maint Margin / NLV
    cash_ratio: float          # Cash / NLV
    gross_leverage: float      # Total Notional / NLV
    total_position_count: int
    option_position_count: int
    stock_position_count: int
    exposure_by_underlying: dict[str, float]
    timestamp: datetime

@dataclass
class PositionContext:
    position_id: str
    symbol: str
    underlying: str | None
    option_type: str | None  # "put" / "call"
    strike: float | None
    expiry: str | None
    dte: int | None
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    strategy_type: StrategyType | None
    related_position_ids: list[str]

@dataclass
class TradingDecision:
    decision_id: str
    decision_type: DecisionType
    source: DecisionSource
    priority: DecisionPriority
    symbol: str
    underlying: str | None
    option_type: str | None       # "put" / "call"
    strike: float | None
    expiry: str | None
    quantity: int                 # 正=买, 负=卖
    recommended_position_size: float | None
    limit_price: float | None
    price_type: str = "mid"       # "bid", "ask", "mid", "market"
    account_state: AccountState | None
    position_context: PositionContext | None
    reason: str
    trigger_alerts: list[str]
    confidence_score: float | None
    expected_impact: dict
    timestamp: datetime
    is_approved: bool
    approval_notes: str
```

### 3.2 Order Models

```python
class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class OrderStatus(Enum):
    PENDING_VALIDATION = "pending_validation"
    VALIDATION_FAILED = "validation_failed"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ERROR = "error"

class AssetClass(Enum):
    STOCK = "stock"
    OPTION = "option"

@dataclass
class OrderRequest:
    order_id: str
    decision_id: str
    symbol: str
    asset_class: AssetClass
    underlying: str | None
    option_type: str | None
    strike: float | None
    expiry: str | None
    trading_class: str | None
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: float | None
    stop_price: float | None
    time_in_force: str = "DAY"
    broker: str
    account_type: str = "paper"  # 必须是 paper
    status: OrderStatus
    validation_errors: list[str]
    created_at: datetime
    updated_at: datetime
    context: dict

@dataclass
class OrderFill:
    fill_id: str
    order_id: str
    filled_quantity: int
    fill_price: float
    commission: float
    fill_time: datetime
    broker_fill_id: str | None
    broker_order_id: str | None

@dataclass
class OrderRecord:
    order: OrderRequest
    fills: list[OrderFill]
    total_filled_quantity: int
    average_fill_price: float | None
    total_commission: float
    status_history: list[tuple[OrderStatus, datetime, str]]
    broker_order_id: str | None
    broker_status: str | None
    is_complete: bool
    completion_time: datetime | None
    error_message: str | None
    retry_count: int

@dataclass
class RiskCheckResult:
    passed: bool
    checks: list[dict]
    failed_checks: list[str]
    warnings: list[str]
    projected_margin_utilization: float | None
    projected_cash_ratio: float | None
    projected_gross_leverage: float | None
    timestamp: datetime
```

### 3.3 Trading Models

```python
class TradingAccountType(Enum):
    PAPER = "paper"
    # REAL = "real"  # 故意不定义

@dataclass
class TradingResult:
    success: bool
    internal_order_id: str | None
    broker_order_id: str | None
    error_code: str | None
    error_message: str | None
    executed_quantity: int
    executed_price: float | None
    commission: float
    timestamp: datetime

@dataclass
class OrderQueryResult:
    found: bool
    broker_order_id: str | None
    status: str | None
    filled_quantity: int
    remaining_quantity: int
    average_price: float | None
    last_updated: datetime | None

@dataclass
class CancelResult:
    success: bool
    broker_order_id: str | None
    error_message: str | None
    timestamp: datetime
```

---

## 4. Interface Definitions

### 4.1 Decision Engine Interface

```python
class DecisionEngine:
    """Decision Engine - transforms signals into trading decisions."""

    def __init__(
        self,
        config: DecisionConfig | None = None,
        account_analyzer: AccountStateAnalyzer | None = None,
        position_sizer: PositionSizer | None = None,
        conflict_resolver: ConflictResolver | None = None,
    ) -> None: ...

    def process_screen_signal(
        self,
        opportunity: ContractOpportunity,
        account_state: AccountState,
    ) -> TradingDecision | None:
        """Process opening signal from Screen system."""
        ...

    def process_monitor_signal(
        self,
        suggestion: PositionSuggestion,
        account_state: AccountState,
    ) -> TradingDecision | None:
        """Process adjustment signal from Monitor system."""
        ...

    def process_batch(
        self,
        screen_result: ScreeningResult | None,
        monitor_result: MonitorResult | None,
        account_state: AccountState,
    ) -> list[TradingDecision]:
        """Process batch of signals from both systems."""
        ...

    def get_account_state(self) -> AccountState:
        """Fetch current account state from providers."""
        ...


class AccountStateAnalyzer(ABC):
    @abstractmethod
    def can_open_position(
        self, account_state: AccountState, required_margin: float
    ) -> tuple[bool, str]: ...

    @abstractmethod
    def get_available_capital_for_opening(
        self, account_state: AccountState
    ) -> float: ...


class PositionSizer(ABC):
    @abstractmethod
    def calculate_size(
        self,
        opportunity: ContractOpportunity,
        account_state: AccountState,
        max_allocation_pct: float = 0.05,
    ) -> int: ...


class ConflictResolver(ABC):
    @abstractmethod
    def resolve(
        self,
        open_decisions: list[TradingDecision],
        close_decisions: list[TradingDecision],
        account_state: AccountState,
    ) -> list[TradingDecision]: ...
```

### 4.2 Order Manager Interface

```python
class OrderManager:
    """Order Manager - handles order lifecycle from decision to execution."""

    def __init__(
        self,
        config: OrderConfig | None = None,
        risk_checker: RiskChecker | None = None,
        order_store: OrderStore | None = None,
    ) -> None: ...

    def create_order(self, decision: TradingDecision) -> OrderRequest: ...

    def validate_order(self, order: OrderRequest) -> RiskCheckResult: ...

    def submit_order(self, order: OrderRequest) -> OrderRecord: ...

    def cancel_order(self, order_id: str) -> bool: ...

    def get_order_status(self, order_id: str) -> OrderRecord | None: ...

    def get_open_orders(self) -> list[OrderRecord]: ...

    def get_orders_by_decision(self, decision_id: str) -> list[OrderRecord]: ...


class RiskChecker(ABC):
    @abstractmethod
    def check(self, order: OrderRequest) -> RiskCheckResult: ...


class OrderStore(ABC):
    @abstractmethod
    def save(self, record: OrderRecord) -> None: ...

    @abstractmethod
    def get(self, order_id: str) -> OrderRecord | None: ...

    @abstractmethod
    def get_by_status(self, status: OrderStatus) -> list[OrderRecord]: ...

    @abstractmethod
    def get_recent(self, days: int = 7) -> list[OrderRecord]: ...
```

### 4.3 Trading Provider Interface

```python
class TradingProviderError(Exception):
    """Base exception for trading provider errors."""
    pass


class AccountTypeError(TradingProviderError):
    """Raised when attempting to trade on non-paper account."""
    pass


class TradingProvider(ABC):
    """Abstract base class for trading providers.

    CRITICAL: This interface ONLY supports PAPER trading accounts.
    """

    def __init__(
        self,
        account_type: TradingAccountType = TradingAccountType.PAPER,
    ) -> None:
        if account_type != TradingAccountType.PAPER:
            raise AccountTypeError(
                "REAL trading is not supported. "
                "This system only supports PAPER trading accounts."
            )
        self._account_type = account_type

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    def account_type(self) -> TradingAccountType:
        return self._account_type

    def _validate_paper_account(self) -> None:
        if self._account_type != TradingAccountType.PAPER:
            raise AccountTypeError("Trading only allowed on PAPER accounts")

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> TradingResult: ...

    @abstractmethod
    def query_order(self, broker_order_id: str) -> OrderQueryResult: ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> CancelResult: ...

    @abstractmethod
    def get_open_orders(self) -> list[OrderQueryResult]: ...
```

---

## 5. Risk Control (Multi-Layer)

### Layer 1: Account-Level Gates (Decision Engine)
| 指标 | 阈值 | 说明 |
|------|------|------|
| margin_utilization | < 70% | 可开新仓 |
| cash_ratio | > 10% | 流动性缓冲 |
| gross_leverage | < 4.0x | 敞口限制 |
| stress_test_loss | < 20% | 尾部风险 |

### Layer 2: Position-Level Limits (Decision Engine)
| 限制 | 值 | 说明 |
|------|------|------|
| max_contracts_per_underlying | 10 | 单标的合约数 |
| max_notional_pct | 5% | 单标的名义价值占比 |
| max_option_positions | 20 | 期权持仓总数 |
| no duplicate position | - | 同一 strike/expiry 不重复开仓 |

### Layer 3: Order-Level Validation (Order Manager)
| 检查项 | 阈值 | 说明 |
|------|------|------|
| Margin Check | projected < 80% | 交易后保证金 |
| Price Check | \|limit - mid\| / mid < 5% | 价格偏离 |
| Quantity Check | ≤ max_contracts | 数量限制 |
| Account Check | account_type == "paper" | **CRITICAL** |

### Layer 4: Broker-Level Safeguards (Trading Provider)
| 券商 | 控制点 | 说明 |
|------|------|------|
| IBKR | Port 4002 only | Paper trading 端口 |
| IBKR | DU* account prefix | Paper 账户前缀校验 |
| Futu | TrdEnv.SIMULATE only | 模拟环境 |

---

## 6. Workflows

### 6.1 Opening Signal Processing Flow

```
Screen.confirmed: List[ContractOpportunity]
    │
    ▼
DecisionEngine.process_screen_signal()
    │
    ├── AccountState Check
    │   ├── margin_utilization < 70%?
    │   ├── cash_ratio > 10%?
    │   └── no existing position in same underlying?
    │   ❌ Fail → Skip opportunity
    │
    ├── Position Sizing (Kelly-based)
    │   ├── kelly = opportunity.kelly_fraction
    │   ├── position = kelly × 0.25 (fractional)
    │   ├── cap by max_contracts_per_underlying
    │   └── cap by available_margin
    │
    ├── Conflict Check
    │   └── Check pending close decisions on same underlying
    │
    └── Generate TradingDecision
        ├── decision_type = OPEN
        ├── source = SCREEN_SIGNAL
        ├── priority = NORMAL
        └── quantity = calculated (negative for sell)
    │
    ▼
OrderManager.create_order()
    │
    ├── Map symbol to broker format
    ├── Set order_type = LIMIT
    ├── Set limit_price = opportunity.mid_price
    └── Set time_in_force = DAY
    │
    ▼
OrderManager.validate_order()
    │
    ├── Margin Check: projected_margin_util < 80%?
    ├── Position Limit: contracts < MAX?
    ├── Price Check: |limit - mid| / mid < 5%?
    └── Account Check: account_type == "paper"?
    │
    ❌ Any fail → OrderStatus.VALIDATION_FAILED
    ✓ All pass → OrderStatus.APPROVED
    │
    ▼
OrderManager.submit_order()
    │
    └── TradingProvider.submit_order()
        │
        ├── _validate_paper_account()
        ├── Build broker-specific order
        └── Submit to broker API
    │
    ▼
Track fills → Update OrderRecord → Complete
    │
    └── Push notification to Feishu
```

### 6.2 Risk Adjustment Signal Processing Flow

```
Monitor.suggestions: List[PositionSuggestion]
    │
    ├── Sort by urgency: IMMEDIATE > SOON > MONITOR
    │
    ▼
DecisionEngine.process_monitor_signal()
    │
    ├── Map ActionType to DecisionType
    │   ├── CLOSE → CLOSE
    │   ├── REDUCE → ADJUST (partial close)
    │   ├── ROLL → CLOSE + OPEN (two decisions)
    │   ├── HEDGE → OPEN (hedge position)
    │   └── TAKE_PROFIT → CLOSE
    │
    ├── Lookup Position Context
    │   ├── Get current position from AccountAggregator
    │   ├── Verify position still exists
    │   └── Get current market price
    │
    ├── Calculate Action Parameters
    │   ├── CLOSE: quantity = -position.quantity
    │   ├── REDUCE: quantity = -position.quantity × reduction_pct
    │   └── ROLL: generate two decisions
    │
    └── Generate TradingDecision
        ├── decision_type = mapped_type
        ├── source = MONITOR_ALERT
        ├── priority = urgency_to_priority(suggestion.urgency)
        └── trigger_alerts = suggestion.trigger_alerts
    │
    ▼
ConflictResolver.resolve()
    │
    ├── CLOSE decisions execute before OPEN
    ├── Same underlying: only one action
    └── Margin release: close first to free margin
    │
    ▼
OrderManager (same flow as opening signal)
```

### 6.3 Order Execution Flow

```
OrderManager.submit_order(order_request)
    │
    ├── Validate order.status == APPROVED
    └── Select TradingProvider based on order.broker
    │
    ▼
TradingProvider.submit_order(order)
    │
    ├── _validate_paper_account()
    │   ❌ Raises AccountTypeError if not PAPER
    │
    ├── Build broker-specific order
    │   ├── IBKR: ib_async Order object
    │   └── Futu: OpenSecTradeContext.place_order()
    │
    └── Submit to broker API
    │
    ▼
Handle Response
    │
    ├── Success:
    │   ├── Get broker_order_id
    │   ├── OrderStatus → SUBMITTED
    │   └── Store in OrderRecord
    │
    └── Failure:
        ├── OrderStatus → REJECTED
        ├── Store error_message
        └── Log for review
    │
    ▼
Execution Monitoring (polling)
    │
    ├── Query broker for order status
    │   TradingProvider.query_order(broker_order_id)
    │
    ├── Handle fills:
    │   ├── Create OrderFill record
    │   ├── Update total_filled_quantity
    │   └── Calculate average_fill_price
    │
    └── Terminal states:
        ├── FILLED → Complete + Notify
        ├── PARTIAL_FILLED → Continue monitoring
        ├── CANCELLED → Log + Notify
        └── EXPIRED → Log + Optional resubmit
```

---

## 7. CLI Commands

```bash
# Trading module commands
optrade trade status              # Show trading system status
optrade trade process             # Process signals, generate decisions (dry-run)
optrade trade process --auto-execute  # Process and auto-execute (for crontab)
optrade trade execute -d <id> --confirm  # Execute specific decision
optrade trade execute --all-pending --confirm  # Execute all pending

# Order management
optrade trade orders list         # List orders (default: open)
optrade trade orders list --status filled --days 30
optrade trade orders cancel <order_id> --confirm
```

### CLI Implementation

```python
@click.group()
def trade() -> None:
    """交易模块 - 信号处理与订单执行

    ⚠️  仅支持模拟账户 (Paper Trading)
    """
    pass


@trade.command()
@click.option("--verbose", "-v", is_flag=True)
def status(verbose: bool) -> None:
    """显示交易系统状态"""
    pass


@trade.command()
@click.option("--source", type=click.Choice(["screen", "monitor", "both"]), default="both")
@click.option("--dry-run", is_flag=True, default=True)
@click.option("--auto-execute", is_flag=True, help="自动执行（适合 crontab）")
@click.option("--market", "-m", type=click.Choice(["us", "hk", "all"]), default="all")
def process(source: str, dry_run: bool, auto_execute: bool, market: str) -> None:
    """处理交易信号并生成决策"""
    pass


@trade.command()
@click.option("--decision-id", "-d", help="执行指定决策")
@click.option("--all-pending", is_flag=True)
@click.option("--confirm", is_flag=True, required=True)
def execute(decision_id: str | None, all_pending: bool, confirm: bool) -> None:
    """执行交易决策"""
    pass


@trade.group()
def orders() -> None:
    """订单管理"""
    pass


@orders.command("list")
@click.option("--status", type=click.Choice(["open", "filled", "cancelled", "all"]), default="open")
@click.option("--days", type=int, default=7)
def list_orders(status: str, days: int) -> None:
    """列出订单"""
    pass


@orders.command()
@click.argument("order_id")
@click.option("--confirm", is_flag=True, required=True)
def cancel(order_id: str, confirm: bool) -> None:
    """取消订单"""
    pass
```

---

## 8. File Structure

```
src/business/trading/
├── __init__.py
│
├── config/
│   ├── __init__.py
│   ├── decision_config.py      # Decision engine configuration
│   ├── order_config.py         # Order manager configuration
│   ├── risk_config.py          # Risk limits configuration
│   └── execution_config.py     # Execution mode configuration
│
├── models/
│   ├── __init__.py
│   ├── decision.py             # TradingDecision, AccountState, PositionContext
│   ├── order.py                # OrderRequest, OrderRecord, OrderFill, RiskCheckResult
│   └── trading.py              # TradingResult, TradingAccountType, OrderQueryResult
│
├── decision/
│   ├── __init__.py
│   ├── engine.py               # DecisionEngine main class
│   ├── account_analyzer.py     # AccountStateAnalyzer
│   ├── position_sizer.py       # PositionSizer (Kelly-based)
│   └── conflict_resolver.py    # ConflictResolver
│
├── order/
│   ├── __init__.py
│   ├── manager.py              # OrderManager main class
│   ├── generator.py            # Order generation from decisions
│   ├── risk_checker.py         # RiskChecker
│   └── store.py                # OrderStore (JSON persistence)
│
├── provider/
│   ├── __init__.py
│   ├── base.py                 # TradingProvider abstract base
│   ├── ibkr_trading.py         # IBKRTradingProvider (Paper Only)
│   └── futu_trading.py         # FutuTradingProvider (Paper Only)
│
└── pipeline.py                 # TradingPipeline (orchestration)

src/business/cli/commands/
└── trade.py                    # CLI commands for trading

config/trading/
├── decision.yaml               # Decision engine settings
├── order.yaml                  # Order manager settings
├── risk.yaml                   # Risk limits
└── execution.yaml              # Execution mode settings
```

---

## 9. Configuration Files

### 9.1 Risk Configuration

```yaml
# config/trading/risk.yaml
risk_limits:
  # Account-level limits
  max_margin_utilization: 0.70  # 70%
  min_cash_ratio: 0.10          # 10%
  max_gross_leverage: 4.0       # 4x
  max_stress_test_loss: 0.20    # 20%

  # Position-level limits
  max_contracts_per_underlying: 10
  max_notional_pct_per_underlying: 0.05  # 5% of NLV
  max_total_option_positions: 20
  max_concentration_pct: 0.20   # 20% in single underlying

  # Order-level limits
  max_price_deviation_pct: 0.05  # 5% from mid
  max_order_value_pct: 0.10      # 10% of NLV per order

  # Kelly fraction scaling
  kelly_fraction: 0.25  # Use 1/4 Kelly

  # Emergency thresholds (auto-close triggers)
  emergency_margin_utilization: 0.85  # 85%
  emergency_cash_ratio: 0.05          # 5%
```

### 9.2 Execution Configuration

```yaml
# config/trading/execution.yaml
execution:
  mode: "manual"  # "manual" | "auto"

  manual:
    require_confirm: true  # CLI requires --confirm

  auto:
    enabled: false  # Default off
    require_explicit_flag: true  # Needs --auto-execute to enable

  # Always require confirmation for these
  always_confirm:
    - decision_type: "CLOSE"
      priority: "CRITICAL"  # Except stop loss
```

---

## 10. Critical Files to Reference

| 文件 | 用途 |
|------|------|
| `src/business/screening/models.py` | ContractOpportunity 定义 |
| `src/business/monitoring/suggestions.py` | PositionSuggestion, ActionType 定义 |
| `src/business/monitoring/models.py` | Alert, MonitorResult 定义 |
| `src/data/providers/base.py` | Provider 接口模式参考 |
| `src/data/providers/ibkr_provider.py` | IBKR API 集成参考 |
| `src/data/providers/futu_provider.py` | Futu API 集成参考 |
| `src/data/providers/account_aggregator.py` | 账户聚合参考 |
| `src/business/cli/commands/screen.py` | CLI 命令模式参考 |
| `src/business/notification/dispatcher.py` | 飞书通知集成参考 |

---

## 11. Implementation Phases

### Phase 1: Foundation (Models + Config)
**目标**: 建立数据模型和配置基础

**任务**:
1. 创建 `src/business/trading/` 目录结构
2. 实现所有数据模型 (`models/*.py`)
3. 实现配置类 (`config/*.py`)
4. 创建配置文件 (`config/trading/*.yaml`)

**产出**:
- 完整的类型定义
- 配置加载机制

### Phase 2: Trading Interface
**目标**: 实现券商交易接口

**任务**:
1. 实现 `TradingProvider` 抽象基类
2. 实现 `IBKRTradingProvider` (Paper Only)
   - 连接 4002 端口
   - 账户类型校验
   - 订单提交/查询/取消
3. 实现 `FutuTradingProvider` (Paper Only)
   - TrdEnv.SIMULATE
   - 订单提交/查询/取消
4. 编写单元测试

**产出**:
- 可独立测试的交易接口
- 多层账户类型校验

### Phase 3: Order Manager
**目标**: 实现订单管理

**任务**:
1. 实现 `OrderStore` (JSON 文件存储)
2. 实现 `RiskChecker` (多层风控)
3. 实现 `OrderManager`
4. 集成飞书通知
5. 编写集成测试

**产出**:
- 完整的订单生命周期管理
- 持久化存储
- 风控检验

### Phase 4: Decision Engine
**目标**: 实现决策引擎

**任务**:
1. 实现 `AccountStateAnalyzer`
2. 实现 `PositionSizer` (Kelly-based)
3. 实现 `ConflictResolver`
4. 实现 `DecisionEngine`
5. 编写集成测试

**产出**:
- 信号到决策的转换
- 账户状态分析
- 仓位计算
- 冲突解决

### Phase 5: Integration
**目标**: 系统集成

**任务**:
1. 实现 `TradingPipeline` (编排层)
2. 实现 CLI 命令 (`trade.py`)
3. 端到端测试
4. 文档编写

**产出**:
- 可用的 CLI 命令
- 完整的使用文档

---

## 12. User Decisions Summary

| 问题 | 决策 |
|------|------|
| 订单存储 | **JSON 文件** - 简单可靠，易于调试 |
| 通知集成 | **复用飞书通知** - 订单提交/成交/失败时推送 |
| 回测模式 | **暂不需要** - 专注 Paper Trading |
| 执行流程 | **可配置** - 支持手动确认和全自动两种模式 |
