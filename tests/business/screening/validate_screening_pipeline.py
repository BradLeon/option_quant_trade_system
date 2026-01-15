#!/usr/bin/env python3
"""
Screening Pipeline Validation Script - 筛选管道端到端验证

验证完整的三层筛选 pipeline：
1. MarketFilter - 市场环境评估
2. UnderlyingFilter - 标的评估
3. ContractFilter - 合约评估

使用方式:
    python tests/business/screening/validate_screening_pipeline.py --market us --strategy short_put
    python tests/business/screening/validate_screening_pipeline.py --market hk --skip-market-check
    python tests/business/screening/validate_screening_pipeline.py --pool us_default --debug
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.business.config.screening_config import ScreeningConfig
from src.business.screening.filters.contract_filter import ContractFilter
from src.business.screening.filters.market_filter import MarketFilter
from src.business.screening.filters.underlying_filter import UnderlyingFilter
from src.business.screening.models import (
    ContractOpportunity,
    MarketStatus,
    MarketType,
    TrendStatus,
    UnderlyingScore,
)
from src.business.screening.stock_pool import StockPoolManager
from src.data.providers.unified_provider import UnifiedDataProvider


def setup_logging(debug: bool = False) -> None:
    """配置日志"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # 降低第三方库日志级别
    logging.getLogger("ib_async").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def print_header(title: str) -> None:
    """打印分隔标题"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_section(title: str) -> None:
    """打印小节标题"""
    print("\n" + "-" * 50)
    print(f" {title}")
    print("-" * 50)


def trend_to_symbol(trend: TrendStatus) -> str:
    """趋势状态转符号"""
    mapping = {
        TrendStatus.STRONG_BULLISH: "↑↑",
        TrendStatus.BULLISH: "↑",
        TrendStatus.NEUTRAL: "→",
        TrendStatus.BEARISH: "↓",
        TrendStatus.STRONG_BEARISH: "↓↓",
    }
    return mapping.get(trend, "?")


def format_market_status(status: MarketStatus) -> None:
    """格式化输出市场状态"""
    print_section("Layer 1: Market Filter (市场环境评估)")

    # 波动率指数
    if status.volatility_index:
        vi = status.volatility_index
        percentile_str = f", 百分位={vi.percentile:.1%}" if vi.percentile else ""
        print(f"  波动率指数: {vi.symbol}={vi.value:.2f} ({vi.status.value}{percentile_str})")

    # 大盘趋势
    if status.trend_indices:
        print(f"  大盘趋势: {status.overall_trend.value} {trend_to_symbol(status.overall_trend)}")
        for idx in status.trend_indices:
            sma20_rel = ""
            if idx.sma20 and idx.price:
                rel = (idx.price - idx.sma20) / idx.sma20 * 100
                sma20_rel = f" (vs SMA20: {rel:+.1f}%)"
            print(f"    - {idx.symbol}: ${idx.price:.2f}{sma20_rel}")

    # 期限结构
    if status.term_structure:
        ts = status.term_structure
        structure = "Contango" if ts.is_contango else "Backwardation"
        print(f"  期限结构: {structure} (VIX/VIX3M={ts.ratio:.3f})")

    # PCR
    if status.pcr:
        print(f"  PCR: {status.pcr.symbol} = {status.pcr.value:.2f} ({status.pcr.filter_status.value})")

    # 宏观事件
    if status.macro_events:
        me = status.macro_events
        if me.is_in_blackout:
            events = ", ".join(me.event_names) if me.upcoming_events else "未知"
            print(f"  宏观事件: ⚠️ Blackout ({events})")
        else:
            print("  宏观事件: ✓ 无近期重大事件")

    # 总结
    print()
    if status.is_favorable:
        print("  >>> 市场状态: ✅ FAVORABLE (有利)")
    else:
        print("  >>> 市场状态: ❌ UNFAVORABLE (不利)")
        for reason in status.unfavorable_reasons:
            print(f"      - {reason}")


def format_underlying_scores(
    scores: list[UnderlyingScore],
    total_symbols: int,
) -> None:
    """格式化输出标的评分"""
    print_section("Layer 2: Underlying Filter (标的评估)")

    passed = [s for s in scores if s.passed]
    failed = [s for s in scores if not s.passed]

    print(f"  扫描: {total_symbols} 个标的")
    print(f"  通过: {len(passed)} 个 ({len(passed)/total_symbols*100:.1f}%)")
    print(f"  淘汰: {len(failed)} 个")

    # 显示淘汰原因
    if failed:
        print("\n  淘汰标的:")
        for s in failed[:5]:  # 最多显示 5 个
            reasons = ", ".join(s.disqualify_reasons) if s.disqualify_reasons else "未知原因"
            print(f"    - {s.symbol}: {reasons}")
        if len(failed) > 5:
            print(f"    ... 还有 {len(failed)-5} 个")

    # 显示通过的标的（按评分排序）
    if passed:
        print("\n  通过标的 (按评分排序):")
        sorted_passed = sorted(passed, key=lambda x: x.composite_score, reverse=True)
        for i, s in enumerate(sorted_passed[:10], 1):
            iv_rank_str = f"IV Rank={s.iv_rank:.1f}%" if s.iv_rank else "IV Rank=N/A"
            rsi_str = f"RSI={s.technical.rsi:.1f}" if s.technical and s.technical.rsi else "RSI=N/A"
            warnings_str = f" ⚠️ {len(s.warnings)}" if s.warnings else ""
            print(f"    {i}. {s.symbol} (score={s.composite_score:.1f}) - {iv_rank_str}, {rsi_str}{warnings_str}")

            # 显示警告
            if s.warnings:
                for w in s.warnings[:2]:
                    print(f"       └─ {w}")


def format_contract_opportunities(
    opportunities: list[ContractOpportunity],
    evaluated_count: int,
) -> None:
    """格式化输出合约机会"""
    print_section("Layer 3: Contract Filter (合约评估)")

    qualified = [o for o in opportunities if o.passed]

    print(f"  评估: {evaluated_count} 个合约")
    print(f"  合格: {len(qualified)} 个 ({len(qualified)/max(1,evaluated_count)*100:.1f}%)")

    if not qualified:
        print("\n  ⚠️ 无合格合约")
        # 显示一些淘汰原因
        if opportunities:
            print("\n  部分淘汰原因:")
            shown = 0
            for o in opportunities[:10]:
                if o.disqualify_reasons:
                    print(f"    - {o.symbol} {o.expiry} {o.option_type.upper()}{o.strike}: {o.disqualify_reasons[0]}")
                    shown += 1
                    if shown >= 5:
                        break
        return

    print("\n  Top 10 机会:")
    # 按 expected_roc 排序
    sorted_opps = sorted(qualified, key=lambda x: x.expected_roc or 0, reverse=True)

    for i, o in enumerate(sorted_opps[:10], 1):
        exp_str = o.expiry[5:] if o.expiry else "N/A"  # 只显示 MM-DD
        opt_type = "PUT" if o.option_type == "put" else "CALL"

        roc_str = f"ROC={o.expected_roc*100:.1f}%" if o.expected_roc else "ROC=N/A"
        sr_str = f"SR={o.sharpe_ratio_annual:.2f}" if o.sharpe_ratio_annual else "SR=N/A"
        delta_str = f"Δ={o.delta:.2f}" if o.delta else "Δ=N/A"
        otm_str = f"OTM={o.otm_percent*100:.1f}%" if o.otm_percent else "OTM=N/A"

        print(f"    {i}. {o.symbol} {exp_str} {opt_type}{o.strike:.0f}")
        print(f"       {roc_str}, {sr_str}, {delta_str}, {otm_str}, DTE={o.dte}")

        # 显示警告
        if o.warnings:
            print(f"       ⚠️ {o.warnings[0]}")


def run_validation(
    market_type: MarketType,
    strategy: str,
    pool_name: str | None,
    skip_market_check: bool,
    debug: bool,
) -> None:
    """运行完整的 pipeline 验证"""
    start_time = datetime.now()

    print_header("SCREENING PIPELINE VALIDATION")
    print(f"  策略: {strategy}")
    print(f"  市场: {market_type.value}")
    print(f"  跳过市场检查: {skip_market_check}")
    print(f"  Debug: {debug}")

    # 1. 加载股票池
    pool_manager = StockPoolManager()

    if pool_name:
        symbols = pool_manager.load_pool(pool_name)
        pool_info = pool_manager.get_pool_info(pool_name)
        print(f"  股票池: {pool_name} ({pool_info['count']} 个标的)")
    else:
        default_name = pool_manager.get_default_pool_name(market_type)
        symbols = pool_manager.get_default_pool(market_type)
        print(f"  股票池: {default_name} (默认, {len(symbols)} 个标的)")

    print(f"  标的列表: {', '.join(symbols)}")

    # 2. 初始化组件
    config = ScreeningConfig.load(strategy)
    provider = UnifiedDataProvider()

    market_filter = MarketFilter(config, provider)
    underlying_filter = UnderlyingFilter(config, provider)
    contract_filter = ContractFilter(config, provider)

    # ============ Layer 1: Market Filter ============
    market_status: MarketStatus | None = None

    if not skip_market_check:
        print("\n⏳ 正在评估市场环境...")
        market_status = market_filter.evaluate(market_type)
        format_market_status(market_status)

        if not market_status.is_favorable:
            print("\n" + "=" * 60)
            print(" PIPELINE RESULT: ❌ STOPPED (市场环境不利)")
            print("=" * 60)
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"\n总耗时: {elapsed:.1f}s")
            return
    else:
        print("\n⏭️ 跳过市场环境检查")

    # ============ Layer 2: Underlying Filter ============
    print("\n⏳ 正在评估标的...")
    underlying_scores = underlying_filter.evaluate(symbols, market_type)
    format_underlying_scores(underlying_scores, len(symbols))

    passed_underlyings = [s for s in underlying_scores if s.passed]
    if not passed_underlyings:
        print("\n" + "=" * 60)
        print(" PIPELINE RESULT: ❌ STOPPED (无标的通过筛选)")
        print("=" * 60)
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n总耗时: {elapsed:.1f}s")
        return

    # 按评分排序
    passed_underlyings = underlying_filter.sort_by_score(passed_underlyings)

    # ============ Layer 3: Contract Filter ============
    print("\n⏳ 正在评估合约...")
    opportunities = contract_filter.evaluate(passed_underlyings, strategy)

    # 估算评估的合约数量
    evaluated_count = len(opportunities) if opportunities else 0
    format_contract_opportunities(opportunities, evaluated_count)

    # ============ Summary ============
    elapsed = (datetime.now() - start_time).total_seconds()
    qualified = [o for o in opportunities if o.passed] if opportunities else []

    print_header("SUMMARY")

    if qualified:
        print(f"  Pipeline Result: ✅ PASSED")
        print(f"  合格机会: {len(qualified)} 个")
    else:
        print(f"  Pipeline Result: ⚠️ COMPLETED (无合格合约)")

    print(f"\n  统计:")
    print(f"    - 扫描标的: {len(symbols)}")
    print(f"    - 通过标的: {len(passed_underlyings)}")
    print(f"    - 评估合约: {evaluated_count}")
    print(f"    - 合格合约: {len(qualified)}")
    print(f"\n  总耗时: {elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(
        description="Screening Pipeline 端到端验证脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python validate_screening_pipeline.py --market us --strategy short_put
  python validate_screening_pipeline.py --market hk --skip-market-check
  python validate_screening_pipeline.py --pool us_default --debug
        """,
    )

    parser.add_argument(
        "--market", "-m",
        choices=["us", "hk"],
        default="us",
        help="市场类型 (默认: us)",
    )
    parser.add_argument(
        "--strategy", "-s",
        choices=["short_put", "covered_call"],
        default="short_put",
        help="策略类型 (默认: short_put)",
    )
    parser.add_argument(
        "--pool", "-p",
        type=str,
        default=None,
        help="股票池名称 (默认: 使用市场的默认股票池)",
    )
    parser.add_argument(
        "--skip-market-check",
        action="store_true",
        help="跳过市场环境检查",
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="启用调试日志",
    )
    parser.add_argument(
        "--list-pools",
        action="store_true",
        help="列出所有可用的股票池",
    )

    args = parser.parse_args()

    # 列出股票池
    if args.list_pools:
        pool_manager = StockPoolManager()
        print("\n可用股票池:")
        for pool_name in pool_manager.list_pools():
            info = pool_manager.get_pool_info(pool_name)
            print(f"  - {pool_name}: {info['description']} ({info['count']} 个标的)")
        return

    # 配置日志
    setup_logging(args.debug)

    # 运行验证
    market_type = MarketType.US if args.market == "us" else MarketType.HK

    try:
        run_validation(
            market_type=market_type,
            strategy=args.strategy,
            pool_name=args.pool,
            skip_market_check=args.skip_market_check,
            debug=args.debug,
        )
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
        sys.exit(1)
    except Exception as e:
        logging.exception(f"Pipeline 验证失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
