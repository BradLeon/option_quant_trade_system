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

### Requirement: Black-Scholes Core Calculations
系统 SHALL 提供 Black-Scholes 模型基础计算功能。

#### Scenario: Calculate d1
- **WHEN** 提供 S (现价), K (行权价), r (无风险利率), σ (波动率), T (到期时间)
- **THEN** 返回 d1 = [ln(S/K) + (r + σ²/2)×T] / (σ×√T)

#### Scenario: Calculate d2
- **WHEN** 提供 d1, σ, T
- **THEN** 返回 d2 = d1 - σ×√T

#### Scenario: Calculate N(d)
- **WHEN** 提供 d 值
- **THEN** 返回标准正态分布累积概率 N(d)

#### Scenario: Calculate B-S Call/Put Price
- **WHEN** 提供 S, K, r, σ, T
- **THEN** 返回理论期权价格

---

### Requirement: Option Exercise Probability
系统 SHALL 计算期权行权概率。

#### Scenario: Calculate Put Exercise Probability
- **WHEN** 提供 S, K, r, σ, T
- **THEN** 返回 Put 行权概率 = N(-d2)

#### Scenario: Calculate Call Exercise Probability
- **WHEN** 提供 S, K, r, σ, T
- **THEN** 返回 Call 行权概率 = N(d2)

---

### Requirement: Option Strategy Expected Return
系统 SHALL 基于 B-S 模型计算期权策略的期望收益。

#### Scenario: Short Put Expected Return
- **WHEN** 提供 S (现价), K (行权价), C (权利金), σ (IV), T (到期时间), r (无风险利率)
- **THEN** 返回期望收益 E[π] = C - N(-d2) × [K - e^(rT) × S × N(-d1) / N(-d2)]

#### Scenario: Covered Call Expected Return
- **WHEN** 提供 S, K, C, σ, T, r 和可选的 stock_cost_basis
- **THEN** 返回考虑股票持仓和期权收益的综合期望收益

#### Scenario: Short Strangle Expected Return
- **WHEN** 提供 S, K_put, K_call, C_put, C_call, σ, T, r
- **THEN** 返回两腿期望收益之和

---

### Requirement: Option Strategy Return Variance
系统 SHALL 计算期权策略收益的方差。

#### Scenario: Calculate Return Variance
- **WHEN** 提供策略参数
- **THEN** 返回 Var[π] = E[π²] - (E[π])²
- **AND** 使用 d3 参数计算 E[S_T²] 相关项

---

### Requirement: Option Sharpe Ratio
系统 SHALL 计算期权交易的夏普比率。

#### Scenario: Calculate Option Sharpe Ratio
- **WHEN** 提供策略类型和参数
- **THEN** 返回 SR = (E[π] - Rf) / Std[π]
- **AND** Rf = margin_ratio × K × (e^(rT) - 1) 为无风险收益金额

#### Scenario: Calculate Annualized Sharpe Ratio
- **WHEN** 提供策略参数
- **THEN** 返回 SR_annual = SR / √T

---

### Requirement: Option Kelly Fraction
系统 SHALL 计算期权策略的 Kelly 仓位比例。

#### Scenario: Calculate Option Kelly
- **WHEN** 提供策略类型和参数
- **THEN** 返回 f* = E[π] / Var[π]
- **AND** 若期望收益为负则返回 0

---

### Requirement: Strategy Metrics Calculation
系统 SHALL 提供一次性计算所有策略指标的功能。

#### Scenario: Calculate All Metrics
- **WHEN** 调用 calc_short_put_metrics / calc_covered_call_metrics / calc_short_strangle_metrics
- **THEN** 返回 StrategyMetrics 包含:
  - expected_return (期望收益)
  - return_std (收益标准差)
  - return_variance (收益方差)
  - max_profit (最大盈利)
  - max_loss (最大亏损)
  - breakeven (盈亏平衡点)
  - win_probability (胜率)
  - sharpe_ratio (夏普比率)
  - kelly_fraction (Kelly仓位)

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

---

### Requirement: Moving Average Calculation
系统 SHALL 计算移动平均线 (MA/EMA)。

#### Scenario: Calculate SMA
- **WHEN** 提供价格序列和周期 (20/50/200)
- **THEN** 返回简单移动平均值

#### Scenario: Calculate EMA
- **WHEN** 提供价格序列和周期 (20/50/200)
- **THEN** 返回指数移动平均值
- **AND** EMA = Price × k + EMA_prev × (1-k), k = 2/(period+1)

#### Scenario: Calculate MA Series
- **WHEN** 提供完整价格序列
- **THEN** 返回每个时间点的 SMA/EMA 值列表

#### Scenario: Interpret MA Trend
- **WHEN** 提供短期和长期均线值
- **THEN** 返回趋势信号:
  - BULLISH: 短期 > 长期 (金叉)
  - BEARISH: 短期 < 长期 (死叉)
  - NEUTRAL: 差异小于阈值

#### Scenario: Insufficient Data
- **WHEN** 价格数据点少于周期要求
- **THEN** 返回 None

---

### Requirement: ADX Calculation
系统 SHALL 计算平均趋向指数 (ADX) 用于衡量趋势强度。

#### Scenario: Calculate True Range
- **WHEN** 提供当前 High/Low 和前一日 Close
- **THEN** TR = max(High-Low, |High-PrevClose|, |Low-PrevClose|)

#### Scenario: Calculate ADX
- **WHEN** 提供 High/Low/Close 价格序列 (至少 2×period 数据点)
- **THEN** 返回 ADXResult 包含:
  - adx: 平均趋向指数 (0-100)
  - plus_di: +DI 正向指标
  - minus_di: -DI 负向指标

#### Scenario: Interpret ADX
- **WHEN** ADX > 25 → 强趋势 (适合趋势跟踪)
- **WHEN** ADX 20-25 → 趋势形成中
- **WHEN** ADX < 20 → 弱趋势/震荡 (适合卖期权)

#### Scenario: DI Crossover
- **WHEN** +DI > -DI → BULLISH (上涨趋势)
- **WHEN** -DI > +DI → BEARISH (下跌趋势)

#### Scenario: Insufficient Data
- **WHEN** 数据点少于 2×period
- **THEN** 返回 None

---

### Requirement: Bollinger Bands Calculation
系统 SHALL 计算布林带用于波动率分析和均值回归。

#### Scenario: Calculate Bollinger Bands
- **WHEN** 提供价格序列 (默认 20 周期, 2 倍标准差)
- **THEN** 返回 BollingerBands 包含:
  - upper: 上轨 = SMA + (num_std × σ)
  - middle: 中轨 = SMA
  - lower: 下轨 = SMA - (num_std × σ)
  - bandwidth: 带宽 = (upper - lower) / middle
  - percent_b: %B = (price - lower) / (upper - lower)

#### Scenario: Calculate %B
- **WHEN** 提供当前价格和布林带
- **THEN** 返回 %B 值:
  - %B > 1: 价格在上轨之上 (超买)
  - %B = 0.5: 价格在中轨
  - %B < 0: 价格在下轨之下 (超卖)

#### Scenario: Detect Squeeze
- **WHEN** 带宽 < 阈值 (默认 0.1)
- **THEN** 识别为布林带收窄 (低波动率，可能即将突破)

#### Scenario: Favorable for Option Selling
- **WHEN** %B 在 0.2-0.8 区间
- **THEN** 价格在布林带中间区域，适合卖期权

#### Scenario: Insufficient Data for Bollinger Bands
- **WHEN** 价格数据点少于周期要求
- **THEN** 返回 None

---

### Requirement: ATR (Average True Range) Calculation
系统 SHALL 计算平均真实波幅用于动态行权价buffer计算。

#### Scenario: Calculate ATR
- **WHEN** 提供 High/Low/Close 价格序列 (至少 period+1 数据点)
- **THEN** 返回 ATR 值
- **AND** TR = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
- **AND** ATR = SMA(TR, period)

#### Scenario: ATR-based Strike Buffer
- **WHEN** 提供支撑位和 ATR
- **THEN** Put行权价建议区 = 支撑位 - k×ATR (k默认1.5)
- **AND** Call行权价建议区 = 阻力位 + k×ATR

---

### Requirement: Technical Thresholds Configuration
系统 SHALL 提供可配置的技术指标阈值用于回测优化。

#### Scenario: Configure ADX Thresholds
- **WHEN** 创建 TechnicalThresholds 实例
- **THEN** 可配置以下阈值:
  - adx_very_weak: 15 (极弱趋势，适合Strangle)
  - adx_weak: 20 (弱趋势/震荡)
  - adx_emerging: 25 (趋势形成中)
  - adx_strong: 35 (强趋势，期权卖方高风险)
  - adx_extreme: 45 (极端趋势，禁止逆势开仓)

#### Scenario: Configure RSI Thresholds
- **WHEN** 创建 TechnicalThresholds 实例
- **THEN** 可配置以下阈值:
  - rsi_stabilizing_low/high: 30-45 (企稳区，适合卖Put)
  - rsi_exhaustion_low/high: 55-70 (动能衰竭区，适合卖Call)
  - rsi_extreme_low/high: 20/80 (极端区，危险信号)
  - rsi_close_low/high: 25/75 (平仓信号阈值)

#### Scenario: Configure BB Thresholds
- **WHEN** 创建 TechnicalThresholds 实例
- **THEN** 可配置以下阈值:
  - bb_squeeze: 0.08 (Squeeze阈值，变盘在即)
  - bb_stabilizing_low/high: 0.1-0.3 (企稳区)
  - bb_exhaustion_low/high: 0.7-0.9 (动能衰竭区)

---

### Requirement: Close Signal Generation
系统 SHALL 生成持仓平仓信号。

#### Scenario: Trend Reversal Close Signal
- **WHEN** 持有Short Put且市场转为下跌趋势 (ADX>25)
- **THEN** close_put_signal = "strong"
- **AND** 提供平仓建议说明

#### Scenario: Trend Continuation Close Signal
- **WHEN** 持有Short Call且市场转为上涨趋势 (ADX>25)
- **THEN** close_call_signal = "strong"

#### Scenario: RSI Extreme Close Signal
- **WHEN** RSI < 25 (极度超卖)
- **THEN** close_put_signal = "moderate" (避险)
- **WHEN** RSI > 75 (极度超买)
- **THEN** close_call_signal = "moderate"

---

### Requirement: Danger Period Detection
系统 SHALL 检测期权卖方危险时段。

#### Scenario: BB Squeeze Danger
- **WHEN** BB bandwidth < 0.08
- **THEN** 标记为危险时段
- **AND** 禁用 Strangle 策略
- **AND** 添加警告 "BB Squeeze: 变盘在即且权利金低"

#### Scenario: Strong Trend Danger
- **WHEN** ADX > 45 且趋势明确
- **THEN** 禁止逆势开仓
- **AND** 添加警告 "强趋势中，谨防RSI钝化"

#### Scenario: Near Support/Resistance Danger
- **WHEN** 价格距支撑/阻力 < 2%
- **THEN** 添加危险警告

#### Scenario: Multiple Warnings
- **WHEN** 危险警告数量 >= 2
- **THEN** is_dangerous_period = True

---

### Requirement: Entry Signal Stabilization Logic
系统 SHALL 使用"企稳确认"而非"逆向极端"逻辑生成入场信号。

#### Scenario: Put Stabilization Entry
- **WHEN** RSI 从超卖回升至 30-45 区间
- **AND** %B 脱离下轨进入 0.1-0.3 区间
- **THEN** sell_put_signal = "strong" (适合卖Put)
- **RATIONALE** 避免"接飞刀"，等待企稳后再开仓

#### Scenario: Call Exhaustion Entry
- **WHEN** RSI 在 55-70 动能衰竭区
- **AND** %B 在 0.7-0.9 高位但未极端
- **THEN** sell_call_signal = "strong" (适合卖Call)
- **RATIONALE** 上涨动能减弱，适合卖Call收租

#### Scenario: Strong Trend Filter
- **WHEN** RSI < 30 (超卖) 但 ADX > 45 且 -DI > +DI
- **THEN** sell_put_signal = "none" (禁止逆势)
- **RATIONALE** 强空头趋势中RSI可能钝化，继续下跌
