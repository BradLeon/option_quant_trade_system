"""
Trade Analyzer - 交易分析

对回测交易记录进行深入分析:
- 按标的/月份/年份分组统计
- 持仓周期分析
- 最佳/最差交易识别
- 交易模式分析

Usage:
    from src.backtest.analysis.trade_analyzer import TradeAnalyzer

    analyzer = TradeAnalyzer(trade_records)
    by_symbol = analyzer.group_by_symbol()
    best_trades = analyzer.get_best_trades(n=5)
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.backtest.engine.trade_simulator import TradeRecord


@dataclass
class TradeStats:
    """交易统计"""

    count: int = 0
    winning: int = 0
    losing: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    avg_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float | None = None
    avg_holding_days: float | None = None
    total_commission: float = 0.0


@dataclass
class SymbolStats(TradeStats):
    """按标的统计"""

    symbol: str = ""


@dataclass
class PeriodStats(TradeStats):
    """按时间段统计"""

    year: int = 0
    month: int | None = None  # None 表示年度统计


@dataclass
class TradeSummary:
    """单笔交易摘要"""

    position_id: str
    symbol: str
    underlying: str
    option_type: str
    strike: float
    expiration: date
    entry_date: date
    exit_date: date
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    return_pct: float
    holding_days: int
    exit_reason: str
    commission: float


class TradeAnalyzer:
    """交易分析器

    对回测交易记录进行深入分析。

    Usage:
        analyzer = TradeAnalyzer(trade_records)
        by_symbol = analyzer.group_by_symbol()
        by_month = analyzer.group_by_month()
        best = analyzer.get_best_trades(5)
        worst = analyzer.get_worst_trades(5)
    """

    def __init__(self, trade_records: list["TradeRecord"]) -> None:
        """初始化分析器

        Args:
            trade_records: 交易记录列表
        """
        self._records = trade_records
        self._trades = self._extract_trades()

    def _extract_trades(self) -> list[TradeSummary]:
        """从交易记录提取完整交易

        将 open + close 配对成完整的交易周期。
        """
        # 按 position_id 分组
        by_position: dict[str, list["TradeRecord"]] = defaultdict(list)
        for record in self._records:
            if hasattr(record, "position_id") and record.position_id:
                by_position[record.position_id].append(record)

        trades = []
        for position_id, records in by_position.items():
            # 找到开仓和平仓记录
            open_record = None
            close_record = None

            for record in records:
                if record.action == "open":
                    open_record = record
                elif record.action in ("close", "expire"):
                    close_record = record

            if open_record and close_record:
                # 计算持仓天数 (使用 trade_date 字段)
                holding_days = (close_record.trade_date - open_record.trade_date).days

                # 计算收益率
                entry_value = abs(open_record.price * open_record.quantity * 100)
                if entry_value > 0:
                    return_pct = (close_record.pnl or 0) / entry_value
                else:
                    return_pct = 0.0

                # 解析期权信息
                symbol = open_record.symbol
                underlying = getattr(open_record, "underlying", symbol.split()[0])
                option_type = getattr(open_record, "option_type", "put")
                strike = getattr(open_record, "strike", 0.0)
                expiration = getattr(open_record, "expiration", close_record.trade_date)

                trade = TradeSummary(
                    position_id=position_id,
                    symbol=symbol,
                    underlying=underlying,
                    option_type=option_type,
                    strike=strike,
                    expiration=expiration,
                    entry_date=open_record.trade_date,
                    exit_date=close_record.trade_date,
                    quantity=open_record.quantity,
                    entry_price=open_record.price,
                    exit_price=close_record.price,
                    pnl=close_record.pnl or 0.0,
                    return_pct=return_pct,
                    holding_days=holding_days,
                    exit_reason=getattr(close_record, "reason", close_record.action),
                    commission=open_record.commission + close_record.commission,
                )
                trades.append(trade)

        return trades

    def _calc_stats(self, trades: list[TradeSummary]) -> TradeStats:
        """计算交易统计"""
        if not trades:
            return TradeStats()

        pnls = [t.pnl for t in trades]
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl < 0]

        gross_profit = sum(t.pnl for t in winning)
        gross_loss = abs(sum(t.pnl for t in losing))

        holding_days = [t.holding_days for t in trades]
        commissions = [t.commission for t in trades]

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        return TradeStats(
            count=len(trades),
            winning=len(winning),
            losing=len(losing),
            total_pnl=sum(pnls),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            avg_pnl=sum(pnls) / len(trades),
            win_rate=len(winning) / len(trades) if trades else 0,
            profit_factor=profit_factor,
            avg_holding_days=sum(holding_days) / len(holding_days) if holding_days else None,
            total_commission=sum(commissions),
        )

    def group_by_symbol(self) -> dict[str, SymbolStats]:
        """按标的分组统计

        Returns:
            {underlying: SymbolStats}
        """
        by_symbol: dict[str, list[TradeSummary]] = defaultdict(list)
        for trade in self._trades:
            by_symbol[trade.underlying].append(trade)

        results = {}
        for symbol, trades in by_symbol.items():
            base_stats = self._calc_stats(trades)
            results[symbol] = SymbolStats(
                symbol=symbol,
                count=base_stats.count,
                winning=base_stats.winning,
                losing=base_stats.losing,
                total_pnl=base_stats.total_pnl,
                gross_profit=base_stats.gross_profit,
                gross_loss=base_stats.gross_loss,
                avg_pnl=base_stats.avg_pnl,
                win_rate=base_stats.win_rate,
                profit_factor=base_stats.profit_factor,
                avg_holding_days=base_stats.avg_holding_days,
                total_commission=base_stats.total_commission,
            )

        return results

    def group_by_month(self) -> dict[tuple[int, int], PeriodStats]:
        """按月份分组统计

        Returns:
            {(year, month): PeriodStats}
        """
        by_month: dict[tuple[int, int], list[TradeSummary]] = defaultdict(list)
        for trade in self._trades:
            key = (trade.exit_date.year, trade.exit_date.month)
            by_month[key].append(trade)

        results = {}
        for (year, month), trades in sorted(by_month.items()):
            base_stats = self._calc_stats(trades)
            results[(year, month)] = PeriodStats(
                year=year,
                month=month,
                count=base_stats.count,
                winning=base_stats.winning,
                losing=base_stats.losing,
                total_pnl=base_stats.total_pnl,
                gross_profit=base_stats.gross_profit,
                gross_loss=base_stats.gross_loss,
                avg_pnl=base_stats.avg_pnl,
                win_rate=base_stats.win_rate,
                profit_factor=base_stats.profit_factor,
                avg_holding_days=base_stats.avg_holding_days,
                total_commission=base_stats.total_commission,
            )

        return results

    def group_by_year(self) -> dict[int, PeriodStats]:
        """按年份分组统计

        Returns:
            {year: PeriodStats}
        """
        by_year: dict[int, list[TradeSummary]] = defaultdict(list)
        for trade in self._trades:
            by_year[trade.exit_date.year].append(trade)

        results = {}
        for year, trades in sorted(by_year.items()):
            base_stats = self._calc_stats(trades)
            results[year] = PeriodStats(
                year=year,
                month=None,
                count=base_stats.count,
                winning=base_stats.winning,
                losing=base_stats.losing,
                total_pnl=base_stats.total_pnl,
                gross_profit=base_stats.gross_profit,
                gross_loss=base_stats.gross_loss,
                avg_pnl=base_stats.avg_pnl,
                win_rate=base_stats.win_rate,
                profit_factor=base_stats.profit_factor,
                avg_holding_days=base_stats.avg_holding_days,
                total_commission=base_stats.total_commission,
            )

        return results

    def get_best_trades(self, n: int = 5) -> list[TradeSummary]:
        """获取最佳交易 (按 PnL)

        Args:
            n: 返回数量

        Returns:
            交易列表 (按 PnL 降序)
        """
        sorted_trades = sorted(self._trades, key=lambda t: t.pnl, reverse=True)
        return sorted_trades[:n]

    def get_worst_trades(self, n: int = 5) -> list[TradeSummary]:
        """获取最差交易 (按 PnL)

        Args:
            n: 返回数量

        Returns:
            交易列表 (按 PnL 升序)
        """
        sorted_trades = sorted(self._trades, key=lambda t: t.pnl)
        return sorted_trades[:n]

    def get_holding_period_stats(self) -> dict:
        """获取持仓周期统计

        Returns:
            {
                "min": 最短持仓天数,
                "max": 最长持仓天数,
                "avg": 平均持仓天数,
                "median": 中位数,
                "distribution": {
                    "0-7": count,
                    "8-14": count,
                    ...
                }
            }
        """
        if not self._trades:
            return {}

        holding_days = [t.holding_days for t in self._trades]

        # 计算分布
        distribution = {
            "0-7": 0,
            "8-14": 0,
            "15-21": 0,
            "22-30": 0,
            "31-45": 0,
            "46-60": 0,
            "60+": 0,
        }

        for days in holding_days:
            if days <= 7:
                distribution["0-7"] += 1
            elif days <= 14:
                distribution["8-14"] += 1
            elif days <= 21:
                distribution["15-21"] += 1
            elif days <= 30:
                distribution["22-30"] += 1
            elif days <= 45:
                distribution["31-45"] += 1
            elif days <= 60:
                distribution["46-60"] += 1
            else:
                distribution["60+"] += 1

        return {
            "min": min(holding_days),
            "max": max(holding_days),
            "avg": sum(holding_days) / len(holding_days),
            "median": float(np.median(holding_days)),
            "distribution": distribution,
        }

    def get_exit_reason_stats(self) -> dict[str, TradeStats]:
        """按平仓原因分组统计

        Returns:
            {exit_reason: TradeStats}
        """
        by_reason: dict[str, list[TradeSummary]] = defaultdict(list)
        for trade in self._trades:
            by_reason[trade.exit_reason].append(trade)

        results = {}
        for reason, trades in by_reason.items():
            results[reason] = self._calc_stats(trades)

        return results

    def get_strike_selection_stats(self) -> dict:
        """获取行权价选择统计

        Returns:
            按 delta 区间的交易统计
        """
        # 简化实现 - 如果有 delta 数据则统计
        # 由于 TradeRecord 可能没有 delta 信息，这里返回基本统计
        if not self._trades:
            return {}

        strikes = [t.strike for t in self._trades if t.strike > 0]
        if not strikes:
            return {}

        return {
            "min_strike": min(strikes),
            "max_strike": max(strikes),
            "avg_strike": sum(strikes) / len(strikes),
            "strike_count": len(set(strikes)),
        }

    def to_dataframe(self):
        """转换为 pandas DataFrame

        Returns:
            DataFrame 包含所有交易
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas is required for to_dataframe()")

        data = []
        for trade in self._trades:
            data.append({
                "position_id": trade.position_id,
                "symbol": trade.symbol,
                "underlying": trade.underlying,
                "option_type": trade.option_type,
                "strike": trade.strike,
                "expiration": trade.expiration,
                "entry_date": trade.entry_date,
                "exit_date": trade.exit_date,
                "quantity": trade.quantity,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "pnl": trade.pnl,
                "return_pct": trade.return_pct,
                "holding_days": trade.holding_days,
                "exit_reason": trade.exit_reason,
                "commission": trade.commission,
            })

        return pd.DataFrame(data)

    def summary_report(self) -> str:
        """生成分析报告

        Returns:
            格式化的文本报告
        """
        lines = ["=== Trade Analysis Report ===", ""]

        # 总体统计
        total_stats = self._calc_stats(self._trades)
        lines.extend([
            "--- Overall Statistics ---",
            f"  Total Trades:      {total_stats.count}",
            f"  Win/Loss:          {total_stats.winning}/{total_stats.losing}",
            f"  Win Rate:          {total_stats.win_rate:.1%}",
            f"  Total PnL:         ${total_stats.total_pnl:,.2f}",
            f"  Avg PnL:           ${total_stats.avg_pnl:,.2f}",
            f"  Profit Factor:     {total_stats.profit_factor:.2f}" if total_stats.profit_factor else "  Profit Factor:     N/A",
            f"  Avg Holding Days:  {total_stats.avg_holding_days:.1f}" if total_stats.avg_holding_days else "  Avg Holding Days:  N/A",
            "",
        ])

        # 按标的统计
        by_symbol = self.group_by_symbol()
        if by_symbol:
            lines.extend(["--- By Symbol ---"])
            for symbol, stats in sorted(by_symbol.items(), key=lambda x: x[1].total_pnl, reverse=True):
                lines.append(f"  {symbol:8} {stats.count:3} trades, ${stats.total_pnl:>10,.2f}, {stats.win_rate:.0%} win")
            lines.append("")

        # 最佳/最差交易
        best = self.get_best_trades(3)
        worst = self.get_worst_trades(3)

        if best:
            lines.extend(["--- Best Trades ---"])
            for trade in best:
                lines.append(f"  {trade.underlying:8} ${trade.pnl:>8,.2f}  {trade.entry_date} - {trade.exit_date}")
            lines.append("")

        if worst:
            lines.extend(["--- Worst Trades ---"])
            for trade in worst:
                lines.append(f"  {trade.underlying:8} ${trade.pnl:>8,.2f}  {trade.entry_date} - {trade.exit_date}")
            lines.append("")

        # 持仓周期分布
        holding_stats = self.get_holding_period_stats()
        if holding_stats:
            lines.extend([
                "--- Holding Period Distribution ---",
                f"  Min: {holding_stats['min']} days, Max: {holding_stats['max']} days",
                f"  Avg: {holding_stats['avg']:.1f} days, Median: {holding_stats['median']:.0f} days",
            ])
            for period, count in holding_stats["distribution"].items():
                if count > 0:
                    lines.append(f"    {period:8} days: {count} trades")

        return "\n".join(lines)
