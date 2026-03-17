# Engine — 计算引擎

纯计算模块，无 I/O 依赖，回测与实盘共用。提供 Black-Scholes 定价、Greeks 计算、策略指标、持仓/组合/账户级风险计算。

## 模块结构

```
src/engine/
├── bs/                # Black-Scholes 模型
│   ├── model.py       # BS 公式实现 (d1, d2, call/put price, Greeks)
│   └── iv.py          # 隐含波动率求解 (Newton-Raphson)
├── strategy/          # 策略指标计算
│   ├── short_put.py   # Short Put (胜率/盈亏/ROC/TGR)
│   ├── covered_call.py
│   ├── strangle.py
│   └── factory.py     # 根据持仓创建 Pricer
├── position/          # 持仓级计算
│   ├── greeks_agg.py  # Greeks 聚合 (per-share → position-level)
│   ├── technical.py   # 技术面指标 (SMA, RSI, Bollinger)
│   └── volatility.py  # HV, IV/HV ratio
├── portfolio/         # 组合级计算
│   ├── greeks.py      # 组合 Greeks 汇总
│   └── risk.py        # 风险指标 (HHI, BWD%, TGR)
├── account/           # 账户级计算
│   ├── margin.py      # 保证金计算 (Reg-T / Portfolio Margin)
│   ├── position_sizer.py # 仓位计算
│   └── sentiment.py   # 市场情绪 (VIX 分位数)
└── models/            # 数据模型
    ├── params.py      # BSParams (S, K, T, r, σ, q)
    ├── position.py    # Position (持仓数据)
    └── enums.py       # StrategyType, OptionType
```

## 关键指标

| 指标 | 说明 | 计算模块 |
|------|------|----------|
| **TGR** | Theta/Gamma Ratio — Theta 收入 / Gamma 风险 | `strategy/` |
| **ROC** | Return on Capital — 年化权利金/保证金 | `strategy/` |
| **PREI** | Position Risk Exposure Index — 基于 gamma/vega/DTE 的尾部风险 | `portfolio/risk.py` |
| **SAS** | Strategy Attractiveness Score — IV/HV + Sharpe + 胜率综合评分 | `strategy/` |

## Greeks 约定

- `Position` 模型存储 **per-share** Greeks
- `greeks_agg.py` 乘以 qty × multiplier 得到持仓级 Greeks
- `PositionData` 存储持仓级 Greeks：delta×qty, gamma×|qty|, theta×qty, vega×|qty|
- BS theta 为日度 (/365)，vega 为每 1% IV 变动
