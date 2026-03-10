"""
Standalone Vectorized Backtester for SMA Timing Strategies on SPY.

Strategies:
1. Price vs SMA200 (Full Position)
2. SMA50 vs SMA200 (Full Position)
3. Price > SMA50 AND SMA20 > SMA50 (Full Position)
4. 3-Line Scoring (Dynamic Position)
5. Buy & Hold
"""

import os
import sys
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date

# Add src to path to import DuckDBProvider
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.backtest.data.duckdb_provider import DuckDBProvider
from src.data.models.stock import KlineType

# Configuration
SYMBOL = "SPY"
START_DATE = date(2010, 1, 1)  # Fetch more history for initial SMA calculation
BT_START_DATE = date(2016, 9, 1) # Actual backtest start date
END_DATE = date(2026, 3, 1)
TRANSACTION_COST = 0.0005  # 0.05% one-way cost
RISK_FREE_RATE = 0.02

def fetch_data():
    provider = DuckDBProvider(data_dir="/Volumes/ORICO/option_quant", as_of_date=END_DATE)
    klines = provider.get_history_kline(SYMBOL, KlineType.DAY, START_DATE, END_DATE)
    
    if not klines:
        print("No data found!")
        sys.exit(1)
        
    data = []
    for k in klines:
        data.append({
            "date": pd.to_datetime(k.timestamp),
            "open": k.open,
            "high": k.high,
            "low": k.low,
            "close": k.close,
            "volume": k.volume
        })
        
    df = pd.DataFrame(data)
    df = df.sort_values("date").set_index("date")
    return df

def calculate_indicators(df):
    df["sma20"] = df["close"].rolling(window=20).mean()
    df["sma50"] = df["close"].rolling(window=50).mean()
    df["sma200"] = df["close"].rolling(window=200).mean()
    # Daily return of the underlying asset
    df["return"] = df["close"].pct_change()
    return df

def generate_signals(df):
    df = df.copy()
    
    # Strat 1: Price vs SMA200
    df["pos_strat1"] = np.where(df["close"] > df["sma200"], 1.0, 0.0)
    
    # Strat 2: SMA50 vs SMA200
    df["pos_strat2"] = np.where(df["sma50"] > df["sma200"], 1.0, 0.0)
    
    # Strat 3: Price/SMA50/SMA20
    # Entry: Price > SMA50 AND SMA20 > SMA50
    # Exit: Price < SMA50 AND SMA20 < SMA50
    # Otherwise: keep previous position
    cond_entry = (df["close"] > df["sma50"]) & (df["sma20"] > df["sma50"])
    cond_exit = (df["close"] < df["sma50"]) & (df["sma20"] < df["sma50"])
    
    pos3 = np.zeros(len(df))
    current_pos = 0.0
    for i in range(len(df)):
        if cond_entry.iloc[i]:
            current_pos = 1.0
        elif cond_exit.iloc[i]:
            current_pos = 0.0
        pos3[i] = current_pos
    df["pos_strat3"] = pos3
    
    # Strat 4: 3-Line Scoring
    # 1. Close > SMA20
    # 2. Close > SMA50
    # 3. Close > SMA200
    # 4. SMA20 > SMA50
    # 5. SMA50 > SMA200
    score = (
        (df["close"] > df["sma20"]).astype(int) +
        (df["close"] > df["sma50"]).astype(int) +
        (df["close"] > df["sma200"]).astype(int) +
        (df["sma20"] > df["sma50"]).astype(int) +
        (df["sma50"] > df["sma200"]).astype(int)
    )
    # Mapping score to position: 0 -> 0.0, 1 -> 0.2, ..., 5 -> 1.0
    df["pos_strat4"] = score * 0.2
    
    # Strat 5: Buy & Hold
    df["pos_strat5"] = 1.0
    
    # Shift positions by 1 day to simulate buying at today's close or tomorrow's open.
    # We use today's close to calculate signal -> position applies to tomorrow's return.
    for i in range(1, 6):
        df[f"target_pos_{i}"] = df[f"pos_strat{i}"].shift(1).fillna(0.0)
        
    return df

def calculate_performance(df):
    results = {}
    bt_df = df[df.index >= pd.to_datetime(BT_START_DATE)].copy()
    
    strat_names = {
        1: "Price vs SMA200",
        2: "SMA50 vs SMA200",
        3: "Price/SMA50/SMA20",
        4: "3-Line Scoring (Dynamic)",
        5: "Buy & Hold"
    }
    
    for i in range(1, 6):
        target_pos = bt_df[f"target_pos_{i}"]
        
        # Calculate daily change in position to apply transaction costs
        pos_change = target_pos.diff().fillna(target_pos.iloc[0])
        trade_costs = pos_change.abs() * TRANSACTION_COST
        
        # Strategy return = position * asset_return - trade_costs
        strat_ret = target_pos * bt_df["return"] - trade_costs
        
        # Calculate equity curve
        equity_curve = (1 + strat_ret).cumprod()
        
        # Drawdown
        rolling_max = equity_curve.cummax()
        drawdown = equity_curve / rolling_max - 1.0
        max_dd = drawdown.min()
        
        # Metrics
        total_return = equity_curve.iloc[-1] - 1.0
        years = (bt_df.index[-1] - bt_df.index[0]).days / 365.25
        cagr = (1 + total_return) ** (1 / years) - 1.0 if total_return > -1 else -1.0
        
        # Sharpe
        daily_rf = RISK_FREE_RATE / 252
        excess_ret = strat_ret - daily_rf
        sharpe = np.sqrt(252) * excess_ret.mean() / strat_ret.std() if strat_ret.std() > 0 else 0
        
        # Win rate (based on trades, but here we approximate by looking at daily returns > 0 when holding)
        # More accurate trade count:
        num_trades = (pos_change != 0).sum()
        
        # Calculate PnL per trade to get win rate of trades
        is_holding = target_pos > 0
        winning_days = (is_holding & (strat_ret > 0)).sum()
        losing_days = (is_holding & (strat_ret < 0)).sum()
        win_rate = winning_days / (winning_days + losing_days) if (winning_days + losing_days) > 0 else 0
        
        results[i] = {
            "name": strat_names[i],
            "total_return": total_return,
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": sharpe,
            "win_rate_days": win_rate,
            "trades": num_trades,
            "equity_curve": equity_curve,
            "drawdown": drawdown,
            "position": target_pos
        }
        
    return bt_df, results

def print_metrics_table(results):
    print("\n" + "="*85)
    print(f"{'Strategy Name':<28} | {'Total Ret':<9} | {'Ann. Ret':<9} | {'Max DD':<9} | {'Sharpe':<6} | {'WinRate':<7} | {'Trades':<6}")
    print("-" * 85)
    for i in range(1, 6):
        res = results[i]
        print(f"{res['name']:<28} | {res['total_return']:>8.2%} | {res['cagr']:>8.2%} | {res['max_dd']:>8.2%} | {res['sharpe']:>6.2f} | {res['win_rate_days']:>7.1%} | {res['trades']:>6}")
    print("="*85 + "\n")

def plot_results(df, results):
    os.makedirs("reports", exist_ok=True)
    
    # 1. Equity Curves & Drawdown Comparison
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                        subplot_titles=("Cumulative Equity Curve", "Drawdown"))
    
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    
    for i in range(1, 6):
        res = results[i]
        fig.add_trace(go.Scatter(x=res['equity_curve'].index, y=res['equity_curve'], 
                                 mode='lines', name=res['name'], line=dict(color=colors[i-1])), row=1, col=1)
        fig.add_trace(go.Scatter(x=res['drawdown'].index, y=res['drawdown'], 
                                 mode='lines', name=res['name']+" DD", line=dict(color=colors[i-1]), showlegend=False), row=2, col=1)
        
    fig.update_layout(title="SMA Strategies Comparison - Standard SPY Stock Proxy", 
                      height=800, hovermode="x unified",
                      template="plotly_dark")
    fig.update_yaxes(title_text="Equity Value ($1 grows to)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown", row=2, col=1, tickformat='.1%')
    
    out_file = "reports/sma_strategies_comparison.html"
    fig.write_html(out_file)
    print(f"Equity curve comparison saved to {out_file}")
    
    # 2. Plot Strategy 1 (Price vs SMA200) specific buy/sell points
    plot_strategy_signals(df, results, strat_id=1, filename="reports/strat1_price_sma200_signals.html")
    
    # 3. Plot Strategy 4 (3-Line Scoring) positions and SMAs
    plot_strategy_signals(df, results, strat_id=4, filename="reports/strat4_3line_scoring_signals.html")


def plot_strategy_signals(df, results, strat_id, filename):
    res = results[strat_id]
    pos = res["position"]
    pos_change = pos.diff()
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.7, 0.3],
                        subplot_titles=(f"Price & Signals: {res['name']}", "Position Level"))
    
    # Price
    fig.add_trace(go.Scatter(x=df.index, y=df['close'], mode='lines', name='Price', line=dict(color='gray')), row=1, col=1)
    
    # SMAs depending on strategy
    if strat_id in [1, 2, 4]:
        fig.add_trace(go.Scatter(x=df.index, y=df['sma200'], mode='lines', name='SMA200', line=dict(color='yellow')), row=1, col=1)
    if strat_id in [2, 3, 4]:
        fig.add_trace(go.Scatter(x=df.index, y=df['sma50'], mode='lines', name='SMA50', line=dict(color='cyan')), row=1, col=1)
    if strat_id in [3, 4]:
        fig.add_trace(go.Scatter(x=df.index, y=df['sma20'], mode='lines', name='SMA20', line=dict(color='magenta')), row=1, col=1)
        
    # Buy/Sell markers (simplistic view: positive change = buy, negative change = sell)
    buys = df[pos_change > 0]
    sells = df[pos_change < 0]
    
    fig.add_trace(go.Scatter(x=buys.index, y=buys['close'], mode='markers', name='Buy/Increase',
                             marker=dict(symbol='triangle-up', color='green', size=10)), row=1, col=1)
    fig.add_trace(go.Scatter(x=sells.index, y=sells['close'], mode='markers', name='Sell/Reduce',
                             marker=dict(symbol='triangle-down', color='red', size=10)), row=1, col=1)
                             
    # Position
    fig.add_trace(go.Scatter(x=df.index, y=pos, mode='lines', fill='tozeroy', name='Position', line=dict(color='blue')), row=2, col=1)

    fig.update_layout(title=res['name'] + " Analysis", height=800, hovermode="x unified", template="plotly_dark")
    fig.write_html(filename)
    print(f"Strategy {strat_id} signal plot saved to {filename}")

if __name__ == "__main__":
    print(f"Fetching data for {SYMBOL}...")
    df = fetch_data()
    print("Calculating indicators...")
    df = calculate_indicators(df)
    print("Generating simulation signals...")
    df = generate_signals(df)
    print("Evaluating performance...")
    bt_df, results = calculate_performance(df)
    
    print_metrics_table(results)
    plot_results(bt_df, results)

