import sys
import logging
import traceback
import urllib3
from datetime import date

# Hook into urllib3 to print stack trace on network requests
original_urlopen = urllib3.PoolManager.urlopen

def hooked_urlopen(self, method, url, redirect=True, **kw):
    print(f"\n[NETWORK REQUEST DETECTED] {method} {url}")
    # Print the last 15 frames of the stack trace
    traceback.print_stack(limit=15)
    return original_urlopen(self, method, url, redirect, **kw)

urllib3.PoolManager.urlopen = hooked_urlopen

try:
    import curl_cffi.requests
    original_curl_request = curl_cffi.requests.Session.request
    def hooked_curl_request(self, method, url, *args, **kwargs):
        print(f"\\n[CURL_CFFI REQUEST DETECTED] {method} {url}")
        traceback.print_stack(limit=15)
        return original_curl_request(self, method, url, *args, **kwargs)
    curl_cffi.requests.Session.request = hooked_curl_request
except ImportError:
    pass

logging.basicConfig(level=logging.WARNING)

sys.path.append("/Users/liuchao/Code/Quant/option_quant_trade_system")
from src.backtest.engine.backtest_executor import BacktestExecutor
from src.backtest.config.backtest_config import BacktestConfig

def run_trace():
    config = BacktestConfig.from_yaml("config/backtest/short_put.yaml")
    config.data_dir = "/Volumes/ORICO/option_quant"
    config.start_date = date(2024, 6, 1)
    config.end_date = date(2024, 6, 5)  # 5 days is enough
    config.symbols = ["SPY"]
    
    print("Starting execution with network hook...")
    executor = BacktestExecutor(config)
    executor.run()
    print("Execution finished.")

if __name__ == "__main__":
    run_trace()
