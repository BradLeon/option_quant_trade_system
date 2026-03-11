"""MA Signal Search V3 — SPY Stock + Moving Average Timing Strategy Comparison

V1 strategies (1-5):
  1. SMA200/Price — full position when price > SMA200
  2. SMA50/SMA200 — full position when SMA50 > SMA200
  3. Price/SMA50/SMA20 — full position when Price>SMA50 AND SMA20>SMA50
  4. SMA Triple Score — dynamic position (0-100%) based on 5-point scoring
  5. Buy & Hold — benchmark

V2 additions — Signal improvements (6-8):
  6. EMA Triple Score — same 5 conditions using EMA20/50/200
  7. Score+Momentum — 7 conditions (5 original + 20d/60d momentum)
  8. Score+VIX — 5 original + VIX regime adjustment (max 6)

V2 additions — Position management (9-14):
  9. Score Aggressive — low-score cutoff, top-heavy mapping
  10. Score Convex — (score/5)² convex mapping
  11. Score Leverage — up to 300% leverage on high conviction
  12. Score Moderate Lev — up to 200% leverage
  13. Score Binary≥3 Lev — binary 0% or 200%
  14. Momentum+Leverage — 7-score momentum + 0-300% leverage

V3 additions — Crisis drawdown optimization (15-18):
  15. VolTarget — vol_scalar=min(2.0, 15/VIX), Tier3 only
  16. VIXTerm — graduated VIX/VIX3M term structure response
  17. SmartRisk — 3-tier: panic breaker + bear limiter + vol target
  18. AdaptiveRisk — SmartRisk + VIX9D ultra-short panic + drawdown protection

Data: stock_daily.parquet (SPY) + macro_daily.parquet (^VIX, ^VIX3M, ^VIX9D)
Output: HTML report with Plotly interactive charts
"""

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
import pyarrow.parquet as pq

# Project root for engine imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.position.technical.moving_average import calc_ema_series, calc_sma_series

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# ============================================================
# Config
# ============================================================
STOCK_PARQUET = Path("/Volumes/ORICO/option_quant/stock_daily.parquet")
MACRO_PARQUET = Path("/Volumes/ORICO/option_quant/macro_daily.parquet")
SYMBOL = "QQQ"
VIX_INDICATOR = "^VIX"
START_DATE = date(2016, 1, 4)
END_DATE = date(2026, 2, 27)
INITIAL_CAPITAL = 1_000_000.0
OUTPUT_DIR = Path(__file__).parent
REPORT_FILE = OUTPUT_DIR / "QQQ_ma_signal_search_report.html"

# Auto-assigned color palette (18 strategies + B&H)
COLOR_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12",
    "#1abc9c", "#e67e22", "#d35400", "#c0392b", "#2980b9",
    "#27ae60", "#8e44ad", "#16a085", "#7f8c8d", "#e91e63",
    "#00bcd4", "#ff5722", "#4caf50", "#673ab7",
]


# ============================================================
# Data Models
# ============================================================
@dataclass
class MarketData:
    dates: list[date]
    closes: list[float]
    vix: list[float]  # VIX close aligned to dates
    vix3m: list[float]  # VIX3M close aligned to dates
    vix9d: list[float]  # VIX9D close aligned to dates


@dataclass
class PrecomputedMA:
    sma20: list[float | None]
    sma50: list[float | None]
    sma200: list[float | None]
    ema20: list[float | None]
    ema50: list[float | None]
    ema200: list[float | None]
    closes: list[float]


@dataclass
class TradeRecord:
    date: date
    action: str  # "BUY" or "SELL"
    price: float
    position_pct: float  # 0.0 - 3.0 (>1.0 = leveraged)


@dataclass
class BacktestResult:
    name: str
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    num_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    time_in_market: float = 0.0
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    drawdown_curve: list[float] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    position_series: list[float] = field(default_factory=list)  # 0.0-1.0 per bar


# ============================================================
# Data Loading
# ============================================================
def load_market_data() -> MarketData:
    """Load SPY daily close + VIX from parquet."""
    # SPY prices
    table = pq.read_table(
        STOCK_PARQUET,
        filters=[("symbol", "=", SYMBOL)],
        columns=["date", "close"],
    )
    dates = table.column("date").to_pylist()
    closes = table.column("close").to_pylist()
    pairs = sorted(zip(dates, closes), key=lambda x: x[0])
    pairs = [(d, float(c)) for d, c in pairs if START_DATE <= d <= END_DATE]

    spy_dates = [p[0] for p in pairs]
    spy_closes = [p[1] for p in pairs]

    # VIX data (VIX, VIX3M, VIX9D)
    vix_table = pq.read_table(
        MACRO_PARQUET,
        filters=[("indicator", "in", [VIX_INDICATOR, "^VIX3M", "^VIX9D"])],
        columns=["date", "close", "indicator"],
    )
    vix_dates = vix_table.column("date").to_pylist()
    vix_closes = vix_table.column("close").to_pylist()
    vix_inds = vix_table.column("indicator").to_pylist()

    vix_map: dict[date, float] = {}
    vix3m_map: dict[date, float] = {}
    vix9d_map: dict[date, float] = {}
    for d, c, ind in zip(vix_dates, vix_closes, vix_inds):
        if ind == VIX_INDICATOR:
            vix_map[d] = float(c)
        elif ind == "^VIX3M":
            vix3m_map[d] = float(c)
        elif ind == "^VIX9D":
            vix9d_map[d] = float(c)

    # Align VIX, VIX3M, VIX9D to SPY dates (forward-fill missing)
    vix_aligned: list[float] = []
    vix3m_aligned: list[float] = []
    vix9d_aligned: list[float] = []
    last_vix = 20.0
    last_vix3m = 20.0
    last_vix9d = 20.0
    for d in spy_dates:
        if d in vix_map:
            last_vix = vix_map[d]
        if d in vix3m_map:
            last_vix3m = vix3m_map[d]
        if d in vix9d_map:
            last_vix9d = vix9d_map[d]
        vix_aligned.append(last_vix)
        vix3m_aligned.append(last_vix3m)
        vix9d_aligned.append(last_vix9d)

    return MarketData(
        dates=spy_dates, closes=spy_closes,
        vix=vix_aligned, vix3m=vix3m_aligned, vix9d=vix9d_aligned,
    )


def precompute_ma(data: MarketData) -> PrecomputedMA:
    """Precompute all needed SMA and EMA series."""
    return PrecomputedMA(
        sma20=calc_sma_series(data.closes, 20),
        sma50=calc_sma_series(data.closes, 50),
        sma200=calc_sma_series(data.closes, 200),
        ema20=calc_ema_series(data.closes, 20),
        ema50=calc_ema_series(data.closes, 50),
        ema200=calc_ema_series(data.closes, 200),
        closes=data.closes,
    )


# ============================================================
# Metrics Calculation
# ============================================================
def calc_metrics(result: BacktestResult, years: float) -> None:
    """Fill in metrics from equity_curve and trades."""
    eq = result.equity_curve
    if not eq or eq[0] <= 0:
        return

    # Total & annualized return
    result.total_return = (eq[-1] / eq[0] - 1) * 100
    if years > 0:
        result.annualized_return = ((eq[-1] / eq[0]) ** (1 / years) - 1) * 100

    # Max drawdown
    peak = eq[0]
    max_dd = 0.0
    dd_curve = []
    for val in eq:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        dd_curve.append(-dd * 100)
        if dd > max_dd:
            max_dd = dd
    result.max_drawdown = -max_dd * 100
    result.drawdown_curve = dd_curve

    # Sharpe
    if len(eq) > 1:
        daily_rets = np.diff(eq) / np.array(eq[:-1])
        if np.std(daily_rets) > 0:
            result.sharpe = float(
                (np.mean(daily_rets) / np.std(daily_rets)) * np.sqrt(252)
            )

    # Time in market
    if result.position_series:
        bars_in = sum(1 for p in result.position_series if p > 0)
        result.time_in_market = bars_in / len(result.position_series) * 100

    # Win rate from round-trip trades
    trades = result.trades
    wins, losses = 0, 0
    win_pcts, loss_pcts = [], []
    buy_price = None
    for t in trades:
        if t.action == "BUY":
            buy_price = t.price
        elif t.action == "SELL" and buy_price is not None:
            pnl_pct = (t.price / buy_price - 1) * 100
            if pnl_pct > 0:
                wins += 1
                win_pcts.append(pnl_pct)
            else:
                losses += 1
                loss_pcts.append(pnl_pct)
            buy_price = None

    total_trips = wins + losses
    if total_trips > 0:
        result.win_rate = wins / total_trips * 100
        result.avg_win_pct = np.mean(win_pcts) if win_pcts else 0.0
        result.avg_loss_pct = np.mean(loss_pcts) if loss_pcts else 0.0
    result.num_trades = len(trades)


# ============================================================
# Strategy Implementations
# ============================================================
def run_buy_and_hold(data: MarketData, ma: PrecomputedMA) -> BacktestResult:
    """Strategy 5: Buy & Hold benchmark."""
    r = BacktestResult(name="Buy & Hold")
    r.dates = data.dates
    shares = INITIAL_CAPITAL / data.closes[0]
    r.equity_curve = [shares * c for c in data.closes]
    r.position_series = [1.0] * len(data.closes)
    r.trades = [TradeRecord(data.dates[0], "BUY", data.closes[0], 1.0)]
    years = (data.dates[-1] - data.dates[0]).days / 365.25
    calc_metrics(r, years)
    return r


def run_sma200_price(data: MarketData, ma: PrecomputedMA) -> BacktestResult:
    """Strategy 1: Price > SMA200 → full position."""
    r = BacktestResult(name="SMA200/Price")
    r.dates = data.dates
    n = len(data.closes)

    cash = INITIAL_CAPITAL
    shares = 0.0
    invested = False
    equity = []
    positions = []
    trades = []

    for i in range(n):
        close = data.closes[i]
        sma200 = ma.sma200[i] if i < len(ma.sma200) else None

        if sma200 is not None:
            if close > sma200 and not invested:
                shares = cash / close
                cash = 0.0
                invested = True
                trades.append(TradeRecord(data.dates[i], "BUY", close, 1.0))
            elif close < sma200 and invested:
                cash = shares * close
                shares = 0.0
                invested = False
                trades.append(TradeRecord(data.dates[i], "SELL", close, 0.0))

        equity.append(cash + shares * close)
        positions.append(1.0 if invested else 0.0)

    r.equity_curve = equity
    r.position_series = positions
    r.trades = trades
    years = (data.dates[-1] - data.dates[0]).days / 365.25
    calc_metrics(r, years)
    return r


def run_sma50_sma200(data: MarketData, ma: PrecomputedMA) -> BacktestResult:
    """Strategy 2: SMA50 > SMA200 → full position (golden/death cross)."""
    r = BacktestResult(name="SMA50/SMA200")
    r.dates = data.dates
    n = len(data.closes)

    cash = INITIAL_CAPITAL
    shares = 0.0
    invested = False
    equity = []
    positions = []
    trades = []

    for i in range(n):
        close = data.closes[i]
        sma50 = ma.sma50[i] if i < len(ma.sma50) else None
        sma200 = ma.sma200[i] if i < len(ma.sma200) else None

        if sma50 is not None and sma200 is not None:
            if sma50 > sma200 and not invested:
                shares = cash / close
                cash = 0.0
                invested = True
                trades.append(TradeRecord(data.dates[i], "BUY", close, 1.0))
            elif sma50 < sma200 and invested:
                cash = shares * close
                shares = 0.0
                invested = False
                trades.append(TradeRecord(data.dates[i], "SELL", close, 0.0))

        equity.append(cash + shares * close)
        positions.append(1.0 if invested else 0.0)

    r.equity_curve = equity
    r.position_series = positions
    r.trades = trades
    years = (data.dates[-1] - data.dates[0]).days / 365.25
    calc_metrics(r, years)
    return r


def run_price_sma50_sma20(data: MarketData, ma: PrecomputedMA) -> BacktestResult:
    """Strategy 3: Price>SMA50 AND SMA20>SMA50 → in; Price<SMA50 AND SMA20<SMA50 → out."""
    r = BacktestResult(name="Price/SMA50/SMA20")
    r.dates = data.dates
    n = len(data.closes)

    cash = INITIAL_CAPITAL
    shares = 0.0
    invested = False
    equity = []
    positions = []
    trades = []

    for i in range(n):
        close = data.closes[i]
        sma20 = ma.sma20[i] if i < len(ma.sma20) else None
        sma50 = ma.sma50[i] if i < len(ma.sma50) else None

        if sma20 is not None and sma50 is not None:
            entry_cond = close > sma50 and sma20 > sma50
            exit_cond = close < sma50 and sma20 < sma50

            if entry_cond and not invested:
                shares = cash / close
                cash = 0.0
                invested = True
                trades.append(TradeRecord(data.dates[i], "BUY", close, 1.0))
            elif exit_cond and invested:
                cash = shares * close
                shares = 0.0
                invested = False
                trades.append(TradeRecord(data.dates[i], "SELL", close, 0.0))

        equity.append(cash + shares * close)
        positions.append(1.0 if invested else 0.0)

    r.equity_curve = equity
    r.position_series = positions
    r.trades = trades
    years = (data.dates[-1] - data.dates[0]).days / 365.25
    calc_metrics(r, years)
    return r


def run_sma_triple_score(data: MarketData, ma: PrecomputedMA) -> BacktestResult:
    """Strategy 4: SMA Triple Score (0-5) → dynamic position sizing."""
    r = BacktestResult(name="SMA Triple Score")
    r.dates = data.dates
    n = len(data.closes)

    score_to_pct = {0: 0.0, 1: 0.2, 2: 0.4, 3: 0.6, 4: 0.8, 5: 1.0}

    cash = INITIAL_CAPITAL
    shares = 0.0
    current_pct = 0.0
    equity = []
    positions = []
    trades = []

    for i in range(n):
        close = data.closes[i]
        sma20 = ma.sma20[i] if i < len(ma.sma20) else None
        sma50 = ma.sma50[i] if i < len(ma.sma50) else None
        sma200 = ma.sma200[i] if i < len(ma.sma200) else None

        if sma20 is not None and sma50 is not None and sma200 is not None:
            score = 0
            if close > sma20:
                score += 1
            if close > sma50:
                score += 1
            if close > sma200:
                score += 1
            if sma20 > sma50:
                score += 1
            if sma50 > sma200:
                score += 1

            target_pct = score_to_pct[score]

            if target_pct != current_pct:
                # Rebalance: liquidate all, then re-enter at target %
                total_value = cash + shares * close
                cash = total_value * (1 - target_pct)
                shares = (total_value * target_pct) / close if target_pct > 0 else 0.0

                if target_pct > current_pct:
                    trades.append(
                        TradeRecord(data.dates[i], "BUY", close, target_pct)
                    )
                else:
                    trades.append(
                        TradeRecord(data.dates[i], "SELL", close, target_pct)
                    )
                current_pct = target_pct

        equity.append(cash + shares * close)
        positions.append(current_pct)

    r.equity_curve = equity
    r.position_series = positions
    r.trades = trades
    years = (data.dates[-1] - data.dates[0]).days / 365.25
    calc_metrics(r, years)
    return r


# ============================================================
# Generic Score Strategy Engine
# ============================================================
def run_score_strategy(
    name: str,
    data: MarketData,
    ma: PrecomputedMA,
    score_fn: Callable[[int], int | None],
    max_score: int,
    position_map: dict[int, float] | None = None,
    risk_filter_fn: Callable[[int, float, float], float] | None = None,
) -> BacktestResult:
    """Run a score-based strategy with configurable scoring and position mapping.

    Args:
        name: Strategy name.
        score_fn: bar index → score (None if insufficient data).
        max_score: Maximum possible score for linear pct = score/max_score.
        position_map: Optional dict mapping score → target_pct (overrides linear).
                      Supports pct > 1.0 for leverage.
        risk_filter_fn: Optional function (index, target_pct, drawdown) → adjusted_pct.
                        drawdown is 0.0 to -1.0 (e.g. -0.20 = 20% drawdown from peak).
    """
    r = BacktestResult(name=name)
    r.dates = data.dates
    n = len(data.closes)

    cash = INITIAL_CAPITAL
    shares = 0.0
    current_pct = 0.0
    equity = []
    positions = []
    trades = []
    equity_peak = INITIAL_CAPITAL

    for i in range(n):
        close = data.closes[i]
        current_equity = cash + shares * close

        # Track drawdown from equity peak
        if current_equity > equity_peak:
            equity_peak = current_equity
        current_dd = (current_equity / equity_peak - 1.0) if equity_peak > 0 else 0.0

        score = score_fn(i)

        if score is not None:
            if position_map is not None:
                target_pct = position_map.get(score, 0.0)
            else:
                target_pct = score / max_score if max_score > 0 else 0.0

            if risk_filter_fn is not None:
                target_pct = risk_filter_fn(i, target_pct, current_dd)

            if target_pct != current_pct:
                total_value = cash + shares * close
                # Leverage: when target_pct > 1.0, shares cost > total_value, cash goes negative
                shares = (total_value * target_pct) / close if target_pct > 0 else 0.0
                cash = total_value - shares * close  # negative when leveraged

                if target_pct > current_pct:
                    trades.append(TradeRecord(data.dates[i], "BUY", close, target_pct))
                else:
                    trades.append(TradeRecord(data.dates[i], "SELL", close, target_pct))
                current_pct = target_pct

        equity.append(cash + shares * close)
        positions.append(current_pct)

    r.equity_curve = equity
    r.position_series = positions
    r.trades = trades
    years = (data.dates[-1] - data.dates[0]).days / 365.25
    calc_metrics(r, years)
    return r


# ============================================================
# V2 Score Functions
# ============================================================
def _sma_score(i: int, ma: PrecomputedMA, data: MarketData) -> int | None:
    """Original 5-point SMA score."""
    sma20 = ma.sma20[i] if i < len(ma.sma20) else None
    sma50 = ma.sma50[i] if i < len(ma.sma50) else None
    sma200 = ma.sma200[i] if i < len(ma.sma200) else None
    if sma20 is None or sma50 is None or sma200 is None:
        return None
    close = data.closes[i]
    score = 0
    if close > sma20:
        score += 1
    if close > sma50:
        score += 1
    if close > sma200:
        score += 1
    if sma20 > sma50:
        score += 1
    if sma50 > sma200:
        score += 1
    return score


def _ema_score(i: int, ma: PrecomputedMA, data: MarketData) -> int | None:
    """Strategy 6: Same 5 conditions using EMA20/50/200."""
    ema20 = ma.ema20[i] if i < len(ma.ema20) else None
    ema50 = ma.ema50[i] if i < len(ma.ema50) else None
    ema200 = ma.ema200[i] if i < len(ma.ema200) else None
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    close = data.closes[i]
    score = 0
    if close > ema20:
        score += 1
    if close > ema50:
        score += 1
    if close > ema200:
        score += 1
    if ema20 > ema50:
        score += 1
    if ema50 > ema200:
        score += 1
    return score


def _score_momentum(i: int, ma: PrecomputedMA, data: MarketData) -> int | None:
    """Strategy 7: 5 original + 20d/60d momentum = 7 max."""
    base = _sma_score(i, ma, data)
    if base is None:
        return None
    if i < 60:
        return None
    close = data.closes[i]
    score = base
    if close > data.closes[i - 20]:
        score += 1
    if close > data.closes[i - 60]:
        score += 1
    return score


def _score_vix(i: int, ma: PrecomputedMA, data: MarketData) -> int | None:
    """Strategy 8: 5 original + VIX regime adjustment (max 6)."""
    base = _sma_score(i, ma, data)
    if base is None:
        return None
    vix = data.vix[i]
    score = base
    if vix > 25:
        score -= 1
    elif vix < 15:
        score += 1
    return max(0, min(6, score))


# ============================================================
# V2 Strategy Builders
# ============================================================
def build_v2_strategies(data: MarketData, ma: PrecomputedMA) -> list[BacktestResult]:
    """Build all 8 V2 strategy variants."""
    results = []

    # --- A. Signal improvements ---
    # 6. EMA Triple Score
    results.append(run_score_strategy(
        "EMA Triple Score", data, ma,
        score_fn=lambda i: _ema_score(i, ma, data),
        max_score=5,
    ))

    # 7. Score+Momentum
    results.append(run_score_strategy(
        "Score+Momentum", data, ma,
        score_fn=lambda i: _score_momentum(i, ma, data),
        max_score=7,
    ))

    # 8. Score+VIX
    results.append(run_score_strategy(
        "Score+VIX", data, ma,
        score_fn=lambda i: _score_vix(i, ma, data),
        max_score=6,
    ))

    # --- B. Position management (all use original SMA 5-point score) ---
    sma_score_fn = lambda i: _sma_score(i, ma, data)

    # 9. Score Aggressive
    results.append(run_score_strategy(
        "Score Aggressive", data, ma,
        score_fn=sma_score_fn, max_score=5,
        position_map={0: 0.0, 1: 0.0, 2: 0.3, 3: 0.6, 4: 1.0, 5: 1.0},
    ))

    # 10. Score Convex: (score/5)²
    results.append(run_score_strategy(
        "Score Convex", data, ma,
        score_fn=sma_score_fn, max_score=5,
        position_map={s: (s / 5) ** 2 for s in range(6)},
    ))

    # 11. Score Leverage: up to 300%
    results.append(run_score_strategy(
        "Score Leverage", data, ma,
        score_fn=sma_score_fn, max_score=5,
        position_map={0: 0.0, 1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 3.0},
    ))

    # 12. Score Moderate Lev: up to 200%
    results.append(run_score_strategy(
        "Score Moderate Lev", data, ma,
        score_fn=sma_score_fn, max_score=5,
        position_map={0: 0.0, 1: 0.3, 2: 0.6, 3: 1.0, 4: 1.5, 5: 2.0},
    ))

    # 13. Score Binary≥3 Lev: 200% or 0%
    results.append(run_score_strategy(
        "Score Binary≥3 Lev", data, ma,
        score_fn=sma_score_fn, max_score=5,
        position_map={0: 0.0, 1: 0.0, 2: 0.0, 3: 2.0, 4: 2.0, 5: 2.0},
    ))

    # 14. Momentum+Leverage: 7-score momentum signal + leverage 0%-300%
    momentum_score_fn = lambda i: _score_momentum(i, ma, data)
    momentum_map = {0: 0.0, 1: 0.0, 2: 0.5, 3: 1.0, 4: 1.5, 5: 2.0, 6: 2.5, 7: 3.0}
    
    results.append(run_score_strategy(
        "Momentum+Leverage", data, ma,
        score_fn=momentum_score_fn, max_score=7,
        position_map=momentum_map,
    ))

    # --- C. Advanced Risk & Leverage Management ---

    # 15. Momentum+Lev (Vol Target) — Tier3 only
    # Target vol=15%. vol_scalar capped at 2.0 to prevent over-leverage in low-VIX.
    def vol_target_risk(i: int, base_pct: float, dd: float) -> float:
        if base_pct == 0:
            return 0.0
        vix = data.vix[i]
        vol_scalar = min(2.0, 15.0 / vix) if vix > 0 else 1.0
        return max(0.0, min(3.0, base_pct * vol_scalar))

    results.append(run_score_strategy(
        "Moment+Lev (VolTgt)", data, ma,
        score_fn=momentum_score_fn, max_score=7,
        position_map=momentum_map,
        risk_filter_fn=vol_target_risk,
    ))

    # 16. Momentum+Lev (VIX Term Structure) — graduated response
    # VIX/VIX3M ratio triggers: severe→clear, mild→delever, flat→cap
    def term_structure_risk(i: int, base_pct: float, dd: float) -> float:
        vix, vix3m = data.vix[i], data.vix3m[i]
        ratio = vix / vix3m if vix3m > 0 else 1.0

        if ratio > 1.10:       # severe backwardation → clear all
            return 0.0
        elif ratio > 1.02:     # mild backwardation → cap at 1.0 (no leverage)
            return min(1.0, base_pct)
        elif ratio > 0.98:     # near-flat → cap at 1.5
            return min(1.5, base_pct)
        else:                  # normal contango → pass through
            return base_pct

    results.append(run_score_strategy(
        "Moment+Lev (VIXTerm)", data, ma,
        score_fn=momentum_score_fn, max_score=7,
        position_map=momentum_map,
        risk_filter_fn=term_structure_risk,
    ))

    # 17. Momentum+Lev (SmartRisk) — 3-tier: panic + bear + vol-target
    def smart_risk_filter(i: int, base_pct: float, dd: float) -> float:
        if base_pct == 0:
            return 0.0
        vix, vix3m = data.vix[i], data.vix3m[i]

        # === Tier 1: Panic Circuit Breaker ===
        # VIX term structure inversion (covers 2020 COVID, 2025 Tariff, 2018Q4)
        term_ratio = vix / vix3m if vix3m > 0 else 1.0
        if term_ratio > 1.10:
            return 0.0                          # severe panic → full exit
        if term_ratio > 1.02:
            base_pct = min(0.5, base_pct)       # mild panic → ≤50%

        # VIX 5-day spike (covers fast flash crashes)
        if i >= 5:
            vix_5ago = data.vix[i - 5]
            if vix - vix_5ago > 10:
                base_pct = min(0.5, base_pct)   # VIX jumped >10pts in 5d → ≤50%

        # === Tier 2: Bear Market Limiter (covers 2022 slow bear) ===
        sma200_now = ma.sma200[i]
        sma200_20ago = ma.sma200[i - 20] if i >= 20 else None
        if sma200_now and sma200_20ago:
            if sma200_now < sma200_20ago:       # SMA200 declining
                base_pct = min(1.0, base_pct)   # no leverage allowed
            close = data.closes[i]
            if close < sma200_now:              # price below SMA200
                base_pct = min(0.5, base_pct)   # further reduce

        # === Tier 3: Volatility Targeting ===
        vol_scalar = min(2.0, 15.0 / vix) if vix > 0 else 1.0
        adj_pct = base_pct * vol_scalar

        return max(0.0, min(3.0, adj_pct))

    results.append(run_score_strategy(
        "Moment+Lev (SmartRisk)", data, ma,
        score_fn=momentum_score_fn, max_score=7,
        position_map=momentum_map,
        risk_filter_fn=smart_risk_filter,
    ))

    # 18. Momentum+Lev (AdaptiveRisk) — SmartRisk + VIX9D + tighter bear filter
    def adaptive_risk_filter(i: int, base_pct: float, dd: float) -> float:
        if base_pct == 0:
            return 0.0
        vix, vix3m = data.vix[i], data.vix3m[i]
        vix9d = data.vix9d[i]

        # === Tier 0: Ultra-short-term Panic (VIX9D) ===
        # VIX9D/VIX > 1.20 = near-term fear spikes far above 30d expectation
        if vix > 0 and vix9d / vix > 1.20:
            base_pct = min(0.5, base_pct)

        # === Tier 1: Panic Circuit Breaker ===
        term_ratio = vix / vix3m if vix3m > 0 else 1.0
        if term_ratio > 1.05:
            return 0.0                          # tighter than SmartRisk (1.10→1.05)
        if term_ratio > 1.00:
            base_pct = min(0.5, base_pct)       # tighter (1.02→1.00)

        if i >= 5:
            vix_5ago = data.vix[i - 5]
            if vix - vix_5ago > 8:              # tighter (10→8)
                base_pct = min(0.5, base_pct)

        # === Tier 2: Bear Market Limiter (tighter SMA200 slope) ===
        sma200_now = ma.sma200[i]
        sma200_20ago = ma.sma200[i - 20] if i >= 20 else None
        if sma200_now and sma200_20ago:
            if sma200_now < sma200_20ago:
                base_pct = min(1.0, base_pct)
            close = data.closes[i]
            if close < sma200_now:
                base_pct = min(0.3, base_pct)   # tighter (0.5→0.3) below SMA200

        # === Tier 3: Volatility Targeting ===
        vol_scalar = min(2.0, 15.0 / vix) if vix > 0 else 1.0
        adj_pct = base_pct * vol_scalar

        return max(0.0, min(3.0, adj_pct))

    results.append(run_score_strategy(
        "Moment+Lev (Adaptive)", data, ma,
        score_fn=momentum_score_fn, max_score=7,
        position_map=momentum_map,
        risk_filter_fn=adaptive_risk_filter,
    ))

    return results


# ============================================================
# Terminal Output
# ============================================================
def print_comparison(results: list[BacktestResult]) -> None:
    """Print metrics comparison table, sorted by Sharpe."""
    sorted_r = sorted(results, key=lambda r: r.sharpe, reverse=True)

    print("\n" + "=" * 115)
    print("MA Signal Search V3 — Strategy Comparison (sorted by Sharpe)")
    print(
        f"Symbol: {SYMBOL}  |  Period: {START_DATE} -> {END_DATE}  |  Capital: ${INITIAL_CAPITAL:,.0f}"
    )
    print("=" * 115)

    header = (
        f"{'#':>3} {'Strategy':<22} {'Return':>9} {'AnnRet':>9} {'MaxDD':>9} "
        f"{'Sharpe':>8} {'WinRate':>8} {'Trades':>7} {'InMkt%':>7} {'Final$':>13}"
    )
    print(header)
    print("-" * 115)

    for rank, r in enumerate(sorted_r, 1):
        final_val = r.equity_curve[-1] if r.equity_curve else 0
        print(
            f"{rank:>3} {r.name:<22} {r.total_return:>+8.1f}% {r.annualized_return:>+8.1f}% "
            f"{r.max_drawdown:>+8.1f}% {r.sharpe:>8.2f} {r.win_rate:>7.0f}% "
            f"{r.num_trades:>7} {r.time_in_market:>6.0f}% "
            f"${final_val:>12,.0f}"
        )

    print("=" * 115)


# ============================================================
# HTML Report Generation
# ============================================================
def _get_color(name: str, results: list[BacktestResult]) -> str:
    """Get color for a strategy by its index in results list."""
    for idx, r in enumerate(results):
        if r.name == name:
            return COLOR_PALETTE[idx % len(COLOR_PALETTE)]
    return "#333"


def generate_report(results: list[BacktestResult], data: MarketData, ma: PrecomputedMA) -> None:
    """Generate interactive HTML report with Plotly."""
    if not PLOTLY_AVAILABLE:
        print("[WARN] Plotly not installed, skipping HTML report.")
        return

    chart_htmls: list[str] = []

    # --- A. Metrics Matrix Table ---
    chart_htmls.append(_build_metrics_table(results))

    # --- B. Equity Curves ---
    chart_htmls.append(_build_equity_curves(results))

    # --- C. Drawdown Curves ---
    chart_htmls.append(_build_drawdown_curves(results))

    # --- D+. Signal deep-dive for Top 5 by Sharpe (excluding Buy & Hold) ---
    non_bh = [r for r in results if r.name != "Buy & Hold"]
    top5 = sorted(non_bh, key=lambda r: r.sharpe, reverse=True)[:5]
    for idx, r in enumerate(top5):
        chart_htmls.append(_build_signal_chart(r, data, ma, results, section_idx=idx))

    # Assemble HTML
    charts_combined = "\n".join(
        f'<div class="chart-container">{html}</div>' for html in chart_htmls
    )

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MA Signal Search V3 — {SYMBOL}</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0; padding: 20px;
            background-color: #f0f2f5;
        }}
        .container {{
            max-width: 1400px; margin: 0 auto;
            background: white; padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        }}
        h1 {{ text-align: center; color: #1a1a2e; margin-bottom: 5px; }}
        .subtitle {{ text-align: center; color: #666; margin-bottom: 30px; font-size: 14px; }}
        .chart-container {{ margin: 25px 0; }}
        h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 8px; }}
        .footer {{
            text-align: center; color: #999; margin-top: 40px;
            padding-top: 20px; border-top: 1px solid #eee; font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>MA Signal Search V3 Report</h1>
        <p class="subtitle">{SYMBOL} | {START_DATE} &rarr; {END_DATE} | Initial Capital: ${INITIAL_CAPITAL:,.0f}</p>
        {charts_combined}
        <div class="footer">
            <p>Generated by Option Quant Trade System | {date.today().isoformat()}</p>
        </div>
    </div>
</body>
</html>"""

    REPORT_FILE.write_text(full_html, encoding="utf-8")
    print(f"\n[OK] HTML report saved to: {REPORT_FILE}")


def _build_metrics_table(results: list[BacktestResult]) -> str:
    """Section A: Metrics comparison table."""
    # Sort by Sharpe descending
    sorted_r = sorted(results, key=lambda r: r.sharpe, reverse=True)

    names = [r.name for r in sorted_r]
    total_ret = [f"{r.total_return:+.1f}%" for r in sorted_r]
    ann_ret = [f"{r.annualized_return:+.1f}%" for r in sorted_r]
    max_dd = [f"{r.max_drawdown:+.1f}%" for r in sorted_r]
    sharpe = [f"{r.sharpe:.2f}" for r in sorted_r]
    win_rate = [f"{r.win_rate:.0f}%" for r in sorted_r]
    trades = [str(r.num_trades) for r in sorted_r]
    in_mkt = [f"{r.time_in_market:.0f}%" for r in sorted_r]
    final_v = [f"${r.equity_curve[-1]:,.0f}" if r.equity_curve else "$0" for r in sorted_r]

    # Color cells: green for positive, red for negative
    def color_ret(vals):
        colors = []
        for v in vals:
            num = float(v.replace("%", "").replace("$", "").replace(",", "").replace("+", ""))
            colors.append("#e8f5e9" if num > 0 else "#ffebee" if num < 0 else "white")
        return colors

    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=["<b>Strategy</b>", "<b>Total Return</b>", "<b>Ann. Return</b>",
                            "<b>Max DD</b>", "<b>Sharpe</b>", "<b>Win Rate</b>",
                            "<b>Trades</b>", "<b>In Market</b>", "<b>Final Value</b>"],
                    fill_color="#2c3e50",
                    font=dict(color="white", size=13),
                    align="center",
                    height=35,
                ),
                cells=dict(
                    values=[names, total_ret, ann_ret, max_dd, sharpe,
                            win_rate, trades, in_mkt, final_v],
                    fill_color=[
                        ["white"] * len(names),
                        color_ret(total_ret),
                        color_ret(ann_ret),
                        color_ret(max_dd),
                        color_ret(sharpe),
                        ["white"] * len(names),
                        ["white"] * len(names),
                        ["white"] * len(names),
                        ["white"] * len(names),
                    ],
                    font=dict(size=12),
                    align="center",
                    height=30,
                ),
            )
        ]
    )
    fig.update_layout(
        title="<b>A. Strategy Metrics Comparison</b> (sorted by Sharpe)",
        height=max(300, 50 + 35 + 30 * len(results)),
        margin=dict(l=20, r=20, t=50, b=10),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_equity_curves(results: list[BacktestResult]) -> str:
    """Section B: Overlaid equity curves. B&H dashed, Top5 solid colored, rest gray."""
    non_bh = [r for r in results if r.name != "Buy & Hold"]
    top5_names = {r.name for r in sorted(non_bh, key=lambda r: r.sharpe, reverse=True)[:5]}

    fig = go.Figure()
    # Draw non-top5 first (background gray)
    for r in results:
        if r.name == "Buy & Hold" or r.name in top5_names:
            continue
        fig.add_trace(
            go.Scatter(
                x=r.dates, y=r.equity_curve,
                name=r.name, mode="lines",
                line=dict(color="#cccccc", width=1),
                opacity=0.5, legendgroup="others",
            )
        )
    # Buy & Hold dashed
    bh = next((r for r in results if r.name == "Buy & Hold"), None)
    if bh:
        fig.add_trace(
            go.Scatter(
                x=bh.dates, y=bh.equity_curve,
                name="Buy & Hold", mode="lines",
                line=dict(color="#95a5a6", width=2, dash="dash"),
            )
        )
    # Top 5 colored
    for r in sorted(non_bh, key=lambda r: r.sharpe, reverse=True)[:5]:
        color = _get_color(r.name, results)
        fig.add_trace(
            go.Scatter(
                x=r.dates, y=r.equity_curve,
                name=r.name, mode="lines",
                line=dict(color=color, width=2),
            )
        )

    fig.update_layout(
        title="<b>B. Equity Curves</b> (Top 5 by Sharpe highlighted)",
        xaxis_title="Date", yaxis_title="Portfolio Value ($)",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=550,
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
        margin=dict(l=80, r=20, t=50, b=40),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_drawdown_curves(results: list[BacktestResult]) -> str:
    """Section C: Drawdown curves. Same Top5 + B&H highlighting."""
    non_bh = [r for r in results if r.name != "Buy & Hold"]
    top5_names = {r.name for r in sorted(non_bh, key=lambda r: r.sharpe, reverse=True)[:5]}

    fig = go.Figure()
    # Non-top5 gray
    for r in results:
        if r.name == "Buy & Hold" or r.name in top5_names or not r.drawdown_curve:
            continue
        fig.add_trace(
            go.Scatter(
                x=r.dates, y=r.drawdown_curve,
                name=r.name, mode="lines",
                line=dict(color="#cccccc", width=1),
                opacity=0.4, legendgroup="others",
            )
        )
    # B&H
    bh = next((r for r in results if r.name == "Buy & Hold"), None)
    if bh and bh.drawdown_curve:
        fig.add_trace(
            go.Scatter(
                x=bh.dates, y=bh.drawdown_curve,
                name="Buy & Hold", mode="lines",
                line=dict(color="#95a5a6", width=1.5, dash="dash"),
            )
        )
    # Top 5
    for r in sorted(non_bh, key=lambda r: r.sharpe, reverse=True)[:5]:
        if not r.drawdown_curve:
            continue
        color = _get_color(r.name, results)
        fig.add_trace(
            go.Scatter(
                x=r.dates, y=r.drawdown_curve,
                name=r.name, mode="lines",
                line=dict(color=color, width=1.5),
            )
        )

    fig.update_layout(
        title="<b>C. Drawdown Curves</b> (Top 5 by Sharpe highlighted)",
        xaxis_title="Date", yaxis_title="Drawdown (%)",
        yaxis_ticksuffix="%",
        hovermode="x unified",
        height=450,
        legend=dict(x=0.01, y=-0.15, orientation="h", bgcolor="rgba(255,255,255,0.8)"),
        margin=dict(l=80, r=20, t=50, b=60),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_signal_chart(
    result: BacktestResult, data: MarketData, ma: PrecomputedMA,
    all_results: list[BacktestResult], section_idx: int = 0,
) -> str:
    """Per-strategy signal chart: price + MA lines + buy/sell markers + position shading."""
    name = result.name

    # Determine max position % for y-axis range
    max_pos = max(result.position_series) if result.position_series else 1.0
    pos_y_max = max(1.05, max_pos + 0.05) * 100

    # 3 rows: price+signals, position%, equity
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.55, 0.15, 0.30],
        subplot_titles=[
            f"{name} — Price & Signals",
            "Position %",
            "Equity Curve",
        ],
    )

    dates = data.dates

    # Row 1: Price
    fig.add_trace(
        go.Scatter(
            x=dates, y=data.closes,
            name="Price", mode="lines",
            line=dict(color="#333", width=1.2),
            showlegend=True,
        ),
        row=1, col=1,
    )

    # MA lines — show EMA for EMA-based, SMA for others
    uses_ema = "EMA" in name
    if uses_ema:
        _add_ma_trace(fig, dates, ma.ema20, "EMA20", "#2ecc71", row=1)
        _add_ma_trace(fig, dates, ma.ema50, "EMA50", "#3498db", row=1)
        _add_ma_trace(fig, dates, ma.ema200, "EMA200", "#e67e22", row=1)
    elif name in ("SMA200/Price",):
        _add_ma_trace(fig, dates, ma.sma200, "SMA200", "#e67e22", row=1)
    elif name == "SMA50/SMA200":
        _add_ma_trace(fig, dates, ma.sma50, "SMA50", "#3498db", row=1)
        _add_ma_trace(fig, dates, ma.sma200, "SMA200", "#e67e22", row=1)
    elif name == "Price/SMA50/SMA20":
        _add_ma_trace(fig, dates, ma.sma20, "SMA20", "#2ecc71", row=1)
        _add_ma_trace(fig, dates, ma.sma50, "SMA50", "#3498db", row=1)
    else:
        # Default: show all 3 SMAs for score-based strategies
        _add_ma_trace(fig, dates, ma.sma20, "SMA20", "#2ecc71", row=1)
        _add_ma_trace(fig, dates, ma.sma50, "SMA50", "#3498db", row=1)
        _add_ma_trace(fig, dates, ma.sma200, "SMA200", "#e67e22", row=1)

    # Position shading (background color for invested periods)
    _add_position_shading(fig, dates, result.position_series, row=1)

    # Buy/Sell markers
    buy_dates = [t.date for t in result.trades if t.action == "BUY"]
    buy_prices = [t.price for t in result.trades if t.action == "BUY"]
    sell_dates = [t.date for t in result.trades if t.action == "SELL"]
    sell_prices = [t.price for t in result.trades if t.action == "SELL"]

    if buy_dates:
        fig.add_trace(
            go.Scatter(
                x=buy_dates, y=buy_prices,
                name="BUY", mode="markers",
                marker=dict(symbol="triangle-up", size=10, color="#2ecc71",
                            line=dict(width=1, color="#27ae60")),
            ),
            row=1, col=1,
        )
    if sell_dates:
        fig.add_trace(
            go.Scatter(
                x=sell_dates, y=sell_prices,
                name="SELL", mode="markers",
                marker=dict(symbol="triangle-down", size=10, color="#e74c3c",
                            line=dict(width=1, color="#c0392b")),
            ),
            row=1, col=1,
        )

    # Row 2: Position %
    fig.add_trace(
        go.Scatter(
            x=dates, y=[p * 100 for p in result.position_series],
            name="Position %", mode="lines",
            line=dict(color="#9b59b6", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(155, 89, 182, 0.15)",
            showlegend=False,
        ),
        row=2, col=1,
    )
    # Add 100% reference line if leveraged
    if max_pos > 1.0:
        fig.add_hline(y=100, line_dash="dot", line_color="red", opacity=0.5, row=2, col=1)

    # Row 3: Equity
    color = _get_color(name, all_results)
    fig.add_trace(
        go.Scatter(
            x=dates, y=result.equity_curve,
            name="Equity", mode="lines",
            line=dict(color=color, width=1.5),
            showlegend=False,
        ),
        row=3, col=1,
    )

    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="%", range=[-5, pos_y_max], row=2, col=1)
    fig.update_yaxes(title_text="$", tickformat="$,.0f", row=3, col=1)
    fig.update_xaxes(title_text="Date", row=3, col=1)

    fig.update_layout(
        height=800,
        hovermode="x unified",
        legend=dict(x=0.01, y=1.0, bgcolor="rgba(255,255,255,0.8)"),
        margin=dict(l=80, r=20, t=60, b=40),
    )

    section_letter = chr(ord("D") + section_idx)

    return f"<h2>{section_letter}. {name} (Top {section_idx + 1} by Sharpe)</h2>" + fig.to_html(
        full_html=False, include_plotlyjs=False
    )


def _add_ma_trace(fig, dates, series, name, color, row=1):
    """Add a moving average line trace."""
    # Filter None values for clean display
    x_vals = [d for d, v in zip(dates, series) if v is not None]
    y_vals = [v for v in series if v is not None]
    fig.add_trace(
        go.Scatter(
            x=x_vals, y=y_vals,
            name=name, mode="lines",
            line=dict(color=color, width=1, dash="dot"),
            opacity=0.8,
        ),
        row=row, col=1,
    )


def _add_position_shading(fig, dates, position_series, row=1):
    """Add green background shading for invested periods using vrects."""
    # Find contiguous invested blocks
    in_block = False
    block_start = None

    for i, pos in enumerate(position_series):
        if pos > 0 and not in_block:
            block_start = dates[i]
            in_block = True
        elif pos == 0 and in_block:
            fig.add_vrect(
                x0=block_start, x1=dates[i],
                fillcolor="rgba(46, 204, 113, 0.08)",
                layer="below", line_width=0,
                row=row, col=1,
            )
            in_block = False

    # Close last block if still open
    if in_block and block_start:
        fig.add_vrect(
            x0=block_start, x1=dates[-1],
            fillcolor="rgba(46, 204, 113, 0.08)",
            layer="below", line_width=0,
            row=row, col=1,
        )


# ============================================================
# Main
# ============================================================
def main():
    print("Loading SPY daily prices + VIX/VIX3M/VIX9D...")
    data = load_market_data()
    print(f"  Loaded {len(data.dates)} trading days: {data.dates[0]} -> {data.dates[-1]}")
    print(f"  Price range: ${data.closes[0]:.2f} -> ${data.closes[-1]:.2f}")
    print(f"  VIX range: {min(data.vix):.1f} -> {max(data.vix):.1f}")
    print(f"  VIX3M range: {min(data.vix3m):.1f} -> {max(data.vix3m):.1f}")
    print(f"  VIX9D range: {min(data.vix9d):.1f} -> {max(data.vix9d):.1f}")

    print("\nPrecomputing SMA + EMA series...")
    ma = precompute_ma(data)

    print("Running V1 strategies (1-5)...")
    v1_results = [
        run_buy_and_hold(data, ma),
        run_sma200_price(data, ma),
        run_sma50_sma200(data, ma),
        run_price_sma50_sma20(data, ma),
        run_sma_triple_score(data, ma),
    ]

    print("Running V2 strategies (6-14) + V3 risk filters (15-18)...")
    v2_results = build_v2_strategies(data, ma)

    results = v1_results + v2_results
    print(f"\nTotal: {len(results)} strategies")

    print_comparison(results)
    generate_report(results, data, ma)

    # Open in browser
    import webbrowser
    webbrowser.open(f"file://{REPORT_FILE.resolve()}")


if __name__ == "__main__":
    main()
