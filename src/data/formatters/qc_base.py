"""Base classes for QuantConnect data format conversion.

This module provides base functionality for creating QuantConnect-compatible
custom data types. Due to the complexity of integrating with QuantConnect's
LEAN engine, these classes are designed to:

1. Work standalone for data export/import
2. Be compatible with LEAN when QuantConnect is available

Note: Full LEAN integration requires the QuantConnect package to be installed.
"""

import csv
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="BaseCustomData")


class BaseCustomData(ABC):
    """Base class for custom data compatible with QuantConnect.

    This class mimics QuantConnect's PythonData interface but can work
    standalone without LEAN installed.

    When used with LEAN, subclasses should also inherit from PythonData:
        from QuantConnect.Python import PythonData
        class MyData(BaseCustomData, PythonData):
            pass
    """

    # Required properties that map to QuantConnect fields
    time: datetime
    symbol: str
    value: float

    def __init__(self) -> None:
        """Initialize custom data."""
        self.time = datetime.min
        self.symbol = ""
        self.value = 0.0
        self._data: dict[str, Any] = {}

    @classmethod
    @abstractmethod
    def get_source_format(cls) -> str:
        """Return the data format (csv, json, etc.)."""
        pass

    @abstractmethod
    def reader(self, line: str, date: datetime) -> "BaseCustomData | None":
        """Parse a line of data and return a data instance.

        Args:
            line: A single line from the data source.
            date: The date for the data (for filtering).

        Returns:
            Parsed data instance or None if line should be skipped.
        """
        pass

    def to_csv_line(self) -> str:
        """Convert data to CSV line format.

        Override in subclass to customize format.
        """
        raise NotImplementedError("Subclass must implement to_csv_line")

    @classmethod
    def get_csv_header(cls) -> str:
        """Get CSV header line.

        Override in subclass to customize header.
        """
        raise NotImplementedError("Subclass must implement get_csv_header")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a data field value."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a data field value."""
        self._data[key] = value

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access."""
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Allow dictionary-style assignment."""
        self._data[key] = value


def export_to_csv(
    data: list[BaseCustomData],
    output_path: str | Path,
    include_header: bool = True,
) -> None:
    """Export custom data to CSV file.

    Args:
        data: List of custom data instances.
        output_path: Output file path.
        include_header: Whether to include header row.
    """
    if not data:
        logger.warning("No data to export")
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        if include_header:
            f.write(data[0].get_csv_header() + "\n")
        for item in data:
            f.write(item.to_csv_line() + "\n")

    logger.info(f"Exported {len(data)} records to {output_path}")


def import_from_csv(
    data_class: type[T],
    input_path: str | Path,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[T]:
    """Import custom data from CSV file.

    Args:
        data_class: The custom data class to instantiate.
        input_path: Input file path.
        start_date: Optional start date filter.
        end_date: Optional end date filter.

    Returns:
        List of parsed data instances.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        logger.error(f"File not found: {input_path}")
        return []

    results = []
    with open(input_path, "r") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # Skip header

        for line in reader:
            line_str = ",".join(line)
            instance = data_class()
            parsed = instance.reader(line_str, datetime.now())

            if parsed is None:
                continue

            # Apply date filters
            if start_date and parsed.time < start_date:
                continue
            if end_date and parsed.time > end_date:
                continue

            results.append(parsed)

    logger.info(f"Imported {len(results)} records from {input_path}")
    return results
