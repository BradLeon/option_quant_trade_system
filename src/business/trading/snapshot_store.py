"""Live Snapshot Store — JSONL append-only storage for daily snapshots.

Storage path: data/trading/snapshots/{strategy_name}/snapshots.jsonl
Each line is one JSON object representing a LiveDailySnapshot.
Same-day writes are idempotent (overwrite existing entry for that date).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from src.business.trading.models.snapshot import LiveDailySnapshot

logger = logging.getLogger(__name__)

DEFAULT_BASE_PATH = "data/trading/snapshots"


class LiveSnapshotStore:
    """JSONL append-only storage for live daily snapshots."""

    def __init__(self, base_path: str = DEFAULT_BASE_PATH) -> None:
        self._base_path = Path(base_path)

    def _strategy_path(self, strategy_name: str) -> Path:
        return self._base_path / strategy_name / "snapshots.jsonl"

    def save(self, snapshot: LiveDailySnapshot) -> None:
        """Save a snapshot. Same-day entries are overwritten (idempotent)."""
        path = self._strategy_path(snapshot.strategy_name)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing lines, filter out same-date entries
        existing_lines: list[str] = []
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("date") == snapshot.date.isoformat():
                            continue  # Skip same-date entry
                        existing_lines.append(line)
                    except json.JSONDecodeError:
                        existing_lines.append(line)  # Keep malformed lines

        # Append new snapshot
        new_line = json.dumps(snapshot.to_dict(), ensure_ascii=False)
        existing_lines.append(new_line)

        # Write back
        with open(path, "w", encoding="utf-8") as f:
            for line in existing_lines:
                f.write(line + "\n")

        logger.debug(
            f"Snapshot saved: {snapshot.strategy_name} {snapshot.date} "
            f"NLV={snapshot.nlv:,.0f}"
        )

    def load(
        self,
        strategy_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[LiveDailySnapshot]:
        """Load snapshots for a strategy, optionally filtered by date range."""
        path = self._strategy_path(strategy_name)
        if not path.exists():
            return []

        snapshots: list[LiveDailySnapshot] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    snap = LiveDailySnapshot.from_dict(data)
                    if start_date and snap.date < start_date:
                        continue
                    if end_date and snap.date > end_date:
                        continue
                    snapshots.append(snap)
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"Skipping malformed snapshot line: {e}")

        snapshots.sort(key=lambda s: s.date)
        return snapshots

    def get_strategies(self) -> list[str]:
        """List all strategies that have snapshot data."""
        if not self._base_path.exists():
            return []
        strategies = []
        for d in sorted(self._base_path.iterdir()):
            if d.is_dir() and (d / "snapshots.jsonl").exists():
                strategies.append(d.name)
        return strategies
