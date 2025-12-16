## ADDED Requirements

### Requirement: Greeks Calculation
系统 SHALL 提供期权希腊值的获取和计算功能。

#### Scenario: Get Greeks from Option Quote
- **WHEN** 提供包含希腊值的 OptionQuote
- **THEN** 返回 Greeks 对象包含 delta, gamma, theta, vega, rho

#### Scenario: Option Quote without Greeks
- **WHEN** 提供的 OptionQuote 不包含希腊值
- **THEN** 返回 None 或包含 None 值的 Greeks 对象

---

### Requirement: Historical Volatility Calculation
系统 SHALL 基于历史价格序列计算历史波动率 (HV)。

#### Scenario: Calculate HV with default window
- **WHEN** 提供至少 20 个价格数据点
- **THEN** 返回年化历史波动率 (基于 252 交易日)

#### Scenario: Calculate HV with custom window
- **WHEN** 提供价格序列和自定义窗口期 (如 10 天)
- **THEN** 返回基于指定窗口期计算的历史波动率

#### Scenario: Insufficient data for HV
- **WHEN** 价格数据点少于窗口期要求
- **THEN** 返回 None 或抛出 ValueError

---

### Requirement: Implied Volatility Retrieval
系统 SHALL 从期权报价中获取隐含波动率 (IV)。

#### Scenario: Get IV from Option Quote
- **WHEN** OptionQuote 包含 IV 数据
- **THEN** 返回 IV 值 (0-1 小数形式)

#### Scenario: IV not available
- **WHEN** OptionQuote 不包含 IV 数据
- **THEN** 返回 None

---

### Requirement: IV/HV Ratio Calculation
系统 SHALL 计算隐含波动率与历史波动率的比率。

#### Scenario: Calculate IV/HV Ratio
- **WHEN** 提供 IV 和 HV 值
- **THEN** 返回 IV/HV 比率
- **AND** 比率 > 1 表示期权相对"贵"，< 1 表示相对"便宜"

#### Scenario: HV is zero
- **WHEN** HV 为 0
- **THEN** 返回 None 或 float('inf')

---

### Requirement: IV Rank Calculation
系统 SHALL 计算当前 IV 在历史区间中的百分位排名。

#### Scenario: Calculate IV Rank
- **WHEN** 提供当前 IV 和历史 IV 序列 (如过去 252 天)
- **THEN** 返回 0-100 的百分位值
- **AND** IV Rank = (当前IV - 最低IV) / (最高IV - 最低IV) * 100

#### Scenario: All historical IVs are equal
- **WHEN** 历史 IV 最高值等于最低值
- **THEN** 返回 50 (中间值)

---

### Requirement: Annualized Return Calculation
系统 SHALL 计算年化收益率。

#### Scenario: Calculate annualized return from daily returns
- **WHEN** 提供日收益率序列
- **THEN** 返回年化收益率 (假设 252 交易日/年)

#### Scenario: Calculate from different periods
- **WHEN** 提供收益率序列和周期类型 (日/周/月)
- **THEN** 按对应周期数进行年化

---

### Requirement: Win Rate Calculation
系统 SHALL 计算交易胜率。

#### Scenario: Calculate win rate
- **WHEN** 提供交易盈亏列表
- **THEN** 返回胜率 = 盈利交易数 / 总交易数

#### Scenario: No trades
- **WHEN** 交易列表为空
- **THEN** 返回 0 或 None

---

### Requirement: Expected Return Calculation
系统 SHALL 计算期望收益率。

#### Scenario: Calculate expected return
- **WHEN** 提供胜率、平均盈利、平均亏损
- **THEN** 期望收益 = 胜率 × 平均盈利 - (1-胜率) × 平均亏损

---

### Requirement: Sharpe Ratio Calculation
系统 SHALL 计算夏普比率。

#### Scenario: Calculate Sharpe ratio
- **WHEN** 提供收益率序列和无风险利率
- **THEN** 夏普比率 = (平均收益 - 无风险利率) / 收益标准差
- **AND** 结果进行年化调整

#### Scenario: Zero volatility
- **WHEN** 收益标准差为 0
- **THEN** 返回 0 或 None

---

### Requirement: Kelly Criterion Calculation
系统 SHALL 计算 Kelly 公式推荐仓位比例。

#### Scenario: Calculate Kelly fraction
- **WHEN** 提供胜率和盈亏比
- **THEN** Kelly% = 胜率 - (1-胜率) / 盈亏比

#### Scenario: Calculate Kelly from trades
- **WHEN** 提供历史交易记录
- **THEN** 自动计算胜率和盈亏比，返回 Kelly%

---

### Requirement: Maximum Drawdown Calculation
系统 SHALL 计算最大回撤。

#### Scenario: Calculate max drawdown
- **WHEN** 提供权益曲线 (净值序列)
- **THEN** 返回最大回撤百分比 (峰值到谷底的最大跌幅)

#### Scenario: Monotonically increasing equity
- **WHEN** 权益曲线单调递增
- **THEN** 返回 0 (无回撤)

---

### Requirement: VIX Interpretation
系统 SHALL 解读 VIX 指数水平。

#### Scenario: Interpret VIX level
- **WHEN** 提供 VIX 数值
- **THEN** 返回市场情绪信号 (BULLISH/NEUTRAL/BEARISH)
- **AND** 返回 VIX 区间 (low/normal/elevated/high/extreme)

#### Scenario: VIX zones
- **WHEN** VIX < 15 → low (市场自满)
- **WHEN** VIX 15-20 → normal
- **WHEN** VIX 20-25 → elevated
- **WHEN** VIX 25-35 → high (恐慌)
- **WHEN** VIX > 35 → extreme

---

### Requirement: SPY Trend Detection
系统 SHALL 判断 SPY (大盘) 趋势方向。

#### Scenario: Calculate trend using moving averages
- **WHEN** 提供 SPY 价格序列
- **THEN** 使用短期/长期均线交叉判断趋势
- **AND** 返回 BULLISH (短期 > 长期), BEARISH (短期 < 长期), NEUTRAL

#### Scenario: Calculate trend strength
- **WHEN** 提供价格序列
- **THEN** 返回趋势强度指标 (-1 到 1)

---

### Requirement: Put/Call Ratio Calculation
系统 SHALL 计算看跌/看涨期权成交量比率。

#### Scenario: Calculate PCR
- **WHEN** 提供 Put 和 Call 的成交量
- **THEN** PCR = Put成交量 / Call成交量

#### Scenario: Interpret PCR
- **WHEN** PCR > 1.0 → 看空情绪较重 (逆向指标可能看涨)
- **WHEN** PCR < 0.7 → 看多情绪较重 (逆向指标可能看跌)
- **WHEN** PCR 0.7-1.0 → 中性

---

### Requirement: Fundamental Metrics Extraction
系统 SHALL 从基本面数据中提取关键指标。

#### Scenario: Get PE ratio
- **WHEN** 提供 Fundamental 数据
- **THEN** 返回市盈率 (P/E)

#### Scenario: Get revenue growth
- **WHEN** 提供 Fundamental 数据
- **THEN** 返回营收增长率 (YoY%)

#### Scenario: Get profit margin
- **WHEN** 提供 Fundamental 数据
- **THEN** 返回净利润率

#### Scenario: Get analyst rating
- **WHEN** 提供 Fundamental 数据
- **THEN** 返回分析师评级 (STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL)

---

### Requirement: RSI Calculation
系统 SHALL 计算相对强弱指数 (RSI)。

#### Scenario: Calculate RSI
- **WHEN** 提供价格序列和周期 (默认 14)
- **THEN** 返回 0-100 的 RSI 值

#### Scenario: Interpret RSI
- **WHEN** RSI > 70 → 超买 (BEARISH 信号)
- **WHEN** RSI < 30 → 超卖 (BULLISH 信号)
- **WHEN** RSI 30-70 → NEUTRAL

---

### Requirement: Support Distance Calculation
系统 SHALL 计算当前价格距支撑位的距离。

#### Scenario: Calculate support level
- **WHEN** 提供历史价格序列
- **THEN** 计算近期支撑位 (如近 N 日最低价)

#### Scenario: Calculate distance to support
- **WHEN** 提供当前价格和支撑位
- **THEN** 返回距离百分比 = (当前价 - 支撑位) / 支撑位 × 100

---

### Requirement: Portfolio Greeks Aggregation
系统 SHALL 汇总计算组合的希腊值。

#### Scenario: Calculate beta-weighted delta
- **WHEN** 提供持仓列表 (含 delta 和 beta) 和 SPY 价格
- **THEN** 返回 Beta 加权 Delta 总和

#### Scenario: Calculate portfolio theta
- **WHEN** 提供持仓列表 (含 theta)
- **THEN** 返回所有持仓 Theta 之和

#### Scenario: Calculate portfolio vega
- **WHEN** 提供持仓列表 (含 vega)
- **THEN** 返回所有持仓 Vega 之和

#### Scenario: Calculate portfolio gamma
- **WHEN** 提供持仓列表 (含 gamma)
- **THEN** 返回所有持仓 Gamma 之和

---

### Requirement: TGR (Theta/Gamma Ratio) Calculation
系统 SHALL 计算组合的 Theta/Gamma 风险比率。

#### Scenario: Calculate TGR
- **WHEN** 提供组合 Theta 和 Gamma
- **THEN** TGR = |Theta| / |Gamma|
- **AND** TGR 越高表示时间衰减收益相对 Gamma 风险越大

#### Scenario: Gamma is zero
- **WHEN** Gamma 为 0
- **THEN** 返回 float('inf') 或 None

---

### Requirement: ROC (Return on Capital) Calculation
系统 SHALL 计算资本回报率。

#### Scenario: Calculate ROC
- **WHEN** 提供收益和占用资本
- **THEN** ROC = 收益 / 占用资本 × 100%

---

### Requirement: SAS (Strategy Allocation Score) Calculation
系统 SHALL 计算策略分配评分。

#### Scenario: Calculate SAS
- **WHEN** 提供各策略的资金分配比例
- **THEN** 返回分配集中度/分散度评分

---

### Requirement: PREI (Portfolio Risk Exposure Index) Calculation
系统 SHALL 计算组合风险暴露指数。

#### Scenario: Calculate PREI
- **WHEN** 提供各类风险敞口 (方向、波动率、时间等)
- **THEN** 返回综合风险暴露指数
