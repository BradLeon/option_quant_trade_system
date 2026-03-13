"""LEAPS Contract Selector — 回测/实盘双路径合约筛选。

回测路径: 合成数据有完美报价，使用 DTE/moneyness 偏差评分。
实盘路径: IBKR 真实期权链，使用 Delta + 流动性 + Spread 多因子评分。

Usage:
    from src.strategy.leaps_selector import LeapsContractSelector, LeapsSelectionConfig

    selector = LeapsContractSelector()
    best = selector.select(
        symbol="QQQ", spot=598.0, current_date=date.today(),
        data_provider=ibkr_provider,
        config=LeapsSelectionConfig(),
        log_fn=strategy.log,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional


@dataclass
class LeapsSelectionConfig:
    """LEAPS 合约筛选参数。"""

    # DTE
    target_dte: int = 252
    min_dte: int = 180
    max_dte: int = 400

    # Delta 目标 (实盘优先)
    target_delta: float = 0.70
    min_delta: float = 0.50
    max_delta: float = 0.85

    # Moneyness 降级 (回测合成数据用)
    target_moneyness: float = 0.85

    # 流动性硬过滤
    min_open_interest: int = 100
    max_bid_ask_spread: float = 0.08  # 8%

    # 评分权重
    w_delta: float = 3.0
    w_liquidity: float = 2.0
    w_spread: float = 1.5
    w_dte: float = 0.5

    # 预筛数量
    max_candidates: int = 30


# Backtest fallback scoring weights (legacy)
_W_DTE = 1.0
_W_STRIKE = 2.0


class LeapsContractSelector:
    """LEAPS 合约选择器。

    三步筛选流程:
    1. 预筛: get_option_chain() → DTE 范围 + strike 接近度 → top N 候选
    2. 获取报价: get_option_quotes_batch() (仅实盘)
    3. 硬过滤 + 多因子评分: delta/OI/spread → 加权评分 → 最优合约
    """

    def select(
        self,
        symbol: str,
        spot: float,
        current_date: date,
        data_provider: Any,
        config: LeapsSelectionConfig,
        log_fn: Optional[Callable[..., None]] = None,
    ) -> Any:
        """选择最优 LEAPS Call 合约。

        Returns:
            OptionQuote or None
        """
        target_strike = spot * config.target_moneyness

        # ── Step 1: Get chain + pre-filter ──
        chain = data_provider.get_option_chain(
            underlying=symbol,
            expiry_min_days=config.min_dte,
            expiry_max_days=config.max_dte,
        )
        if not chain or not chain.calls:
            if log_fn:
                log_fn(f"option_chain:{symbol}", "fail",
                       reason="无CALL合约",
                       dte_range=f"[{config.min_dte}-{config.max_dte}]")
            return None

        total = len(chain.calls)
        prefiltered = []
        reject_dte = 0
        for call in chain.calls:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days
            if dte < config.min_dte or dte > config.max_dte:
                reject_dte += 1
                continue
            prefiltered.append(call)

        # Narrow by strike proximity
        prefiltered.sort(key=lambda c: abs(c.contract.strike_price - target_strike))
        shortlisted = prefiltered[:config.max_candidates]

        if not shortlisted:
            if log_fn:
                log_fn(f"contract_select:{symbol}", "fail",
                       total=total, passed=0,
                       rejected_by={"dte": reject_dte},
                       filters=f"DTE=[{config.min_dte}-{config.max_dte}] target_K={target_strike:.0f}")
            return None

        # ── Step 2: Fetch quotes (live path) or use as-is (backtest) ──
        is_live = hasattr(data_provider, 'get_option_quotes_batch')
        if is_live:
            contracts_to_fetch = [c.contract for c in shortlisted]
            quotes = data_provider.get_option_quotes_batch(
                contracts_to_fetch, min_volume=0,
            )
            if log_fn:
                log_fn(f"option_quotes:{symbol}", "info",
                       prefiltered=len(prefiltered),
                       shortlisted=len(shortlisted),
                       quotes_returned=len(quotes))
        else:
            quotes = shortlisted

        # ── Step 3: Filter + Score ──
        if is_live:
            return self._select_live(
                symbol, spot, current_date, quotes, config, log_fn,
                total=total, reject_dte=reject_dte,
            )
        else:
            return self._select_backtest(
                symbol, spot, current_date, quotes, config, log_fn,
                total=total, reject_dte=reject_dte,
            )

    def _select_live(
        self,
        symbol: str,
        spot: float,
        current_date: date,
        quotes: list[Any],
        config: LeapsSelectionConfig,
        log_fn: Optional[Callable[..., None]],
        total: int = 0,
        reject_dte: int = 0,
    ) -> Any:
        """实盘路径: Delta + 流动性 + Spread 多因子评分。"""
        from src.engine.contract.liquidity import (
            calc_bid_ask_spread_ratio,
            liquidity_score,
        )

        best = None
        best_score = -float("inf")
        reject = {"no_price": 0, "no_delta": 0, "delta_range": 0, "low_oi": 0, "wide_spread": 0}
        candidates: list[dict[str, Any]] = []

        for call in quotes:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days

            # Price check
            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if not mid or mid <= 0:
                reject["no_price"] += 1
                continue

            # Delta check
            delta = call.greeks.delta if call.greeks else None
            if not delta or delta <= 0:
                reject["no_delta"] += 1
                continue

            # Hard filter: delta range
            if delta < config.min_delta or delta > config.max_delta:
                reject["delta_range"] += 1
                continue

            # Hard filter: OI
            oi = call.open_interest or 0
            if oi < config.min_open_interest:
                reject["low_oi"] += 1
                continue

            # Hard filter: bid-ask spread
            spread_ratio = calc_bid_ask_spread_ratio(call.bid, call.ask)
            if spread_ratio is not None and spread_ratio > config.max_bid_ask_spread:
                reject["wide_spread"] += 1
                continue

            # ── Multi-factor scoring ──
            delta_range = config.max_delta - config.min_delta
            delta_score = 1.0 - abs(delta - config.target_delta) / delta_range if delta_range > 0 else 0.5

            liq = liquidity_score(call.bid, call.ask, oi, call.volume) / 100.0

            spread_score = 0.0
            if spread_ratio is not None and config.max_bid_ask_spread > 0:
                spread_score = max(0, 1.0 - spread_ratio / config.max_bid_ask_spread)

            dte_score = 1.0 - abs(dte - config.target_dte) / config.target_dte if config.target_dte > 0 else 0.5

            score = (
                config.w_delta * delta_score
                + config.w_liquidity * liq
                + config.w_spread * spread_score
                + config.w_dte * dte_score
            )

            candidates.append({
                "strike": contract.strike_price, "dte": dte,
                "delta": delta, "oi": oi,
                "spread": f"{spread_ratio:.1%}" if spread_ratio else "N/A",
                "score": score,
            })

            if score > best_score:
                best_score = score
                best = call

        # Log results
        if log_fn:
            if best:
                bc = best.contract
                bd = best.greeks.delta if best.greeks else 0
                b_mid = best.last_price
                if best.bid is not None and best.ask is not None and best.ask > 0:
                    b_mid = (best.bid + best.ask) / 2
                b_spread = calc_bid_ask_spread_ratio(best.bid, best.ask)

                # Show top 3 candidates
                top3 = sorted(candidates, key=lambda c: c["score"], reverse=True)[:3]

                log_fn(f"contract_select:{symbol}", "pass",
                       total=total, passed=len(candidates),
                       strike=bc.strike_price,
                       dte=(bc.expiry_date - current_date).days,
                       delta=round(bd, 3),
                       oi=best.open_interest or 0,
                       spread=f"{b_spread:.1%}" if b_spread else "N/A",
                       mid=round(b_mid, 2) if b_mid else 0,
                       score=round(best_score, 2),
                       top3=top3,
                       rejected_by={k: v for k, v in reject.items() if v > 0})
            else:
                log_fn(f"contract_select:{symbol}", "fail",
                       total=total, passed=0,
                       rejected_by={"dte": reject_dte, **{k: v for k, v in reject.items() if v > 0}},
                       filters=f"DTE=[{config.min_dte}-{config.max_dte}] delta=[{config.min_delta}-{config.max_delta}] min_oi={config.min_open_interest}")

        return best

    def _select_backtest(
        self,
        symbol: str,
        spot: float,
        current_date: date,
        quotes: list[Any],
        config: LeapsSelectionConfig,
        log_fn: Optional[Callable[..., None]],
        total: int = 0,
        reject_dte: int = 0,
    ) -> Any:
        """回测路径: DTE/moneyness 偏差评分 (向后兼容)。"""
        target_strike = spot * config.target_moneyness

        best = None
        best_score = -float("inf")
        reject = {"no_price": 0, "no_delta": 0}

        for call in quotes:
            contract = call.contract
            dte = (contract.expiry_date - current_date).days

            mid = call.last_price
            if call.bid is not None and call.ask is not None and call.ask > 0:
                mid = (call.bid + call.ask) / 2
            if not mid or mid <= 0:
                reject["no_price"] += 1
                continue

            delta = call.greeks.delta if call.greeks else None
            if not delta or delta <= 0:
                reject["no_delta"] += 1
                continue

            dte_dev = abs(dte - config.target_dte) / config.target_dte if config.target_dte > 0 else 0
            strike_dev = abs(contract.strike_price - target_strike) / target_strike if target_strike > 0 else 0
            score = -_W_DTE * dte_dev - _W_STRIKE * strike_dev

            if score > best_score:
                best_score = score
                best = call

        if log_fn:
            if best:
                bc = best.contract
                log_fn(f"contract_select:{symbol}", "pass",
                       total=total, passed=1,
                       strike=bc.strike_price,
                       dte=(bc.expiry_date - current_date).days,
                       delta=best.greeks.delta if best.greeks else 0,
                       mid=best.last_price,
                       rejected_by={k: v for k, v in reject.items() if v > 0})
            else:
                log_fn(f"contract_select:{symbol}", "fail",
                       total=total, passed=0,
                       rejected_by={"dte": reject_dte, **{k: v for k, v in reject.items() if v > 0}},
                       filters=f"DTE=[{config.min_dte}-{config.max_dte}] target_K={target_strike:.0f}")

        return best
