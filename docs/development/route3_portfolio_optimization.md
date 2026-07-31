# 路线 3：Portfolio 组合优化

> 目标：从单标的（SPY）升级为多标的低相关性组合，提升 Sharpe、降低回撤。
> 前置依赖：路线 1（选股）提供候选标的池。
> 预期：Sharpe 从 1.82 → 2.0-2.3，最大回撤从 18.4% → 12-16%。

---

## 1. 整体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Portfolio Optimization Pipeline                    │
│                                                                      │
│  路线1 选股                                                           │
│  top_N = [(AAPL, 85), (MSFT, 82), (NVDA, 78), ...]                 │
│       │                                                              │
│       ▼                                                              │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │ 阶段 1   │──▶│ 阶段 2       │──▶│ 阶段 3       │                │
│  │ 风险平价 │   │ HRP 分层配仓 │   │ Regime 动态  │                │
│  └──────────┘   └──────────────┘   └──────────────┘                │
│  等风险贡献     协方差聚类分配     根据市场状态                       │
│  σ-倒数加权     无需矩阵求逆       调整因子倾斜                      │
│                                                                      │
│  输出: {symbol: weight} → LEAPS SmartRisk 分仓执行                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. 阶段 1：风险平价（Risk Parity）基础版（周 1-2）

### 2.1 原理

等权配置的问题：如果 NVDA 波动率是 KO 的 3 倍，等权意味着 NVDA 贡献了组合 75% 的风险。
风险平价：让每个标的对组合风险的贡献相等。

### 2.2 实现方式

**Inverse Volatility Weighting（最简单的风险平价）**

```python
# 每月 rebalance
def inverse_vol_weights(symbols: list[str], lookback: int = 63) -> dict[str, float]:
    """63 个交易日 (~3 个月) 的历史波动率倒数加权"""
    vols = {}
    for sym in symbols:
        returns = get_daily_returns(sym, lookback)
        vols[sym] = returns.std() * np.sqrt(252)  # 年化波动率

    inv_vols = {sym: 1.0 / vol for sym, vol in vols.items()}
    total = sum(inv_vols.values())
    weights = {sym: iv / total for sym, iv in inv_vols.items()}
    return weights

# 示例输出:
# AAPL (vol=28%): weight=14%
# NVDA (vol=52%): weight=8%
# KO   (vol=16%): weight=25%
# JNJ  (vol=14%): weight=28%
# SPY  (vol=18%): weight=22%
```

### 2.3 约束条件

```python
constraints = {
    "max_single_weight": 0.20,      # 单标的上限 20%
    "max_sector_weight": 0.35,      # 单行业上限 35%
    "min_weight": 0.03,             # 低于 3% 不持仓（交易成本不划算）
    "max_positions": 12,            # LEAPS 流动性限制
    "min_positions": 5,             # 最低分散化要求
}
```

### 2.4 评估指标

| 指标 | 计算 | 目标 |
|------|------|------|
| HHI (集中度) | Σ(w_i²) | < 0.15 (分散) |
| 有效标的数 | 1/HHI | > 6 |
| 最大权重 | max(w_i) | < 20% |
| 各标的风险贡献 | w_i × σ_i × corr_i / σ_p | 均匀分布 |

---

## 3. 阶段 2：HRP 分层风险平价（周 3-4）

### 3.1 为什么用 HRP 而不是 Markowitz

| | Markowitz (均值方差) | HRP |
|---|---|---|
| 需要收益预测 | 是（对误差极敏感） | 否 |
| 需要协方差逆矩阵 | 是（不稳定） | 否 |
| 样本外表现 | 差（过拟合） | 好 |
| 处理高相关资产 | 差（权重爆炸） | 好（聚类分组） |
| 实现复杂度 | 中 | 中 |

### 3.2 HRP 算法流程

```
输入: 收益率矩阵 R (T × N), T=交易日, N=标的数

Step 1: 计算距离矩阵
  d(i,j) = sqrt(0.5 × (1 - corr(i,j)))

Step 2: 层次聚类 (Single Linkage)
  用 scipy.cluster.hierarchy.linkage(d, method='single')
  → 生成树状图 (dendrogram)

Step 3: 准对角化 (Quasi-Diagonalization)
  重排协方差矩阵，使相关资产相邻
  → 高相关的 (AAPL, MSFT) 排在一起
  → 低相关的 (AAPL, GLD) 分开

Step 4: 递归二分配仓
  从根节点开始：
  - 左子树风险 σ_L, 右子树风险 σ_R
  - 左子树权重 = σ_R / (σ_L + σ_R)   # 低风险的分多一点
  - 右子树权重 = σ_L / (σ_L + σ_R)
  - 递归到叶子节点

输出: 每个标的的权重 w_i
```

### 3.3 代码实现参考

```python
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform

class HRPOptimizer:
    """Hierarchical Risk Parity — Lopez de Prado (2016)"""

    def optimize(self, returns: pd.DataFrame) -> dict[str, float]:
        cov = returns.cov()
        corr = returns.corr()

        # Step 1: 距离矩阵
        dist = np.sqrt(0.5 * (1 - corr))
        dist_condensed = squareform(dist.values)

        # Step 2: 层次聚类
        link = linkage(dist_condensed, method='single')

        # Step 3: 准对角化
        sorted_idx = leaves_list(link).tolist()
        sorted_symbols = [returns.columns[i] for i in sorted_idx]

        # Step 4: 递归二分
        weights = self._recursive_bisection(
            cov, sorted_symbols
        )
        return weights

    def _recursive_bisection(self, cov, symbols):
        if len(symbols) == 1:
            return {symbols[0]: 1.0}

        mid = len(symbols) // 2
        left = symbols[:mid]
        right = symbols[mid:]

        var_left = self._cluster_var(cov, left)
        var_right = self._cluster_var(cov, right)

        alpha = var_right / (var_left + var_right)  # 低风险多配

        w_left = self._recursive_bisection(cov, left)
        w_right = self._recursive_bisection(cov, right)

        weights = {}
        for s, w in w_left.items():
            weights[s] = w * alpha
        for s, w in w_right.items():
            weights[s] = w * (1 - alpha)
        return weights

    def _cluster_var(self, cov, symbols):
        """子集的逆方差加权组合方差"""
        sub_cov = cov.loc[symbols, symbols]
        inv_diag = 1.0 / np.diag(sub_cov.values)
        inv_diag /= inv_diag.sum()
        return float(inv_diag @ sub_cov.values @ inv_diag)
```

### 3.4 HRP vs 简单风险平价的预期差异

| 场景 | Inverse Vol | HRP |
|------|-------------|-----|
| 所有标的低相关 | 差不多 | 差不多 |
| 科技股集群 (AAPL/MSFT/GOOG 高相关) | 合计配 40%+ | 聚类后整体降权 |
| 加入防御性标的 (JNJ/KO) | 按波动率配 | 低相关 → 加权更多 |
| **结果** | Sharpe +0.1 | **Sharpe +0.2-0.4** |

---

## 4. 阶段 3：Regime 感知的动态配置（周 5-6，可选）

### 4.1 核心思路

不同 regime 下因子表现差异巨大：

| Regime | 表现好的因子 | 表现差的因子 |
|--------|------------|------------|
| Bull (低波牛市) | 动量、成长 | 价值、低波 |
| Bear (熊市) | 质量、低波 | 动量、小盘 |
| Crisis (危机) | 低波、现金 | 全部权益 |
| Recovery (复苏) | 价值、小盘 | 防御、债券 |

### 4.2 实现方式

```python
def adjust_weights_for_regime(
    base_weights: dict[str, float],
    factor_scores: dict[str, dict[str, float]],  # {symbol: {factor: score}}
    regime: str,  # 来自 SmartRisk 的 regime 识别
) -> dict[str, float]:
    """根据 regime 倾斜权重"""

    regime_factor_preference = {
        "bull":     {"momentum": 1.3, "quality": 1.0, "value": 0.8, "low_vol": 0.7},
        "bear":     {"momentum": 0.6, "quality": 1.3, "value": 1.0, "low_vol": 1.4},
        "crisis":   {"momentum": 0.3, "quality": 1.2, "value": 0.8, "low_vol": 1.5},
        "recovery": {"momentum": 1.0, "quality": 0.9, "value": 1.4, "low_vol": 0.8},
    }

    prefs = regime_factor_preference[regime]

    adjusted = {}
    for sym, base_w in base_weights.items():
        # 用因子偏好加权调整
        factor_tilt = sum(
            factor_scores[sym].get(f, 0) * pref
            for f, pref in prefs.items()
        ) / sum(prefs.values())

        adjusted[sym] = base_w * (0.7 + 0.3 * factor_tilt)  # 70% 基础 + 30% 倾斜

    # 归一化
    total = sum(adjusted.values())
    return {s: w / total for s, w in adjusted.items()}
```

### 4.3 风险控制约束

```python
# Regime 动态调整的安全边界
regime_constraints = {
    # regime 调整后的权重变化不超过基础权重的 ±50%
    "max_tilt_ratio": 1.5,
    "min_tilt_ratio": 0.5,

    # 整体约束不变
    "max_single_weight": 0.20,
    "max_sector_weight": 0.35,

    # 换手控制：regime 切换不触发大规模 rebalance
    "max_monthly_turnover": 0.30,  # 单月换手不超过 30%
}
```

---

## 5. 与现有系统的集成

### 5.1 接口设计

```python
# src/portfolio/optimizer.py
class PortfolioOptimizer:
    """组合优化器，接收选股结果，输出仓位分配"""

    def __init__(self, method: str = "hrp", constraints: dict = None):
        self.method = method  # "equal", "inverse_vol", "hrp"
        self.constraints = constraints or DEFAULT_CONSTRAINTS

    def optimize(
        self,
        candidates: list[StockSignal],     # 路线1 选股输出
        returns: pd.DataFrame,              # 历史收益率矩阵
        regime: str = "normal",             # SmartRisk regime
    ) -> dict[str, float]:
        """返回 {symbol: target_weight}"""
        ...

# 在 BacktestExecutor 中集成
class BacktestExecutor:
    def _run_single_day(self, current_date):
        if self._is_month_start(current_date):
            # 1. 选股
            candidates = self.stock_selector.select(current_date)
            # 2. 配仓
            weights = self.portfolio_optimizer.optimize(
                candidates, self._get_returns_matrix(), self.current_regime
            )
            # 3. 执行 rebalance
            self._rebalance_positions(weights)
```

### 5.2 Rebalance 逻辑

```
月度 Rebalance 流程:
1. 计算当前持仓权重 vs 目标权重
2. 差异 > 5% 的标的才调整（避免频繁交易）
3. 先关闭需要减仓的 LEAPS
4. 再开仓需要增仓的 LEAPS
5. 记录 rebalance 交易成本
```

### 5.3 回测验证

| 测试 | 方法 | 预期 |
|------|------|------|
| 等权 vs 风险平价 vs HRP | 3 种配仓方法对比 | HRP Sharpe 最高 |
| 不同 rebalance 频率 | 周/月/季度 | 月度最优（换手 vs 时效平衡） |
| 有/无 regime 倾斜 | A/B 测试 | 倾斜在 bear 市提升显著 |
| 交易成本敏感性 | 不同滑点/佣金假设 | 月换手 < 25% 时净收益正 |

---

## 6. 权威资料与参考文献

### 6.1 Portfolio 理论（必读）

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"Building Diversified Portfolios that Outperform Out of Sample"** | Lopez de Prado (2016) | HRP 原始论文，证明 HRP 样本外优于 Markowitz | ★★★ |
| **"Risk Parity Fundamentals"** | Edward Qian (2016) | 风险平价的完整理论与实践 | ★★★ |
| **"A Robust Estimator for the Tail Index of Pareto-type Distributions"** | — | 协方差矩阵收缩估计（Ledoit-Wolf），改善 Markowitz 输入 | ★★★ |
| **"Active Portfolio Management"** | Grinold & Kahn (2000) | 主动管理的圣经：IC、IR、Alpha 转化公式 | ★★★ |
| **"Risk-Based and Factor Investing"** | Roncalli (2017) | 风险平价 + 因子投资的结合框架 | ★★★ |

### 6.2 动态配置

| 资料 | 作者 | 核心内容 | 难度 |
|------|------|---------|------|
| **"Adaptive Asset Allocation"** | Butler, Philbrick & Gordillo (2012) | 动量 + 风险平价 + regime 的自适应配置 | ★★☆ |
| **"Momentum Crashes"** | Daniel & Moskowitz (2016) | 动量策略在 regime 切换时的崩溃风险与对冲 | ★★★ |
| **"Regime Changes and Financial Markets"** | Ang & Timmermann (2012) | regime 变化对资产配置的影响 | ★★★ |

### 6.3 实战工具 & 开源

| 资源 | 类型 | 内容 |
|------|------|------|
| **PyPortfolioOpt** (robertmartin8/PyPortfolioOpt) | 开源库 | HRP, 均值方差, Black-Litterman 实现 |
| **Riskfolio-Lib** (dcajasn/Riskfolio-Lib) | 开源库 | 风险平价、HRP、因子风险模型 |
| **QuantStats** (ranaroussi/quantstats) | 开源库 | 组合绩效分析、报告生成 |
| **empyrical** (quantopian/empyrical) | 开源库 | 金融绩效指标计算 |
