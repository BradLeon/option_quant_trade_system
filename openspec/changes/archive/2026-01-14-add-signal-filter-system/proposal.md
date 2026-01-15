## Why

现有 `src/business/screening/` 模块已实现三层过滤器框架，但缺少关键的**事件日历集成**（财报日、除息日、宏观事件），无法满足 `options_signal_filter_system_v2.md` 中对二元事件回避的核心要求。同时，部分工具函数（如 Bid-Ask Spread 计算、OTM 百分比等）尚未封装，影响合约层过滤的完整性。

## What Changes

### 数据层扩展 (data-layer)
- 扩展 `Fundamental` 模型，添加 `earnings_date`、`ex_dividend_date` 字段
- 修改 `YahooProvider.get_fundamental()` 从 yfinance 提取财报/除息日期
- 新增 `EconomicEvent` 模型和 `EconomicCalendarProvider` (FRED API + 静态 FOMC) 用于获取宏观事件日历（FOMC、CPI、NFP、GDP、PPI 等）

### 业务层增强 (signal-filter)
- **新增 Stock Pool 管理**：配置驱动的股票池，替代硬编码默认列表
- 在 `MarketFilter` 中添加宏观事件黑名单检查（FOMC/CPI 发布前 3 天暂停开仓）
- 在 `UnderlyingFilter` 中添加财报/除息日检查（距事件 > 7 天 或 合约在事件前到期）
- 封装工具函数：`calc_bid_ask_spread()`、`calc_otm_percent()`、`calc_support_distance()`
- 完善 `ContractFilter` 中的合约流动性和收益风险验证
- **新增 README 文档**：包含数据流水线和开仓决策流程图

### 配置扩展
- 在 `ScreeningConfig` 中添加事件日历相关配置项
- **新增 `stock_pools.yaml`**：股票池配置文件

## Impact

- **Affected specs**: `data-layer`, `signal-filter`（新增）
- **Affected code**:
  - `src/data/models/fundamental.py` - 添加日历字段
  - `src/data/models/event.py` - 新增事件模型
  - `src/data/providers/yahoo_provider.py` - 扩展基本面获取
  - `src/data/providers/fred_calendar_provider.py` - 新增 FRED API 客户端
  - `src/data/providers/economic_calendar_provider.py` - 新增宏观事件日历提供者 (FRED + 静态 FOMC)
  - `config/screening/fomc_calendar.yaml` - **新增** 静态 FOMC 会议日期
  - `src/business/screening/filters/market_filter.py` - 宏观事件检查
  - `src/business/screening/filters/underlying_filter.py` - 财报/除息日检查
  - `src/business/screening/filters/contract_filter.py` - 合约过滤增强
  - `src/business/config/screening_config.py` - 配置扩展
  - `src/business/screening/stock_pool.py` - **新增** Stock Pool 管理器
  - `src/business/cli/commands/screen.py` - 添加 `--pool` 选项
  - `config/screening/stock_pools.yaml` - **新增** 股票池配置
  - `src/business/screening/README.md` - **新增** 文档和流程图
