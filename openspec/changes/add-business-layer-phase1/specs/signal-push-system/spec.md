## ADDED Requirements

### Requirement: Notification Channel Interface

系统 SHALL 定义通知渠道抽象接口，支持多种推送渠道实现。

#### Scenario: 通知渠道接口定义
- **WHEN** 实现新的推送渠道
- **THEN** 渠道 MUST 实现以下接口方法：
  - `send(message: Message) -> SendResult` - 发送单条消息
  - `send_batch(messages: List[Message]) -> List[SendResult]` - 批量发送
  - `test_connection() -> bool` - 测试连接是否正常
- **AND** 返回发送结果，包含成功/失败状态和错误信息

### Requirement: Feishu Webhook Channel

系统 SHALL 实现飞书 Webhook 推送渠道，作为主要推送方式。

#### Scenario: 飞书 Webhook 配置
- **WHEN** 配置飞书推送
- **THEN** 系统 MUST 支持以下配置项：
  - webhook_url: 飞书机器人 Webhook 地址
  - secret: 签名密钥（可选，用于安全验证）
  - timeout: 请求超时时间（默认 10 秒）
- **AND** 配置通过环境变量或配置文件提供

#### Scenario: 飞书消息发送
- **WHEN** 系统发送消息到飞书
- **THEN** 系统 MUST：
  - 构造 HTTP POST 请求
  - 设置正确的 Content-Type 头
  - 如配置了签名密钥，计算并添加签名
  - 处理响应，判断发送是否成功
- **AND** 如果发送失败，记录错误并返回失败结果

#### Scenario: 飞书连接测试
- **WHEN** 用户测试飞书连接
- **THEN** 系统 MUST 发送一条测试消息
- **AND** 返回连接状态（成功/失败）和错误详情（如有）

### Requirement: Screening Result Card Formatter

系统 SHALL 实现筛选结果卡片格式化器，将筛选结果转换为飞书卡片消息。

#### Scenario: 开仓机会卡片格式
- **WHEN** 系统推送开仓机会
- **THEN** 系统 MUST 生成包含以下内容的飞书卡片：
  - 标题：策略类型 + "开仓机会"（如"Short Put 开仓机会"）
  - 标题颜色：绿色（表示机会）
  - 核心信息字段：
    - 标的代码和当前价格
    - 行权价和权利金
    - DTE 和 Delta
  - 评分指标：
    - SAS（策略吸引力分数）
    - 夏普比率
    - 胜率
    - 建议 Kelly 仓位
  - 市场状态摘要（可选）
  - 筛选时间戳

#### Scenario: 无机会提示卡片
- **WHEN** 筛选未发现合适机会
- **THEN** 系统 MUST 生成提示卡片：
  - 标题："筛选完成 - 暂无机会"
  - 标题颜色：灰色
  - 内容：扫描标的数量、未通过原因摘要
  - 市场状态概览

#### Scenario: 市场不利提示卡片
- **WHEN** 市场环境不适合开仓
- **THEN** 系统 MUST 生成警示卡片：
  - 标题："市场环境不利 - 建议观望"
  - 标题颜色：黄色
  - 内容：不利因素列表（VIX 过高、趋势向下等）
  - 建议操作

### Requirement: Alert Card Formatter

系统 SHALL 实现预警卡片格式化器，将监控预警转换为飞书卡片消息。

#### Scenario: 风险预警卡片格式
- **WHEN** 系统推送风险预警（红色级别）
- **THEN** 系统 MUST 生成包含以下内容的飞书卡片：
  - 标题："风险预警" + 预警类型
  - 标题颜色：红色
  - 核心信息：
    - 相关标的和合约
    - 触发指标和当前值
    - 阈值对比
  - 建议操作（如"立即止损"、"考虑移仓"）
  - 预警时间

#### Scenario: 关注提醒卡片格式
- **WHEN** 系统推送关注提醒（黄色级别）
- **THEN** 系统 MUST 生成包含以下内容的飞书卡片：
  - 标题："关注提醒" + 提醒类型
  - 标题颜色：黄色
  - 核心信息：触发指标和建议关注点
  - 无需立即行动的说明

#### Scenario: 机会提醒卡片格式
- **WHEN** 系统推送机会提醒（绿色级别）
- **THEN** 系统 MUST 生成包含以下内容的飞书卡片：
  - 标题："发现机会" + 机会类型
  - 标题颜色：绿色
  - 核心信息：机会详情（如"可加仓"、"波动率套利"）
  - 相关指标数据

#### Scenario: 监控报告汇总卡片
- **WHEN** 系统推送定期监控报告
- **THEN** 系统 MUST 生成汇总卡片：
  - 标题："持仓监控报告"
  - 组合概览：总 Delta、总 Theta、组合 TGR
  - 持仓状态表格：每个持仓的关键指标
  - 预警汇总：按级别统计预警数量
  - 报告时间

### Requirement: Message Dispatcher

系统 SHALL 实现消息调度器，管理消息发送流程和策略。

#### Scenario: 消息队列管理
- **WHEN** 系统生成多条待发送消息
- **THEN** 调度器 MUST：
  - 按优先级排序（红色 > 黄色 > 绿色）
  - 维护发送队列
  - 按配置的发送频率依次发送

#### Scenario: 消息聚合
- **WHEN** 短时间内产生多条同类型消息
- **THEN** 调度器 MUST 支持消息聚合：
  - 将同类型预警合并为一条汇总消息
  - 配置聚合时间窗口（默认 5 分钟）
  - 聚合后的消息包含所有原始预警摘要

#### Scenario: 防骚扰机制
- **WHEN** 同一预警频繁触发
- **THEN** 调度器 MUST 实现防骚扰：
  - 同一持仓同一指标在 N 分钟内（默认 30 分钟）不重复推送
  - 如果级别升高（黄色→红色），立即推送
  - 记录已发送预警，用于去重判断

#### Scenario: 发送失败重试
- **WHEN** 消息发送失败
- **THEN** 调度器 MUST 实现重试机制：
  - 最多重试 3 次
  - 重试间隔递增（1秒、5秒、15秒）
  - 超过重试次数后记录错误日志

#### Scenario: 静默时段
- **WHEN** 配置了静默时段
- **THEN** 调度器 MUST：
  - 在静默时段内不发送消息
  - 将消息缓存到队列
  - 静默结束后发送汇总消息

### Requirement: Push Configuration

系统 SHALL 支持灵活的推送配置。

#### Scenario: 推送频率配置
- **WHEN** 用户配置推送策略
- **THEN** 系统 MUST 支持以下配置：
  ```yaml
  push:
    min_interval: 60              # 最小推送间隔（秒）
    aggregation_window: 300       # 聚合时间窗口（秒）
    silent_hours:                 # 静默时段
      start: "23:00"
      end: "07:00"
    dedup_window: 1800            # 去重时间窗口（秒）
  ```

#### Scenario: 推送内容配置
- **WHEN** 用户配置推送内容
- **THEN** 系统 MUST 支持以下配置：
  ```yaml
  content:
    include_market_status: true   # 是否包含市场状态
    include_suggestions: true     # 是否包含建议操作
    max_opportunities: 5          # 最多推送机会数量
    alert_levels:                 # 启用的预警级别
      - red
      - yellow
  ```

#### Scenario: 多渠道配置
- **WHEN** 用户配置多个推送渠道
- **THEN** 系统 MUST 支持：
  - 为不同类型消息配置不同渠道
  - 同一消息发送到多个渠道
  - 各渠道独立的配置参数

### Requirement: Push CLI

系统 SHALL 提供命令行接口，支持手动触发推送。

#### Scenario: 测试推送命令
- **WHEN** 用户测试推送配置
- **THEN** 系统 MUST 支持以下命令：
  ```bash
  python -m src.business.cli notify --test
  ```
- **AND** 发送测试卡片到配置的渠道
- **AND** 输出发送结果

#### Scenario: 手动推送筛选结果
- **WHEN** 用户手动触发筛选并推送
- **THEN** 系统 MUST 支持以下命令：
  ```bash
  python -m src.business.cli screen \
    --watchlist AAPL,MSFT \
    --strategy short_put \
    --push
  ```
- **AND** 执行筛选后将结果推送到配置的渠道

#### Scenario: 手动推送监控报告
- **WHEN** 用户手动触发监控并推送
- **THEN** 系统 MUST 支持以下命令：
  ```bash
  python -m src.business.cli monitor \
    --positions positions.json \
    --push
  ```
- **AND** 执行监控后将预警推送到配置的渠道

### Requirement: Push Logging

系统 SHALL 记录推送历史，便于追溯和调试。

#### Scenario: 推送日志记录
- **WHEN** 系统发送消息
- **THEN** 系统 MUST 记录以下信息：
  - 发送时间
  - 消息类型
  - 目标渠道
  - 发送结果（成功/失败）
  - 失败原因（如有）
  - 消息内容摘要

#### Scenario: 推送统计
- **WHEN** 用户查询推送统计
- **THEN** 系统 MUST 提供：
  - 各类型消息发送数量
  - 发送成功率
  - 平均发送延迟
  - 最近失败记录
