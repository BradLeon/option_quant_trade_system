"""Unified Execution Log — structured pipeline trace for all strategies.

Every strategy inheriting from Strategy automatically gets self.log() and
self.execution_log. The executor appends its own pipeline steps (snapshot,
risk guards, conversion, execution) to produce a complete trace.

Designed to be lightweight (list appends only) so backtest performance
is not affected. The CLI renders the trace for human consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LogEntry:
    """Single step in the execution pipeline."""

    step: str  # e.g. "sma_filter", "option_chain:AAPL"
    status: str  # "pass", "fail", "skip", "error", "info"
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        parts = [f"[{self.step}]", self.status.upper()]
        for k, v in self.detail.items():
            if isinstance(v, float):
                parts.append(f"{k}={v:.4f}")
            else:
                parts.append(f"{k}={v}")
        return " ".join(parts)


class ExecutionLog:
    """Structured execution log — append-only list of LogEntry.

    Usage in strategies:
        self.log("sma_filter", "pass", symbol="AAPL", close=260.3, sma=242.1)
        self.log("technical:AAPL", "fail", rsi=72.1, reason="RSI > 70")

    Usage in executor:
        log = ExecutionLog()
        log.record("market_snapshot", "ok", symbols=["AAPL"], vix=25.4)
        log.extend(strategy.execution_log)  # merge strategy entries
        log.record("risk_guards", "ok", before=3, after=2)
    """

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []

    def record(self, step: str, status: str, **detail: Any) -> None:
        """Append a log entry."""
        self._entries.append(LogEntry(step=step, status=status, detail=detail))

    def extend(self, other: ExecutionLog) -> None:
        """Merge entries from another log (e.g. strategy log into executor log)."""
        self._entries.extend(other._entries)

    @property
    def entries(self) -> list[LogEntry]:
        return self._entries

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def format_text(self) -> str:
        """Format log as human-readable text for CLI display."""
        if not self._entries:
            return ""

        lines: list[str] = []
        step_num = 0
        current_group = ""

        for entry in self._entries:
            # Group by top-level step (before ':')
            group = entry.step.split(":")[0] if ":" in entry.step else entry.step

            if group != current_group:
                step_num += 1
                current_group = group
                ts = entry.timestamp.strftime("%H:%M:%S")
                lines.append("")
                lines.append(f"  [{ts}] Step {step_num}: {_step_title(entry.step)}")
                lines.append(f"  {'─' * 56}")

            # Format status icon
            icon = _status_icon(entry.status)

            # Format detail
            detail_parts = []
            extra_lines: list[str] = []
            for k, v in entry.detail.items():
                if k == "signals":
                    # Signal list: show each on its own line
                    for sig_desc in v:
                        extra_lines.append(f"       → {sig_desc}")
                    continue
                if k == "rejected_by" and isinstance(v, dict) and v:
                    # Rejection breakdown: show as indented detail
                    parts = [f"{rk}={rv}" for rk, rv in v.items()]
                    extra_lines.append(f"       rejected: {', '.join(parts)}")
                    continue
                if k == "reject_detail" and isinstance(v, list) and v:
                    # Per-contract rejection details
                    for sample in v:
                        extra_lines.append(f"         · {sample}")
                    continue
                if k == "positions" and isinstance(v, list):
                    for pos_desc in v:
                        extra_lines.append(f"       {pos_desc}")
                    continue
                if isinstance(v, dict):
                    for dk, dv in v.items():
                        extra_lines.append(f"       {dk}={_fmt_value(dv)}")
                    continue
                if isinstance(v, float):
                    # Smart decimal formatting based on magnitude
                    if abs(v) >= 100:
                        detail_parts.append(f"{k}={v:,.2f}")
                    elif abs(v) >= 1:
                        detail_parts.append(f"{k}={v:.2f}")
                    else:
                        detail_parts.append(f"{k}={v:.4f}")
                else:
                    detail_parts.append(f"{k}={v}")
            detail_str = ", ".join(detail_parts)

            # Sub-step label (after ':')
            label = entry.step.split(":", 1)[1] if ":" in entry.step else ""
            if label:
                lines.append(f"    {icon} [{label}] {detail_str}")
            else:
                lines.append(f"    {icon} {detail_str}")

            # Extra detail lines (signals, rejections, positions)
            for extra in extra_lines:
                lines.append(extra)

        return "\n".join(lines)


def _fmt_value(v: Any) -> str:
    """Format a single value for display."""
    if isinstance(v, float):
        if abs(v) >= 100:
            return f"{v:,.2f}"
        elif abs(v) >= 1:
            return f"{v:.2f}"
        else:
            return f"{v:.4f}"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def _status_icon(status: str) -> str:
    return {
        "pass": "✓",
        "ok": "✓",
        "fail": "✗",
        "skip": "–",
        "error": "✗",
        "info": "·",
    }.get(status, "·")


def _step_title(step: str) -> str:
    """Human-readable step title."""
    base = step.split(":")[0]
    return {
        "market_snapshot": "构建市场快照",
        "portfolio_state": "构建组合状态",
        "strategy_call": "策略信号生成",
        "portfolio": "组合状态",
        "day_start": "策略初始化",
        "exit_scan": "退出信号扫描",
        "exit_context": "退出信号上下文",
        "exit_signals": "退出信号汇总",
        "trend_filter": "趋势过滤",
        "technical_filter": "技术指标过滤",
        "option_chain": "期权链获取",
        "contract_select": "合约筛选",
        "entry_signal": "入场信号",
        "entry_context": "入场信号上下文",
        "entry_signals": "入场信号汇总",
        "risk_guards": "风控过滤",
        "signal_convert": "信号转换",
        "execution": "执行",
    }.get(base, base)
