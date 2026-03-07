from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Any

import requests

from priceradar.collectors.base import RawItem


@dataclass
class NotificationConfig:
    enabled: bool
    channels: list[str]
    email_settings: dict[str, Any] = field(default_factory=dict)
    webhook_url: str = ""
    telegram_config: dict[str, str] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationEvent:
    title: str
    message: str
    priority: str
    event_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Notifier:
    def __init__(self, config: NotificationConfig):
        self.config = config

    def send(
        self,
        title: str,
        message: str,
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.config.enabled:
            return

        payload = {
            "title": title,
            "message": message,
            "priority": priority,
            "metadata": metadata or {},
        }
        channels = {channel.strip().lower() for channel in self.config.channels}

        if "email" in channels:
            self._send_email(payload)
        if "webhook" in channels:
            self._send_webhook(payload)
        if "telegram" in channels:
            self._send_telegram(payload)

    def _send_email(self, payload: dict[str, Any]) -> None:
        settings = self.config.email_settings
        smtp_host = str(settings.get("smtp_host", "")).strip()
        smtp_port = int(settings.get("smtp_port", 587) or 587)
        from_address = str(settings.get("from_address", "")).strip()
        to_addresses = settings.get("to_addresses", [])
        username = str(settings.get("username", "")).strip()
        password = str(settings.get("password", "")).strip()

        if (
            not smtp_host
            or not from_address
            or not isinstance(to_addresses, list)
            or not to_addresses
        ):
            return

        msg = MIMEText(str(payload["message"]), "plain", "utf-8")
        msg["Subject"] = str(payload["title"])
        msg["From"] = from_address
        msg["To"] = ", ".join(str(addr) for addr in to_addresses)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)

    def _send_webhook(self, payload: dict[str, Any]) -> None:
        if not self.config.webhook_url:
            return
        requests.post(self.config.webhook_url, json=payload, timeout=10)

    def _send_telegram(self, payload: dict[str, Any]) -> None:
        token = self.config.telegram_config.get("bot_token", "")
        chat_id = self.config.telegram_config.get("chat_id", "")
        if not token or not chat_id:
            return

        text = f"[{payload['priority'].upper()}] {payload['title']}\n{payload['message']}"
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )


def detect_price_notifications(
    items: list[RawItem],
    *,
    previous_states: dict[str, dict[str, Any]],
    rules: dict[str, Any],
) -> list[NotificationEvent]:
    events: list[NotificationEvent] = []

    lowest_drop_pct = float(rules.get("lowest_price_drop_percent", 0.0))
    discount_threshold = float(rules.get("discount_rate_percent", 50.0))

    for item in items:
        state = previous_states.get(item.product_id, {})
        previous_min_price = state.get("min_price")
        previous_last_price = state.get("last_price")

        if item.current_price is not None and previous_min_price is not None:
            if item.current_price < previous_min_price:
                drop_pct = ((previous_min_price - item.current_price) / previous_min_price) * 100.0
                if drop_pct >= lowest_drop_pct:
                    events.append(
                        NotificationEvent(
                            title=f"[PriceRadar] 최저가 갱신: {item.title}",
                            message=(
                                f"이전 최저가 {int(previous_min_price):,}원 -> "
                                f"신규 최저가 {int(item.current_price):,}원 ({drop_pct:.1f}% 하락)\n"
                                f"URL: {item.url}"
                            ),
                            priority="high",
                            event_type="new_lowest_price",
                            metadata={"product_id": item.product_id, "drop_pct": drop_pct},
                        )
                    )

        normalized_discount_rate = _normalize_discount_rate_percent(item.discount_rate)
        if normalized_discount_rate is not None and normalized_discount_rate >= discount_threshold:
            events.append(
                NotificationEvent(
                    title=f"[PriceRadar] 고할인 감지: {item.title}",
                    message=(
                        f"할인율 {normalized_discount_rate:.1f}% 감지 (기준 {discount_threshold:.1f}% 이상)\n"
                        f"현재가: {item.current_price if item.current_price is not None else '미상'}\n"
                        f"URL: {item.url}"
                    ),
                    priority="high",
                    event_type="high_discount",
                    metadata={
                        "product_id": item.product_id,
                        "discount_rate_percent": normalized_discount_rate,
                    },
                )
            )

        previous_available = previous_last_price is not None and previous_last_price > 0
        current_available = item.current_price is not None and item.current_price > 0
        if not previous_available and current_available:
            events.append(
                NotificationEvent(
                    title=f"[PriceRadar] 재입고 감지: {item.title}",
                    message=f"품절 상태에서 재입고로 전환되었습니다.\nURL: {item.url}",
                    priority="normal",
                    event_type="restock",
                    metadata={"product_id": item.product_id},
                )
            )

    return events


def _normalize_discount_rate_percent(discount_rate: float | None) -> float | None:
    if discount_rate is None:
        return None
    if discount_rate <= 1:
        return discount_rate * 100.0
    return discount_rate
