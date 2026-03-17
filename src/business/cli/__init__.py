"""
Business Layer CLI - 业务层命令行工具

V2 命令：
- strategy: V2 策略实盘执行 (Signal → RiskGuard → OrderRequest → Provider)
- dashboard: 实时监控仪表盘
- notify: 测试通知发送
"""

from src.business.cli.main import cli

__all__ = ["cli"]
