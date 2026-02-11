"""
配置模式枚举

定义 LIVE 和 BACKTEST 两种配置模式，用于在运行时加载不同的配置值。
"""

from enum import Enum


class ConfigMode(Enum):
    """配置模式

    LIVE: 实盘模式
        - paper 和 live 账户都使用此模式
        - 使用严格的生产环境默认值
        - 配置来源: YAML 文件 > dataclass 默认值

    BACKTEST: 回测模式
        - 允许放宽参数以便测试
        - 应用 backtest_overrides 覆盖
        - 配置来源: BacktestConfig 覆盖 > YAML backtest_overrides > YAML 主配置 > dataclass 默认值
    """

    LIVE = "live"
    BACKTEST = "backtest"
