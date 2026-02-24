# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

## Common Commands

### Development
```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/engine/ -v                          # Engine layer tests
uv run pytest tests/backtest/ -v                         # Backtest tests
uv run pytest tests/business/ -v                          # Business layer tests

# Run single test
uv run pytest tests/engine/test_strategy.py::test_short_put -v

# Linting/Formatting
uv run black src tests
uv run ruff check src tests
uv run mypy src
```

### Live Trading (optrade)
```bash
# Screen for opportunities
uv run optrade screen -m us -s short_put
uv run optrade screen -S AAPL -S MSFT

# Monitor positions
uv run optrade monitor -a paper -l red --push

# Interactive dashboard
uv run optrade dashboard -a paper -r 30

# Auto trade (paper only)
uv run optrade trade screen -m us --execute
uv run optrade trade monitor --execute
```

### Backtesting
```bash
# Quick backtest (auto-download data if needed)
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG

# Skip data check (data already downloaded)
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download

# Check data gaps only
uv run backtest run -n "CHECK" -s 2025-12-01 -e 2026-02-01 -S GOOG --check-only

# Multi-symbol, multi-strategy
uv run backtest run -n "MULTI" -s 2025-12-01 -e 2026-02-01 -S GOOG -S SPY -S AAPL --strategy all -c 500000
```

## Architecture Overview

This is an options quantitative trading system with two parallel execution paths:

### 1. Live Trading Path (`optrade` CLI)
- **ScreeningPipeline**: Three-layer funnel (Market → Underlying → Contract filters)
- **MonitoringPipeline**: Three-tier monitoring (Portfolio/Position/Capital levels)
- **DecisionEngine**: Generates trading decisions (OPEN/CLOSE/ROLL) from screening signals and monitoring suggestions
- **TradingProvider**: Executes orders via IBKR TWS or Futu OpenAPI

### 2. Backtesting Path (`backtest` CLI)
- **BacktestExecutor**: Orchestrates daily backtest loop using real-time pipelines
- **Data Providers**: DuckDB (historical Parquet files) supports Point-in-Time queries to prevent look-ahead bias
- **AccountSimulator**: Simulates margin, cash, position management
- **TradeSimulator**: Simulates slippage and commission using IBKR fee schedules

### Shared Engine Layer (`src/engine/`)
- **BS Model**: Black-Scholes pricing and Greeks calculations
- **Strategy Classes**: ShortPutStrategy, CoveredCallStrategy, ShortStrangleStrategy (extend `OptionStrategy`)
- **Position Calculations**: Greeks, risk-return metrics (TGR, PREI, SAS, ROC)
- **Portfolio Calculations**: Aggregated Greeks, BWD%, Gamma%, Vega%, TGR, HHI

### Data Flow
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Configuration Layer                           │
│  ConfigMode (LIVE/BACKTEST) → YAML configs (config/Screening/)      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Data Provider Interface                           │
│  - Live: Yahoo Finance, IBKR TWS, Futu OpenAPI                     │
│  - Backtest: DuckDBProvider (Parquet files with PIT queries)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Engine Layer                                 │
│  Black-Scholes → Strategy → Position → Portfolio → Account            │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Backtest Daily Loop

The `BacktestExecutor._run_single_day()` method implements the core backtest logic:

```
1. Update all position prices (PositionManager)
2. Process expiring options
3. Run MonitoringPipeline on existing positions → PositionSuggestion[]
4. Run ScreeningPipeline for new opportunities → ScreeningResult
5. DecisionEngine.process_batch() → TradingDecision[] (OPEN/CLOSE/ROLL)
6. Execute trades via TradeSimulator (slippage + commission)
7. Capture attribution snapshots (if AttributionCollector enabled)
8. Record DailySnapshot (NLV, cash, margin, PnL, positions)
```

## Strategy Implementation

To add a new option strategy:

1. Extend `OptionStrategy` in `src/engine/strategy/` (see `short_put.py` for reference)
2. Implement abstract methods:
   - `calc_expected_return()` - Expected PnL E[π]
   - `calc_return_variance()` - Variance Var[π]
   - `calc_max_profit()` - Maximum possible profit
   - `calc_max_loss()` - Maximum possible loss (positive number)
   - `calc_breakeven()` - Breakeven price(s)
   - `calc_win_probability()` - Probability of profit
3. Add strategy to `src/engine/strategy/__init__.py` and `StrategyType` enum

## Configuration System

Configurations use `ConfigMode.LIVE` (real trading) or `ConfigMode.BACKTEST` (historical simulation):

- **ScreeningConfig**: `config/screening/{short_put,covered_call}.yaml`
  - Three-layer filters: MarketFilter → UnderlyingFilter → ContractFilter
  - Priority levels: P0 (fatal), P1 (core), P2 (important), P3 (reference)
  - Trend override adjusts `min_iv_rank` based on market direction

- **MonitoringConfig**: `config/monitoring/thresholds.yaml`
  - Portfolio/Position/Capital risk thresholds

- **BacktestConfig**: CLI arguments + optional YAML overrides
  - `screening_overrides`: Merge with ScreeningConfig
  - `monitoring_overrides`: Merge with MonitoringConfig
  - `risk_overrides`: Merge with RiskConfig

## Key Metrics

- **TGR (Theta/Gamma Ratio)**: Standardized theta income per unit gamma risk. Target > 1.0
- **PREI (Position Risk Exposure Index)**: Tail risk based on gamma, vega, DTE. Lower is better.
- **SAS (Strategy Attractiveness Score)**: IV/HV, Sharpe, win probability combined. 0-100.
- **ROC (Return on Capital)**: Annualized premium/margin ratio.
- **Expected ROC**: Probability-weighted expected return/margin.

## Data Providers

| Provider | Use Case | Data Type |
|----------|-----------|-----------|
| DuckDBProvider | Backtest | Parquet files, Point-in-Time queries |
| Yahoo Finance | Live | Fundamental, macro, historical K-lines |
| Futu OpenAPI | Live | HK options, real-time quotes |
| IBKR TWS | Live | US trading, option Greeks |

## Important Patterns

1. **Pipeline Pattern**: Both live and backtest paths use the same `ScreeningPipeline` and `MonitoringPipeline` classes. The difference is the data provider (live API vs DuckDB).

2. **Three-Layer Architecture** in `BacktestExecutor`:
   - Trade Layer: `TradeSimulator` (execution, fees)
   - Position Layer: `PositionManager` (Greeks, margin, PnL)
   - Account Layer: `AccountSimulator` (cash, positions, equity snapshots)

3. **Data Provider Interface**: All pipelines use `DataProvider` protocol. DuckDBProvider implements this interface for backtesting, while live providers (Yahoo, IBKR, Futu) implement it for real-time.

4. **Observer Pattern**: `AttributionCollector` observes the backtest loop to capture daily position/portfolio snapshots for PnL attribution analysis.

5. **Factory Pattern**: `create_strategies_from_position()` in `src/engine/strategy/factory.py` reconstructs strategy instances from saved positions.

## Testing Guidelines

- Unit tests: `tests/engine/` for calculation logic
- Integration tests: `tests/backtest/test_backtest_e2e.py` for full backtest pipeline
- Verification tests: `tests/verification/` for data accuracy and cross-validation
- Business logic tests: `tests/business/screening/` validate filters against expected behavior

## Environment Variables

Required in `.env`:
```
# IBKR TWS API
IBKR_HOST=127.0.0.1
IBKR_PORT=7497          # Paper: 7497, Live: 7496
IBKR_CLIENT_ID=1
IBKR_APP_TYPE=tws

# Futu OpenAPI
FUTU_HOST=127.0.0.1
FUTU_PORT=11111

# Proxy (Yahoo Finance needs it)
HTTP_PROXY=http://127.0.0.1:33210
HTTPS_PROXY=http://127.0.0.1:33210
```