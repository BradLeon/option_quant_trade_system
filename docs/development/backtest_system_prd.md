# 期权策略回测系统 - 产品需求文档 (PRD)

## 文档信息

| 项目 | 内容 |
|-----|------|
| 模块名称 | Backtest Module (策略回测系统) |
| 版本 | v1.0 |
| 创建日期 | 2026-01-29 |
| 状态 | 待实现 |

---

## 1. 背景与目标

### 1.1 背景

现有期权量化交易系统已完成：
- **数据层**: IBKR/Futu/Yahoo多源数据获取
- **引擎层**: Greeks计算、定价引擎、风险量化
- **业务层**: 开仓筛选系统、持仓监控系统、自动化交易

缺失的关键模块是**策略回测系统**，用于验证策略在历史数据上的表现。

### 1.2 目标

1. 构建独立的回测模块，验证SHORT_PUT/COVERED_CALL策略穿越牛熊的能力
2. **最大化代码复用**：回测逻辑与实盘逻辑共享同一套核心代码
3. **本地化存储**：使用本地4TB SSD + DuckDB，不依赖云数据库
4. **交互式可视化**：Plotly仪表板展示买卖点和期权详情

### 1.3 非目标

- 不构建实时交易系统（已有Trading模块）
- 不支持高频策略（专注于日级别期权策略）
- 不构建分布式系统（单机足够）

---

## 2. 资源需求

### 2.1 数据源

| 阶段 | 数据源 | 费用 | 说明 |
|-----|-------|------|-----|
| **开发测试** | ThetaData Free | $0 | 1年EOD数据, 20 req/min |
| **数据下载** | ThetaData Pro | $40×1-2月 | 批量下载10年历史数据 |
| **日常回测** | 本地DuckDB | $0 | 数据已下载，无API调用 |

**总预算: $40-80 一次性**

### 2.2 存储方案

```
┌─────────────────────────────────────────────────────────────┐
│  本地存储架构 (4TB 外接SSD)                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  /Volumes/TradingData/                                      │
│  ├── raw/                    # 原始下载数据                  │
│  │   └── thetadata/                                         │
│  │       ├── stocks/         # 股票EOD                      │
│  │       └── options/        # 期权EOD + Greeks             │
│  │                                                          │
│  ├── processed/              # 处理后的Parquet文件           │
│  │   ├── stock_daily.parquet                               │
│  │   ├── option_daily/       # 按标的分区                   │
│  │   │   ├── AAPL/                                         │
│  │   │   ├── MSFT/                                         │
│  │   │   └── ...                                           │
│  │   └── option_chain/       # 期权链快照                   │
│  │                                                          │
│  └── backtest.duckdb         # DuckDB数据库文件 (可选)       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**为什么选择 DuckDB + Parquet 而不是 Presto?**

| 方案 | DuckDB + Parquet | Presto |
|-----|------------------|--------|
| 部署 | 嵌入式，`import duckdb` | 需要JVM服务器集群 |
| 适用规模 | GB-TB (单机) | PB (分布式) |
| 查询性能 | 10年数据 < 10秒 | 需要集群资源 |
| 维护成本 | 零 | 高 |
| Python集成 | 原生支持 | 需要连接器 |

**结论**: 4TB期权数据属于DuckDB最佳适用范围，无需Presto。

### 2.3 存储容量估算

| 数据类型 | 单标的/年 | 10标的×10年 |
|---------|----------|-------------|
| 股票EOD | ~10KB | ~1MB |
| 期权EOD (全链) | ~500MB | ~50GB |
| 期权链快照 | ~100MB | ~10GB |
| **总计** | | **~60GB** |

4TB SSD容量充足，可扩展到100+标的。

---

## 3. 核心设计：数据与策略复用

### 3.1 数据层复用架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    统一数据接口层                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                      DataProvider (抽象接口)                     │
│                     src/data/providers/base.py                  │
│                              │                                  │
│          ┌──────────────────┼──────────────────┐               │
│          │                  │                  │               │
│          ▼                  ▼                  ▼               │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐     │
│   │   实盘模式   │   │   回测模式   │   │    混合模式      │     │
│   │             │   │             │   │                 │     │
│   │ IBKRProvider│   │ DuckDB      │   │ DuckDB历史 +    │     │
│   │ FutuProvider│   │ Provider    │   │ IBKR实时        │     │
│   │ YahooProvider│   │ (新增)      │   │                 │     │
│   └─────────────┘   └─────────────┘   └─────────────────┘     │
│                              │                                  │
│                              ▼                                  │
│                    统一数据模型 (复用)                           │
│                    src/data/models/                             │
│                    - OptionQuote                                │
│                    - OptionChain                                │
│                    - StockQuote                                 │
│                    - KlineBar                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**关键复用点**:

1. **数据模型100%复用**: `OptionQuote`, `OptionChain`, `StockQuote` 在实盘和回测中完全相同
2. **新增DuckDBProvider**: 实现相同的 `DataProvider` 接口，但从本地DuckDB读取
3. **透明切换**: 业务层代码无需修改，通过配置切换数据源

### 3.2 策略层复用架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    策略逻辑复用设计                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              核心策略逻辑 (100%复用)                      │   │
│  │                                                         │   │
│  │  src/business/screening/pipeline.py                     │   │
│  │  ├─ MarketFilter    # 市场环境筛选                       │   │
│  │  ├─ UnderlyingFilter # 标的筛选                         │   │
│  │  └─ ContractFilter   # 合约筛选                         │   │
│  │                                                         │   │
│  │  src/business/monitoring/pipeline.py                    │   │
│  │  ├─ CapitalMonitor   # 资本监控                         │   │
│  │  ├─ PortfolioMonitor # 组合监控                         │   │
│  │  └─ PositionMonitor  # 持仓监控                         │   │
│  │                                                         │   │
│  │  src/engine/bs/                                         │   │
│  │  ├─ greeks.py        # Greeks计算                       │   │
│  │  └─ probability.py   # 胜率计算                         │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│              ┌───────────────┼───────────────┐                 │
│              ▼                               ▼                 │
│  ┌─────────────────────┐         ┌─────────────────────┐      │
│  │      实盘执行        │         │      回测执行        │      │
│  │                     │         │                     │      │
│  │  TradingPipeline    │         │  BacktestExecutor   │      │
│  │  ├─ 调用Screening   │         │  ├─ 调用Screening   │      │
│  │  ├─ 调用Monitoring  │         │  ├─ 调用Monitoring  │      │
│  │  ├─ DecisionEngine  │         │  ├─ DecisionEngine  │      │
│  │  └─ IBKR下单        │         │  └─ 虚拟成交        │      │
│  │                     │         │                     │      │
│  └─────────────────────┘         └─────────────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**关键复用点**:

| 模块 | 实盘 | 回测 | 复用方式 |
|-----|------|------|---------|
| ScreeningPipeline | 实时数据 | 历史数据 | **100%复用**，仅切换DataProvider |
| MonitoringPipeline | 实时持仓 | 模拟持仓 | **100%复用**，传入不同持仓数据 |
| DecisionEngine | 生成订单 | 模拟成交 | **100%复用**，仅执行层不同 |
| Greeks计算 | calc_bs_greeks | calc_bs_greeks | **100%复用** |
| 配置文件 | screening/short_put.yaml | 同一文件 | **100%复用** |

### 3.3 代码复用具体实现

#### 3.3.1 统一数据提供者接口

```python
# 现有: src/data/providers/base.py
class DataProvider(ABC):
    @abstractmethod
    def get_stock_quote(self, symbol: str) -> StockQuote | None: ...

    @abstractmethod
    def get_option_chain(self, underlying: str, ...) -> OptionChain | None: ...

    @abstractmethod
    def get_history_kline(self, symbol: str, ...) -> list[KlineBar]: ...

# 新增: src/backtest/data/duckdb_provider.py
class DuckDBProvider(DataProvider):
    """从本地DuckDB读取历史数据，实现相同接口"""

    def __init__(self, db_path: str, as_of_date: date):
        self._conn = duckdb.connect(db_path)
        self._as_of_date = as_of_date  # 回测当前日期

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        # SQL查询指定日期的股票数据
        result = self._conn.execute("""
            SELECT * FROM stock_daily
            WHERE symbol = ? AND date = ?
        """, [symbol, self._as_of_date]).fetchone()

        return StockQuote(...) if result else None

    def get_option_chain(self, underlying: str, ...) -> OptionChain | None:
        # SQL查询指定日期的期权链
        ...
```

#### 3.3.2 回测执行器调用现有Pipeline

```python
# src/backtest/engine/backtest_executor.py
class BacktestExecutor:
    def _step_day(self, current_date: date):
        # 1. 创建当日的数据提供者 (指向历史数据)
        provider = DuckDBProvider(
            db_path=self._config.db_path,
            as_of_date=current_date
        )

        # 2. 复用现有ScreeningPipeline (代码完全相同)
        screening_pipeline = ScreeningPipeline(
            config=ScreeningConfig.from_yaml("config/screening/short_put.yaml"),
            provider=provider,  # 只是换了数据源
        )
        screen_result = screening_pipeline.run(
            symbols=self._config.symbols,
            market_type=MarketType.US,
            strategy_type=StrategyType.SHORT_PUT,
        )

        # 3. 复用现有MonitoringPipeline
        monitoring_pipeline = MonitoringPipeline(
            config=MonitoringConfig.from_yaml("config/monitoring/thresholds.yaml"),
        )
        monitor_result = monitoring_pipeline.run(
            positions=self._positions.to_list(),  # 模拟持仓
            capital_metrics=self._account.to_capital_metrics(),
        )

        # 4. 复用现有DecisionEngine
        decisions = self._decision_engine.process_batch(
            screen_result=screen_result,
            monitor_result=monitor_result,
            account_state=self._account.state,
        )

        # 5. 唯一不同: 模拟成交而非真实下单
        for decision in decisions:
            self._simulate_execution(decision, current_date)
```

#### 3.3.3 配置文件复用

```yaml
# config/screening/short_put.yaml
# 实盘和回测共用同一配置文件

strategy:
  type: SHORT_PUT

filters:
  dte:
    min: 7
    max: 45
  delta:
    min: 0.05
    max: 0.35
  iv_rank:
    min: 30

# 回测可以覆盖部分参数
# config/backtest/short_put_backtest.yaml
inherit: config/screening/short_put.yaml

overrides:
  # 回测时可以调整参数进行优化
  filters:
    delta:
      max: 0.30
```

---

## 4. 模块结构

```
src/backtest/
├── __init__.py
├── config/
│   ├── __init__.py
│   └── backtest_config.py          # 回测配置 (继承现有配置模式)
│
├── data/
│   ├── __init__.py
│   ├── thetadata_client.py         # ThetaData API封装
│   ├── data_downloader.py          # 批量下载工具
│   ├── duckdb_provider.py          # DuckDB数据提供者 (实现DataProvider接口)
│   └── schema.py                   # DuckDB表结构定义
│
├── engine/
│   ├── __init__.py
│   ├── backtest_executor.py        # 回测执行器 (调用现有Pipeline)
│   ├── trade_simulator.py          # 交易模拟器 (滑点/费用)
│   ├── account_simulator.py        # 账户模拟器
│   └── position_tracker.py         # 持仓追踪器
│
├── analysis/
│   ├── __init__.py
│   ├── metrics.py                  # 回测指标 (复用engine/portfolio/returns.py)
│   ├── trade_analyzer.py           # 交易分析
│   └── report_generator.py         # 报告生成
│
├── visualization/
│   ├── __init__.py
│   ├── dashboard.py                # Plotly仪表板
│   ├── equity_chart.py             # 权益曲线
│   ├── trade_timeline.py           # 买卖点时间轴
│   └── monthly_heatmap.py          # 月度热力图
│
└── cli/
    ├── __init__.py
    └── commands.py                 # CLI命令 (trade backtest)
```

---

## 5. 数据流程

### 5.1 数据下载流程 (一次性)

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: 数据下载 (ThetaData Pro, 1-2个月)                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  ThetaData API                                               │
│  - get_stock_eod(symbol, start, end)                        │
│  - get_option_eod(symbol, expiry, strike, type, start, end) │
│  - get_expirations(symbol, date)                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  DataDownloader                                              │
│  - 批量下载10标的 × 10年数据                                 │
│  - 处理rate limit (Free: 20/min, Pro: 无限)                 │
│  - 保存为Parquet文件                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  /Volumes/TradingData/processed/                            │
│  ├── stock_daily.parquet                                    │
│  └── option_daily/{AAPL,MSFT,...}/                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  DuckDB (可选，用于复杂查询)                                  │
│  CREATE TABLE stock_daily AS SELECT * FROM 'stock_daily.parquet';
│  CREATE TABLE option_daily AS SELECT * FROM 'option_daily/**/*.parquet';
└─────────────────────────────────────────────────────────────┘
```

### 5.2 回测执行流程

```
┌─────────────────────────────────────────────────────────────┐
│  回测配置 (YAML)                                             │
│  - 标的: [AAPL, MSFT, NVDA, ...]                            │
│  - 时间: 2015-01-01 ~ 2024-12-31                            │
│  - 策略: SHORT_PUT                                          │
│  - 初始资金: $100,000                                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  BacktestExecutor.run()                                      │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │           每个交易日循环                    │
        │                                           │
        │  1. 设置当前日期 → DuckDBProvider         │
        │                                           │
        │  2. 处理到期合约                           │
        │     - 自动行权/过期                        │
        │     - 计算盈亏                            │
        │                                           │
        │  3. 持仓监控 (复用MonitoringPipeline)      │
        │     - 止盈/止损信号                        │
        │     - 展期建议                            │
        │                                           │
        │  4. 开仓筛选 (复用ScreeningPipeline)       │
        │     - 市场过滤                            │
        │     - 标的过滤                            │
        │     - 合约过滤                            │
        │                                           │
        │  5. 执行决策 (复用DecisionEngine)          │
        │     - OPEN/CLOSE/ROLL                    │
        │                                           │
        │  6. 模拟成交                              │
        │     - 滑点模拟                            │
        │     - 费用计算                            │
        │                                           │
        │  7. 记录日终状态                          │
        │     - 权益                               │
        │     - 持仓                               │
        │     - 交易记录                            │
        └───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  BacktestResult                                              │
│  - 权益曲线 (DataFrame)                                      │
│  - 交易记录 (List[TradeRecord])                             │
│  - 统计指标 (BacktestMetrics)                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  BacktestDashboard (Plotly)                                  │
│  - 交互式HTML报告                                            │
│  - 买卖点悬停详情                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 可视化设计

### 6.1 仪表板布局

```
┌─────────────────────────────────────────────────────────────┐
│  回测报告: SHORT_PUT Strategy (2015-2024)                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────┐  ┌───────────────────────────┐  │
│  │  权益曲线             │  │  关键指标                  │  │
│  │  ▲ 开仓点 (绿)        │  │  年化收益: 18.5%          │  │
│  │  ▼ 平仓点 (红)        │  │  夏普率: 1.42             │  │
│  │  [悬停显示期权详情]    │  │  最大回撤: -15.3%         │  │
│  │                       │  │  胜率: 78.5%             │  │
│  └───────────────────────┘  │  盈亏比: 2.1              │  │
│                             └───────────────────────────┘  │
│  ┌───────────────────────┐  ┌───────────────────────────┐  │
│  │  回撤分析             │  │  月度收益热力图            │  │
│  │  [阴影区域显示回撤]    │  │      J F M A M J J A S O N D│
│  │                       │  │  2024 ■ ■ □ ■ ■ □ ...    │  │
│  │                       │  │  2023 ■ □ ■ ■ □ ■ ...    │  │
│  └───────────────────────┘  └───────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  交易时间轴                                          │   │
│  │  AAPL ━━●━━━━━━●━━━━●━━━━━━━━━━━━●━━━━━             │   │
│  │  MSFT ━━━━●━━━━━━━━━●━━━━━━●━━━━━━━━━━━             │   │
│  │  NVDA ━━━━━━●━━━━━━━━━━●━━━━━━━━━●━━━━              │   │
│  │       2015        2018        2021        2024      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  交易详情表                                          │   │
│  │  日期    | 标的 | 类型 | Strike | Expiry | Premium | PnL│
│  │  2024-01 | AAPL | PUT  | $170   | 03-15  | $3.50  | +$280│
│  │  ...                                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 悬停显示期权详情

```python
# 期权详情悬停模板
hover_template = """
<b>{symbol}</b><br>
━━━━━━━━━━━━━━━━<br>
<b>操作:</b> {direction} {option_type}<br>
<b>行权价:</b> ${strike:.2f}<br>
<b>到期日:</b> {expiry}<br>
<b>权利金:</b> ${premium:.2f}<br>
<b>数量:</b> {quantity} 张<br>
━━━━━━━━━━━━━━━━<br>
<b>Greeks:</b><br>
  Delta: {delta:.3f}<br>
  IV: {iv:.1%}<br>
━━━━━━━━━━━━━━━━<br>
<b>P&L:</b> ${pnl:+,.2f} ({pnl_pct:+.1%})
"""

# 示例显示:
# AAPL 240315P170
# ━━━━━━━━━━━━━━━━
# 操作: SELL PUT
# 行权价: $170.00
# 到期日: 2024-03-15
# 权利金: $3.50
# 数量: 10 张
# ━━━━━━━━━━━━━━━━
# Greeks:
#   Delta: -0.250
#   IV: 32.5%
# ━━━━━━━━━━━━━━━━
# P&L: +$2,800.00 (+80.0%)
```

---

## 7. 关键接口定义

### 7.1 DuckDBProvider (新增)

```python
# src/backtest/data/duckdb_provider.py

class DuckDBProvider(DataProvider):
    """
    从本地DuckDB/Parquet读取历史数据
    实现与IBKRProvider/FutuProvider相同的接口
    """

    def __init__(
        self,
        data_dir: str | Path,      # Parquet文件目录
        as_of_date: date,          # 回测当前日期
        use_duckdb: bool = True,   # 使用DuckDB还是直接读Parquet
    ):
        ...

    # ===== 实现DataProvider接口 =====

    def get_stock_quote(self, symbol: str) -> StockQuote | None:
        """获取指定日期的股票报价"""
        ...

    def get_option_chain(
        self,
        underlying: str,
        expiry_min_days: int = 7,
        expiry_max_days: int = 45,
    ) -> OptionChain | None:
        """获取指定日期的期权链"""
        ...

    def get_history_kline(
        self,
        symbol: str,
        ktype: KlineType,
        start_date: date,
        end_date: date,
    ) -> list[KlineBar]:
        """获取历史K线 (截止到as_of_date)"""
        ...

    # ===== 回测专用方法 =====

    def set_as_of_date(self, date: date) -> None:
        """更新当前回测日期"""
        self._as_of_date = date

    def get_trading_days(self, start: date, end: date) -> list[date]:
        """获取交易日列表"""
        ...
```

### 7.2 BacktestConfig

```python
# src/backtest/config/backtest_config.py

@dataclass
class BacktestConfig:
    """回测配置"""

    # 基本信息
    name: str
    description: str = ""

    # 时间范围
    start_date: date
    end_date: date

    # 标的池
    symbols: list[str]
    market: str = "US"

    # 策略配置 (复用现有配置文件)
    screening_config: str = "config/screening/short_put.yaml"
    monitoring_config: str = "config/monitoring/thresholds.yaml"
    strategy_type: StrategyType = StrategyType.SHORT_PUT

    # 资金配置
    initial_capital: float = 100_000
    max_margin_utilization: float = 0.70
    max_position_pct: float = 0.10

    # 执行配置
    slippage_pct: float = 0.001
    commission_per_contract: float = 0.65

    # 数据配置
    data_dir: str = "/Volumes/TradingData/processed"

    @classmethod
    def from_yaml(cls, path: str) -> "BacktestConfig":
        ...
```

### 7.3 BacktestResult

```python
# src/backtest/analysis/metrics.py

@dataclass
class TradeRecord:
    """单笔交易记录"""

    # 合约信息
    trade_id: str
    underlying: str
    option_type: Literal["call", "put"]
    strike: float
    expiry: date

    # 开仓
    entry_date: date
    entry_price: float
    entry_direction: Literal["buy", "sell"]
    quantity: int
    entry_reason: str  # 来自ScreeningPipeline

    # 平仓
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None  # 来自MonitoringPipeline

    # 盈亏
    realized_pnl: float | None = None
    realized_pnl_pct: float | None = None


@dataclass
class BacktestMetrics:
    """回测统计指标"""

    # 收益
    total_return: float
    annualized_return: float
    cagr: float

    # 风险
    max_drawdown: float
    max_drawdown_duration_days: int
    volatility: float

    # 风险调整
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    # 交易统计
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_holding_days: float

    # 期权特有
    avg_premium_collected: float
    assignment_rate: float
    roll_count: int


@dataclass
class BacktestResult:
    """完整回测结果"""

    config: BacktestConfig
    metrics: BacktestMetrics

    equity_curve: pd.DataFrame  # date, equity, drawdown
    trades: list[TradeRecord]

    monthly_returns: pd.DataFrame

    def save_html(self, path: str) -> None:
        """保存交互式HTML报告"""
        ...
```

---

## 8. 实现阶段

### Phase 1: 数据层 (1-2周)

**目标**: 完成数据下载和本地存储

**任务**:
1. `thetadata_client.py` - ThetaData API封装
2. `data_downloader.py` - 批量下载工具
3. `schema.py` - DuckDB表结构
4. `duckdb_provider.py` - 实现DataProvider接口

**验收标准**:
```python
# 能够从本地读取历史数据
provider = DuckDBProvider(data_dir="/Volumes/TradingData", as_of_date=date(2023, 1, 15))
quote = provider.get_stock_quote("AAPL")
chain = provider.get_option_chain("AAPL")
assert quote is not None
assert len(chain.options) > 0
```

**关键文件**:
- 参考: `src/data/providers/ibkr_provider.py`
- 新建: `src/backtest/data/duckdb_provider.py`

---

### Phase 2: 回测引擎 (2周)

**目标**: 完成核心回测执行器

**任务**:
1. `backtest_config.py` - 配置管理
2. `account_simulator.py` - 账户模拟
3. `position_tracker.py` - 持仓追踪
4. `trade_simulator.py` - 交易模拟
5. `backtest_executor.py` - 执行器 (集成现有Pipeline)

**验收标准**:
```python
# 能完成单标的回测
config = BacktestConfig.from_yaml("config/backtest/test.yaml")
executor = BacktestExecutor(config)
result = executor.run()
assert result.metrics.total_trades > 0
assert len(result.equity_curve) > 200  # 至少1年交易日
```

**关键文件**:
- 复用: `src/business/screening/pipeline.py`
- 复用: `src/business/monitoring/pipeline.py`
- 复用: `src/business/trading/decision/engine.py`
- 新建: `src/backtest/engine/backtest_executor.py`

---

### Phase 3: 策略集成测试 (1周)

**目标**: 验证与现有Pipeline的集成

**任务**:
1. 集成ScreeningPipeline
2. 集成MonitoringPipeline
3. 集成DecisionEngine
4. 端到端测试

**验收标准**:
```python
# 回测交易记录包含筛选/监控原因
for trade in result.trades:
    assert "三层筛选" in trade.entry_reason or "Delta" in trade.entry_reason
    if trade.exit_reason:
        assert "止盈" in trade.exit_reason or "止损" in trade.exit_reason or "到期" in trade.exit_reason
```

---

### Phase 4: 分析与可视化 (1-2周)

**目标**: 完成报告生成和可视化

**任务**:
1. `metrics.py` - 指标计算 (复用engine/portfolio/returns.py)
2. `dashboard.py` - Plotly仪表板
3. `equity_chart.py` - 权益曲线 + 买卖点
4. `trade_timeline.py` - 交易时间轴
5. CLI命令 `trade backtest`

**验收标准**:
```bash
# CLI执行回测并生成报告
trade backtest --config config/backtest/short_put.yaml --output reports/

# 生成的HTML包含所有图表
ls reports/
# backtest_short_put_2024.html
```

**关键文件**:
- 复用: `src/engine/portfolio/returns.py` (calc_sharpe_ratio, calc_max_drawdown)
- 新建: `src/backtest/visualization/dashboard.py`

---

### Phase 5: 优化与扩展 (1周)

**目标**: 性能优化和功能增强

**任务**:
1. 多标的并行回测
2. 参数优化框架
3. 基准对比 (SPY Buy&Hold)
4. Walk-forward验证

**验收标准**:
```python
# 10标的5年回测 < 5分钟
import time
start = time.time()
result = executor.run()
assert time.time() - start < 300
```

---

## 9. 时间估算

| 阶段 | 内容 | 时间 |
|-----|------|------|
| Phase 1 | 数据层 (ThetaData + DuckDB) | 1-2周 |
| Phase 2 | 回测引擎 | 2周 |
| Phase 3 | 策略集成测试 | 1周 |
| Phase 4 | 分析与可视化 | 1-2周 |
| Phase 5 | 优化与扩展 | 1周 |
| **总计** | | **6-8周** |

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| ThetaData Free限制 (20 req/min) | 下载慢 | 分批下载，先用少量数据开发 |
| 期权数据不完整 | 回测精度 | BS模型补充Greeks，数据验证 |
| 滑点估计不准 | 收益偏差 | 保守设置，与实盘对比 |
| DuckDB内存不足 | 查询失败 | 分区查询，使用Parquet直读 |

---

## 附录A: 现有代码参考

### 需要参考的文件

| 文件 | 用途 |
|-----|------|
| `src/data/providers/base.py` | DataProvider接口定义 |
| `src/data/providers/ibkr_provider.py` | Provider实现参考 |
| `src/data/models/option.py` | OptionQuote, OptionChain模型 |
| `src/business/screening/pipeline.py` | 开仓筛选逻辑 |
| `src/business/monitoring/pipeline.py` | 持仓监控逻辑 |
| `src/business/trading/decision/engine.py` | 决策引擎 |
| `src/engine/portfolio/returns.py` | 收益指标计算 |
| `src/business/config/screening_config.py` | 配置模式参考 |

### 需要新建的文件

| 文件 | 功能 |
|-----|------|
| `src/backtest/data/thetadata_client.py` | ThetaData API封装 |
| `src/backtest/data/data_downloader.py` | 批量下载工具 |
| `src/backtest/data/duckdb_provider.py` | DuckDB数据提供者 |
| `src/backtest/engine/backtest_executor.py` | 回测执行器 |
| `src/backtest/visualization/dashboard.py` | Plotly仪表板 |
| `src/backtest/cli/commands.py` | CLI命令 |

---

## 附录B: 参考资料

- [ThetaData Python API](https://github.com/ThetaData-API/thetadata-python)
- [ThetaData Options Data](https://www.thetadata.net/options-data)
- [DuckDB官方文档](https://duckdb.org/docs/)
- [DuckDB Python API](https://duckdb.org/docs/api/python/overview)
- [Plotly Python](https://plotly.com/python/)
