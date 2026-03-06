"""Phase 2 验证脚本

验证内容：
1. 回测 PositionData 中技术面字段是否被正确填充
2. 策略版本级监控阈值覆写是否生效
3. rank_candidates 模板方法是否正常工作
"""

import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("verify_phase2")


def verify_technical_data_enrichment():
    """验证 1: 回测 PositionData 技术面字段填充"""
    logger.info("=" * 60)
    logger.info("验证 1: 回测技术面数据填充")
    logger.info("=" * 60)

    from src.backtest.config.backtest_config import BacktestConfig, PriceMode
    from src.backtest.data.duckdb_provider import DuckDBProvider
    from src.backtest.engine.position_manager import PositionManager
    from src.backtest.engine.account_simulator import SimulatedPosition
    from src.data.models.option import OptionType

    data_dir = "/Volumes/ORICO/option_quant"
    provider = DuckDBProvider(data_dir=data_dir)

    # 设置日期为有数据的某天
    test_date = date(2025, 6, 15)
    provider.set_as_of_date(test_date)

    pm = PositionManager(data_provider=provider, price_mode=PriceMode.CLOSE)
    pm.set_date(test_date)

    # 创建一个模拟持仓
    pos = SimulatedPosition(
        position_id="TEST_001",
        symbol="GOOG 20250718 175.0P",
        asset_type="option",
        underlying="GOOG",
        option_type=OptionType.PUT,
        strike=175.0,
        expiration=date(2025, 7, 18),
        quantity=-1,
        entry_price=3.50,
        entry_date=date(2025, 6, 1),
        lot_size=100,
    )
    pos.current_price = 3.20
    pos.underlying_price = 180.0
    pos.market_value = -320.0
    pos.unrealized_pnl = 30.0

    # 转换为 PositionData
    pos_data = pm._convert_to_position_data(pos, test_date)

    # 检查技术面字段
    tech_fields = {
        "rsi": pos_data.rsi,
        "rsi_zone": pos_data.rsi_zone,
        "adx": pos_data.adx,
        "support": pos_data.support,
        "resistance": pos_data.resistance,
        "trend_signal": pos_data.trend_signal,
        "ma_alignment": pos_data.ma_alignment,
        "market_regime": pos_data.market_regime,
        "tech_trend_strength": pos_data.tech_trend_strength,
        "sell_put_signal": pos_data.sell_put_signal,
        "sell_call_signal": pos_data.sell_call_signal,
        "is_dangerous_period": pos_data.is_dangerous_period,
    }

    filled_count = 0
    for field, value in tech_fields.items():
        status = "FILLED" if value is not None else "MISSING"
        if value is not None:
            filled_count += 1
        logger.info(f"  {field}: {value} [{status}]")

    # 验证缓存机制
    cache_size = len(pm._technical_cache)
    logger.info(f"\n  Technical cache size: {cache_size} (should be 1 for GOOG)")

    # 验证同 underlying 第二个持仓使用缓存
    pos2 = SimulatedPosition(
        position_id="TEST_002",
        symbol="GOOG 20250718 170.0P",
        asset_type="option",
        underlying="GOOG",
        option_type=OptionType.PUT,
        strike=170.0,
        expiration=date(2025, 7, 18),
        quantity=-1,
        entry_price=2.00,
        entry_date=date(2025, 6, 1),
        lot_size=100,
    )
    pos2.current_price = 1.80
    pos2.underlying_price = 180.0
    pos2.market_value = -180.0
    pos2.unrealized_pnl = 20.0

    pos_data2 = pm._convert_to_position_data(pos2, test_date)
    cache_size_after = len(pm._technical_cache)
    logger.info(f"  Technical cache size after 2nd pos: {cache_size_after} (should still be 1)")

    # 验证日期切换清空缓存
    pm.set_date(date(2025, 6, 16))
    cache_after_date_change = len(pm._technical_cache)
    logger.info(f"  Technical cache size after date change: {cache_after_date_change} (should be 0)")

    success = filled_count >= 8  # 至少 8/12 个字段被填充
    logger.info(f"\n  Result: {'PASS' if success else 'FAIL'} ({filled_count}/12 fields filled)")
    return success


def verify_monitoring_overrides():
    """验证 2: 策略版本级监控阈值覆写"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 2: 策略版本级监控阈值覆写")
    logger.info("=" * 60)

    from src.business.strategy.versions.short_options_with_expire_itm_stock_trade import (
        ShortOptionsWithExpireItmStockTrade,
    )
    from src.business.strategy.versions.short_options_without_expire_itm_stock_trade import (
        ShortOptionsWithoutExpireItmStockTrade,
    )
    from src.business.config.monitoring_config import MonitoringConfig

    # Test WithExpire overrides
    with_expire = ShortOptionsWithExpireItmStockTrade()
    overrides_w = with_expire.get_monitoring_overrides()
    logger.info(f"  WithExpire overrides: {overrides_w}")
    assert overrides_w is not None, "WithExpire should return overrides"
    assert overrides_w["otm_pct"]["enabled"] is False, "otm_pct should be disabled"
    assert overrides_w["pnl"]["enabled"] is False, "pnl should be disabled"

    # Test WithoutExpire overrides
    without_expire = ShortOptionsWithoutExpireItmStockTrade()
    overrides_wo = without_expire.get_monitoring_overrides()
    logger.info(f"  WithoutExpire overrides: {overrides_wo}")
    assert overrides_wo is not None, "WithoutExpire should return overrides"
    assert overrides_wo["otm_pct"]["enabled"] is True, "otm_pct should be enabled"
    assert overrides_wo["otm_pct"]["red_below"] == 0.02, "otm_pct red_below should be 0.02"
    assert overrides_wo["pnl"]["enabled"] is True, "pnl should be enabled"
    assert overrides_wo["pnl"]["red_below"] == -1.0, "pnl red_below should be -1.0"

    # Test _apply_monitoring_overrides actually mutates config
    config = MonitoringConfig.load(strategy_name="short_options_with_expire_itm_stock_trade")

    # 记录覆写前的值
    otm_before = getattr(config.position.otm_pct, 'enabled', None) if hasattr(config.position, 'otm_pct') else 'N/A'
    pnl_before = getattr(config.position.pnl, 'enabled', None) if hasattr(config.position, 'pnl') else 'N/A'
    logger.info(f"  Before override - otm_pct.enabled: {otm_before}, pnl.enabled: {pnl_before}")

    with_expire._apply_monitoring_overrides(config, overrides_w)

    otm_after = getattr(config.position.otm_pct, 'enabled', None) if hasattr(config.position, 'otm_pct') else 'N/A'
    pnl_after = getattr(config.position.pnl, 'enabled', None) if hasattr(config.position, 'pnl') else 'N/A'
    logger.info(f"  After override  - otm_pct.enabled: {otm_after}, pnl.enabled: {pnl_after}")

    success = True
    if hasattr(config.position, 'otm_pct'):
        if config.position.otm_pct.enabled is not False:
            logger.error("  FAIL: otm_pct.enabled should be False after override")
            success = False
    if hasattr(config.position, 'pnl'):
        if config.position.pnl.enabled is not False:
            logger.error("  FAIL: pnl.enabled should be False after override")
            success = False

    logger.info(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def verify_rank_candidates():
    """验证 3: rank_candidates 模板方法"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 3: rank_candidates 模板方法")
    logger.info("=" * 60)

    from src.business.strategy.versions.short_options_with_expire_itm_stock_trade import (
        ShortOptionsWithExpireItmStockTrade,
    )
    from src.business.screening.models import ContractOpportunity

    strategy = ShortOptionsWithExpireItmStockTrade()

    # 创建模拟候选合约
    candidates = []
    for i, (roc, symbol) in enumerate([(0.15, "A"), (0.30, "B"), (0.10, "C"), (0.25, "D")]):
        opp = ContractOpportunity(
            symbol=symbol,
            option_type="put",
            strike=100.0,
            expiry="2025-07-18",
            mid_price=2.0,
            bid=1.9,
            ask=2.1,
            iv=0.3,
            delta=-0.3,
            gamma=0.05,
            theta=-0.02,
            vega=0.1,
            annual_roc=roc,
            dte=30,
            volume=100,
            open_interest=1000,
            lot_size=100,
        )
        candidates.append(opp)

    ranked = strategy.rank_candidates(candidates)
    ranked_symbols = [c.symbol for c in ranked]
    expected_order = ["B", "D", "A", "C"]  # sorted by annual_roc descending

    logger.info(f"  Input order: {[c.symbol for c in candidates]}")
    logger.info(f"  Ranked order: {ranked_symbols}")
    logger.info(f"  Expected order: {expected_order}")

    success = ranked_symbols == expected_order
    logger.info(f"\n  Result: {'PASS' if success else 'FAIL'}")
    return success


def verify_populate_technical_fields():
    """验证 4: PositionDataBuilder.populate_technical_fields 共享方法"""
    logger.info("\n" + "=" * 60)
    logger.info("验证 4: populate_technical_fields 共享方法")
    logger.info("=" * 60)

    from src.business.monitoring.position_data_builder import PositionDataBuilder
    from src.business.monitoring.models import PositionData
    from src.engine.models.result import TechnicalScore, TechnicalSignal
    from src.engine.models.enums import TrendSignal
    from datetime import datetime

    # 创建一个空的 PositionData
    pos_data = PositionData(
        position_id="TEST",
        symbol="TEST",
        asset_type="option",
        quantity=-1,
        entry_price=3.0,
        current_price=2.5,
        market_value=-250.0,
        unrealized_pnl=50.0,
        unrealized_pnl_pct=0.167,
        currency="USD",
        broker="test",
        timestamp=datetime.now(),
    )

    # 创建模拟 score 和 signal
    score = TechnicalScore(
        rsi=45.0,
        rsi_zone="neutral",
        adx=25.0,
        support=170.0,
        resistance=190.0,
        trend_signal=TrendSignal.BULLISH,
        ma_alignment="bullish_aligned",
    )
    signal = TechnicalSignal(
        market_regime="trending_up",
        trend_strength="moderate",
        sell_put_signal="strong",
        sell_call_signal="none",
        is_dangerous_period=False,
    )

    # 调用共享方法
    PositionDataBuilder.populate_technical_fields(pos_data, score, signal)

    # 验证所有字段
    checks = {
        "rsi": (pos_data.rsi, 45.0),
        "rsi_zone": (pos_data.rsi_zone, "neutral"),
        "adx": (pos_data.adx, 25.0),
        "support": (pos_data.support, 170.0),
        "resistance": (pos_data.resistance, 190.0),
        "trend_signal": (pos_data.trend_signal, "bullish"),
        "ma_alignment": (pos_data.ma_alignment, "bullish_aligned"),
        "market_regime": (pos_data.market_regime, "trending_up"),
        "tech_trend_strength": (pos_data.tech_trend_strength, "moderate"),
        "sell_put_signal": (pos_data.sell_put_signal, "strong"),
        "sell_call_signal": (pos_data.sell_call_signal, "none"),
        "is_dangerous_period": (pos_data.is_dangerous_period, False),
    }

    all_pass = True
    for field, (actual, expected) in checks.items():
        ok = actual == expected
        if not ok:
            all_pass = False
        logger.info(f"  {field}: {actual} (expected {expected}) [{'PASS' if ok else 'FAIL'}]")

    logger.info(f"\n  Result: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


if __name__ == "__main__":
    results = {}

    # 验证 3 和 4 不需要外部数据，优先执行
    results["rank_candidates"] = verify_rank_candidates()
    results["populate_technical_fields"] = verify_populate_technical_fields()
    results["monitoring_overrides"] = verify_monitoring_overrides()

    # 验证 1 需要 DuckDB 数据
    try:
        results["technical_data_enrichment"] = verify_technical_data_enrichment()
    except Exception as e:
        logger.error(f"  技术面数据验证失败: {e}")
        import traceback
        traceback.print_exc()
        results["technical_data_enrichment"] = False

    # 汇总
    logger.info("\n" + "=" * 60)
    logger.info("验证汇总")
    logger.info("=" * 60)
    for name, passed in results.items():
        logger.info(f"  {name}: {'PASS' if passed else 'FAIL'}")

    all_passed = all(results.values())
    logger.info(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    sys.exit(0 if all_passed else 1)
