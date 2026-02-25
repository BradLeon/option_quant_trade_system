r"""
Monitoring Configuration - 监控配置管理

加载和管理持仓监控系统的配置参数。

所有阈值统一使用 ThresholdRange 格式，支持：
- 配置化消息模板（{value}, {threshold} 占位符）
- 配置化建议操作
- 防抖机制（hysteresis）

## Portfolio 级阈值配置参考

### 绝对值指标

| 指标                | 绿色（正常）  | 黄色（关注）   | 红色（风险）      | 说明                  | RED 建议操作                          |
|---------------------|---------------|----------------|-------------------|-----------------------|---------------------------------------|
| Beta Weighted Delta | (-100, 100)   | (-200, 200)    | >300 或 <-300     | SPY 等效股数          | 减少多/空头 Delta 暴露或对冲          |
| Portfolio Theta     | ≥0            | (-50, 0)       | <-100             | 日 theta 收入（美元） | 减少买方头寸或增加卖方头寸            |
| Portfolio Vega      | (-500, 500)   | (-1000, 1000)  | >1500 或 <-1500   | IV 变化 1% 的损益     | 减少 Vega 暴露 / Vega 空头过大        |
| Portfolio Gamma     | (-30, 0)      | (-50, -30)     | <-50              | Gamma 空头风险        | Gamma 空头风险高，大幅波动时亏损加速  |
| TGR                 | ≥1.5          | (1.0, 1.5)     | <1.0              | 标准化 Theta/Gamma 比 | 时间衰减效率不足，考虑调整持仓        |
| HHI                 | <0.25         | (0.25, 0.5)    | >0.5              | 集中度指数            | 分散持仓，降低单一标的风险            |

### NLV 归一化百分比指标

| 指标           | 绿色（正常）    | 黄色（关注）      | 红色（风险）       | 说明                  | RED 建议操作                              |
|----------------|-----------------|-------------------|--------------------|-----------------------|-------------------------------------------|
| BWD%           | ±20%            | ±20%~50%          | >50% 或 <-50%      | 方向性杠杆            | Delta 对冲：交易 SPY/QQQ 期货或 ETF       |
| Gamma%         | > -0.1%         | -0.1% ~ -0.3%     | < -0.5%            | 凸性/崩盘风险         | 买入近月深虚值 Put 或平掉临期 ATM 头寸    |
| Vega%          | ±0.3%           | ±0.3%~0.6%        | < -0.5%            | 波动率风险（做空）    | 买入 VIX Call 或 SPY Put                  |
| Theta%         | 0.05%~0.15%     | 0.15%~0.25%       | >0.30% 或 <0%      | 日时间衰减率          | 平仓部分 Short 头寸（过高意味 Gamma 过大）|
| IV/HV Quality  | >1.0            | 0.8~1.2           | <0.8               | 持仓定价质量          | 停止做空，仅允许 Debit 策略               |

## Position 级阈值配置参考（9个指标）

| 指标            | 绿色（正常）  | 黄色（关注）  | 红色（风险）  | 说明                    | RED 建议操作                              |
|-----------------|---------------|---------------|---------------|-------------------------|-------------------------------------------|
| OTM%            | ≥10%          | 0%~10%        | <0%(仅ITM)    | 虚值百分比（统一公式）  | 仅 ITM 时强制平仓，近 ATM 由 TGR 判断       |
| |Delta|         | ≤0.20         | 0.20~0.40     | >0.50         | 方向性风险（绝对值）    | 必须行动：对冲正股或平仓                  |
| DTE             | ≥14 天        | 0~14 天       | <0 天(禁用)    | 到期天数                | 不因 DTE 强制平仓，允许合约自然到期       |
| P&L%            | ≥50%          | -200%~50%     | <-200%        | 持仓盈亏                | 极端兆底止损（TGR 应先触发）             |
| Gamma Risk%     | ≤0.5%         | 0.5%~1%       | >1%           | Gamma/Margin 百分比     | 减仓或平仓，降低 Gamma 风险敞口           |
| TGR             | ≥1.5          | 0.5~1.5       | <0.5          | 标准化 Theta/Gamma 比   | **主动平仓**，Gamma 风险超过 Theta 收益     |
| IV/HV           | ≥1.2          | 0.8~1.2       | <0.8          | 期权定价质量            | 如盈利可提前止盈，避免继续卖出            |
| Expected ROC    | ≥10%          | 0%~10%        | <0%           | 预期资本回报率          | 立即平仓，策略已失效                      |
| Win Probability | ≥70%          | 55%~70%       | <55%          | 理论胜率                | 考虑平仓，寻找更高效策略                  |

## Capital 级阈值配置参考

| 维度 | 指标 | 绿色 (安全) | 黄色 (警戒) | 红色 (高危) | 说明 (意义与公式) | 红色时操作 (Action) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **生存** | **Margin Utilization**<br>(保证金使用率) | **< 40%** | **40% ~ 70%** | **> 70%** | **意义**：账户距离被券商强平的距离。这是最硬的生存底线。<br>**公式**：`Current Maint Margin / Net Liquidation Value (NLV)` | **强制去杠杆 (De-leverage)**：<br>立即按“保证金/Theta”效率从低到高排序，平掉效率最低或亏损最大的头寸，直至回到黄色区间。 |
| **流动性** | **Cash Ratio**<br>(现金留存率) | **> 30%** | **10% ~ 30%** | **< 10%** | **意义**：应对期权被指派(Assignment)、移仓亏损或紧急对冲的“干火药”。<br>**公式**：`Net Cash Balance / NLV` | **停止开仓 & 变现**：<br>1. 禁止开设任何消耗现金的新仓位。<br>2. 平掉部分盈利的 Long 头寸或股票，补充现金储备。 |
| **敞口** | **Gross Leverage**<br>(总名义杠杆) | **< 2.0x** | **2.0x ~ 4.0x** | **> 4.0x** | **意义**：衡量总资产规模。期权按名义本金计算，防止“赚小钱担大风险”。<br>**公式**：`(Σ|Stock Value| + Σ|Option Notional|) / NLV`<br>*注：Option Notional = Strike × Multiplier × Qty* | **缩减规模 (Scale Down)**：<br>账户“虚胖”，抗风险能力差。<br>需按比例缩减所有策略的仓位规模，降低整体风险暴露。 |
| **稳健** | **Stress Test Loss**<br>(压力测试风险) | **< 10%** | **10% ~ 20%** | **> 20%** | **意义**：预测在黑天鹅事件下的净值回撤。防止平时赚小钱，一波回到解放前。<br>**公式**：`(Curr_NLV - Sim_NLV) / Curr_NLV`<br>*场景：假设 Spot -15% 且 IV +40%* | **切断尾部 (Cut Tails)**：<br>1. 买入深虚值 Put (VIX Call) 进行尾部保护。<br>2. 平掉 Short Gamma 最大的头寸（通常是临期平值期权）。 |



### 💡 深度解读：为什么这四个是“黄金组合”？

1.  **Margin Utilization (防爆仓)**：
    *   这是**现在**会不会死。如果超过 70%，哪怕市场只是正常波动一下，你都可能被强平。

2.  **Cash Ratio (防卡死)**：
    *   这是**操作**灵不灵活。如果没现金了，哪怕看到绝佳的补救机会（比如低位补仓或买保险），你也动弹不得。对于卖 Put 策略，现金是接货的底气。

3.  **Gross Leverage (防虚胖)**：
    *   这是**规模**控没控制住。很多交易员死于 margin 很低（因为卖深虚值），但名义杠杆高达 10 倍。一旦黑天鹅来临，虚值变实值，10 倍杠杆瞬间击穿账户。

4.  **Stress Test Loss (防未来)**：
    *   这是**未来**会不会死。前三个指标看的都是当前静态数据，只有压力测试是看“如果发生灾难会怎样”。如果压力测试显示会亏 50%，说明你的持仓结构在极端行情下极其脆弱（通常是因为由 Short Vega/Short Gamma 堆积）。

Gross Leverage (总名义杠杆)。

该指标衡量账户控制的总资产规模相对于净资产的倍数。对于期权，使用**行权价 (Strike)** 计算名义本金是风控中最保守且通用的做法（代表潜在的履约义务规模）。
意义： 如果你账户有 10 万，你卖了名义价值 100 万的 Put（哪怕保证金够），你的杠杆也是 10 倍。一旦出事，就是 10 倍速的毁灭。控制总杠杆就是控制总风险。


#### 核心公式
$$
\text{Gross Leverage} = \frac{\sum_{i=1}^{N_s} |V_{\text{stock}, i}| + \sum_{j=1}^{N_o} |V_{\text{option}, j}|}{\text{NLV}}
$$

#### 变量定义与计算细节

*   **$\text{NLV}$ (Net Liquidation Value):** 账户当前净清算价值。
*   **$V_{\text{stock}, i}$ (股票名义价值):**
    $$ V_{\text{stock}} = Q_s \times S $$
*   **$V_{\text{option}, j}$ (期权名义价值):**
    $$ V_{\text{option}} = Q_o \times M \times K $$

> **符号说明:**
> *   $|\dots|$: 取绝对值（无论做多还是做空，都会增加杠杆）。
> *   $Q_s$: 股票持仓数量。
> *   $Q_o$: 期权持仓张数。
> *   $S$: 标的当前股价 (Spot Price)。
> *   $K$: 期权行权价 (Strike Price)。
> *   $M$: 合约乘数 (Multiplier，如美股100，港股腾讯100)。




Stress Test Loss (压力测试)
背景： 对于 Options + Stocks 组合，最大的风险不是线性的（Delta），而是非线性的（Gamma + Vega）。
场景： 现在的 Margin 可能很低（绿色），但如果明天大盘跌 10%，波动率翻倍，你的 Margin 可能会瞬间膨胀 5 倍导致爆仓。

该指标通过**完全重估 (Full Revaluation)** 方法，计算在特定极端情境下账户净值的预计回撤比例。不要使用 Delta/Gamma 估算，必须代入定价模型重算价格。


算法：
#### 核心公式
$$
\text{Stress Test Loss \%} = \frac{\text{NLV}_{\text{current}} - \text{NLV}_{\text{stress}}}{\text{NLV}_{\text{current}}} \times 100\%
$$

#### 场景设定 (Scenario)
假设发生“股灾+恐慌”情境：
*   **股价暴跌:** $S_{\text{stress}} = S_{\text{current}} \times (1 - 15\%)$
*   **波动率飙升:** $\sigma_{\text{stress}} = \sigma_{\text{current}} \times (1 + 40\%)$
    *   *(注：也可以设定为绝对值增加，如 $\sigma + 0.15$)*

#### 净值重估公式 ($\text{NLV}_{\text{stress}}$)
$$
\text{NLV}_{\text{stress}} = \text{Cash} + \sum \text{Val}_{\text{stock}}(S_{\text{stress}}) + \sum \text{Val}_{\text{option}}(S_{\text{stress}}, \sigma_{\text{stress}}, T)
$$

其中：

1.  **股票重估价值:**
    $$ \text{Val}_{\text{stock}} = Q_s \times S_{\text{stress}} $$

2.  **期权重估价值 (基于 B-S 模型):**
    $$ \text{Val}_{\text{option}} = Q_o \times M \times \text{BS\_Price}(S_{\text{stress}}, K, T, r, \sigma_{\text{stress}}) $$
    *   对于 **Call**: $\text{BS\_Price}$ 使用 $S_{\text{stress}}$ 和 $\sigma_{\text{stress}}$ 计算看涨价格。
    *   对于 **Put**: $\text{BS\_Price}$ 使用 $S_{\text{stress}}$ 和 $\sigma_{\text{stress}}$ 计算看跌价格。

"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.business.config.config_mode import ConfigMode
from src.business.config.config_utils import merge_overrides
from src.engine.models.enums import StrategyType


@dataclass
class ThresholdRange:
    """阈值范围 - 支持配置化消息

    Attributes:
        green: 绿色（正常）范围
        yellow: 黄色（关注）范围
        red_above: 红色上限阈值
        red_below: 红色下限阈值
        hysteresis: 滞后值（防止频繁切换）
        alert_type: AlertType 枚举名（用于创建 Alert）
        red_above_message: 超上限消息模板（支持 {value}, {threshold}）
        red_below_message: 超下限消息模板
        yellow_message: 黄色预警消息模板
        green_message: 绿色正常消息模板
        red_above_action: 超上限建议操作
        red_below_action: 超下限建议操作
        yellow_action: 黄色预警建议操作
        green_action: 绿色正常建议操作
    """

    # 阈值定义
    green: tuple[float, float] | None = None
    yellow: tuple[float, float] | None = None
    red_above: float | None = None
    red_below: float | None = None
    hysteresis: float = 0.0
    enabled: bool = True  # 是否启用此指标检查（False=跳过）

    # 配置化消息
    alert_type: str = ""
    red_above_message: str = ""
    red_below_message: str = ""
    yellow_message: str = ""
    green_message: str = ""  # 绿色正常消息
    red_above_action: str = ""
    red_below_action: str = ""
    yellow_action: str = ""
    green_action: str = ""  # 绿色正常建议


@dataclass
class PortfolioThresholds:
    """组合级阈值 - 统一使用 ThresholdRange

    使用 NLV 归一化百分比指标，实现账户大小无关的风险评估。
    已移除旧的绝对值指标（beta_weighted_delta, portfolio_theta, portfolio_vega, portfolio_gamma）。
    """

    # === 比率指标（已经是归一化的）===

    portfolio_tgr: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(1.5, float("inf")),     # 标准化 TGR ≥ 1.5
            yellow=(1.0, 1.5),             # 1.0 ~ 1.5
            red_below=1.0,                 # TGR < 1.0
            hysteresis=0.1,
            alert_type="TGR_LOW",
            red_below_message="组合 TGR 过低: {value:.2f} < {threshold}，时间收益/波动风险比不足",
            yellow_message="组合 TGR 偏低: {value:.2f}",
            red_below_action="时间衰减效率不足，考虑调整持仓",
            yellow_action="关注时间衰减效率",
        )
    )

    concentration_hhi: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 0.25),
            yellow=(0.25, 0.5),
            red_above=0.5,
            hysteresis=0.05,
            alert_type="CONCENTRATION",
            red_above_message="持仓集中度过高 (HHI={value:.2f} > {threshold})",
            yellow_message="持仓集中度偏高 (HHI={value:.2f})",
            red_above_action="分散持仓，降低单一标的风险",
            yellow_action="关注集中度变化",
        )
    )

    # === 新增：NLV 归一化百分比阈值 ===
    # 这些阈值用于账户大小无关的风险评估

    beta_weighted_delta_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-0.20, 0.20),  # ±20%
            yellow=(-0.50, 0.50),  # ±20~50%
            red_above=0.50,
            red_below=-0.50,
            hysteresis=0.02,
            alert_type="DELTA_EXPOSURE",
            red_above_message="BWD/NLV 过高: {value:.1%} > {threshold:.0%}，方向性杠杆过大",
            red_below_message="BWD/NLV 过低: {value:.1%} < {threshold:.0%}，方向性杠杆过大",
            yellow_message="BWD/NLV 偏离中性: {value:.1%}",
            red_above_action="Delta 对冲：交易 SPY/QQQ 期货或 ETF 进行反向对冲，或平掉贡献 Delta 最大的单边头寸",
            red_below_action="Delta 对冲：交易 SPY/QQQ 期货或 ETF 进行反向对冲，或平掉贡献 Delta 最大的单边头寸",
            yellow_action="关注方向性敞口",
        )
    )

    gamma_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-0.001, float("inf")),  # > -0.1%
            yellow=(-0.003, -0.001),  # -0.1% ~ -0.3%
            red_below=-0.005,  # < -0.5%
            hysteresis=0.0005,
            alert_type="GAMMA_EXPOSURE",
            red_below_message="Gamma/NLV 空头过大: {value:.2%} < {threshold:.2%}，暴跌时 Delta 敞口恶化加速",
            yellow_message="Gamma/NLV 空头偏大: {value:.2%}",
            red_below_action="切断左尾：买入近月深虚值 Put 保护 Gamma，或平掉临期（DTE < 7）的 Short ATM 头寸",
            yellow_action="关注 Gamma 风险",
        )
    )

    vega_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(-0.003, 0.003),  # ±0.3%
            yellow=(-0.006, 0.006),  # ±0.3~0.6%
            red_below=-0.005,  # < -0.5% (做空方向)
            # 注意：只有做空方向（负值）才触发红色预警
            # 做多方向（正值）通常比较宽容，因为崩盘时 Long Vega 是对冲
            hysteresis=0.0005,
            alert_type="VEGA_EXPOSURE",
            red_below_message="Vega/NLV 空头过大: {value:.2%} < {threshold:.2%}，崩盘时遭遇股价亏+IV亏双杀",
            yellow_message="Vega/NLV 偏大: {value:.2%}",
            red_below_action="IV 对冲/降仓：买入 VIX Call 或 SPY Put，或平掉 Vega 贡献最大的 Short Leg",
            yellow_action="关注波动率风险",
        )
    )

    theta_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.0005, 0.0015),  # 0.05% ~ 0.15%
            yellow=(0.0015, 0.0025),  # 0.15% ~ 0.25%
            red_above=0.0030,  # > 0.30%
            red_below=0.0,  # < 0%
            hysteresis=0.0002,
            alert_type="THETA_EXPOSURE",
            red_above_message="Theta/NLV 过高: {value:.2%} > {threshold:.2%}，卖得太满，Gamma 风险失控",
            red_below_message="Theta/NLV 为负: {value:.2%}，买方策略时间衰减不利",
            yellow_message="Theta/NLV 偏高: {value:.2%}",
            red_above_action="降低风险暴露：平仓部分 Short 头寸，Theta 过高意味着 Gamma 风险过大",
            red_below_action="检查策略逻辑：如非特意做买方策略，需调整持仓结构",
            yellow_action="关注时间衰减效率",
        )
    )

    vega_weighted_iv_hv: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(1.0, float("inf")),  # > 1.0
            yellow=(0.8, 1.2),  # 0.8 ~ 1.2
            red_below=0.8,  # < 0.8
            hysteresis=0.05,
            alert_type="IV_HV_QUALITY",
            red_below_message='Vega加权 IV/HV 过低: {value:.2f} < {threshold}，持仓在"贱卖"期权',
            yellow_message="Vega加权 IV/HV 偏低: {value:.2f}",
            red_below_action="停止做空/熔断：禁止开设新的 Short Vega 仓位，仅允许做 Debit 策略或持有现金",
            yellow_action="关注期权定价质量",
        )
    )


@dataclass
class PositionThresholds:
    """持仓级阈值 - 统一使用 ThresholdRange

    基于实战经验优化的阈值设计：
    - OTM%: 统一公式 Put=(S-K)/S, Call=(K-S)/S
    - |Delta|: 使用绝对值，更早预警
    - DTE: 绿色提高到14天，红色阈值 DTE < 4 天
    - Gamma Risk%: 相对 Margin 的百分比
    """

    # OTM% (虚值百分比) - Gamma 策略：仅 ITM 时强制平仓，近 ATM 由 TGR 判断
    otm_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.10, float("inf")),    # OTM ≥ 10%
            yellow=(0.0, 0.10),            # 0% ~ 10%
            red_below=0.0,                 # OTM < 0% (已 ITM)
            hysteresis=0.01,
            alert_type="OTM_PCT",
            red_below_message="已进入 ITM: OTM%={value:.1%}，必须平仓",
            yellow_message="OTM% 偏低: {value:.1%}，接近 ATM",
            red_below_action="ITM 强制平仓",
            yellow_action="关注方向性风险，TGR 将判断是否退出",
        )
    )

    # |Delta| (方向性风险) - 使用绝对值
    delta: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 0.30),               # |Delta| ≤ 0.30
            yellow=(0.30, 0.65),           # 0.30 ~ 0.65
            red_above=0.65,                # |Delta| > 0.65
            hysteresis=0.03,
            alert_type="DELTA_CHANGE",
            red_above_message="|Delta| 过大: {value:.2f}(>0.65)，方向性风险高",
            yellow_message="|Delta| 偏大: {value:.2f}(>0.30)",
            red_above_action="必须行动：对冲正股或平仓，不要等到 0.8",
            yellow_action="关注方向性风险，准备对冲",
        )
    )

    # DTE (Days to Expiration) - 不因 DTE 强制平仓，允许合约自然到期
    dte: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(14, float("inf")),      # DTE ≥ 14 天
            yellow=(0, 14),                # 0 ~ 14 天
            red_below=0,                   # DTE < 0 天（等同禁用）
            hysteresis=1,
            alert_type="DTE_WARNING",
            red_below_message="DTE 已过期: {value:.0f} 天",
            yellow_message="DTE 进入两周内: {value:.0f} 天",
            red_below_action="合约已过期，检查持仓状态",
            yellow_action="关注到期日，准备到期处理",
        )
    )

    # P&L% (持仓未实现收益率)
    # Gamma 策略：止损放宽到 -200%，TGR 会在此之前触发主动退出
    pnl: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.50, float("inf")),    # 盈利 ≥ 50% (止盈目标)
            yellow=(-2.0, 0.50),           # -200% ~ 50%
            red_below=-2.0,                # 亏损 < -200% (极端兆底止损)
            hysteresis=0.05,
            alert_type="STOP_LOSS",
            red_below_message="持仓亏损极端: {value:.1%}，触发兆底止损线",
            yellow_message="持仓盈亏: {value:.1%}",
            green_message="持仓达到止盈目标: {value:.1%}",
            red_below_action="极端兆底止损，无条件平仓",
            yellow_action="关注盈亏变化",
            green_action="考虑止盈平仓，锁定利润",
        )
    )

    # Gamma Risk% (Gamma 风险百分比) - 相对 Margin
    gamma_risk_pct: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 0.005),              # Gamma/Margin ≤ 0.5%
            yellow=(0.005, 0.01),          # 0.5% ~ 1%
            red_above=0.01,                # Gamma/Margin > 1%
            hysteresis=0.001,
            alert_type="GAMMA_RISK_PCT",
            red_above_message="Gamma Risk% 过高: {value:.2%}，相对 Margin 风险大",
            yellow_message="Gamma Risk% 偏高: {value:.2%}",
            red_above_action="减仓或平仓，降低 Gamma 风险敞口",
            yellow_action="关注 Gamma 风险变化",
        )
    )

    # TGR (Theta/Gamma Ratio) - 标准化公式：|Theta| / (|Gamma| × S² × σ_daily) × 100
    # Position 级使用 POSITION_TGR，与 Portfolio 级 TGR_LOW 区分
    # 持有到期策略：放宽红线到 0.5，避免临期 Gamma 加速时误触发
    tgr: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(1.5, float("inf")),     # 标准化 TGR ≥ 1.5
            yellow=(0.5, 1.5),             # 0.5 ~ 1.5
            red_below=0.5,                 # TGR < 0.5
            hysteresis=0.1,
            alert_type="POSITION_TGR",     # Position 级使用单独的 AlertType
            red_below_message="TGR 过低: {value:.2f}，时间收益/波动风险比不足",
            yellow_message="TGR 偏低: {value:.2f}",
            red_below_action="关注持仓效率，考虑调整",
            yellow_action="关注时间衰减效率",
        )
    )

    # IV/HV Ratio (Position 级使用 POSITION_IV_HV，与 Portfolio 级 IV_HV_QUALITY 区分)
    iv_hv: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(1.2, float("inf")),     # IV/HV ≥ 1.2
            yellow=(0.8, 1.2),             # 0.8 ~ 1.2 (注意: 1.1 在 yellow)
            red_below=0.8,                 # IV/HV < 0.8
            hysteresis=0.05,
            alert_type="POSITION_IV_HV",   # Position 级使用单独的 AlertType
            red_below_message="IV/HV 过低: {value:.2f}，期权被低估",
            yellow_message="IV/HV 偏低: {value:.2f}",
            red_below_action="如盈利可提前止盈，避免继续卖出",
            yellow_action="关注期权定价",
        )
    )

    # ROC (Return on Capital) - 降低绿色门槛
    roc: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.20, float("inf")),    # ROC ≥ 20%
            yellow=(0.10, 0.20),           # 10% ~ 20%
            red_below=0.10,                # ROC < 10%
            hysteresis=0.02,
            alert_type="ROC_LOW",
            red_below_message="ROC 过低: {value:.1%}，资金效率差",
            yellow_message="ROC 偏低: {value:.1%}",
            red_below_action="考虑平仓，寻找更高效策略",
            yellow_action="关注资金使用效率",
        )
    )

    # Expected ROC (预期资本回报率) - 新增关键指标
    expected_roc: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.10, float("inf")),    # Expected ROC ≥ 10%
            yellow=(0.0, 0.10),            # 0% ~ 10%
            red_below=0.0,                 # Expected ROC < 0%
            hysteresis=0.02,
            alert_type="EXPECTED_ROC_LOW",
            red_below_message="Expected ROC 为负: {value:.1%}，预期亏损",
            yellow_message="Expected ROC 偏低: {value:.1%}",
            red_below_action="立即平仓，策略已失效",
            yellow_action="关注预期收益变化",
        )
    )

    # Win Probability (胜率) - 新增关键指标
    win_probability: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.70, float("inf")),    # Win Prob ≥ 70%
            yellow=(0.55, 0.70),           # 55% ~ 70%
            red_below=0.55,                # Win Prob < 55%
            hysteresis=0.03,
            alert_type="WIN_PROB_LOW",
            red_below_message="胜率过低: {value:.0%}，策略优势不足",
            yellow_message="胜率偏低: {value:.0%}",
            red_below_action="考虑平仓，寻找更高效策略",
            yellow_action="关注胜率变化",
        )
    )

    # 注意: PREI、SAS 和 Dividend Risk 已移除

    # Early Take Profit — DTE + 盈利联合止盈（独立规则）
    early_take_profit: "EarlyTakeProfitConfig" = field(
        default_factory=lambda: EarlyTakeProfitConfig()
    )


@dataclass
class EarlyTakeProfitRule:
    """单条 DTE+PnL 联合止盈规则"""
    dte_below: int          # DTE < 此值
    pnl_above: float        # PnL ≥ 此值 (0.50 = 50%)
    level: str = "red"      # red / yellow / green


@dataclass
class EarlyTakeProfitConfig:
    """DTE + 盈利联合止盈配置

    独立于 DTE 和 PnL 检查，按优先级从高到低匹配：
    rules 列表中先匹配的先返回。
    """
    # 启用联合止盈，PnL 阈值提高到 70%（延长持有时间但保留利润锁定）
    enabled: bool = True
    rules: list[EarlyTakeProfitRule] = field(default_factory=lambda: [
        EarlyTakeProfitRule(dte_below=14, pnl_above=0.70, level="red"),
        EarlyTakeProfitRule(dte_below=21, pnl_above=0.70, level="yellow"),
        EarlyTakeProfitRule(dte_below=30, pnl_above=0.80, level="green"),
    ])


@dataclass
class StrategyPositionThresholds:
    """策略特定的持仓级阈值覆盖

    不同策略类型有不同的风险特征：
    - Short Put: 标准阈值，需严格控制 Gamma 和 DTE
    - Covered Call: 有正股覆盖，DTE/Delta/Gamma 可放宽
    - Short Strangle: 双向风险，使用标准阈值

    这个类用于存储策略特定的阈值覆盖，会与 PositionThresholds 合并使用。
    """

    strategy_type: StrategyType = StrategyType.UNKNOWN
    description: str = ""

    # 策略特定覆盖（None 表示使用默认值）
    dte: ThresholdRange | None = None
    delta: ThresholdRange | None = None
    otm_pct: ThresholdRange | None = None
    gamma_risk_pct: ThresholdRange | None = None
    tgr: ThresholdRange | None = None
    pnl: ThresholdRange | None = None
    early_take_profit: EarlyTakeProfitConfig | None = None

    def merge_with_base(self, base: "PositionThresholds") -> "PositionThresholds":
        """与基础配置合并，返回新的 PositionThresholds

        策略特定配置覆盖基础配置中的对应字段。

        Args:
            base: 基础 PositionThresholds

        Returns:
            合并后的 PositionThresholds
        """
        from copy import deepcopy
        merged = deepcopy(base)

        if self.dte is not None:
            merged.dte = self.dte
        if self.delta is not None:
            merged.delta = self.delta
        if self.otm_pct is not None:
            merged.otm_pct = self.otm_pct
        if self.gamma_risk_pct is not None:
            merged.gamma_risk_pct = self.gamma_risk_pct
        if self.tgr is not None:
            merged.tgr = self.tgr
        if self.pnl is not None:
            merged.pnl = self.pnl
        if self.early_take_profit is not None:
            merged.early_take_profit = self.early_take_profit

        return merged


# 预定义策略配置
STRATEGY_POSITION_CONFIGS: dict[StrategyType, StrategyPositionThresholds] = {
    # Short Put: 标准阈值
    StrategyType.SHORT_PUT: StrategyPositionThresholds(
        strategy_type=StrategyType.SHORT_PUT,
        description="Short Put 策略：标准阈值，裸卖需严格风控",
    ),

    # Covered Call: 有正股覆盖，阈值更宽松
    StrategyType.COVERED_CALL: StrategyPositionThresholds(
        strategy_type=StrategyType.COVERED_CALL,
        description="Covered Call 策略：有正股覆盖，Gamma/DTE/Delta 可放宽",
        # DTE 放宽：可持有到期（正股覆盖 Gamma 风险）
        dte=ThresholdRange(
            green=(7, float("inf")),       # DTE ≥ 7 天即可
            yellow=(3, 7),                 # 3~7 天
            red_below=3,                   # DTE < 3 天
            hysteresis=1,
            alert_type="DTE_WARNING",
            red_below_message="DTE < 3 天: {value:.0f} 天，接近到期",
            yellow_message="DTE 进入一周内: {value:.0f} 天",
            red_below_action="考虑展期或接受行权",
            yellow_action="准备展期计划或接受行权",
        ),
        # Delta 放宽：被行权等于卖出正股，可接受
        delta=ThresholdRange(
            green=(0, 0.40),               # |Delta| ≤ 0.40
            yellow=(0.40, 0.60),           # 0.40 ~ 0.60
            red_above=0.70,                # |Delta| > 0.70
            hysteresis=0.03,
            alert_type="DELTA_CHANGE",
            red_above_message="|Delta| 过大: {value:.2f}，接近行权",
            yellow_message="|Delta| 偏大: {value:.2f}",
            red_above_action="准备接受行权（卖出正股）或展期到更高 Strike",
            yellow_action="关注行权风险，评估是否展期",
        ),
        # OTM% 放宽：被行权是收益
        otm_pct=ThresholdRange(
            green=(0.05, float("inf")),    # OTM ≥ 5%
            yellow=(0.02, 0.05),           # 2% ~ 5%
            red_below=0.02,                # OTM < 2%
            hysteresis=0.01,
            alert_type="OTM_PCT",
            red_below_message="OTM% 过低: {value:.1%}，接近行权",
            yellow_message="OTM% 偏低: {value:.1%}",
            red_below_action="准备接受行权或展期到更高 Strike",
            yellow_action="关注行权风险",
        ),
        # Gamma Risk 放宽：正股覆盖
        gamma_risk_pct=ThresholdRange(
            green=(0, 0.02),               # Gamma/Margin ≤ 2%
            yellow=(0.02, 0.03),           # 2% ~ 3%
            red_above=0.03,                # Gamma/Margin > 3%
            hysteresis=0.002,
            alert_type="GAMMA_RISK_PCT",
            red_above_message="Gamma Risk% 偏高: {value:.2%}（正股覆盖，风险可控）",
            yellow_message="Gamma Risk% 偏高: {value:.2%}",
            red_above_action="正股覆盖，风险可控，可持有",
            yellow_action="关注 Gamma 风险变化",
        ),
    ),

    # Short Strangle: 双向风险，使用标准阈值
    StrategyType.SHORT_STRANGLE: StrategyPositionThresholds(
        strategy_type=StrategyType.SHORT_STRANGLE,
        description="Short Strangle 策略：双向裸卖，需严格风控",
    ),

    # 默认配置
    StrategyType.UNKNOWN: StrategyPositionThresholds(
        strategy_type=StrategyType.UNKNOWN,
        description="默认配置：使用标准阈值",
    ),
}


@dataclass
class CapitalThresholds:
    """资金级阈值 - 统一使用 ThresholdRange

    核心风控四大支柱：
    1. Margin Utilization (保证金使用率) - 生存：距离追保的距离
    2. Cash Ratio (现金留存率) - 流动性：操作灵活度
    3. Gross Leverage (总名义杠杆) - 敞口：防止"虚胖"
    4. Stress Test Loss (压力测试风险) - 稳健：尾部风险保护
    """

    # 1. Margin Utilization: Maint Margin / NLV
    # 绿色: < 40%, 黄色: 40%~70%, 红色: > 70%
    margin_utilization: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 0.40),
            yellow=(0.40, 0.70),
            red_above=0.70,
            hysteresis=0.02,
            alert_type="MARGIN_UTILIZATION",
            red_above_message="保证金使用率过高: {value:.1%} > {threshold:.0%}，接近追保线",
            yellow_message="保证金使用率偏高: {value:.1%}",
            green_message="保证金使用率正常: {value:.1%}",
            red_above_action="强制去杠杆：按保证金/Theta效率排序，平掉效率最低的头寸",
            yellow_action="谨慎加仓，关注保证金水平",
            green_action="保证金充足",
        )
    )

    # 2. Cash Ratio: Net Cash Balance / NLV
    # 绿色: > 30%, 黄色: 10%~30%, 红色: < 10%
    cash_ratio: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0.30, float("inf")),
            yellow=(0.10, 0.30),
            red_below=0.10,
            hysteresis=0.02,
            alert_type="CASH_RATIO",
            red_below_message="现金留存率过低: {value:.1%} < {threshold:.0%}，流动性不足",
            yellow_message="现金留存率偏低: {value:.1%}",
            green_message="现金留存率充足: {value:.1%}",
            red_below_action="停止开仓 & 变现：禁止消耗现金的新仓位，平掉部分盈利头寸补充现金",
            yellow_action="关注现金储备，控制开仓节奏",
            green_action="现金充足，可正常操作",
        )
    )

    # 3. Gross Leverage: Total Notional / NLV
    # 绿色: < 2.0x, 黄色: 2.0x~4.0x, 红色: > 4.0x
    gross_leverage: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 2.0),
            yellow=(2.0, 4.0),
            red_above=4.0,
            hysteresis=0.1,
            alert_type="GROSS_LEVERAGE",
            red_above_message="总名义杠杆过高: {value:.1f}x > {threshold:.1f}x，账户'虚胖'",
            yellow_message="总名义杠杆偏高: {value:.1f}x",
            green_message="总名义杠杆正常: {value:.1f}x",
            red_above_action="缩减规模：按比例缩减所有策略的仓位规模，降低整体风险暴露",
            yellow_action="关注总敞口，避免继续放大",
            green_action="杠杆水平合理",
        )
    )

    # 4. Stress Test Loss: (Current_NLV - Stressed_NLV) / Current_NLV
    # 场景: Spot -15% & IV +40%
    # 绿色: < 10%, 黄色: 10%~20%, 红色: > 20%
    stress_test_loss: ThresholdRange = field(
        default_factory=lambda: ThresholdRange(
            green=(0, 0.10),
            yellow=(0.10, 0.20),
            red_above=0.20,
            hysteresis=0.01,
            alert_type="STRESS_TEST_LOSS",
            red_above_message="压力测试亏损过高: {value:.1%} > {threshold:.0%}，尾部风险过大",
            yellow_message="压力测试亏损偏高: {value:.1%}",
            green_message="压力测试亏损可控: {value:.1%}",
            red_above_action="切断尾部：买入深虚值Put保护，或平掉Short Gamma最大的头寸",
            yellow_action="关注尾部风险，考虑增加保护",
            green_action="尾部风险可控",
        )
    )


@dataclass
class DynamicAdjustment:
    """动态调整配置"""

    # 高波动率环境 (VIX > 28)
    high_vol_gamma_multiplier: float = 0.6
    high_vol_delta_multiplier: float = 0.8
    high_vol_kelly_multiplier: float = 0.5

    # 趋势环境 (ADX > 25)
    trending_counter_multiplier: float = 0.7
    trending_with_multiplier: float = 1.2

    # 震荡环境 (ADX < 20)
    ranging_gamma_multiplier: float = 1.3
    ranging_tgr_multiplier: float = 1.2


@dataclass
class MonitoringConfig:
    """监控配置

    支持策略特定的阈值配置：
    - portfolio: Portfolio 级阈值（所有策略共用）
    - position: Position 级基础阈值（可被策略覆盖）
    - capital: Capital 级阈值（所有策略共用）
    - strategy_configs: 策略特定的 Position 级阈值覆盖

    使用 get_position_thresholds(strategy_type) 获取合并后的阈值。
    """

    portfolio: PortfolioThresholds = field(default_factory=PortfolioThresholds)
    position: PositionThresholds = field(default_factory=PositionThresholds)
    capital: CapitalThresholds = field(default_factory=CapitalThresholds)
    dynamic: DynamicAdjustment = field(default_factory=DynamicAdjustment)

    # 策略特定配置缓存
    _strategy_position_cache: dict[StrategyType, PositionThresholds] = field(
        default_factory=dict, repr=False
    )

    def get_position_thresholds(
        self, strategy_type: StrategyType | str | None = None
    ) -> PositionThresholds:
        """获取策略特定的 Position 级阈值

        根据策略类型返回合并后的阈值配置：
        - 如果策略有特定配置，与基础配置合并
        - 如果没有特定配置，返回基础配置

        Args:
            strategy_type: 策略类型（StrategyType 枚举或字符串）

        Returns:
            合并后的 PositionThresholds
        """
        if not strategy_type:
            return self.position

        # 将字符串转换为枚举（向后兼容）
        if isinstance(strategy_type, str):
            strategy_type = StrategyType.from_string(strategy_type)

        # 检查缓存
        if strategy_type in self._strategy_position_cache:
            return self._strategy_position_cache[strategy_type]

        # 获取策略配置并合并
        strategy_config = STRATEGY_POSITION_CONFIGS.get(
            strategy_type,
            STRATEGY_POSITION_CONFIGS[StrategyType.UNKNOWN]
        )
        merged = strategy_config.merge_with_base(self.position)

        # 缓存结果
        self._strategy_position_cache[strategy_type] = merged
        return merged

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        mode: ConfigMode = ConfigMode.LIVE,
    ) -> "MonitoringConfig":
        """从 YAML 文件加载配置

        Args:
            path: YAML 文件路径
            mode: 配置模式 (LIVE 或 BACKTEST)

        Returns:
            MonitoringConfig 实例
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data, mode=mode)

    @staticmethod
    def _parse_threshold_range(data: dict[str, Any], default: ThresholdRange) -> ThresholdRange:
        """从字典解析 ThresholdRange

        Args:
            data: YAML 中的阈值配置
            default: 默认的 ThresholdRange

        Returns:
            解析后的 ThresholdRange
        """
        green = data.get("green")
        yellow = data.get("yellow")

        # 处理 .inf (YAML 中表示无穷大)
        def parse_range(val: list | None) -> tuple[float, float] | None:
            if val is None:
                return None
            low, high = val
            if high == ".inf" or high == float("inf"):
                high = float("inf")
            if low == "-.inf" or low == float("-inf"):
                low = float("-inf")
            return (float(low), float(high))

        return ThresholdRange(
            green=parse_range(green) if green else default.green,
            yellow=parse_range(yellow) if yellow else default.yellow,
            red_above=data.get("red_above", default.red_above),
            red_below=data.get("red_below", default.red_below),
            hysteresis=data.get("hysteresis", default.hysteresis),
            enabled=data.get("enabled", default.enabled),
            alert_type=data.get("alert_type", default.alert_type),
            red_above_message=data.get("red_above_message", default.red_above_message),
            red_below_message=data.get("red_below_message", default.red_below_message),
            yellow_message=data.get("yellow_message", default.yellow_message),
            red_above_action=data.get("red_above_action", default.red_above_action),
            red_below_action=data.get("red_below_action", default.red_below_action),
            yellow_action=data.get("yellow_action", default.yellow_action),
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        mode: ConfigMode = ConfigMode.LIVE,
    ) -> "MonitoringConfig":
        """从字典创建配置

        Args:
            data: 配置字典
            mode: 配置模式 (LIVE 或 BACKTEST)

        Returns:
            MonitoringConfig 实例

        YAML 结构示例:
            portfolio_level:
              ...
            position_level:
              ...
            # 可选: 回测覆盖
            backtest_overrides:
              position_level:
                delta:
                  red_above: 0.70
        """
        # 如果是 BACKTEST 模式，合并 backtest_overrides
        if mode == ConfigMode.BACKTEST and "backtest_overrides" in data:
            data = merge_overrides(data, data["backtest_overrides"])

        config = cls()

        if "portfolio_level" in data:
            pl = data["portfolio_level"]

            # 使用统一的 ThresholdRange 解析
            if "portfolio_tgr" in pl:
                config.portfolio.portfolio_tgr = cls._parse_threshold_range(
                    pl["portfolio_tgr"],
                    PortfolioThresholds().portfolio_tgr,
                )

            if "concentration_hhi" in pl:
                config.portfolio.concentration_hhi = cls._parse_threshold_range(
                    pl["concentration_hhi"],
                    PortfolioThresholds().concentration_hhi,
                )

        # Position level 的 YAML 解析
        if "position_level" in data:
            pos = data["position_level"]
            defaults = PositionThresholds()

            # ThresholdRange 字段映射：YAML key → PositionThresholds 属性名
            _tr_fields = {
                "otm_pct": "otm_pct",
                "delta": "delta",
                "dte": "dte",
                "pnl": "pnl",
                "gamma_risk_pct": "gamma_risk_pct",
                "tgr": "tgr",
                "iv_hv": "iv_hv",
                "expected_roc": "expected_roc",
                "win_probability": "win_probability",
            }

            for yaml_key, attr_name in _tr_fields.items():
                if yaml_key in pos:
                    default_range = getattr(defaults, attr_name)
                    parsed = cls._parse_threshold_range(pos[yaml_key], default_range)
                    setattr(config.position, attr_name, parsed)

            # Early Take Profit（独立规则，非 ThresholdRange）
            if "early_take_profit" in pos:
                etp = pos["early_take_profit"]
                config.position.early_take_profit = EarlyTakeProfitConfig(
                    enabled=etp.get("enabled", True),
                    rules=[
                        EarlyTakeProfitRule(
                            dte_below=r["dte_below"],
                            pnl_above=r["pnl_above"],
                            level=r["level"],
                        )
                        for r in etp.get("rules", [])
                    ],
                )
        if "dynamic_adjustment" in data:
            da = data["dynamic_adjustment"]
            if "high_volatility" in da:
                hv = da["high_volatility"]
                config.dynamic.high_vol_gamma_multiplier = hv.get(
                    "gamma_multiplier", 0.6
                )
                config.dynamic.high_vol_delta_multiplier = hv.get(
                    "delta_multiplier", 0.8
                )
                config.dynamic.high_vol_kelly_multiplier = hv.get(
                    "kelly_multiplier", 0.5
                )
            if "trending" in da:
                t = da["trending"]
                config.dynamic.trending_counter_multiplier = t.get(
                    "counter_trend_multiplier", 0.7
                )
                config.dynamic.trending_with_multiplier = t.get(
                    "with_trend_multiplier", 1.2
                )
            if "ranging" in da:
                r = da["ranging"]
                config.dynamic.ranging_gamma_multiplier = r.get("gamma_multiplier", 1.3)
                config.dynamic.ranging_tgr_multiplier = r.get("tgr_multiplier", 1.2)

        return config

    @classmethod
    def load(cls, mode: ConfigMode = ConfigMode.LIVE) -> "MonitoringConfig":
        """加载默认配置

        Args:
            mode: 配置模式 (LIVE 或 BACKTEST)

        Returns:
            MonitoringConfig 实例
        """
        config_dir = (
            Path(__file__).parent.parent.parent.parent / "config" / "monitoring"
        )
        config_file = config_dir / "thresholds.yaml"
        if config_file.exists():
            return cls.from_yaml(config_file, mode=mode)
        return cls()

