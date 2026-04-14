"""Pluggable notification hook for scheduled-task fires.

On every fire completion the service calls ``notifier.notify(schedule, fire)``.
The default implementation logs to stdout and does nothing else. Setting
``SCHEDULED_TASKS_WEBHOOK_URL`` in the environment swaps in a webhook
notifier that POSTs a small JSON payload to the given URL.

Notifications are best-effort: any exception is logged and swallowed so
a broken notification target can never fail a schedule run.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import httpx

_logger = logging.getLogger(__name__)


# Lightweight DTOs — keeping the protocol free of SQLAlchemy so notifiers
# can be unit-tested without a DB.


class NotifyFire:
    def __init__(
        self,
        schedule_id: str,
        schedule_name: str,
        status: str,
        task_id: str | None,
        conversation_id: str | None,
        error: str | None,
        fire_id: str,
    ) -> None:
        self.schedule_id = schedule_id
        self.schedule_name = schedule_name
        self.status = status
        self.task_id = task_id
        self.conversation_id = conversation_id
        self.error = error
        self.fire_id = fire_id

    def to_dict(self) -> dict:
        return {
            'schedule_id': self.schedule_id,
            'schedule_name': self.schedule_name,
            'status': self.status,
            'task_id': self.task_id,
            'conversation_id': self.conversation_id,
            'error': self.error,
            'fire_id': self.fire_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


@runtime_checkable
class Notifier(Protocol):
    async def notify(self, fire: NotifyFire) -> None: ...  # pragma: no cover


class NoopNotifier:
    async def notify(self, fire: NotifyFire) -> None:
        _logger.info(
            'schedule fire: name=%r status=%s task_id=%s error=%s',
            fire.schedule_name,
            fire.status,
            fire.task_id,
            fire.error,
        )


class WebhookNotifier:
    """POST a JSON body to an arbitrary URL on every fire.

    Intended for Slack / DingTalk / feishu incoming webhooks. Failures
    are logged at WARN and swallowed — notification loss must never
    fail the schedule run itself.
    """

    def __init__(self, url: str) -> None:
        self._url = url

    async def notify(self, fire: NotifyFire) -> None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(self._url, json=fire.to_dict())
        except Exception as e:
            _logger.warning(
                'Webhook notify failed for schedule %s: %s',
                fire.schedule_id,
                e,
            )
        # Always also log locally so the host operator has a trail even
        # if the webhook target is down.
        _logger.info(
            'schedule fire: name=%r status=%s task_id=%s (webhook posted)',
            fire.schedule_name,
            fire.status,
            fire.task_id,
        )


def get_notifier() -> Notifier:
    """Return the configured notifier based on environment.

    Called per-fire so a change to ``SCHEDULED_TASKS_WEBHOOK_URL``
    takes effect on the next fire without requiring a restart.
    """
    url = os.environ.get('SCHEDULED_TASKS_WEBHOOK_URL')
    if url:
        return WebhookNotifier(url)
    return NoopNotifier()
