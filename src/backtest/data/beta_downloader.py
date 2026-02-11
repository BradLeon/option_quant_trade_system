"""
Stock Beta Downloader - 股票 Beta 数据下载器

从 yfinance 下载股票 beta 值并保存到 stock_beta.parquet。
Beta 是相对稳定的指标，可以一次下载后在回测中复用。

Usage:
    from src.backtest.data.beta_downloader import BetaDownloader

    downloader = BetaDownloader("/Volumes/ORICO/option_quant")
    results = downloader.download_and_save(["GOOG", "AAPL", "MSFT"])
"""

import logging
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)


class BetaDownloader:
    """股票 Beta 数据下载器

    从 yfinance 下载股票 beta 值并保存到 stock_beta.parquet。
    """

    # ETF 列表 (ETF 没有传统的 beta 计算方式)
    _ETF_SYMBOLS = frozenset({
        "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "EEM", "XLF", "XLE", "XLK",
        "GLD", "SLV", "TLT", "HYG", "LQD", "VXX", "UVXY", "SQQQ", "TQQQ",
        "ARKK", "XBI", "IBB", "SMH", "SOXX", "XOP", "OIH", "GDX", "GDXJ",
    })

    def __init__(self, data_dir: Path | str) -> None:
        """初始化下载器

        Args:
            data_dir: Parquet 数据目录
        """
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def output_path(self) -> Path:
        """输出文件路径"""
        return self._data_dir / "stock_beta.parquet"

    def download_symbols(
        self,
        symbols: list[str],
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, float]:
        """下载股票 beta 值

        Args:
            symbols: 股票代码列表
            on_progress: 进度回调函数 (symbol, current, total)

        Returns:
            {symbol: beta} 字典
        """
        import yfinance as yf

        results: dict[str, float] = {}
        total = len(symbols)

        for i, symbol in enumerate(symbols, 1):
            if on_progress:
                on_progress(symbol, i, total)

            # 跳过 ETF (beta 为 1.0 或不适用)
            if symbol.upper() in self._ETF_SYMBOLS:
                logger.debug(f"Skipping ETF {symbol}")
                continue

            try:
                ticker = yf.Ticker(symbol)
                beta = ticker.info.get("beta")
                if beta is not None and isinstance(beta, (int, float)):
                    results[symbol] = float(beta)
                    logger.debug(f"Downloaded beta for {symbol}: {beta:.2f}")
                else:
                    logger.warning(f"No beta available for {symbol}")
            except Exception as e:
                logger.warning(f"Failed to download beta for {symbol}: {e}")

        return results

    def save_to_parquet(self, data: dict[str, float]) -> Path:
        """保存为 stock_beta.parquet

        Args:
            data: {symbol: beta} 字典

        Returns:
            保存的文件路径
        """
        if not data:
            logger.warning("No beta data to save")
            return self.output_path

        # 构建 DataFrame
        records = [
            {
                "symbol": symbol,
                "beta": beta,
                "download_date": date.today(),
            }
            for symbol, beta in data.items()
        ]
        df = pd.DataFrame(records)

        # 如果文件已存在，合并数据（新数据覆盖旧数据）
        if self.output_path.exists():
            existing_df = pd.read_parquet(self.output_path)
            # 删除已存在的 symbols，用新数据替换
            existing_df = existing_df[~existing_df["symbol"].isin(data.keys())]
            df = pd.concat([existing_df, df], ignore_index=True)

        # 保存
        df.to_parquet(self.output_path, index=False)
        logger.info(f"Saved {len(data)} beta records to {self.output_path}")

        return self.output_path

    def download_and_save(
        self,
        symbols: list[str],
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, float]:
        """下载并保存 beta 数据

        Args:
            symbols: 股票代码列表
            on_progress: 进度回调函数

        Returns:
            {symbol: beta} 字典
        """
        logger.info(f"Downloading beta for {len(symbols)} symbols...")

        results = self.download_symbols(symbols, on_progress)

        if results:
            self.save_to_parquet(results)

        return results

    def load_beta(self, symbol: str) -> float | None:
        """从 parquet 加载单个股票的 beta

        Args:
            symbol: 股票代码

        Returns:
            Beta 值或 None
        """
        if not self.output_path.exists():
            return None

        try:
            df = pd.read_parquet(self.output_path)
            row = df[df["symbol"] == symbol.upper()]
            if not row.empty:
                return float(row.iloc[0]["beta"])
            return None
        except Exception as e:
            logger.warning(f"Failed to load beta for {symbol}: {e}")
            return None

    def load_all_betas(self) -> dict[str, float]:
        """加载所有 beta 数据

        Returns:
            {symbol: beta} 字典
        """
        if not self.output_path.exists():
            return {}

        try:
            df = pd.read_parquet(self.output_path)
            return dict(zip(df["symbol"], df["beta"]))
        except Exception as e:
            logger.warning(f"Failed to load beta data: {e}")
            return {}

    # ========== Rolling Beta Calculation ==========

    @property
    def rolling_beta_path(self) -> Path:
        """滚动 Beta 时序文件路径"""
        return self._data_dir / "stock_beta_daily.parquet"

    def calculate_rolling_beta(
        self,
        symbols: list[str],
        window: int = 252,
    ) -> pd.DataFrame:
        """从 stock_daily.parquet 计算滚动 Beta 时序

        使用 Cov(stock_returns, SPY_returns) / Var(SPY_returns) 公式计算。

        Args:
            symbols: 股票代码列表 (不含 SPY，SPY 用作基准)
            window: 滚动窗口天数 (默认 252，即一年)

        Returns:
            DataFrame with columns: date, symbol, beta
        """
        import numpy as np

        stock_path = self._data_dir / "stock_daily.parquet"
        if not stock_path.exists():
            raise FileNotFoundError(f"stock_daily.parquet not found: {stock_path}")

        # 读取股票日线数据
        stock_df = pd.read_parquet(stock_path)
        logger.info(f"Loaded {len(stock_df)} rows from stock_daily.parquet")

        # 确保 SPY 在数据中
        if "SPY" not in stock_df["symbol"].unique():
            raise ValueError("SPY data is required for beta calculation")

        # 转换为 pivot 表 (date x symbol)
        pivot = stock_df.pivot(index="date", columns="symbol", values="close")
        pivot = pivot.sort_index()

        # 计算每日收益率
        returns = pivot.pct_change()

        # SPY 收益率作为基准
        spy_returns = returns["SPY"]

        # 计算每个 symbol 的滚动 Beta
        results = []

        for symbol in symbols:
            if symbol.upper() == "SPY":
                logger.debug("Skipping SPY (benchmark)")
                continue

            if symbol not in returns.columns:
                logger.warning(f"Symbol {symbol} not found in stock_daily.parquet")
                continue

            stock_returns = returns[symbol]

            # 滚动协方差和方差
            # Beta = Cov(stock, SPY) / Var(SPY)
            rolling_cov = stock_returns.rolling(window=window).cov(spy_returns)
            rolling_var = spy_returns.rolling(window=window).var()

            # 计算 Beta
            rolling_beta = rolling_cov / rolling_var

            # 转换为 DataFrame
            beta_df = pd.DataFrame({
                "date": rolling_beta.index,
                "symbol": symbol,
                "beta": rolling_beta.values,
            })

            # 移除 NaN (前 window-1 天没有足够数据)
            beta_df = beta_df.dropna()

            results.append(beta_df)
            logger.info(f"Calculated rolling beta for {symbol}: {len(beta_df)} rows")

        if not results:
            return pd.DataFrame(columns=["date", "symbol", "beta"])

        combined = pd.concat(results, ignore_index=True)
        combined = combined.sort_values(["symbol", "date"])

        return combined

    def calculate_and_save_rolling_beta(
        self,
        symbols: list[str],
        window: int = 252,
    ) -> Path:
        """计算并保存滚动 Beta 到 stock_beta_daily.parquet

        Args:
            symbols: 股票代码列表 (不含 SPY)
            window: 滚动窗口天数 (默认 252)

        Returns:
            保存的文件路径
        """
        logger.info(f"Calculating rolling beta (window={window}) for {symbols}...")

        df = self.calculate_rolling_beta(symbols, window)

        if df.empty:
            logger.warning("No rolling beta data to save")
            return self.rolling_beta_path

        # 如果文件已存在，合并数据（新数据覆盖旧数据）
        if self.rolling_beta_path.exists():
            existing_df = pd.read_parquet(self.rolling_beta_path)
            # 删除将要更新的 symbols
            existing_df = existing_df[~existing_df["symbol"].isin(symbols)]
            df = pd.concat([existing_df, df], ignore_index=True)
            df = df.sort_values(["symbol", "date"])

        df.to_parquet(self.rolling_beta_path, index=False)
        logger.info(f"Saved rolling beta to {self.rolling_beta_path}")

        return self.rolling_beta_path

    def load_rolling_beta(self, symbol: str, as_of_date: date | None = None) -> float | None:
        """从 stock_beta_daily.parquet 加载指定日期的 Beta

        Args:
            symbol: 股票代码
            as_of_date: 查询日期 (如果为 None，返回最新值)

        Returns:
            Beta 值或 None
        """
        if not self.rolling_beta_path.exists():
            return None

        try:
            df = pd.read_parquet(self.rolling_beta_path)
            df = df[df["symbol"] == symbol.upper()]

            if df.empty:
                return None

            if as_of_date:
                # 查询指定日期或之前最近的 Beta
                df = df[df["date"] <= as_of_date]
                if df.empty:
                    return None
                # 取最近的一条
                df = df.sort_values("date", ascending=False)

            return float(df.iloc[0]["beta"])

        except Exception as e:
            logger.warning(f"Failed to load rolling beta for {symbol}: {e}")
            return None
