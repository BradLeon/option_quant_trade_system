## Why

实现期权量化交易系统的业务模块层第一阶段，完成从"数据+计算引擎"到"可用交易辅助工具"的跨越。当前系统已具备完整的数据层（Yahoo/Futu/IBKR 多数据源）和计算引擎层（B-S模型、Greeks、策略指标计算），但缺乏将这些能力整合成可操作交易流程的业务模块。

本阶段聚焦三个核心子系统：
1. **开仓筛选系统** - 多层漏斗筛选期权合约，输出交易机会
2. **持仓监控系统** - 实时监控持仓风险，生成预警信号
3. **信号推送系统** - 将信号实时推送到飞书群，便于移动端接收

## What Changes

### 新增能力

**开仓筛选系统 (Opening Filter System)**
- 三层筛选漏斗：市场环境过滤 → 标的过滤 → 合约过滤
- 市场环境过滤：VIX、SPY趋势、VIX期限结构、PCR
- 标的过滤：基本面评分、技术面评分、IV Rank
- 合约过滤：DTE选择、行权价选择、SAS/PREI评分、Kelly仓位

**持仓监控系统 (Position Monitor System)**
- 三层监控架构：Portfolio级 → Position级 → Capital级
- Portfolio级：Beta加权Delta、总Theta、总Vega、组合TGR
- Position级：Moneyness、个股Gamma、IV/HV、PREI
- Capital级：夏普比率、Kelly使用率、最大回撤

**信号推送系统 (Signal Push System)**
- 飞书Webhook推送集成
- 信号类型：开仓机会、持仓预警、平仓建议
- 信号格式化：富文本卡片、关键指标高亮
- 推送频率控制：防骚扰机制

### 明确不包含（Phase 2）
- 策略回测系统
- 实盘追踪系统
- 绩效复盘系统

## Impact

- Affected specs:
  - 新建 `opening-filter-system` - 开仓筛选系统
  - 新建 `position-monitor-system` - 持仓监控系统
  - 新建 `signal-push-system` - 信号推送系统
- Affected code:
  - 新建 `src/business/` 目录
  - 新建 `src/business/screening/` - 筛选逻辑
  - 新建 `src/business/monitoring/` - 监控逻辑
  - 新建 `src/business/notification/` - 推送逻辑
- Dependencies:
  - 依赖已有 `src/data/` 数据层
  - 依赖已有 `src/engine/` 计算引擎层
  - 新增飞书 Webhook API 集成
