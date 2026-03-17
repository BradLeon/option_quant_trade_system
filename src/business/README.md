# Business — 实盘交易业务层

实盘交易的完整业务栈：CLI 入口、交易执行、仪表盘和通知。

## 模块结构

```
src/business/
├── cli/               # optrade CLI
│   └── commands/
│       ├── strategy.py   # optrade strategy (V2 策略实盘)
│       ├── dashboard.py  # optrade dashboard (仪表盘)
│       └── notify.py     # optrade notify (飞书通知)
├── trading/           # V2 交易执行 (详见 trading/README.md)
├── dashboard/         # 实时仪表盘 (Plotly)
├── notification/      # 飞书推送
│   └── formatters/    # 消息格式化 (dashboard, strategy)
├── screening/         # 开仓筛选 Pipeline (回测引擎依赖)
├── monitoring/        # 持仓监控 Pipeline (回测引擎依赖)
└── strategy/          # V1 策略抽象 (回测引擎依赖)
```

## CLI 命令

### optrade strategy — V2 策略实盘

将回测验证的 V2 策略部署到 IBKR Paper Trading：

```bash
uv run optrade strategy list                                    # 列出可用策略
uv run optrade strategy run -s momentum_mixed_v2 -S QQQ         # dry-run
uv run optrade strategy run -s momentum_mixed_v2 -S QQQ --execute --push  # 执行+通知
```

### optrade dashboard — 实时仪表盘

```bash
uv run optrade dashboard -a paper            # IBKR Paper 账户
uv run optrade dashboard -a paper -r 30      # 每 30 秒刷新
uv run optrade dashboard -a paper --push     # 推送到飞书
```

### optrade notify — 飞书通知

```bash
uv run optrade notify                        # 推送当前持仓报告
```

## 历史模块说明

`screening/`、`monitoring/`、`strategy/` 是 V1 架构的组件，当前仍被回测引擎的旧策略路径 (`short_options`) 和仪表盘依赖。V2 策略路径不再使用这些模块。

| 模块 | V2 替代 | 状态 |
|------|---------|------|
| `screening/` | V2 策略的 `compute_entry_signals()` | 回测旧路径依赖 |
| `monitoring/` | V2 策略的 `compute_exit_signals()` + `RiskGuard` | 回测旧路径依赖 |
| `strategy/` (business) | `src/strategy/` 共享层 + `src/backtest/strategy/` | Dashboard 依赖 |
