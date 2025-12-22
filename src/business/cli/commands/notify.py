"""
Notify Command - 通知测试命令

测试飞书通知推送功能。
"""

import logging
from typing import Optional

import click

from src.business.monitoring.models import Alert, AlertLevel, AlertType
from src.business.notification.channels.feishu import FeishuChannel, FeishuCardBuilder
from src.business.notification.dispatcher import MessageDispatcher


logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--type",
    "-t",
    "msg_type",
    type=click.Choice(["text", "alert", "test"]),
    default="test",
    help="消息类型：text (文本)、alert (预警卡片)、test (测试消息)",
)
@click.option(
    "--title",
    "-T",
    default=None,
    help="消息标题",
)
@click.option(
    "--content",
    "-c",
    default=None,
    help="消息内容",
)
@click.option(
    "--level",
    "-l",
    type=click.Choice(["red", "yellow", "green"]),
    default="yellow",
    help="预警级别（仅 alert 类型有效）",
)
@click.option(
    "--webhook",
    "-w",
    envvar="FEISHU_WEBHOOK_URL",
    help="飞书 Webhook URL（也可通过 FEISHU_WEBHOOK_URL 环境变量设置）",
)
@click.option(
    "--secret",
    "-s",
    envvar="FEISHU_WEBHOOK_SECRET",
    help="飞书签名密钥（也可通过 FEISHU_WEBHOOK_SECRET 环境变量设置）",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细日志",
)
def notify(
    msg_type: str,
    title: Optional[str],
    content: Optional[str],
    level: str,
    webhook: Optional[str],
    secret: Optional[str],
    verbose: bool,
) -> None:
    """测试飞书通知推送

    支持发送文本消息、预警卡片等。

    \b
    示例：
      # 发送测试消息
      optrade notify

      # 发送自定义文本
      optrade notify -t text -T "测试标题" -c "这是测试内容"

      # 发送预警卡片
      optrade notify -t alert -l red -c "发现重要风险预警"

      # 指定 Webhook URL
      optrade notify -w https://open.feishu.cn/open-apis/bot/v2/hook/xxx
    """
    # 配置日志
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    click.echo("📤 发送飞书通知")
    click.echo("-" * 50)

    try:
        # 创建通知渠道
        if webhook:
            channel = FeishuChannel(webhook_url=webhook, secret=secret)
        else:
            channel = FeishuChannel.from_env()

        # 根据类型发送消息
        if msg_type == "test":
            _send_test_message(channel)
        elif msg_type == "text":
            _send_text_message(channel, title, content)
        elif msg_type == "alert":
            _send_alert_message(channel, title, content, level)

    except ValueError as e:
        click.echo(f"❌ 配置错误: {e}", err=True)
        click.echo("💡 提示: 请设置 FEISHU_WEBHOOK_URL 环境变量或使用 -w 参数指定 Webhook URL")
        raise SystemExit(1)
    except Exception as e:
        logger.exception("发送通知出错")
        click.echo(f"❌ 发送失败: {e}", err=True)
        raise SystemExit(1)


def _send_test_message(channel: FeishuChannel) -> None:
    """发送测试消息"""
    click.echo("📝 发送测试消息...")

    card_data = FeishuCardBuilder.create_alert_card(
        title="🧪 期权量化系统测试",
        level="green",
        message="恭喜！飞书通知配置成功，系统可以正常推送消息。",
        details={
            "系统": "期权量化交易系统",
            "模块": "通知推送",
            "状态": "正常",
        },
        suggestion="这是一条测试消息，无需操作",
    )

    result = channel.send_card(card_data)

    if result.is_success:
        click.echo(f"✅ 发送成功！消息 ID: {result.message_id}")
    else:
        click.echo(f"❌ 发送失败: {result.error}")
        raise SystemExit(1)


def _send_text_message(
    channel: FeishuChannel,
    title: Optional[str],
    content: Optional[str],
) -> None:
    """发送文本消息"""
    title = title or "通知"
    content = content or "这是一条测试通知"

    click.echo(f"📝 发送文本消息: {title}")

    result = channel.send(title, content)

    if result.is_success:
        click.echo(f"✅ 发送成功！消息 ID: {result.message_id}")
    else:
        click.echo(f"❌ 发送失败: {result.error}")
        raise SystemExit(1)


def _send_alert_message(
    channel: FeishuChannel,
    title: Optional[str],
    content: Optional[str],
    level: str,
) -> None:
    """发送预警卡片"""
    level_config = {
        "red": ("🔴 风险预警", "发现重要风险，请立即处理"),
        "yellow": ("🟡 关注提醒", "发现需要关注的情况"),
        "green": ("🟢 机会提示", "发现潜在机会"),
    }

    default_title, default_content = level_config.get(level, level_config["yellow"])
    title = title or default_title
    content = content or default_content

    click.echo(f"📝 发送预警卡片: {title} ({level})")

    card_data = FeishuCardBuilder.create_alert_card(
        title=title,
        level=level,
        message=content,
    )

    result = channel.send_card(card_data)

    if result.is_success:
        click.echo(f"✅ 发送成功！消息 ID: {result.message_id}")
    else:
        click.echo(f"❌ 发送失败: {result.error}")
        raise SystemExit(1)


@click.command("notify-config")
def notify_config() -> None:
    """显示通知配置状态

    检查飞书 Webhook 配置是否正确。
    """
    import os

    click.echo("🔧 通知配置检查")
    click.echo("-" * 50)

    # 检查环境变量
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    webhook_secret = os.environ.get("FEISHU_WEBHOOK_SECRET")

    if webhook_url:
        # 隐藏敏感信息
        masked_url = webhook_url[:50] + "..." if len(webhook_url) > 50 else webhook_url
        click.echo(f"✅ FEISHU_WEBHOOK_URL: {masked_url}")
    else:
        click.echo("❌ FEISHU_WEBHOOK_URL: 未设置")

    if webhook_secret:
        click.echo(f"✅ FEISHU_WEBHOOK_SECRET: {'*' * 10}")
    else:
        click.echo("⚠️ FEISHU_WEBHOOK_SECRET: 未设置（签名验证已禁用）")

    click.echo()
    click.echo("💡 配置方法:")
    click.echo("   export FEISHU_WEBHOOK_URL='https://open.feishu.cn/open-apis/bot/v2/hook/xxx'")
    click.echo("   export FEISHU_WEBHOOK_SECRET='your-secret-key'")
