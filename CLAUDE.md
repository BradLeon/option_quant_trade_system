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
uv run pytest tests/engine/test_pricing.py::test_short_put -v

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
# Quick backtest (auto-download data from ThetaData if needed)
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG

# Skip data check (data already downloaded)
uv run backtest run -n "TEST" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download

# Check data gaps only
uv run backtest run -n "CHECK" -s 2025-12-01 -e 2026-02-01 -S GOOG --check-only

# Multi-symbol, multi-strategy
uv run backtest run -n "MULTI" -s 2025-12-01 -e 2026-02-01 -S GOOG -S SPY -S AAPL --strategy all -c 500000

# Strategy version A/B comparison
uv run backtest run -n "V_STOCK" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download \
  --strategy-version short_options_with_expire_itm_stock_trade
uv run backtest run -n "V_CLOSE" -s 2025-12-01 -e 2026-02-01 -S GOOG --skip-download \
  --strategy-version short_options_without_expire_itm_stock_trade
```

### Programmatic Backtest (Python API)
```python
from datetime import date
from src.backtest import BacktestConfig, BacktestPipeline
from src.engine.models.enums import StrategyType

config = BacktestConfig(
    name="TEST", start_date=date(2025, 12, 1), end_date=date(2026, 2, 1),
    symbols=["GOOG", "SPY"], strategy_types=[StrategyType.SHORT_PUT, StrategyType.COVERED_CALL],
    initial_capital=1_000_000, max_positions=20, max_margin_utilization=0.70,
)
result = BacktestPipeline(config).run(skip_data_check=True, generate_report=True)
```

## Architecture Overview

This is an options quantitative trading system (Python 3.11+, `uv` package manager) with four modules:

| Module | Path | Role |
|--------|------|------|
| **Engine** | `src/engine/` | Pure calculations: BS pricing, Greeks, pricing metrics. Shared by both live and backtest. |
| **Data** | `src/data/` | Multi-provider abstraction: Yahoo Finance, Futu OpenAPI, IBKR TWS (live); DuckDB/Parquet (backtest) |
| **Business** | `src/business/` | Live trading: CLI (`optrade`), screening, monitoring, trading, notifications (Feishu) |
| **Backtest** | `src/backtest/` | Simulation: CLI (`backtest`), executor, account/position/trade simulators, PnL attribution, HTML reports |

### Two Execution Paths

**Live** (`optrade` CLI): ScreeningPipeline → MonitoringPipeline → DecisionEngine → TradingProvider (IBKR/Futu)

**Backtest** (`backtest` CLI): DuckDB (Parquet, PIT queries) → same Screening/Monitoring pipelines → TradeSimulator → AttributionCollector

Both paths share the same `ScreeningPipeline` and `MonitoringPipeline` classes — only the data provider differs.

### Business Strategy Abstraction (`src/business/strategy/`)

`BaseOptionStrategy` defines the strategy interface with three methods:
- `evaluate_positions()` — Monitor positions, generate close/roll signals
- `find_opportunities()` — Screen market for entry opportunities
- `generate_entry_signals()` — Size positions, generate open signals

Strategy versions implement different behaviors (e.g., ITM expiry → accept stock assignment vs close before expiry). Versions live in `src/business/strategy/versions/` and are selected via `--strategy-version` CLI flag.

Key design: monitoring suggestions (e.g., `take_profit`, `reduce`, `hedge`) are translated to standard `TradeAction.CLOSE` or `ROLL` actions. Position matching uses `position_id` as primary key to handle format differences between live brokers and backtest data.

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

## Pricing Implementation

To add a new option pricer:

1. Extend `OptionPricer` in `src/engine/pricing/` (see `short_put.py` for reference)
2. Implement abstract methods:
   - `calc_expected_return()` - Expected PnL E[π]
   - `calc_return_variance()` - Variance Var[π]
   - `calc_max_profit()` - Maximum possible profit
   - `calc_max_loss()` - Maximum possible loss (positive number)
   - `calc_breakeven()` - Breakeven price(s)
   - `calc_win_probability()` - Probability of profit
3. Add pricer to `src/engine/pricing/__init__.py` and `StrategyType` enum

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
| ThetaData | Backtest data download | Stock EOD, Option EOD + Greeks (FREE tier: data after 2023-06-01) |
| Yahoo Finance | Live + Backtest macro | Fundamental, macro (VIX/TNX), historical K-lines |
| Futu OpenAPI | Live | HK options, real-time quotes |
| IBKR TWS | Live | US trading, option Greeks |

## Important Patterns

1. **DataProvider Protocol**: All pipelines use `DataProvider` protocol. DuckDBProvider implements it for backtesting (with `set_as_of_date()` for PIT queries), live providers (Yahoo, IBKR, Futu) for real-time.

2. **Three-Layer Architecture** in `BacktestExecutor`:
   - Trade Layer: `TradeSimulator` (execution, fees)
   - Position Layer: `PositionManager` (Greeks, margin, PnL)
   - Account Layer: `AccountSimulator` (cash, positions, equity snapshots)

3. **Observer Pattern**: `AttributionCollector` observes the backtest loop to capture daily position/portfolio snapshots for PnL attribution analysis.

4. **Factory Pattern**: `create_pricers_from_position()` in `src/engine/pricing/factory.py` reconstructs pricer instances from saved positions.

## Testing Guidelines

- Unit tests: `tests/engine/` for calculation logic
- Integration tests: `tests/backtest/test_backtest_e2e.py` for full backtest pipeline
- Verification tests: `tests/verification/` for data accuracy and cross-validation
- Business logic tests: `tests/business/screening/` validate filters against expected behavior

**Known issues**: `test_backtest_e2e.py` and `test_executor_components.py` have import errors (PositionTracker module missing). Some test files (`test_analysis.py`, `test_optimization.py`) may hang without a real data connection.

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
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```