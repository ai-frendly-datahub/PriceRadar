# Canonical Notifier implementation for AI-Friendly DataHub
# Synced from: Radar-Template/radar/notifier.py
# DO NOT MODIFY core classes (Notifier, NotificationPayload, EmailNotifier, WebhookNotifier, CompositeNotifier)
# Domain-specific detection functions (detect_price_notifications) preserved below

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional, Any, Protocol

import requests
import structlog

from priceradar.collectors.base import RawItem

logger = structlog.get_logger(__name__)


@dataclass
class NotificationPayload:
    """Payload for notification delivery."""

    category_name: str
    sources_count: int
    collected_count: int
    matched_count: int
    errors_count: int
    timestamp: datetime
    report_url: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        """Convert payload to dictionary for JSON serialization."""
        return {
            "category_name": self.category_name,
            "sources_count": self.sources_count,
            "collected_count": self.collected_count,
            "matched_count": self.matched_count,
            "errors_count": self.errors_count,
            "timestamp": self.timestamp.isoformat(),
            "report_url": self.report_url,
        }


class Notifier(Protocol):
    """Protocol for notification delivery."""

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification. Return True if successful, False otherwise."""
        ...


class EmailNotifier:
    """Send notifications via email using SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_addr: str,
        to_addrs: list[str],
    ) -> None:
        """Initialize email notifier.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_password: SMTP password
            from_addr: Sender email address
            to_addrs: List of recipient email addresses
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_addr = from_addr
        self.to_addrs = to_addrs

    def send(self, payload: NotificationPayload) -> bool:
        """Send email notification.

        Args:
            payload: Notification payload

        Returns:
            True if successful, False otherwise
        """
        try:
            subject = f"Radar Pipeline Complete: {payload.category_name}"
            body = self._build_email_body(payload)

            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("email_notification_sent", category=payload.category_name)
            return True
        except Exception as e:
            logger.error(
                "email_notification_failed",
                category=payload.category_name,
                error=str(e),
            )
            return False

    def _build_email_body(self, payload: NotificationPayload) -> str:
        """Build email body from payload."""
        lines = [
            f"Radar Pipeline Completion Report",
            f"================================",
            f"",
            f"Category: {payload.category_name}",
            f"Timestamp: {payload.timestamp.isoformat()}",
            f"",
            f"Statistics:",
            f"  Sources: {payload.sources_count}",
            f"  Collected: {payload.collected_count}",
            f"  Matched: {payload.matched_count}",
            f"  Errors: {payload.errors_count}",
        ]
        if payload.report_url:
            lines.append(f"")
            lines.append(f"Report: {payload.report_url}")
        return "\n".join(lines)


class WebhookNotifier:
    """Send notifications via HTTP webhook."""

    def __init__(
        self,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize webhook notifier.

        Args:
            url: Webhook URL
            method: HTTP method (POST or GET)
            headers: Optional HTTP headers
        """
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}

    def send(self, payload: NotificationPayload) -> bool:
        """Send webhook notification.

        Args:
            payload: Notification payload

        Returns:
            True if successful, False otherwise
        """
        try:
            if self.method == "POST":
                response = requests.post(
                    self.url,
                    json=payload.to_dict(),
                    headers=self.headers,
                    timeout=10,
                )
            elif self.method == "GET":
                response = requests.get(
                    self.url,
                    headers=self.headers,
                    timeout=10,
                )
            else:
                logger.error(
                    "webhook_invalid_method",
                    method=self.method,
                    url=self.url,
                )
                return False

            if response.status_code >= 400:
                logger.error(
                    "webhook_notification_failed",
                    url=self.url,
                    status_code=response.status_code,
                )
                return False

            logger.info("webhook_notification_sent", url=self.url)
            return True
        except Exception as e:
            logger.error(
                "webhook_notification_failed",
                url=self.url,
                error=str(e),
            )
            return False


class CompositeNotifier:
    """Send notifications to multiple notifiers."""

    def __init__(self, notifiers: list[object]) -> None:
        """Initialize composite notifier.

        Args:
            notifiers: List of notifiers to send to
        """
        self.notifiers = notifiers

    def send(self, payload: NotificationPayload) -> bool:
        """Send notification to all notifiers.

        Args:
            payload: Notification payload

        Returns:
            True if all notifiers succeeded, False if any failed
        """
        if not self.notifiers:
            return True

        results = []
        for notifier in self.notifiers:
            try:
                result = getattr(notifier, "send")(payload)
                results.append(result)
            except Exception:
                results.append(False)
        return all(results) if results else True


# Domain-specific configuration and event classes (preserved from original)
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


def detect_price_notifications(
    items: list[RawItem],
    *,
    previous_states: dict[str, dict[str, Any]],
    rules: dict[str, Any],
) -> list[NotificationEvent]:
    """Detect price-specific notification events (price drops, discounts, restocks).

    Args:
        items: List of collected raw items
        previous_states: Map of product_id to previous price state
        rules: Notification rules from config/notifications.yaml

    Returns:
        List of notification events to send
    """
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


def _normalize_discount_rate_percent(discount_rate: Optional[float]) -> Optional[float]:
    if discount_rate is None:
        return None
    if discount_rate <= 1:
        return discount_rate * 100.0
    return discount_rate
