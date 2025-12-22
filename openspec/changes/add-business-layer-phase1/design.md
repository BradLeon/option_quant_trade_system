## Context

本项目已完成数据层和计算引擎层的实现：
- **数据层** (`src/data/`): Yahoo/Futu/IBKR 三个数据源，支持股票行情、期权链、历史K线、基本面数据
- **计算引擎层** (`src/engine/`): B-S模型计算、Greeks计算、策略指标（SAS/PREI/TGR/Kelly）、技术指标（MA/ADX/RSI/BB）

业务模块层需要将这些能力整合，形成完整的交易辅助流程。本阶段聚焦"开仓筛选"和"持仓监控"两个核心场景，并通过飞书推送实现移动端信号接收。

### 参考设计文档
- `data/knowledge/期权量化指标计算-以卖看跌期权为例.md`：详细描述了三层筛选漏斗和三层监控体系的设计

## Goals / Non-Goals

### Goals
- 实现可配置的三层筛选漏斗，输出符合条件的期权合约及其评分
- 实现三层持仓监控体系，输出风险/机会信号
- 实现飞书 Webhook 推送，支持富文本卡片格式
- 提供命令行工具，支持手动触发筛选和监控
- 所有配置可通过 YAML/JSON 文件管理

### Non-Goals
- 不实现自动化交易执行（仅信号推送）
- 不实现策略回测（Phase 2）
- 不实现 Web UI 界面（Phase 2）
- 不实现交易记录和绩效分析（Phase 2）

## Decisions

### 1. 业务层目录结构

```
src/business/
├── __init__.py
├── screening/                    # 开仓筛选系统
│   ├── __init__.py
│   ├── filters/                  # 三层筛选器
│   │   ├── market_filter.py      # 市场环境过滤
│   │   ├── underlying_filter.py  # 标的过滤
│   │   └── contract_filter.py    # 合约过滤
│   ├── pipeline.py               # 筛选管道（组合三层）
│   └── models.py                 # 筛选结果数据模型
├── monitoring/                   # 持仓监控系统
│   ├── __init__.py
│   ├── monitors/                 # 三层监控器
│   │   ├── portfolio_monitor.py  # 组合级监控
│   │   ├── position_monitor.py   # 持仓级监控
│   │   └── capital_monitor.py    # 资金级监控
│   ├── alerts.py                 # 预警生成
│   └── models.py                 # 监控结果数据模型
├── notification/                 # 信号推送系统
│   ├── __init__.py
│   ├── channels/                 # 推送渠道
│   │   ├── base.py               # 基础接口
│   │   └── feishu.py             # 飞书 Webhook
│   ├── formatters/               # 消息格式化
│   │   ├── screening_card.py     # 筛选结果卡片
│   │   └── alert_card.py         # 预警信号卡片
│   └── dispatcher.py             # 推送调度器
└── config/                       # 配置管理
    ├── __init__.py
    ├── screening_config.py       # 筛选参数配置
    └── monitoring_config.py      # 监控参数配置
```

**理由**: 按职责分层，与已有的 `data/` 和 `engine/` 层保持一致的组织风格。

### 2. 配置驱动设计

所有阈值和参数通过 YAML 配置文件管理，支持：
- 全局默认配置 (`config/default.yaml`)
- 策略级配置覆盖 (`config/short_put.yaml`, `config/covered_call.yaml`)
- 运行时参数覆盖

```yaml
# config/screening/default.yaml
market_filter:
  # 美股市场指标
  us_market:
    vix_symbol: "^VIX"            # VIX 指数代码
    vix_range: [15, 28]           # VIX 适宜区间
    vix_percentile_range: [0.3, 0.8]  # VIX 历史百分位
    vix3m_symbol: "^VIX3M"        # VIX3M 代码（期限结构）
    term_structure_threshold: 0.9  # VIX/VIX3M 正向结构阈值
    trend_indices:
      - symbol: "SPY"             # 标普500 ETF
        weight: 0.6               # 权重
      - symbol: "QQQ"             # 纳斯达克100 ETF
        weight: 0.4               # 权重
    trend_required: "bullish_or_neutral"  # 要求牛市或中性
    pcr_symbol: "SPY"             # PCR 计算标的
    pcr_range: [0.8, 1.2]         # PCR 适宜区间

  # 港股市场指标
  hk_market:
    # 港股波动率：通过 2800.HK 期权链 IV 计算（无直接 VHSI API）
    volatility_source: "2800.HK"  # 用于计算市场 IV 的标的
    iv_calculation: "atm_weighted" # ATM 期权 IV 加权平均
    iv_range: [18, 32]            # IV 适宜区间
    iv_percentile_range: [0.3, 0.8]  # IV 历史百分位
    trend_indices:
      - symbol: "2800.HK"         # 盈富基金（恒生指数）
        weight: 0.5               # 权重
      - symbol: "3033.HK"         # 恒生科技 ETF
        weight: 0.5               # 权重
    trend_required: "bullish_or_neutral"  # 要求牛市或中性

underlying_filter:
  min_iv_rank: 50               # 最低 IV Rank
  max_iv_hv_ratio: 2.0          # IV/HV 上限
  min_sma_alignment: "neutral"  # MA 排列要求
  min_rsi: 30                   # RSI 下限（避免接飞刀）
  max_rsi: 70                   # RSI 上限

contract_filter:
  dte_range: [25, 45]           # DTE 范围
  delta_range: [-0.35, -0.15]   # Delta 范围（卖Put）
  min_sharpe_ratio: 1.0         # 最低夏普比率
  min_sas: 50                   # 最低策略吸引力分数
  max_prei: 75                  # 最高风险暴露指数
  max_kelly_fraction: 0.25     # Kelly 仓位上限系数
```

**理由**: 配置驱动便于调参优化和策略定制，无需修改代码。

### 3. 筛选管道设计

采用管道模式（Pipeline），三层筛选器串联执行：

```python
# 伪代码示意
class ScreeningPipeline:
    def __init__(self, config: ScreeningConfig):
        self.market_filter = MarketFilter(config.market_filter)
        self.underlying_filter = UnderlyingFilter(config.underlying_filter)
        self.contract_filter = ContractFilter(config.contract_filter)

    def run(self, watchlist: List[str]) -> ScreeningResult:
        # Step 1: 市场环境检查（全局，不筛选标的）
        market_status = self.market_filter.evaluate()
        if not market_status.is_favorable:
            return ScreeningResult(
                passed=False,
                reason=market_status.unfavorable_reason,
                opportunities=[]
            )

        # Step 2: 标的筛选
        qualified_underlyings = []
        for symbol in watchlist:
            result = self.underlying_filter.evaluate(symbol)
            if result.passed:
                qualified_underlyings.append((symbol, result))

        # Step 3: 合约筛选
        opportunities = []
        for symbol, underlying_result in qualified_underlyings:
            contracts = self.contract_filter.evaluate(symbol)
            opportunities.extend(contracts)

        # 排序：按 SAS 降序
        opportunities.sort(key=lambda x: x.sas, reverse=True)

        return ScreeningResult(
            passed=True,
            market_status=market_status,
            opportunities=opportunities[:10]  # 取 Top 10
        )
```

**理由**: 管道模式清晰表达筛选流程，每层职责单一，便于单独测试和替换。

### 4. 监控状态机设计

持仓监控采用状态机模式，每个指标有三种状态：

```
正常 (Green) → 关注 (Yellow) → 风险 (Red)
```

状态转换基于阈值配置，支持迟滞（hysteresis）防止频繁切换：

```yaml
# config/monitoring/thresholds.yaml
portfolio_level:
  beta_weighted_delta:
    green: [-100, 100]
    yellow: [-200, 200]
    red_above: 300
    red_below: -300
    hysteresis: 20              # 迟滞值，防止状态抖动

position_level:
  prei:
    green: [0, 40]
    yellow: [40, 75]
    red_above: 75
```

**理由**: 状态机模式便于追踪状态变化，迟滞机制减少误报。

### 5. 飞书推送卡片设计

使用飞书消息卡片（Interactive Card）格式，支持结构化展示：

```json
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {"tag": "plain_text", "content": "📈 Short Put 开仓机会"},
      "template": "green"
    },
    "elements": [
      {
        "tag": "div",
        "fields": [
          {"is_short": true, "text": {"tag": "lark_md", "content": "**标的**: AAPL"}},
          {"is_short": true, "text": {"tag": "lark_md", "content": "**行权价**: $180"}}
        ]
      },
      {
        "tag": "div",
        "fields": [
          {"is_short": true, "text": {"tag": "lark_md", "content": "**DTE**: 35天"}},
          {"is_short": true, "text": {"tag": "lark_md", "content": "**Delta**: -0.25"}}
        ]
      },
      {
        "tag": "hr"
      },
      {
        "tag": "div",
        "text": {"tag": "lark_md", "content": "**SAS**: 78 | **Sharpe**: 1.8 | **Kelly**: 12%"}
      }
    ]
  }
}
```

**理由**: 飞书卡片美观易读，在移动端体验好；结构化字段便于快速浏览。

### 6. 命令行接口设计

提供 CLI 工具，便于手动触发和调试：

```bash
# 运行开仓筛选
python -m src.business.cli screen --watchlist AAPL,MSFT,NVDA --strategy short_put

# 运行持仓监控
python -m src.business.cli monitor --positions positions.json

# 测试飞书推送
python -m src.business.cli notify --test

# 完整流程（筛选 + 推送）
python -m src.business.cli screen --watchlist AAPL,MSFT --push
```

**理由**: CLI 工具便于调试、定时任务调度和集成测试。

## Risks / Trade-offs

### Risk 1: 数据源延迟
- **问题**: Yahoo Finance 数据有延迟（15-20分钟），实时性不足
- **缓解**:
  - 筛选系统使用 Yahoo 作为主数据源（延迟可接受）
  - 监控系统支持切换到 IBKR/Futu 实时数据源
  - 配置中明确标注数据源和延迟

### Risk 2: 飞书 API 限流
- **问题**: 飞书 Webhook 有频率限制
- **缓解**:
  - 实现消息聚合：将同一时段多个信号合并为一条消息
  - 实现防抖机制：相同信号在 N 分钟内不重复推送
  - 配置最小推送间隔

### Risk 3: 配置复杂度
- **问题**: 大量可配置参数可能让用户困惑
- **缓解**:
  - 提供预设配置（conservative/moderate/aggressive）
  - 使用合理的默认值
  - 配置文件添加详细注释

## Migration Plan

本阶段为新增功能，无迁移需求。

## Open Questions

1. **持仓数据来源**: 用户持仓信息从哪里获取？
   - 选项 A: 手动录入 JSON 文件
   - 选项 B: 从券商 API 获取（需要交易权限）
   - **建议**: Phase 1 采用选项 A，Phase 2 考虑选项 B

2. **定时任务调度**: 如何触发定时筛选/监控？
   - 选项 A: 系统 cron
   - 选项 B: Python APScheduler
   - **建议**: Phase 1 使用系统 cron，简单可靠

3. **多策略支持**: 是否需要同时支持多种策略的筛选？
   - **建议**: Phase 1 支持 Short Put 和 Covered Call 两种策略，配置独立
