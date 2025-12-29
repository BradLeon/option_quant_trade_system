"""Dashboard UI components.

Provides helper functions for rendering dashboard elements:
- Progress bars
- Alert icons
- Metric formatting
- Table rendering
"""

from typing import Optional

from src.business.monitoring.models import AlertLevel


def progress_bar(
    value: float,
    min_val: float,
    max_val: float,
    width: int = 10,
    fill_char: str = "█",
    empty_char: str = "░",
) -> str:
    """Generate a progress bar string.

    Args:
        value: Current value
        min_val: Minimum value (0% fill)
        max_val: Maximum value (100% fill)
        width: Total width of the bar
        fill_char: Character for filled portion
        empty_char: Character for empty portion

    Returns:
        Progress bar string like [████████░░]

    Example:
        >>> progress_bar(75, 0, 100, 10)
        '[███████░░░]'
    """
    if max_val <= min_val:
        return f"[{empty_char * width}]"

    # Clamp value to range
    clamped = max(min_val, min(max_val, value))
    ratio = (clamped - min_val) / (max_val - min_val)
    filled = int(ratio * width)
    empty = width - filled

    return f"[{fill_char * filled}{empty_char * empty}]"


def alert_icon(level: AlertLevel) -> str:
    """Return emoji icon for alert level.

    Args:
        level: AlertLevel enum value

    Returns:
        Emoji string: 🔴 (red), 🟡 (yellow), 🟢 (green)
    """
    icons = {
        AlertLevel.RED: "🔴",
        AlertLevel.YELLOW: "🟡",
        AlertLevel.GREEN: "🟢",
    }
    return icons.get(level, "⚪")


def urgency_icon(urgency: str) -> str:
    """Return emoji icon for urgency level.

    Args:
        urgency: Urgency level string (immediate/soon/monitor)

    Returns:
        Emoji string
    """
    icons = {
        "immediate": "🚨",
        "soon": "⚡",
        "monitor": "👁️",
    }
    return icons.get(urgency.lower(), "📌")


def format_metric(
    value: Optional[float],
    fmt: str = ".2f",
    prefix: str = "",
    suffix: str = "",
    na_str: str = "-",
) -> str:
    """Format a metric value with optional prefix/suffix.

    Args:
        value: Numeric value or None
        fmt: Format string for the number
        prefix: Prefix string (e.g., "+" for positive)
        suffix: Suffix string (e.g., "%")
        na_str: String to display if value is None

    Returns:
        Formatted string

    Example:
        >>> format_metric(0.25, ".1%")
        '25.0%'
        >>> format_metric(163, "+.0f")
        '+163'
    """
    if value is None:
        return na_str

    if fmt.endswith("%"):
        # Percentage format
        return f"{prefix}{value * 100:{fmt[:-1]}}{suffix}%"
    else:
        return f"{prefix}{value:{fmt}}{suffix}"


def format_delta(value: Optional[float], multiplier: int = 100) -> str:
    """Format delta value with sign and multiplier.

    Args:
        value: Raw delta value
        multiplier: Contract multiplier (default 100)

    Returns:
        Formatted string like "+30" or "-45"
    """
    if value is None:
        return "-"
    scaled = value * multiplier
    return f"{scaled:+.0f}"


def format_pct(value: Optional[float], decimals: int = 1) -> str:
    """Format value as percentage.

    Args:
        value: Decimal value (0.25 = 25%)
        decimals: Number of decimal places

    Returns:
        Formatted percentage string
    """
    if value is None:
        return "-"
    return f"{value * 100:.{decimals}f}%"


def box_title(title: str, width: int = 40) -> str:
    """Create a box title line.

    Args:
        title: Title text
        width: Total width of the box

    Returns:
        Formatted title line like "┌─── Title ───────────┐"
    """
    padding = width - len(title) - 6  # 6 = "┌─── " + " ─┐"
    if padding < 2:
        padding = 2
    return f"┌─── {title} {'─' * padding}┐"


def box_line(content: str, width: int = 40) -> str:
    """Create a box content line.

    Args:
        content: Line content
        width: Total width of the box

    Returns:
        Formatted content line like "│ content            │"
    """
    padding = width - len(content) - 4  # 4 = "│ " + " │"
    if padding < 0:
        content = content[:width - 4]
        padding = 0
    return f"│ {content}{' ' * padding} │"


def box_bottom(width: int = 40) -> str:
    """Create a box bottom line.

    Args:
        width: Total width of the box

    Returns:
        Bottom line like "└────────────────────┘"
    """
    return f"└{'─' * (width - 2)}┘"


def table_header(columns: list[tuple[str, int]], separator: str = "│") -> str:
    """Create a table header line.

    Args:
        columns: List of (name, width) tuples
        separator: Column separator character

    Returns:
        Header line string
    """
    parts = []
    for name, width in columns:
        parts.append(f"{name:^{width}}")
    return f"{separator}{separator.join(parts)}{separator}"


def table_separator(columns: list[tuple[str, int]], char: str = "─") -> str:
    """Create a table separator line.

    Args:
        columns: List of (name, width) tuples
        char: Separator character

    Returns:
        Separator line string
    """
    parts = [char * width for _, width in columns]
    return f"┼{'┼'.join(parts)}┼"


def table_row(values: list[str], columns: list[tuple[str, int]], separator: str = "│") -> str:
    """Create a table data row.

    Args:
        values: List of cell values
        columns: List of (name, width) tuples
        separator: Column separator character

    Returns:
        Row line string
    """
    parts = []
    for i, (_, width) in enumerate(columns):
        val = values[i] if i < len(values) else ""
        # Right-align numbers, left-align text
        if val.lstrip("+-").replace(".", "").replace("%", "").isdigit():
            parts.append(f"{val:>{width}}")
        else:
            parts.append(f"{val:<{width}}")
    return f"{separator}{separator.join(parts)}{separator}"


def side_by_side(left: list[str], right: list[str], gap: int = 2) -> list[str]:
    """Combine two column layouts side by side.

    Args:
        left: Lines for left column
        right: Lines for right column
        gap: Number of spaces between columns

    Returns:
        Combined lines
    """
    # Find max width of left column
    left_width = max(len(line) for line in left) if left else 0

    result = []
    max_lines = max(len(left), len(right))

    for i in range(max_lines):
        left_line = left[i] if i < len(left) else ""
        right_line = right[i] if i < len(right) else ""
        result.append(f"{left_line:<{left_width}}{' ' * gap}{right_line}")

    return result
