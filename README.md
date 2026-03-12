# Option Quant Trade System

期权量化策略交易系统 — 集成开仓筛选、持仓监控、自动交易与策略回测。

## 功能概览

| 模块 | 说明 |
|------|------|
| **开仓筛选** (`optrade screen`) | 三层筛选（技术面 + 基本面 + 期权指标），支持 US/HK 市场 |
| **持仓监控** (`optrade monitor`) | 组合级 / 持仓级 / 资金级三层风险预警 |
| **实时仪表盘** (`optrade dashboard`) | Plotly 可视化面板，支持自动刷新 |
| **自动交易** (`optrade trade`) | 筛选/监控信号 → 决策 → 订单执行（仅 Paper） |
| **V2 策略实盘** (`optrade strategy`) | 回测策略零修改部署到实盘，自动化 Paper Trading |
| **策略回测** (`backtest run`) | 基于历史数据的期权策略验证，含归因分析与交互式报告 |

**支持的策略**：Short Put、Covered Call、Short Strangle、SMA Stock、SMA LEAPS、Momentum Mixed、Bull Put Spread

**数据源**：Yahoo Finance（基本面/宏观）、Futu OpenAPI（港股）、IBKR TWS（美股交易）、ThetaData（回测历史数据）

---

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 安装

```bash
# 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目
git clone https://github.com/BradLeon/option_quant_trade_system.git
cd option_quant_trade_system

# 安装依赖
uv sync
```

### 环境变量

创建 `.env` 文件：

```env
# IBKR TWS API
IBKR_HOST=127.0.0.1
IBKR_PORT=7497          # Paper: 7497, Live: 7496
IBKR_CLIENT_ID=1
IBKR_APP_TYPE=tws       # tws 或 gateway

# Futu OpenAPI
FUTU_HOST=127.0.0.1
FUTU_PORT=11111

# ThetaData（回测用，需运行 ThetaData Terminal）
# 无需配置环境变量，默认连接 localhost:25503

# 代理（Yahoo Finance 需要）
HTTP_PROXY=http://127.0.0.1:33210
HTTPS_PROXY=http://127.0.0.1:33210

# 可选
SUPABASE_URL=your-project-url
SUPABASE_KEY=your-anon-key
FRED_API_KEY=your-fred-api-key
```

---

## 策略回测系统

回测系统是独立的 CLI 工具 `backtest`，基于 ThetaData 历史数据运行期权策略模拟。

### 数据准备

回测依赖本地 Parquet 数据文件，需先从 ThetaData 下载：

```bash
# 运行回测时自动检查并下载缺失数据（需运行 ThetaData Terminal）
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG -S SPY

# 跳过数据下载检查（数据已就绪时）
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download

# 仅检查数据缺口，不运行回测
uv run backtest run -n "CHECK" -s 2025-12-01 -e 2026-02-01 -S GOOG --check-only
```

**数据下载流程**（6 阶段）：

```
Stock EOD → Option EOD + Greeks → Macro (VIX/TNX) → Economic Calendar → Fundamental → Rolling Beta
```

- 数据源：ThetaData REST API（股票/期权）、yfinance（VIX/TNX）、FRED（经济日历）
- 支持断点续传，自动限流
- FREE 账户仅支持 2023-06-01 之后的数据

### 运行回测

```bash
uv run backtest run [OPTIONS]
```

**必选参数**：

| 参数 | 说明 | 示例 |
|------|------|------|
| `-n, --name` | 回测名称 | `-n "SHORT_PUT_TEST"` |
| `-s, --start` | 开始日期 | `-s 2025-12-01` |
| `-e, --end` | 结束日期 | `-e 2026-02-01` |
| `-S, --symbols` | 标的代码（可多次指定） | `-S GOOG -S SPY` |

**可选参数**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-d, --data-dir` | 数据目录 | `/Volumes/ORICO/option_quant` |
| `-c, --capital` | 初始资金 | `1000000` |
| `--strategy` | 策略类型：`short_put`, `covered_call`, `all` | `all` |
| `--max-positions` | 最大持仓数 | `20` |
| `--skip-download` | 跳过数据下载检查 | 否 |
| `--no-report` | 不生成 HTML 报告 | 否 |
| `--report-dir` | 报告输出目录 | `reports` |
| `--check-only` | 仅检查数据 | 否 |
| `-v, --verbose` | 详细日志 | 否 |

**示例**：

```bash
# 基础回测
uv run backtest run -n "SP_GOOG" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download

# 多标的 + 多策略
uv run backtest run -n "MULTI" -s 2025-06-01 -e 2026-02-01 \
  -S GOOG -S SPY -S AAPL --strategy all -c 500000

# 仅 Short Put
uv run backtest run -n "SP_ONLY" -s 2025-12-01 -e 2026-02-01 \
  -S GOOG --strategy short_put --skip-download
```

### 回测报告

回测完成后自动生成交互式 HTML 报告（除非指定 `--no-report`），包含：

| 图表 | 说明 |
|------|------|
| **Equity Curve** | 净值曲线 + 交易标记 + SPY 基准对比 |
| **Drawdown** | 最大回撤可视化 |
| **Monthly Returns** | 月度收益热力图 |
| **Daily PnL** | 每日盈亏柱状图 |
| **K-line Charts** | 各标的价格走势 + 持仓区间 |
| **Greeks Attribution** | PnL 归因分解（Delta/Gamma/Theta/Vega） |
| **Greeks Evolution** | 组合 Greeks 时间序列 |
| **VIX / TNX** | 宏观环境 |
| **Economic Calendar** | 经济事件时间线 |
| **Performance Stats** | 关键指标汇总面板 |

**关键绩效指标**：

| 类别 | 指标 |
|------|------|
| 收益 | 总收益、年化收益、月度收益 |
| 风险 | 最大回撤、波动率、VaR 95%、CVaR 95% |
| 风险调整 | Sharpe Ratio、Sortino Ratio、Calmar Ratio |
| 交易 | 胜率、盈亏比、利润因子、期望值 |
| 基准 | Alpha、Beta、信息比率、相关性 |

### 多策略版本对比

回测系统支持多策略版本共存，便于进行 A/B 测试：

```bash
# 策略版本 1: ITM 行权接股票 (默认)
uv run backtest run -n "V9_WITH_STOCK" -s 2025-12-01 -e 2026-02-01 \
  -S GOOG --skip-download \
  --strategy-version short_options_with_expire_itm_stock_trade

# 策略版本 2: ITM 到期前平仓
uv run backtest run -n "V9_WITHOUT_STOCK" -s 2025-12-01 -e 2026-02-01 \
  -S GOOG --skip-download \
  --strategy-version short_options_without_expire_itm_stock_trade

# 对比报告
open reports/V9_WITH_STOCK_*.html
open reports/V9_WITHOUT_STOCK_*.html
```

**可用策略版本**：

| 策略版本 | CLI 参数 | 说明 |
|----------|----------|------|
| ITM 接股票 | `short_options_with_expire_itm_stock_trade` | 到期 ITM 时行权接股票 |
| ITM 平仓 | `short_options_without_expire_itm_stock_trade` | 到期 ITM 前市价平仓 |

### PnL 归因分析

回测自动运行 Greeks 归因分解，将 PnL 分解为各风险因子贡献：

```
Daily PnL ≈ Delta × ΔS + ½ × Gamma × (ΔS)² + Theta × Δt + Vega × ΔIV + Residual
```

归因支持三种粒度：
- **Daily**：每日组合级归因
- **Per-Position-Daily**：每持仓每日归因
- **Per-Trade**：单笔交易从开仓到平仓的累计归因

### Python API

除 CLI 外，也可通过 Python API 运行回测：

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
    max_positions=20,
    max_margin_utilization=0.70,
)

pipeline = BacktestPipeline(config)
result = pipeline.run(skip_data_check=True, generate_report=True)

print(f"Total Return: {result.metrics.total_return_pct:.2%}")
print(f"Sharpe Ratio: {result.metrics.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.metrics.max_drawdown:.2%}")
print(f"Report: {result.report_path}")
```

---

## 实盘交易工具 (optrade)

`optrade` 是实盘交易的 CLI 工具，支持开仓筛选、持仓监控、实时仪表盘和自动交易。

```bash
uv run optrade --help
```

### screen — 开仓筛选

```bash
# 默认：筛选所有市场、所有策略
uv run optrade screen

# 筛选美股 Short Put
uv run optrade screen -m us -s short_put

# 指定标的
uv run optrade screen -S AAPL -S MSFT

# 推送结果到飞书
uv run optrade screen -m us --push
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-m, --market` | 市场：`us`, `hk`, `all` | `all` |
| `-s, --strategy` | 策略：`short_put`, `covered_call`, `all` | `all` |
| `-S, --symbol` | 指定标的（可多次指定） | 使用股票池 |
| `-p, --pool` | 股票池名称 | 市场默认池 |
| `--push/--no-push` | 推送到飞书 | 不推送 |
| `-o, --output` | 输出格式：`text`, `json` | `text` |
| `-v, --verbose` | 详细日志 | 否 |

### monitor — 持仓监控

三层监控体系：

| 层级 | 监控内容 | 关键指标 |
|------|---------|---------|
| Portfolio 级 | 组合整体风险 | BWD%, Gamma%, Vega%, TGR, HHI |
| Position 级 | 单个持仓风险 | OTM%, Delta, DTE, P&L%, IV/HV |
| Capital 级 | 资金层面风险 | Margin 使用率, Cash Ratio, Leverage |

```bash
# 从 Paper 账户监控
uv run optrade monitor -a paper

# 只关注红色预警
uv run optrade monitor -a paper -l red

# 推送到飞书
uv run optrade monitor -a paper --push
```

### dashboard — 实时仪表盘

```bash
# 使用示例数据
uv run optrade dashboard

# 从 Paper 账户获取数据，每 30 秒刷新
uv run optrade dashboard -a paper -r 30
```

### trade — 自动交易

**仅支持 Paper Trading**。

```bash
# Screen → Trade：筛选并开仓（dry-run）
uv run optrade trade screen -m us -s short_put

# 执行下单
uv run optrade trade screen -m us --execute

# Monitor → Trade：处理监控建议
uv run optrade trade monitor --execute
```

### strategy — V2 策略实盘执行

将回测中验证过的 V2 策略（`src/backtest/strategy/`）零修改部署到实盘 Paper Trading。策略代码完全相同，只是数据源从 DuckDB 切换为 IBKR 实时行情。

```bash
# 查看可用策略
uv run optrade strategy list

# Dry-run（仅生成信号，不下单）
uv run optrade strategy run -s spy_leaps_only_vol_target -S SPY

# 实际下单到 IBKR Paper
uv run optrade strategy run -s spy_leaps_only_vol_target -S SPY --execute

# 下单 + 推送飞书通知
uv run optrade strategy run -s spy_leaps_only_vol_target -S QQQ --execute --push

# 多标的 + 风控参数
uv run optrade strategy run -s sma_stock -S SPY -S AAPL --max-margin 0.50
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-s, --strategy-name` | 策略名称 | 必填 |
| `-S, --symbol` | 标的代码（可多次指定） | 必填 |
| `-a, --account` | 账户类型：`paper` / `live` | `paper` |
| `--execute` | 实际下单（默认 dry-run） | 否 |
| `--max-margin` | 最大保证金使用率 | `0.60` |
| `--max-positions` | 最大持仓数量 | `10` |
| `--push/--no-push` | 推送结果到飞书 | 不推送 |
| `-v, --verbose` | 详细日志 | 否 |

**执行流程**（两阶段设计，解决 IBKR 单连接限制）：

```
Phase A: IBKRProvider 连接 → 市场快照 → 组合状态 → 策略信号 → 风控过滤
Phase B: 断开数据连接 → TradingPipeline 连接 → 订单执行 → 断开交易连接
```

**飞书推送卡片**包含：策略/标的/账户摘要、市场快照（价格/VIX/无风险利率）、资金概览+风控指标（保证金使用率/现金比率，红绿标识）、股票/期权持仓 Markdown 表格（盈亏红绿标识）、信号管线汇总、订单详情。

**结构化执行日志**：每个策略步骤（初始化 → 退出扫描 → 入场信号 → 合约筛选 → 风控 → 执行）均有详细 trace 输出，便于排查问题。

### 常用工作流

```bash
# 每日开盘前筛选
uv run optrade screen -m us -v

# 盘中监控
uv run optrade dashboard -a paper -r 30

# 收盘后风险检查
uv run optrade monitor -a paper -l red --push

# V2 策略自动交易（美股开盘后 10:30 AM ET，cron 自动执行）
uv run optrade strategy run -s spy_leaps_only_vol_target -S QQQ --execute --push
```

---

## 系统架构

```
option_quant_trade_system/
├── src/
│   ├── backtest/                   # 策略回测系统
│   │   ├── cli/                    # CLI 入口 (backtest 命令)
│   │   ├── config/                 # BacktestConfig 配置
│   │   ├── data/                   # 数据层
│   │   │   ├── thetadata_client.py # ThetaData REST API 客户端
│   │   │   ├── data_downloader.py  # 批量数据下载 (6阶段 pipeline)
│   │   │   ├── duckdb_provider.py  # DuckDB 数据提供者 (Point-in-time 查询)
│   │   │   ├── greeks_calculator.py# BS Greeks 批量计算
│   │   │   └── schema.py           # Parquet/DuckDB 表结构
│   │   ├── strategy/               # V2 回测策略抽象层
│   │   │   ├── models.py           # Instrument, Signal, MarketSnapshot, PortfolioState
│   │   │   ├── protocol.py         # StrategyProtocol + BacktestStrategy 基类
│   │   │   ├── registry.py         # BacktestStrategyRegistry (策略注册表)
│   │   │   ├── signal_converter.py # Signal → TradeSignal 桥接
│   │   │   ├── signals/            # 可复用信号计算器 (SMA, Momentum)
│   │   │   ├── risk/               # 可插拔风控 (Account, VolTarget)
│   │   │   └── versions/           # 策略实现 (sma_stock, sma_leaps, momentum_mixed, short_options)
│   │   ├── engine/                 # 回测引擎
│   │   │   ├── backtest_executor.py# 回测执行器 (每日循环)
│   │   │   ├── account_simulator.py# 账户模拟器 (资金/保证金)
│   │   │   ├── position_manager.py # 持仓管理器
│   │   │   └── trade_simulator.py  # 交易模拟器 (滑点/佣金)
│   │   ├── attribution/            # PnL 归因分析
│   │   │   ├── collector.py        # 数据采集器 (Observer 模式)
│   │   │   ├── pnl_attribution.py  # Greeks 归因引擎
│   │   │   ├── slice_attribution.py# 多维切片归因
│   │   │   ├── strategy_diagnosis.py# 策略诊断
│   │   │   └── regime_analyzer.py  # 市场环境分析
│   │   ├── analysis/               # 绩效分析
│   │   │   ├── metrics.py          # BacktestMetrics (Sharpe/Sortino/Calmar)
│   │   │   └── trade_analyzer.py   # 交易分析
│   │   ├── visualization/          # 可视化
│   │   │   ├── dashboard.py        # Plotly 仪表盘 (HTML 报告)
│   │   │   └── attribution_charts.py# 归因图表
│   │   ├── optimization/           # 优化模块
│   │   │   ├── benchmark.py        # 基准比较 (SPY Buy&Hold)
│   │   │   ├── parameter_sweep.py  # 参数网格搜索
│   │   │   ├── walk_forward.py     # Walk-Forward 验证
│   │   │   └── parallel_runner.py  # 并行回测
│   │   └── pipeline.py             # 回测 Pipeline (完整流程编排)
│   ├── business/                   # 业务层 (实盘交易)
│   │   ├── cli/                    # CLI 入口 (optrade 命令)
│   │   │   └── commands/strategy.py# V2 策略实盘 CLI (optrade strategy)
│   │   ├── strategy/               # V1 策略抽象层 (Screen/Monitor 驱动)
│   │   │   ├── base.py             # BaseTradeStrategy 抽象基类
│   │   │   ├── factory.py          # 策略工厂
│   │   │   ├── models.py           # TradeSignal, MarketContext
│   │   │   └── versions/           # 具体策略实现
│   │   ├── screening/              # 开仓筛选 Pipeline
│   │   ├── monitoring/             # 持仓监控 Pipeline
│   │   ├── dashboard/              # 实时仪表盘
│   │   ├── notification/           # 飞书推送
│   │   │   └── formatters/         # 消息格式化 (dashboard, strategy, trading...)
│   │   └── trading/                # 交易执行
│   │       ├── live_executor.py    # V2 策略实盘执行器
│   │       ├── live_snapshot_builder.py # IBKR → MarketSnapshot/PortfolioState
│   │       ├── live_signal_converter.py # Signal → TradingDecision
│   │       └── pipeline.py         # TradingPipeline (IBKR 下单)
│   ├── engine/                     # 计算引擎 (回测与实盘共用)
│   │   ├── models/                 # 数据模型 (BSParams, Position, Strategy)
│   │   ├── bs/                     # Black-Scholes 模型
│   │   ├── strategy/               # 策略实现 (ShortPut, CoveredCall, Strangle)
│   │   ├── position/               # 持仓级计算 (Greeks, 技术面, 波动率)
│   │   ├── portfolio/              # 组合级计算 (Greeks 汇总, 风险指标)
│   │   └── account/                # 账户级计算 (保证金, 仓位, 市场情绪)
│   └── data/                       # 数据层 (实盘)
│       ├── providers/              # 数据提供者 (Yahoo, Futu, IBKR)
│       ├── models/                 # 数据模型
│       ├── currency/               # 汇率转换
│       └── cache/                  # Redis/Supabase 缓存
├── tests/                          # 测试
├── config/                         # 配置文件
├── reports/                        # 回测报告输出
└── openspec/                       # 规格文档
```

### 策略抽象层

系统有两套策略抽象，分别服务实盘和回测：

#### 实盘策略 (`src/business/strategy/`)

`BaseTradeStrategy` 三方法生命周期，驱动 Screening/Monitoring Pipeline：

```
evaluate_positions()  →  持仓监控，生成平仓/展期信号
find_opportunities()  →  市场筛选，寻找开仓机会
generate_entry_signals() → 仓位计算，生成开仓信号
```

#### V2 策略 (`src/backtest/strategy/` + `src/strategy/`)

单入口 `generate_signals()`，回测与实盘共用同一份策略代码：

```
┌─────────────────────────────────────────────────────────────────────┐
│              StrategyProtocol (策略最小契约)                          │
├─────────────────────────────────────────────────────────────────────┤
│  generate_signals(market, portfolio, data_provider) → list[Signal]  │
└─────────────────────────────────────────────────────────────────────┘
         ↑                    ↑                    ↑
    SmaStockStrategy   SmaLeapsStrategy   MomentumMixedStrategy
    (SMA择时+股票)      (SMA择时+LEAPS)    (动量+Stock/LEAPS)
```

**回测路径**: DuckDBProvider → generate_signals() → TradeSimulator
**实盘路径**: IBKRProvider → generate_signals() → TradingPipeline → IBKR Paper

策略代码零修改，仅数据源和执行层不同。`LiveStrategyExecutor` 负责实盘编排：
构建 MarketSnapshot → 构建 PortfolioState → 调用策略 → RiskGuard 链 → Signal→Decision 转换 → 下单。

**V2 核心改进**：
- **单入口**: `generate_signals()` 替代 3 个生命周期方法
- **回测/实盘统一**: 同一策略代码，两种执行路径
- **原生多资产**: `Instrument` 模型消除 stock proxy hack
- **可组合**: `SmaComputer` / `MomentumVolTargetComputer` 信号计算器复用
- **可插拔风控**: `RiskGuard` 中间件链
- **结构化日志**: `ExecutionLog` 记录每步 trace，CLI 和飞书卡片均可渲染
- **代码精简**: 7 个旧策略 → 4 个参数化新策略 (代码量 -55%)

### 核心设计

**回测引擎每日循环**（`BacktestExecutor._run_single_day()`）：

```
1. 更新持仓市场价格
2. 处理到期期权
3. 运行 MonitoringPipeline（检查现有持仓，生成调仓建议）
4. 运行 ScreeningPipeline（筛选新开仓机会）
5. 执行交易（TradeSimulator，含滑点和佣金）
6. 采集归因快照（如启用 AttributionCollector）
7. 记录每日快照
```

**数据提供者设计**：

| 提供者 | 用途 | 数据 |
|--------|------|------|
| DuckDBProvider | 回测 | Parquet 本地数据，支持 Point-in-time 查询，防止未来数据泄漏 |
| Yahoo Finance | 实盘 | 基本面、宏观指标、历史 K 线（免费） |
| Futu OpenAPI | 实盘 | 港股期权、实时行情（需 OpenD 网关） |
| IBKR TWS | 实盘 | 美股交易、期权 Greeks（需 TWS/Gateway） |

**回测 Pipeline 完整流程**（`BacktestPipeline.run()`）：

```
数据检查/下载 → 回测执行 → 绩效计算 → 基准比较 → 归因分析 → HTML 报告生成
```

---

## 数据提供者

### 实盘数据源对比

| 功能 | Yahoo Finance | Futu OpenAPI | IBKR TWS |
|-----|---------------|--------------|----------|
| 股票行情 | US/HK | US/HK | US |
| 期权链 | US | US/HK | US |
| 期权 Greeks | - | Yes | Yes |
| 基本面数据 | Yes | - | - |
| 宏观数据 (VIX) | Yes | - | - |
| 实时数据 | 延迟 | Yes | Yes |
| 账户/持仓 | - | Yes | Yes |
| 需要网关 | - | OpenD | TWS/Gateway |

### 回测数据源

| 数据 | 来源 | 说明 |
|------|------|------|
| Stock EOD | ThetaData | 日线 OHLCV |
| Option EOD + Greeks | ThetaData | 合约级 bid/ask/Greeks |
| VIX / TNX | yfinance | 宏观环境 |
| Economic Calendar | FRED + 静态日历 | 经济事件 |
| Fundamental | IBKR | EPS/Revenue/Dividends |
| Rolling Beta | 本地计算 | 252 日窗口 |

---

## IBC 自动化运行

IBKR TWS 需要 [IBC](https://github.com/IbcAlpha/IBC) 实现无人值守运行（自动登录、处理 2FA、自动重启）。

```bash
# 安装
cd ~ && git clone https://github.com/IbcAlpha/IBC.git
cp ~/IBC/resources/config.ini ~/IBC/config.ini  # 编辑填入账户凭据

# 启动
~/start_tws.sh paper   # Paper 账户
~/start_tws.sh live    # Live 账户

# 定时任务中使用
~/ensure_tws.sh paper && uv run optrade trade monitor -a paper --execute -y --push
```

端口映射：

| 应用 | Paper | Live |
|------|-------|------|
| TWS | 7497 | 7496 |
| Gateway | 4002 | 4001 |

---

## Crontab 定时任务

```crontab
SHELL=/bin/zsh
PATH=/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin
PROJECT_DIR=/path/to/option_quant_trade_system
HTTP_PROXY=http://127.0.0.1:33210
HTTPS_PROXY=http://127.0.0.1:33210

# Dashboard 持仓报告: 北京时间 9:30, 16:30, 22:30, 周一到周五
30 9,16,22 * * 1-5 $PROJECT_DIR/scripts/ensure_tws.sh paper && cd $PROJECT_DIR && uv run optrade dashboard -a paper --push >> logs/dashboard.log 2>&1

# V2 策略实盘 (Paper): US 10:30 AM ET, 每日一次
# 夏令时=北京22:30 / 冬令时=北京23:30, 推迟到10:30因为开盘后spread收窄、LEAPS报价更完整
30 22,23 * * 1-5 $PROJECT_DIR/scripts/ensure_tws.sh paper && cd $PROJECT_DIR && uv run optrade strategy run -s spy_leaps_only_vol_target -S QQQ --execute --push >> logs/paper_trade.log 2>&1
```

> 夏令时/冬令时覆盖：同一任务设置两个时间点（如 `22,23`），策略内部检查当前持仓状态，重复执行不会重复建仓。

---

## 开发

### 运行测试

```bash
# 引擎层单元测试
uv run pytest tests/engine/ -v

# 回测模块测试
uv run pytest tests/backtest/ -v

# 指定测试文件
uv run pytest tests/engine/test_strategy.py -v
```

### 项目依赖

- **核心**：pandas, numpy, scipy, duckdb, pyarrow
- **可视化**：plotly
- **数据源**：yfinance, thetadata, ib_async, futu-api
- **CLI**：click
- **缓存**：redis, supabase（可选）

---

## License

MIT
## 更新：监控风控与策略执行一致性修复

在新的模块化策略架构（V9/V10）下，**持仓监控器(PositionMonitor)** 被高度依赖来主动生成退场信号：
- 尤其对于 `short_options_without_expire_itm_stock_trade` 策略，**P&L 与 OTM 止损被显式禁用**，取而代之的是依赖 **TGR 过低 (`< 0.5`)** 或者 **Delta 暴露 (`> 0.65`)** 进行主动防守。

### 修复问题
1. **指标计算缺失：** 由于回测引擎的 `PositionManager` 不经过实盘抓取的 `DataBridge`，部分风控指标（如 `TGR`, `Gamma Risk %` 等）在生成监控数据包 (`PositionData`) 时被遗漏，导致 TGR 监控规则永远无法被触发。
2. **Delta 偏差评估：** 旧版监控器对持仓 Delta 进行了错误的缩放处理 `abs(pos.delta / qty)`，由于系统内的 Delta 已经是 per-share 数据，除以数量反而使评估值缩小了数十倍，完全丧失了风控效力。

### 实现效果
修复计算错误后：
1. **亏损止损即时响应：** 策略的 `TGR` 监控现在能够在盈亏（PNL）发生超预期恶化之前提前发现时间衰减失效与 Gamma 风险的不对称，成功拦截由于过期价内 (ITM) 造成的严重回撤（例如防止单手亏损超过 `-3000`）。
2. **提前止盈联动：** 在符合 DTE 及高比例利润的条件时，由于所有风控链路已被打通，现在能够准确抛出触发退出的交易信号。
