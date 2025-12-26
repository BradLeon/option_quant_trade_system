"""Bridge between data layer and sentiment calculations.

Provides utilities to fetch data needed for sentiment analysis
from the unified data provider.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.data.providers.unified_provider import UnifiedDataProvider

from src.data.models.stock import KlineType
from src.engine.models.sentiment import MarketSentiment

from src.engine.account.sentiment.aggregator import (
    analyze_hk_sentiment,
    analyze_us_sentiment,
)


def fetch_us_sentiment_data(
    provider: UnifiedDataProvider,
    lookback_days: int = 250,
) -> dict[str, Any]:
    """Fetch all data needed for US market sentiment analysis.

    Fetches VIX, VIX3M, SPY prices, QQQ prices, and PCR from data layer.

    Args:
        provider: UnifiedDataProvider instance.
        lookback_days: Number of historical days to fetch for trend analysis.

    Returns:
        Dictionary with all required data for analyze_us_sentiment().
        Keys: vix, vix_3m, spy_prices, qqq_prices, spy_current, qqq_current, pcr

    Example:
        >>> provider = UnifiedDataProvider()
        >>> data = fetch_us_sentiment_data(provider)
        >>> sentiment = analyze_us_sentiment(**data)
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days + 50)  # Buffer for MAs

    result: dict[str, Any] = {
        "vix": None,
        "vix_3m": None,
        "spy_prices": None,
        "qqq_prices": None,
        "spy_current": None,
        "qqq_current": None,
        "pcr": None,
    }

    # Fetch VIX data
    try:
        vix_data = provider.get_macro_data("^VIX", start_date, end_date)
        if vix_data:
            result["vix"] = vix_data[-1].value
    except Exception:
        pass

    # Fetch VIX3M data
    try:
        vix_3m_data = provider.get_macro_data("^VIX3M", start_date, end_date)
        if vix_3m_data:
            result["vix_3m"] = vix_3m_data[-1].value
    except Exception:
        pass

    # Fetch SPY data
    try:
        spy_klines = provider.get_history_kline("SPY", KlineType.DAY, start_date, end_date)
        if spy_klines:
            result["spy_prices"] = [k.close for k in spy_klines if k.close is not None]
            result["spy_current"] = spy_klines[-1].close
    except Exception:
        pass

    # Fetch QQQ data
    try:
        qqq_klines = provider.get_history_kline("QQQ", KlineType.DAY, start_date, end_date)
        if qqq_klines:
            result["qqq_prices"] = [k.close for k in qqq_klines if k.close is not None]
            result["qqq_current"] = qqq_klines[-1].close
    except Exception:
        pass

    # Fetch PCR
    try:
        result["pcr"] = provider.get_put_call_ratio("SPY")
    except Exception:
        pass

    return result


def fetch_hk_sentiment_data(
    provider: UnifiedDataProvider,
    lookback_days: int = 250,
) -> dict[str, Any]:
    """Fetch all data needed for HK market sentiment analysis.

    Data Sources (priority order):
    - VHSI: 800125.HK (Futu) > 2800.HK IV (IBKR)
    - HSI: 800000.HK (Futu) > ^HSI (Yahoo) > 2800.HK ETF
    - HSTECH: 3032.HK ETF (Futu compatible)
    - PCR: 2800.HK volatility (IBKR)

    VHSI Term Structure:
    - vhsi_proxy: 800125.HK close (Futu) or 30-day IV from IBKR
    - vhsi_3m_proxy: ATM IV (60-120 DTE) from 800000.HK (HSI) option chain

    Note: Futu is the best source for VHSI (800125.HK) and HSI (800000.HK).

    Args:
        provider: UnifiedDataProvider instance.
        lookback_days: Number of historical days to fetch for trend analysis.

    Returns:
        Dictionary with all required data for analyze_hk_sentiment().
        Keys: vhsi_proxy, vhsi_3m_proxy, hsi_prices, hstech_prices,
              hsi_current, hstech_current, pcr

    Example:
        >>> provider = UnifiedDataProvider()
        >>> data = fetch_hk_sentiment_data(provider)
        >>> sentiment = analyze_hk_sentiment(**data)
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days + 50)  # Buffer for MAs

    result: dict[str, Any] = {
        "vhsi_proxy": None,
        "vhsi_3m_proxy": None,
        "hsi_prices": None,
        "hstech_prices": None,
        "hsi_current": None,
        "hstech_current": None,
        "pcr": None,
    }

    # === VHSI Data ===
    # Priority 1: Try 800125.HK directly (Futu provider)
    try:
        vhsi_klines = provider.get_history_kline(
            "800125.HK", KlineType.DAY,
            date.today() - timedelta(days=5),
            date.today()
        )
        if vhsi_klines:
            result["vhsi_proxy"] = vhsi_klines[-1].close
    except Exception:
        pass

    # =========================================================================
    # Priority 2: 使用IBKR获取2800.HK的IV和PCR
    # =========================================================================
    # 原因: Futu API不提供股票级别的IV和PCR数据
    #       IBKR的get_stock_volatility可以获取30天IV、HV和Put/Call Ratio
    # =========================================================================
    if result["vhsi_proxy"] is None:
        try:
            volatility = provider.get_stock_volatility("2800.HK")
            if volatility:
                # Convert IV from decimal to percentage (e.g., 0.25 -> 25)
                if volatility.iv is not None:
                    result["vhsi_proxy"] = volatility.iv * 100
                    logger.debug(f"Got VHSI proxy from 2800.HK IV: {result['vhsi_proxy']}")
                # PCR from 2800.HK options (IBKR provides this via Open Interest)
                if volatility.pcr is not None:
                    result["pcr"] = volatility.pcr
                    logger.debug(f"Got PCR from 2800.HK: {result['pcr']}")
        except Exception as e:
            logger.debug(f"Failed to get 2800.HK volatility from IBKR: {e}")

    # =========================================================================
    # vhsi_3m_proxy: 暂不支持
    # =========================================================================
    # 原因: IBKR的reqSecDefOptParams返回的远期到期日（60-120 DTE）对应的期权合约
    #       尚未在交易所上市，无法通过get_option_quotes_batch获取IV数据。
    #       IBKR返回错误200: "未找到该请求的证券定义"
    # 兜底: vhsi_3m_proxy保持为None，sentiment分析会跳过term structure计算
    # =========================================================================
    logger.debug("vhsi_3m_proxy: skipped (HK far-dated options not available in IBKR)")

    # === HSI Price Data ===
    # Priority 1: Try 800000.HK (Futu provider - actual HSI index)
    try:
        hsi_klines = provider.get_history_kline("800000.HK", KlineType.DAY, start_date, end_date)
        if hsi_klines:
            result["hsi_prices"] = [k.close for k in hsi_klines if k.close is not None]
            result["hsi_current"] = hsi_klines[-1].close
    except Exception:
        pass

    # Priority 2: Fallback to ^HSI (Yahoo provider)
    if result["hsi_prices"] is None:
        try:
            hsi_klines = provider.get_history_kline("^HSI", KlineType.DAY, start_date, end_date)
            if hsi_klines:
                result["hsi_prices"] = [k.close for k in hsi_klines if k.close is not None]
                result["hsi_current"] = hsi_klines[-1].close
        except Exception:
            pass

    # Priority 3: Fallback to 2800.HK ETF
    if result["hsi_prices"] is None:
        try:
            hsi_klines = provider.get_history_kline("2800.HK", KlineType.DAY, start_date, end_date)
            if hsi_klines:
                result["hsi_prices"] = [k.close for k in hsi_klines if k.close is not None]
                result["hsi_current"] = hsi_klines[-1].close
        except Exception:
            pass

    # Fetch HSTECH price data (use 3032.HK ETF - Futu compatible)
    try:
        hstech_klines = provider.get_history_kline(
            "3032.HK", KlineType.DAY, start_date, end_date
        )
        if hstech_klines:
            result["hstech_prices"] = [k.close for k in hstech_klines if k.close is not None]
            result["hstech_current"] = hstech_klines[-1].close
    except Exception:
        pass

    # =========================================================================
    # PCR: 使用IBKR获取2800.HK的Put/Call Ratio
    # =========================================================================
    # 原因: Futu API不提供PCR数据
    #       IBKR通过期权Open Interest计算PCR (put_oi / call_oi)
    # =========================================================================
    if result["pcr"] is None:
        try:
            logger.debug("Fetching 2800.HK PCR from IBKR...")
            volatility = provider.get_stock_volatility("2800.HK")
            if volatility and volatility.pcr is not None:
                result["pcr"] = volatility.pcr
                logger.debug(f"Got PCR from 2800.HK: {result['pcr']}")
            else:
                logger.warning("PCR not available (IBKR required, Futu does not provide PCR)")
        except Exception as e:
            logger.warning(f"Failed to get PCR: {e}")

    return result


def get_us_sentiment(
    provider: UnifiedDataProvider,
    lookback_days: int = 250,
) -> MarketSentiment:
    """Get complete US market sentiment analysis.

    Convenience function that fetches data and performs analysis in one call.

    Args:
        provider: UnifiedDataProvider instance.
        lookback_days: Number of historical days to fetch.

    Returns:
        MarketSentiment for US market.

    Example:
        >>> provider = UnifiedDataProvider()
        >>> sentiment = get_us_sentiment(provider)
        >>> print(sentiment.composite_signal)
    """
    data = fetch_us_sentiment_data(provider, lookback_days)
    return analyze_us_sentiment(**data)


def get_hk_sentiment(
    provider: UnifiedDataProvider,
    lookback_days: int = 250,
) -> MarketSentiment:
    """Get complete HK market sentiment analysis.

    Convenience function that fetches data and performs analysis in one call.

    Args:
        provider: UnifiedDataProvider instance.
        lookback_days: Number of historical days to fetch.

    Returns:
        MarketSentiment for HK market.

    Example:
        >>> provider = UnifiedDataProvider()
        >>> sentiment = get_hk_sentiment(provider)
        >>> print(sentiment.composite_signal)
    """
    data = fetch_hk_sentiment_data(provider, lookback_days)
    return analyze_hk_sentiment(**data)
