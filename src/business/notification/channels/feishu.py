"""
Feishu Channel - 飞书推送渠道

通过飞书 Webhook 发送消息到飞书群。

支持：
- 文本消息
- 卡片消息（Interactive Card）
- 签名验证
- 频率限制
"""

import hashlib
import hmac
import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from src.business.notification.channels.base import (
    NotificationChannel,
    SendResult,
    SendStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class FeishuConfig:
    """飞书配置"""

    webhook_url: str
    secret: Optional[str] = None
    timeout: int = 10

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        """从环境变量加载配置"""
        load_dotenv()
        webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")
        secret = os.getenv("FEISHU_WEBHOOK_SECRET")
        timeout = int(os.getenv("FEISHU_TIMEOUT", "10"))

        return cls(
            webhook_url=webhook_url,
            secret=secret,
            timeout=timeout,
        )

    @classmethod
    def from_yaml_config(cls, config: dict[str, Any]) -> "FeishuConfig":
        """从 YAML 配置加载"""
        webhook = config.get("webhook", {})

        # 优先使用环境变量
        url_env = webhook.get("url_env", "FEISHU_WEBHOOK_URL")
        secret_env = webhook.get("secret_env", "FEISHU_WEBHOOK_SECRET")

        webhook_url = os.getenv(url_env, webhook.get("url", ""))
        secret = os.getenv(secret_env) or webhook.get("secret")
        timeout = webhook.get("timeout", 10)

        return cls(
            webhook_url=webhook_url,
            secret=secret,
            timeout=timeout,
        )


class FeishuChannel(NotificationChannel):
    """飞书推送渠道

    使用飞书群机器人 Webhook 发送消息。

    使用方式：
        channel = FeishuChannel.from_env()
        result = channel.send("标题", "内容")

    或使用卡片消息：
        card = FeishuCardBuilder.create_alert_card(...)
        result = channel.send_card(card)
    """

    def __init__(self, config: FeishuConfig) -> None:
        """初始化飞书渠道

        Args:
            config: 飞书配置
        """
        self.config = config
        self._last_send_time: float = 0
        self._min_interval: float = 1.0  # 最小发送间隔（秒）

    @classmethod
    def from_env(cls) -> "FeishuChannel":
        """从环境变量创建"""
        return cls(FeishuConfig.from_env())

    @classmethod
    def from_yaml(cls, config: dict[str, Any]) -> "FeishuChannel":
        """从 YAML 配置创建"""
        return cls(FeishuConfig.from_yaml_config(config))

    @property
    def name(self) -> str:
        return "feishu"

    @property
    def is_available(self) -> bool:
        return bool(self.config.webhook_url)

    def _gen_sign(self, timestamp: int) -> str:
        """生成签名

        Args:
            timestamp: 时间戳（秒）

        Returns:
            签名字符串
        """
        if not self.config.secret:
            return ""

        # 拼接 timestamp 和 secret
        string_to_sign = f"{timestamp}\n{self.config.secret}"

        # HMAC-SHA256 签名
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

        # Base64 编码
        return base64.b64encode(hmac_code).decode("utf-8")

    def _rate_limit(self) -> None:
        """执行频率限制"""
        current_time = time.time()
        elapsed = current_time - self._last_send_time

        if elapsed < self._min_interval:
            sleep_time = self._min_interval - elapsed
            time.sleep(sleep_time)

        self._last_send_time = time.time()

    def send(
        self,
        title: str,
        content: str,
        **kwargs: Any,
    ) -> SendResult:
        """发送文本消息

        Args:
            title: 消息标题
            content: 消息内容

        Returns:
            SendResult
        """
        if not self.is_available:
            return SendResult(
                status=SendStatus.FAILED,
                error="Webhook URL not configured",
            )

        self._rate_limit()

        # 构建消息体
        timestamp = int(time.time())
        message = {
            "msg_type": "text",
            "content": {
                "text": f"{title}\n\n{content}",
            },
        }

        # 添加签名
        if self.config.secret:
            message["timestamp"] = str(timestamp)
            message["sign"] = self._gen_sign(timestamp)

        return self._send_request(message)

    def send_card(
        self,
        card_data: dict[str, Any],
    ) -> SendResult:
        """发送卡片消息

        Args:
            card_data: 卡片数据（飞书 Interactive Card 格式）

        Returns:
            SendResult
        """
        if not self.is_available:
            return SendResult(
                status=SendStatus.FAILED,
                error="Webhook URL not configured",
            )

        self._rate_limit()

        # 构建消息体
        timestamp = int(time.time())
        message = {
            "msg_type": "interactive",
            "card": card_data,
        }

        # 添加签名
        if self.config.secret:
            message["timestamp"] = str(timestamp)
            message["sign"] = self._gen_sign(timestamp)

        return self._send_request(message)

    def _send_request(self, message: dict[str, Any]) -> SendResult:
        """发送请求

        Args:
            message: 消息体

        Returns:
            SendResult
        """
        try:
            response = requests.post(
                self.config.webhook_url,
                json=message,
                timeout=self.config.timeout,
                proxies={"http": "", "https": ""},  # bypass env proxy
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0 or result.get("StatusCode") == 0:
                    return SendResult(
                        status=SendStatus.SUCCESS,
                        message_id=result.get("msg"),
                    )
                else:
                    return SendResult(
                        status=SendStatus.FAILED,
                        error=result.get("msg", "Unknown error"),
                        details=result,
                    )
            else:
                return SendResult(
                    status=SendStatus.FAILED,
                    error=f"HTTP {response.status_code}",
                    details={"response": response.text[:500]},
                )

        except requests.Timeout:
            return SendResult(
                status=SendStatus.FAILED,
                error="Request timeout",
            )
        except requests.RequestException as e:
            return SendResult(
                status=SendStatus.FAILED,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"发送飞书消息失败: {e}")
            return SendResult(
                status=SendStatus.FAILED,
                error=str(e),
            )


class FeishuCardBuilder:
    """飞书卡片消息构建器

    帮助构建飞书 Interactive Card 格式的消息。
    """

    @staticmethod
    def create_header(
        title: str,
        color: str = "blue",
    ) -> dict[str, Any]:
        """创建卡片头部

        Args:
            title: 标题
            color: 颜色 (blue, green, orange, red, grey, etc.)

        Returns:
            头部配置
        """
        return {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "template": color,
        }

    @staticmethod
    def create_text_element(content: str) -> dict[str, Any]:
        """创建文本元素"""
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": content,
            },
        }

    @staticmethod
    def create_fields(fields: list[tuple[str, str]]) -> dict[str, Any]:
        """创建字段元素

        Args:
            fields: [(label, value), ...] 列表

        Returns:
            字段配置
        """
        return {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{label}**\n{value}",
                    },
                }
                for label, value in fields
            ],
        }

    @staticmethod
    def create_divider() -> dict[str, Any]:
        """创建分割线"""
        return {"tag": "hr"}

    @staticmethod
    def create_note(content: str) -> dict[str, Any]:
        """创建注释"""
        return {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": content,
                }
            ],
        }

    @classmethod
    def create_alert_card(
        cls,
        title: str,
        level: str,
        message: str,
        details: Optional[dict[str, str]] = None,
        suggestion: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建预警卡片

        Args:
            title: 标题
            level: 级别 (red/yellow/green)
            message: 消息内容
            details: 详细信息 {label: value}
            suggestion: 建议操作

        Returns:
            卡片数据
        """
        color_map = {
            "red": "red",
            "yellow": "orange",
            "green": "green",
        }
        color = color_map.get(level, "blue")

        elements = []

        # 消息内容
        elements.append(cls.create_text_element(message))

        # 详细信息
        if details:
            elements.append(cls.create_divider())
            fields = [(k, v) for k, v in details.items()]
            elements.append(cls.create_fields(fields))

        # 建议操作
        if suggestion:
            elements.append(cls.create_divider())
            elements.append(cls.create_text_element(f"💡 **建议操作**: {suggestion}"))

        # 时间戳
        elements.append(cls.create_note(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))

        return {
            "header": cls.create_header(title, color),
            "elements": elements,
        }

    @classmethod
    def create_opportunity_card(
        cls,
        title: str,
        opportunities: list[dict[str, Any]],
        market_status: Optional[str] = None,
        max_opportunities: int = 10,
    ) -> dict[str, Any]:
        """创建机会卡片

        Args:
            title: 标题
            opportunities: 机会列表，每个机会包含详细字段
            market_status: 市场状态描述
            max_opportunities: 最多显示的机会数量（默认 10）

        Returns:
            卡片数据
        """
        elements = []

        # 市场状态
        if market_status:
            elements.append(cls.create_text_element(f"📊 **市场状态**: {market_status}"))
            elements.append(cls.create_divider())

        # 机会列表（详细格式）
        display_opportunities = opportunities[:max_opportunities]
        for i, opp in enumerate(display_opportunities, 1):
            symbol = opp.get("symbol", "N/A")
            strike = opp.get("strike", 0)
            expiry = opp.get("expiry", "N/A")
            dte = opp.get("dte", 0)
            option_type = opp.get("option_type", "put").upper()

            # 标题行：#1 TSLA PUT 485 @ 2026-02-06 (DTE=18)
            # 行权价格式化：整数显示为整数，小数保留小数位
            strike_str = f"{strike:.0f}" if strike == int(strike) else f"{strike}"
            header_text = f"**#{i} {symbol} {option_type} {strike_str} @ {expiry} (DTE={dte})**"
            elements.append(cls.create_text_element(header_text))

            # 核心策略指标行 (P0/P1/P2): Pos, ExpROC, AnnROC, WinP, TGR, Θ/Margin
            # 注意：百分比值存储为小数（如 0.484 表示 48.4%），需要乘 100
            pos = opp.get("recommended_position", 0) or 0
            exp_roc = (opp.get("expected_roc", 0) or 0) * 100
            annual_roc = (opp.get("annual_roc", 0) or 0) * 100
            win_prob = (opp.get("win_probability", 0) or 0) * 100
            tgr = opp.get("tgr", 0) or 0
            theta_margin = opp.get("theta_margin_ratio", 0) or 0  # 资金效率

            core_text = (
                f"📈 Pos={pos:.2f} | ExpROC={exp_roc:.1f}% | "
                f"AnnROC={annual_roc:.1f}% | WinP={win_prob:.1f}% | "
                f"TGR={tgr:.2f} | Θ/Margin={theta_margin:.4f}"
            )
            elements.append(cls.create_text_element(core_text))

            # 参考指标行 (P3): Sharpe, PremRate, SAS, PREI, Kelly, Θ/P
            sharpe = opp.get("sharpe_ratio", 0) or 0
            premium_rate = (opp.get("premium_rate", 0) or 0) * 100
            sas = opp.get("sas", 0) or 0
            prei = opp.get("prei", 0) or 0
            kelly = opp.get("kelly_fraction", 0) or 0
            theta_premium = opp.get("theta_premium_ratio", 0) or 0

            ref_text = (
                f"📊 Sharpe={sharpe:.2f} | PremRate={premium_rate:.2f}% | "
                f"SAS={sas:.1f} | PREI={prei:.1f} | Kelly={kelly:.2f} | Θ/P={theta_premium:.3f}"
            )
            elements.append(cls.create_text_element(ref_text))

            # 行情行：S, Premium, Moneyness, Bid/Ask, Vol, IV
            underlying_price = opp.get("underlying_price", 0) or 0
            mid_price = opp.get("mid_price", 0) or 0
            moneyness = (opp.get("moneyness", 0) or 0) * 100  # 小数转百分比
            bid = opp.get("bid")
            ask = opp.get("ask")
            volume = opp.get("volume")
            iv = (opp.get("iv", 0) or 0) * 100  # 小数转百分比

            bid_str = f"{bid:.2f}" if bid else "N/A"
            ask_str = f"{ask:.2f}" if ask else "N/A"
            vol_str = str(volume) if volume else "N/A"

            market_text = (
                f"💹 S={underlying_price:.2f} | Prem={mid_price:.2f} | "
                f"Moneyness={moneyness:.2f}% | Bid/Ask={bid_str}/{ask_str} | "
                f"Vol={vol_str} | IV={iv:.1f}%"
            )
            elements.append(cls.create_text_element(market_text))

            # Greeks行：Δ, Γ, Θ, V, OI, OTM
            delta = opp.get("delta", 0) or 0
            gamma = opp.get("gamma", 0) or 0
            theta = opp.get("theta", 0) or 0
            vega = opp.get("vega", 0) or 0
            oi = opp.get("open_interest", 0) or 0
            otm_pct = (opp.get("otm_percent", 0) or 0) * 100  # 小数转百分比

            greeks_text = (
                f"🔢 Δ={delta:.3f} | Γ={gamma:.4f} | "
                f"Θ={theta:.3f} | V={vega:.3f} | OI={oi} | OTM={otm_pct:.1f}%"
            )
            elements.append(cls.create_text_element(greeks_text))

            # 警告信息
            warnings = opp.get("warnings", [])
            if warnings:
                for warning in warnings[:2]:  # 最多显示 2 个警告
                    elements.append(cls.create_text_element(f"⚠️ {warning}"))

            # 分隔线（除了最后一个）
            if i < len(display_opportunities):
                elements.append(cls.create_divider())

        elements.append(cls.create_note(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))

        return {
            "header": cls.create_header(title, "green"),
            "elements": elements,
        }

    @classmethod
    def create_monitor_report_card(
        cls,
        title: str,
        status: str,
        alerts: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        """创建监控报告卡片

        Args:
            title: 标题
            status: 状态 (red/yellow/green)
            alerts: 预警列表
            summary: 摘要信息

        Returns:
            卡片数据
        """
        color_map = {
            "red": "red",
            "yellow": "orange",
            "green": "green",
        }
        color = color_map.get(status, "blue")

        elements = []

        # 摘要
        summary_fields = [
            ("总持仓", str(summary.get("total_positions", 0))),
            ("红色预警", str(summary.get("red_alerts", 0))),
            ("黄色预警", str(summary.get("yellow_alerts", 0))),
            ("风险持仓", str(summary.get("positions_at_risk", 0))),
        ]
        elements.append(cls.create_fields(summary_fields))

        # 预警列表
        if alerts:
            elements.append(cls.create_divider())
            elements.append(cls.create_text_element("**预警详情:**"))

            for alert in alerts[:10]:  # 最多显示 10 个
                level = alert.get("level", "yellow")
                message = alert.get("message", "")
                emoji = "🔴" if level == "red" else "🟡" if level == "yellow" else "🟢"
                elements.append(cls.create_text_element(f"{emoji} {message}"))

        elements.append(cls.create_note(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))

        return {
            "header": cls.create_header(title, color),
            "elements": elements,
        }
