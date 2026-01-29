# 期权开仓信号捕捉系统 - 指标现状分析

> 分析日期: 2026-01-08
> 参考文档: `src/data/knowledge/options_signal_filter_system_v2.md`

## 概述

本文档分析 `options_signal_filter_system_v2.md` 中定义的三层过滤器所需指标，对比项目现有实现，明确哪些已存在、哪些需要开发。

---

## Layer 1: 市场过滤器

**核心问题：现在是卖期权的好时机吗？**

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P1 | VIX 水平 | ✅ 已实现 | `MacroIndicator.VIX` + `interpret_vix()` @ `engine/account/sentiment/vix.py` | - |
| P1 | VIX期限结构 (VIX/VIX3M) | ✅ 已实现 | `calc_vix_term_ratio()` @ `engine/account/sentiment/vix_term.py` | - |
| P1 | 宏观事件 | ✅ 已实现 | `EconomicCalendarProvider.get_economic_calendar()` @ `data/providers/economic_calendar_provider.py` (FRED + 静态FOMC) | - |
| P2 | VIX Percentile | ✅ 已实现 | `calc_vix_percentile()` @ `engine/account/sentiment/vix.py` | - |
| P3 | SPY趋势 (vs MA50) | ✅ 已实现 | `calc_sma()` @ `engine/position/technical/moving_average.py` | 需要封装比较逻辑 |
| P3 | ADX趋势强度 | ✅ 已实现 | `calc_adx()` @ `engine/position/technical/adx.py` | - |
| P4 | Put/Call Ratio | ✅ 已实现 | `calc_pcr()` / `interpret_pcr()` @ `engine/account/sentiment/pcr.py` | - |

### 详细说明

#### ✅ VIX 相关 (已完整实现)
- **数据获取**: `UnifiedDataProvider.get_macro_data(MacroIndicator.VIX)` → `MacroData`
- **解读函数**:
  - `interpret_vix()` → 返回交易信号 (BULLISH/BEARISH/NEUTRAL)
  - `get_vix_zone()` → 返回 VixZone (LOW/NORMAL/ELEVATED/HIGH/EXTREME)
  - `is_vix_favorable_for_selling()` → 适合卖方策略判断
- **期限结构**:
  - `calc_vix_term_ratio()` → VIX/VIX3M 比率
  - `get_term_structure()` → TermStructure (CONTANGO/FLAT/BACKWARDATION)

#### ✅ 宏观事件日历 (已实现)
**已完成**:
- FOMC/CPI/NFP/GDP/PPI 等重大事件检查
- 混合数据源: FRED API (CPI/NFP/GDP/PPI) + 静态 FOMC 日历
- 事件前 blackout 期间自动暂停开仓

**实现位置**:
1. `src/data/models/event.py` - 事件数据模型 (EconomicEvent, EventCalendar)
2. `src/data/providers/fred_calendar_provider.py` - FRED API 客户端 (CPI/NFP/GDP/PPI)
3. `src/data/providers/economic_calendar_provider.py` - 整合 FRED + 静态 FOMC
4. `config/screening/fomc_calendar.yaml` - 静态 FOMC 会议日期 (2025-2026)
5. `src/business/screening/filters/market_filter.py` - `_check_macro_events()` 方法

---

## Layer 2: 标的过滤器

**核心问题：这个标的适合卖期权吗？我愿意长期持有吗？**

### 2.1 流动性指标 【必要条件】

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P0 | 期权成交量 (> 5,000) | ✅ 已实现 | `OptionChain` 所有合约 `volume` 汇总 (当日/昨日) | 需要封装汇总函数 |
| P0 | ATM Bid-Ask Spread (< 5%) | ✅ 已实现 | `calc_bid_ask_spread()` @ `engine/contract/liquidity.py` | - |
| P1 | Open Interest (> 500) | ✅ 已实现 | `OptionQuote.open_interest` | - |
| P2 | 股票成交量 (> 500K) | ✅ 已实现 | `StockQuote.volume` (当日/昨日) | - |

### 2.2 波动率指标

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P1 | IV/HV (> 1.0) | ✅ 已实现 | `StockVolatility.iv_hv_ratio` @ `data/models/stock.py` | - |
| P2 | IV Rank (> 30%) | ✅ 已实现 | `StockVolatility.iv_rank` / `calc_iv_rank()` @ `engine/position/volatility/iv_rank.py` | - |
| P3 | IV Percentile (> 30%) | ✅ 已实现 | `StockVolatility.iv_percentile` / `calc_iv_percentile()` @ `engine/position/volatility/iv_rank.py` | - |

### 2.3 基本面指标

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P2 | 市值 (> $10B) | ✅ 已实现 | `Fundamental.market_cap` @ `data/models/fundamental.py` | - |
| P3 | PE vs 历史 | ⚠️ 部分 | `Fundamental.pe_ratio` (当前值) | 需要历史PE范围计算 |
| P3 | 分析师评级 (Hold~Buy) | ✅ 已实现 | `Fundamental.recommendation_mean` (1-5分) | - |

### 2.4 技术面指标

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P2 | RSI (35~65) | ✅ 已实现 | `calc_rsi()` @ `engine/position/technical/rsi.py` | - |
| P2 | 价格 vs MA200 | ✅ 已实现 | `calc_sma()` @ `engine/position/technical/moving_average.py` | 需要封装比较函数 |
| P3 | Support Distance (> 5%) | ✅ 已实现 | `calc_support_level()` @ `engine/position/technical/support.py` | 需要距离计算封装 |
| P3 | Resistance Distance | ✅ 已实现 | `calc_resistance_level()` @ `engine/position/technical/support.py` | 需要距离计算封装 |

### 2.5 事件日历

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P1 | 财报日期 (> 7天) | ✅ 已实现 | `Fundamental.earnings_date` + `UnderlyingFilter._check_event_calendar()` | - |
| P1 | 重大事件 (无) | ✅ 已实现 | `EconomicCalendarProvider.get_economic_calendar()` + `MarketFilter._check_macro_events()` | - |
| P2 | 除息日 (> 7天, CC专用) | ✅ 已实现 | `Fundamental.ex_dividend_date` + `UnderlyingFilter._check_event_calendar()` | - |

---

## Layer 3: 合约过滤器

**核心问题：选择哪个Strike和到期日？**

### 3.1 DTE选择

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P1 | DTE (14~45天) | ✅ 已实现 | `OptionContract.days_to_expiry` @ `data/models/option.py` | - |
| P2 | 财报跨越检查 | ✅ 已实现 | `UnderlyingFilter._check_event_calendar()` | - |

### 3.2 Strike选择

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P1 | \|Delta\| (0.15~0.35) | ✅ 已实现 | `OptionQuote.greeks.delta` @ `data/models/option.py` | - |
| P2 | OTM % (5%~15%) | ✅ 已实现 | `calc_otm_percent()` @ `engine/contract/metrics.py` | - |
| P2 | Strike位置 vs 支撑/阻力 | ✅ 已实现 | `calc_support_level()` / `calc_resistance_level()` | 需要比较逻辑 |
| P3 | Win Probability (> 65%) | ✅ 已实现 | `calc_win_prob()` @ `engine/bs/probability.py` | - |

### 3.3 收益风险验证

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P0 | Expected ROC (> 0%) | ✅ 已实现 | `calc_expected_return()` @ `engine/strategy/base.py` | - |
| P1 | TGR (> 0.10) | ✅ 已实现 | `calc_tgr()` @ `engine/position/risk_return.py` | - |
| P1 | Sharpe比率 (> 1.0) | ✅ 已实现 | `calc_sharpe_ratio()` @ `engine/strategy/base.py` | - |
| P2 | ROC 年化 (> 15%) | ✅ 已实现 | `calc_roc_from_dte()` @ `engine/position/risk_return.py` | - |
| P3 | Theta/Premium (> 1%/天) | ✅ 已实现 | `calc_theta_premium_ratio()` @ `engine/contract/metrics.py` | - |
| P3 | Kelly Fraction (> 1%) | ✅ 已实现 | `calc_kelly_fraction()` @ `engine/strategy/base.py` | - |

### 3.4 合约流动性

| 优先级 | 指标 | 状态 | 现有实现/上游来源 | 待开发 |
|--------|------|------|------------------|--------|
| P1 | Bid-Ask Spread (< 10%) | ✅ 已实现 | `calc_bid_ask_spread()` @ `engine/contract/liquidity.py` | - |
| P2 | Open Interest (> 100) | ✅ 已实现 | `OptionQuote.open_interest` | - |
| P3 | Volume Today (> 50) | ✅ 已实现 | `OptionQuote.volume` | - |

---

## 汇总统计

### 按状态分类

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 已完整实现 | 32 | 94% |
| ⚠️ 部分实现/需封装 | 2 | 6% |
| ❌ 未实现 | 0 | 0% |
| **合计** | **34** | 100% |

### 已完成开发项目

#### 优先级 P0/P1 (核心功能) - ✅ 全部完成

1. **财报日期 + 除息日** (Layer 2, P1) → ✅ **已完成**
   - `Fundamental` 模型新增 `earnings_date` 和 `ex_dividend_date` 字段
   - `YahooProvider.get_fundamental()` 从 yfinance `info` 提取日期
   - `UnderlyingFilter._check_event_calendar()` 实现财报/除息检查

2. **宏观事件日历** (Layer 1, P1) → ✅ **已完成**
   - `EconomicCalendarProvider` 整合 FRED API + 静态 FOMC 日历
   - `FredCalendarProvider` 获取 CPI/NFP/GDP/PPI 发布日期
   - `EconomicEvent` / `EventCalendar` 数据模型
   - `MarketFilter._check_macro_events()` 实现 blackout 检查

3. **合约工具函数** (Layer 3) → ✅ **已完成**
   - `calc_bid_ask_spread()` @ `engine/contract/liquidity.py`
   - `calc_otm_percent()` @ `engine/contract/metrics.py`
   - `calc_theta_premium_ratio()` @ `engine/contract/metrics.py`

#### 优先级 P2/P3 (后续增强)

4. **PE历史范围** (Layer 2, P3) - 暂缓
   - 需要历史PE数据源
   - 可在后续版本实现

5. **工具函数封装** (多处) → ✅ **已完成**
   - `calc_option_chain_volume()` @ `engine/contract/liquidity.py` ✅
   - `calc_bid_ask_spread()` @ `engine/contract/liquidity.py` ✅
   - `calc_otm_percent()` @ `engine/contract/metrics.py` ✅
   - `calc_theta_premium_ratio()` @ `engine/contract/metrics.py` ✅
   - `calc_support_distance()` @ `engine/position/technical/support.py` (已存在)
   - `calc_resistance_distance()` @ `engine/position/technical/support.py` (已存在)
   - `is_price_above_ma()` - 集成在 MarketFilter 中

---

## 数据源方案

### 股票级日历数据 → YahooProvider

**数据来源**: yfinance `ticker.info` 已有字段，只需扩展模型提取。

| 数据 | yfinance 字段 | 说明 |
|------|--------------|------|
| 财报日期 | `earningsTimestamp` | Unix时间戳，下一次财报发布日期 |
| 除息日 | `exDividendDate` | Unix时间戳，下一个除息日 |
| 分红支付日 | `dividendDate` | Unix时间戳 |
| 最后拆股日 | `lastSplitDate` | Unix时间戳 |

**实现步骤**:

1. 扩展 `Fundamental` 模型 (`src/data/models/fundamental.py`):
   ```python
   @dataclass
   class Fundamental:
       # ... 现有字段 ...
       # 新增日历字段
       earnings_date: date | None = None          # 下一财报日期
       earnings_date_estimated: bool | None = None # 是否为预估
       ex_dividend_date: date | None = None       # 除息日
       dividend_pay_date: date | None = None      # 分红支付日
       last_split_date: date | None = None        # 最后拆股日
   ```

2. 修改 `YahooProvider.get_fundamental()` (`src/data/providers/yahoo_provider.py`):
   ```python
   def _parse_timestamp(ts: int | None) -> date | None:
       return datetime.fromtimestamp(ts).date() if ts else None

   # 在构建 Fundamental 时添加:
   earnings_date=_parse_timestamp(info.get("earningsTimestamp")),
   ex_dividend_date=_parse_timestamp(info.get("exDividendDate")),
   dividend_pay_date=_parse_timestamp(info.get("dividendDate")),
   ```

### 宏观事件日历 → FRED API + 静态 FOMC

**数据来源**:
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/) - CPI/NFP/GDP/PPI 发布日期
- [Federal Reserve FOMC Calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) - FOMC 会议日期

**FRED API**:
- 免费额度: 120次/分钟 (无每日限制)
- API 端点: `/fred/releases/dates?include_release_dates_with_no_data=true`
- Release IDs: 10=CPI, 50=NFP (Employment Situation), 53=GDP, 46=PPI
- 响应格式: JSON

**静态 FOMC 日历**:
- 美联储每年提前公布 FOMC 会议日期
- 存储在 `config/screening/fomc_calendar.yaml`
- 每年初更新一次

**实现步骤**:

1. 新建数据模型 (`src/data/models/event.py`):
   ```python
   @dataclass
   class EconomicEvent:
       event_type: EconomicEventType  # 事件类型枚举
       event_date: date               # 事件日期
       name: str                      # 事件名称 (如 "Consumer Price Index")
       impact: EventImpact            # 影响程度 (LOW/MEDIUM/HIGH)
       country: str = "US"            # 国家代码
       time: str | None = None        # 事件时间 (可选)
       source: str = "fred"           # 数据源 (fred/static)
   ```

2. 新建 FRED Provider (`src/data/providers/fred_calendar_provider.py`):
   ```python
   class FredCalendarProvider:
       """FRED API provider for economic release dates."""

       BASE_URL = "https://api.stlouisfed.org/fred"

       # Release IDs
       RELEASE_CPI = 10
       RELEASE_NFP = 50
       RELEASE_GDP = 53
       RELEASE_PPI = 46

       def __init__(self, api_key: str | None = None):
           self._api_key = api_key or os.environ.get("FRED_API_KEY")

       def get_release_dates(
           self,
           release_id: int,
           start_date: date,
           end_date: date,
       ) -> list[EconomicEvent]:
           """获取指定发布类型的未来发布日期."""
           ...
   ```

3. 新建静态 FOMC 日历 (`config/screening/fomc_calendar.yaml`):
   ```yaml
   # FOMC 会议日期 (来源: federalreserve.gov)
   fomc_meetings:
     2025:
       - 2025-01-29  # Jan 28-29
       - 2025-03-19  # Mar 18-19*
       - 2025-05-07  # May 6-7
       - 2025-06-18  # Jun 17-18*
       - 2025-07-30  # Jul 29-30
       - 2025-09-17  # Sep 16-17*
       - 2025-10-29  # Oct 28-29
       - 2025-12-10  # Dec 9-10*
     2026:
       - 2026-01-28
       - 2026-03-18
       # ...
   ```

4. 新建整合 Provider (`src/data/providers/economic_calendar_provider.py`):
   ```python
   class EconomicCalendarProvider:
       """整合 FRED + 静态 FOMC 的经济日历提供者."""

       def __init__(self):
           self._fred = FredCalendarProvider()
           self._fomc_dates = self._load_fomc_calendar()

       def get_economic_calendar(
           self, start_date: date, end_date: date
       ) -> EventCalendar:
           """获取完整经济日历 (FRED + FOMC)."""
           events = []
           # 从 FRED 获取 CPI/NFP/GDP/PPI
           events.extend(self._fred.get_release_dates(RELEASE_CPI, ...))
           events.extend(self._fred.get_release_dates(RELEASE_NFP, ...))
           # 从静态配置获取 FOMC
           events.extend(self._get_fomc_events(start_date, end_date))
           return EventCalendar(events=sorted(events, key=lambda e: e.event_date))

       def check_blackout_period(
           self, target_date: date, blackout_days: int = 3, ...
       ) -> tuple[bool, list[EconomicEvent]]:
           """检查是否处于 blackout 期间."""
           ...
   ```

5. 集成到 `UnifiedDataProvider`:
   ```python
   def get_economic_calendar(self, start: date, end: date) -> EventCalendar | None:
       return self._economic_calendar.get_economic_calendar(start, end)

   def check_macro_blackout(self, target_date: date, ...) -> tuple[bool, list[EconomicEvent]]:
       """检查是否处于宏观事件禁止开仓期."""
       return self._economic_calendar.check_blackout_period(target_date, ...)
   ```

**FRED API 配置**:
- 需要在 `.env` 添加: `FRED_API_KEY=your_api_key`
- 免费注册: https://fred.stlouisfed.org/docs/api/api_key.html

### 数据源对比

| 数据类型 | Provider | API | 免费额度 | 复杂度 |
|---------|----------|-----|---------|-------|
| 财报日期 | YahooProvider | yfinance | 无限制 | 低 |
| 除息日 | YahooProvider | yfinance | 无限制 | 低 |
| CPI/NFP/GDP/PPI | FredCalendarProvider | FRED | 120次/分钟 | 低 |
| FOMC | 静态 YAML | Fed Calendar | 无限制 | 低 |
| FDA/并购事件 | - | - | - | 暂缓 |

---

## 现有关键文件索引

### 数据模型层 (src/data/models/)

| 文件 | 主要模型 | 用途 |
|------|---------|------|
| `option.py` | `OptionQuote`, `Greeks`, `OptionChain` | 期权报价和Greeks |
| `stock.py` | `StockVolatility`, `StockQuote`, `KlineBar` | 股票波动率和报价 |
| `fundamental.py` | `Fundamental` | 基本面数据 + 财报日期/除息日 |
| `macro.py` | `MacroData`, `MacroIndicator` | 宏观指标(VIX等) |
| `technical.py` | `TechnicalData` | 技术分析数据 |
| `event.py` | `EconomicEvent`, `EventCalendar` | 宏观经济事件日历 |

### 计算引擎层 (src/engine/)

| 文件 | 主要函数 | 用途 |
|------|---------|------|
| `bs/probability.py` | `calc_win_prob()` | 胜率计算 |
| `bs/greeks.py` | `calc_bs_delta/gamma/theta/vega()` | Greeks计算 |
| `position/volatility/iv_rank.py` | `calc_iv_rank()`, `calc_iv_percentile()` | IV Rank/Percentile |
| `position/volatility/metrics.py` | `evaluate_volatility()` | 波动率综合评分 |
| `position/technical/rsi.py` | `calc_rsi()` | RSI指标 |
| `position/technical/adx.py` | `calc_adx()` | ADX指标 |
| `position/technical/moving_average.py` | `calc_sma()`, `calc_ema()` | 移动平均 |
| `position/technical/support.py` | `calc_support_level()`, `calc_resistance_level()` | 支撑阻力 |
| `position/risk_return.py` | `calc_tgr()`, `calc_roc_from_dte()` | TGR和ROC |
| `account/sentiment/vix.py` | `interpret_vix()`, `get_vix_zone()` | VIX解读 |
| `account/sentiment/vix_term.py` | `calc_vix_term_ratio()` | VIX期限结构 |
| `account/sentiment/pcr.py` | `calc_pcr()`, `interpret_pcr()` | Put/Call Ratio |
| `strategy/base.py` | `calc_sharpe_ratio()`, `calc_kelly_fraction()` | 策略指标 |

### 数据提供者层 (src/data/providers/)

| 文件 | 主要类 | 数据来源 |
|------|-------|---------|
| `unified_provider.py` | `UnifiedDataProvider` | 统一入口(智能路由) |
| `yahoo_provider.py` | `YahooProvider` | Yahoo Finance (股票/期权/基本面/财报日期) |
| `ibkr_provider.py` | `IBKRProvider` | Interactive Brokers (实时行情/交易) |
| `futu_provider.py` | `FutuProvider` | 富途证券 (港股/交易) |
| `fred_calendar_provider.py` | `FredCalendarProvider` | FRED (CPI/NFP/GDP/PPI 发布日期) |
| `economic_calendar_provider.py` | `EconomicCalendarProvider` | 整合 FRED + 静态 FOMC |

---

## 建议开发顺序

### Phase 1: 数据层扩展 (P0/P1) ✅ 方案已确定

1. **财报日期 + 除息日** - 扩展 `Fundamental` 模型，修改 `YahooProvider`
2. **宏观事件日历** - 新建 `EconomicEvent` 模型 + `FredCalendarProvider` + `EconomicCalendarProvider`

### Phase 2: 便捷工具函数

3. **流动性计算工具** - `calc_option_chain_volume()`, `calc_bid_ask_spread()`
4. **技术距离计算** - `calc_support_distance()`, `calc_resistance_distance()`
5. **价格位置判断** - `is_price_above_ma()`, `calc_otm_percent()`

### Phase 3: 信号过滤器集成

6. **Layer 1 市场过滤器** - 整合 VIX + 宏观事件检查
7. **Layer 2 标的过滤器** - 整合流动性/波动率/基本面/技术面/事件检查
8. **Layer 3 合约过滤器** - 整合DTE/Strike/收益风险/流动性检查

### Phase 4: 决策流程

9. **开仓决策引擎** - 按优先级执行三层过滤
10. **仓位计算** - Kelly Fraction 应用

---

## 下一步行动

1. ~~确认开发优先级和时间线~~ ✅
2. ~~为缺失的数据字段设计数据模型~~ ✅
3. ~~选择经济日历数据源~~ ✅ FRED API + 静态 FOMC (混合方案)
4. 开始按 Phase 顺序实现：
   - [x] 扩展 `Fundamental` 模型添加日历字段
   - [x] 修改 `YahooProvider.get_fundamental()` 提取日期
   - [x] 新建 `EconomicEvent` 数据模型
   - [ ] 新建 `FredCalendarProvider` 集成 FRED API (CPI/NFP/GDP/PPI)
   - [ ] 新建 `config/screening/fomc_calendar.yaml` 静态 FOMC 日历
   - [ ] 新建 `EconomicCalendarProvider` 整合 FRED + FOMC
   - [ ] 更新 `UnifiedDataProvider` 使用 `EconomicCalendarProvider`
   - [ ] 删除废弃的 `fmp_calendar_provider.py`
