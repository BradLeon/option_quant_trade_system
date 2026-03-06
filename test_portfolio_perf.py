import sys
import cProfile
import pstats
import logging
from datetime import date

logging.basicConfig(level=logging.WARNING)

sys.path.append("/Users/liuchao/Code/Quant/option_quant_trade_system")
from src.engine.models.position import Position
from src.data.models.option import OptionType
from src.engine.portfolio.metrics import calc_portfolio_metrics
from src.backtest.data.duckdb_provider import DuckDBProvider

def test_portfolio_metrics():
    provider = DuckDBProvider(data_dir="/Volumes/ORICO/option_quant")
    as_of_date = date(2024, 6, 3)
    provider.set_as_of_date(as_of_date)
    
    positions = []
    # simulate 20 positions
    for i in range(20):
        from src.data.models.option import Greeks
        pos = Position(
            symbol=f"SPY 20240712 {500+i}.0P",
            quantity=-1,
            greeks=Greeks(delta=0.1 + i*0.01, gamma=0.01, theta=-0.05, vega=0.1, rho=0.01),
            beta=1.0,
            market_value=200.0,
            underlying_price=530.0,
            contract_multiplier=100.0,
            margin=1000.0,
            dte=30,
            iv=0.15,
        )
        positions.append(pos)
        
    print("Running calc_portfolio_metrics 100 times...")
    for _ in range(100):
        calc_portfolio_metrics(
            positions=positions,
            nlv=1000000.0,
            position_iv_hv_ratios={"SPY": 1.2},
            data_provider=provider,
            as_of_date=as_of_date
        )

if __name__ == "__main__":
    cProfile.run("test_portfolio_metrics()", "profile.stats")
    p = pstats.Stats("profile.stats")
    p.sort_stats("cumulative").print_stats(20)
