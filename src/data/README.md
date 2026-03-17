# Data — 数据层

多数据源抽象，为实盘交易提供统一的数据访问接口。

## 模块结构

```
src/data/
├── providers/         # 数据提供者
│   ├── base.py        # DataProvider 协议
│   ├── yahoo.py       # Yahoo Finance (基本面/宏观/K线)
│   ├── ibkr.py        # IBKR TWS (美股交易/Greeks/账户)
│   └── futu.py        # Futu OpenAPI (港股)
├── models/            # 数据模型
│   ├── option.py      # OptionContract, OptionQuote, Greeks
│   ├── stock.py       # StockQuote, StockBar
│   └── fundamental.py # 基本面数据
├── currency/          # 汇率转换 (HKD/USD)
└── cache/             # 缓存层
```

## DataProvider 协议

所有数据提供者实现统一协议，业务层通过协议而非具体实现访问数据：

```python
class DataProvider(Protocol):
    def get_stock_price(self, symbol: str) -> float: ...
    def get_option_chain(self, symbol: str) -> list[OptionQuote]: ...
    def get_account_summary(self) -> AccountSummary: ...
    def get_positions(self) -> list[Position]: ...
```

回测使用 `DuckDBProvider`（在 `src/backtest/data/`），实盘使用 `IBKRProvider`。

## 数据源对比

| 功能 | Yahoo Finance | IBKR TWS |
|------|---------------|----------|
| 股票行情 | US/HK | US |
| 期权 Greeks | - | Yes |
| 基本面 | Yes | - |
| 宏观 (VIX) | Yes | - |
| 账户/持仓 | - | Yes |
| 实时数据 | 延迟 | Yes |
| 需要网关 | - | TWS/Gateway |
