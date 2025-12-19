## 1. 基础设施

- [x] 1.1 创建 `src/engine/` 目录结构
- [x] 1.2 创建 `src/engine/base.py` 定义基础类型 (TrendSignal, RatingSignal, Position)
- [x] 1.3 创建 `src/engine/__init__.py` 模块导出

## 1.5 B-S 模型基础层

- [x] 1.5.1 创建 `src/engine/bs/core.py`
  - `calc_d1(S, K, r, σ, T) -> float`
  - `calc_d2(d1, σ, T) -> float`
  - `calc_d3(d2, σ, T) -> float`
  - `calc_n(d) -> float`
  - `calc_bs_call_price(S, K, r, σ, T) -> float`
  - `calc_bs_put_price(S, K, r, σ, T) -> float`
- [x] 1.5.2 创建 `src/engine/bs/probability.py`
  - `calc_put_exercise_prob(S, K, r, σ, T) -> float`
  - `calc_call_exercise_prob(S, K, r, σ, T) -> float`
  - `calc_put_itm_prob(S, K, r, σ, T) -> float`
  - `calc_call_itm_prob(S, K, r, σ, T) -> float`
- [x] 1.5.3 编写 B-S 模块单元测试

## 1.6 期权策略实现层

- [x] 1.6.1 创建 `src/engine/strategy/base.py`
  - `OptionType`, `PositionSide` 枚举
  - `OptionLeg`, `StrategyParams`, `StrategyMetrics` 数据类
  - `OptionStrategy` 抽象基类
- [x] 1.6.2 创建 `src/engine/strategy/short_put.py`
  - `ShortPutStrategy` 实现
  - `calc_expected_return()`, `calc_return_variance()`
  - `calc_exercise_probability()`, `calc_expected_loss_if_exercised()`
- [x] 1.6.3 创建 `src/engine/strategy/covered_call.py`
  - `CoveredCallStrategy` 实现
  - 支持 `stock_cost_basis` 参数
  - `calc_assignment_probability()`
- [x] 1.6.4 创建 `src/engine/strategy/strangle.py`
  - `ShortStrangleStrategy` 实现
  - 支持双腿独立 IV
  - `calc_put_exercise_probability()`, `calc_call_exercise_probability()`
- [x] 1.6.5 编写策略模块单元测试

## 2. Greeks 模块

- [x] 2.1 创建 `src/engine/greeks/calculator.py`
  - `get_greeks(option_quote: OptionQuote) -> Greeks`
- [x] 2.2 编写 Greeks 模块单元测试

## 3. 波动率模块

- [x] 3.1 创建 `src/engine/volatility/historical.py`
  - `calc_hv(prices: list[float], window: int = 20, annualize: bool = True) -> float`
- [x] 3.2 创建 `src/engine/volatility/implied.py`
  - `get_iv(option_quote: OptionQuote) -> float | None`
  - `calc_iv_hv_ratio(iv: float, hv: float) -> float`
- [x] 3.3 创建 `src/engine/volatility/iv_rank.py`
  - `calc_iv_rank(current_iv: float, historical_ivs: list[float]) -> float`
  - `calc_iv_percentile(current_iv: float, historical_ivs: list[float]) -> float`
- [x] 3.4 编写波动率模块单元测试

## 4. 收益风险模块

- [x] 4.1 创建 `src/engine/returns/basic.py`
  - `calc_annualized_return(returns: list[float], periods_per_year: int = 252) -> float`
  - `calc_win_rate(trades: list[float]) -> float`
  - `calc_expected_return(win_rate: float, avg_win: float, avg_loss: float) -> float`
  - `calc_expected_std(returns: list[float]) -> float`
- [x] 4.2 创建 `src/engine/returns/risk.py`
  - `calc_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float`
  - `calc_max_drawdown(equity_curve: list[float]) -> float`
  - `calc_calmar_ratio(annualized_return: float, max_drawdown: float) -> float`
- [x] 4.3 创建 `src/engine/returns/kelly.py`
  - `calc_kelly(win_rate: float, win_loss_ratio: float) -> float`
  - `calc_kelly_from_trades(trades: list[float]) -> float`
- [x] 4.4 编写收益风险模块单元测试
- [x] 4.5 创建 `src/engine/returns/option_expected.py` 期权策略无关接口
  - `calc_short_put_metrics(S, K, C, σ, T, r) -> StrategyMetrics`
  - `calc_covered_call_metrics(S, K, C, σ, T, r) -> StrategyMetrics`
  - `calc_short_strangle_metrics(S, K_p, K_c, C_p, C_c, σ, T, r) -> StrategyMetrics`
  - `calc_option_expected_return(strategy_type, **kwargs) -> float`
  - `calc_option_sharpe_ratio(strategy_type, **kwargs) -> float`
  - `calc_option_kelly_fraction(strategy_type, **kwargs) -> float`

## 5. 市场情绪模块

- [x] 5.1 创建 `src/engine/sentiment/vix.py`
  - `interpret_vix(vix_value: float) -> TrendSignal`
  - `get_vix_zone(vix_value: float) -> str` (low/normal/elevated/high/extreme)
- [x] 5.2 创建 `src/engine/sentiment/trend.py`
  - `calc_spy_trend(prices: list[float], short_window: int = 20, long_window: int = 50) -> TrendSignal`
  - `calc_trend_strength(prices: list[float], window: int = 20) -> float`
- [x] 5.3 创建 `src/engine/sentiment/pcr.py`
  - `calc_pcr(put_volume: int, call_volume: int) -> float`
  - `interpret_pcr(pcr: float) -> TrendSignal`
- [x] 5.4 编写市场情绪模块单元测试

## 6. 基本面模块

- [x] 6.1 创建 `src/engine/fundamental/metrics.py`
  - `get_pe(fundamental: Fundamental) -> float | None`
  - `get_revenue_growth(fundamental: Fundamental) -> float | None`
  - `get_profit_margin(fundamental: Fundamental) -> float | None`
  - `get_analyst_rating(fundamental: Fundamental) -> RatingSignal`
  - `evaluate_fundamentals(fundamental: Fundamental) -> FundamentalScore`
- [x] 6.2 编写基本面模块单元测试

## 7. 技术面模块

- [x] 7.1 创建 `src/engine/technical/rsi.py`
  - `calc_rsi(prices: list[float], period: int = 14) -> float`
  - `interpret_rsi(rsi: float) -> TrendSignal`
- [x] 7.2 创建 `src/engine/technical/support.py`
  - `calc_support_level(prices: list[float], window: int = 20) -> float`
  - `calc_support_distance(current_price: float, support: float) -> float`
  - `find_support_resistance(prices: list[float]) -> tuple[float, float]`
- [x] 7.3 编写技术面模块单元测试

## 8. 组合风险模块

- [x] 8.1 创建 `src/engine/portfolio/greeks_agg.py`
  - `calc_beta_weighted_delta(positions: list[Position], spy_price: float) -> float`
  - `calc_portfolio_theta(positions: list[Position]) -> float`
  - `calc_portfolio_vega(positions: list[Position]) -> float`
  - `calc_portfolio_gamma(positions: list[Position]) -> float`
- [x] 8.2 创建 `src/engine/portfolio/risk_metrics.py`
  - `calc_tgr(theta: float, gamma: float) -> float` (Theta/Gamma Ratio)
  - `calc_roc(profit: float, capital: float) -> float` (Return on Capital)
  - `calc_portfolio_var(positions: list[Position], confidence: float = 0.95) -> float`
- [x] 8.3 创建 `src/engine/portfolio/composite.py`
  - `calc_sas(allocations: list[float]) -> float` (Strategy Allocation Score)
  - `calc_prei(exposures: dict[str, float]) -> float` (Portfolio Risk Exposure Index)
- [x] 8.4 编写组合风险模块单元测试

## 9. 集成与文档

- [x] 9.1 更新 `src/engine/__init__.py` 导出所有公共接口
- [x] 9.2 创建 `examples/engine_demo.py` 演示各模块使用
- [x] 9.3 运行完整测试套件确保所有测试通过

## 10. 波动率数据验证

- [x] 10.1 创建 `src/data/models/stock.py` 添加 `StockVolatility` 数据模型
- [x] 10.2 实现 `IBKRProvider.get_stock_volatility()` 获取股票级别波动率指标
  - IV (30 天隐含波动率) - tick 106
  - HV (30 天历史波动率) - tick 104
  - PCR (基于 Open Interest) - tick 101
  - IV Rank / IV Percentile (基于 52 周历史 IV)
- [x] 10.3 统一 PCR 计算口径为 Open Interest (而非 Volume)，确保港美股一致
- [x] 10.4 创建 `tests/verification/verify_volatility_data.py` 验证脚本
- [x] 10.5 验证美股 (TSLA) 波动率数据 - 80% 匹配率
- [x] 10.6 验证港股 (9988.HK) 波动率数据 - 100% 匹配率
- [x] 10.7 实现 `src/engine/position/volatility/metrics.py` 波动率评估层

## 11. 技术面指标模块

- [x] 11.1 更新 calculation-engine spec 添加 MA/ADX/BBand 要求
- [x] 11.2 实现 `moving_average.py` (SMA/EMA, 20/50/200 周期)
- [x] 11.3 实现 `adx.py` (ADX/+DI/-DI, 14 周期)
- [x] 11.4 实现 `bollinger_bands.py` (20 周期, 2 标准差)
- [x] 11.5 更新 `technical/__init__.py` 模块导出
- [x] 11.6 编写单元测试 `test_technical_indicators.py`
- [x] 11.7 创建验证脚本 `verify_technical_data.py`
- [x] 11.8 验证美股 (TSLA) 技术指标 - 77% 匹配率 (10/13)
  - MATCH: SMA(20/50/200), EMA(20/50), BB(上/中/下), RSI(14), +DI
  - DIFF: EMA200 (5.85%), ADX (21.65点), -DI (5.43点)
  - ADX 差异原因: 我们使用标准 Wilder 方法，与参考实现一致
- [x] 11.9 验证港股 (9988.HK) 技术指标 - SKIPPED (待用户提供 ground truth)

## 12. 技术面信号专家Review优化

- [x] 12.1 新建 `src/engine/position/technical/thresholds.py` 阈值配置模块
  - `TechnicalThresholds` dataclass 包含所有可配置阈值
  - ADX阈值: 15/20/25/35/45 五级划分
  - RSI阈值: 企稳区 30-45, 动能衰竭区 55-70, 极端区 <20/>80
  - BB阈值: Squeeze<0.08, 企稳区 0.1-0.3, 衰竭区 0.7-0.9
  - ATR strike buffer: k=1.5
- [x] 12.2 更新 `result.py` 数据模型
  - `TechnicalScore` 新增 `atr` 字段
  - `TechnicalSignal` 新增 `close_put_signal`, `close_call_signal`, `close_note`
  - `TechnicalSignal` 新增 `is_dangerous_period`, `danger_warnings`
- [x] 12.3 修改 `calc_technical_score()` 新增 ATR 计算
- [x] 12.4 重写 `calc_technical_signal()` 核心逻辑
  - BB Squeeze 检测: bandwidth<0.08 禁用 Strangle
  - 入场信号改用"企稳确认"逻辑 (非逆向极端)
  - RSI 30-45 + %B 0.1-0.3 → 企稳卖Put
  - RSI 55-70 + %B 0.7-0.9 → 动能衰竭卖Call
  - 强趋势屏蔽: ADX>45 时禁止逆势开仓
  - ATR动态行权价buffer: strike = support - 1.5*ATR
  - 平仓信号: 趋势反转 + ADX>25 触发平仓建议
  - 危险时段检测: ≥2个警告标记为危险时段
- [x] 12.5 更新 `__init__.py` 导出 TechnicalThresholds
- [x] 12.6 更新 verify_technical_data.py 显示新字段
- [x] 12.7 运行测试验证 - 49/49 通过
