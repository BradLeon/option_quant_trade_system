"""
Backtest Configuration - 回测配置

定义回测的配置参数，支持 YAML 文件加载。

Usage:
    # 从 YAML 加载
    config = BacktestConfig.from_yaml("config/backtest/short_put.yaml")

    # 或直接创建
    config = BacktestConfig(
        name="SHORT_PUT_2020_2024",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        symbols=["AAPL", "MSFT", "NVDA"],
        strategy_type="SHORT_PUT",
    )
"""

import os
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml

from src.business.config.config_mode import ConfigMode


class PriceMode(str, Enum):
    """回测价格模式

    决定回测中使用哪个价格进行交易执行和持仓估值。

    - OPEN: 使用开盘价（推荐，更贴近实盘执行）
    - CLOSE: 使用收盘价（传统回测方式）
    - MID: 使用中间价 (bid+ask)/2 或 (open+close)/2
    """

    OPEN = "open"
    CLOSE = "close"
    MID = "mid"


@dataclass
class BacktestConfig:
    """回测配置

    定义回测的所有参数，包括:
    - 时间范围
    - 标的池
    - 策略配置
    - 资金配置
    - 执行配置 (滑点、手续费)
    """

    # ========== 基本信息 ==========
    name: str  # 回测名称 (用于报告)
    description: str = ""

    # ========== 时间范围 ==========
    start_date: date = field(default_factory=lambda: date(2020, 1, 1))
    end_date: date = field(default_factory=date.today)

    # ========== 标的池 ==========
    symbols: list[str] = field(default_factory=list)
    market: Literal["US", "HK"] = "US"

    # ========== 策略配置 (复用现有配置) ==========
    # 指向现有的筛选/监控配置文件
    screening_config: str = "config/screening/short_put.yaml"
    monitoring_config: str = "config/monitoring/thresholds.yaml"
    strategy_type: Literal["SHORT_PUT", "COVERED_CALL"] = "SHORT_PUT"

    # ========== 资金配置 ==========
    initial_capital: float = 100_000.0  # 初始资金
    max_margin_utilization: float = 0.70  # 最大保证金使用率
    max_position_pct: float = 0.10  # 单标的最大仓位占比
    max_positions: int = 10  # 最大持仓数量

    # ========== 执行配置 ==========
    slippage_pct: float = 0.001  # 滑点百分比 (0.1%)

    # 佣金配置 (IBKR Tiered 定价)
    # Option: 每张 $0.65，每笔最低 $1.00
    # Stock: 每股 $0.005，每笔最低 $1.00
    commission_per_contract: float = 0.65  # 期权每张合约手续费 (deprecated, 使用 option_commission_per_contract)
    option_commission_per_contract: float = 0.65  # 期权每张合约手续费
    option_commission_min_per_order: float = 1.00  # 期权每笔最低手续费
    stock_commission_per_share: float = 0.005  # 股票每股手续费
    stock_commission_min_per_order: float = 1.00  # 股票每笔最低手续费

    # ========== 数据配置 ==========
    data_dir: str = "data/backtest"  # Parquet 数据目录

    # ========== 价格模式 ==========
    # 决定交易执行和持仓估值使用的价格
    # - "open": 开盘价（推荐，更贴近实盘执行）
    # - "close": 收盘价（传统回测方式）
    # - "mid": 中间价
    price_mode: str = "close"

    # ========== 其他选项 ==========
    random_seed: int | None = None  # 随机种子 (用于可重复性)
    verbose: bool = False  # 详细日志

    # ========== 配置模式 (始终为 BACKTEST) ==========
    # BacktestConfig 始终使用 BACKTEST 模式
    # 该字段不可在初始化时修改
    config_mode: ConfigMode = field(default=ConfigMode.BACKTEST, init=False)

    # ========== 配置覆盖 (优先级最高) ==========
    # 这些覆盖会应用在 BACKTEST 模式默认值之上
    # 用于进一步自定义回测参数
    risk_overrides: dict[str, Any] = field(default_factory=dict)
    screening_overrides: dict[str, Any] = field(default_factory=dict)
    monitoring_overrides: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """初始化后验证"""
        # 确保 symbols 是列表
        if isinstance(self.symbols, str):
            self.symbols = [s.strip() for s in self.symbols.split(",")]

        # 确保日期是 date 类型
        if isinstance(self.start_date, str):
            self.start_date = date.fromisoformat(self.start_date)
        if isinstance(self.end_date, str):
            self.end_date = date.fromisoformat(self.end_date)

        # 验证日期范围 (允许单日回测)
        if self.start_date > self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must not be after end_date ({self.end_date})"
            )

        # 标准化 symbols
        self.symbols = [s.upper() for s in self.symbols]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BacktestConfig":
        """从 YAML 文件加载配置

        Args:
            path: YAML 文件路径

        Returns:
            BacktestConfig 实例

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 配置无效
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 处理配置继承
        if "inherit" in data:
            parent_path = Path(data.pop("inherit"))
            if not parent_path.is_absolute():
                parent_path = path.parent / parent_path
            parent = cls.from_yaml(parent_path)
            # 合并配置，子配置覆盖父配置
            parent_dict = parent.to_dict()
            parent_dict.update(data)
            data = parent_dict

        # 环境变量替换
        data = cls._substitute_env_vars(data)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BacktestConfig":
        """从字典创建配置

        Args:
            data: 配置字典

        Returns:
            BacktestConfig 实例
        """
        # 过滤只保留 dataclass 字段
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典

        Returns:
            配置字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "symbols": self.symbols,
            "market": self.market,
            "screening_config": self.screening_config,
            "monitoring_config": self.monitoring_config,
            "strategy_type": self.strategy_type,
            "initial_capital": self.initial_capital,
            "max_margin_utilization": self.max_margin_utilization,
            "max_position_pct": self.max_position_pct,
            "max_positions": self.max_positions,
            "slippage_pct": self.slippage_pct,
            # 佣金配置
            "option_commission_per_contract": self.option_commission_per_contract,
            "option_commission_min_per_order": self.option_commission_min_per_order,
            "stock_commission_per_share": self.stock_commission_per_share,
            "stock_commission_min_per_order": self.stock_commission_min_per_order,
            "data_dir": self.data_dir,
            "price_mode": self.price_mode,
            "random_seed": self.random_seed,
            "verbose": self.verbose,
            # 配置覆盖
            "risk_overrides": self.risk_overrides,
            "screening_overrides": self.screening_overrides,
            "monitoring_overrides": self.monitoring_overrides,
        }

    def to_yaml(self, path: str | Path) -> None:
        """保存配置到 YAML 文件

        Args:
            path: 输出路径
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True)

    @staticmethod
    def _substitute_env_vars(data: dict[str, Any]) -> dict[str, Any]:
        """替换环境变量

        支持 ${VAR} 或 $VAR 格式

        Args:
            data: 原始配置字典

        Returns:
            替换后的配置字典
        """

        def _substitute(value: Any) -> Any:
            if isinstance(value, str):
                # 替换 ${VAR} 格式
                import re

                pattern = r"\$\{(\w+)\}|\$(\w+)"
                matches = re.findall(pattern, value)
                for match in matches:
                    var_name = match[0] or match[1]
                    env_value = os.environ.get(var_name)
                    if env_value:
                        if match[0]:
                            value = value.replace(f"${{{var_name}}}", env_value)
                        else:
                            value = value.replace(f"${var_name}", env_value)
                return value
            elif isinstance(value, dict):
                return {k: _substitute(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [_substitute(v) for v in value]
            return value

        return _substitute(data)

    @property
    def duration_days(self) -> int:
        """回测时长 (天数)"""
        return (self.end_date - self.start_date).days

    @property
    def duration_years(self) -> float:
        """回测时长 (年数)"""
        return self.duration_days / 365.25

    def validate(self) -> list[str]:
        """验证配置

        Returns:
            错误信息列表 (空表示验证通过)
        """
        errors = []

        # 必填字段
        if not self.name:
            errors.append("name is required")
        if not self.symbols:
            errors.append("symbols is required")

        # 日期范围
        if self.start_date >= self.end_date:
            errors.append(
                f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
            )

        # 资金配置
        if self.initial_capital <= 0:
            errors.append("initial_capital must be positive")
        if not 0 < self.max_margin_utilization <= 1:
            errors.append("max_margin_utilization must be between 0 and 1")
        if not 0 < self.max_position_pct <= 1:
            errors.append("max_position_pct must be between 0 and 1")

        # 执行配置
        if self.slippage_pct < 0:
            errors.append("slippage_pct must be non-negative")
        if self.option_commission_per_contract < 0:
            errors.append("option_commission_per_contract must be non-negative")
        if self.option_commission_min_per_order < 0:
            errors.append("option_commission_min_per_order must be non-negative")
        if self.stock_commission_per_share < 0:
            errors.append("stock_commission_per_share must be non-negative")
        if self.stock_commission_min_per_order < 0:
            errors.append("stock_commission_min_per_order must be non-negative")

        # 配置文件存在性 (警告级别)
        screening_path = Path(self.screening_config)
        if not screening_path.exists():
            errors.append(f"screening_config not found: {self.screening_config}")

        monitoring_path = Path(self.monitoring_config)
        if not monitoring_path.exists():
            errors.append(f"monitoring_config not found: {self.monitoring_config}")

        return errors


def create_sample_config(path: str | Path) -> None:
    """创建示例配置文件

    Args:
        path: 输出路径
    """
    sample = BacktestConfig(
        name="SHORT_PUT_SAMPLE",
        description="Sample backtest configuration for SHORT_PUT strategy",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        symbols=["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"],
        market="US",
        screening_config="config/screening/short_put.yaml",
        monitoring_config="config/monitoring/thresholds.yaml",
        strategy_type="SHORT_PUT",
        initial_capital=100_000.0,
        max_margin_utilization=0.70,
        max_position_pct=0.10,
        max_positions=10,
        slippage_pct=0.001,
        # IBKR Tiered 定价
        option_commission_per_contract=0.65,
        option_commission_min_per_order=1.00,
        stock_commission_per_share=0.005,
        stock_commission_min_per_order=1.00,
        data_dir="/Volumes/TradingData/processed",
    )
    sample.to_yaml(path)
