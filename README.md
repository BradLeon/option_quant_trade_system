# Option Quant Trade System

期权量化策略交易系统 — 策略回测验证 → 实盘 Paper Trading 零修改部署。

一份策略代码，两条执行路径：

```
strategy.generate_signals(market, portfolio, dp) → list[Signal]
    ├── 回测: DuckDB (Parquet) → SignalConverter → TradeSimulator → 归因分析 → HTML 报告
    └── 实盘: IBKR TWS → SignalOrderBuilder → OrderValidator → IBKR Paper → 飞书通知
```

| 能力 | CLI | 说明 |
|------|-----|------|
| **策略回测** | `backtest run` | 基于 ThetaData 历史数据的期权策略验证，含 Greeks 归因与交互式报告 |
| **策略实盘** | `optrade strategy run` | V2 策略自动化 Paper Trading，两阶段执行 |
| **实时仪表盘** | `optrade dashboard` | Plotly 可视化面板，IBKR 账户数据 |
| **飞书通知** | `optrade notify` | 持仓报告 / 策略执行结果推送 |

---

# Part 1 — 如何使用

## 环境准备

### 安装

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 包管理器

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/BradLeon/option_quant_trade_system.git
cd option_quant_trade_system
uv sync
```

### 环境变量

创建 `.env` 文件：

```env
# IBKR TWS API
IBKR_HOST=127.0.0.1
IBKR_PORT=7497          # Paper: 7497, Live: 7496
IBKR_CLIENT_ID=1
IBKR_APP_TYPE=tws

# ThetaData（回测用，需运行 ThetaData Terminal）
# 默认连接 localhost:25503，无需配置环境变量

# 代理（Yahoo Finance 需要）
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```

### 外部依赖

| 服务 | 用途 | 启动方式 |
|------|------|----------|
| **ThetaData Terminal** | 回测历史数据（股票/期权 EOD） | 运行 ThetaData 桌面端，FREE 账户仅支持 2023-06-01 之后的数据 |
| **IBKR TWS / Gateway** | 实盘交易 + 实时数据 | 手动启动或 IBC 自动化（见下文） |
| **Yahoo Finance** | 宏观数据（VIX/TNX）、基本面 | 需代理 |

### IBC 自动化运行（可选）

IBKR TWS 需要 [IBC](https://github.com/IbcAlpha/IBC) 实现无人值守运行：

```bash
cd ~ && git clone https://github.com/IbcAlpha/IBC.git
cp ~/IBC/resources/config.ini ~/IBC/config.ini  # 编辑填入账户凭据
~/start_tws.sh paper
```

端口映射：Paper TWS=7497, Live TWS=7496, Paper Gateway=4002, Live Gateway=4001。

---

## 策略回测

回测系统基于 ThetaData 历史数据运行期权策略模拟，生成交互式 HTML 报告。

### 运行回测

```bash
# LEAPS V2 + CashSweep（推荐）
uv run backtest run -n "SPY_leaps_v2" -s 2016-06-01 -e 2026-03-01 \
  -S SPY -B SPY --skip-download --strategy-version leaps_v2_cash_sweep

# SMA LEAPS 策略
uv run backtest run -n "QQQ_sma_leaps" -s 2016-06-01 -e 2026-03-01 \
  -S QQQ -B SPY --skip-download --strategy-version sma_leaps

# 动量混合 V2
uv run backtest run -n "SPY_momentum_v2" -s 2016-06-01 -e 2026-03-01 \
  -S SPY -B SPY --skip-download --strategy-version momentum_mixed_v2

# Short Put（旧策略桥接）
uv run backtest run -n "GOOG_short_put" -s 2025-06-01 -e 2026-03-01 \
  -S GOOG -B SPY --skip-download --strategy-version short_put_with_assignment

# 自动下载缺失数据（需运行 ThetaData Terminal）
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG -B SPY
```

**CLI 参数**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-n, --name` | 回测名称 | 必填 |
| `-s, --start` | 开始日期 | 必填 |
| `-e, --end` | 结束日期 | 必填 |
| `-S, --symbols` | 标的代码（可多次指定） | 必填 |
| `-B, --benchmark` | 基准标的 | `SPY` |
| `-c, --capital` | 初始资金 | `1000000` |
| `-sv, --strategy-version` | V2 策略版本名 | `short_put_with_assignment` |
| `--skip-download` | 跳过数据下载检查 | 否 |
| `--no-report` | 不生成 HTML 报告 | 否 |
| `-v, --verbose` | 详细日志 | 否 |

### 可用策略版本

| 策略名 | `--strategy-version` | 说明 |
|--------|----------------------|------|
| SMA 股票 | `sma_stock` | SMA 均线择时 + 股票交易 |
| SMA LEAPS | `sma_leaps` | SMA 均线择时 + LEAPS 期权 |
| 动量混合 | `momentum_mixed` | 动量 + 波动率目标 + Stock/LEAPS 混合 |
| 动量混合 V2 | `momentum_mixed_v2` / `leaps_v2` | 动量 V2 + 改进风控 |
| LEAPS CashSweep | `leaps_v2_cash_sweep` | LEAPS V2 + 闲置现金自动买入货币基金 |
| LEAPS Only | `momentum_leaps_only` | 纯 LEAPS，不持有股票 |
| LEAPS Only CashSweep | `leaps_cash_sweep` | 纯 LEAPS + CashSweep |
| Short Put (接股) | `short_put_with_assignment` | 卖 Put，ITM 行权接股票 |
| Short Put (平仓) | `short_put_without_assignment` | 卖 Put，ITM 到期前平仓 |
| Bull Put Spread | `bull_put_spread` | 牛市看跌价差 |
| LEAPS 变体 | `leaps_vega_guard` / `leaps_stop_loss` / ... | A/B 测试变体 |

### Python API

```python
from datetime import date
from src.backtest import BacktestConfig, BacktestPipeline
from src.engine.models.enums import StrategyType

config = BacktestConfig(
    name="MULTI_STRAT",
    start_date=date(2025, 12, 1),
    end_date=date(2026, 2, 1),
    symbols=["GOOG", "SPY"],
    strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
    initial_capital=1_000_000,
)

result = BacktestPipeline(config).run(skip_data_check=True, generate_report=True)
print(f"Total Return: {result.metrics.total_return_pct:.2%}")
print(f"Sharpe Ratio: {result.metrics.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.metrics.max_drawdown:.2%}")
```

### 回测报告

自动生成的交互式 HTML 报告包含：

| 图表 | 说明 |
|------|------|
| Equity Curve | 净值曲线 + 交易标记 + SPY 基准对比 |
| Drawdown | 最大回撤可视化 |
| Monthly Returns | 月度收益热力图 |
| K-line Charts | 各标的价格走势 + 持仓区间 |
| Greeks Attribution | PnL 归因分解（Delta/Gamma/Theta/Vega/Residual） |
| Greeks Evolution | 组合 Greeks 时间序列 |
| Performance Stats | 关键绩效指标 (Sharpe, Sortino, Calmar, 胜率, 盈亏比) |

---

## 策略实盘 (Paper Trading)

将回测验证的 V2 策略零修改部署到 IBKR Paper Trading。

### 基本用法

```bash
# 查看可用策略
uv run optrade strategy list

# Dry-run（仅生成信号，不下单）
uv run optrade strategy run -s momentum_mixed_v2 -S QQQ

# 实际下单到 IBKR Paper
uv run optrade strategy run -s momentum_mixed_v2 -S QQQ --execute

# 下单 + 推送飞书通知
uv run optrade strategy run -s momentum_mixed_v2 -S QQQ --execute --push

# 多标的
uv run optrade strategy run -s sma_stock -S SPY -S AAPL --execute
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-s, --strategy-name` | 策略名称 | 必填 |
| `-S, --symbol` | 标的代码（可多次指定） | 必填 |
| `--execute` | 实际下单（默认 dry-run） | 否 |
| `--max-margin` | 最大保证金使用率 | `0.60` |
| `--max-positions` | 最大持仓数量 | `10` |
| `--push/--no-push` | 推送结果到飞书 | 不推送 |
| `-v, --verbose` | 详细日志 | 否 |

### Crontab 定时任务

```crontab
SHELL=/bin/zsh
PATH=/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin
PROJECT_DIR=/path/to/option_quant_trade_system
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897

# Dashboard 持仓报告: 北京时间 9:30, 16:30, 22:30, 周一到周五
30 9,16,22 * * 1-5 $PROJECT_DIR/scripts/ensure_tws.sh paper && cd $PROJECT_DIR && uv run optrade dashboard -a paper --push >> logs/dashboard.log 2>&1

# V2 策略实盘 (Paper): US 10:30 AM ET
# 夏令时=北京22:30 / 冬令时=北京23:30
30 22,23 * * 1-5 $PROJECT_DIR/scripts/ensure_tws.sh paper && cd $PROJECT_DIR && uv run optrade strategy run -s momentum_mixed_v2 -S QQQ --execute --push >> logs/paper_trade.log 2>&1
```

> 夏令时/冬令时覆盖：同一任务设两个时间点，策略检查持仓状态，重复执行不会重复建仓。

---

# Part 2 — 如何开发

## 交易员工作流

```bash
# 1. 在 src/strategy/versions/ 中编写策略
# 2. 注册到 src/strategy/registry.py
# 3. 回测验证
uv run backtest run -n "TEST" -s 2016-06-01 -e 2026-03-01 \
  -S SPY -B SPY --skip-download --strategy-version leaps_v2_cash_sweep

# 4. 查看报告
open reports/TEST_*.html

# 5. 满意后部署到 Paper Trading
uv run optrade strategy run -s leaps_v2_cash_sweep -S SPY --execute --push

# 6. 日常监控
uv run optrade dashboard -a paper --push
```

## 开发者导航

| 想做什么 | 去哪里 |
|----------|--------|
| 写新策略 | `src/strategy/versions/` 继承 `Strategy`，注册到 `registry.py` |
| 加信号计算器 | `src/strategy/signals/` 实现 `SignalComputer` 协议 |
| 加风控规则 | `src/strategy/risk_guards/` 实现 `RiskGuard` 协议 |
| 改回测引擎 | `src/backtest/engine/` |
| 改实盘下单 | `src/business/trading/` |
| 改定价公式 | `src/engine/pricing/` |
| 改数据源 | `src/data/providers/` |

## 测试

```bash
uv run pytest tests/engine/ -v         # 引擎层
uv run pytest tests/backtest/ -v       # 回测模块
uv run pytest tests/business/ -v       # 业务层

# 单个测试
uv run pytest tests/engine/test_pricing.py::test_short_put -v
```

## 代码质量

```bash
uv run black src tests
uv run ruff check src tests
uv run mypy src
```

## 项目依赖

- **核心**：pandas, numpy, scipy, duckdb, pyarrow
- **可视化**：plotly
- **数据源**：yfinance, thetadata, ib_async
- **CLI**：click
- **通知**：飞书 webhook

---

# Part 3 — 系统设计

## 1. 系统定位

一个面向个人交易员的期权量化系统，核心能力：

1. **策略开发**：编写期权交易策略（趋势跟踪、卖方收租、价差组合）
2. **策略验证**：在历史数据上回测，评估收益/风险/归因
3. **策略部署**：经验证的策略零修改部署到 IBKR Paper Trading
4. **风险管控**：信号级风控链 + 订单级安全校验

核心原则：**一份策略代码，两条执行路径**。

## 2. 模块职责划分

系统按「计算无状态 → 策略有逻辑 → 执行有副作用」分层：

```
┌──────────────────────────────────────────────────────────┐
│                    用户接口 (CLI)                          │
│  backtest run / optrade strategy run / optrade dashboard  │
└────────────┬───────────────────────────────┬──────────────┘
             │                               │
   ┌─────────▼──────────┐         ┌──────────▼─────────┐
   │   回测引擎 Engine    │         │  实盘执行 Executor   │
   │  (模拟撮合/归因)     │         │  (IBKR 下单/通知)    │
   └─────────┬──────────┘         └──────────┬─────────┘
             │                               │
             │    ┌──────────────────────┐    │
             └────▶   策略框架 Strategy   ◀───┘
                  │  (协议/实现/风控)     │
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │   计算引擎 Pricing    │
                  │  (BS/Greeks/指标)     │
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │   数据层 Data         │
                  │  (DuckDB/IBKR/Yahoo) │
                  └──────────────────────┘
```

### 各模块单一职责

| 模块 | 职责 | 不应该做的事 |
|------|------|-------------|
| **数据层** `data/` | 统一数据访问接口（行情/期权链/账户/宏观） | 不做计算、不做决策 |
| **计算引擎** `engine/` | BS 定价、Greeks、策略指标（TGR/ROC/胜率） | 不做交易决策、不访问数据源 |
| **策略框架** `strategy/` | 策略协议、策略实现、信号计算器、风控链 | 不做撮合、不下单、不访问券商 |
| **回测引擎** `backtest/` | 历史模拟撮合、仓位/账户/归因、报告 | 不包含策略实现 |
| **实盘执行** `business/` | IBKR 连接、订单构建/提交、通知推送 | 不包含策略实现 |

关键设计：**策略框架是独立模块**，不属于回测也不属于实盘。回测引擎和实盘执行器都「调用」策略，而非「包含」策略。

## 3. 数据流

### 3.1 回测路径

```
ThetaData (Parquet)
  → DuckDBProvider (PIT 查询, 防未来泄漏)
  → BacktestExecutor 每日循环:
      1. 更新持仓价格
      2. 处理到期期权
      3. 构建 MarketSnapshot + PortfolioState
      4. strategy.generate_signals(market, portfolio, dp) → list[Signal]
      5. RiskGuard chain 过滤 → list[Signal]
      6. SignalConverter: Signal → TradeSignal (回测引擎内部格式)
      7. TradeSimulator 模拟撮合 (滑点/佣金)
      8. AttributionCollector 采集归因快照
      9. 记录 DailySnapshot
  → BacktestMetrics + HTML 报告
```

### 3.2 实盘路径

```
IBKR TWS
  → LiveSnapshotBuilder 构建 MarketSnapshot + PortfolioState
  → strategy.generate_signals(market, portfolio, dp) → list[Signal]
  → RiskGuard chain 过滤 → list[Signal]
  → SignalOrderBuilder: Signal → OrderRequest (一步转换)
  → OrderValidator 安全校验
  → OrderManager → TradingProvider (IBKR Paper)
  → OrderRecord + 飞书通知
```

### 3.3 共享边界

两条路径共享的是「策略调用」这一步：

```
MarketSnapshot + PortfolioState
       │
       ▼
strategy.generate_signals()  ← 同一份代码
       │
       ▼
list[Signal]
       │
       ├── 回测: SignalConverter → TradeSimulator
       └── 实盘: SignalOrderBuilder → IBKR
```

## 4. 目录结构

```
src/
├── strategy/                     # 策略框架 — 协议/实现/风控，回测与实盘共用
│   ├── models.py                 #   核心模型: Instrument, Signal, MarketSnapshot, PortfolioState, AlertType
│   ├── protocol.py               #   StrategyProtocol (最小契约) + Strategy (模板基类)
│   ├── risk.py                   #   RiskGuard 协议
│   ├── execution_log.py          #   结构化执行日志
│   ├── cash_sweep.py             #   CashSweepMixin (闲置现金管理)
│   ├── leaps_selector.py         #   LeapsContractSelector (Delta 驱动选约)
│   ├── registry.py               #   StrategyRegistry — 策略名 → 工厂函数
│   ├── signals/                  #   可复用信号计算器
│   │   ├── sma.py                #     SmaComputer (均线择时)
│   │   └── momentum.py           #     MomentumVolTargetComputer (动量+波动率目标)
│   ├── risk_guards/              #   风控中间件实现
│   │   └── account_risk.py       #     AccountRiskGuard (保证金/现金/持仓数限制)
│   └── versions/                 #   策略实现
│       ├── sma_stock.py          #     SMA 择时 + 股票
│       ├── sma_leaps.py          #     SMA 择时 + LEAPS
│       ├── momentum_mixed.py     #     动量 + Stock/LEAPS 混合
│       ├── momentum_mixed_v2.py  #     动量 V2 + CashSweep
│       ├── short_options.py      #     卖方策略 (桥接旧 Pipeline)
│       ├── spread.py             #     Bull Put Spread
│       └── leaps_variants.py     #     LEAPS A/B 测试变体
│
├── engine/                       # 计算引擎 — 纯函数，无 I/O
│   ├── pricing/                  #   期权策略定价 (ShortPut, CoveredCall, Strangle, ...)
│   ├── bs/                       #   Black-Scholes 模型
│   ├── position/                 #   持仓级计算 (Greeks 聚合, 技术面, 波动率)
│   ├── portfolio/                #   组合级计算 (Greeks 汇总, 风险指标)
│   ├── account/                  #   账户级计算 (保证金, 仓位, 情绪)
│   └── models/                   #   数据模型 (BSParams, Position, StrategyType)
│
├── data/                         # 数据层 — 统一数据访问接口
│   ├── providers/                #   数据提供者 (Yahoo, IBKR, Futu)
│   ├── models/                   #   数据模型 (OptionContract, OptionQuote, Greeks)
│   └── currency/                 #   汇率转换
│
├── backtest/                     # 回测引擎 — 历史模拟
│   ├── engine/                   #   执行器 (BacktestExecutor, TradeSimulator, PositionManager)
│   │   ├── models.py             #   TradeSignal, MarketContext (V1 遗留模型，引擎内部使用)
│   │   └── signal_converter.py   #   Signal → TradeSignal 桥接 (回测引擎内部转换)
│   ├── data/                     #   回测数据 (DuckDB, ThetaData, 数据下载)
│   ├── attribution/              #   PnL 归因 (Observer 模式)
│   ├── analysis/                 #   绩效分析 (Sharpe, Sortino, Calmar)
│   ├── visualization/            #   Plotly HTML 报告
│   ├── optimization/             #   参数搜索, Walk-Forward
│   └── cli/                      #   backtest CLI
│
├── business/                     # 实盘业务层 — IBKR 交易
│   ├── trading/                  #   V2 交易执行
│   │   ├── live_executor.py      #     LiveStrategyExecutor (plan/execute 两阶段)
│   │   ├── signal_order_builder.py #   Signal → OrderRequest
│   │   ├── order/                #     OrderValidator, OrderManager, OrderStore
│   │   ├── risk/                 #     DailyLimitsGuard
│   │   └── provider/             #     TradingProvider (IBKR)
│   ├── cli/                      #   optrade CLI (strategy, dashboard, notify)
│   ├── notification/             #   飞书推送
│   └── dashboard/                #   实时仪表盘
│
├── screening/                    #   [V1 Legacy] 开仓筛选 Pipeline (回测旧路径依赖)
└── monitoring/                   #   [V1 Legacy] 持仓监控 Pipeline (回测旧路径依赖)
```

## 5. 核心协议

### 5.1 StrategyProtocol — 策略最小契约

```python
@runtime_checkable
class StrategyProtocol(Protocol):
    @property
    def name(self) -> str: ...

    def generate_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]: ...
```

### 5.2 Strategy — 模板基类

```python
class Strategy:
    def generate_signals(self, market, portfolio, dp) -> list[Signal]:
        self.on_day_start(market, portfolio)
        exits = self.compute_exit_signals(market, portfolio, dp)
        entries = self.compute_entry_signals(market, portfolio, dp)
        return exits + entries

    @property
    def requires_synthetic_data(self) -> bool:
        """回测需要合成 LEAPS 数据时返回 True"""
        return False
```

### 5.3 Signal — 策略唯一输出

```python
@dataclass
class Signal:
    type: SignalType              # ENTRY / EXIT / ROLL / REBALANCE
    instrument: Instrument        # 交易标的 (stock / option / combo)
    target_quantity: int          # 正=买, 负=卖
    reason: str                   # 人类可读原因
    alert_type: Optional[AlertType]  # 22 种结构化退出原因 (用于 PnL 归因)
    position_id: Optional[str]   # EXIT/ROLL 必填
    roll_to: Optional[Instrument]  # ROLL 目标合约
    quote_price: Optional[float] # 信号生成时的报价
    greeks: Optional[dict]       # Greeks 快照
```

### 5.4 RiskGuard — 风控中间件协议

```python
class RiskGuard(Protocol):
    def check(self, signals, portfolio, market) -> list[Signal]: ...
```

风控中间件按序执行，每层可过滤或截断信号。EXIT 信号始终通过（不截断止损）：

```
AccountRiskGuard     — 保证金/现金/持仓数量限制
DailyLimitsGuard     — 每日交易次数/金额截断
[自定义 Guard]       — 可扩展
```

### 5.5 StrategyRegistry — 策略注册表

```python
class StrategyRegistry:
    @classmethod
    def create(cls, name: str, **kwargs) -> StrategyProtocol: ...

    @classmethod
    def get_available_strategies(cls) -> list[str]: ...
```

### 5.6 AlertType — 退出原因枚举

Signal 的 `alert_type` 字段使用 `AlertType(str, Enum)` 管理退出原因，22 种结构化类型：

| 分类 | AlertType |
|------|-----------|
| 止盈 | `PROFIT_TARGET`, `DTE_PROFITABLE` |
| Delta/OTM | `DELTA_CHANGE`, `OTM_PCT`, `MONEYNESS` |
| 止损 | `STOP_LOSS`, `PNL_TARGET`, `GAMMA_RISK` |
| 时间退出 | `POSITION_TGR`, `TGR_LOW`, `ROC_LOW` |
| LEAPS | `ROLL_DTE`, `SMA_EXIT`, `VEGA_GUARD`, `VOLTGT_EXIT` |
| 组合风控 | `DELTA_EXPOSURE`, `MARGIN_UTILIZATION`, `CASH_RATIO` |

每个 AlertType 映射到 `CloseReasonType` 用于 PnL 归因统计。

## 6. PnL 归因分析

```
Daily PnL ≈ Delta × ΔS + ½ × Gamma × (ΔS)² + Theta × Δt + Vega × ΔIV + Residual
```

三种粒度：**Daily**（组合级）、**Per-Position-Daily**（持仓级）、**Per-Trade**（交易级累计）。

### 数据源

| 场景 | 数据 | 来源 |
|------|------|------|
| 回测 | Stock EOD, Option EOD + Greeks | ThetaData |
| 回测 | VIX / TNX | yfinance |
| 实盘 | 美股交易 + 期权 Greeks + 账户持仓 | IBKR TWS |
| 实盘 | 基本面、宏观 (VIX/TNX) | Yahoo Finance |

---

## License

MIT
