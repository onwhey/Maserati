"""Notification channels.

Module: Notifications
Responsibility: send already-created notification attempts through configured channels.
Not responsible for creating business facts, trading, Binance, DeepSeek, or Hermes inbound commands.
Database: not accessed here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryResponse:
    success: bool
    provider_message_id: str = ""
    http_status: int | None = None
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False


class NotificationChannel:
    def send(self, *, title: str, body: str, idempotency_key: str) -> DeliveryResponse:
        raise NotImplementedError


class DisabledNotificationChannel(NotificationChannel):
    def send(self, *, title: str, body: str, idempotency_key: str) -> DeliveryResponse:
        return DeliveryResponse(success=False, error_code="channel_disabled", error_message="通知渠道未启用", retryable=False)


class InMemorySuccessChannel(NotificationChannel):
    def send(self, *, title: str, body: str, idempotency_key: str) -> DeliveryResponse:
        return DeliveryResponse(success=True, provider_message_id=idempotency_key)

