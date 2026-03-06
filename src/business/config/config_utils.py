"""
Config Utilities - 配置工具函数

所有配置模块共享的工具函数。
"""

from typing import Any


def merge_overrides(
    base: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """递归深合并覆盖配置到基础配置

    用于 backtest_overrides 等场景：将覆盖字典递归合并到基础字典中。
    - 嵌套 dict：递归合并
    - 其他类型：直接覆盖
    - 跳过 "backtest_overrides" 键本身

    Args:
        base: 基础配置字典
        overrides: 覆盖字典

    Returns:
        合并后的配置字典（不修改原字典）
    """
    result = base.copy()
    for key, value in overrides.items():
        if key == "backtest_overrides":
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_overrides(result[key], value)
        else:
            result[key] = value
    return result
