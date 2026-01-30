# 创建 verify_position_stocks.py 验证脚本

## 目标

参考 `verify_position_strategies.py` 的格式，创建股票持仓验证脚本，汇总展示所有股票持仓数据。

## 数据来源

### 1. 行情数据（从 AccountPosition）
| 字段 | 来源 | 说明 |
|------|------|------|
| 数量 (Qty) | `pos.quantity` | 持仓股数 |
| 现价 | `pos.market_value / pos.quantity` | 当前股价 |
| 成本价 | `pos.avg_cost` | 平均成本 |
| 持仓市值 | `pos.market_value` | 需转换为 USD |
| 今日盈亏% | 需计算 | (现价 - 昨收) / 昨收 |
| 今日盈亏$ | 需计算 | 今日盈亏% × 市值 |
| 总盈亏% | `unrealized_pnl / (qty × avg_cost)` | |
| 总盈亏$ | `pos.unrealized_pnl` | |

### 2. 基本面数据（FundamentalScore）
| 字段 | 来源 |
|------|------|
| score | `fund_score.score` (0-100) |
| rating | `fund_score.rating` (STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL) |
| pe_score | `fund_score.pe_score` |
| growth_score | `fund_score.growth_score` |
| margin_score | `fund_score.margin_score` |

### 3. 波动率数据（VolatilityScore）
| 字段 | 来源 |
|------|------|
| score | `vol_score.score` (0-100) |
| rating | `vol_score.rating` |
| iv_rank | `vol_score.iv_rank` (0-100) |
| iv_hv_ratio | `vol_score.iv_hv_ratio` |
| iv_percentile | `vol_score.iv_percentile` (0-1) |

### 4. 技术面数据（TechnicalScore）
| 字段 | 来源 |
|------|------|
| trend_signal | `tech_score.trend_signal` (bull/bear/neutral) |
| ma_alignment | `tech_score.ma_alignment` |
| rsi | `tech_score.rsi` (0-100) |
| rsi_zone | `tech_score.rsi_zone` |
| adx | `tech_score.adx` |
| support | `tech_score.support` |
| resistance | `tech_score.resistance` |

### 5. 技术信号（TechnicalSignal）
| 字段 | 来源 |
|------|------|
| market_regime | `tech_signal.market_regime` (ranging/trending_up/trending_down) |
| trend_strength | `tech_signal.trend_strength` |
| sell_put_signal | `tech_signal.sell_put_signal` |
| sell_call_signal | `tech_signal.sell_call_signal` |
| is_dangerous_period | `tech_signal.is_dangerous_period` |

---

## 输出表格设计

### Table 1: 持仓行情
| 标的 | Qty | 现价 | 成本 | 市值(USD) | 今日PnL% | 今日PnL$ | 总PnL% | 总PnL$ |

### Table 2: 基本面分析
| 标的 | Score | Rating | PE评分 | 增长评分 | 利润率评分 |

### Table 3: 波动率分析
| 标的 | Score | Rating | IV Rank | IV/HV | IV Pctl |

### Table 4: 技术面分析
| 标的 | 趋势 | MA对齐 | RSI | RSI区 | ADX | 支撑 | 阻力 |

### Table 5: 技术信号
| 标的 | 市场状态 | 趋势强度 | 卖Put信号 | 卖Call信号 | 危险期 |

---

## 实现步骤

1. 创建 `tests/verification/verify_position_stocks.py`
2. 复用 `verify_position_strategies.py` 的结构
3. 连接 IBKR/Futu 获取股票持仓
4. 调用 engine 层函数计算各类 Score
5. 格式化输出 5 个表格

---

## 关键文件

- 参考: `tests/verification/verify_position_strategies.py`
- 数据模型: `src/engine/models/result.py`
- 计算函数:
  - `src/engine/position/fundamental/metrics.py` → `evaluate_fundamentals()`
  - `src/engine/position/volatility/metrics.py` → `evaluate_volatility()`
  - `src/engine/position/technical/metrics.py` → `calc_technical_score()`
  - `src/engine/position/technical/signal.py` → `calc_technical_signal()`
