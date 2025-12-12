# Project Context

## Purpose

实盘可用的期权量化交易系统，专注于卖方策略（做时间的朋友）。

**核心目标：**
- 自动化期权卖方策略的筛选、监控和信号推送
- 支持策略回测和实盘追踪
- 提供完整的绩效复盘分析

## Tech Stack

### 核心框架
- **Python 3.11** - 主开发语言
- **QuantConnect LEAN** - 策略框架（已安装于 `/opt/anaconda3/envs/quant-env/lib/python3.11/site-packages/QuantConnect`）
  - 提供：算法结构、数据处理、期权Greeks、回测引擎
  - 文档：https://www.quantconnect.com/docs/v2/writing-algorithms
  - 源码：https://github.com/QuantConnect/Lean（C#实现，兼容Python）

### 数据源
- **富途 OpenAPI** - 实时行情数据
  - 支持市场：港股、美股、A股、新加坡、日本、澳洲
  - 数据类型：实时报价、K线、逐笔、摆盘、期权、期货
  - 架构：OpenD（本地网关）+ API SDK
  - 文档：https://openapi.futunn.com/futu-api-doc/intro/intro.html

### 环境
- **Conda 环境**: `quant-env`
- **激活命令**: `conda activate quant-env`

## Project Conventions

### Code Style
- 遵循 PEP 8 规范
- 类名：PascalCase（如 `ShortPutStrategy`）
- 函数/变量：snake_case（如 `calculate_greeks`）
- 常量：UPPER_SNAKE_CASE（如 `MAX_POSITION_SIZE`）
- 文档字符串：Google 风格
- 类型注解：所有公共函数必须有类型注解

### Architecture Patterns
- **四层架构**：
  1. **数据层 (Data Layer)** - 行情获取、数据存储、数据清洗
  2. **计算引擎层 (Engine Layer)** - Greeks计算、信号生成、风险计算
  3. **业务模块层 (Business Layer)** - 策略实现、持仓管理、回测逻辑
  4. **展示层 (Presentation Layer)** - Web界面、信号推送、报表展示

- **设计原则**：
  - 模块间通过接口解耦
  - 策略可插拔，便于扩展
  - 配置与代码分离

### Testing Strategy
- 单元测试：pytest
- 策略回测：使用 QuantConnect 回测引擎
- 集成测试：模拟交易环境验证

### Git Workflow
- 主分支：`main`
- 功能分支：`feature/<feature-name>`
- 修复分支：`fix/<bug-description>`
- Commit 格式：`<type>: <description>`
  - type: feat, fix, docs, refactor, test, chore

## Domain Context

### 交易策略

| 策略 | 描述 | 风险特征 |
|------|------|----------|
| **Short Put** | 卖出看跌期权，收取权利金 | 下行风险有限（到0），适合看涨或震荡市 |
| **Covered Call** | 持有正股+卖出看涨期权 | 上行收益有限，但有权利金保护 |
| **轮动策略** | Short Put + Covered Call 组合轮动 | 根据市场状态动态切换 |

### 核心模块

1. **开仓前筛选** - 根据Greeks、流动性、价格等筛选合适的期权合约
2. **持仓监控** - 实时监控持仓盈亏、Greeks变化、风险指标
3. **交易信号推送** - 开仓/平仓/调仓信号通知
4. **策略回测** - 历史数据回测，验证策略有效性
5. **实盘追踪** - 记录实际交易，对比预期
6. **绩效复盘** - 收益分析、风险分析、策略优化建议

### 期权Greeks

| Greek | 含义 | 用途 |
|-------|------|------|
| **Delta (Δ)** | 标的价格变化对期权价格的影响 | 方向性敞口管理 |
| **Gamma (Γ)** | Delta的变化率 | Delta对冲频率 |
| **Theta (Θ)** | 时间衰减 | 卖方策略核心收益来源 |
| **Vega (ν)** | 波动率敏感度 | 波动率风险管理 |
| **Rho (ρ)** | 利率敏感度 | 长期期权考量 |

### 关键概念
- **行权价 (Strike)** - 期权合约的约定价格
- **到期日 (Expiration)** - 期权有效期截止日
- **内在价值 (Intrinsic Value)** - max(0, S-K) for call, max(0, K-S) for put
- **时间价值 (Time Value)** - 期权价格 - 内在价值
- **隐含波动率 (IV)** - 市场对未来波动率的预期

## Important Constraints

### 风险约束
- 单一标的持仓不超过总资金的 X%（可配置）
- 总Delta敞口控制在合理范围
- 设置止损线和预警线

### 技术约束
- 富途 OpenAPI 需要本地运行 OpenD 网关
- QuantConnect LEAN 本地运行需要配置
- 实盘交易需要券商账户授权

### 合规约束
- 仅限个人投资，非商业用途
- 遵守相关市场交易规则

## External Dependencies

### APIs
| 服务 | 用途 | 文档 |
|------|------|------|
| 富途 OpenAPI | 实时行情、交易执行 | https://openapi.futunn.com/futu-api-doc/ |
| QuantConnect | 策略框架、回测引擎 | https://www.quantconnect.com/docs/v2/ |

### Python 包（预期）
```
futu-api          # 富途API SDK
pandas            # 数据处理
numpy             # 数值计算
scipy             # 统计分析
matplotlib        # 可视化
streamlit/dash    # Web界面（待定）
```

## File Structure (Planned)

```
option_quant_trade_system/
├── src/
│   ├── data/           # 数据层
│   │   ├── fetcher/    # 行情获取
│   │   ├── storage/    # 数据存储
│   │   └── cleaner/    # 数据清洗
│   ├── engine/         # 计算引擎层
│   │   ├── greeks/     # Greeks计算
│   │   ├── signals/    # 信号生成
│   │   └── risk/       # 风险计算
│   ├── business/       # 业务模块层
│   │   ├── strategies/ # 交易策略
│   │   ├── portfolio/  # 持仓管理
│   │   └── backtest/   # 回测模块
│   └── presentation/   # 展示层
│       ├── web/        # Web界面
│       ├── notify/     # 信号推送
│       └── reports/    # 报表生成
├── tests/              # 测试代码
├── config/             # 配置文件
├── data/               # 数据存储
└── docs/               # 文档
```
