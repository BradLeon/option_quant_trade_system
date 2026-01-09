## ADDED Requirements

### Requirement: Market Environment Filter

系统 SHALL 实现市场环境过滤器，作为筛选漏斗的第一层，评估当前市场是否适合开仓。支持美股和港股两个市场。

#### Scenario: 美股波动率指数评估
- **WHEN** 系统评估美股市场环境
- **THEN** 系统 MUST 获取当前 VIX 指数值（^VIX）
- **AND** 计算 VIX 在过去一年的历史百分位
- **AND** 如果 VIX 在配置的适宜区间（默认 15-28）且百分位在 30%-80%，标记为"有利"
- **AND** 如果 VIX 过高（>30）或过低（<12），标记为"不利"

#### Scenario: 港股波动率指数评估
- **WHEN** 系统评估港股市场环境
- **THEN** 系统 MUST 通过 2800.HK（盈富基金）期权链计算隐含波动率作为港股市场波动率指标
- **AND** 计算方法：取 ATM 期权的 IV 加权平均值（类似 VIX 计算逻辑）
- **AND** 计算该 IV 在过去一年的历史百分位
- **AND** 如果 IV 在配置的适宜区间（默认 18-32）且百分位在 30%-80%，标记为"有利"
- **AND** 如果 IV 过高（>35）或过低（<15），标记为"不利"

#### Scenario: 美股大盘趋势评估
- **WHEN** 系统评估美股大盘趋势
- **THEN** 系统 MUST 获取以下指数的 20/50/200 日均线数据：
  - SPY（标普500 ETF）- 代表大盘蓝筹
  - QQQ（纳斯达克100 ETF）- 代表科技成长
- **AND** 分别判断 SPY 和 QQQ 的均线排列状态（多头/空头/缠绕）
- **AND** 对于 Short Put 策略，如果目标标的所属市场指数呈多头排列（20日 > 50日 > 200日），标记为"有利"
- **AND** 如果均线呈空头排列（200日 > 50日 > 20日），标记为"不利"
- **AND** 如果 SPY 和 QQQ 走势背离，标记为"关注"

#### Scenario: 港股大盘趋势评估
- **WHEN** 系统评估港股大盘趋势
- **THEN** 系统 MUST 获取以下指数/ETF 的 20/50/200 日均线数据：
  - 盈富基金（2800.HK）- 代表恒生指数
  - 恒生科技 ETF（3033.HK）- 代表科技板块
- **AND** 分别判断两者的均线排列状态（多头/空头/缠绕）
- **AND** 对于 Short Put 策略，如果目标标的所属市场指数呈多头排列，标记为"有利"
- **AND** 如果均线呈空头排列，标记为"不利"
- **AND** 如果恒指和恒生科技走势背离，标记为"关注"

#### Scenario: VIX 期限结构评估
- **WHEN** 系统评估美股波动率期限结构
- **THEN** 系统 MUST 获取 VIX（30天，^VIX）和 VIX3M（3个月，^VIX3M）数据
- **AND** 计算 VIX/VIX3M 比值
- **AND** 如果比值 < 0.9（正向结构），标记为"有利"
- **AND** 如果比值 > 1.0（倒挂结构），标记为"不利"

#### Scenario: Put/Call Ratio 评估
- **WHEN** 系统评估市场情绪
- **THEN** 系统 MUST 获取对应市场的 Put/Call 成交量比率：
  - 美股：SPY 的 PCR
  - 港股：恒生指数期权的 PCR（如可获取）
- **AND** 如果 PCR 在 0.8-1.2 区间，标记为"中性"
- **AND** 如果 PCR > 1.3（过度悲观），对 Short Put 标记为"机会"

#### Scenario: 市场环境综合评估
- **WHEN** 所有市场指标评估完成
- **THEN** 系统 MUST 生成 MarketStatus 对象，包含：
  - market_type: 市场类型（US / HK）
  - is_favorable: 是否适合开仓（布尔值）
  - volatility_index: 波动率指数状态
    - us_vix: VIX 状态及数值（美股）
    - hk_iv: 2800.HK 期权 IV 状态及数值（港股，基于期权链计算）
  - trend_status: 趋势状态
    - us_spy: SPY 趋势状态（美股）
    - us_qqq: QQQ 趋势状态（美股）
    - hk_hsi: 恒生指数趋势状态（港股）
    - hk_hstech: 恒生科技趋势状态（港股）
  - term_structure_status: 期限结构状态（美股 VIX）
  - pcr_status: PCR 状态
  - unfavorable_reasons: 不利因素列表（如有）

#### Scenario: 按标的市场选择指标
- **WHEN** 系统评估特定标的的市场环境
- **THEN** 系统 MUST 根据标的所属市场选择对应指标：
  - 美股标的：使用 VIX、SPY/QQQ 趋势、VIX 期限结构
  - 港股标的：使用 VHSI、2800.HK/3033.HK 趋势
- **AND** 科技类美股标的额外参考 QQQ 趋势
- **AND** 科技类港股标的额外参考 3033.HK 趋势

### Requirement: Underlying Filter

系统 SHALL 实现标的过滤器，作为筛选漏斗的第二层，从观察列表中筛选适合交易的标的。

#### Scenario: IV Rank 筛选
- **WHEN** 系统评估标的的波动率水平
- **THEN** 系统 MUST 计算标的过去一年的 IV Rank
- **AND** 如果 IV Rank >= 配置阈值（默认 50），标的通过此项筛选
- **AND** 如果 IV Rank < 30，标的被标记为"权利金不足"

#### Scenario: IV/HV 比值筛选
- **WHEN** 系统评估隐含波动率与历史波动率的关系
- **THEN** 系统 MUST 计算 IV/HV 比值
- **AND** 如果 IV/HV > 1.0 且 < 2.0，标的通过此项筛选（期权溢价合理）
- **AND** 如果 IV/HV < 0.8，标的被标记为"IV 过低"
- **AND** 如果 IV/HV > 2.0，标的被标记为"需警惕潜在事件"

#### Scenario: 技术面筛选
- **WHEN** 系统评估标的的技术形态
- **THEN** 系统 MUST 计算以下技术指标：
  - RSI（14日）
  - 布林带 %B
  - ADX（趋势强度）
  - MA 排列状态
- **AND** 对于 Short Put，如果 RSI 在 30-45 且 %B 在 0.1-0.3（企稳信号），标记为"适宜开仓"
- **AND** 如果 ADX > 45（强趋势），标记为"趋势过强，暂缓"

#### Scenario: 基本面筛选（可选）
- **WHEN** 用户配置启用基本面筛选
- **THEN** 系统 MUST 获取以下基本面数据：
  - PE 历史百分位
  - 营收增长率
  - 分析师评级
- **AND** 如果 PE 处于历史低位（<30% 百分位），加分
- **AND** 如果分析师评级为"持有"到"买入"，加分

#### Scenario: 标的评分汇总
- **WHEN** 单个标的完成所有筛选项
- **THEN** 系统 MUST 生成 UnderlyingScore 对象，包含：
  - symbol: 标的代码
  - passed: 是否通过筛选（布尔值）
  - iv_rank: IV Rank 数值
  - iv_hv_ratio: IV/HV 比值
  - technical_score: 技术面综合评分
  - fundamental_score: 基本面综合评分（可选）
  - disqualify_reasons: 不合格原因列表（如有）

### Requirement: Contract Filter

系统 SHALL 实现合约过滤器，作为筛选漏斗的第三层，为通过标的筛选的每个标的选择最优期权合约。

#### Scenario: DTE 筛选
- **WHEN** 系统评估期权到期日
- **THEN** 系统 MUST 获取标的的全部期权链
- **AND** 筛选 DTE 在配置范围内（默认 25-45 天）的合约
- **AND** 优先选择 DTE 在 30-35 天的合约（Theta 效率最优）

#### Scenario: Delta 筛选
- **WHEN** 系统评估期权 Delta
- **THEN** 对于 Short Put，系统 MUST 筛选 Delta 在配置范围内（默认 -0.35 到 -0.15）的合约
- **AND** 优先选择 Delta 在 -0.25 到 -0.20 的合约（胜率与收益平衡）
- **AND** 对于 Covered Call，筛选 Delta 在 0.20 到 0.35 的合约

#### Scenario: 流动性筛选
- **WHEN** 系统评估期权流动性
- **THEN** 系统 MUST 检查以下流动性指标：
  - Bid/Ask 价差 <= 配置阈值（默认 10%）
  - Open Interest >= 配置阈值（默认 100）
- **AND** 如果不满足流动性要求，合约被排除

#### Scenario: 策略指标计算
- **WHEN** 合约通过基础筛选
- **THEN** 系统 MUST 调用计算引擎计算以下指标：
  - 期望收益 (Expected Return)
  - 收益标准差 (Return Std)
  - 夏普比率 (Sharpe Ratio)
  - 胜率 (Win Probability)
  - SAS (策略吸引力评分)
  - PREI (风险暴露指数)
  - TGR (Theta/Gamma 比率)
  - Kelly 仓位

#### Scenario: 合约评分与排序
- **WHEN** 合约完成所有指标计算
- **THEN** 系统 MUST 筛选满足以下条件的合约：
  - 夏普比率 >= 配置阈值（默认 1.0）
  - SAS >= 配置阈值（默认 50）
  - PREI <= 配置阈值（默认 75）
- **AND** 按 SAS 降序排列
- **AND** 生成 ContractOpportunity 对象列表

### Requirement: Screening Pipeline

系统 SHALL 实现筛选管道，串联三层筛选器，输出完整的筛选结果。

#### Scenario: 执行完整筛选流程
- **WHEN** 用户触发筛选（通过 CLI 或 API）
- **THEN** 系统 MUST 按顺序执行：
  1. 市场环境过滤
  2. 标的过滤（对观察列表中的每个标的）
  3. 合约过滤（对通过标的筛选的每个标的）
- **AND** 如果市场环境不利，直接返回不开仓建议
- **AND** 最终输出 ScreeningResult 对象

#### Scenario: 筛选结果数据结构
- **WHEN** 筛选流程完成
- **THEN** 系统 MUST 生成包含以下信息的结果：
  - screening_time: 筛选时间戳
  - market_status: 市场环境状态
  - strategy_type: 策略类型（Short Put / Covered Call）
  - opportunities: 机会列表（按 SAS 排序，最多 10 个）
  - summary: 筛选摘要（扫描标的数、通过标的数、机会合约数）

#### Scenario: 配置驱动的筛选参数
- **WHEN** 系统启动筛选
- **THEN** 系统 MUST 从配置文件加载筛选参数
- **AND** 支持通过命令行参数覆盖配置
- **AND** 不同策略类型使用不同的默认配置

### Requirement: Watchlist Management

系统 SHALL 支持观察列表管理，定义待筛选的标的集合。

#### Scenario: 配置观察列表
- **WHEN** 用户配置观察列表
- **THEN** 系统 MUST 支持以下配置方式：
  - 直接指定标的代码列表
  - 指定观察列表文件路径（JSON/YAML）
  - 通过命令行参数传入

#### Scenario: 动态观察列表（可选）
- **WHEN** 用户配置动态观察列表规则
- **THEN** 系统 MAY 支持基于条件动态生成观察列表：
  - 按市值筛选（如 S&P 500 成分股）
  - 按行业筛选
  - 按持仓标的筛选

### Requirement: Screening CLI

系统 SHALL 提供命令行接口，支持手动触发筛选。

#### Scenario: 运行筛选命令
- **WHEN** 用户执行筛选命令
- **THEN** 系统 MUST 支持以下命令格式：
  ```bash
  python -m src.business.cli screen \
    --watchlist AAPL,MSFT,NVDA \
    --strategy short_put \
    --config config/screening/default.yaml \
    --output json
  ```
- **AND** 输出筛选结果到控制台或文件

#### Scenario: 筛选结果输出格式
- **WHEN** 筛选完成
- **THEN** 系统 MUST 支持以下输出格式：
  - JSON 格式（便于程序处理）
  - 表格格式（便于人工阅读）
- **AND** 包含执行时间和配置摘要
