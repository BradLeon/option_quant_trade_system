import sys
from datetime import date, timedelta
import time
import logging

logging.basicConfig(level=logging.WARNING)

sys.path.append("/Users/liuchao/Code/Quant/option_quant_trade_system")
from src.backtest.data.duckdb_provider import DuckDBProvider

def run_test():
    provider = DuckDBProvider(data_dir="/Volumes/ORICO/option_quant")
    
    start_date = date(2024, 6, 1)
    
    # Time get_stock_quote for SPY for 100 days
    t0 = time.time()
    for i in range(100):
        current_date = start_date + timedelta(days=i)
        provider.set_as_of_date(current_date)
        provider.get_stock_quote("SPY")
    t1 = time.time()
    print(f"get_stock_quote(100 days): {t1-t0:.4f} seconds")

    # Time get_stock_beta for SPY for 100 days
    t0 = time.time()
    for i in range(100):
        current_date = start_date + timedelta(days=i)
        provider.set_as_of_date(current_date)
        provider.get_stock_beta("SPY", as_of_date=current_date)
    t1 = time.time()
    print(f"get_stock_beta(100 days): {t1-t0:.4f} seconds")

if __name__ == "__main__":
    run_test()
