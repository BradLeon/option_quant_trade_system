## ADDED Requirements

### Requirement: Signal Push Interface

系统 SHALL 提供统一的信号推送接口，支持多种推送渠道。

#### Scenario: 推送接口抽象
- **WHEN** 业务层生成交易信号
- **THEN** 展示层通过统一接口推送到用户配置的渠道
- **AND** 支持同时推送到多个渠道

### Requirement: WeChat Push

系统 SHALL 支持通过微信推送交易信号。

#### Scenario: 通过 Server酱 推送
- **WHEN** 用户配置了 Server酱 SendKey
- **THEN** 系统通过 Server酱 API 发送信号到微信
- **AND** 消息包含：信号类型、标的、价格、理由、时间

#### Scenario: 通过 WxPusher 推送
- **WHEN** 用户配置了 WxPusher Token
- **THEN** 系统通过 WxPusher API 发送信号到微信
- **AND** 支持富文本格式

#### Scenario: 推送失败处理
- **WHEN** 微信推送失败（网络错误或 Token 失效）
- **THEN** 系统记录错误日志
- **AND** 尝试通过备用渠道推送

### Requirement: Email Push

系统 SHALL 支持通过邮件推送交易信号。

#### Scenario: 发送邮件通知
- **WHEN** 用户配置了邮箱地址和 SMTP 设置
- **THEN** 系统发送包含信号详情的邮件
- **AND** 邮件主题明确标识信号类型

### Requirement: Telegram Push

系统 SHALL 支持通过 Telegram Bot 推送交易信号。

#### Scenario: 发送 Telegram 消息
- **WHEN** 用户配置了 Telegram Bot Token 和 Chat ID
- **THEN** 系统通过 Telegram Bot API 发送消息
- **AND** 支持 Markdown 格式

### Requirement: Web Dashboard

系统 SHALL 提供 Web 仪表盘，展示持仓和策略状态。

#### Scenario: 持仓概览页面
- **WHEN** 用户访问仪表盘首页
- **THEN** 显示当前所有持仓的汇总信息：
  - 持仓列表（合约、数量、成本、现价、盈亏）
  - 组合总价值和总盈亏
  - 组合 Greeks 汇总
  - 风险指标

#### Scenario: 策略筛选页面
- **WHEN** 用户访问策略筛选页面
- **THEN** 用户可以：
  - 选择标的
  - 设置筛选条件（Delta、到期日、流动性等）
  - 查看符合条件的期权列表
  - 查看每个期权的详细 Greeks

#### Scenario: 回测结果页面
- **WHEN** 用户运行回测后查看结果
- **THEN** 显示：
  - 净值曲线图
  - 回撤曲线图
  - 关键指标（收益率、夏普、最大回撤等）
  - 交易明细列表

#### Scenario: 绩效分析页面
- **WHEN** 用户访问绩效分析页面
- **THEN** 显示实盘交易的统计分析：
  - 按月/季/年的收益汇总
  - 按策略的收益对比
  - 按标的的收益分布
  - 胜率和盈亏比分析

### Requirement: Performance Report Generation

系统 SHALL 能够生成绩效报告文件。

#### Scenario: 生成 PDF 报告
- **WHEN** 用户请求导出绩效报告
- **THEN** 系统生成包含图表和数据的 PDF 文件
- **AND** 报告包含：
  - 报告期间概述
  - 收益曲线
  - 关键指标汇总
  - 交易明细

#### Scenario: 生成 HTML 报告
- **WHEN** 用户选择 HTML 格式
- **THEN** 系统生成可交互的 HTML 报告
- **AND** 支持图表缩放和数据筛选

### Requirement: Real-time Data Display

系统 SHALL 在仪表盘上实时更新数据。

#### Scenario: 自动刷新行情
- **WHEN** 市场开盘期间
- **THEN** 仪表盘每 N 秒（可配置）自动刷新行情数据
- **AND** 高亮显示价格变动

#### Scenario: 实时信号展示
- **WHEN** 系统生成新的交易信号
- **THEN** 信号立即显示在仪表盘上
- **AND** 伴随视觉或声音提示
