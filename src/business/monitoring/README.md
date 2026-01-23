# 期权监控系统用户手册

本文档介绍期权量化交易系统的监控体系，包括各级别指标、阈值设定、预警机制和建议操作。

## 目录

- [概述](#概述)
- [资本级监控 (Capital Level)](#资本级监控-capital-level)
- [组合级监控 (Portfolio Level)](#组合级监控-portfolio-level)
- [持仓级监控 (Position Level)](#持仓级监控-position-level)
- [使用方法](#使用方法)

---

## 概述

监控系统采用 **三级架构**：

| 级别 | 关注点 | 核心问题 |
|------|--------|----------|
| **Capital** | 账户生存 | 会不会爆仓？流动性够吗？ |
| **Portfolio** | 整体风险 | Greeks 敞口是否均衡？ |
| **Position** | 单一持仓 | 这笔交易还值得持有吗？ |

### 预警颜色

| 颜色 | 含义 | 行动 |
|------|------|------|
| 🟢 绿色 | 正常 | 无需操作 |
| 🟡 黄色 | 关注 | 准备调整 |
| 🔴 红色 | 风险 | 立即行动 |

---

## 资本级监控 (Capital Level)

资本级监控关注 **账户生存** 问题，是风控的第一道防线。

### 核心风控四大支柱

| 指标 | 物理意义 | 🟢 绿色 | 🟡 黄色 | 🔴 红色 | 红色时操作 |
|------|----------|---------|---------|---------|------------|
| **Margin Utilization** | 距离追保的距离 | < 40% | 40%~70% | > 70% | 强制去杠杆 |
| **Cash Ratio** | 流动性缓冲 | > 30% | 10%~30% | < 10% | 停止开仓 |
| **Gross Leverage** | 总敞口控制 | < 2.0x | 2.0x~4.0x | > 4.0x | 缩减规模 |
| **Stress Test Loss** | 尾部风险 | < 10% | 10%~20% | > 20% | 切断尾部 |

### 详细说明

#### 1. Margin Utilization（保证金使用率）

```
公式: Current Maintenance Margin / NLV
```

**物理意义**: 账户距离被券商强平的距离。这是最硬的生存底线。

**红色时操作**:
- 按"保证金/Theta"效率从低到高排序
- 平掉效率最低或亏损最大的头寸
- 直至回到黄色区间（< 70%）

#### 2. Cash Ratio（现金留存率）

```
公式: Net Cash Balance / NLV
```

**物理意义**: 应对期权被指派(Assignment)、移仓亏损或紧急对冲的"干火药"。

**红色时操作**:
- 禁止开设任何消耗现金的新仓位
- 平掉部分盈利的 Long 头寸或股票
- 补充现金储备至 > 10%

#### 3. Gross Leverage（总名义杠杆）

```
公式: (Σ|Stock Value| + Σ|Option Notional|) / NLV
其中: Option Notional = Strike × Multiplier × |Qty|
```

**物理意义**: 衡量总资产规模。期权按名义本金计算，防止"赚小钱担大风险"。

**红色时操作**:
- 账户"虚胖"，抗风险能力差
- 按比例缩减所有策略的仓位规模
- 降低整体风险暴露至 < 4.0x

#### 4. Stress Test Loss（压力测试亏损）

```
公式: (Current_NLV - Stressed_NLV) / Current_NLV
场景: Spot -15% 且 IV +40%
```

**物理意义**: 预测在黑天鹅事件下的净值回撤。

**红色时操作**:
- 买入深虚值 Put (或 VIX Call) 进行尾部保护
- 平掉 Short Gamma 最大的头寸（通常是临期平值期权）

### 为什么是这四个指标？

1. **Margin Utilization (防爆仓)**: 这是**现在**会不会死
2. **Cash Ratio (防卡死)**: 这是**操作**灵不灵活
3. **Gross Leverage (防虚胖)**: 这是**规模**控没控制住
4. **Stress Test Loss (防未来)**: 这是**未来**会不会死

---

## 组合级监控 (Portfolio Level)

组合级监控关注 **整体 Greeks 敞口** 是否均衡。

### NLV 归一化百分比指标

| 指标 | 物理意义 | 🟢 绿色 | 🟡 黄色 | 🔴 红色 | 红色时操作 |
|------|----------|---------|---------|---------|------------|
| **BWD%** | 方向性杠杆 | ±20% | ±20%~50% | >50% 或 <-50% | Delta 对冲 |
| **Gamma%** | 凸性风险 | > -0.1% | -0.1%~-0.3% | < -0.5% | 买入保护性 Put |
| **Vega%** | 波动率风险 | ±0.3% | ±0.3%~0.6% | < -0.5% | 买入 VIX Call |
| **Theta%** | 日时间衰减率 | 0.05%~0.15% | 0.15%~0.25% | >0.30% 或 <0% | 平仓部分 Short |
| **IV/HV** | 持仓定价质量 | >1.0 | 0.8~1.2 | <0.8 | 停止做空 |

### 其他组合级指标

| 指标 | 物理意义 | 🟢 绿色 | 🟡 黄色 | 🔴 红色 | 红色时操作 |
|------|----------|---------|---------|---------|------------|
| **TGR** | Theta/Gamma 效率 | ≥1.5 | 1.0~1.5 | <1.0 | 调整持仓结构 |
| **HHI** | 集中度指数 | <0.25 | 0.25~0.5 | >0.5 | 分散持仓 |

---

## 持仓级监控 (Position Level)

持仓级监控关注 **单一持仓** 的健康状况和交易机会。

### 核心指标（9个）

| 指标 | 物理意义 | 🟢 绿色 | 🟡 黄色 | 🔴 红色 | 红色时操作 |
|------|----------|---------|---------|---------|------------|
| **OTM%** | 虚值百分比 | ≥10% | 5%~10% | <5% | 立即 Roll |
| **\|Delta\|** | 方向性风险 | ≤0.20 | 0.20~0.40 | >0.50 | 对冲或平仓 |
| **DTE** | 到期天数 | ≥14天 | 7~14天 | <7天 | 强制平仓/展期 |
| **P&L%** | 持仓盈亏 | ≥50% | -100%~50% | <-100% | 无条件止损 |
| **Gamma Risk%** | Gamma/Margin | ≤0.5% | 0.5%~1% | >1% | 减仓 |
| **TGR** | Theta/Gamma 效率 | ≥1.5 | 1.0~1.5 | <1.0 | 平仓换合约 |
| **IV/HV** | 期权定价质量 | ≥1.2 | 0.8~1.2 | <0.8 | 提前止盈 |
| **Expected ROC** | 预期资本回报 | ≥10% | 0%~10% | <0% | 立即平仓 |
| **Win Prob** | 胜率 | ≥70% | 55%~70% | <55% | 考虑平仓 |

### 关键指标说明

#### OTM%（虚值百分比）

```
Put: (Spot - Strike) / Spot
Call: (Strike - Spot) / Spot
```

**红色时操作**: 立即 Roll 到下个月或更远行权价，或直接平仓。

#### DTE（到期天数）

**红色时操作**: 强制平仓或展期，**绝不持有 Short Gamma 进入最后一周**。

#### TGR（Theta/Gamma 效率）

```
TGR = |Theta| / (|Gamma| × S² × σ_daily) × 100
其中: σ_daily = IV / sqrt(252)
```

**物理意义**: 标准化的 Theta/Gamma 比率，衡量时间衰减收益与波动风险的比值。
- TGR ≥ 1.5: 时间衰减效率高，头寸质量好
- TGR < 1.0: 时间衰减效率不足，需要调整

---

## 使用方法

### 命令行监控

```bash
# 实时监控（real 账户）
python src/business/cli/main.py monitor --account-type real

# 纸交易监控（paper 账户）
python src/business/cli/main.py monitor --account-type paper

# 启用详细日志
python src/business/cli/main.py monitor --account-type real -v
```

### 仪表板模式

```bash
# 启动 Dashboard（实时刷新）
python src/business/cli/main.py dashboard --account-type real

# 指定刷新间隔（秒）
python src/business/cli/main.py dashboard --account-type real --refresh 30
```

### 输出示例

```
=== Capital Level ===
  保证金使用率正常: 35.2%           🟢
  现金留存率充足: 42.1%             🟢
  总名义杠杆正常: 1.8x              🟢
  压力测试亏损可控: 8.5%            🟢

=== Position Alerts ===
  AAPL250117P180: DTE < 7 天: 5 天   🔴 → 强制平仓或展期
  GOOG250117C345: |Delta| 偏大: 0.35 🟡 → 关注方向性风险
```

---

## 配置自定义

阈值配置位于 `config/monitoring/thresholds.yaml`，可根据个人风险偏好调整：

```yaml
capital_level:
  margin_utilization:
    green: [0, 0.35]      # 更保守
    yellow: [0.35, 0.60]
    red_above: 0.60

position_level:
  dte:
    green: [21, .inf]     # 要求更长 DTE
    yellow: [14, 21]
    red_below: 14
```

---

## 数据流水线 (Data Pipeline)

监控系统的数据流如下：

### 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Data Providers                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐          │
│   │    IBKR     │         │    Futu     │         │   Yahoo     │          │
│   │  Provider   │         │  Provider   │         │  Finance    │          │
│   └──────┬──────┘         └──────┬──────┘         └──────┬──────┘          │
│          │                       │                       │                  │
│          │  Positions, Greeks    │  Positions, Greeks    │  Exchange Rates  │
│          │  Market Data          │  Market Data          │                  │
│          └───────────────┬───────┴───────────────────────┘                  │
│                          │                                                  │
│                          ▼                                                  │
│              ┌───────────────────────┐                                      │
│              │   AccountAggregator   │                                      │
│              │  - 合并多券商持仓     │                                      │
│              │  - 货币转换 (HKD→USD) │                                      │
│              │  - 补充 Greeks 数据   │                                      │
│              └───────────┬───────────┘                                      │
│                          │                                                  │
│                          ▼                                                  │
│              ┌───────────────────────┐                                      │
│              │ ConsolidatedPortfolio │                                      │
│              │  - positions[]        │                                      │
│              │  - cash_balances[]    │                                      │
│              │  - total_value_usd    │                                      │
│              │  - exchange_rates{}   │                                      │
│              └───────────┬───────────┘                                      │
│                          │                                                  │
└──────────────────────────┼──────────────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────────────┐
│                          │              Engine Layer                         │
├──────────────────────────┼──────────────────────────────────────────────────┤
│                          │                                                  │
│          ┌───────────────┴───────────────┐                                  │
│          │                               │                                  │
│          ▼                               ▼                                  │
│  ┌───────────────────┐         ┌─────────────────────┐                     │
│  │ calc_capital_     │         │ create_strategies_  │                     │
│  │ metrics()         │         │ from_position()     │                     │
│  │                   │         │                     │                     │
│  │ - margin_util     │         │ - ShortPutStrategy  │                     │
│  │ - cash_ratio      │         │ - CoveredCallStrat  │                     │
│  │ - gross_leverage  │         │ - ShortStrangleStr  │                     │
│  │ - stress_test     │         │                     │                     │
│  └─────────┬─────────┘         └──────────┬──────────┘                     │
│            │                              │                                  │
│            │  CapitalMetrics              │  StrategyMetrics                │
│            │                              │  (TGR, ROC, Expected ROC...)    │
│            └──────────────┬───────────────┘                                  │
│                           │                                                  │
└───────────────────────────┼──────────────────────────────────────────────────┘
                            │
┌───────────────────────────┼──────────────────────────────────────────────────┐
│                           │             Business Layer                        │
├───────────────────────────┼──────────────────────────────────────────────────┤
│                           │                                                  │
│                           ▼                                                  │
│               ┌───────────────────────┐                                      │
│               │  MonitoringDataBridge │                                      │
│               │  - 转换 AccountPos    │                                      │
│               │    → PositionData     │                                      │
│               │  - 计算派生指标       │                                      │
│               │  - 丰富技术/基本面数据│                                      │
│               └───────────┬───────────┘                                      │
│                           │                                                  │
│           ┌───────────────┴───────────────┐                                  │
│           │                               │                                  │
│           ▼                               ▼                                  │
│   ┌───────────────────┐         ┌─────────────────────┐                     │
│   │  CapitalMonitor   │         │   PositionMonitor   │                     │
│   │  - 检查 Capital   │         │   - 检查每个持仓    │                     │
│   │    阈值           │         │     阈值            │                     │
│   │  - 生成 Alerts    │         │   - 生成 Alerts     │                     │
│   └─────────┬─────────┘         └──────────┬──────────┘                     │
│             │                              │                                  │
│             │  MonitorResult               │  MonitorResult                  │
│             └──────────────┬───────────────┘                                  │
│                            │                                                  │
│                            ▼                                                  │
│                ┌───────────────────────┐                                     │
│                │  ThresholdChecker     │                                     │
│                │  - 根据配置检查阈值  │                                     │
│                │  - 返回 AlertLevel   │                                     │
│                └───────────┬───────────┘                                     │
│                            │                                                  │
│                            ▼                                                  │
│                ┌───────────────────────┐                                     │
│                │     CLI / Dashboard   │                                     │
│                │  - monitor 命令       │                                     │
│                │  - dashboard 命令     │                                     │
│                │  - 渲染输出           │                                     │
│                └───────────────────────┘                                     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 数据流详解

#### 1. 数据采集层 (Data Providers)

| 组件 | 职责 | 输出 |
|------|------|------|
| `IBKRProvider` | 连接盈透证券获取持仓、Greeks、市场数据 | `AccountPosition[]` |
| `FutuProvider` | 连接富途证券获取 HK 期权持仓 | `AccountPosition[]` |
| `CurrencyConverter` | 获取实时汇率（Yahoo Finance） | `exchange_rates{}` |

#### 2. 数据聚合层 (AccountAggregator)

```python
# 核心流程
portfolio = aggregator.get_consolidated_portfolio(account_type, base_currency="USD")

# 内部步骤:
# 1. 从 IBKR/Futu 获取原始持仓
# 2. 为 Futu HK 期权补充 Greeks (调用 IBKR API)
# 3. 货币转换 (HKD → USD)
# 4. 合并为 ConsolidatedPortfolio
```

#### 3. 计算引擎层 (Engine)

| 模块 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `calc_capital_metrics()` | `ConsolidatedPortfolio` | `CapitalMetrics` | 计算资本级风控指标 |
| `create_strategies_from_position()` | `AccountPosition` | `StrategyInstance[]` | 识别策略类型，计算策略指标 |

#### 4. 监控桥接层 (MonitoringDataBridge)

```python
# 转换流程
bridge = MonitoringDataBridge(data_provider, ibkr_provider, futu_provider)
position_list = bridge.convert_positions(portfolio)

# 每个 AccountPosition 转换为 PositionData:
# - 计算 OTM%, DTE, P&L%
# - 调用 engine 层获取策略指标 (TGR, ROC, Expected ROC, Win Prob)
# - 丰富技术面/基本面数据
```

#### 5. 监控检查层 (Monitors)

| 监控器 | 检查内容 | 输出 |
|--------|----------|------|
| `CapitalMonitor` | 4 大资本指标阈值 | `MonitorResult` with `Alert[]` |
| `PositionMonitor` | 9 个持仓指标阈值 | `MonitorResult` with `Alert[]` |

### 关键文件

| 文件 | 层级 | 说明 |
|------|------|------|
| `src/data/providers/ibkr_provider.py` | Data | IBKR 数据接口 |
| `src/data/providers/futu_provider.py` | Data | Futu 数据接口 |
| `src/data/providers/account_aggregator.py` | Data | 多券商数据聚合 |
| `src/engine/account/metrics.py` | Engine | 资本指标计算 |
| `src/engine/strategy/factory.py` | Engine | 策略识别与指标计算 |
| `src/business/monitoring/data_bridge.py` | Business | 数据转换桥接 |
| `src/business/monitoring/monitors/` | Business | 阈值检查与预警 |
| `src/business/config/monitoring_config.py` | Business | 阈值配置 |
| `src/business/cli/commands/monitor.py` | CLI | 监控命令入口 |
| `src/business/cli/commands/dashboard.py` | CLI | 仪表板命令入口 |

---

## 常见问题

### Q: 为什么压力测试显示 0%？

A: 可能是 HK 期权的 underlying_price 获取失败。检查：
1. 市场数据订阅是否有效
2. 是否在交易时间内
3. 查看日志中的 `undPrice not in Greeks` 警告

### Q: 为什么某些 HK 期权的 underlying_price 与其他不一致？

A: 可能是货币单位不一致（HKD vs USD）。系统已自动将 HKD 转换为 USD（rate ≈ 0.128）。

### Q: P&L% 止损线为什么是 -100%？

A: P&L% = -100% 意味着亏损金额等于收取的原始权利金。这是卖方策略的合理止损点：
- 超过此点继续持有，风险/收益比急剧恶化
- 触发止损时应无条件平仓，不要抗单

---

## 更新日志

### 2026-01-23
- Position 级指标从 12 个精简为 9 个（移除 PREI、SAS、ROC）
- P&L% 止损线从 0% 调整为 -100%（亏损超过原始权利金才触发）
- TGR 阈值更新为标准化公式（绿色 ≥1.5，红色 <1.0）
- 新增 Win Probability 指标说明
- 新增策略差异化阈值支持（Short Put / Covered Call / Short Strangle）

### 2026-01-08
- 重构资本级监控，引入四大核心风控指标
- 修复 HK 期权 underlying_price 获取问题
- 添加 Futu fallback 和 HKD→USD 货币转换
- 清理 deprecated 代码（移除旧阈值字段）
- 添加数据流水线文档
