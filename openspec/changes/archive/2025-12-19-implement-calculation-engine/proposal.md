## Why

系统需要计算引擎层来处理原始市场数据，生成可用于策略决策的量化指标。数据层已完成，可提供期权行情、股票行情、基本面数据和宏观数据，但这些原始数据需要经过加工才能为开仓筛选、持仓监控等业务模块提供决策依据。

## What Changes

### 新增计算引擎模块 (`src/engine/`)

**1. 期权希腊值计算 (Option Greeks)**
- Delta, Gamma, Theta, Vega, Rho 计算与获取

**2. 波动率计算 (Volatility)**
- HV (历史波动率) - 基于标的历史价格计算
- IV (隐含波动率) - 从期权报价获取
- IV/HV 比率 - 评估期权是否"便宜"
- IV Rank - IV在历史区间中的百分位

**3. 收益与风险指标 (Return & Risk)**
- 年化收益率 (Annualized Return)
- 胜率 (Win Rate)
- 期望收益率 (Expected Return)
- 期望收益标准差 (Expected Return Std)
- 夏普比率 (Sharpe Ratio)
- Kelly公式 (Kelly Criterion)
- 最大回撤 (Max Drawdown)

**4. 市场情绪指标 (Market Sentiment)**
- VIX 指数获取
- SPY 趋势判断
- Put/Call Ratio

**5. 基本面指标 (Fundamental)**
- PE (市盈率)
- 营收增长率 (Revenue Growth)
- 利润率 (Profit Margin)
- 分析师评级 (Analyst Rating)

**6. 技术面指标 (Technical)**
- RSI (相对强弱指数)
- Support Distance (距支撑位距离)

**7. 组合风险指标 (Portfolio Risk)**
- Beta 加权 Delta 总和
- 组合 Theta、Vega、Gamma 总和
- Portfolio TGR (Theta/Gamma Ratio)
- ROC (Return on Capital)
- SAS (Strategy Allocation Score)
- PREI (Portfolio Risk Exposure Index)

## Impact

- Affected specs: 新增 `calculation-engine` capability
- Affected code:
  - 新建 `src/engine/` 目录及子模块
  - 依赖 `src/data/` 数据层提供原始数据
- Dependencies: numpy, scipy (已在项目中)
