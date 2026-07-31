# 路线 2：Regime 模型 + RV 预测

> 目标：精进 SmartRisk 的风控层，用 ML 替代部分硬编码规则。
> 前置：路线 1（选股）和路线 3（配仓）已初步完成后再投入。
> 预期：Sharpe +0.1-0.3，回撤降低 2-4 个百分点。

---

## 1. 整体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                SmartRisk V2: ML-Enhanced Risk Control                 │
│                                                                      │
│  现有 SmartRisk 3 层                    ML 增强层                     │
│  ┌──────────────┐                      ┌──────────────┐             │
│  │ Tier 1:      │  ← 保留规则 ─────────│ HMM Regime   │             │
│  │ Panic Break  │    + 补充 HMM 的      │ (状态转移    │             │
│  │ (VIX Term)   │    regime 概率         │  概率输出)   │             │
│  ├──────────────┤                      ├──────────────┤             │
│  │ Tier 2:      │  ← 保留规则 ─────────│ HAR-RV       │             │
│  │ Bear Limiter │    + RV 预测替代      │ 波动率预测   │             │
│  │ (SMA200)     │    VIX 做 vol target  │              │             │
│  ├──────────────┤                      ├──────────────┤             │
│  │ Tier 3:      │  ← RV 预测驱动 ──────│ XGBoost      │             │
│  │ Vol Target   │    (替代 VIX 简单     │ 多特征 RV    │             │
│  │              │     映射)             │ 预测模型     │             │
│  └──────────────┘                      └──────────────┘             │
└──────────────────────────────────────────────────────────────────────┘
```

**核心原则：ML 模型作为信号增强，规则作为安全网。二者并行，取更保守的结果。**

---

## 2. HAR-RV 波动率预测（周 1-2）

### 2.1 为什么 HAR-RV

| 模型 | 优点 | 缺点 | RV 预测 R² |
|------|------|------|-----------|
| **HAR-RV** | 极简（3 个变量）、可解释、稳定 | 只捕捉线性关系 | 0.4-0.6 |
| GARCH(1,1) | 经典、自适应 | 单尺度、厚尾处理弱 | 0.3-0.5 |
| EGARCH | 捕捉非对称 vol | 参数敏感 | 0.35-0.55 |
| HAR-RV + XGBoost | 捕捉非线性 | 过拟合风险 | 0.5-0.7 |
| LSTM | 高容量 | 数据量不够、不稳定 | 0.4-0.65 |

**推荐路线：先实现 HAR-RV 基线，再用 XGBoost 增强。**

### 2.2 HAR-RV 模型（Corsi 2009）

```
RV_t+h = β₀ + β₁ × RV_day + β₂ × RV_week + β₃ × RV_month + ε

其中:
  RV_day   = 过去 1 天的 realized volatility
  RV_week  = 过去 5 天的平均 RV
  RV_month = 过去 22 天的平均 RV
  h        = 预测期限 (5 天或 22 天)
```

### 2.3 实现

```python
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

class HARRVPredictor:
    """HAR-RV: Heterogeneous Autoregressive model of Realized Volatility"""

    def __init__(self, horizon: int = 5):
        self.horizon = horizon  # 预测未来 N 天的 RV
        self.model = LinearRegression()

    def compute_rv(self, returns: pd.Series, window: int) -> pd.Series:
        """Realized Volatility = sqrt(sum(r²)) 在窗口内"""
        return (returns ** 2).rolling(window).sum().apply(np.sqrt)

    def prepare_features(self, returns: pd.Series) -> pd.DataFrame:
        """构建 HAR 三尺度特征"""
        rv_1d = self.compute_rv(returns, 1)
        rv_5d = self.compute_rv(returns, 5) / np.sqrt(5)   # 归一化到日频
        rv_22d = self.compute_rv(returns, 22) / np.sqrt(22)

        features = pd.DataFrame({
            "rv_day": rv_1d,
            "rv_week": rv_5d,
            "rv_month": rv_22d,
        }).dropna()
        return features

    def fit(self, returns: pd.Series) -> None:
        """训练模型"""
        features = self.prepare_features(returns)

        # 目标: 未来 horizon 天的 RV
        target_rv = self.compute_rv(returns, self.horizon).shift(-self.horizon) / np.sqrt(self.horizon)

        # 对齐
        aligned = pd.concat([features, target_rv.rename("target")], axis=1).dropna()

        X = aligned[["rv_day", "rv_week", "rv_month"]]
        y = aligned["target"]

        self.model.fit(X, y)

    def predict(self, returns: pd.Series) -> float:
        """预测未来 horizon 天的日均 RV"""
        features = self.prepare_features(returns)
        latest = features.iloc[[-1]]
        return float(self.model.predict(latest)[0])
```

### 2.4 XGBoost 增强版

```python
# 在 HAR-RV 基础上添加更多特征
enhanced_features = {
    # HAR 基础
    "rv_day": "1日 RV",
    "rv_week": "5日 RV",
    "rv_month": "22日 RV",

    # 市场微观结构
    "volume_ratio": "成交量 / 20日均量",
    "high_low_range": "(H-L)/C 日内振幅",
    "close_to_close_vol": "收盘价波动率",

    # VIX 家族
    "vix": "VIX 现值",
    "vix3m": "VIX3M",
    "vix_term": "VIX/VIX3M 期限结构",
    "vix_5d_change": "VIX 5日变化",

    # 跨资产
    "tnx_level": "10Y 国债收益率",
    "credit_spread": "HY-IG 信用利差 (如可获取)",
    "gold_vol": "黄金 5日 RV",

    # 技术指标
    "rsi_14": "14日 RSI",
    "sma200_distance": "(Price - SMA200) / SMA200",
}

# XGBoost 训练
from xgboost import XGBRegressor

model = XGBRegressor(
    n_estimators=200,
    max_depth=4,          # 限制深度防止过拟合
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,        # L1 正则化
    reg_lambda=1.0,       # L2 正则化
)
```

### 2.5 RV 预测 → Vol Target 集成

```python
# 当前 SmartRisk Vol Target (基于 VIX):
def current_vol_target(vix: float, target_vol: float = 0.16) -> float:
    """VIX → 杠杆上限"""
    return target_vol / (vix / 100 * np.sqrt(252))

# ML 增强版 (基于预测 RV):
def ml_vol_target(predicted_rv: float, target_vol: float = 0.16) -> float:
    """预测 RV → 杠杆上限"""
    annualized_rv = predicted_rv * np.sqrt(252)
    leverage = target_vol / annualized_rv
    return min(leverage, 3.0)  # 安全上限

# 最终策略: 取保守值
def combined_vol_target(vix, predicted_rv, target_vol=0.16):
    rule_based = current_vol_target(vix, target_vol)
    ml_based = ml_vol_target(predicted_rv, target_vol)
    return min(rule_based, ml_based)  # 取更保守的
```

### 2.6 预期提升

```
当前 SmartRisk Vol Target: 用 VIX 做杠杆映射
问题: VIX 是隐含波动率，有时 overstate 真实风险
  → 不必要的降杠杆 → 错过收益

HAR-RV 预测: 直接预测未来 5 天 realized vol
  → 更精准的杠杆调整
  → 减少 false alarm (VIX 跳高但实际 RV 不高)
  → 预期年化提升 1-3%, Sharpe +0.1-0.2
```

---

## 3. HMM Regime 模型（周 3-4）

### 3.1 Hidden Markov Model 用于 Regime 检测

**状态定义（3 状态模型）**

| 状态 | 特征 | 历史占比 |
|------|------|---------|
| State 0: 低波牛市 | 低 vol, 正收益, 低相关 | ~55% |
| State 1: 高波震荡 | 中高 vol, 收益不确定 | ~30% |
| State 2: 危机 | 极高 vol, 负收益, 高相关 | ~15% |

### 3.2 实现

```python
from hmmlearn.hmm import GaussianHMM
import numpy as np
import pandas as pd

class RegimeDetector:
    """HMM-based market regime detection"""

    def __init__(self, n_regimes: int = 3):
        self.n_regimes = n_regimes
        self.model = GaussianHMM(
            n_components=n_regimes,
            covariance_type="full",
            n_iter=200,
            random_state=42,
        )

    def prepare_observations(self, data: dict[str, pd.Series]) -> np.ndarray:
        """
        多维观测序列:
        - 日收益率
        - 5日 realized vol
        - VIX 水平
        """
        returns = data["returns"]
        rv5 = (returns ** 2).rolling(5).sum().apply(np.sqrt)
        vix = data["vix"]

        obs = pd.DataFrame({
            "return": returns,
            "rv5": rv5,
            "vix": vix,
        }).dropna()

        return obs.values, obs.index

    def fit(self, data: dict[str, pd.Series]) -> None:
        obs, _ = self.prepare_observations(data)
        self.model.fit(obs)

        # 按波动率排序状态 (确保 State 0 = 低波)
        means = self.model.means_
        vol_order = np.argsort(means[:, 1])  # 按 rv5 排序
        self._reorder_states(vol_order)

    def predict_regime(self, data: dict[str, pd.Series]) -> dict:
        """返回当前 regime 和转移概率"""
        obs, dates = self.prepare_observations(data)

        # 当前最可能状态
        states = self.model.predict(obs)
        current_state = states[-1]

        # 状态概率分布
        state_probs = self.model.predict_proba(obs)[-1]

        # 转移概率矩阵
        trans_matrix = self.model.transmat_

        # 未来 5 天仍在当前状态的概率
        stay_prob = trans_matrix[current_state, current_state] ** 5

        return {
            "current_regime": int(current_state),
            "regime_name": ["low_vol_bull", "high_vol_choppy", "crisis"][current_state],
            "state_probabilities": state_probs.tolist(),
            "stay_probability_5d": float(stay_prob),
            "transition_matrix": trans_matrix.tolist(),
        }
```

### 3.3 HMM vs 规则的对比

| 场景 | SmartRisk 规则 | HMM |
|------|--------------|-----|
| VIX 从 15 跳到 25 | Panic Breaker 触发 | 可能仍是 State 1（高波但非危机） |
| VIX 缓慢从 18 升到 22 | 不触发任何规则 | 可能检测到 State 0→1 转移 |
| VIX 30 但 VIX3M 也 30 | VIX term = 1.0，不触发 | 基于多维特征，可能识别为 State 2 |
| 2022 慢熊 | Bear Limiter (SMA200) 延迟触发 | HMM 可能更早检测 |

### 3.4 集成方式：HMM 增强规则，不替代规则

```python
def smartrisk_v2_filter(
    rule_based_cap: float,     # SmartRisk 规则输出的杠杆上限
    hmm_regime: dict,          # HMM 输出
) -> float:
    """
    规则和 HMM 并行运行，取更保守的结果。
    HMM 提供额外的信号，但不覆盖规则的安全网。
    """
    hmm_cap = {
        0: 3.0,    # low_vol_bull: 不限制
        1: 2.0,    # high_vol_choppy: 温和限制
        2: 0.5,    # crisis: 强限制
    }[hmm_regime["current_regime"]]

    # 如果 HMM 不确定（最大状态概率 < 0.6），不施加额外限制
    max_prob = max(hmm_regime["state_probabilities"])
    if max_prob < 0.6:
        hmm_cap = 3.0  # 不限制

    return min(rule_based_cap, hmm_cap)
```

### 3.5 HMM 的已知问题与应对

| 问题 | 影响 | 应对 |
|------|------|------|
| 状态数选择 | 3 vs 4 vs 5 状态效果不同 | BIC/AIC 选择 + walk-forward |
| Look-ahead bias | 全样本 fit 会泄露未来信息 | 必须 expanding window 训练 |
| 状态标签不稳定 | 重新训练后 State 0/1/2 含义变化 | 按波动率重排序 |
| 转移检测延迟 | HMM 需要几天数据才能确认切换 | 与规则并行，规则做即时响应 |
| 过拟合 | 尤其是 n_components 过大时 | 限制 3 状态 + 正则化 |

---

## 4. 强化学习在策略优化中的应用（探索性，周 5-6）

### 4.1 适用场景

RL **不适合**直接做交易决策（状态空间太大、奖励稀疏、过拟合）。
RL **适合**做超参数调优和策略选择：

| 应用 | 状态 | 动作 | 奖励 | 可行性 |
|------|------|------|------|--------|
| Vol Target 阈值调优 | (VIX, RV, regime) | target_vol ∈ {0.12, 0.14, 0.16, 0.18, 0.20} | risk-adjusted return | ★★★ |
| Rebalance 频率 | (组合偏离度, 交易成本) | rebalance or skip | net return | ★★☆ |
| 策略权重分配 | (多策略收益特征) | 策略间资金分配 | portfolio Sharpe | ★★☆ |
| 直接交易信号 | (全市场状态) | buy/sell/hold | P&L | ★☆☆ 不推荐 |

### 4.2 推荐框架

```python
# 使用 Stable-Baselines3 做 Vol Target 优化
# 环境定义
import gymnasium as gym

class VolTargetEnv(gym.Env):
    """
    State: [vix, rv_5d, rv_22d, regime_prob_0, regime_prob_1, regime_prob_2,
            current_leverage, portfolio_return_5d]
    Action: target_vol ∈ [0.10, 0.25] (连续动作)
    Reward: daily_return - 0.5 * daily_return² (风险调整收益)
    """

    def __init__(self, returns, features):
        self.returns = returns
        self.features = features
        self.current_step = 0

        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(8,)
        )
        self.action_space = gym.spaces.Box(
            low=0.10, high=0.25, shape=(1,)
        )

    def step(self, action):
        target_vol = action[0]
        # 计算杠杆
        rv = self.features.iloc[self.current_step]["rv_5d"]
        leverage = min(target_vol / (rv * np.sqrt(252)), 3.0)

        # 计算当日收益
        daily_return = self.returns.iloc[self.current_step] * leverage

        # 风险调整奖励 (惩罚波动)
        reward = daily_return - 0.5 * daily_return ** 2

        self.current_step += 1
        done = self.current_step >= len(self.returns)

        obs = self._get_obs()
        return obs, reward, done, False, {}
```

### 4.3 RL 的风险与注意事项

| 风险 | 原因 | 应对 |
|------|------|------|
| **严重过拟合** | 金融数据信噪比极低 | Walk-forward, 限制动作空间 |
| **Reward hacking** | Agent 找到奖励函数漏洞 | 多维度奖励 (return + Sharpe + DD) |
| **非平稳性** | 市场结构变化 | 短窗口训练 + 频繁重训练 |
| **sim-to-real gap** | 回测不包含滑点/流动性 | 保守滑点假设 + paper trading 验证 |

**建议：RL 作为探索性研究，不作为核心策略。任何 RL 输出都必须有规则安全网兜底。**

---

## 5. 执行计划

| 周 | 任务 | 输出 | 依赖 |
|----|------|------|------|
| 1 | HAR-RV 基线模型 | RV 预测模块 + R² 评估 | 无 |
| 2 | HAR-RV + XGBoost 增强 + Vol Target 集成 | SmartRisk Vol Target 升级 | 周 1 |
| 3 | HMM 3 状态模型训练 + walk-forward 验证 | Regime 检测模块 | 无 |
| 4 | HMM 集成到 SmartRisk + A/B 测试 | SmartRisk V2 回测 | 周 2-3 |
| 5-6 | (可选) RL Vol Target 调优探索 | 实验报告 | 周 1-4 |

---

## 6. 权威资料与参考文献

### 6.1 Realized Volatility 预测（必读）

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"A Simple Approximate Long-Memory Model of Realized Volatility"** | Corsi (2009) | HAR-RV 原始论文，极简但有效的多尺度 RV 模型 | ★★☆ |
| **"Forecasting Realized Volatility: A Review"** | Bucci (2017) | RV 预测方法综述，对比 GARCH/HAR/ML | ★★★ |
| **"Volatility Forecasting with Machine Learning and Intraday Commonality"** | Christensen, Siggaard & Veliyev (2023) | ML 增强 RV 预测，XGBoost 表现最佳 | ★★★ |
| **"Forecasting Financial Market Volatility"** | Poon & Granger (2003) | 波动率预测方法全面综述（93 篇论文 meta-analysis） | ★★★ |
| **"Realized Volatility and Variance: Options via Swaps"** | Carr & Wu (2009) | RV vs IV 的关系，VRP 的度量方法 | ★★★ |
| **"Volatility Trading"** | Euan Sinclair (2013) | 波动率交易实战指南，含 RV 预测与交易策略 | ★★☆ |

### 6.2 Regime 检测（必读）

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"A New Approach to Markov-Switching GARCH Models"** | Haas, Mittnik & Paolella (2004) | MS-GARCH：在 GARCH 框架中加入 regime 切换 | ★★★ |
| **"Regime Changes and Financial Markets"** | Ang & Timmermann (2012) | Regime 变化对资产配置的影响 (Annual Review of Financial Economics) | ★★★ |
| **"Machine Learning for Financial Market Prediction"** | — | HMM 在金融中的应用综述 | ★★☆ |
| **hmmlearn 官方文档** | scikit-learn 项目 | Python HMM 实现参考 | ★☆☆ |

### 6.3 强化学习 + 金融

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"Deep Reinforcement Learning for Trading"** | Zhang et al. (2020) | DRL 在交易中的综述，含仓位管理 | ★★★ |
| **"FinRL: A Deep Reinforcement Learning Library for Automated Stock Trading"** | Liu et al. (2020) | FinRL 框架论文，标准化的 RL 金融交易环境 | ★★☆ |
| **"An Application of Deep Reinforcement Learning to Algorithmic Trading"** | Théate & Ernst (2021) | DRL 做算法交易的实证研究，含 walk-forward | ★★★ |
| **Stable-Baselines3 文档** | DLR-RM | 最常用的 RL 库，PPO/SAC/TD3 实现 | ★★☆ |
| **"Advances in Financial Machine Learning"** | Lopez de Prado (2018) | 第 10 章：回测中避免过拟合的方法论 | ★★★ |

### 6.4 综合参考 & 工具

| 资源 | 类型 | 内容 |
|------|------|------|
| **ARCH** (bashtage/arch) | 开源库 | GARCH/EGARCH/HAR-RV Python 实现 |
| **hmmlearn** (hmmlearn/hmmlearn) | 开源库 | Gaussian HMM Python 实现 |
| **Stable-Baselines3** (DLR-RM/stable-baselines3) | 开源库 | PPO/SAC/TD3 强化学习框架 |
| **FinRL** (AI4Finance-Foundation/FinRL) | 开源框架 | 金融 RL 一体化环境 |
| **XGBoost** (dmlc/xgboost) | 开源库 | 梯度提升树，RV 预测主力模型 |
| **Ernest Chan — "Machine Trading"** (2017) | 书 | ML 在交易中的实战，含 regime 检测和 vol 预测 |
