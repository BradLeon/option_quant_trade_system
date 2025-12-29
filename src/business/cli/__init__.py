"""
Business Layer CLI - 业务层命令行工具

提供命令：
- screen: 运行开仓筛选
- monitor: 运行持仓监控
- notify: 测试通知发送
- dashboard: 实时监控仪表盘
"""

from src.business.cli.main import cli

__all__ = ["cli"]
