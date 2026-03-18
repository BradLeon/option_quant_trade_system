"""LEAPS + Short Put Overlay V3 — 动量 LEAPS 买方 + 卖 Put Spread 闲置现金增强

在 momentum_mixed_v2 (LEAPS-only + Theta/Vega Guard) 的基础上，
用 Bull Put Spread 替代 Cash Sweep (SHV/SGOV ETF) 来提升闲置现金收益。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、策略架构 — 组合模式 (Composition)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  LeapsShortPutV3Strategy
    ├── MomentumMixedV2Strategy  (主策略, 代理调用)
    │     ├── MomentumVolTargetComputer (7分动量 + 波动率目标)
    │     ├── LeapsContractSelector     (delta 驱动合约选择)
    │     ├── Theta Guard               (DTE≤90 提前 roll)
    │     └── Vega Guard                (VIX 飙升减仓 50%)
    └── ShortPutOverlay          (叠加层, 独立调用)
          ├── Bull Put Spread 合约选择 (delta 0.20, DTE 30-45)
          ├── VIX 分级缩仓 (25→半仓, 30→1/4仓, 35→停开)
          └── VIX Spike Guard (20%涨幅 → 全平 + 5天冷却)

不继承 V2，而是组合: 两个子模块完全独立，各自维护状态。
主策略通过 self._leaps.generate_signals() 获取 LEAPS 信号，
叠加层通过 self._overlay.compute_exits/entries() 获取 overlay 信号。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、信号流程
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每日 generate_signals() 执行:
  1. leaps_signals = self._leaps.generate_signals(...)
       → V2 内部完成: momentum 计算 → 出场检查 → 入场检查
  2. momentum_score = self._leaps._momentum.compute(...)["momentum_score"]
       → 复用 V2 的动量评分结果 (有缓存, 不重复计算)
  3. overlay_exits  = self._overlay.compute_exit_signals(...)
       → 检查 VIX spike / momentum=0 / 止盈 / DTE退出
  4. overlay_entries = self._overlay.compute_entry_signals(...)
       → 仅在 LEAPS 非全退出时执行 (momentum>0 且有活跃 LEAPS)
  5. 合并排序:

     LEAPS EXIT (P10/P8/P5) → Overlay EXIT (P9/P8/P5)
       → LEAPS ENTRY (P0)    → Overlay ENTRY (P-1)

  信号优先级确保: 先退出释放资金/保证金 → 主策略优先入场 → overlay 用剩余保证金

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、主策略 — MomentumMixedV2 (LEAPS-only 模式)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

与 momentum_mixed_v2.py 完全相同，详见该文件注释。关键参数:
  - use_stock_component = False  (纯 LEAPS，不买正股)
  - cash_interest_enabled = False (不用被动利息，overlay 替代)
  - 信号系统: 7分动量 + vol target → target_pct (0~3.0x)
  - 合约: delta=0.70, DTE≈252, LEAPS Call
  - 出场: momentum=0 全清, DTE≤90 roll, VIX spike 减仓 50%
  - 再平衡: |target-current| > 25% 且冷却 ≥ 5天

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、叠加层 — ShortPutOverlay (Bull Put Spread)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

详见 src/strategy/overlay/short_put_overlay.py 注释。关键参数:
  - 合约: short put delta=0.20, spread_width=$5, DTE 30-45
  - 仓位: max_spreads=10, max_margin_pct=50%, min_cash_reserve=10% NLV
  - 门控: momentum>0, 有LEAPS仓位, VIX<35, 无冷却期
  - 止盈: 50% max profit
  - 风控: VIX spike 全平 + 5天冷却

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
五、与 V2 的对比
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────┬──────────────────┬──────────────────────────┐
│ 维度             │ V2 (passive)     │ V3 (short put overlay)   │
├──────────────────┼──────────────────┼──────────────────────────┤
│ 闲置现金收益     │ ^TNX 利率 ~4.5%  │ Bull Put Spread 权利金   │
│ 风险             │ 无               │ 定义风险 (spread width)  │
│ 额外交易         │ 无               │ 每月多次开平仓           │
│ VIX 敏感度       │ 无               │ VIX 缩仓 + spike guard   │
│ 与主策略联动     │ 无               │ momentum=0 时同步退出    │
│ 保证金占用       │ 无               │ 最多 50% 闲置资金        │
│ 现金利息         │ 每日自动计入     │ 不计入 (overlay 替代)    │
└──────────────────┴──────────────────┴──────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
六、使用方式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLI:
  uv run backtest run -n "V3" -s 2015-01-01 -e 2025-12-31 -S SPY \\
    --strategy-version leaps_short_put_v3 --skip-download

Registry 名称:
  "leaps_short_put_v3" 或 "leaps_v3"

Python API:
  from src.strategy.versions.leaps_short_put_v3 import (
      LeapsShortPutV3Strategy, LeapsShortPutV3Config,
  )
  from src.strategy.overlay.short_put_overlay import ShortPutOverlayConfig

  config = LeapsShortPutV3Config(
      overlay=ShortPutOverlayConfig(
          max_spreads=5,            # 保守: 最多 5 组 spread
          max_margin_pct=0.30,      # 保守: 仅用 30% 闲置资金
          spread_width=10.0,        # 更宽 spread, 更高 credit
      ),
  )
  strategy = LeapsShortPutV3Strategy(config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.strategy.models import (
    MarketSnapshot,
    OptionRight,
    PortfolioState,
    Signal,
    SignalType,
)
from src.strategy.overlay.short_put_overlay import ShortPutOverlay, ShortPutOverlayConfig
from src.strategy.protocol import BacktestStrategy
from src.strategy.versions.momentum_mixed_v2 import (
    MomentumMixedV2Config,
    MomentumMixedV2Strategy,
)

logger = logging.getLogger(__name__)


@dataclass
class LeapsShortPutV3Config:
    """Configuration for LEAPS + Short Put Overlay V3 strategy."""

    name: str = "leaps_short_put_v3"

    # Primary strategy config (LEAPS-only, no cash sweep)
    leaps: MomentumMixedV2Config = field(default_factory=lambda: MomentumMixedV2Config(
        name="leaps_short_put_v3_leaps",
        use_stock_component=False,
        cash_interest_enabled=False,
    ))

    # Overlay config
    overlay: ShortPutOverlayConfig = field(default_factory=ShortPutOverlayConfig)


class LeapsShortPutV3Strategy(BacktestStrategy):
    """LEAPS momentum + short put spread overlay on idle cash.

    Composes MomentumMixedV2Strategy (for LEAPS signals) with
    ShortPutOverlay (for bull put spread income on idle margin).
    """

    def __init__(self, config: LeapsShortPutV3Config | None = None) -> None:
        super().__init__()
        self._config = config or LeapsShortPutV3Config()

        # Compose: primary LEAPS strategy + overlay
        self._leaps = MomentumMixedV2Strategy(self._config.leaps)
        self._overlay = ShortPutOverlay(self._config.overlay)
        self._overlay._log_fn = self.log

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def requires_synthetic_data(self) -> bool:
        return True

    def generate_signals(
        self, market: MarketSnapshot, portfolio: PortfolioState, data_provider: Any
    ) -> list[Signal]:
        """Generate combined LEAPS + overlay signals."""
        # Manage own base-class state
        self._execution_log.clear()
        self._trading_day_count += 1

        # 1. Get LEAPS signals (exits + entries) — LEAPS manages its own state
        leaps_signals = self._leaps.generate_signals(market, portfolio, data_provider)

        # 2. Get momentum context from the LEAPS strategy
        momentum_result = self._leaps._momentum.compute(market, data_provider)
        momentum_score = momentum_result.get("momentum_score", 0)
        vix = momentum_result.get("vix", 20.0)

        # 3. Check if LEAPS positions exist
        has_leaps = any(
            p for p in portfolio.get_option_positions()
            if p.instrument.right == OptionRight.CALL and p.quantity > 0
        )

        # 4. Overlay exits
        overlay_exits = self._overlay.compute_exit_signals(
            market, portfolio, momentum_score, vix,
        )

        # 5. Overlay entries (only if not exiting everything)
        overlay_entries: list[Signal] = []
        leaps_exiting_all = (
            momentum_score == 0
            or (len(leaps_signals) > 0
                and all(s.type == SignalType.EXIT for s in leaps_signals))
        )
        if not leaps_exiting_all:
            overlay_entries = self._overlay.compute_entry_signals(
                market, portfolio, data_provider,
                momentum_score, vix, has_leaps,
            )

        # 6. Merge with priority ordering:
        #    LEAPS exits → Overlay exits → LEAPS entries → Overlay entries
        leaps_exits = [s for s in leaps_signals if s.type == SignalType.EXIT]
        leaps_entries = [s for s in leaps_signals if s.type != SignalType.EXIT]

        combined = leaps_exits + overlay_exits + leaps_entries + overlay_entries

        if overlay_exits or overlay_entries:
            self.log("overlay:summary", "info",
                     overlay_exits=len(overlay_exits),
                     overlay_entries=len(overlay_entries),
                     momentum_score=momentum_score,
                     vix=vix,
                     has_leaps=has_leaps)

        # Merge execution logs
        self._execution_log.extend(self._leaps._execution_log)

        return combined

    def _compute_daily_interest(
        self, cash: float, current_date: Any, data_provider: Any
    ) -> float:
        """No passive interest — income comes from overlay spreads."""
        return 0.0

    def on_day_end(
        self,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        data_provider: Any,
    ) -> dict:
        """Forward signal detail from LEAPS strategy."""
        return dict(self._leaps._last_signal_detail)
