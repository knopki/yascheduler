# FILE: yascheduler/adapters/notifier/webhook.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Webhook event handler — sends HTTP notifications for task lifecycle events.
#   SCOPE: webhook_handler async function dispatching webhooks per event type.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-WEBHOOK
#   LINKS: M-DOMAIN-EVENTS, M-NOTIFIER-WEBHOOK
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   webhook_handler - Async handler that sends webhooks for task lifecycle events
#   _send_webhook - Send webhook payload via HTTP POST with retry and rate limiting
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Restore strict D4 signature (http: aiohttp.ClientSession, no | None).
#   PREVIOUS_CHANGE: v1.0.0 - Create webhook handler for domain event dispatch.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from asyncio.locks import Semaphore
from dataclasses import asdict

import aiohttp
import backoff

from yascheduler.domain import (
    DomainEvent,
    TaskAllocated,
    TaskCreated,
    TaskStatus,
)
from yascheduler.webhook import WebhookPayload

logger = logging.getLogger(__name__)

_webhook_sem: Semaphore | None = None


# START_CONTRACT: _get_semaphore
#   PURPOSE: Lazy-initialize module-level concurrency semaphore for webhook requests
#   INPUTS: { None }
#   OUTPUTS: { asyncio.Semaphore - shared semaphore instance (max 10 concurrent) }
#   SIDE_EFFECTS: Creates and stores global _webhook_sem on first call
#   LINKS: M-NOTIFIER-WEBHOOK, fn-webhook_handler
# END_CONTRACT: _get_semaphore
def _get_semaphore() -> Semaphore:
    global _webhook_sem
    if _webhook_sem is None:
        _webhook_sem = Semaphore(10)
    return _webhook_sem


# START_CONTRACT: webhook_handler
#   PURPOSE: Async handler that sends webhooks for task lifecycle events.
#   INPUTS: { event: DomainEvent - domain event with optional webhook_url, http: aiohttp.ClientSession }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Sends HTTP POST via _send_webhook; suppresses final errors after backoff exhausts.
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
# END_CONTRACT: webhook_handler
async def webhook_handler(event: DomainEvent, http: aiohttp.ClientSession) -> None:
    if event.webhook_url is None:
        return

    if isinstance(event, TaskCreated):
        status = TaskStatus.TO_DO
    elif isinstance(event, TaskAllocated):
        status = TaskStatus.RUNNING
    else:
        status = TaskStatus.DONE

    payload = WebhookPayload(
        task_id=event.task_id,
        status=status.value,
        custom_params=event.webhook_custom_params,
    )
    try:
        await _send_webhook(event.webhook_url, payload, http)
    except aiohttp.ClientError:
        logger.exception(
            "[NotifierWebhook][webhook_handler][GIVEUP] %s", event.webhook_url
        )


# START_CONTRACT: _send_webhook
#   PURPOSE: Send webhook payload via HTTP POST with retry and rate limiting.
#   INPUTS: { url: str, payload: WebhookPayload, http: aiohttp.ClientSession }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Sends HTTP POST to url; logs warning on non-ok response.
#   RAISES: aiohttp.ClientError — propagated for backoff retry.
#   LINKS: M-WEBHOOK
# END_CONTRACT: _send_webhook
@backoff.on_exception(backoff.fibo, aiohttp.ClientError, max_time=60)
async def _send_webhook(
    url: str, payload: WebhookPayload, http: aiohttp.ClientSession
) -> None:
    async with _get_semaphore():
        try:
            async with http.post(url, data=asdict(payload)) as resp:
                if resp.ok:
                    return
                raise aiohttp.ClientError(f"HTTP {resp.status}: {await resp.text()}")
        except aiohttp.ClientError:
            logger.warning("[NotifierWebhook][_send_webhook][RETRY] %s", url)
            raise
