import sys
import cProfile
import pstats
import logging

logging.basicConfig(level=logging.WARNING)

sys.path.append("/Users/liuchao/Code/Quant/option_quant_trade_system")
from src.backtest.engine.backtest_executor import BacktestExecutor
from src.backtest.config.backtest_config import BacktestConfig

def run_profile():
    config = BacktestConfig.from_yaml("config/backtest/short_put.yaml")
    config.data_dir = "/Volumes/ORICO/option_quant"
    from datetime import date
    config.start_date = date(2024, 6, 1)
    config.end_date = date(2024, 7, 1)
    config.symbols = ["SPY"]
    
    executor = BacktestExecutor(config)
    result = executor.run()
    print("BACKTEST RESULT:")
    print(result.to_dict())

if __name__ == "__main__":
    cProfile.run("run_profile()", "profile_full.stats")
    p = pstats.Stats("profile_full.stats")
    p.sort_stats("cumulative").print_stats(30)
    p.sort_stats("tottime").print_stats(30)
