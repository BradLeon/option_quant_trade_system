# Backtest — 策略回测系统

基于 ThetaData 历史数据的期权策略回测系统，支持 V2 策略协议、Greeks 归因分析和交互式 HTML 报告。

## 快速开始

```bash
# 启动 ThetaData Terminal（期权/股票历史数据）
./scripts/ensure_thetadata.sh

# LEAPS V2 + CashSweep（推荐）
uv run backtest run -n "SPY_leaps_v2" -s 2016-06-01 -e 2026-03-01 \
  -S SPY -B SPY --skip-download --strategy-version leaps_v2_cash_sweep

# 动量混合 V2
uv run backtest run -n "QQQ_momentum_v2" -s 2016-06-01 -e 2026-03-01 \
  -S QQQ -B SPY --skip-download --strategy-version momentum_mixed_v2

# 自动下载缺失数据（需运行 ThetaData Terminal）
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG -B SPY
```

## 模块结构

```
src/backtest/
├── cli/                   # CLI 入口 (backtest 命令)
├── config/                # BacktestConfig
├── pipeline.py            # BacktestPipeline (完整流程编排)
│
├── engine/                # 回测引擎
│   ├── backtest_executor.py   # BacktestExecutor (每日循环)
│   ├── signal_converter.py    # Signal → TradeSignal 桥接 (回测引擎内部转换)
│   ├── trade_simulator.py     # TradeSimulator (滑点/佣金/成交)
│   ├── position_manager.py    # PositionManager (Greeks/保证金/PnL)
│   └── account_simulator.py   # AccountSimulator (资金/权益/快照)
│
├── data/                  # 数据层
│   ├── duckdb_provider.py     # DuckDB 数据提供者 (Point-in-Time 查询)
│   ├── thetadata_client.py    # ThetaData REST API 客户端
│   ├── data_downloader.py     # 批量数据下载 (6阶段 pipeline)
│   ├── greeks_calculator.py   # BS Greeks 批量计算
│   └── schema.py              # Parquet/DuckDB 表结构
│
├── attribution/           # PnL 归因分析 (Observer 模式)
│   ├── collector.py           # AttributionCollector (数据采集)
│   ├── pnl_attribution.py     # Greeks 归因引擎
│   ├── slice_attribution.py   # 多维切片归因
│   ├── strategy_diagnosis.py  # 策略诊断
│   └── regime_analyzer.py     # 市场环境分析
│
├── analysis/              # 绩效分析
│   ├── metrics.py             # BacktestMetrics (Sharpe/Sortino/Calmar)
│   └── trade_analyzer.py      # 交易分析 (胜率/盈亏比)
│
├── visualization/         # 可视化
│   ├── dashboard.py           # Plotly HTML 报告
│   └── attribution_charts.py  # 归因图表
│
└── optimization/          # 优化模块
    ├── benchmark.py           # 基准比较 (SPY Buy&Hold)
    ├── parameter_sweep.py     # 参数网格搜索
    ├── walk_forward.py        # Walk-Forward 验证
    └── parallel_runner.py     # 并行回测
```

## 回测引擎每日循环

`BacktestExecutor._run_single_day()`:

```
1. 更新持仓市场价格 (PositionManager)
2. 处理到期期权 (行权/过期)
3. V2 策略: strategy.generate_signals(market, portfolio, dp)
   → RiskGuard chain 过滤
   → SignalConverter: Signal → TradeSignal
4. 执行交易 (TradeSimulator, 含滑点和佣金)
5. 采集归因快照 (AttributionCollector, 如启用)
6. 记录每日快照 (NLV, cash, margin, positions)
```

## V2 策略系统

> 策略协议、实现、信号计算器、风控中间件均位于 `src/strategy/`。

### 策略协议

所有 V2 策略实现 `StrategyProtocol.generate_signals(market, portfolio, dp) → list[Signal]`。

`Strategy` 模板基类将其拆分为三步：
1. `on_day_start()` — 计算指标（SMA、动量、波动率）
2. `compute_exit_signals()` — 扫描持仓生成退出信号
3. `compute_entry_signals()` — 基于市场条件生成入场信号

### 策略注册表

```python
from src.strategy.registry import StrategyRegistry

strategy = StrategyRegistry.create("momentum_mixed_v2", symbols=["QQQ"])
signals = strategy.generate_signals(market, portfolio, dp)
```

> `BacktestStrategyRegistry` 是 `StrategyRegistry` 的向后兼容别名，旧代码无需修改。

### 信号计算器

可复用的信号组件，多个策略共享：

- **SmaComputer**: SMA 均线计算，支持自定义周期和上穿/下穿判断
- **MomentumVolTargetComputer**: 动量评分 + 波动率目标仓位计算

### AlertType 与 CloseReasonType 映射

策略设置 `signal.alert_type = AlertType.PROFIT_TARGET`，`TradeSimulator` 通过 `ALERT_TO_CLOSE_REASON` 映射到 `CloseReasonType.PROFIT_TARGET`，用于 PnL 归因中按退出原因统计。

## 数据层

### DuckDB Provider

Point-in-Time 查询防止未来数据泄漏：

```python
provider = DuckDBProvider(data_dir="/path/to/data")
provider.set_as_of_date(date(2025, 12, 15))  # 只返回该日期及之前的数据
quotes = provider.get_option_chain("GOOG")
```

### 数据下载流程

6 阶段 pipeline（支持断点续传）：

```
Stock EOD → Option EOD + Greeks → Macro (VIX/TNX) → Economic Calendar → Fundamental → Rolling Beta
```

数据源：ThetaData REST API（股票/期权）、yfinance（VIX/TNX）、FRED（经济日历）。
ThetaData FREE 账户仅支持 2023-06-01 之后的数据。

## PnL 归因分析

```
Daily PnL ≈ Delta × ΔS + ½ × Gamma × (ΔS)² + Theta × Δt + Vega × ΔIV + Residual
```

Observer 模式：`AttributionCollector` 挂载到 `BacktestExecutor`，在监控步骤后采集持仓快照。end-of-day Greeks 作为 next-day 归因的 start-of-day Greeks。

三种粒度：
- **Daily**: 每日组合级归因
- **Per-Position-Daily**: 每持仓每日归因
- **Per-Trade**: 单笔交易开仓到平仓累计归因

## 回测报告

自动生成交互式 HTML 报告：
- Equity Curve + SPY 基准对比
- Drawdown 可视化
- 月度收益热力图
- 各标的 K 线 + 持仓区间
- Greeks 归因分解 (Delta/Gamma/Theta/Vega/Residual)
- 组合 Greeks 时间序列
- 关键绩效指标 (Sharpe, Sortino, Calmar, 胜率, 盈亏比)

## Python API

```python
from datetime import date
from src.backtest import BacktestConfig, BacktestPipeline

config = BacktestConfig(
    name="LEAPS_QQQ",
    start_date=date(2025, 6, 1),
    end_date=date(2026, 2, 1),
    symbols=["QQQ"],
    initial_capital=500_000,
)

result = BacktestPipeline(config).run(skip_data_check=True, generate_report=True)
print(f"Return: {result.metrics.total_return_pct:.2%}")
print(f"Sharpe: {result.metrics.sharpe_ratio:.2f}")
```

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `No data for GOOG` | Parquet 文件缺失 | 运行 `backtest run` 不加 `--skip-download` |
| `ThetaData connection refused` | Terminal 未启动 | `./scripts/ensure_thetadata.sh` |
| Greeks 全为 0 | 数据日期在 2023-06-01 之前 | FREE 账户限制，使用更近的日期 |
| `Unmapped alert_type` | AlertType 缺少映射 | 检查 `ALERT_TO_CLOSE_REASON` in `trade_simulator.py` |
