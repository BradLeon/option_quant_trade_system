## Why

构建一个实盘可用的期权量化交易系统，专注于卖方策略（Short Put、Covered Call及轮动组合），实现从开仓筛选到绩效复盘的完整交易闭环。系统基于富途 OpenAPI 获取实时行情，使用 QuantConnect LEAN 框架进行策略开发和回测。

## What Changes

### 新增能力

**数据层 (Data Layer)**
- 富途 OpenAPI 集成，获取实时行情和期权链数据
- 历史数据存储和管理
- 数据清洗和标准化

**计算引擎层 (Engine Layer)**
- 期权 Greeks 计算引擎
- 交易信号生成器
- 风险指标计算

**业务模块层 (Business Layer)**
- Short Put 策略实现
- Covered Call 策略实现
- 轮动策略（组合切换逻辑）
- 持仓管理和监控
- 策略回测框架

**展示层 (Presentation Layer)**
- 交易信号推送（微信/邮件/Telegram）
- 持仓和绩效 Web 仪表盘
- 回测报告生成

## Impact

- Affected specs: 新建 4 个核心能力规格
  - `data-layer` - 数据获取和存储
  - `engine-layer` - 计算引擎
  - `business-layer` - 业务逻辑和策略
  - `presentation-layer` - 展示和通知
- Affected code: 全新项目，从零开始构建
- Dependencies:
  - 富途 OpenAPI + OpenD 网关
  - QuantConnect LEAN 框架
  - Python 3.11 环境
