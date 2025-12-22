## 1. 项目基础设施

- [ ] 1.1 创建 `src/business/` 目录结构
- [ ] 1.2 创建业务层配置文件结构 `config/screening/` 和 `config/monitoring/`
- [ ] 1.3 实现配置加载模块 `src/business/config/`
- [ ] 1.4 添加业务层依赖到 requirements.txt（如 `requests` 用于飞书推送）

## 2. 开仓筛选系统实现

### 2.1 数据模型
- [ ] 2.1.1 定义筛选结果数据模型 `src/business/screening/models.py`
  - MarketStatus（市场状态）
  - UnderlyingScore（标的评分）
  - ContractOpportunity（合约机会）
  - ScreeningResult（筛选结果）

### 2.2 市场环境过滤器
- [ ] 2.2.1 实现 VIX 指数评估 `src/business/screening/filters/market_filter.py`
- [ ] 2.2.2 实现 SPY 趋势评估
- [ ] 2.2.3 实现 VIX 期限结构评估
- [ ] 2.2.4 实现 Put/Call Ratio 评估
- [ ] 2.2.5 实现市场环境综合评估
- [ ] 2.2.6 编写市场过滤器单元测试

### 2.3 标的过滤器
- [ ] 2.3.1 实现 IV Rank 筛选 `src/business/screening/filters/underlying_filter.py`
- [ ] 2.3.2 实现 IV/HV 比值筛选
- [ ] 2.3.3 实现技术面筛选（集成 engine/position/technical）
- [ ] 2.3.4 实现基本面筛选（可选，集成 engine/position/fundamental）
- [ ] 2.3.5 实现标的评分汇总
- [ ] 2.3.6 编写标的过滤器单元测试

### 2.4 合约过滤器
- [ ] 2.4.1 实现 DTE 筛选 `src/business/screening/filters/contract_filter.py`
- [ ] 2.4.2 实现 Delta 筛选
- [ ] 2.4.3 实现流动性筛选
- [ ] 2.4.4 实现策略指标计算（集成 engine/strategy）
- [ ] 2.4.5 实现合约评分与排序
- [ ] 2.4.6 编写合约过滤器单元测试

### 2.5 筛选管道
- [ ] 2.5.1 实现筛选管道 `src/business/screening/pipeline.py`
- [ ] 2.5.2 实现观察列表管理
- [ ] 2.5.3 编写筛选管道集成测试

### 2.6 配置文件
- [ ] 2.6.1 创建 Short Put 策略筛选配置 `config/screening/short_put.yaml`
- [ ] 2.6.2 创建 Covered Call 策略筛选配置 `config/screening/covered_call.yaml`

## 3. 持仓监控系统实现

### 3.1 数据模型
- [ ] 3.1.1 定义监控数据模型 `src/business/monitoring/models.py`
  - PositionData（持仓数据）
  - MonitorStatus（监控状态：Green/Yellow/Red）
  - Alert（预警信息）
  - MonitorResult（监控结果）

### 3.2 组合级监控器
- [ ] 3.2.1 实现 Beta 加权 Delta 监控 `src/business/monitoring/monitors/portfolio_monitor.py`
- [ ] 3.2.2 实现组合 Theta/Vega/Gamma 监控
- [ ] 3.2.3 实现组合 TGR 监控
- [ ] 3.2.4 实现持仓相关性监控
- [ ] 3.2.5 编写组合监控器单元测试

### 3.3 持仓级监控器
- [ ] 3.3.1 实现 Moneyness 监控 `src/business/monitoring/monitors/position_monitor.py`
- [ ] 3.3.2 实现 Delta/Gamma 变化监控
- [ ] 3.3.3 实现 IV/HV 比值监控
- [ ] 3.3.4 实现 PREI 监控
- [ ] 3.3.5 实现 DTE 到期提醒
- [ ] 3.3.6 实现盈亏监控（止盈/止损信号）
- [ ] 3.3.7 编写持仓监控器单元测试

### 3.4 资金级监控器
- [ ] 3.4.1 实现夏普比率监控 `src/business/monitoring/monitors/capital_monitor.py`
- [ ] 3.4.2 实现 Kelly 使用率监控
- [ ] 3.4.3 实现保证金使用率监控
- [ ] 3.4.4 实现最大回撤监控
- [ ] 3.4.5 编写资金监控器单元测试

### 3.5 预警生成
- [ ] 3.5.1 实现预警生成器 `src/business/monitoring/alerts.py`
- [ ] 3.5.2 实现预警分级逻辑
- [ ] 3.5.3 实现预警去重机制
- [ ] 3.5.4 编写预警生成器单元测试

### 3.6 动态阈值调整
- [ ] 3.6.1 实现市场状态感知 `src/business/monitoring/threshold_adjuster.py`
- [ ] 3.6.2 实现高波动率环境阈值调整
- [ ] 3.6.3 实现趋势/震荡环境阈值调整
- [ ] 3.6.4 编写阈值调整单元测试

### 3.7 配置文件
- [ ] 3.7.1 创建监控阈值配置 `config/monitoring/thresholds.yaml`

## 4. 信号推送系统实现

### 4.1 通知渠道接口
- [ ] 4.1.1 定义通知渠道基类 `src/business/notification/channels/base.py`
- [ ] 4.1.2 定义消息和发送结果数据模型

### 4.2 飞书推送渠道
- [ ] 4.2.1 实现飞书 Webhook 发送 `src/business/notification/channels/feishu.py`
- [ ] 4.2.2 实现签名计算（如配置了密钥）
- [ ] 4.2.3 实现连接测试
- [ ] 4.2.4 编写飞书渠道单元测试

### 4.3 消息格式化器
- [ ] 4.3.1 实现筛选结果卡片格式化 `src/business/notification/formatters/screening_card.py`
- [ ] 4.3.2 实现预警卡片格式化 `src/business/notification/formatters/alert_card.py`
- [ ] 4.3.3 实现监控报告卡片格式化
- [ ] 4.3.4 编写格式化器单元测试

### 4.4 消息调度器
- [ ] 4.4.1 实现消息队列 `src/business/notification/dispatcher.py`
- [ ] 4.4.2 实现消息聚合
- [ ] 4.4.3 实现防骚扰机制
- [ ] 4.4.4 实现发送失败重试
- [ ] 4.4.5 编写调度器单元测试

### 4.5 推送日志
- [ ] 4.5.1 实现推送历史记录
- [ ] 4.5.2 实现推送统计查询

### 4.6 配置文件
- [ ] 4.6.1 创建推送配置 `config/notification/feishu.yaml`

## 5. CLI 命令行工具

- [ ] 5.1 实现 CLI 入口 `src/business/cli.py`
- [ ] 5.2 实现 `screen` 命令（筛选）
- [ ] 5.3 实现 `monitor` 命令（监控）
- [ ] 5.4 实现 `notify` 命令（推送测试）
- [ ] 5.5 实现 `--push` 参数（筛选/监控后推送）
- [ ] 5.6 编写 CLI 集成测试

## 6. 集成与文档

- [ ] 6.1 编写端到端集成测试（筛选→监控→推送）
- [ ] 6.2 创建示例配置文件
- [ ] 6.3 创建示例持仓文件 `examples/positions.json`
- [ ] 6.4 更新 README.md 添加业务层使用说明
- [ ] 6.5 创建 `.env.example` 添加飞书 Webhook 配置示例

## 验证检查清单

- [ ] 所有单元测试通过
- [ ] 集成测试通过
- [ ] CLI 命令可正常运行
- [ ] 飞书推送功能测试通过
- [ ] 配置文件格式正确
- [ ] 文档完整准确
