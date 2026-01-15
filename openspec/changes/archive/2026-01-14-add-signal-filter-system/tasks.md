## 1. 数据层扩展 - 股票财经日历

- [x] 1.1 扩展 `Fundamental` 模型，添加 `earnings_date: date | None` 和 `ex_dividend_date: date | None` 字段
- [x] 1.2 修改 `YahooProvider.get_fundamental()` 从 yfinance `info` 字典提取:
  - `earningsTimestamp` / `earningsTimestampStart` / `earningsTimestampEnd`
  - `exDividendDate` / `dividendDate`
- [x] 1.3 添加日期转换工具函数处理 Unix 时间戳
- [ ] 1.4 编写单元测试验证财报/除息日期获取

## 2. 数据层扩展 - 宏观事件日历 (FRED + 静态 FOMC)

- [x] 2.1 创建 `src/data/models/event.py`，定义:
  - `EconomicEventType` 枚举（FOMC, CPI, NFP, GDP, PCE, PPI, EARNINGS, OTHER）
  - `EconomicEvent` 数据类（event_type, date, name, impact, country）
  - `EventCalendar` 容器类
- [ ] 2.2 创建 `src/data/providers/fred_calendar_provider.py`:
  - 实现 FRED (Federal Reserve Economic Data) API 客户端
  - API 端点: `/fred/releases/dates?include_release_dates_with_no_data=true`
  - 免费额度: 120次/分钟 (无每日限制)
  - Release IDs: 10=CPI, 50=NFP, 53=GDP, 46=PPI
  - `get_release_dates(release_id, start_date, end_date)` → `list[EconomicEvent]`
- [ ] 2.3 创建 `config/screening/fomc_calendar.yaml`:
  - 静态 FOMC 会议日期 (2025-2026)
  - 数据来源: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  - 每年更新一次
- [ ] 2.4 创建 `src/data/providers/economic_calendar_provider.py`:
  - 整合 FRED API + 静态 FOMC 日历
  - `get_economic_calendar(start_date, end_date)` → `EventCalendar`
  - `check_blackout_period(target_date, blackout_days, events)` → `tuple[bool, list]`
- [ ] 2.5 更新 `UnifiedDataProvider` 使用 `EconomicCalendarProvider`
- [ ] 2.6 删除废弃的 `fmp_calendar_provider.py`
- [ ] 2.7 编写单元测试（使用 mock 数据）

## 3. 业务层 - MarketFilter 宏观事件检查

- [x] 3.1 在 `MarketFilterConfig` 中添加:
  - `macro_event_blackout_days: int = 3`（事件前禁止开仓天数）
  - `blackout_events: list[str] = ["FOMC", "CPI", "NFP"]`（需要回避的事件类型）
- [x] 3.2 在 `MarketFilter` 中实现 `_check_macro_events()`:
  - 获取未来 N 天的宏观事件
  - 检查是否有黑名单事件在 blackout 期间内
  - 返回事件列表和是否应暂停开仓
- [x] 3.3 更新 `MarketStatus` 模型添加 `macro_events` 和 `macro_blackout` 字段
- [x] 3.4 在 `_evaluate_us_market()` 中集成宏观事件检查
- [ ] 3.5 编写单元测试

## 4. 业务层 - UnderlyingFilter 财报/除息日检查

- [x] 4.1 在 `UnderlyingFilterConfig` 中添加:
  - `min_days_to_earnings: int = 7`（距财报最小天数）
  - `min_days_to_ex_dividend: int = 7`（距除息日最小天数，仅 CC）
  - `allow_earnings_if_before_expiry: bool = True`（允许合约在财报前到期）
- [x] 4.2 在 `UnderlyingFilter` 中实现 `_check_event_calendar()`:
  - 从 `Fundamental` 获取 `earnings_date` 和 `ex_dividend_date`
  - 计算距事件天数
  - 返回是否通过及原因
- [x] 4.3 更新 `UnderlyingScore` 模型添加 `earnings_date`、`ex_dividend_date`、`days_to_earnings`
- [x] 4.4 在 `_evaluate_single()` 中集成事件日历检查
- [ ] 4.5 编写单元测试

## 5. 业务层 - ContractFilter 工具函数

- [x] 5.1 创建/扩展 `src/engine/contract/liquidity.py`:
  - `calc_bid_ask_spread(bid, ask) -> float | None`（返回百分比）
  - `calc_option_chain_volume(chain) -> int`（计算期权链总成交量）
- [x] 5.2 创建/扩展 `src/engine/contract/metrics.py`:
  - `calc_otm_percent(spot, strike, option_type) -> float`
  - `calc_theta_premium_ratio(theta, premium) -> float`
- [x] 5.3 扩展 `src/engine/position/technical/support.py`:
  - `calc_support_distance(price, support) -> float`（返回百分比）- 已存在
  - `calc_resistance_distance(price, resistance) -> float` - 已存在
- [x] 5.4 在 `ContractFilter` 中使用新工具函数增强过滤逻辑
- [x] 5.5 编写单元测试

## 6. 配置和集成

- [x] 6.1 更新 `src/business/config/screening_config.py` 添加所有新配置项
- [x] 6.2 更新 `ScreeningPipeline` 支持事件日历检查
- [ ] 6.3 编写端到端集成测试
- [x] 6.4 更新文档 `docs/development/signal_filter_indicator_analysis.md` 标记已实现的指标

## 7. Stock Pool 管理

- [x] 7.1 创建 `config/screening/stock_pools.yaml` 配置文件:
  - `us_default`: 美股默认池 (SPY, QQQ, AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA)
  - `us_large_cap`: 美股大盘股池
  - `hk_default`: 港股默认池 (2800.HK, 3033.HK, 0700.HK, 9988.HK, 9618.HK)
  - `hk_large_cap`: 港股大盘股池
- [x] 7.2 创建 `src/business/screening/stock_pool.py`:
  - `StockPoolManager` 类
  - `load_pool(name: str) -> list[str]` 加载股票池
  - `list_pools() -> list[str]` 列出所有可用池
  - `get_default_pool(market_type: MarketType) -> list[str]` 获取默认池
- [x] 7.3 修改 `src/business/cli/commands/screen.py`:
  - 添加 `--pool` / `-p` 选项
  - 支持 `--pool us_large_cap` 形式调用
  - 与现有 `--symbols` 选项互斥或组合
- [x] 7.4 编写 Stock Pool 单元测试

## 8. 文档 - Screening README

- [x] 8.1 创建 `src/business/screening/README.md`:
  - 概述：三层筛选漏斗说明
  - 数据流水线架构图 (Mermaid/ASCII)
  - 开仓决策流程图
  - 各层过滤器详解
  - 使用方法示例
  - 配置说明
- [x] 8.2 在 README 中包含 Stock Pool 使用说明

## 9. 验收标准

- [x] 9.1 所有 P0/P1 指标检查已实现
- [x] 9.2 宏观事件（FOMC/CPI/NFP）在发布前 3 天触发暂停开仓
- [x] 9.3 财报在 7 天内的标的被过滤（除非合约在财报前到期）
- [x] 9.4 Covered Call 策略检查除息日风险
- [x] 9.5 Stock Pool 配置可通过 CLI `--pool` 选项使用
- [x] 9.6 README 包含完整的数据流和决策流程图
- [x] 9.7 所有单元测试通过
