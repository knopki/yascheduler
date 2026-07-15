"""Webhook event handler and outbound payload DTO — sends HTTP notifications for task lifecycle events."""
# FILE: yascheduler/infra/notifier/webhook.py
# VERSION: 1.4.1
# START_MODULE_CONTRACT
#   PURPOSE: Webhook event handler and outbound payload DTO — sends HTTP notifications for task lifecycle events.
#   SCOPE: WebhookPayload frozen dataclass, webhook_handler async function, _send_webhook retry helper.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-EVENTS, M-NOTIFIER-WEBHOOK
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   webhook_handler - Async handler that sends webhooks for task lifecycle events
#   _send_webhook - Send webhook payload via HTTP POST with retry and rate limiting
#   WebhookPayload - Webhook request data shape
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.4.1 - Replace module-global _webhook_sem lazy-init with @lru_cache on _get_semaphore (removes PLW0603 noqa); behavior unchanged.
#   PREVIOUS_CHANGE: v1.4.0 - Mark the HTTP-status raise inside _send_webhook try as noqa: TRY301 — intentional: the except below logs every backoff retry for BOTH network failures and HTTP-status errors.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from asyncio.locks import Semaphore
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import aiohttp
import backoff

from yascheduler.domain import (
    DomainEvent,
    TaskAllocated,
    TaskCreated,
    TaskStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookPayload:
    """Payload dataclass for webhook event dispatch."""

    task_id: int = field()
    status: int = field()
    custom_params: Mapping[str, Any] = field(default_factory=dict)


# START_CONTRACT: webhook_handler
#   PURPOSE: Async handler that sends webhooks for task lifecycle events.
#   INPUTS: { event: DomainEvent - domain event (event.task_id is a TaskId) with optional webhook_url, http: aiohttp.ClientSession }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Sends HTTP POST via _send_webhook (body built via asdict(WebhookPayload(task_id=event.task_id.value, ...))); suppresses final errors after backoff exhausts.
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
# END_CONTRACT: webhook_handler
@lru_cache(maxsize=1)
def _get_semaphore() -> Semaphore:
    """Return the process-wide webhook concurrency semaphore (lazy-init).

    Created lazily on first call so it binds to the running event loop.
    """
    return Semaphore(10)


async def webhook_handler(event: DomainEvent, http: aiohttp.ClientSession) -> None:
    """Async handler that sends webhooks for task lifecycle events."""
    if event.webhook_url is None:
        return

    if isinstance(event, TaskCreated):
        status = TaskStatus.TO_DO
    elif isinstance(event, TaskAllocated):
        status = TaskStatus.RUNNING
    else:
        status = TaskStatus.DONE

    payload = WebhookPayload(
        task_id=event.task_id.value,
        status=status.value,
        custom_params=event.webhook_custom_params,
    )
    try:
        await _send_webhook(event.webhook_url, payload, http)
    except aiohttp.ClientError:
        logger.exception("webhook giveup: %s", event.webhook_url)


# START_CONTRACT: _send_webhook
#   PURPOSE: Send webhook payload via HTTP POST with retry and rate limiting.
#   INPUTS: { url: str, payload: WebhookPayload, http: aiohttp.ClientSession }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Sends HTTP POST to url; logs warning on non-ok response.
#   RAISES: aiohttp.ClientError — propagated for backoff retry.
#   LINKS: M-NOTIFIER-WEBHOOK
# END_CONTRACT: _send_webhook
@backoff.on_exception(backoff.fibo, aiohttp.ClientError, max_time=60)
async def _send_webhook(
    url: str,
    payload: WebhookPayload,
    http: aiohttp.ClientSession,
) -> None:
    async with _get_semaphore():
        try:
            async with http.post(url, data=asdict(payload)) as resp:
                if resp.ok:
                    return
                # Raised inside the try so the except below logs every retry
                # for BOTH error sources (network failure and HTTP status).
                msg = f"HTTP {resp.status}: {await resp.text()}"
                raise aiohttp.ClientError(msg)  # noqa: TRY301
        except aiohttp.ClientError:
            logger.debug("RETRY", extra={"url": url})
            logger.warning("webhook retry to %s", url)
            raise
